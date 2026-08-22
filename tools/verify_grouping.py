"""Stage 4's placement clustering and bit order, checked against the netlist.

Two of Package 4's criteria are derived rather than scored, and neither has a
corpus number behind it. `spatial_groups` clusters flops by where they sit, and
**nothing in `out/synth/` was ever placed**, so no corpus figure covers it at
all. `bit_order` walks `D <- Q` links, and the corpus declares register sizes
rather than bit orders, so there is nothing to score it against either.

What can be done instead is to check both against something that is not their
own output:

    single linkage    recomputed here by brute force transitive closure --
                      repeatedly merge any two groups holding a pair within the
                      threshold -- which is quadratic, obviously correct, and
                      shares no code with the union find in `stage4_registers`.
                      Checked at every threshold from 1 to 12 row heights, not
                      only at the committed one.
    determinism       the same answer under 100 shuffles of the flop dict and
                      the placement dict. A criterion whose answer depends on
                      dictionary order is a criterion that cannot be recorded.
    the chains        every consecutive pair of every chain has to be a real
                      `D <- Q` link in the graph **and the only one into that
                      bit**, every chain head has to have no predecessor inside
                      its group and every tail no successor. Checked against
                      `flop_edges`, not against the chain list that produced it.
    ripple depth      by construction, on two synthetic graphs. A chain with a
                      skip edge distinguishes longest path from shortest --
                      longest gives four distinct depths and an order, shortest
                      gives a repeat and a refusal. A **diamond does not**
                      distinguish them: two bits share a depth under either
                      rule, so refusing is correct and says nothing about which
                      rule ran. The first version of this check used a diamond.

Two things it reports rather than asserts, because both are properties of the
design rather than of the code: how many flops the layout never placed, and
which groups come back as part chain and part isolated bits.

Usage:
    python tools/verify_grouping.py warmup
    python tools/verify_grouping.py warmup --selftest    # and would it notice
"""

import json
import math
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_registers as stage4
from stage1_cells import TARGETS

SHUFFLES = 50
THRESHOLDS = range(1, 13)


def linkage_by_closure(graph, positions, link_rows):
    """Single linkage as a transitive closure, quadratic and obvious.

    Written out rather than shared: the point is that two implementations of
    the same definition agree, and importing the one under test would make this
    a check on nothing.
    """
    limit = link_rows * stage4.ROW_HEIGHT
    out = []
    for _signature, members in stage4.control_groups(graph).items():
        placed = [flop for flop in members if flop in positions]
        groups = [[flop] for flop in placed]
        merged = True
        while merged:
            merged = False
            for first in range(len(groups)):
                for second in range(first + 1, len(groups)):
                    if any(math.hypot(positions[a][0] - positions[b][0],
                                      positions[a][1] - positions[b][1]) <= limit
                           for a in groups[first] for b in groups[second]):
                        groups[first] += groups[second]
                        del groups[second]
                        merged = True
                        break
                if merged:
                    break
        out.extend(groups)
        out.extend([flop] for flop in members if flop not in positions)
    return sorted(sorted(group) for group in out)


def synthetic(edges):
    """A graph with only what `flop_edges` reads, built from a pred map."""
    graph = {"flipflops": {}, "nets": {}}
    for node in edges:
        graph["flipflops"][f"f{node}"] = {"q": f"q{node}"}
        graph["nets"][f"q{node}"] = {
            "cones": [f"f{target}.data" for target, preds in edges.items()
                      if node in preds]}
    return graph


