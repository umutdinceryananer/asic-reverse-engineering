"""Stage 3's warm up annotations against the RTL the warm up was written from.

Every other check on stage 3 is internal. The round trip proves the circuit
survived; `stage3_crosscheck.py` derives the annotations a second time from
stage 2's netlist. Both are this pipeline checking itself, and the hold
annotation in particular had never been checked against anything at all -- it
is a structural search whose own docstring calls it a lower bound.

`puzzle/warmup/00_source.v` is the design, in the author's own words, before
synthesis. It says there are two eight bit shift registers, that they hold when
`en` is low, that the reset is asynchronous and active low, and that there is
one clock. None of that is derived here; it is read out of the file and used as
the answer.

**How much of the file is read, and how.** Not a Verilog elaborator. Targeted
patterns for the four constructs this RTL uses, and a refusal if it meets
anything else, so that a design this cannot read produces an error rather than
a confident answer about the parts it happened to match:

    always @(posedge CLK or negedge RST)     clock, and an async active low reset
    if (!RST) ... else if (COND)             a hold, gated on COND
    reg [h:l] NAME                           state, and how much of it
    MODULE instance (...)                    one level of hierarchy, counted

**What the warm up cannot exercise.** Its output is `assign eq = (val == 496)`,
combinational. The puzzle's `success` is a registered output, and no part of
that path is tested here. Said in the output rather than left to be discovered.

Usage:
    python tools/verify_annotations.py warmup
    python tools/verify_annotations.py warmup --graph out/warmup/broken.json
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage1_cells import TARGETS

# The RTL each target was written from, where the repository has it. The puzzle
# has none, which is the entire situation this pipeline exists to address.
SOURCE = {"warmup": "puzzle/warmup/00_source.v", "puzzle": None}

MODULE = re.compile(r"\bmodule\s+(\w+)\s*\((.*?)\);(.*?)\bendmodule\b", re.S)
CLOCKED = re.compile(r"always\s*@\s*\(\s*(posedge|negedge)\s+(\w+)"
                     r"(?:\s+or\s+(posedge|negedge)\s+(\w+))?\s*\)")
REG = re.compile(r"\breg\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*(\w+)")
HOLD = re.compile(r"else\s+if\s*\(\s*(\w+)\s*\)")
INSTANCE = re.compile(r"^\s*(\w+)\s+(\w+)\s*\(", re.M)
ASSIGN = re.compile(r"\bassign\s+(\w+)\s*=")


def read_rtl(path):
    """What the RTL declares about state, clocking, reset and holding."""
    text = re.sub(r"//[^\n]*", "", open(path, encoding="utf-8").read())
    modules = {name: (ports, body) for name, ports, body in MODULE.findall(text)}
    if not modules:
        sys.exit(f"{path}: no modules found")

    described = {}
    for name, (ports, body) in modules.items():
        # The port list as well as the body: this RTL declares its state as
        # `output reg [7:0] parallel_out` in the header, and a reader that only
        # looked below the semicolon found zero flip flops in a design with
        # sixteen -- and said so, which is the only reason it was noticed.
        text_of = ports + ";\n" + body
        clocked = CLOCKED.findall(body)
        if len(clocked) > 1:
            sys.exit(f"{path}: module {name} has {len(clocked)} clocked blocks; "
                     f"this reader handles one and will not guess at more")
        registers = {r[2]: (int(r[0]) - int(r[1]) + 1 if r[0] else 1)
                     for r in REG.findall(text_of)}
        entry = {"registers": registers, "bits": sum(registers.values()),
                 "combinational": set(ASSIGN.findall(body)), "clock": None,
                 "reset": None, "reset_level": None, "set": None, "hold": None}
        if clocked:
            edge, signal, other_edge, other = clocked[0]
            entry["clock"] = signal if edge == "posedge" else None
            if entry["clock"] is None:
                sys.exit(f"{path}: module {name} clocks on a {edge}; every "
                         f"target so far is positive edge and this reader "
                         f"would have to be told what to do with it")
            if other:
                entry["reset"] = other
                entry["reset_level"] = "low" if other_edge == "negedge" else "high"
            holds = HOLD.findall(body)
            entry["hold"] = holds[0] if holds else None
        described[name] = entry

    instantiated = {}
    for name, (_ports, body) in modules.items():
        for module, instance in INSTANCE.findall(body):
            if module in modules and module != name:
                instantiated.setdefault(name, []).append((module, instance))
    tops = [n for n in modules
            if not any(n == m for uses in instantiated.values()
                       for m, _i in uses)]
    if len(tops) != 1:
        sys.exit(f"{path}: {len(tops)} top level modules {tops}; expected one")
    top = tops[0]

    total, resets, clocks = 0, set(), set()
    holds = {}          # net -> bits held, summed over instances
    combinational = set(described[top]["combinational"])
    for module, _instance in instantiated.get(top, []):
        combinational |= described[module]["combinational"]
    for module, _instance in instantiated.get(top, []):
        entry = described[module]
        total += entry["bits"]
        if entry["hold"]:
            holds[entry["hold"]] = holds.get(entry["hold"], 0) + entry["bits"]
        if entry["reset"]:
            resets.add((entry["reset"], entry["reset_level"]))
        if entry["clock"]:
            clocks.add(entry["clock"])
    total += described[top]["bits"]

    return {"top": top, "path": path, "flops": total,
            "holds": holds, "resets": resets, "clocks": clocks,
            "sets": 0,
            "combinational_outputs": sorted(combinational),
            "hierarchy": instantiated.get(top, [])}


def run(target, graph_path=None):
    source = SOURCE.get(target)
    if source is None:
        sys.exit(f"target {target!r} has no RTL in this repository. That is the "
                 f"point of the pipeline, not a defect in this gate.")
    if not os.path.exists(source):
        sys.exit(f"{source} missing; run git submodule update --init")
    graph_path = graph_path or os.path.join("out", target, "graph.json")
    if not os.path.exists(graph_path):
        sys.exit(f"{graph_path} missing; run tools/stage3_graph.py {target}")
    with open(graph_path, encoding="utf-8") as handle:
        graph = json.load(handle)

    rtl = read_rtl(source)
    named = lambda net: graph["net_names"].get(net, net) if net else None
    flops = graph["flipflops"]

    print(f"target {target}")
    print(f"  answer key   {source}, module {rtl['top']}")
    print(f"  it declares  {rtl['flops']} flip flops over "
          f"{len(rtl['hierarchy'])} instances "
          f"{[f'{m} {i}' for m, i in rtl['hierarchy']]}")
    print(f"               clock {sorted(rtl['clocks'])}, reset "
          f"{sorted(rtl['resets'])}, hold {sorted(rtl['holds'].items())}")
    print(f"  under test   {graph_path.replace(os.sep, '/')}\n")

    problems = []

    print(f"  flip flops        {len(flops)} found, {rtl['flops']} declared")
    if len(flops) != rtl["flops"]:
        problems.append(f"{len(flops)} flip flops, the RTL declares "
                        f"{rtl['flops']}")

    clock_roots = {named(root) for root in graph["clock_roots"]}
    print(f"  clock roots       {sorted(clock_roots)} found, "
          f"{sorted(rtl['clocks'])} declared")
    if clock_roots != rtl["clocks"]:
        problems.append(f"clock roots {sorted(clock_roots)}, the RTL declares "
                        f"{sorted(rtl['clocks'])}")

    reset_names = {(named(r["reset_root"]), r["reset_level"])
                   for r in flops.values() if r["reset_root"]}
    without = sum(1 for r in flops.values() if not r["reset_root"])
    print(f"  resets            {sorted(reset_names)} over "
          f"{len(flops) - without} flops, {without} with none; RTL declares "
          f"{sorted(rtl['resets'])}")
    if reset_names != rtl["resets"] or without:
        problems.append(f"resets {sorted(reset_names)} with {without} flop(s) "
                        f"unreset, the RTL declares {sorted(rtl['resets'])} "
                        f"for all of them")

    sets = sum(1 for r in flops.values() if r["set_root"])
    print(f"  sets              {sets} found, {rtl['sets']} declared")
    if sets != rtl["sets"]:
        problems.append(f"{sets} flop(s) have a set pin, the RTL declares "
                        f"{rtl['sets']}")

    # The hold. This is the annotation with no other external check anywhere in
    # the pipeline, and the reason this tool was written.
    held = {i: r["enable"] for i, r in flops.items() if r.get("enable")}
    hold_nets = {named(h["net"]) for h in held.values()}
    levels = {h["held_when"] for h in held.values()}
    declared_nets = set(rtl["holds"])
    declared_bits = sum(rtl["holds"].values())
    print(f"  holds             {len(held)} of {len(flops)} flops, on "
          f"{sorted(hold_nets)} when {sorted(levels)}; RTL declares "
          f"{declared_bits} on {sorted(declared_nets)}")
    if len(held) != declared_bits:
        problems.append(f"{len(held)} flop(s) annotated as holding, the RTL "
                        f"declares {declared_bits}")
    if hold_nets != declared_nets:
        problems.append(f"holds on {sorted(hold_nets)}, the RTL gates them on "
                        f"{sorted(declared_nets)}")
    # `else if (en)` writes when en is high, so the register holds when it is
    # low. The RTL states the writing condition and stage 3 records the holding
    # one, and they are opposites; getting this backwards is exactly the mux
    # polarity defect the mux2i rule exists to prevent.
    if levels and levels != {"low"}:
        problems.append(f"holds when {sorted(levels)}; the RTL writes on "
                        f"`else if ({sorted(declared_nets)[0]})`, so it holds "
                        f"when that is low")

    print(f"\n  Not exercised here: the warm up's output is "
          f"{rtl['combinational_outputs']}, assigned\n  combinationally. The "
          f"puzzle's `success` is a registered output and no part of\n  that "
          f"path is tested by this gate.")

    if problems:
        print(f"\nDISAGREEMENTS")
        for problem in problems:
            print(f"  {problem}")
        print("\nRESULT: fail, stage 3's annotations are not what the RTL says")
        return 1
    print("\nRESULT: pass, every annotation matches the RTL the design was "
          "written from")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    override = None
    if len(args) >= 3 and args[1] == "--graph":
        override, args = args[2], args[:1]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/verify_annotations.py "
                 f"[{' | '.join(TARGETS)}] [--graph <path>]")
    sys.exit(run(args[0], override))
