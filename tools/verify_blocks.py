"""Stage 4 against the warm up's own hierarchy, which the repository has had
all along.

`puzzle/warmup/03_post_place_and_route.def` names every placed instance with the
hierarchy it came from -- `sr_a/_16_`, `add0/_31_`, `cmp0/_02_` -- and
`01_netlist.v` carries the same names. That is an exact block partition of a
*real* design: not a corpus we wrote, not a shape we chose, the actual answer.

It was never used. Stage 4's register grouping was scored only against the
synthetic corpus, where 108 of 126 circuits hold exactly one register, so a
criterion that returns one group scores 86% and says nothing. This is the test
that says something.

**Nothing here adjusts what counts as a register to make the score better.** The
DEF says the warm up holds two eight bit registers; a criterion answering "one
of sixteen" is wrong, and is reported wrong.

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
from stage4_registers import (control_groups, connected_components,
                              refined_to_fixed_point)

DEF_PATH = "puzzle/warmup/03_post_place_and_route.def"
TARGET = "warmup"

CRITERIA = {
    "control signature": control_groups,
    "connected components": connected_components,
    "colour refinement, fixed point": refined_to_fixed_point,
    # The null model. Any score that this also achieves is not a result, and
    # printing it beside the others is the only way that stays visible.
    "everything is one register": lambda g: {"all": list(g["flipflops"])},
    "every flop is its own": lambda g: {f: [f] for f in g["flipflops"]},
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

    print(f"\nstage 4's criteria against it")
    results = {}
    for name, criterion in CRITERIA.items():
        got = sorted((len(m) for m in criterion(graph).values()), reverse=True)
        results[name] = got
        verdict = "CORRECT" if got == expected else "wrong"
        print(f"  {name:<32} {str(got):<16} {verdict}")

    committed = "control signature"
    if results[committed] != expected:
        print(f"\n  The committed criterion is {committed}, and it is wrong "
              f"here.")
        print(f"  It merges the two shift registers because they share a clock,")
        print(f"  a reset and an enable, and nothing in the control signature")
        print(f"  can separate two registers that share all three.")
        winners = [n for n, g in results.items()
                   if g == expected and not n.startswith(("everything", "every flop"))]
        if winners:
            print(f"  {winners} get it right, and one of them is the criterion")
            print(f"  the corpus score ranked last. The three are complementary")
            print(f"  and were presented as a ranking, which was a mistake.")
        print("\nRESULT: fail")
        return 1

    print("\nRESULT: pass")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args not in ([], ["--show"]):
        sys.exit("usage: python tools/verify_blocks.py [--show]")
    sys.exit(run(show=bool(args)))
