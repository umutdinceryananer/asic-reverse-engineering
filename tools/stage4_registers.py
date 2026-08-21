"""Stage 4, first step. The flip flops of a netlist, gathered into registers.

Every later detector needs this. "These eight flops are a counter" cannot be
said before "these eight flops are one thing", and a flat netlist does not say
which flops belong together -- the puzzle's 92 sit in no declared order, under no
shared name, on sixteen different clock nets.

Criteria are computed and **none is committed**, because measurement refuted
the first attempt at choosing between them, and then refuted the ranking.

                                    exact/133      NMI   purity
    control signature                     117   0.0014   0.5062
    colour refinement                      97   0.1867     0.75
    + connected components                 80   0.5476     0.80
    null: one group, do nothing           109      0.0      0.5
    null: every flop its own                7   0.3733      1.0

**Exact match and NMI rank these in opposite orders.** Exact match compares
size multisets and is all or nothing; 109 of the corpus's 133 netlists hold
exactly one register, so a criterion that returns one group and does nothing
else scores 109/133 and the whole ranking is that majority talking. NMI and
purity above are over the ten netlists whose ground truth has more than one
class -- the ones that ask the question -- and there the control signature
scores the one-group null model's numbers to three decimal places.

The metrics, the membership ground truth they need, and the convention for the
0/0 case are below and in `docs/04-detectors.md`.

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

`--score` and `--compare` are gates and exit non-zero. They did not use to:
both ended in `return 0` whatever they measured, so a criterion returning one
group per flop scored 6/126 and still passed. What each one is expected to
measure is recorded in `RECORDED` and `RECORDED_CRITERIA` below, and a figure
that moves in either direction fails until somebody re-records it.

Usage:
    python tools/stage4_registers.py warmup
    python tools/stage4_registers.py puzzle
    python tools/stage4_registers.py --score      # gate: against the corpus
    python tools/stage4_registers.py --compare    # gate: every criterion
    python tools/stage4_registers.py --selftest   # gate: the metrics against
                                                  # a hand computed table
"""

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage1_cells import TARGETS

OUT_DIR = "out/synth"
REFINEMENT_ROUNDS = 3

# Task C's one parameter, recorded rather than tuned. Row height is a PDK fact
# -- sky130_fd_sc_hd, `docs/00-environment.md` -- and two flops within three row
# heights of each other are near neighbours on any placement this library can
# produce. `spatial_profile` prints the cluster count at every threshold from 1
# to 12 rows beside it, so a reader can see whether 3 sits in a plateau.
ROW_HEIGHT = 2.720
LINK_ROWS = 3

# What the corpus said the last time somebody looked at it and understood the
# answer. Recorded rather than only recomputed, because both entry points below
# used to end in an unconditional `return 0`: replacing the criterion with
# "every flop is its own register" took the score from 116/126 to 6/126 and the
# run still passed, which made --score a report wearing a gate's clothes.
#
# A number that falls below its recording fails. A number that rises is printed
# loudly and also fails, deliberately: an unexplained improvement is a change to
# something, and re-recording it has to be a decision rather than a side effect.
#
# Exact match is a size multiset comparison and needs no membership, so it is
# recorded over all 133. NMI and purity need one, so they are recorded over the
# subset that has one and the subset is recorded too.
RECORDED = {
    "exact": 117,           # netlists the control signature partitions exactly
    "netlists": 133,        # netlists with flops and a declared partition
    "null model": 109,      # what "one group, and do nothing" scores
    "multi": 24,            # netlists declaring more than one register
    "multi hits": 8,        # of those, what the control signature gets
    "membership": 119,      # netlists with a flop level ground truth at all
    "nmi": 0.9161,          # mean NMI over all of those
    "nmi over": 119,        # how many rows that was
    "purity": 0.9585,       # mean purity over all of those
    # The pair that means something, and the pair that indicts the committed
    # criterion. Over the ten netlists whose ground truth has more than one
    # class the control signature scores 0.0014 NMI against the one-group null
    # model's 0.0, and 0.5062 purity against its 0.5. On the question stage 4
    # exists to answer it is the null model to three decimal places.
    "nmi real": 0.0014,     # mean NMI where the truth has >1 class
    "purity real": 0.5062,  # mean purity there
    "real over": 10,        # and how many netlists that is
}

# Per criterion, for --compare. Same rule.
#
# `+ connected components` went 75 to 80 across two corpus additions, because
# `warmup_twin` and the warm up's own RTL are the shape it handles and the
# control signature cannot: two registers sharing every control signal. The
# control signature gets none of those six netlists, which is the point of
# adding them -- `verify_blocks.py` has been failing the warm up on exactly this
# since it was written, and until now nothing in the corpus agreed.
#
# It went up by five and not by six, and the one it misses is worth more than
# the five it gets. `adder_demo` and `adder_demo__fast` are the same RTL mapped
# two ways. On the base mapping all 16 holds survive as muxes and components
# answers [8, 8]. On the fast mapping only 11 do, and all three criteria come
# apart: [11, 5], then [3,2,2,2,2,1,1,1,1,1], then sixteen singletons. See
# `docs/problems.md` 45.
# **Exact match and NMI rank these three in opposite orders, and that is the
# most useful thing this file now measures.** Exact match puts the control
# signature first at 117 and connected components last at 80; over the ten
# netlists that actually ask the question, NMI puts connected components at
# 0.5476 and the control signature at 0.0014, which is the one-group null
# model's 0.0 to three places. The exact-match ranking was an artefact of the
# 109 netlists that declare one register, and `docs/references.md` section 3
# said so from the literature before anything here measured it.
RECORDED_CRITERIA = {
    "control signature": {"exact": 117, "nmi real": 0.0014,
                          "purity real": 0.5062},
    "colour refinement, fixed point": {"exact": 97, "nmi real": 0.1867,
                                       "purity real": 0.75},
    "+ connected components": {"exact": 80, "nmi real": 0.5476,
                               "purity real": 0.8},
    # DANA's split by successor/predecessor groupings, run standalone to a
    # fixpoint over two seeds. **It scores the all-singletons null model's
    # numbers, 0.3733 and 1.0, on exactly the ten netlists that ask the
    # question** -- because on those ten it *is* all singletons. Every one of
    # them is a shift register or a pair of them, and a chain hands each bit a
    # different predecessor group as soon as its predecessor has one.
    #
    # That is not DANA being wrong. DANA applies nine passes in ordered pairs
    # with a majority vote and never runs one to a fixpoint alone, which is
    # what this measures. The pass has a real advantage the numbers here do not
    # show, and `demonstrations()` below shows it instead.
    "control + flow split": {"exact": 91, "nmi real": 0.3733,
                             "purity real": 1.0},
    "+ components + flow split": {"exact": 49, "nmi real": 0.3733,
                                  "purity real": 1.0},
}


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


