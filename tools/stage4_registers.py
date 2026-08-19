"""Stage 4, first step. The flip flops of a netlist, gathered into registers.

Every later detector needs this. "These eight flops are a counter" cannot be
said before "these eight flops are one thing", and a flat netlist does not say
which flops belong together -- the puzzle's 92 sit in no declared order, under no
shared name, on sixteen different clock nets.

Three criteria are computed and **none is committed**, because measurement
refuted the first attempt at choosing between them.

    control signature      116/126   clock root, reset root and level, set root
                                     and level, hold net
    colour refinement       96/126   shatters a shift register: the chain gives
                                     every bit a distinct colour once its
                                     predecessor has one
    connected components    74/126   shatters a plain register, whose bits do
                                     not depend on one another at all

Those corpus numbers are nearly meaningless on their own, and `--score` now
prints the reason beside them: **108 of the corpus's 126 netlists hold exactly
one register**, so a criterion that returns one group and does nothing else
scores 108/126. The control signature's real margin is eight circuits, and on
the 18 netlists where the question is not trivial it gets 8.

On the warm up, whose true partition the DEF states outright -- two eight bit
shift registers, `sr_a` and `sr_b` -- the control signature is **wrong** and
connected components is right. See `tools/verify_blocks.py`. The two shift
registers share a clock, a reset and an enable, and no control signature can
separate registers that share all three.

So the three are **complementary and not ranked**, and presenting them as a
ranking was the mistake. Each is reported, and where they disagree that
disagreement is the residue: it is where a person has to read, and it is not
resolved by picking whichever scored best on a corpus that mostly does not ask
the question.

Usage:
    python tools/stage4_registers.py warmup
    python tools/stage4_registers.py puzzle
    python tools/stage4_registers.py --score      # against the corpus
    python tools/stage4_registers.py --compare    # all three criteria
"""

import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage1_cells import TARGETS

OUT_DIR = "out/synth"
REFINEMENT_ROUNDS = 3


def flop_edges(graph):
    """fanin[f] = the flops whose Q is in f's data cone. fanout is the reverse.

    Read out of stage 3's cone membership rather than walked again here, so this
    depends on something `stage3_crosscheck.py` derives a second time.
    """
    fanin, fanout = defaultdict(set), defaultdict(set)
    for source, record in graph["flipflops"].items():
        for root in graph["nets"].get(record["q"], {}).get("cones", ()):
            if not root.endswith(".data"):
                continue
            target = root[: -len(".data")]
            if target in graph["flipflops"]:
                fanin[target].add(source)
                fanout[source].add(target)
    return fanin, fanout


def control_signature(graph, instance):
    """What a register is written and cleared by, which its bits share.

    The hold net is included, which is why this is not simply "same clock and
    reset": in the puzzle it separates twelve flops from the other seventy two.
    It is also the weakest term, because stage 3 finds a hold structurally and
    that search is a measured lower bound -- four ways of hiding a hold are
    recorded in `verify_corpus.py`, and a hold it misses is a split missed here.
    """
    record = graph["flipflops"][instance]
    hold = record.get("enable") or {}
    return (record.get("clock_root"), bool(record.get("clock_inverted")),
            record.get("reset_root"), record.get("reset_level"),
            record.get("set_root"), record.get("set_level"),
            hold.get("net"), hold.get("held_when"))


def control_groups(graph):
    groups = defaultdict(list)
    for instance in sorted(graph["flipflops"]):
        groups[control_signature(graph, instance)].append(instance)
    return dict(groups)


def refinements(graph, rounds=REFINEMENT_ROUNDS):
    """Successive splits of the control groups, as candidates and not answers.

    Each round recolours a flop by its own colour and the *sets* of colours it
    reads and feeds. Sets rather than multisets: a counter's bit 0 depends on one
    flop and its bit 7 on eight, so a multiset separates them and destroys the
    register, while both depend on flops of the same colour and a set does not.

    Run to a fixed point this shatters chains, so it is not run to a fixed point.
    The rounds are reported and the caller decides.
    """
    fanin, fanout = flop_edges(graph)
    colour = {f: control_signature(graph, f) for f in graph["flipflops"]}
    levels = []
    for _ in range(rounds):
        fresh = {f: (colour[f],
                     frozenset(colour[g] for g in fanin.get(f, ())),
                     frozenset(colour[g] for g in fanout.get(f, ())))
                 for f in colour}
        order = {s: i for i, s in enumerate(sorted(set(fresh.values()), key=str))}
        fresh = {f: order[s] for f, s in fresh.items()}
        if len(set(fresh.values())) == len(set(colour.values())):
            break
        colour = fresh
        grouped = defaultdict(list)
        for flop, tag in colour.items():
            grouped[tag].append(flop)
        levels.append(sorted((sorted(v) for v in grouped.values()),
                             key=lambda g: (-len(g), g[0])))
    return levels


