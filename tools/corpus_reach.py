"""How far the corpus reaches, measured against a target it has to explain.

Stage 4 will name a block by comparing it against the corpus, so the corpus
bounds what can ever be named: a structure absent from it can be found
unexplained but not identified. This measures that bound, and it exists because
the number previously quoted for it was answering a different question.

**Cell vocabulary overlap is not coverage.** The corpus and the puzzle share 91%
of their cell instances by function, which sounds like a coverage figure and is
not one. The corpus can only name a puzzle block if some corpus circuit computes
the same *function*; a block built entirely from `nand2` scores 100% on
vocabulary and may still compute something nothing here computes. That number is
reported below because it justifies a different claim -- detectors must normalise
the drive strength suffix, and reason about functions rather than cell types --
and it is labelled so it cannot be read as coverage again.

**Functional coverage cannot be measured before stage 4**, because measuring it
is what stage 4's miters do. What *can* be measured now is a one-directional
bound. A cone depending on more distinct inputs than any corpus cone cannot be
equivalent to any of them, so it cannot be named however good the detector is.
Necessary, never sufficient: staying inside the envelope proves nothing, and
falling outside it proves the block is out of reach.

The real number is stage 4's residue report: after the detectors run, how much
of the netlist is still unexplained.

Usage:
    python tools/corpus_reach.py puzzle
    python tools/corpus_reach.py warmup
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict

OUT_DIR = "out/synth"
SUPPLY = ("VGND", "VPWR", "VPB", "VNB")

# `a21oi_1` and `a21oi_2` compute the same function and differ in how hard they
# can drive, which is a physical choice a detector has no business reading.
function_of = lambda name: re.sub(r"_\d+$", "", name.split("__")[-1])


def cone_shapes(graph):
    """Per cone root, how many boundary nets it depends on and how deep it is.

    The boundary is where combinational logic stops: a flop's output, a primary
    input, a constant. Support counted there rather than at the cells makes the
    number comparable between two circuits mapped differently, which is the
    whole point of comparing them.
    """
    boundary = {r["q"] for r in graph["flipflops"].values()}
    boundary |= set(graph["constant_nets"])
    boundary |= {bit for port in graph["ports"].values()
                 if port["direction"] == "input" for bit in port["bits"]}

    support = defaultdict(set)
    for net, entry in graph["nets"].items():
        if net in boundary:
            for root in entry["cones"]:
                support[root].add(net)

    shapes = {}
    for root, start in graph["cone_roots"].items():
        seen, stack, depth = set(), [(start, 0)], 0
        while stack:
            net, distance = stack.pop()
            if net in seen:
                continue
            seen.add(net)
            depth = max(depth, distance)
            if net in boundary:
                continue
            driver = graph["nets"].get(net, {}).get("driver")
            if driver is None:
                continue
            cell = graph["cells"][driver]
            if cell["type"] in graph["cell_roles"]:
                continue
            for pin, nets in cell["connections"].items():
                if pin in SUPPLY:
                    continue
                for upstream in nets:
                    stack.append((upstream, distance + 1))
        shapes[root] = (len(support.get(root, ())), depth)
    return shapes


def envelope(entries):
    """The widest and deepest cone the corpus contains, and where it came from."""
    widest = deepest = (0, None, None)
    total = 0
    for entry in entries:
        path = f"{entry['dir']}/graph.json"
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            shapes = cone_shapes(json.load(handle))
        total += len(shapes)
        for root, (support, depth) in shapes.items():
            label = f"{entry['name']}[{entry.get('variant', 'base')}]"
            if support > widest[0]:
                widest = (support, label, root)
            if depth > deepest[0]:
                deepest = (depth, label, root)
    return total, widest, deepest


def main(target):
    graph_path = f"out/{target}/graph.json"
    if not os.path.exists(graph_path):
        sys.exit(f"{graph_path} missing; run tools/stage3_graph.py {target}")
    if not os.path.exists(f"{OUT_DIR}/index.json"):
        sys.exit(f"{OUT_DIR}/index.json missing; run tools/stage5_corpus.py")

    with open(graph_path, encoding="utf-8") as handle:
        graph = json.load(handle)
    with open(f"{OUT_DIR}/index.json", encoding="utf-8") as handle:
        entries = json.load(handle)["circuits"]
    for entry in entries:
        entry.setdefault("dir", f"{OUT_DIR}/{entry['name']}")

    shapes = cone_shapes(graph)
    total, widest, deepest = envelope(entries)

    print(f"target {target}: {len(shapes)} cone roots, "
          f"{len(graph['cells'])} cells")
    print(f"corpus: {len({e['name'] for e in entries})} circuits, "
          f"{len(entries)} netlists, {total} cone roots")

    print(f"\n--- the bound: cones this corpus provably cannot name")
    print(f"  corpus envelope: support up to {widest[0]} inputs "
          f"({widest[1]}), depth up to {deepest[0]} ({deepest[1]})")
    supports = sorted(s for s, _ in shapes.values())
    depths = sorted(d for _, d in shapes.values())
    print(f"  {target}: support median {supports[len(supports)//2]} "
          f"max {supports[-1]}, depth median {depths[len(depths)//2]} "
          f"max {depths[-1]}")

    outside = {root for root, (s, d) in shapes.items()
               if s > widest[0] or d > deepest[0]}
    print(f"  cones wider or deeper than anything in the corpus: "
          f"{len(outside)}/{len(shapes)} "
          f"({100 * len(outside) / len(shapes):.0f}%)")
    for root in sorted(outside)[:8]:
        print(f"    {root}  support {shapes[root][0]}, depth {shapes[root][1]}")
    if not outside:
        print("  Nothing is out of reach on size grounds. That is a necessary")
        print("  condition and not a sufficient one: it says no block is")
        print("  provably unnameable, not that any block will be named.")

    print(f"\n--- not coverage: cell vocabulary")
    puzzle_cells = Counter(function_of(c["type"]) for c in graph["cells"].values())
    corpus_cells = Counter()
    for entry in entries:
        for cell, count in entry["cell_mix"].items():
            corpus_cells[function_of(cell)] += count
    shared = set(puzzle_cells) & set(corpus_cells)
    covered = sum(n for c, n in corpus_cells.items() if c in shared)
    print(f"  by function: {len(shared)} kinds shared, "
          f"{covered}/{sum(corpus_cells.values())} corpus instances of a "
          f"shared kind ({100 * covered / sum(corpus_cells.values()):.0f}%)")

    by_name = Counter(c["type"] for c in graph["cells"].values())
    corpus_names = Counter()
    for entry in entries:
        corpus_names.update(entry["cell_mix"])
    shared_names = set(by_name) & set(corpus_names)
    named = sum(n for c, n in corpus_names.items() if c in shared_names)
    print(f"  by full name: {len(shared_names)} kinds shared, "
          f"{named}/{sum(corpus_names.values())} "
          f"({100 * named / sum(corpus_names.values()):.0f}%)")
    print(f"  the gap between those two is drive strength, and it is why")
    print(f"  detectors must normalise the suffix rather than match on it.")

    absent = sorted(set(puzzle_cells) - set(corpus_cells))
    share = sum(puzzle_cells[c] for c in absent)
    print(f"  functions the corpus never produced: {len(absent)}, "
          f"{share}/{sum(puzzle_cells.values())} target cells "
          f"({100 * share / sum(puzzle_cells.values()):.0f}%)")
    if absent:
        print(f"    {absent}")
    transparent = {function_of(t) for t in graph.get("transparent_cells", {})}
    excused = [c for c in absent if c in transparent or c == "diode"]
    if excused:
        remaining = share - sum(puzzle_cells[c] for c in excused)
        print(f"    of those, {excused} need no naming: transparent cells are")
        print(f"    walked through by function, and a diode has none. Leaves")
        print(f"    {remaining}/{sum(puzzle_cells.values())} cells "
              f"({100 * remaining / sum(puzzle_cells.values()):.0f}%).")

    print(f"\n  None of the above is functional coverage. The corpus names a")
    print(f"  block only if some circuit in it computes the same function, and")
    print(f"  no miter has been run. That measurement is stage 4's residue")
    print(f"  report and does not exist yet.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1:
        sys.exit("usage: python tools/corpus_reach.py [warmup | puzzle]")
    sys.exit(main(args[0]))