def bit_order(graph, members):
    """The order of the bits inside one register, where the structure gives one.

    Stage 4 has emitted registers as *sets* since it was written, and stage 7
    needs a word: `O[7:0]` is not the same eight flops in some other order, and
    an operand's bits carry different arithmetic weight. WordRev
    (`docs/references.md` section 3) derives the order from the direction data
    flows through the register, and this is that, in two shapes:

    **A shift chain.** Drop self edges -- a flop whose Q returns to its own D is
    holding, not shifting, and every held register has one -- and if what is
    left gives every bit at most one predecessor and at most one successor
    inside the group, the group decomposes into simple paths. Those are the
    chains, head first. Two disjoint paths is a normal answer and not a
    failure: the warm up's sixteen flops under one control signature are two
    chains of eight, which is the boundary the control signature cannot see
    said in a second language.

    **A carry chain.** Otherwise, if the induced graph is acyclic, the longest
    path to each bit is its ripple depth, and if those depths are distinct the
    register is ordered by them. A counter is this shape: bit *i* depends on
    every bit below it and on nothing above.

    **Otherwise nothing.** A plain register's bits do not depend on one another
    at all, so every depth is 0 and no order exists to derive. That is emitted
    as a fact -- `"method": null` with the reason -- and not as a guess, because
    a guessed bit order is worse than none: it is the kind of answer stage 7
    would build a string out of.
    """
    inside = set(members)
    fanin, fanout = flop_edges(graph)
    before = {f: sorted((fanin.get(f, set()) & inside) - {f}) for f in members}
    after = {f: sorted((fanout.get(f, set()) & inside) - {f}) for f in members}

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
            if all(len(chain) == 1 for chain in chains):
                # A plain register: no bit depends on another, so the "paths"
                # are all of length one and there is no order in them. Saying
                # "8 chains" here would be a decomposition wearing a bit
                # order's clothes.
                return {"method": None, "chains": [],
                        "why": f"the {len(members)} bits do not depend on one "
                               f"another; nothing here orders them"}
            return {"method": "shift chain, following D <- Q",
                    "chains": chains,
                    "why": f"{len(chains)} path(s) covering all "
                           f"{len(members)} bits, head first"}
        # Everything left is on a cycle: a ring counter, or a chain whose last
        # bit feeds its first. Reported rather than cut at an arbitrary bit.
        return {"method": None, "chains": [],
                "why": f"{len(members) - len(seen)} bits lie on a cycle; a "
                       f"ring has no first bit to name"}

    depth, mark = {}, {}

    def ripple(node):
        if node in depth:
            return depth[node]
        if mark.get(node):
            raise ValueError("cycle")
        mark[node] = True
        depth[node] = 1 + max((ripple(p) for p in before[node]), default=-1)
        mark[node] = False
        return depth[node]

    try:
        for flop in members:
            ripple(flop)
    except (ValueError, RecursionError):
        return {"method": None, "chains": [],
                "why": "the bits depend on one another cyclically, so no "
                       "ripple depth exists"}
    if len(set(depth.values())) == len(members):
        return {"method": "carry chain, by ripple depth",
                "chains": [sorted(members, key=lambda f: depth[f])],
                "why": f"{len(members)} distinct ripple depths, least "
                       f"dependent first"}
    return {"method": None, "chains": [],
            "why": f"{len(set(depth.values()))} distinct ripple depths over "
                   f"{len(members)} bits, and no chain: nothing here orders "
                   f"these bits"}


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
            # `flops` stays in instance order, because `stage4_cone.py` names a
            # boundary signal `R0[i]` by its position in this list and every
            # cone listing already written reads that way. The order below is a
            # separate field, and `verify_cone.py` checks it against the
            # arithmetic weights it derives on its own.
            "bit_order": bit_order(graph, members),
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
    positions = None
    print(f"target {target}: {len(graph['flipflops'])} flip flops")
    print(f"\nwhat each criterion says, none of them committed")
    short = sizes_as
    for name, criterion in CRITERIA.items():
        sizes = sorted((len(m) for m in criterion(graph).values()), reverse=True)
        print(f"  {name:<32} {short(sizes)}")
    positions = placements(target)
    if positions:
        sizes = sorted((len(m) for m in
                        spatial_groups(graph, positions).values()),
                       reverse=True)
        print(f"  {'placement locality':<32} {short(sizes)}")
    print(f"\nthe rest of this report follows the control signature, which "
          f"is the")
    print(f"coarsest of them. Where the others split further, that is reported")
    print(f"as a candidate split and not applied.\n")
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

    if positions:
        print(f"\nwhere the flops actually sit")
        print(f"  The announcement says the circuit is physically arranged to "
              f"hint at its")
        print(f"  functionality, so this is printed for a person to read "
              f"against that. Single")
        print(f"  linkage at {LINK_ROWS} row heights "
              f"({LINK_ROWS * ROW_HEIGHT:.2f} um), one recorded parameter; the "
              f"cluster count at")
        print(f"  every threshold from 1 to 12 rows is below it, so a plateau "
              f"or its absence")
        print(f"  is visible. **No corpus figure covers this criterion** -- "
              f"nothing under")
        print(f"  out/synth/ was ever placed -- and its only design with a "
              f"known answer is the")
        print(f"  warm up. See tools/verify_blocks.py.")
        clusters = spatial_groups(graph, positions)
        owner = {f: name for name, members in
                 group_names(graph, control_groups(graph)).items()
                 for f in members}
        for key in sorted(clusters, key=lambda k: (-len(clusters[k]), str(k))):
            members = clusters[key]
            placed = [f for f in members if f in positions]
            if not placed:
                continue
            xs = [positions[f][0] for f in placed]
            ys = [positions[f][1] for f in placed]
            inside = sorted({owner.get(f, "?") for f in members})
            print(f"    {len(members):>4} flops   x {min(xs):8.2f}..{max(xs):<8.2f}"
                  f" y {min(ys):8.2f}..{max(ys):<8.2f}   from {inside}")
        print(f"  cluster sizes against the threshold:")
        for link, sizes in spatial_profile(graph, positions):
            mark = "   <- committed" if link == LINK_ROWS else ""
            print(f"    {link:>3} rows  {link * ROW_HEIGHT:6.2f} um   "
                  f"{short(sizes)}{mark}")

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
    print(f"\n  Refinement is NOT applied, and neither is any other criterion.")
    print(f"  Where they disagree, that disagreement is the residue and a person")
    print(f"  reads it. For how the three score against a known answer run")
    print(f"  --compare, and tools/verify_blocks.py for the one real design")
    print(f"  whose partition is known. No score is quoted here, because this")
    print(f"  entry point does not measure one: the numbers that stood here were")
    print(f"  from a corpus two sizes ago and no run reproduced them.")

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


