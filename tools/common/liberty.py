"""What each cell computes, from the PDK's own liberty data.

Stage 3 has to say which net is a clock, which is a reset, which carries data.
An earlier version of it derived that from the LEF's `USE CLOCK` marker plus the
cell's name, and both sources are weaker than they look.

`USE CLOCK` is a statement about how a pin should be routed, not about what it
does. The library proves it: `lpflow_inputisolatch_1` marks `SLEEP_B` as
`USE CLOCK`, and `SLEEP_B` is a power gating control.

The cell name is not an independent second opinion either. `RESET_B` on a pin
and `dfrtp` in the cell name are two expressions of one naming convention,
written by the same people at the same time. If the convention were misapplied,
both would be wrong together.

Liberty says it functionally, and this is the authority stage 3 uses:

    ff (IQ, IQ_N) { clocked_on : CLK;  next_state : D;  clear : !RESET_B; }
    pin (Y)       { function : "(!A) | (!B)"; }

This library ships liberty as per cell, per corner JSON rather than as `.lib`
text, so this reads that JSON directly. One corner is cached; corners differ in
timing tables and agree on every functional attribute, and nothing here reads
timing.

The `function` expressions are kept as well as the sequential attributes. A
netlist of blackboxes can be walked as a graph but cannot be exported to SMT2 or
CNF, and stages 4 and 6 need exactly that.
"""

import glob
import json
import os
import re

CORNER = "tt_025C_1v80"
SUFFIX = f"__{CORNER}.lib.json"

# Bumped whenever `parse` changes what it extracts, so a stale distilled cache
# is rebuilt rather than believed.
FORMAT = 3
CACHE = "_liberty_functions.json"

# Liberty writes a group as "ff,IQ,IQ_N" or "latch,IQ,IQ_N" once flattened into
# JSON keys, and a pin as "pin,NAME".
GROUP = re.compile(r"^(ff|latch)(?:,|$)")
PIN = re.compile(r"^pin,(.+)$")


def boolean(value):
    """A liberty boolean, which arrives as the *string* 'true' or 'false'.

    Worth its own function and its own name. `bool(value)` on the raw field is
    true for both, because 'false' is a non-empty string, and the result is that
    every input pin of every combinational cell reads as a clock. That is a
    silent defect: the netlist stays valid, and only the clock annotations are
    nonsense. Caught by cross-checking against the LEF's own clock marking,
    which flagged 414 cells rather than the handful that genuinely differ.
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def parse(text):
    """One cell's liberty JSON to the subset that says what the cell does."""
    raw = json.loads(text)
    pins, sequential = {}, None

    for key, value in raw.items():
        match = PIN.match(key)
        if match:
            pins[match.group(1)] = {
                "direction": value.get("direction"),
                "function": value.get("function"),
                # Liberty states this functionally, unlike the LEF's USE CLOCK:
                # it means "this pin clocks the state element".
                "clock": boolean(value.get("clock", False)),
            }
            continue
        group = GROUP.match(key)
        if group:
            sequential = {
                "kind": group.group(1),
                "clocked_on": value.get("clocked_on") or value.get("enable"),
                "next_state": value.get("next_state") or value.get("data_in"),
                "clear": value.get("clear"),
                "preset": value.get("preset"),
                "state": key.split(",")[1:],
            }
    # Area is kept because synthesis needs it: the mapper chooses between cells
    # that compute the same function by cost, and without an area it has no
    # reason to prefer a small gate over a large one.
    return {"pins": pins, "sequential": sequential,
            "area": raw.get("area")}


def load(directory, rebuild=False):
    """Cell name -> {'pins': {...}, 'sequential': {...} or None}.

    The source is 17 MB of JSON that is almost entirely timing tables, and
    reading it takes half a minute, so the distilled result is cached beside it.
    The cache is keyed on the source file names and sizes plus FORMAT, so
    changing the library or changing what `parse` extracts both invalidate it.
    Guessing that a cache is still good is not cheaper than checking.
    """
    paths = sorted(glob.glob(os.path.join(directory, f"*{SUFFIX}")))
    stamp = {"format": FORMAT,
             "sources": [[os.path.basename(p), os.path.getsize(p)]
                         for p in paths]}

    cache_path = os.path.join(directory, CACHE)
    if not rebuild and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as handle:
                cached = json.load(handle)
            if cached.get("stamp") == stamp:
                return cached["cells"]
        except (ValueError, KeyError):
            pass

    library = {}
    for path in paths:
        name = os.path.basename(path)[: -len(SUFFIX)]
        with open(path, encoding="utf-8") as handle:
            library[name] = parse(handle.read())

    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump({"stamp": stamp, "cells": library}, handle)
    return library