def register_graph(graph, groups):
    """Which register feeds which, at the level a person can read.

    738 cells and 723 nets is not a picture. Fifteen boxes and the arrows
    between them is, and it is what the block partition has to become before
    anybody can say what the circuit does.
    """
    fanin, _ = flop_edges(graph)
    owner = {f: name for name, members in groups.items() for f in members}
    edges = defaultdict(set)
    for flop, sources in fanin.items():
        for source in sources:
            if owner.get(source) != owner.get(flop):
                edges[owner[source]].add(owner[flop])

    ports = {}
    for name, port in graph["ports"].items():
        for bit in port["bits"]:
            ports[bit] = (name, port["direction"])
    reads, drives = defaultdict(set), defaultdict(set)
    for name, members in groups.items():
        # what it drives: a primary output in the cone of any of its Q nets
        for flop in members:
            q = graph["flipflops"][flop]["q"]
            for root in graph["nets"].get(q, {}).get("cones", ()):
                if root.startswith("port."):
                    drives[name].add(root[len("port."):].split("[")[0])
        # what it reads: a primary input whose cone contains any of its D roots
        wanted = {f"{f}.data" for f in members}
        for bit, (port, direction) in ports.items():
            if direction != "input":
                continue
            if wanted & set(graph["nets"].get(bit, {}).get("cones", ())):
                reads[name].add(port)
    return edges, reads, drives


def describe(graph, name_groups):
    """One line per register: width, control, and what it is made of.

    Control nets are reported under the names stage 2 gave them. `clk` says
    something; `n5` says only that a tool numbered it.
    """
    named = lambda net: graph["net_names"].get(net, net) if net else None
    rows = []
    for name, members in sorted(name_groups.items()):
        record = graph["flipflops"][members[0]]
        kinds = Counter(graph["flipflops"][f]["cell"].split("__")[-1]
                        for f in members)
        rows.append({
            "register": name,
            "width": len(members),
            "clock": named(record.get("clock_root")),
            "clock_inverted": bool(record.get("clock_inverted")),
            "reset": named(record.get("reset_root")),
            "reset_level": record.get("reset_level"),
            "set": named(record.get("set_root")),
            "set_level": record.get("set_level"),
            "hold": named((record.get("enable") or {}).get("net")),
            "cells": dict(kinds),
            "flops": members,
        })
    return rows


def group_names(graph, groups):
    """Stable names, from the widest group down, so reruns agree."""
    ordered = sorted(groups.values(), key=lambda m: (-len(m), m[0]))
    return {f"R{index}": members for index, members in enumerate(ordered)}


def analyse(graph):
    groups = group_names(graph, control_groups(graph))
    levels = refinements(graph)
    rows = describe(graph, groups)
    edges, reads, drives = register_graph(graph, groups)

    owner = {f: name for name, members in groups.items() for f in members}
    splits = {}
    if levels:
        finest = levels[-1]
        for name, members in groups.items():
            pieces = defaultdict(list)
            for group in finest:
                for flop in group:
                    if owner.get(flop) == name:
                        pieces[id(group)].append(flop)
            if len(pieces) > 1:
                splits[name] = sorted((sorted(v) for v in pieces.values()),
                                      key=lambda g: (-len(g), g[0]))
    return {"registers": rows, "edges": {k: sorted(v) for k, v in edges.items()},
            "reads": {k: sorted(v) for k, v in reads.items()},
            "drives": {k: sorted(v) for k, v in drives.items()},
            "candidate_splits": splits,
            "refinement_sizes": [[len(g) for g in level] for level in levels]}