# --------------------------------------------------------------------------
# Metrics.
#
# Exact match on the size multiset is what this file has always scored, and it
# is all or nothing: an answer that gets 71 of a register's 72 bits right scores
# the same as one that gets none of them. Every partial credit on the puzzle's
# R0 -- which is the whole of what stage 4 has left to report -- rounds to
# "wrong".
#
# The literature this belongs to settled on normalised mutual information and
# purity instead; `docs/references.md` section 3 is where that reading is
# written down. Both are computed over a flop-level *membership* rather than
# over sizes, which the corpus does not declare, so `truth_membership` below
# recovers one where it can and refuses where it cannot.
#
# Neither metric replaces exact match, and the three are printed together
# because each one is blind to something the others see:
#
#   exact match   one group scores 109/133 here. All singletons scores 0.
#   NMI           one group scores 0, because a single cluster has no entropy
#                 and therefore no mutual information with anything.
#   purity        all singletons scores 1.0, exactly. Purity does not penalise
#                 over-splitting at all -- every cluster of one is pure -- so
#                 the claim that purity kills that degenerate is false, and the
#                 pair that does kill it is NMI with exact match. Measured
#                 below and printed rather than asserted.

NMI_NORMALISATION = "arithmetic mean, 2 I(C;T) / (H(C) + H(T))"

# A vector bit as yosys leaves it on a net name: `a_reg[4]` is bit 4 of the
# register `a_reg`.
VECTOR_BIT = re.compile(r"\[\d+\]$")


def sizes_as(sizes):
    """A partition's sizes, short enough to read when most of them are ones."""
    ones = sizes.count(1)
    rest = [size for size in sizes if size > 1]
    if not ones:
        return str(rest)
    tail = f"{ones} singleton" + ("s" if ones > 1 else "")
    return tail if not rest else f"{rest} + {tail}"


def labels_of(groups):
    """{name: [flop, ...]} as {flop: name}, which is what the metrics read."""
    return {flop: name for name, members in groups.items() for flop in members}


def _entropy(sizes, total):
    return -sum((n / total) * math.log2(n / total) for n in sizes if n)


def contingency(answer, truth):
    """counts[(cluster, class)], and the two marginals."""
    counts = Counter((answer[f], truth[f]) for f in truth)
    clusters, classes = Counter(), Counter()
    for (cluster, klass), n in counts.items():
        clusters[cluster] += n
        classes[klass] += n
    return counts, clusters, classes


def purity(answer, truth):
    """The fraction of flops in the majority true class of their cluster.

    One cluster per flop scores 1.0. That is not a defect in the measure, it is
    what the measure is for: purity says nothing about over-splitting and is
    only ever read beside something that does.
    """
    counts, clusters, _classes = contingency(answer, truth)
    best = Counter()
    for (cluster, _klass), n in counts.items():
        best[cluster] = max(best[cluster], n)
    return sum(best.values()) / len(truth)


def nmi(answer, truth):
    """Normalised mutual information. Returns (value or None, branch).

    **The 0/0 case is load-bearing here and is not an edge case.** 109 of the
    corpus's 133 netlists declare exactly one register, so their ground truth
    has one class, zero entropy, and zero mutual information with any answer:
    the ratio is 0/0 and there is no value to report. Averaging those in as 0
    would say every criterion fails on 82% of the corpus; averaging them in as
    1 would say every criterion is nearly perfect. Both are wrong for the same
    reason, which is that the netlist does not ask the question.

    The convention, stated once and counted in every aggregate:

        truth has two or more classes      NMI as defined.
        truth has one class, answer too    1.0. The two partitions are equal,
                                           which is the only thing NMI ever
                                           measures, and 0/0 is resolved by
                                           that agreement rather than by a
                                           limit.
        truth has one class, answer splits None. Excluded from the NMI mean,
                                           reported under its own count, and
                                           left to purity and exact match --
                                           both of which do see it.

    An aggregate that does not say how many netlists went down each branch is
    not reporting a measurement, and every caller below prints the counts.
    """
    counts, clusters, classes = contingency(answer, truth)
    total = len(truth)
    h_truth = _entropy(classes.values(), total)
    h_answer = _entropy(clusters.values(), total)
    if h_truth == 0:
        if h_answer == 0:
            return 1.0, "one class, answer agrees"
        return None, "one class, answer splits"
    info = 0.0
    for (cluster, klass), n in counts.items():
        joint = n / total
        info += joint * math.log2(joint /
                                  ((clusters[cluster] / total) *
                                   (classes[klass] / total)))
    return 2 * info / (h_answer + h_truth), "defined"


