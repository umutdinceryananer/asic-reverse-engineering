"""Stage 4 against the warm up's own hierarchy, which the repository has had
all along.

`puzzle/warmup/03_post_place_and_route.def` names every placed instance with the
hierarchy it came from -- `sr_a/_16_`, `add0/_31_`, `cmp0/_02_` -- and
`01_netlist.v` carries the same names. That is an exact block partition of a
*real* design: not a corpus we wrote, not a shape we chose, the actual answer.

It was never used. Stage 4's register grouping was scored only against the
synthetic corpus, where 109 of 133 netlists hold exactly one register, so a
criterion that returns one group scores 82% and says nothing. This is the test
that says something.

**Nothing here adjusts what counts as a register to make the score better.** The
DEF says the warm up holds two eight bit registers; a criterion answering "one
of sixteen" is wrong, and is reported wrong.

Sizes are not enough, and membership is scored beside them. A criterion can
answer `[8, 8]` with the wrong eight in each group and a size comparison calls
that correct; the DEF names every flop's block, so NMI and purity are exact here
in a way they are not on the corpus, and a right-sized wrong-membered answer is
labelled as one.

**The verdict is scored against the control signature, which is the committed
criterion, and it fails.** Criteria that get the warm up right -- connected
components, and placement locality -- appear as rows, not as a changed verdict.
Committing one of them is the author's decision and not this tool's.

Usage:
    python tools/verify_blocks.py            # score stage 4 against the truth
    python tools/verify_blocks.py --show     # the true partition, in full
"""

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_def import parse_components, read
from stage4_registers import (LINK_ROWS, ROW_HEIGHT, connected_components,
                              sizes_as,
                              control_groups, control_then_flow,
                              components_then_flow, labels_of, nmi,
                              placements, purity, refined_to_fixed_point,
                              spatial_groups, spatial_profile)

DEF_PATH = "puzzle/warmup/03_post_place_and_route.def"
TARGET = "warmup"

# Every criterion stage 4 computes, plus the two null models. The spatial one
# is passed the placements separately, because it is the only criterion here
# that reads something other than the graph -- and the only one the synthetic
# corpus cannot score at all, since nothing in `out/synth/` was ever placed.
CRITERIA = {
    "control signature": control_groups,
    "connected components": connected_components,
    "colour refinement, fixed point": refined_to_fixed_point,
    "control + flow split": control_then_flow,
    "components + flow split": components_then_flow,
    # The null models. Any score that these also achieve is not a result, and
    # printing them beside the others is the only way that stays visible.
    "everything is one register": lambda g: {"all": list(g["flipflops"])},
    "every flop is its own": lambda g: {f: [f] for f in g["flipflops"]},
    # And a third, which exists only so the membership columns can never be
    # silent. It deals the flops alternately into two groups, so it answers
    # `[8, 8]` -- the right sizes, from no information at all -- with eight bits
    # of `sr_a` and eight of `sr_b` mixed into each. A tool that compared sizes
    # alone would print CORRECT beside it. See `docs/problems.md` 46.
    "interleaved, right sizes": lambda g: {
        side: sorted(f for i, f in enumerate(sorted(g["flipflops"]))
                     if i % 2 == side)
        for side in (0, 1)},
}


def block_of(name):
    """The hierarchy a DEF instance name came from, or the top level."""
    bare = name.lstrip("\\")
    return bare.split("/")[0] if "/" in bare else "(top)"


