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
FORMAT = 2
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
    return {"pins": pins, "sequential": sequential}


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


SIGNAL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
NOT_A_SIGNAL = {"1", "0"}


def pin_of(expression):
    """The single pin an expression names, or None if it is anything else.

    `clear : "!RESET_B"` and `clocked_on : "CLK"` both reduce to one pin, which
    is all stage 3 needs; the leading `!` is the pin's active level, recorded
    separately. An expression naming more than one pin is not reduced, because
    guessing which of them matters is how a wrong netlist gets built.
    """
    if not expression:
        return None, None
    names = [n for n in SIGNAL.findall(expression) if n not in NOT_A_SIGNAL]
    if len(set(names)) != 1:
        return None, None
    return names[0], "low" if expression.strip().startswith("!") else "high"