# Hand computed, in the style of `verify_functions.HAND_WRITTEN`, and for the
# same reason: the implementation above is the only thing that computes these
# numbers, so agreeing with itself is worth nothing. Each row was worked out on
# paper from the definitions and is written here with that arithmetic beside it.
#
# n = 16 unless the row says otherwise. Truth and answer are lists of lists of
# flop indices.
_A = list(range(8))
_B = list(range(8, 16))
HAND_WRITTEN_METRICS = [
    # Identical partitions: I = H(C) = H(T), so the ratio is 1 whatever the
    # normalisation, and every flop sits in the majority class of its cluster.
    ("perfect, [8, 8]", [_A, _B], [_A, _B], 1.0, 1.0),

    # One cluster: H(C) = 0 and I = 0, so NMI = 0 exactly. Purity is the
    # largest true class over n, 8/16.
    ("one group vs [8, 8]", [_A, _B], [list(range(16))], 0.0, 0.5),

    # Sixteen clusters of one. H(C) = log2(16) = 4, H(T) = 1, and I = H(T) = 1
    # because knowing the cluster names the class. NMI = 2(1)/(4+1) = 0.4.
    # Purity is 1.0, which is the degenerate purity cannot see.
    ("all singletons vs [8, 8]", [_A, _B], [[i] for i in range(16)], 0.4, 1.0),

    # n = 8. Truth [4, 4]; the answer moves one flop across the boundary.
    #   p(c0) = 5/8, p(c1) = 3/8, p(t0) = p(t1) = 1/2
    #   H(C) = -(0.625 log2 0.625 + 0.375 log2 0.375) = 0.954434
    #   I    = 0.5 log2(1.6) + 0.125 log2(0.4) + 0.375 log2(2)
    #        = 0.339036 - 0.165241 + 0.375 = 0.548795
    #   NMI  = 2(0.548795) / (0.954434 + 1) = 0.561601
    #   purity = (4 + 3)/8 = 0.875
    ("one flop across the boundary, [4, 4]",
     [[0, 1, 2, 3], [4, 5, 6, 7]], [[0, 1, 2, 3, 4], [5, 6, 7]],
     0.5616, 0.875),

    # Eight clusters, each holding one flop of each true class. Cluster and
    # class are statistically independent: every joint probability is 1/16 and
    # every product of marginals is (1/8)(1/2) = 1/16, so I = 0 and NMI = 0
    # even though the answer is not degenerate. Purity is 8(1)/16.
    ("paired across [8, 8]", [_A, _B], [[i, i + 8] for i in range(8)],
     0.0, 0.5),

    # The 0/0 branch, both ways. n = 4, one true class.
    ("one true class, answer agrees", [[0, 1, 2, 3]], [[0, 1, 2, 3]],
     1.0, 1.0),
    ("one true class, answer splits", [[0, 1, 2, 3]], [[0, 1], [2, 3]],
     None, 1.0),
]


def metric_selftest(verbose=True):
    """Every hand computed row reproduced by the implementation."""
    wrong = 0
    if verbose:
        print(f"metric selftest, {len(HAND_WRITTEN_METRICS)} hand computed "
              f"rows")
        print(f"  NMI normalisation: {NMI_NORMALISATION}")
    for label, truth_groups, answer_groups, want_nmi, want_purity in \
            HAND_WRITTEN_METRICS:
        truth = labels_of({f"t{i}": g for i, g in enumerate(truth_groups)})
        answer = labels_of({f"c{i}": g for i, g in enumerate(answer_groups)})
        got_nmi, branch = nmi(answer, truth)
        got_purity = purity(answer, truth)
        bad = []
        if want_nmi is None:
            if got_nmi is not None:
                bad.append(f"NMI {got_nmi:.4f}, expected undefined")
        elif got_nmi is None or abs(got_nmi - want_nmi) > 5e-5:
            bad.append(f"NMI {got_nmi}, expected {want_nmi}")
        if abs(got_purity - want_purity) > 5e-5:
            bad.append(f"purity {got_purity:.4f}, expected {want_purity}")
        shown = "undefined" if got_nmi is None else f"{got_nmi:.4f}"
        if verbose:
            print(f"  {'WRONG' if bad else '    '} {label:<38} "
                  f"NMI {shown:>9}  purity {got_purity:.4f}   [{branch}]")
        for problem in bad:
            print(f"          {problem}")
        wrong += bool(bad)
    if verbose:
        print(f"  {len(HAND_WRITTEN_METRICS) - wrong}/"
              f"{len(HAND_WRITTEN_METRICS)} rows reproduced")
    return wrong


def truth_membership(graph, expected):
    """Which declared register each flop belongs to, or None and why not.

    The corpus declares register *sizes* -- `"registers": [8, 8]` -- and NMI
    and purity need memberships. Two sources, in order:

    1. A declaration of one register covering every flop is a membership
       already, and 109 of the 133 netlists are that.
    2. Otherwise the RTL vector name yosys leaves on each flop's Q net:
       `a_reg[4]` and `a_reg[5]` are bits of one register. This is **checked
       against the declaration** rather than trusted -- if the names partition
       the flops differently from the sizes the generator declared, the
       netlist is refused rather than scored against a membership invented
       here. 10 of the 24 multi-register netlists survive that check.

    The 14 that do not are refused for two measured reasons, both real:
    `two_clocks` and `inverted_clock` declare `[4, 4]` for what the RTL writes
    as one vector split across two clocks, so the names say `[8]`; and the
    `scale_datapath` family loses one bit of three registers to a yosys rename,
    so the names say `[16, 16, 16, 15, 15, 7, 2, 1, 1, 1]` against a declared
    `[16, 16, 16, 16, 16, 8, 2]`. Attaching those stragglers to whichever group
    makes the sizes match would be fitting the answer key to the answer.
    """
    flops = sorted(graph["flipflops"])
    if expected == [len(flops)]:
        return {f: "(one register)" for f in flops}, "declared as one register"
    groups = defaultdict(list)
    for flop in flops:
        name = graph["net_names"].get(graph["flipflops"][flop]["q"])
        groups[VECTOR_BIT.sub("", name) if name else f"(unnamed {flop})"] \
            .append(flop)
    sizes = sorted((len(v) for v in groups.values()), reverse=True)
    if sizes != expected:
        return None, (f"RTL vector names partition these flops {sizes}, the "
                      f"generator declares {expected}")
    return labels_of(groups), "RTL vector names on the flops' Q nets"


def measure(groups, truth, membership):
    """One criterion's answer against one netlist's truth, all three metrics.

    `groups` is the criterion's output, `truth` the declared sizes and
    `membership` the flop level ground truth or None.
    """
    got = sorted((len(m) for m in groups.values()), reverse=True)
    row = {"exact": got == truth, "sizes": got, "nmi": None,
           "purity": None, "branch": "no membership"}
    if membership is not None:
        answer = labels_of({str(k): v for k, v in groups.items()})
        row["nmi"], row["branch"] = nmi(answer, membership)
        row["purity"] = purity(answer, membership)
    return row