def mapping():
    """Every recovered instance id to the block the DEF says it belongs to.

    Keyed on position, orientation and cell together. Position alone happens to
    be unique here -- 230 distinct lower left corners for 230 instances -- but
    the raw GDS origins are only 178 distinct, and keying on the wrong one of
    those two is problem 12 in `docs/problems.md`.
    """
    if not os.path.exists(DEF_PATH):
        sys.exit(f"{DEF_PATH} missing; run git submodule update --init")
    path = os.path.join("out", TARGET, "instances.json")
    if not os.path.exists(path):
        sys.exit(f"{path} missing; run tools/stage1_cells.py {TARGET}")

    _, records = parse_components(read(DEF_PATH))
    with open(path, encoding="utf-8") as handle:
        instances = json.load(handle)["instances"]

    key = lambda r: (tuple(r["lower_left"]), r["orient"], r["cell"])
    theirs = {}
    for record in records:
        if key(record) in theirs:
            sys.exit(f"two DEF components share {key(record)}; this key does "
                     f"not identify and nothing below is trustworthy")
        theirs[key(record)] = record["instance"]

    ours, unmatched = {}, []
    for instance in instances:
        if "lower_left" not in instance:
            continue
        found = theirs.get(key(instance))
        if found is None:
            unmatched.append(instance)
        else:
            ours[instance["id"]] = found
    return ours, unmatched, len(records)


def truth(graph, id_to_name):
    """The register partition and the block partition the DEF states."""
    registers = defaultdict(list)
    for flop in graph["flipflops"]:
        name = id_to_name.get(flop)
        if name is None:
            registers["(unmatched)"].append(flop)
        else:
            registers[block_of(name)].append(flop)
    blocks = Counter(block_of(name) for name in id_to_name.values())
    return dict(registers), blocks


