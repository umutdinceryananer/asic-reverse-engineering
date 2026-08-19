"""Stage 4, step 2. One cone of logic, composed into something a person reads.

The roadmap's instruction for the analysis week is "read `success` backwards to
find what gates the success condition". Backwards from `success` the netlist is
738 anonymous cells; this turns the part that matters into a listing over
register bits and ports, in dependency order, with each line showing what the
cell computes rather than what it is called.

Nothing here interprets. It substitutes names and composes liberty functions,
both of which are mechanical, and stops at the boundary stage 3 already defines:
a flip flop's output, a primary input, a constant.

`success` in the puzzle is a *registered* output -- the port is driven straight
off a `dfrtp` -- so the interesting cone is the one feeding that flop's D, and
that is what this defaults to. It is also one of the two widest cones in the
design, 57 boundary signals at depth 6, which is why `corpus_reach.py` had
something to say about it.

Usage:
    python tools/stage4_cone.py puzzle                 # the success condition
    python tools/stage4_cone.py warmup
    python tools/stage4_cone.py puzzle --root port.O[0]
    python tools/stage4_cone.py puzzle --list          # every cone root
"""

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import boolexpr
from stage1_cells import TARGETS

SUPPLY = ("VGND", "VPWR", "VPB", "VNB")


def load(target):
    base = os.path.join("out", target)
    with open(os.path.join(base, "graph.json"), encoding="utf-8") as handle:
        graph = json.load(handle)
    registers = None
    path = os.path.join(base, "registers.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            registers = json.load(handle)
    return graph, registers


def boundary_names(graph, registers):
    """A readable name for every signal a cone can stop at.

    A flop's output becomes `R0[12]`, its register and its position in it, which
    is the only sense in which a bit of an anonymous register has an index. A
    primary input keeps its port name. A constant becomes 0 or 1.
    """
    names = {}
    for net, value in graph["constant_nets"].items():
        names[net] = str(value)
    for port, entry in graph["ports"].items():
        if entry["direction"] != "input":
            continue
        for index, bit in enumerate(entry["bits"]):
            names[bit] = port if len(entry["bits"]) == 1 else f"{port}[{index}]"
    if registers:
        for row in registers["registers"]:
            for index, flop in enumerate(row["flops"]):
                q = graph["flipflops"][flop]["q"]
                names[q] = f"{row['register']}[{index}]"
    else:
        for flop, record in graph["flipflops"].items():
            names[record["q"]] = f"{flop}.Q"
    return names


def cone(graph, root_net, stops):
    """The cells feeding `root_net`, in dependency order, and what it rests on."""
    seen, order, support = set(), [], set()

    def walk(net):
        if net in seen:
            return
        seen.add(net)
        if net in stops:
            support.add(net)
            return
        driver = graph["nets"].get(net, {}).get("driver")
        if driver is None:
            support.add(net)
            return
        cell = graph["cells"][driver]
        if cell["type"] in graph["cell_roles"]:      # a flop: the cone stops
            support.add(net)
            return
        for pin, nets in sorted(cell["connections"].items()):
            if pin in SUPPLY:
                continue
            for upstream in nets:
                walk(upstream)
        order.append((net, driver))
    sys.setrecursionlimit(50000)
    walk(root_net)
    return order, support


def render(graph, order, names, trees):
    """One line per cell: the net it drives, and the function over its inputs."""
    label = dict(names)
    for position, (net, instance) in enumerate(order):
        label.setdefault(net, f"t{position}")
    lines = []
    for net, instance in order:
        cell = graph["cells"][instance]
        kind = cell["type"].split("__")[-1]
        pin_of_net = {}
        for pin, nets in cell["connections"].items():
            if pin in SUPPLY:
                continue
            for wire in nets:
                pin_of_net.setdefault(pin, wire)
        outputs = [p for p in pin_of_net
                   if (cell["type"], p) in trees and pin_of_net[p] == net]
        if not outputs:
            lines.append(f"  {label[net]:<10} = {kind}(?)   # no function for this pin")
            continue
        tree = trees[(cell["type"], outputs[0])]
        text = substitute(tree, {p: label.get(w, w) for p, w in pin_of_net.items()})
        lines.append(f"  {label[net]:<10} = {text:<52} # {kind}")
    return lines, label


def substitute(node, mapping):
    """The expression with pin names replaced by the nets wired to them."""
    if node.kind == "const":
        return str(node.value)
    if node.kind == "var":
        return mapping.get(node.value, node.value)
    if node.kind == "not":
        inner = substitute(node.children[0], mapping)
        return f"!{inner}" if inner.isidentifier() or inner.startswith(("!", "R")) \
            else f"!({inner})"
    joiner = " & " if node.kind == "and" else " | "
    parts = [substitute(c, mapping) for c in node.children]
    return "(" + joiner.join(parts) + ")"


def default_root(graph):
    """The cone behind `success`, following through the flop that drives it."""
    for candidate in ("success", "S"):
        if candidate not in graph["ports"]:
            continue
        net = graph["ports"][candidate]["bits"][0]
        driver = graph["nets"].get(net, {}).get("driver")
        if driver in graph["flipflops"]:
            return f"{driver}.data", graph["flipflops"][driver]["data"]
        return f"port.{candidate}", net
    root = sorted(graph["cone_roots"])[0]
    return root, graph["cone_roots"][root]


def run(target, root=None, listing=False):
    graph, registers = load(target)
    if listing:
        rows = []
        for name, net in graph["cone_roots"].items():
            depth = len([1 for n, e in graph["nets"].items() if name in e["cones"]])
            rows.append((depth, name))
        for size, name in sorted(rows, reverse=True)[:30]:
            print(f"  {size:>5} nets   {name}")
        print(f"  ... {len(rows)} cone roots in total")
        return 0

    if root:
        if root not in graph["cone_roots"]:
            sys.exit(f"no cone root named {root!r}; try --list")
        root_net = graph["cone_roots"][root]
    else:
        root, root_net = default_root(graph)

    names = boundary_names(graph, registers)
    trees = boolexpr.compile_functions(graph["cell_functions"])
    stops = set(names)
    order, support = cone(graph, root_net, stops)

    print(f"target {target}, cone root {root}")
    print(f"  {len(order)} cells, {len(support)} boundary signals\n")

    by_kind = defaultdict(list)
    for net in support:
        name = names.get(net, net)
        if name in ("0", "1"):
            by_kind["constant"].append(name)
        elif "[" in name and name.split("[")[0].startswith("R"):
            by_kind[name.split("[")[0]].append(name)
        else:
            by_kind["port"].append(name)
    print("  it depends on")
    for kind, members in sorted(by_kind.items()):
        shown = sorted(members, key=lambda s: (len(s), s))
        print(f"    {kind:<10} {len(members):>3}  {shown if len(shown) <= 12 else shown[:12] + ['...']}")

    lines, label = render(graph, order, names, trees)
    print(f"\n  {root} = {label.get(root_net, root_net)}")
    for line in lines:
        print(line)

    out = os.path.join("out", target, "cone.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({"root": root, "cells": len(order),
                   "support": sorted(names.get(n, n) for n in support),
                   "listing": lines}, handle, indent=1)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    listing = "--list" in args
    args = [a for a in args if a != "--list"]
    root = None
    if "--root" in args:
        index = args.index("--root")
        root = args[index + 1]
        args = args[:index] + args[index + 2:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage4_cone.py [{' | '.join(TARGETS)}] "
                 f"[--root <cone root>] [--list]")
    sys.exit(run(args[0], root, listing))