def check(spatial, bit_order, graph, positions, verbose=True):
    """Both derivations against something other than themselves."""
    problems = []

    def report(ok, label, detail=""):
        if verbose:
            print(f"  {'ok  ' if ok else 'FAIL'}  {label}"
                  f"{'   ' + detail if detail else ''}")
        if not ok:
            problems.append(label)

    if verbose:
        print("single linkage, against a brute force transitive closure")
    for link in THRESHOLDS:
        mine = linkage_by_closure(graph, positions, link)
        theirs = sorted(sorted(m) for m in spatial(graph, positions, link).values())
        report(mine == theirs, f"threshold {link:>2} rows "
                               f"({link * stage4.ROW_HEIGHT:5.2f} um)",
               stage4.sizes_as(sorted((len(g) for g in theirs), reverse=True)))

    if verbose:
        print(f"\ndeterminism, {SHUFFLES} shuffles of each input dict")
    base = sorted(sorted(m) for m in spatial(graph, positions).values())
    stable = True
    for trial in range(SHUFFLES):
        flops = list(graph["flipflops"].items())
        random.Random(trial).shuffle(flops)
        shuffled = dict(graph)
        shuffled["flipflops"] = dict(flops)
        stable = stable and base == sorted(
            sorted(m) for m in spatial(shuffled, positions).values())
        places = list(positions.items())
        random.Random(trial + 9001).shuffle(places)
        stable = stable and base == sorted(
            sorted(m) for m in spatial(graph, dict(places)).values())
    report(stable, f"{2 * SHUFFLES} shuffles give an identical partition")

    # Reported, not asserted: how many flops the layout never placed. The
    # branch that makes each of those its own group is unreachable when the
    # answer is zero, which is the warm up, so it is exercised by hand below.
    unplaced = [flop for flop in graph["flipflops"] if flop not in positions]
    if verbose:
        print(f"\n  {len(unplaced)} flop(s) have no placement in this target")
    thinned = {k: v for k, v in positions.items()
               if k != sorted(graph["flipflops"])[0]}
    groups = spatial(graph, thinned)
    covered = sorted(flop for members in groups.values() for flop in members)
    report(covered == sorted(graph["flipflops"]),
           "with one placement removed, the partition still covers every flop",
           stage4.sizes_as(sorted((len(m) for m in groups.values()),
                                  reverse=True)))

    if verbose:
        print("\nthe chains, against the graph rather than against themselves")
    fanin, fanout = stage4.flop_edges(graph)
    inside = set(graph["flipflops"])
    order = bit_order(graph, sorted(graph["flipflops"]))
    chains = order.get("chains") or []
    links_real = sole_predecessor = True
    for chain in chains:
        for before, after in zip(chain, chain[1:]):
            links_real = links_real and after in fanout.get(before, set())
            others = (fanin.get(after, set()) & inside) - {before, after}
            sole_predecessor = sole_predecessor and not others
    report(links_real, "every consecutive pair is a real D <- Q link",
           f"{len(chains)} chain(s) of {[len(c) for c in chains]}")
    report(sole_predecessor, "and the only predecessor of the bit it feeds")
    report(all(not (fanin.get(c[0], set()) - {c[0]}) for c in chains),
           "every chain head has no predecessor inside its group")
    report(all(not (fanout.get(c[-1], set()) - {c[-1]}) for c in chains),
           "every chain tail has no successor inside its group")
    singles = [c for c in chains if len(c) == 1]
    if verbose and singles:
        print(f"     {len(singles)} of those chains hold one bit and carry no "
              f"order; `ordered`\n     says how many bits the decomposition "
              f"actually orders: {order.get('ordered')}")

    if verbose:
        print("\nripple depth, by construction")
    # 0 -> 1 -> 2 -> 3 with a skip edge 0 -> 3. Longest path gives depths
    # 0,1,2,3 and an order; shortest gives 0,1,2,1 and a refusal.
    skip = bit_order(synthetic({0: [], 1: [0], 2: [1], 3: [2, 0]}),
                     ["f0", "f1", "f2", "f3"])
    report(skip.get("method") == "carry chain, by ripple depth"
           and skip.get("chains") == [["f0", "f1", "f2", "f3"]],
           "a chain with a skip edge orders by longest path, not shortest",
           f"{skip.get('method')}")
    # And the diamond, which must be refused. It does NOT discriminate the two
    # rules; it is here because refusing is the right answer and a version that
    # ordered it would be wrong.
    diamond = bit_order(synthetic({0: [], 1: [0], 2: [0], 3: [0, 1, 2]}),
                        ["f0", "f1", "f2", "f3"])
    report(diamond.get("method") is None,
           "a diamond is refused, two bits sharing a depth is no order",
           f"{diamond.get('why', '')[:52]}")
    return problems


# Implementations wrong in ways somebody would plausibly write.
def _spatial_manhattan(graph, positions, link_rows=stage4.LINK_ROWS):
    limit = link_rows * stage4.ROW_HEIGHT
    scaled = {k: v for k, v in positions.items()}
    original = math.hypot
    try:
        math.hypot = lambda dx, dy: abs(dx) + abs(dy)      # noqa: E731
        return stage4.spatial_groups(graph, scaled, link_rows)
    finally:
        math.hypot = original


def _spatial_strict(graph, positions, link_rows=stage4.LINK_ROWS):
    """`<` where the definition says `<=`. Two flops exactly at the threshold
    stop being neighbours, which is one row height on a placed design."""
    original = math.hypot
    try:
        math.hypot = lambda dx, dy: original(dx, dy) + 1e-9   # noqa: E731
        return stage4.spatial_groups(graph, positions, link_rows)
    finally:
        math.hypot = original