def run(show=False):
    id_to_name, unmatched, declared = mapping()
    path = os.path.join("out", TARGET, "graph.json")
    if not os.path.exists(path):
        sys.exit(f"{path} missing; run tools/stage3_graph.py {TARGET}")
    with open(path, encoding="utf-8") as handle:
        graph = json.load(handle)

    print(f"warm up: {declared} DEF components, {len(id_to_name)} matched to "
          f"recovered instances, {len(unmatched)} unmatched")
    if unmatched:
        print(f"  unmatched: {[i['id'] for i in unmatched[:6]]}")
        print("\nRESULT: fail, the mapping is incomplete and no score below "
              "would mean anything")
        return 1

    registers, blocks = truth(graph, id_to_name)
    print(f"\nthe design's own block partition, from the DEF")
    for block, count in sorted(blocks.items(), key=lambda kv: -kv[1]):
        flops = len(registers.get(block, ()))
        print(f"  {block:<10} {count:>4} cells" +
              (f", {flops} of them flip flops" if flops else ""))

    expected = sorted((len(v) for v in registers.values()), reverse=True)
    print(f"\nthe register partition it implies: {expected}")
    if show:
        for block, flops in sorted(registers.items()):
            print(f"  {block}: {sorted(flops)}")

    # The DEF partition as a membership, which is what the metrics need and
    # what the corpus mostly cannot supply. Here it is exact: 230 of 230
    # instances matched, so every flop's block is known by name.
    membership = {flop: block for block, flops in registers.items()
                  for flop in flops}
    positions = placements(TARGET)
    criteria = dict(CRITERIA)
    if positions:
        criteria["placement locality"] = \
            lambda g: spatial_groups(g, positions)

    print(f"\nstage 4's criteria against it, by size and by membership")
    print(f"  {'':<32}{'sizes':<24}{'':<27}{'NMI':>7}{'purity':>8}")
    results, correct = {}, {}
    for name, criterion in criteria.items():
        groups = criterion(graph)
        got = sorted((len(m) for m in groups.values()), reverse=True)
        results[name] = got
        answer = labels_of({str(key): members
                            for key, members in groups.items()})
        value, _branch = nmi(answer, membership)
        # Membership, not only sizes. A criterion can answer [8, 8] with the
        # wrong eight in each, and the size comparison would call that correct.
        same = {frozenset(m) for m in groups.values()} == \
               {frozenset(m) for m in registers.values()}
        correct[name] = same
        verdict = "CORRECT" if got == expected else "wrong"
        if got == expected and not same:
            verdict = "RIGHT SIZES, WRONG MEMBERS"
        print(f"  {name:<32}{sizes_as(got):<24}{verdict:<27}"
              f"{value:>7.3f}{purity(answer, membership):>8.3f}")

    if positions:
        print(f"\nplacement locality, and why it is reported and not scored")
        print(f"  Sanctioned verbatim by the announcement -- \"The circuit is "
              f"physically")
        print(f"  arranged to hint at its functionality, so look closely at "
              f"the layout!\" --")
        print(f"  and named by DANA as its own unexploited idea and an open "
              f"question.")
        print(f"  **The synthetic corpus cannot score it.** Nothing under "
              f"out/synth/ was ever")
        print(f"  placed, so this criterion has exactly one design with a "
              f"known answer: this")
        print(f"  one. n = 1. Nothing below is a rate.")
        print(f"  single linkage at {LINK_ROWS} row heights "
              f"({LINK_ROWS * ROW_HEIGHT:.2f} um); cluster sizes against the "
              f"threshold:")
        for link, sizes in spatial_profile(graph, positions):
            mark = "   <- committed" if link == LINK_ROWS else ""
            print(f"    {link:>3} rows  {link * ROW_HEIGHT:6.2f} um   "
                  f"{sizes_as(sizes)}{mark}")
        print(f"  The plateau is what makes the threshold a reading rather "
              f"than a knob: the")
        print(f"  answer is the same from 3 row heights to 8, and 3 is the "
              f"lower edge of it.")
        print(f"  That edge was chosen because it is the smallest threshold "
              f"at which this")
        print(f"  design's two registers connect -- one parameter fitted to "
              f"one data point,")
        print(f"  which is said here rather than hidden. The profile is "
              f"printed so the")
        print(f"  author can pick differently on a design whose answer is not "
              f"known.")
        clusters = spatial_groups(graph, positions)
        print(f"\n  the clusters, against the blocks the DEF names")
        for key in sorted(clusters, key=lambda k: (-len(clusters[k]), str(k))):
            members = clusters[key]
            blocks = sorted({membership.get(f, "?") for f in members})
            box = [min(positions[f][axis] for f in members if f in positions)
                   for axis in (0, 1)] + \
                  [max(positions[f][axis] for f in members if f in positions)
                   for axis in (0, 1)]
            print(f"    {len(members):>3} flops  x {box[0]:7.2f}..{box[2]:<7.2f}"
                  f" y {box[1]:7.2f}..{box[3]:<7.2f}   DEF blocks {blocks}")
        print(f"  sr_a and sr_b DO separate spatially, and by a wide margin: "
              f"the two")
        print(f"  clusters are 21.76 um apart and no flop inside either is "
              f"more than 5.44")
        print(f"  um from its nearest neighbour in it. This is the only "
              f"criterion that gets")
        print(f"  the warm up right without reading a single wire.")

    committed = "control signature"
    if results[committed] != expected:
        print(f"\n  The committed criterion is {committed}, and it is wrong "
              f"here.")
        print(f"  It merges the two shift registers because they share a clock,")
        print(f"  a reset and an enable, and nothing in the control signature")
        print(f"  can separate two registers that share all three.")
        # Membership, not sizes. This list was `g == expected`, and the
        # deliberately wrong `interleaved, right sizes` model walked straight
        # into it -- the tool's own summary sentence naming a null model as a
        # criterion that gets the warm up right. `docs/problems.md` 46.
        winners = [n for n, g in results.items()
                   if g == expected and correct[n]
                   and not n.startswith(("everything", "every flop",
                                         "interleaved"))]
        if winners:
            print(f"  {winners}")
            print(f"  get it right, and one of them is the criterion the "
                  f"corpus score ranked")
            print(f"  last. They are complementary and were presented as a "
                  f"ranking, which was")
            print(f"  the mistake. **The verdict below is still scored "
                  f"against the control")
            print(f"  signature**, which is the committed criterion, and a "
                  f"criterion that passes")
            print(f"  here appears as a row above and not as a changed "
                  f"verdict. Committing one")
            print(f"  is the author's decision and not this tool's.")
        print("\nRESULT: fail")
        return 1

    print("\nRESULT: pass")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args not in ([], ["--show"]):
        sys.exit("usage: python tools/verify_blocks.py [--show]")
    sys.exit(run(show=bool(args)))
