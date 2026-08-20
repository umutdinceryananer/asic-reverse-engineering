"""Stage 3, normalisation. A gate level netlist to an annotated graph.

Input.  `out/<target>/netlist.v` from stage 2.
Output. `out/<target>/graph.json`, and `out/<target>/graph.v` written back out
        of the graph so the round trip can be simulated.

Stage 2 produced a netlist that is correct and unreadable: 738 boxes and 723
wires, none of whose names mean anything. This stage does not try to understand
it. It attaches the structural facts that later stages need in order to look for
patterns, and nothing that requires a guess.

What gets derived, following `docs/solver-pipeline.md`:

  - clock nets, from fanout into pins the LEF declares USE CLOCK
  - reset and set nets, the same way
  - a flip flop inventory: clock, reset, set, data source, and where an enable
    is implemented in logic rather than by a pin, which mux does it
  - primary inputs and outputs
  - constant nets, from the cells that generate constants
  - combinational cone membership per net

Yosys does the reading. It is the standard tool, it will be needed again in
stages 4 and 6 for the SMT2 and CNF exports, and hand-parsing Verilog to save a
container is a trade nobody wins.

What Yosys is *not* asked to do is infer the cells. Their interfaces come from a
blackbox library generated here from the PDK's own LEF, so the pin directions in
the graph are the same ones stage 2 emitted the netlist with, from the same
source. The alternative, reading the behavioural cell models, would make this
stage depend on those models parsing under a second tool for no gain.

Verification is a round trip: the graph is written back to Verilog and has to
pass stage 2's simulation unchanged.

Usage:
    python tools/stage3_graph.py warmup
    python tools/sim/run.py warmup --netlist out/warmup/graph.v
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import boolexpr, liberty
from common.lef import functional_pins, load as load_lef
from stage1_cells import PDK_DIR, TARGETS

IMAGE = "gds-teardown-eda:latest"

# Pin roles come from liberty, which states them functionally:
#
#     ff (IQ, IQ_N) { clocked_on : CLK;  next_state : D;  clear : !RESET_B; }
#
# An earlier version derived them from the LEF's USE CLOCK marker plus the cell
# name. Measured against liberty afterwards, the two sources score differently.
# USE CLOCK turned out to agree with liberty's `clock` on all 429 cells in this
# library, so that half was sound. The cell name was not: `dfbbp_1` and five
# others carry both RESET_B and SET_B, and no reading of `dfr` against `dfs`
# survives that. Reset and set are read from `clear` and `preset`.
#
# The name is still consulted, as a cross check that reports rather than
# decides. Two sources agreeing is worth something; one source and a habit is
# not.
CELL_NAME_MARK = {"reset": "r", "set": "s"}

BUS_BIT = re.compile(r"^(?P<base>.+)\[(?P<index>\d+)\]$")


def selecting_mux(function):
    """(select pin, {leg pin: the level that passes it}) for a 2:1 mux, or None.

    Read out of the cell's liberty function by cofactor, never off its name.
    The name test this replaced was `"mux2" in cell`, which also matches
    `mux2i` -- and `mux2i` is an *inverting* mux:

        mux2   X = (A0&!S) | (A1&S)          passes A0, then A1
        mux2i  Y = (!A0&!S) | (!A1&S)        passes !A0, then !A1

    A flop whose D comes from a `mux2i` with its own Q on a leg does not hold.
    It toggles. Reporting that as a hold is wrong in the one direction that
    matters, because every later stage treats a hold as "this register can keep
    its value" and would build on a register that inverts every cycle instead.

    The test is therefore functional: for some pin S, the function with S=0 must
    be *identically some other pin*, positively, and the function with S=1 must
    be identically a third. `mux2i` fails it because its cofactors are `!A0` and
    `!A1`. Anything else in the library computing a non-inverting select passes
    it, whatever it is called.

    `tools/stage3_crosscheck.py` applies the same rule by a different route, and
    a witness netlist in the corpus holds a `mux2i` in front of a D so that the
    rule has something it can be seen to reject.
    """
    if not function:
        return None
    tree = boolexpr.parse(function)
    names = sorted(tree.inputs)
    if len(names) != 3:
        return None

    def cofactor_is(select, value, target):
        others = [n for n in names if n != select]
        for pattern in range(1 << len(others)):
            values = {n: (pattern >> i) & 1 for i, n in enumerate(others)}
            values[select] = value
            if boolexpr.evaluate(tree, values) != values[target]:
                return False
        return True

    for select in names:
        low, high = [n for n in names if n != select]
        for a, b in ((low, high), (high, low)):
            if cofactor_is(select, 0, a) and cofactor_is(select, 1, b):
                return select, {a: "low", b: "high"}
    return None


def blackbox_library(cells, lef, path, lib=None):
    """Verilog interfaces for every cell the netlist instantiates.

    Supply pins are left out, exactly as stage 2 left them out of the netlist:
    the sky130 models only expose them under USE_POWER_PINS and the reference
    netlist omits them too.

    When `lib` is given, clock inputs are marked `clkbuf_sink`. Yosys's
    `clkbufmap` inserts clock buffers by looking for that attribute, and cells
    that arrive through `dfflibmap` and `abc` do not carry it -- which is why
    stage 5's first attempt at building a clock tree silently inserted nothing.
    Which pins are clocks comes from liberty, the same authority stage 3 uses
    everywhere else.
    """
    lines = ["// Generated by tools/stage3_graph.py from the PDK LEF.",
             "// Interfaces only: stage 3 reasons about connectivity, and the",
             "// behaviour of these cells is stage 2's simulation to check.",
             ""]
    for cell in sorted(cells):
        if cell not in lef:
            sys.exit(f"{cell} instantiated but absent from the LEF library")
        pins = functional_pins(lef[cell])
        clocks = {pin for pin, info in (lib or {}).get(cell, {"pins": {}})["pins"].items()
                  if info.get("clock")}
        lines.append("(* blackbox *)")
        lines.append(f"module {cell} ({', '.join(sorted(pins))});")
        for pin, direction in sorted(pins.items()):
            mark = "(* clkbuf_sink *) " if pin in clocks else ""
            lines.append(f"  {mark}{direction} {pin};")
        lines.append("endmodule")
        lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return len(cells)


def run_yosys(netlist, blackbox, out_json, top):
    """Read the netlist under its blackbox library and dump Yosys's own JSON.

    `check` runs without `-assert`, and its findings are printed by the caller
    instead. An independent tool's opinion of the netlist is worth having in
    full; aborting on the first complaint would hide the rest of the list, and
    some of what it flags -- an output that drives nothing, for one -- is a real
    property of this design rather than a defect.
    """
    script = "; ".join([
        f"read_verilog -lib {blackbox}",
        f"read_verilog {netlist}",
        f"hierarchy -check -top {top}",
        "check",
        "stat",
        f"write_json {out_json}",
    ])
    result = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{os.path.abspath('.')}:/work",
         "-w", "/work", IMAGE, "yosys", "-p", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:])
        sys.exit("yosys failed")
    return result.stdout


def bit_key(bit):
    """Yosys writes a net as an integer and a constant as '0', '1', 'x', 'z'."""
    return f"const:{bit}" if isinstance(bit, str) else f"n{bit}"


def pass_through(cell_type, lib, pins):
    """A cell that carries one input to one output, possibly inverting it.

    Read from liberty's function expression, never from the cell's name. The
    puzzle's clock tree is `clkbuf`, its data paths hold `inv` and one `buf`,
    the corpus's mapper prefers `clkinv` for the same job, and a library is free
    to name a buffer anything at all. What makes a cell transparent is that its
    output is its input.

    Returns {"input", "output", "inverting"} or None. `diode` drives no output
    and is not transparent; `conb_1` drives a constant, not an input; `and2` has
    two inputs and is not transparent.
    """
    entry = lib.get(cell_type)
    if not entry or entry["sequential"]:
        return None
    driven = [(pin, info["function"]) for pin, info in entry["pins"].items()
              if info.get("function")]
    if len(driven) != 1:
        return None
    output, expression = driven[0]
    source, level = liberty.pin_of(expression)
    if source is None or level is None:
        return None
    # The named pin must be the cell's *only* input. Without this an `and2`
    # whose function happened to mention one pin would look transparent.
    if [pin for pin, direction in pins.items() if direction == "input"] != [source]:
        return None
    return {"input": source, "output": output, "inverting": level == "low"}


def trace_root(net, driver_of, cells, transparent):
    """Walk back through transparent cells to where a signal originates.

    Bits of one register do not share a clock net: the puzzle's 92 flip flops
    sit on 16 `clkbuf_8` branches, so grouping them by the net their CLK pin
    reaches splits every register into sixteen pieces. They do share a clock
    *root*, which is what this finds.

    Returns (root net, whether the path inverts, how many cells it crossed).
    Inversion is carried because a clock reaching a flop through an odd number
    of inverters is a falling edge flop, and a reset through one is active high.
    """
    seen, inverting, hops = set(), False, 0
    while net not in seen:
        seen.add(net)
        source = driver_of.get(net)
        if source is None:
            break
        info = transparent.get(source["cell"])
        if info is None or source["pin"] != info["output"]:
            break
        bits = cells[source["instance"]]["connections"].get(info["input"])
        if not bits or len(bits) != 1:
            break
        net, hops = bit_key(bits[0]), hops + 1
        inverting ^= info["inverting"]
    return net, inverting, hops


def build_graph(design, top, lef, lib):
    module = design["modules"][top]
    cells = module["cells"]
    used = {c["type"] for c in cells.values()}

    # Pin directions come from the LEF, the same source stage 2 emitted the
    # netlist from, rather than from Yosys's view of a blackbox. One authority
    # for a fact, and the whole netlist already depends on this one. Liberty
    # states directions too, so the two are compared and any disagreement is
    # reported instead of one being picked.
    pins_of = {cell_type: functional_pins(lef[cell_type]) for cell_type in used}
    direction_clashes = []
    for cell_type in sorted(used):
        entry = lib.get(cell_type)
        if not entry:
            continue
        for pin, direction in sorted(pins_of[cell_type].items()):
            other = entry["pins"].get(pin, {}).get("direction")
            if other and other != direction:
                direction_clashes.append((cell_type, pin, direction, other))

    # --- nets and the pins on them ------------------------------------------
    net_pins = defaultdict(list)
    for instance, cell in cells.items():
        directions = pins_of[cell["type"]]
        for pin, bits in cell["connections"].items():
            for index, bit in enumerate(bits):
                net_pins[bit_key(bit)].append({
                    "instance": instance,
                    "cell": cell["type"],
                    "pin": pin if len(bits) == 1 else f"{pin}[{index}]",
                    "direction": directions.get(pin, "input"),
                })

    port_of = {}
    for name, port in module["ports"].items():
        for index, bit in enumerate(port["bits"]):
            port_of[bit_key(bit)] = {
                "port": name if len(port["bits"]) == 1 else f"{name}[{index}]",
                "direction": port["direction"],
            }

    names = {}
    for name, entry in module.get("netnames", {}).items():
        if entry.get("hide_name"):
            continue
        for index, bit in enumerate(entry["bits"]):
            names.setdefault(bit_key(bit),
                             name if len(entry["bits"]) == 1
                             else f"{name}[{index}]")

    # --- roles, as liberty states them --------------------------------------
    roles_of = {}
    for cell_type in sorted(used):
        entry = lib.get(cell_type)
        if not entry or not entry["sequential"]:
            continue
        state = entry["sequential"]
        clock, _ = liberty.pin_of(state["clocked_on"])
        data, _ = liberty.pin_of(state["next_state"])
        reset, reset_level = liberty.pin_of(state["clear"])
        preset, preset_level = liberty.pin_of(state["preset"])
        outputs = [p for p, d in pins_of[cell_type].items() if d == "output"]
        if clock is None or data is None or len(outputs) != 1:
            sys.exit(f"{cell_type} is sequential but its liberty entry does not "
                     f"reduce to one clock, one data pin and one output: "
                     f"{state}; add a rule rather than guessing")
        roles_of[cell_type] = {
            "kind": state["kind"], "clock": clock, "data": data,
            "q": outputs[0], "reset": reset, "reset_level": reset_level,
            "set": preset, "set_level": preset_level,
        }

    # Cross check against the naming convention. Not the authority -- six cells
    # in this library carry both RESET_B and SET_B and no name reading survives
    # that -- but a disagreement between the two is worth seeing.
    name_clashes = []
    for cell_type, roles in sorted(roles_of.items()):
        short = cell_type.split("__")[-1].split("_")[0]
        for kind in ("reset", "set"):
            present = roles[kind] is not None
            says = CELL_NAME_MARK[kind] in short[2:] or "bb" in short
            if present != says:
                name_clashes.append((cell_type, kind, present, says))

    clock_nets, reset_nets, set_nets = set(), set(), set()
    flipflops = {}
    for instance, cell in sorted(cells.items()):
        roles = roles_of.get(cell["type"])
        if roles is None:
            continue
        record = {"cell": cell["type"], "kind": roles["kind"]}
        for role in ("clock", "data", "q", "reset", "set"):
            pin = roles[role]
            bits = cell["connections"].get(pin) if pin else None
            record[role] = bit_key(bits[0]) if bits else None
        record["reset_level"] = roles["reset_level"]
        record["set_level"] = roles["set_level"]

        clock_nets.add(record["clock"])
        if record["reset"]:
            reset_nets.add(record["reset"])
        if record["set"]:
            set_nets.add(record["set"])
        flipflops[instance] = record

    driver_of = {}
    for net, pins in net_pins.items():
        for pin in pins:
            if pin["direction"] == "output":
                driver_of[net] = pin

    # --- roots, past the buffers ---------------------------------------------
    #
    # Which nets are one signal distributed, rather than several signals. The
    # rule this exists for is that flip flops of one register share a clock
    # root and not a clock net.
    transparent = {}
    for cell_type in sorted(used):
        info = pass_through(cell_type, lib, pins_of[cell_type])
        if info:
            transparent[cell_type] = info

    net_roots = {}
    for net in net_pins:
        root, inverting, hops = trace_root(net, driver_of, cells, transparent)
        if hops:
            net_roots[net] = {"root": root, "inverting": inverting, "hops": hops}

    def root_of(net):
        return net_roots.get(net, {}).get("root", net) if net else None

    for record in flipflops.values():
        for role in ("clock", "reset", "set"):
            record[f"{role}_root"] = root_of(record[role])
            entry = net_roots.get(record[role]) if record[role] else None
            record[f"{role}_inverted"] = bool(entry and entry["inverting"])

    grouped = {}
    for role, nets in (("clock", clock_nets), ("reset", reset_nets),
                       ("set", set_nets)):
        by_root = defaultdict(list)
        for instance, record in sorted(flipflops.items()):
            if record[role]:
                by_root[record[f"{role}_root"]].append(instance)
        grouped[role] = {root: sorted(members)
                         for root, members in sorted(by_root.items())}

    # --- an enable implemented in logic rather than by a pin -----------------
    #
    # None of the sequential cells in this library carry an enable, so a held
    # register can be built as a mux in front of D with the flop's own Q on one
    # leg. That is a structural fact, not an interpretation, so it belongs here.
    #
    # Which cells are that mux comes from `selecting_mux`, which reads the
    # liberty function. The test used to be `"mux2" in the cell name`, and that
    # also matches `mux2i`, whose output is inverted: a flop fed by one with its
    # own Q on a leg toggles rather than holds.
    #
    # It is also only one of the forms a hold takes, and the corpus proves it.
    # Every enabled counter in the corpus declares `if (en) q <= q + 1`, and
    # synthesis absorbs the enable into the carry chain -- `D[0] = q[0] ^ en`,
    # `D[1] = q[1] ^ (q[0] & en)` -- so the register holds with no mux anywhere
    # in it and this search returns nothing for all four of its flops. What is
    # found here is a lower bound, named `mux_feedback` so no later stage can
    # mistake it for the answer to "is this register enabled". That question is
    # functional -- is there an input assignment under which D equals Q -- and
    # belongs to stage 4, which has a solver.
    for instance, record in flipflops.items():
        record["enable"] = None
        source = driver_of.get(record["data"])
        if source is None:
            continue
        entry = lib.get(source["cell"])
        if not entry:
            continue
        shape = selecting_mux(entry["pins"].get(source["pin"], {}).get("function"))
        if shape is None:
            continue
        select_pin, passed_at = shape
        mux = cells[source["instance"]]
        legs = {pin: bit_key(bits[0])
                for pin, bits in mux["connections"].items()
                if pin in passed_at and len(bits) == 1}
        held = [pin for pin, net in legs.items() if net == record["q"]]
        if len(held) != 1:
            continue
        other = [pin for pin in passed_at if pin != held[0]]
        select = mux["connections"].get(select_pin)
        record["enable"] = {
            "form": "mux_feedback",
            "net": bit_key(select[0]) if select else None,
            "mux": source["instance"],
            "held_when": passed_at[held[0]],
            "data_leg": legs.get(other[0]) if other else None,
        }

    # --- constants -----------------------------------------------------------
    #
    # A constant is a cell output whose liberty function is the literal 1 or 0,
    # which is what `conb_1` is for. Read from the function rather than from the
    # cell's name, so a differently named constant generator is still caught.
    constant_nets = {}
    for net, pin in driver_of.items():
        entry = lib.get(pin["cell"])
        if not entry:
            continue
        function = (entry["pins"].get(pin["pin"], {}).get("function") or "").strip()
        if function in ("0", "1"):
            constant_nets[net] = int(function)
    for net in net_pins:
        if net.startswith("const:"):
            constant_nets[net] = net.split(":", 1)[1]

    # --- combinational cones -------------------------------------------------
    #
    # A cone root is somewhere combinational logic ends: a flip flop's data or
    # asynchronous input, or a primary output. Walking backwards from each root
    # until a flop output, a primary input or a constant stops it gives the nets
    # that root's value depends on this cycle.
    roots = {}
    for instance, record in flipflops.items():
        for role in ("data", "reset", "set"):
            if record[role]:
                roots[f"{instance}.{role}"] = record[role]
    for net, port in port_of.items():
        if port["direction"] == "output":
            roots[f"port.{port['port']}"] = net

    sequential_outputs = {record["q"] for record in flipflops.values()}
    boundary = sequential_outputs | set(constant_nets) | {
        net for net, port in port_of.items() if port["direction"] == "input"}

    cones = defaultdict(set)
    for name, start in sorted(roots.items()):
        seen = set()
        stack = [start]
        while stack:
            net = stack.pop()
            if net in seen:
                continue
            seen.add(net)
            cones[net].add(name)
            if net in boundary:
                continue
            source = driver_of.get(net)
            if source is None:
                continue
            cell = cells[source["instance"]]
            directions = pins_of[cell["type"]]
            for pin, bits in cell["connections"].items():
                if directions.get(pin) != "input":
                    continue
                for bit in bits:
                    stack.append(bit_key(bit))

    graph = {
        "target": None,
        "top": top,
        "cells": {instance: {"type": cell["type"],
                             "connections": {pin: [bit_key(b) for b in bits]
                                             for pin, bits in
                                             cell["connections"].items()}}
                  for instance, cell in sorted(cells.items())},
        "ports": {name: {"direction": port["direction"],
                         "bits": [bit_key(b) for b in port["bits"]]}
                  for name, port in sorted(module["ports"].items())},
        "net_names": names,
        "nets": {net: {"pins": pins,
                       "driver": driver_of.get(net, {}).get("instance"),
                       "cones": sorted(cones.get(net, ()))}
                 for net, pins in sorted(net_pins.items())},
        "clock_nets": sorted(clock_nets),
        "reset_nets": sorted(reset_nets),
        "set_nets": sorted(set_nets),
        # Where a net's signal originates, for the nets that are not their own
        # origin. A net absent from this map is its own root, which keeps the
        # map to the 30 or so entries that carry information.
        "net_roots": net_roots,
        "clock_roots": grouped["clock"],
        "reset_roots": grouped["reset"],
        "set_roots": grouped["set"],
        "transparent_cells": transparent,
        "constant_nets": constant_nets,
        "flipflops": flipflops,
        "cone_roots": roots,
        # Kept for stages 4 and 6. Structural matching needs to know what a cell
        # computes, and a solver export is impossible without it: a netlist of
        # blackboxes can be walked as a graph and cannot be written to SMT2.
        "cell_functions": {
            cell_type: {pin: info["function"]
                        for pin, info in sorted(lib[cell_type]["pins"].items())
                        if info["function"]}
            for cell_type in sorted(used) if cell_type in lib},
        "cell_roles": roles_of,
        "source_disagreements": {
            "lef_vs_liberty_direction": direction_clashes,
            "liberty_vs_cell_name": name_clashes,
        },
    }
    return graph


def write_verilog(graph, path, lef):
    """The graph back out as Verilog, for the round trip gate.

    Written from the graph alone, never from stage 2's file, or the round trip
    would only prove that a copy is a copy.
    """
    buses, scalars = defaultdict(dict), {}
    for name, port in graph["ports"].items():
        if len(port["bits"]) == 1:
            scalars[name] = port
        else:
            for index, bit in enumerate(port["bits"]):
                buses[name][index] = bit
    port_direction = {name: port["direction"]
                      for name, port in graph["ports"].items()}

    of_net = {}
    for name, port in graph["ports"].items():
        for index, bit in enumerate(port["bits"]):
            of_net[bit] = name if len(port["bits"]) == 1 else f"{name}[{index}]"
    for net in graph["nets"]:
        of_net.setdefault(net, net if not net.startswith("const:")
                          else {"0": "1'b0", "1": "1'b1"}.get(
                              net.split(":", 1)[1], "1'bx"))

    lines = [f"module {graph['top']} ({', '.join(sorted(graph['ports']))});"]
    for name in sorted(scalars):
        lines.append(f"  {port_direction[name]} {name};")
    for name in sorted(buses):
        width = max(buses[name])
        lines.append(f"  {port_direction[name]} [{width}:0] {name};")
    lines.append("")

    port_nets = {bit for port in graph["ports"].values() for bit in port["bits"]}
    for net in sorted(graph["nets"]):
        if net in port_nets or net.startswith("const:"):
            continue
        lines.append(f"  wire {of_net[net]};")
    lines.append("")

    for instance, cell in sorted(graph["cells"].items()):
        allowed = functional_pins(lef[cell["type"]])
        wired = [f".{pin}({of_net[nets[0]]})"
                 for pin, nets in sorted(cell["connections"].items())
                 if pin in allowed and len(nets) == 1]
        if wired:
            lines.append(f"  {cell['type']} {instance} ({', '.join(wired)});")
    lines.append("endmodule")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return sum(1 for line in lines if line.startswith("  sky130"))


def build(out_dir, top, lef=None, lib=None, quiet=False):
    """Netlist in `out_dir` to `graph.json` and `graph.v` beside it.

    Separated from `run` so stage 5 can call it on each corpus circuit. The
    corpus has to reach stage 4 in the same shape the puzzle does, and the only
    way to be sure of that is to put it through the same code.
    """
    say = (lambda *a: None) if quiet else print

    netlist = os.path.join(out_dir, "netlist.v")
    if not os.path.exists(netlist):
        sys.exit(f"{netlist} missing")

    text = open(netlist, encoding="utf-8").read()
    used = sorted(set(re.findall(r"^\s*(sky130_fd_sc_hd__\w+)\s", text, re.M)))
    lef = lef if lef is not None else load_lef(PDK_DIR)
    lib = lib if lib is not None else liberty.load(PDK_DIR)

    say(f"top    {top}\ncells  {len(used)} types instantiated")
    without = [c for c in used if c not in lib]
    if without:
        sys.exit(f"no liberty entry for {without}; run tools/fetch_pdk.py")

    blackbox = os.path.join(out_dir, "blackbox.v")
    blackbox_library(used, lef, blackbox)
    say(f"wrote {blackbox}")

    yosys_json = os.path.join(out_dir, "yosys.json")
    log = run_yosys(netlist.replace("\\", "/"), blackbox.replace("\\", "/"),
                    yosys_json.replace("\\", "/"), top)
    for line in log.splitlines():
        if line.strip().startswith(("Number of cells", "Number of wires",
                                    "Number of public wires")):
            say(f"  yosys: {line.strip()}")

    complaints = [line.strip() for line in log.splitlines()
                  if line.startswith(("Warning:", "Found and reported"))
                  or "problems." in line]
    if complaints:
        say("  yosys check:")
        for line in complaints[:20]:
            say(f"    {line}")
        if len(complaints) > 20:
            say(f"    ... and {len(complaints) - 20} more")

    with open(yosys_json, encoding="utf-8") as handle:
        design = json.load(handle)
    if top not in design["modules"]:
        sys.exit(f"yosys produced no module named {top!r}")

    graph = build_graph(design, top, lef, lib)
    graph["target"] = top

    clashes = graph["source_disagreements"]
    for label, entries in sorted(clashes.items()):
        if entries:
            say(f"\nSOURCES DISAGREE, {label}: {len(entries)}")
            for entry in entries[:10]:
                say(f"  {entry}")
        else:
            say(f"  sources agree: {label}")

    say(f"\ncells {len(graph['cells'])}, nets {len(graph['nets'])}, "
          f"ports {len(graph['ports'])}")
    say(f"clock nets {len(graph['clock_nets'])}: "
          f"{[graph['net_names'].get(n, n) for n in graph['clock_nets']]}")
    say(f"reset nets {len(graph['reset_nets'])}, "
          f"set nets {len(graph['set_nets'])}, "
          f"constant nets {len(graph['constant_nets'])}")
    say(f"state elements {len(graph['flipflops'])}: "
          f"{dict(Counter(r['cell'].split('__')[-1] for r in graph['flipflops'].values()))}")
    for cell_type, roles in sorted(graph["cell_roles"].items()):
        say(f"  {cell_type.split('__')[-1]:<12} {roles['kind']:<5} "
              f"clock={roles['clock']} data={roles['data']} q={roles['q']} "
              f"reset={roles['reset']}({roles['reset_level']}) "
              f"set={roles['set']}({roles['set_level']})")
    say(f"transparent cells: {len(graph['transparent_cells'])} types, "
          f"{sum(1 for c in graph['cells'].values() if c['type'] in graph['transparent_cells'])} "
          f"instances; {len(graph['net_roots'])} nets are not their own root")
    for role in ("clock", "reset", "set"):
        groups = graph[f"{role}_roots"]
        if not groups:
            continue
        sizes = sorted((len(m) for m in groups.values()), reverse=True)
        say(f"  {role}: {len(graph[role + '_nets'])} nets -> {len(groups)} root(s) "
              f"{[graph['net_names'].get(r, r) for r in groups]}, "
              f"flops per root {sizes}")
    flipped = [i for i, r in graph["flipflops"].items()
               if any(r.get(f"{role}_inverted") for role in ("clock", "reset", "set"))]
    say(f"  flops reached through an inverting path: {len(flipped)}")
    say(f"cell functions kept for stages 4 and 6: "
          f"{len(graph['cell_functions'])} cell types")
    enabled = [i for i, r in graph["flipflops"].items() if r["enable"]]
    say(f"  holds found structurally, as a mux fed back from Q: {len(enabled)} "
          f"of {len(graph['flipflops'])}. A lower bound: synthesis can absorb "
          f"an enable into arithmetic and leave no mux. Stage 4 decides this "
          f"functionally.")
    if enabled:
        nets = Counter(graph["net_names"].get(graph["flipflops"][i]["enable"]["net"],
                                              graph["flipflops"][i]["enable"]["net"])
                       for i in enabled)
        say(f"  enable nets: {dict(nets)}")
    say(f"cone roots {len(graph['cone_roots'])}")
    sizes = Counter(len(entry["cones"]) for entry in graph["nets"].values())
    say(f"  nets in no cone: {sizes.get(0, 0)}, in exactly one: {sizes.get(1, 0)}, "
          f"in more: {sum(c for n, c in sizes.items() if n > 1)}")

    graph_path = os.path.join(out_dir, "graph.json")
    with open(graph_path, "w", encoding="utf-8") as handle:
        json.dump(graph, handle, indent=1)
    say(f"\nwrote {graph_path}")

    verilog_path = os.path.join(out_dir, "graph.v")
    emitted = write_verilog(graph, verilog_path, lef)
    say(f"wrote {verilog_path} with {emitted} instances")
    return graph


def run(target):
    """The stage 3 entry point for a real target, warm up or puzzle."""
    out_dir = os.path.join("out", target)
    with open(os.path.join(out_dir, "netlist.json"), encoding="utf-8") as handle:
        top = json.load(handle)["top"]

    print(f"target {target}")
    build(out_dir, top)
    print(f"\nround trip gate: python tools/sim/run.py {target} "
          f"--netlist {os.path.join(out_dir, 'graph.v')}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage3_graph.py [{' | '.join(TARGETS)}]")
    sys.exit(run(args[0]))