def _bit_order_keeping_self_edges(graph, members):
    """Self edges kept. Every held register has one -- Q back to its own D --
    so a chain decomposition that keeps them sees a successor everywhere."""
    inside = set(members)
    fanin, fanout = stage4.flop_edges(graph)
    before = {f: sorted(fanin.get(f, set()) & inside) for f in members}
    after = {f: sorted(fanout.get(f, set()) & inside) for f in members}
    if all(len(before[f]) <= 1 and len(after[f]) <= 1 for f in members):
        chains, seen = [], set()
        for start in sorted(f for f in members if not before[f]):
            chain, node = [], start
            while node is not None and node not in seen:
                seen.add(node)
                chain.append(node)
                node = after[node][0] if after[node] else None
            chains.append(chain)
        if len(seen) == len(members):
            return {"method": "shift chain, following D <- Q",
                    "chains": chains, "ordered": len(members), "why": ""}
    return {"method": None, "chains": [], "ordered": 0, "why": "kept self edges"}


def _bit_order_shortest_path(graph, members):
    """Ripple depth as the SHORTEST path. A carry chain with any skip edge
    then has two bits at one depth and is refused."""
    inside = set(members)
    fanin, _fanout = stage4.flop_edges(graph)
    before = {f: sorted((fanin.get(f, set()) & inside) - {f}) for f in members}
    depth, seen = {}, set()

    def ripple(node):
        if node in depth:
            return depth[node]
        if node in seen:
            raise ValueError("cycle")
        seen.add(node)
        depth[node] = 1 + min((ripple(p) for p in before[node]), default=-1)
        seen.discard(node)
        return depth[node]

    try:
        for flop in members:
            ripple(flop)
    except (ValueError, RecursionError):
        return {"method": None, "chains": [], "why": "cycle"}
    if len(set(depth.values())) == len(members):
        return {"method": "carry chain, by ripple depth",
                "chains": [sorted(members, key=lambda f: depth[f])],
                "ordered": len(members), "why": ""}
    return {"method": None, "chains": [], "why": "depths repeat"}


WRONG = {
    "single linkage on Manhattan distance rather than Euclidean":
        (_spatial_manhattan, stage4.bit_order),
    "a threshold that excludes the distance it names":
        (_spatial_strict, stage4.bit_order),
    "a chain decomposition that keeps a held register's self edge":
        (stage4.spatial_groups, _bit_order_keeping_self_edges),
    "ripple depth taken as the shortest path":
        (stage4.spatial_groups, _bit_order_shortest_path),
}


def load(target):
    path = os.path.join("out", target, "graph.json")
    if not os.path.exists(path):
        sys.exit(f"{path} missing; run tools/stage3_graph.py {target}")
    with open(path, encoding="utf-8") as handle:
        graph = json.load(handle)
    positions = stage4.placements(target)
    if not positions:
        sys.exit(f"out/{target}/instances.json missing; run "
                 f"tools/stage1_cells.py {target}")
    return graph, positions


def selftest(target):
    graph, positions = load(target)
    print(f"the audit against implementations that are wrong on purpose, on "
          f"{target}\n")
    problems = check(stage4.spatial_groups, stage4.bit_order, graph, positions,
                     verbose=False)
    if problems:
        print(f"  the real implementation does not pass, so nothing below "
              f"would mean anything:")
        for problem in problems[:4]:
            print(f"    {problem.strip()}")
        print("\nRESULT: fail")
        return 1
    print("  the real implementation passes first\n")

    missed = []
    for label, (spatial, order) in WRONG.items():
        found = check(spatial, order, graph, positions, verbose=False)
        print(f"  {'caught' if found else 'MISSED'}  {label}")
        if found:
            print(f"          {found[0].strip()}")
        else:
            missed.append(label)
    print(f"\n  {len(WRONG) - len(missed)}/{len(WRONG)} caught")
    if missed:
        print("\nRESULT: fail, this audit does not notice: " + ", ".join(missed))
        return 1
    print("\nRESULT: pass, every wrong implementation is caught and the real "
          "one is not")
    return 0


def run(target):
    graph, positions = load(target)
    print(f"target {target}: {len(graph['flipflops'])} flip flops, "
          f"{sum(1 for f in graph['flipflops'] if f in positions)} of them "
          f"placed\n")
    problems = check(stage4.spatial_groups, stage4.bit_order, graph, positions)
    if problems:
        print(f"\nRESULT: fail, {len(problems)} check(s) did not hold")
        return 1
    print(f"\nRESULT: pass. Neither criterion has a corpus number behind it -- "
          f"nothing in\n  out/synth/ was ever placed, and the corpus declares "
          f"register sizes rather than\n  bit orders -- so this is what stands "
          f"in place of one.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    selftest_mode = "--selftest" in args
    args = [a for a in args if a != "--selftest"]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/verify_grouping.py "
                 f"[{' | '.join(TARGETS)}] [--selftest]")
    sys.exit(selftest(args[0]) if selftest_mode else run(args[0]))