def run(target):
    path = os.path.join("out", target, "graph.json")
    if not os.path.exists(path):
        sys.exit(f"{path} missing; run tools/stage3_graph.py {target}")
    with open(path, encoding="utf-8") as handle:
        graph = json.load(handle)

    result = analyse(graph)
    rows = result["registers"]
    print(f"target {target}: {len(graph['flipflops'])} flip flops")
    print(f"\nwhat each criterion says, none of them committed")
    for name, criterion in CRITERIA.items():
        sizes = sorted((len(m) for m in criterion(graph).values()), reverse=True)
        print(f"  {name:<32} {sizes}")
    print(f"\nthe rest of this report follows the control signature, which is")
    print(f"the coarsest of the three. Where the others split further, that is")
    print(f"reported as a candidate split and not applied.\n")
    for row in rows:
        control = f"clock {row['clock']}"
        if row["clock_inverted"]:
            control += " (falling edge)"
        if row["reset"]:
            control += f", reset {row['reset']} {row['reset_level']}"
        if row["set"]:
            control += f", set {row['set']} {row['set_level']}"
        if row["hold"]:
            control += f", holds on {row['hold']}"
        print(f"  {row['register']:<5} {row['width']:>4} bits   {control}")
        print(f"        {row['cells']}")
        inputs = result["reads"].get(row["register"], [])
        outputs = result["drives"].get(row["register"], [])
        feeds = result["edges"].get(row["register"], [])
        if inputs:
            print(f"        reads ports {inputs}")
        if feeds:
            print(f"        feeds {feeds}")
        if outputs:
            print(f"        drives ports {outputs}")

    print(f"\nregister dependency graph")
    for source in sorted(result["edges"]):
        print(f"  {source} -> {', '.join(result['edges'][source])}")

    print(f"\ncandidate splits, reported and not applied")
    if not result["candidate_splits"]:
        print(f"  none: {REFINEMENT_ROUNDS} rounds of refinement separate nothing")
    for name, pieces in sorted(result["candidate_splits"].items()):
        print(f"  {name} ({len(pieces)} pieces): "
              f"{[len(p) for p in pieces]}")
    print(f"  group sizes after each round: {result['refinement_sizes']}")
    print(f"\n  Refinement is NOT applied. Measured on the corpus it scores")
    print(f"  48/63 against the control signature's 56/63, because it shatters")
    print(f"  a shift register. Where it disagrees, a person should read.")

    out = os.path.join("out", target, "registers.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1)
    print(f"\nwrote {out}")
    return 0


def expected_registers(truth, graph):
    """What the generator says the register partition is.

    Declared where it is not simply "every flop is one register", so that the
    score below is against the answer key and not against a rule invented here
    to make the score look better.
    """
    if "registers" in truth:
        return sorted(truth["registers"], reverse=True)
    return [len(graph["flipflops"])]


def connected_components(graph):
    """Control groups, then split by weak connectivity of the flop graph.

    The first alternative, and it loses badly: a plain register's bits do not
    depend on one another at all, so every one of them becomes its own group.
    """
    fanin, fanout = flop_edges(graph)
    out = {}
    for signature, members in control_groups(graph).items():
        inside, seen = set(members), set()
        for start in members:
            if start in seen:
                continue
            stack, group = [start], []
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                group.append(node)
                for other in fanin.get(node, set()) | fanout.get(node, set()):
                    if other in inside:
                        stack.append(other)
            out[(signature, group[0])] = sorted(group)
    return out


def refined_to_fixed_point(graph):
    """Control groups, then colour refinement run all the way.

    The second alternative. It separates registers that share control, which is
    exactly what the committed criterion cannot do -- and it shatters a shift
    register, because a chain hands every bit a distinct colour once its
    predecessor has one. It loses on more circuits than it wins.
    """
    levels = refinements(graph, rounds=200)
    if not levels:
        return control_groups(graph)
    return {index: members for index, members in enumerate(levels[-1])}


CRITERIA = {
    "control signature": control_groups,
    "+ connected components": connected_components,
    "colour refinement, fixed point": refined_to_fixed_point,
}


def compare():
    """Every criterion against the same answer key, in one run."""
    with open(f"{OUT_DIR}/index.json", encoding="utf-8") as handle:
        entries = json.load(handle)["circuits"]
    tally = {name: 0 for name in CRITERIA}
    total = 0
    for entry in entries:
        directory = entry.get("dir", f"{OUT_DIR}/{entry['name']}")
        if not os.path.exists(f"{directory}/graph.json"):
            continue
        with open(f"{directory}/graph.json", encoding="utf-8") as handle:
            graph = json.load(handle)
        if not graph["flipflops"]:
            continue
        with open(f"{directory}/truth.json", encoding="utf-8") as handle:
            truth = json.load(handle)
        expected = expected_registers(truth, graph)
        total += 1
        for name, criterion in CRITERIA.items():
            got = sorted((len(m) for m in criterion(graph).values()), reverse=True)
            tally[name] += got == expected
    print(f"register grouping criteria, over {total} netlists with a declared "
          f"partition\n")
    for name, hits in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {hits:>4}/{total}   {name}")
    print(f"\n  The two alternatives fail in mirror image. Connected components")
    print(f"  shatters a plain register, whose bits do not depend on one")
    print(f"  another. Refinement shatters a shift register, whose chain gives")
    print(f"  every bit a distinct colour. Neither failure is a tuning problem.")
    return 0


def score():
    """Sensitivity of the committed criterion, on circuits with a known answer."""
    with open(f"{OUT_DIR}/index.json", encoding="utf-8") as handle:
        entries = json.load(handle)["circuits"]
    exact, wrong, held_out = 0, [], Counter()
    for entry in entries:
        directory = entry.get("dir", f"{OUT_DIR}/{entry['name']}")
        if not os.path.exists(f"{directory}/graph.json"):
            continue
        with open(f"{directory}/graph.json", encoding="utf-8") as handle:
            graph = json.load(handle)
        if not graph["flipflops"]:
            continue
        with open(f"{directory}/truth.json", encoding="utf-8") as handle:
            truth = json.load(handle)
        expected = expected_registers(truth, graph)
        got = sorted((len(m) for m in control_groups(graph).values()),
                     reverse=True)
        if got == expected:
            exact += 1
            held_out["exact, held out" if entry["held_out"] else "exact"] += 1
        else:
            wrong.append((entry["name"], entry.get("variant"), truth["family"],
                          expected, got))
    total = exact + len(wrong)
    print(f"register grouping by control signature, over the corpus")
    print(f"  {exact}/{total} netlists partitioned exactly {dict(held_out)}")

    # The null model, printed here rather than left for somebody to think of.
    # A score a criterion that does nothing also achieves is not a result, and
    # this one very nearly is: most of the corpus holds a single register.
    trivial, single = 0, 0
    for entry in entries:
        directory = entry.get("dir", f"{OUT_DIR}/{entry['name']}")
        if not os.path.exists(f"{directory}/graph.json"):
            continue
        with open(f"{directory}/graph.json", encoding="utf-8") as handle:
            graph = json.load(handle)
        if not graph["flipflops"]:
            continue
        with open(f"{directory}/truth.json", encoding="utf-8") as handle:
            declared = expected_registers(json.load(handle), graph)
        single += len(declared) == 1
        trivial += declared == [len(graph["flipflops"])]
    print(f"  {trivial}/{total} would be got right by a criterion that returns "
          f"one group and does nothing else")
    print(f"  {total - single}/{total} netlists declare more than one register, "
          f"which is where the question is real")
    hard = [w for w in wrong]
    print(f"  of those {total - single}, this criterion gets "
          f"{total - single - len(hard)}")
    print(f"\n  On the warm up, whose true partition the DEF states, it is "
          f"wrong: see tools/verify_blocks.py")
    print(f"\n  the {len(wrong)} it does not get:")
    for name, variant, family, expected, got in wrong:
        print(f"    {name}[{variant}]  {family}")
        print(f"      expected {expected}")
        print(f"      got      {got}")
    families = Counter(w[2] for w in wrong)
    print(f"\n  by family: {dict(families)}")
    print(f"  Every one is a circuit built from several registers that share a")
    print(f"  clock, a reset and a hold. The criterion cannot see a boundary")
    print(f"  that no control signal marks, and refinement, which can, breaks")
    print(f"  more than it fixes. This is the residue stage 4 reports rather")
    print(f"  than the failure it hides.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--score"]:
        sys.exit(score())
    if args == ["--compare"]:
        sys.exit(compare())
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage4_registers.py "
                 f"[{' | '.join(TARGETS)} | --score | --compare]")
    sys.exit(run(args[0]))