def aggregate(rows):
    """Means over a criterion's per netlist rows, with the branch counts.

    **Two means, not one, and the second is the one to read.** The convention
    hands 1.0 to every netlist whose truth is a single class and whose answer
    is too, and 109 of 133 netlists are that, so a mean over everything is
    109 parts agreement and 10 parts measurement. Measured: the null model that
    returns one group scores the same 0.9161 as the committed criterion under
    that mean, which is the aggregate saying nothing in four decimal places.

    So `nmi` and `purity` are the means over every netlist with a membership,
    and `nmi real` and `purity real` are the means over the netlists whose
    ground truth has more than one class -- the ones that ask the question.
    Both are reported, both are recorded, and the counts under each are printed
    so neither can be quoted without its denominator.
    """
    scored = [r for r in rows if r["nmi"] is not None]
    pure = [r for r in rows if r["purity"] is not None]
    real = [r for r in rows if r["branch"] == "defined"]
    branches = Counter(r["branch"] for r in rows)
    mean = lambda values: (round(sum(values) / len(values), 4) if values
                           else None)
    return {
        "exact": sum(r["exact"] for r in rows),
        "netlists": len(rows),
        "nmi": mean([r["nmi"] for r in scored]),
        "nmi over": len(scored),
        "purity": mean([r["purity"] for r in pure]),
        "purity over": len(pure),
        "nmi real": mean([r["nmi"] for r in real]),
        "purity real": mean([r["purity"] for r in real]),
        "real over": len(real),
        "branches": dict(branches),
    }


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


def port_edges(graph):
    """reads[flop] = input ports reaching its D. drives[flop] = outputs it feeds.

    The same two walks `register_graph` does for a whole register, done per
    flop, because the split below needs a flop's successors and predecessors
    and a primary port is one of each.

    Ports are named, not bit-indexed. `d[0]` and `d[1]` are the port `d`, and
    they have to be, or a plain register whose bits read distinct bits of one
    input bus would be split by its own inputs -- which is the failure this
    pass is supposed to avoid.
    """
    reads, drives = defaultdict(set), defaultdict(set)
    for flop, record in graph["flipflops"].items():
        for root in graph["nets"].get(record["q"], {}).get("cones", ()):
            if root.startswith("port."):
                drives[flop].add(root[len("port."):].split("[")[0])
    for name, port in graph["ports"].items():
        if port["direction"] != "input":
            continue
        for bit in port["bits"]:
            for root in graph["nets"].get(bit, {}).get("cones", ()):
                if root.endswith(".data"):
                    flop = root[: -len(".data")]
                    if flop in graph["flipflops"]:
                        reads[flop].add(name)
    return reads, drives


def split_by_flow(graph, seed):
    """DANA's split by successor/predecessor groupings, run to a fixpoint.

    Within a candidate group, each flop gets a signature of *which groups* its
    data reaches and which reach it -- at group level, not flop level, which is
    the whole point: two bits of one register have different flop-level
    predecessors and the same group-level ones. Primary ports count as groups,
    by port name.

    A group whose members disagree is split. Groups only ever split, so the
    group count is monotone and bounded by the flop count, and the loop ends
    when a round adds nothing.

    **This is the pass DANA singles out for our symptom** -- "becomes essential
    in later iterations, where different metrics combined resulted in too large
    groupings", TCHES 2020 section 4.4, quoted in `docs/references.md` section
    3 -- and both of our failures are too-large groupings. What it does here is
    measured in `--compare` and `verify_blocks.py` rather than assumed, and the
    measurement is not what the quotation predicts. See `docs/04-detectors.md`.
    """
    fanin, fanout = flop_edges(graph)
    reads, drives = port_edges(graph)
    owner = {flop: index for index, (_key, members)
             in enumerate(sorted(seed.items(), key=lambda kv: str(kv[0])))
             for flop in members}
    while True:
        signature = {}
        for flop in owner:
            successors = frozenset(owner[g] for g in fanout.get(flop, ())) \
                | frozenset(f"port {p}" for p in drives.get(flop, ()))
            predecessors = frozenset(owner[g] for g in fanin.get(flop, ())) \
                | frozenset(f"port {p}" for p in reads.get(flop, ()))
            signature[flop] = (owner[flop], sorted(map(str, predecessors)),
                               sorted(map(str, successors)))
        groups = defaultdict(list)
        for flop, key in signature.items():
            groups[str(key)].append(flop)
        if len(groups) == len(set(owner.values())):
            return {key: sorted(members) for key, members in groups.items()}
        owner = {flop: index for index, (_key, members)
                 in enumerate(sorted(groups.items()))
                 for flop in members}


def control_then_flow(graph):
    """Seed 1: the control signature, then DANA's split."""
    return split_by_flow(graph, control_groups(graph))


def components_then_flow(graph):
    """Seed 2: control signature and connected components, then DANA's split."""
    return split_by_flow(graph, connected_components(graph))


CRITERIA = {
    "control signature": control_groups,
    "+ connected components": connected_components,
    "colour refinement, fixed point": refined_to_fixed_point,
    "control + flow split": control_then_flow,
    "+ components + flow split": components_then_flow,
}