# Cell families a low power flow brings and this design's flow did not. The
# puzzle instantiates none of them, and offering them to the mapper would build
# a corpus out of a vocabulary the target never used -- which is the one thing
# `docs/solver-pipeline.md` asks stage 5 to avoid.
#
# This is deliberately an exclusion by *design intent*, not by drive strength or
# by "what the puzzle happens to contain". Narrowing to exactly the puzzle's 67
# cell types would tune the test set to the target and make the detector scores
# meaningless.
EXCLUDED_FAMILIES = ("lpflow_",)


def write_lib(library, path, cells=None):
    """Emit a minimal liberty text file, which is what Yosys can actually read.

    Yosys maps logic onto a cell library through `abc -liberty` and
    `dfflibmap -liberty`, and both want liberty *text*. This PDK publishes
    liberty as per cell, per corner JSON instead, so the text has to be
    reconstructed.

    Only what a mapper uses is written: area, pin directions, output functions,
    and the sequential group. Everything else in the source is timing and power
    characterisation, which nothing in this pipeline reads.

    This file is what lets stage 5 synthesise the corpus through the same cell
    vocabulary the puzzle uses. Without it the corpus would be built from
    generic gates and would not resemble what the detectors have to work on.
    """
    names = sorted(cells if cells is not None else library)
    names = [n for n in names
             if not any(f in n for f in EXCLUDED_FAMILIES)]
    lines = ['library(sky130_fd_sc_hd) {',
             '  delay_model : table_lookup;',
             '  time_unit : "1ns";',
             '  voltage_unit : "1V";',
             '  current_unit : "1mA";',
             '  capacitive_load_unit(1, pf);']
    written = 0
    for name in names:
        entry = library.get(name)
        if entry is None:
            continue
        outputs = {p: i for p, i in entry["pins"].items()
                   if i["direction"] == "output"}
        # A cell with no output function is one a mapper cannot use. Physical
        # only cells -- fill, tap, decap -- are exactly that, and are skipped
        # rather than emitted as something the mapper might try to pick.
        if not outputs or not all(i["function"] for i in outputs.values()):
            continue
        lines.append(f'  cell({name}) {{')
        lines.append(f'    area : {entry.get("area") or 1.0};')
        state = entry["sequential"]
        if state:
            group = ",".join(state["state"]) or "IQ,IQ_N"
            lines.append(f'    {state["kind"]}({group}) {{')
            for field in ("clocked_on", "next_state", "clear", "preset"):
                if state.get(field):
                    lines.append(f'      {field} : "{state[field]}";')
            lines.append('    }')
        for pin, info in sorted(entry["pins"].items()):
            lines.append(f'    pin({pin}) {{')
            lines.append(f'      direction : {info["direction"]};')
            if info["clock"]:
                lines.append('      clock : true;')
            if info["function"]:
                lines.append(f'      function : "{info["function"]}";')
            lines.append('    }')
        lines.append('  }')
        written += 1
    lines.append('}')

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return written


SIGNAL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NOT_A_SIGNAL = {"1", "0"}


def unwrap(expression):
    """An expression with its enclosing parentheses removed, if it has any.

    Only *enclosing* ones: `(A)&(B)` is returned unchanged, because its leading
    bracket closes before the end. Written naively this would strip the two
    outer characters off `(A)|(B)` and hand back `A)|(B`.
    """
    text = (expression or "").strip()
    while text.startswith("(") and text.endswith(")"):
        depth, closes_at = 0, len(text) - 1
        for index, character in enumerate(text):
            depth += (character == "(") - (character == ")")
            if depth == 0:
                closes_at = index
                break
        if closes_at != len(text) - 1:
            break
        text = text[1:-1].strip()
    return text


def pin_of(expression):
    """The single pin an expression names, or None if it is anything else.

    `clear : "!RESET_B"` and `clocked_on : "CLK"` both reduce to one pin, which
    is all stage 3 needs; the leading `!` is the pin's active level, recorded
    separately. An expression naming more than one pin is not reduced, because
    guessing which of them matters is how a wrong netlist gets built.

    The level is read *after* unwrapping. This library writes a combinational
    output as `function : "(!A)"`, parenthesised, while it writes the sequential
    fields bare -- so testing the raw first character for `!` gets `clear` right
    and reports all 21 of the library's inverters as non-inverting. The clock
    root walk in stage 3 then traces through an inverter and calls the path
    straight, which is silent: the root is still correct and only the parity is
    wrong. Caught by asking why no corpus circuit could ever put a flop on an
    inverting clock path, and finding that none could be *reported*.
    """
    if not expression:
        return None, None
    names = [n for n in SIGNAL.findall(expression) if n not in NOT_A_SIGNAL]
    if len(set(names)) != 1:
        return None, None
    return names[0], "low" if unwrap(expression).startswith("!") else "high"