# The two circuits where the flow split has to be looked at rather than scored.
def placements(target):
    """Where stage 1 found each flop, as {instance: (x, y)}, or None.

    Stage 1 records `lower_left` and `orient` for every placement and
    `verify_blocks.py` already keys on both, 230 of 230. This reads the corner
    rather than a centre because that is what is recorded and what the DEF
    states; a cell's width would have to come from the LEF and would add a
    second file to a criterion whose whole claim is that it needs no
    connectivity at all.
    """
    path = os.path.join("out", target, "instances.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        instances = json.load(handle)["instances"]
    return {record["id"]: tuple(record["lower_left"]) for record in instances
            if "lower_left" in record}


def spatial_groups(graph, positions, link_rows=LINK_ROWS):
    """Control groups, then single linkage on where the flops actually sit.

    **The announcement sanctions this outright** -- "The circuit is physically
    arranged to hint at its functionality, so look closely at the layout!",
    quoted verbatim in `docs/references.md` section 6 -- and DANA names the same
    idea as its own unexploited one and an open research question: "in the case
    of ASICs, information about the location of FFs can be leveraged, since the
    FFs of registers are typically laid out in close proximity of each other
    ... We do not analyze this information in our instantiation."

    Single linkage: two flops join when they sit within `link_rows` row heights
    of each other, and a group is a transitive closure of that. Single linkage
    rather than a centroid method because a register laid out along a row is a
    chain of near neighbours and not a ball, and any method that measures
    distance to a centre would cut it in half.

    One parameter, `LINK_ROWS = 3`, recorded rather than tuned, and
    `spatial_profile` prints the cluster count at every threshold from 1 to 12
    rows so the reader can see whether it sits in a plateau or on a slope. On
    the warm up rows 2 to 7 all answer two clusters, which is what a real gap
    between two registers looks like.

    **The corpus cannot score this.** Every synthetic circuit is synthesised and
    never placed, so `out/synth/*/instances.json` does not exist and no number
    in `--score` or `--compare` covers it. Its only ground truth is the warm up,
    n = 1, and later the puzzle read by a person. That sentence is printed
    wherever this criterion is.
    """
    limit = link_rows * ROW_HEIGHT
    out = {}
    for signature, members in control_groups(graph).items():
        placed = [f for f in members if f in positions]
        parent = {f: f for f in placed}

        def find(node):
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for index, one in enumerate(placed):
            for other in placed[index + 1:]:
                (x1, y1), (x2, y2) = positions[one], positions[other]
                if math.hypot(x1 - x2, y1 - y2) <= limit:
                    parent[find(one)] = find(other)
        clusters = defaultdict(list)
        for flop in placed:
            clusters[find(flop)].append(flop)
        for root, group in clusters.items():
            out[(signature, root)] = sorted(group)
        # A flop stage 1 never placed is its own group rather than silently
        # absent: a criterion that drops what it cannot see reports a partition
        # that does not cover the design.
        for flop in members:
            if flop not in positions:
                out[(signature, flop, "unplaced")] = [flop]
    return out


def spatial_profile(graph, positions, thresholds=range(1, 13)):
    """Cluster count against link threshold, so the plateau is visible.

    A threshold picked out of a plateau is a threshold the data supports. One
    picked off a slope is a tuning parameter wearing a measurement's clothes,
    and the only way to tell them apart is to print both.
    """
    rows = []
    for link in thresholds:
        sizes = sorted((len(m) for m in
                        spatial_groups(graph, positions, link).values()),
                       reverse=True)
        rows.append((link, sizes))
    return rows


DEMONSTRATIONS = {
    # A plain register: eight flops, no dependence between them, all reading
    # one input port and all driving one output port. Connected components
    # shatters it -- that is its recorded failure -- and the flow split must
    # not, because every bit has the same successors and the same
    # predecessors. This is the pass's designed advantage over components and
    # the only thing in the corpus that shows it.
    "plain register stays whole": {
        "circuit": ("register_w8_async_reset", "base"),
        "expect": {"control + flow split": [8],
                   "+ connected components": [1] * 8},
    },
}


def demonstrations(rows):
    """Two claims about the flow split, checked rather than described.

    Returns (lines, failed). A claim that stops being true fails the run, which
    is the difference between a demonstration and a sentence.
    """
    lines, failed = [], False
    by_name = {(r["entry"]["name"], r["entry"].get("variant")): r
               for r in rows}

    for label, spec in DEMONSTRATIONS.items():
        row = by_name.get(spec["circuit"])
        if row is None:
            lines.append(f"  MISSING  {label}: no {spec['circuit']} in the "
                         f"corpus")
            failed = True
            continue
        lines.append(f"  {label}, on {spec['circuit'][0]}[{spec['circuit'][1]}]"
                     f", declared {row['expected']}")
        for name, want in spec["expect"].items():
            got = sorted((len(m) for m in CRITERIA[name](row["graph"]).values()),
                         reverse=True)
            mark = "" if got == want else f"   WRONG, expected {want}"
            lines.append(f"    {name:<32} {got}{mark}")
            failed = failed or got != want

    # The R0 analogue. The control signature answers one group of 82 of its 90
    # flops, which is the shape of the puzzle's R0 -- 72 of 92 under one
    # signature. Reported and not scored: `truth_membership` refuses this
    # family, because a yosys rename splits three of its registers across two
    # names each and the declared sizes and the RTL names disagree.
    family = [r for r in rows if r["truth"].get("family") == "scale_datapath"]
    if family:
        row = min(family, key=lambda r: len(r["graph"]["flipflops"]))
        lines.append("")
        lines.append(f"  the R0 analogue: {len(family)} scale_datapath "
                     f"netlists. The smallest holds "
                     f"{len(row['graph']['flipflops'])} flops in")
        lines.append(f"  {len(row['expected'])} declared registers, "
                     f"{row['expected']}, and the control signature answers")
        lines.append(f"  one group of 82 -- the shape of the puzzle's R0, "
                     f"which is 72 of 92 flops")
        lines.append(f"  under one signature.")
        for name, criterion in CRITERIA.items():
            sizes = sorted((len(m) for m in criterion(row["graph"]).values()),
                           reverse=True)
            ones = sizes.count(1)
            shown = str([s for s in sizes if s > 1])
            if ones:
                shown += f" and {ones} singleton" + ("s" if ones > 1 else "")
            lines.append(f"    {name:<32} {shown}")

        # Whether those surviving groups are whole registers is checked and not
        # stated: a vector's bits are indexed, so the names on a group's Q nets
        # have to cover 0 .. n-1 once each, whatever the base names say.
        names = {f: (row["graph"]["net_names"].get(
            row["graph"]["flipflops"][f]["q"]) or f)
            for f in row["graph"]["flipflops"]}
        lines.append(f"    the flow split's surviving groups, by the RTL "
                     f"vector names on their Q nets")
        survivors = [m for m in
                     CRITERIA["control + flow split"](row["graph"]).values()
                     if len(m) > 1]
        for members in sorted(survivors, key=len, reverse=True):
            bases = Counter(VECTOR_BIT.sub("", names[f]) for f in members)
            indices = sorted(int(names[f].split("[")[1][:-1]) for f in members
                             if "[" in names[f])
            whole = indices == list(range(len(members)))
            parts = " + ".join(f"{base}[{n} bits]"
                               for base, n in sorted(bases.items()))
            lines.append(f"      {len(members):>3} bits  {parts}")
            lines.append(f"               bits 0..{len(members) - 1} covered "
                         f"once each: {'yes' if whole else 'NO'}")
            failed = failed or not whole
        lines.append(f"    Each of those is one whole RTL register split "
                     f"across two names by a")
        lines.append(f"    yosys rename, which is also why this family has no "
                     f"membership ground")
        lines.append(f"    truth and why the check above is on bit indices "
                     f"rather than on names.")
        lines.append(f"    No other criterion produces a complete register "
                     f"here at all.")
    return lines, failed


def corpus():
    """Every scored netlist, loaded once, as a list of dicts.

    Both entry points below used to walk the index themselves, `score` twice
    over, which is how its score and its null model could end up counting
    different denominators without anything saying so.

    `membership` is the flop level ground truth or None, and `why` says which
    of the two sources it came from or why there is none. Every metric that
    reads a membership counts the Nones rather than dropping them.
    """
    with open(f"{OUT_DIR}/index.json", encoding="utf-8") as handle:
        entries = json.load(handle)["circuits"]
    rows = []
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
        membership, why = truth_membership(graph, expected)
        rows.append({"entry": entry, "truth": truth, "expected": expected,
                     "graph": graph, "membership": membership,
                     "membership from": why})
    return rows


def against_recording(measured):
    """Every figure against what was recorded. Returns (lines, failed).

    Below its recording is a regression. *Above* its recording fails too, which
    is deliberate: a score that improved on its own is a change to something,
    and the recording is the only thing that makes it visible. Re-record it and
    the next run is quiet.
    """
    lines, failed = [], False
    for key, value in measured.items():
        recorded = RECORDED.get(key)
        if key not in RECORDED or recorded is None:
            lines.append(f"  {key}: {value}, NOT RECORDED -- add it to RECORDED")
            failed = True
        elif value is None:
            lines.append(f"  {key}: not measured, recorded {recorded}")
            failed = True
        elif value < recorded:
            lines.append(f"  REGRESSION  {key}: {value}, recorded {recorded}")
            failed = True
        elif value > recorded:
            lines.append(f"  NOTE        {key}: {value}, recorded {recorded}. "
                         f"Above the recording, which is not automatically good")
            lines.append(f"              news. Find out why it moved, then "
                         f"re-record it in RECORDED.")
            failed = True
    return lines, failed


def compare():
    """Every criterion against the same answer key, in one run."""
    if metric_selftest():
        print("\nRESULT: fail, the metric implementation does not reproduce "
              "its own hand computed table")
        return 1
    print()
    rows = corpus()
    tally = {name: [] for name in CRITERIA}
    for row in rows:
        for name, criterion in CRITERIA.items():
            tally[name].append(measure(criterion(row["graph"]),
                                       row["expected"], row["membership"]))
    total = len(rows)
    summaries = {name: aggregate(measured) for name, measured in tally.items()}
    with_membership = sum(r["membership"] is not None for r in rows)

    print(f"register grouping criteria, over {total} netlists with a declared "
          f"partition")
    real = sum(1 for r in rows if r["membership"] is not None
               and r["expected"] != [len(r["graph"]["flipflops"])])
    print(f"exact match is over all {total}. NMI and purity are over the "
          f"{real} netlists that have a")
    print(f"flop level membership AND a ground truth with more than one class; "
          f"the other")
    print(f"{with_membership - real} with a membership are the 0/0 convention "
          f"and would only dilute it.")
    print(f"NMI normalisation: {NMI_NORMALISATION}\n")
    print(f"  {'':<34}{'exact':>10}{'NMI':>9}{'purity':>9}   recording")
    off = []
    for name, summary in sorted(summaries.items(),
                                key=lambda kv: -kv[1]["exact"]):
        recorded = RECORDED_CRITERIA.get(name)
        got = {k: summary[k] for k in ("exact", "nmi real", "purity real")}
        mark = ""
        if recorded is None:
            mark, bad = "NOT RECORDED", True
        else:
            bad = any(got[k] != recorded.get(k) for k in got)
            mark = "" if not bad else f"differs from {recorded}"
        off += [name] if bad else []
        cell = f"{summary['exact']}/{total}"
        print(f"  {name:<34}{cell:>10}"
              f"{str(summary['nmi real']):>9}"
              f"{str(summary['purity real']):>9}   {mark}")
    missing = sorted(set(RECORDED_CRITERIA) - set(CRITERIA))
    for name in missing:
        print(f"  {name:<34}{'--':>10}{'--':>9}{'--':>9}   RECORDED, BUT NO "
              f"LONGER COMPUTED")

    branches = Counter()
    for summary in summaries.values():
        branches.update(summary["branches"])
    print(f"\n  0/0 convention branches, summed over every criterion above:")
    for branch, count in sorted(branches.items()):
        print(f"    {count:>5}  {branch}")
    print(f"\n  The alternatives fail in mirror image, and that is the "
          f"useful part.")
    print(f"  Connected components shatters a plain register, whose bits do "
          f"not depend")
    print(f"  on one another. Refinement and the flow split shatter a shift "
          f"register,")
    print(f"  whose chain hands every bit a distinct colour once its "
          f"predecessor has")
    print(f"  one. Neither failure is a tuning problem: one needs the bits to "
          f"interact")
    print(f"  and the others need them not to.")

    print(f"\nwhat the scores cannot show")
    demo_lines, demo_failed = demonstrations(rows)
    print("\n".join(demo_lines))

    off = sorted(off + missing)
    if demo_failed:
        off = off + ["a demonstration above no longer holds"]
    if off:
        print(f"\nRESULT: fail, {len(off)} criterion(s) do not match their "
              f"recording: {off}")
        return 1
    print(f"\nRESULT: pass, all {len(tally)} criteria match their recording")
    return 0


NULL_MODELS = {
    "one group, and do nothing": lambda g: {"all": sorted(g["flipflops"])},
    "every flop its own register": lambda g: {f: [f] for f in
                                              sorted(g["flipflops"])},
}


def score():
    """Sensitivity of the committed criterion, on circuits with a known answer."""
    if metric_selftest():
        print("\nRESULT: fail, the metric implementation does not reproduce "
              "its own hand computed table")
        return 1
    print()
    rows = corpus()
    exact, wrong, held_out = 0, [], Counter()
    # The null model and the non-trivial subset, counted in the same pass over
    # the same rows as the score, so the denominators cannot drift apart.
    trivial = multi = multi_hits = 0
    measured_rows = []
    for row in rows:
        entry, truth = row["entry"], row["truth"]
        expected, graph = row["expected"], row["graph"]
        got = sorted((len(m) for m in control_groups(graph).values()),
                     reverse=True)
        measured_rows.append(measure(control_groups(graph), expected,
                                     row["membership"]))
        hit = got == expected
        if hit:
            exact += 1
            held_out["exact, held out" if entry["held_out"] else "exact"] += 1
        else:
            wrong.append((entry["name"], entry.get("variant"), truth["family"],
                          expected, got))
        trivial += expected == [len(graph["flipflops"])]
        if len(expected) > 1:
            multi += 1
            # Hits among the multi-register netlists, counted directly. This was
            # `multi - len(wrong)`, which subtracts every miss including the
            # single-register ones, so a criterion that split every flop
            # reported "of those 18, this criterion gets -102". A figure that
            # can go negative was never counting what its sentence said.
            multi_hits += hit
    total = len(rows)
    summary = aggregate(measured_rows)
    with_membership = sum(r["membership"] is not None for r in rows)

    print(f"register grouping by control signature, over the corpus")
    print(f"  {exact}/{total} netlists partitioned exactly {dict(held_out)}")
    print(f"  {trivial}/{total} would be got right by a criterion that returns "
          f"one group and does nothing else")
    print(f"  {multi}/{total} netlists declare more than one register, "
          f"which is where the question is real")
    print(f"  of those {multi}, this criterion gets {multi_hits}")
    print(f"\n  On the warm up, whose true partition the DEF states, it is "
          f"wrong: see tools/verify_blocks.py")

    print(f"\nthe same answers under NMI and purity, which are not all or "
          f"nothing")
    print(f"  membership ground truth on {with_membership}/{total} netlists; "
          f"{total - with_membership} have none and are")
    print(f"  scored by exact match alone. NMI normalisation: "
          f"{NMI_NORMALISATION}")
    print(f"  which branch of the 0/0 convention each netlist took:")
    for branch, count in sorted(summary["branches"].items()):
        print(f"    {count:>4}  {branch}")

    print(f"\nthe two degenerate answers, under all three metrics and both "
          f"denominators")
    print(f"  {'':<30}{'exact':>10}{'NMI':>8}{'purity':>8}   "
          f"{'NMI':>8}{'purity':>8}")
    print(f"  {'':<30}{'':>10}{'all ' + str(with_membership):>16}   "
          f"{'truth splits':>16}")
    shown = dict(NULL_MODELS)
    table = [(name, aggregate([measure(model(r["graph"]), r["expected"],
                                       r["membership"]) for r in rows]))
             for name, model in shown.items()]
    table.append(("the control signature", summary))
    for name, entry in table:
        cell = f"{entry['exact']}/{total}"
        print(f"  {name:<30}{cell:>10}{str(entry['nmi']):>8}"
              f"{str(entry['purity']):>8}   {str(entry['nmi real']):>8}"
              f"{str(entry['purity real']):>8}")
    print(f"  the right hand pair is over the {summary['real over']} netlists "
          f"whose ground truth has")
    print(f"  more than one class. The left hand pair is over all "
          f"{with_membership} and is mostly the")
    print(f"  convention: one group and the committed criterion score the same "
          f"there, to")
    print(f"  four decimal places, which is what an aggregate looks like when "
          f"109 of its")
    print(f"  119 rows were never able to disagree.")
    print(f"\n  Each degenerate is bad on at least one axis, and no single "
          f"axis catches")
    print(f"  both. One group scores zero NMI, because a single cluster has no "
          f"entropy.")
    print(f"  All singletons scores 1.0 purity, exactly -- purity does not "
          f"penalise")
    print(f"  over-splitting at all, so the claim that it kills that "
          f"degenerate is false.")
    print(f"  What kills that one here is exact match. Three columns, not "
          f"two.")

    print(f"\n  the {len(wrong)} it does not get:")
    for name, variant, family, expected, got in wrong[:20]:
        print(f"    {name}[{variant}]  {family}")
        print(f"      expected {expected}")
        print(f"      got      {got}")
    if len(wrong) > 20:
        print(f"    ... and {len(wrong) - 20} more")
    families = Counter(w[2] for w in wrong)
    print(f"\n  by family: {dict(families)}")
    # Said only when it is true of the run that just happened. It used to be
    # printed unconditionally, so a criterion that shattered every plain
    # register still concluded that every miss was a shared-control circuit.
    over = sum(1 for w in wrong if len(w[3]) == 1)
    if wrong and not over:
        print(f"  Every one is a circuit built from several registers that share")
        print(f"  a clock, a reset and a hold. The criterion cannot see a")
        print(f"  boundary that no control signal marks, and refinement, which")
        print(f"  can, breaks more than it fixes. This is the residue stage 4")
        print(f"  reports rather than the failure it hides.")
    elif wrong:
        print(f"  {over} of the misses are on netlists that declare ONE register,")
        print(f"  so this criterion is over-splitting and not merely failing to")
        print(f"  split. That is a different failure from the recorded one.")

    lines, failed = against_recording({
        "exact": exact, "netlists": total, "null model": trivial,
        "multi": multi, "multi hits": multi_hits,
        "membership": with_membership,
        "nmi": summary["nmi"], "nmi over": summary["nmi over"],
        "purity": summary["purity"],
        "nmi real": summary["nmi real"], "purity real": summary["purity real"],
        "real over": summary["real over"]})
    print(f"\nagainst the recorded expectation")
    print("\n".join(lines) if lines else "  every figure matches its recording")
    if failed:
        print("\nRESULT: fail")
        return 1
    print("\nRESULT: pass")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        wrong = metric_selftest()
        print(f"\nRESULT: {'fail' if wrong else 'pass'}")
        sys.exit(1 if wrong else 0)
    if args == ["--score"]:
        sys.exit(score())
    if args == ["--compare"]:
        sys.exit(compare())
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage4_registers.py "
                 f"[{' | '.join(TARGETS)} | --score | --compare | "
                 f"--selftest]")
    sys.exit(run(args[0]))
