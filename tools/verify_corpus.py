"""The corpus against its own answer key.

Stage 5 writes each circuit's `truth.json` from the generator that produced it,
then puts the netlist through the same stage 3 the puzzle goes through. Those
two records are independent: one is what we asked for, the other is what a tool
found in the gate level result. Where they disagree, something is wrong -- in a
generator, in synthesis, or in stage 3 -- and which one is not knowable in
advance.

This existed once as a claim in prose: "the declared width equals the flip flops
stage 3 finds, 86 out of 86". A number that ran once and was written down is not
a gate. This is the gate.

Every rule here can fail, and `--selftest` proves it by feeding each one a graph
broken in the way that rule exists to catch. A check that has never been seen to
fail is silence, not evidence.

Usage:
    python tools/verify_corpus.py
    python tools/verify_corpus.py --selftest
"""

import copy
import json
import os
import sys
from collections import Counter, defaultdict

OUT_DIR = "out/synth"

# Fields these rules read that an older stage 3 did not write.
REQUIRED = ("clock_roots", "flipflops", "constant_nets", "clock_nets")

# Families whose declared `width` is exactly the number of state bits, by
# construction. The others hold state too, but their width names an operand or a
# bus rather than a flop count, so equality would be asserting a coincidence.
WIDTH_IS_FLOPS = {"register", "shift_register", "counter", "lfsr", "clock_tree"}

# Where stage 3's structural search for a held register finds nothing, and why.
# Measured against circuits whose enable we declared ourselves, so these are
# false negatives with a known ground truth rather than guesses.
#
#   counter          the enable is folded into the carry chain -- `D[0] = q[0] ^
#                    en`, `D[1] = q[1] ^ (q[0] & en)`. No mux exists at all.
#   register + sync  the mux exists, `mux2i` with A0 on Q and S on `en`, but the
#     reset          synchronous reset's `nor2b` sits between it and D, and the
#                    search only looks one cell back.
#   scale_datapath   the mux is factored away entirely. `D = en ? (acc ^ lfsr) :
#                    outr` maps to one `a21oi`, `Y = !B1 & (!A1 | !A2)`, with
#                    `en` on A1 and Q arriving through a `nor2` two cells back.
#                    This is the general case and the other two are the special
#                    ones: a plain register keeps its mux only because the data
#                    leg is a port. Once that leg is computed, the mapper folds
#                    the select into the logic that computes it, which is what a
#                    technology mapper is for.
#
# Three shapes, one conclusion: whether a register holds is a question about
# behaviour, not about what stands in front of D. Stage 4 answers it with a
# solver -- is there an input assignment under which D equals Q -- and this
# table exists so that the answer can be scored against the cases known to
# defeat the structural version.
ENABLE_HIDDEN_BY = {
    "counter": "absorbed into the carry chain",
    "register+sync": "displaced from D by the reset logic",
    "scale_datapath": "factored into an AOI gate, Q entering two cells back",
}


def rules(truth, graph):
    """Every declared fact this circuit's graph can be checked against.

    Each entry is (rule, declared, found, ok). Rules that do not apply to a
    circuit are simply not produced.
    """
    out = []
    flops = graph["flipflops"]
    family = truth["family"]

    def check(rule, declared, found):
        out.append((rule, declared, found, declared == found))

    # Bits of one register do not share a clock net; they share a clock root.
    # Grouping by net gives `branches` groups on the clock_tree family, which is
    # the whole reason that family exists.
    #
    # The expected number of roots is declared rather than assumed to be one.
    # Every circuit here was single clock, so this rule had only ever been asked
    # to confirm the number 1 -- which tests a walk that under-merges and never
    # one that over-merges, and a walk collapsing every clock in a design into
    # one root would have passed on all of them. The `two_clocks` family must
    # come back with two.
    #
    # The second check is not the first restated. Every flop lands in exactly
    # one root group by construction, so "one root" would imply "all flops under
    # it" -- but "the groups account for every flop" holds whatever the root
    # count is, and catches a flop that fell out of the grouping entirely.
    if flops:
        check("clock roots", truth.get("clock_roots", 1),
              len(graph["clock_roots"]))
        check("flops accounted for by the clock roots", len(flops),
              sum(len(m) for m in graph["clock_roots"].values()))

    # A family that writes its own clock tree, because clkbufmap gives one
    # buffer per clock net and cannot split fanout.
    if "branches" in truth:
        check("distinct clock nets", truth["branches"], len(graph["clock_nets"]))

    if family in WIDTH_IS_FLOPS:
        check("width in flip flops", truth["width"], len(flops))
    if "flops" in truth:
        check("declared flip flop count", truth["flops"], len(flops))

    # A combinational circuit that grew state means a generator wrote something
    # other than what it declared.
    if family in ("adder", "subtractor", "comparator", "multiplexer", "decoder",
                  "xor_tree", "tied_outputs"):
        check("stateless", 0, len(flops))

    # Reset style, as declared, against the pins liberty says the mapped flops
    # actually have. The two styles are different shapes and not degrees of one:
    # an asynchronous reset is a pin on the flop, a synchronous one is logic in
    # front of D and leaves the flop with no reset pin at all. Checking only
    # "has a reset somewhere" would have passed a generator that declared `sync`
    # and emitted no reset of any kind, which is what it was doing.
    style = truth.get("reset")
    if style is not None and flops:
        with_pin = sum(1 for r in flops.values() if r["reset"] or r["set"])
        check(f"flops whose reset is a pin ({style})",
              len(flops) if style.startswith("async") else 0, with_pin)
    if style == "sync":
        check("a reset port, with the reset in the logic",
              True, any(p in graph["ports"] for p in ("rst_n", "rst", "reset")))

    if family == "tied_outputs":
        check("constant nets", truth["constants"], len(graph["constant_nets"]))

    # An enable, checked as a property of the circuit rather than of the shape
    # synthesis happened to give it. Whether a hold mux survives is not a fact
    # about the register -- measured, it survives in a plain register, vanishes
    # into a counter's carry chain, and is pushed away from D by a synchronous
    # reset -- so asserting it would freeze an expectation the corpus itself
    # disproves. What is invariably true is that the enable reaches the data
    # cone of every flop it holds, and a detector that cannot rely on that has
    # nothing to work with at all.
    #
    # How many flops an enable holds is itself declared, because it is not
    # always all of them: in the scale family the enable gates one register out
    # of seven, and a rule assuming otherwise would fail on a correct circuit.
    if truth.get("enable") and "en" in graph["ports"]:
        net = graph["ports"]["en"]["bits"][0]
        reached = set(graph["nets"].get(net, {}).get("cones", ()))
        check("flops whose data cone the enable reaches",
              truth.get("enable_holds", len(flops)),
              sum(1 for i in flops if f"{i}.data" in reached))

    # An inverting path to CLK makes a rising edge flop sample on the falling
    # edge of the root clock. Declared rather than assumed to be zero: it was
    # zero everywhere, and the reason turned out to be that stage 3 could not
    # report anything else. This library writes a combinational output as
    # `function : "(!A)"` and the level was read off the raw first character, so
    # every inverter in it was classified as a buffer. The `inverted_clock`
    # family is what makes this rule able to fail.
    if flops:
        check("flops on an inverting clock path", truth.get("clock_inverted", 0),
              sum(1 for r in flops.values() if r.get("clock_inverted")))

    return out


def load(entry):
    """A corpus entry's declared truth and the graph stage 3 found.

    `entry` is an index record, which names its own output directory: base and
    variant mappings of one circuit share a name and differ in `dir`.
    """
    directory = entry["dir"] if isinstance(entry, dict) else f"{OUT_DIR}/{entry}"
    with open(f"{directory}/truth.json", encoding="utf-8") as handle:
        truth = json.load(handle)
    with open(f"{directory}/graph.json", encoding="utf-8") as handle:
        graph = json.load(handle)
    return truth, graph


def label(entry):
    return f"{entry['name']}[{entry.get('variant', 'base')}]"


def verify(entries):
    """Every declared fact against every mapping of the circuit that declared it.

    A circuit is synthesised more than one way, and the declared facts have to
    hold for all of them. That is the structural invariance test, made at the
    stage 3 level and for free: if a fact only survives one particular mapping
    it was a property of that mapping and not of the circuit.
    """
    checked, failures = 0, []
    by_rule = Counter()
    for entry in entries:
        truth, graph = load(entry)
        for rule, declared, found, ok in rules(truth, graph):
            checked += 1
            by_rule[rule.split(" (")[0]] += 1
            if not ok:
                failures.append((label(entry), rule, declared, found))
    return checked, by_rule, failures


def broken_roots(graph):
    """Stage 3 without the root walk: every clock net is taken for a root."""
    graph["clock_roots"] = {net: [i for i, r in graph["flipflops"].items()
                                  if r["clock"] == net]
                            for net in graph["clock_nets"]}
    for record in graph["flipflops"].values():
        record["clock_root"] = record["clock"]


def lost_reset(graph):
    for record in graph["flipflops"].values():
        record["reset"] = record["set"] = None


def inverted_clock(graph):
    next(iter(graph["flipflops"].values()))["clock_inverted"] = True


def grew_a_flop(graph):
    instance, record = next(iter(graph["flipflops"].items()))
    graph["flipflops"][instance + "_extra"] = dict(record)


def enable_reaches_nothing(graph):
    graph["nets"][graph["ports"]["en"]["bits"][0]]["cones"] = []


def lost_the_constants(graph):
    graph["constant_nets"] = {}


def clocks_merged(graph):
    """A root walk that runs past a primary input and merges two domains."""
    everything = [i for i in graph["flipflops"]]
    graph["clock_roots"] = {"merged": everything}


def a_flop_falls_out_of_the_grouping(graph):
    root = next(iter(graph["clock_roots"]))
    graph["clock_roots"][root] = graph["clock_roots"][root][1:]


def inversion_parity_lost(graph):
    """What stage 3 did before `(!A)` was unwrapped: every path looks straight."""
    for record in graph["flipflops"].values():
        record["clock_inverted"] = False


# Each corruption is the real failure mode of one rule, paired with the kind of
# circuit that rule applies to. Running them all against a single circuit is how
# a corruption goes unnoticed for the uninteresting reason that its rule was
# never in play -- which is what the first version of this did.
CORRUPTIONS = [
    ("root walk removed", broken_roots, lambda t: t["family"] == "clock_tree"),
    ("reset pins lost", lost_reset,
     lambda t: str(t.get("reset")).startswith("async")),
    ("a sync reset made async", lambda g: [r.update(reset="n0")
                                           for r in g["flipflops"].values()],
     lambda t: t.get("reset") == "sync"),
    ("clock inverted", inverted_clock, lambda t: t["family"] in WIDTH_IS_FLOPS),
    ("an extra flip flop", grew_a_flop, lambda t: t["family"] in WIDTH_IS_FLOPS),
    ("enable reaches no cone", enable_reaches_nothing, lambda t: t.get("enable")),
    ("constants folded away", lost_the_constants,
     lambda t: t["family"] == "tied_outputs"),
    ("two clock domains merged", clocks_merged,
     lambda t: t.get("clock_roots", 1) > 1),
    ("a flop left out of a root", a_flop_falls_out_of_the_grouping,
     lambda t: t["family"] in WIDTH_IS_FLOPS),
    ("inversion parity lost", inversion_parity_lost,
     lambda t: t.get("clock_inverted", 0) > 0),
]


def selftest(index, available):
    """Feed each rule a graph broken the way that rule exists to catch.

    A check that has never been seen to fail is silence. Each corruption is
    applied to a circuit the corresponding rule applies to and that passes
    cleanly beforehand, so a rule staying quiet means the rule is not checking
    anything rather than that it was not asked.
    """
    silent, skipped = [], []
    for name, corrupt, applies in CORRUPTIONS:
        subject = None
        for entry in index:
            if not applies(entry) or label(entry) not in available:
                continue
            truth, good = load(entry)
            if all(ok for *_, ok in rules(truth, good)):
                subject = (entry, truth, good)
                break
        if subject is None:
            skipped.append(name)
            print(f"  {name:<22} NO SUBJECT, rule untested")
            continue
        entry, truth, good = subject
        graph = copy.deepcopy(good)
        corrupt(graph)
        caught = sorted({r.split(" (")[0]
                         for r, d, f, ok in rules(truth, graph) if not ok})
        print(f"  {name:<22} on {label(entry):<32} "
              f"{'caught by ' + ', '.join(caught) if caught else 'NOT CAUGHT'}")
        if not caught:
            silent.append(name)
    return silent, skipped


def main(argv):
    if not os.path.exists(f"{OUT_DIR}/index.json"):
        sys.exit(f"{OUT_DIR}/index.json missing; run tools/stage5_corpus.py")
    with open(f"{OUT_DIR}/index.json", encoding="utf-8") as handle:
        index = json.load(handle)["circuits"]
    for entry in index:
        entry.setdefault("dir", f"{OUT_DIR}/{entry['name']}")

    # A graph written by an older stage 3 is missing fields these rules read.
    # Saying so is the point: the alternative is a KeyError, or worse, a rule
    # that quietly skips and reports a pass it never earned.
    available = set()
    for entry in index:
        path = f"{entry['dir']}/graph.json"
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                graph = json.load(handle)
        except json.JSONDecodeError:
            continue
        if all(key in graph for key in REQUIRED):
            available.add(label(entry))
    entries = [e for e in index if label(e) in available]
    if len(entries) < len(index):
        print(f"{len(index) - len(entries)} of {len(index)} netlists have no "
              f"graph.json or one written by an older stage 3.")
        print(f"  re-run: python tools/stage5_corpus.py")
        if not entries:
            return 1

    if "--selftest" in argv:
        print(f"selftest: each rule against the corruption it exists to catch")
        silent, skipped = selftest(index, available)
        if silent or skipped:
            print(f"\nRESULT: fail, {len(silent)} corruption(s) went unnoticed, "
                  f"{len(skipped)} rule(s) had no subject to test against")
            return 1
        print("\nRESULT: pass, every corruption was caught")
        return 0

    checked, by_rule, failures = verify(entries)
    variants = Counter(e.get("variant", "base") for e in entries)

    # Which rules were ever asked for more than one answer. A rule whose
    # declared value is the same on every circuit is one an implementation
    # returning that value unconditionally would pass, and counting its uses
    # towards a headline total flatters the total. Two of the constants below
    # are inherent -- a combinational family has no flops by definition -- and
    # they are still worth running, because a generator that accidentally infers
    # a latch would break them. The distinction is between a rule that cannot
    # fail and one that simply has not.
    declared = defaultdict(set)
    for entry in entries:
        truth, graph = load(entry)
        for rule, value, _, _ in rules(truth, graph):
            declared[rule.split(" (")[0]].add(str(value))

    print(f"{len({e['name'] for e in entries})} circuits as {len(entries)} "
          f"netlists {dict(variants)}, {len(by_rule)} rules, {checked} uses, "
          f"checked against what stage 3 independently found")
    constant = 0
    for rule, count in sorted(by_rule.items()):
        values = sorted(declared[rule])
        mark = ""
        if len(values) == 1:
            mark, constant = f"   always {values[0]}", constant + count
        print(f"  {count:>4}  {rule}{mark}")
    print(f"  {len(by_rule) - sum(1 for v in declared.values() if len(v) == 1)}"
          f"/{len(by_rule)} rules were asked for more than one answer; "
          f"{constant}/{checked} uses assert a constant")

    if failures:
        print(f"\n{len(failures)} DISAGREEMENTS")
        for name, rule, declared, found in failures[:20]:
            print(f"  {name:<36} {rule}: declared {declared}, found {found}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more")
        print("\nRESULT: fail")
        return 1

    # Reported rather than checked. How a hold looks after synthesis is not a
    # property of the circuit, so it is not something the answer key can assert
    # -- but it is the measurement stage 4's design rests on, and it is the list
    # stage 4's hold detection has to be scored against.
    hidden, found = [], []
    for entry in entries:
        truth, graph = load(entry)
        if not truth.get("enable"):
            continue
        shape = f"{truth['family']}{'+sync' if truth.get('reset') == 'sync' else ''}"
        (found if any(r["enable"] for r in graph["flipflops"].values())
         else hidden).append(shape)
    print(f"\nholds declared {len(found) + len(hidden)}: found structurally "
          f"{len(found)} {dict(Counter(found))}, hidden from the structural "
          f"search {len(hidden)} {dict(Counter(hidden))}")
    for shape in sorted(set(hidden)):
        print(f"    {shape:<16} {ENABLE_HIDDEN_BY.get(shape, 'NEW, and unexplained')}")
    surprises = sorted(set(hidden) - set(ENABLE_HIDDEN_BY))
    if surprises:
        print(f"  a hold vanished in a way not on the known list: {surprises}")
        print("\nRESULT: fail")
        return 1

    # How far apart the mappings actually are. A variant identical to its base
    # tests nothing, and the point of the doubling is that the declared facts
    # above survived two different structures rather than one.
    by_name = defaultdict(dict)
    for entry in entries:
        by_name[entry["name"]][entry.get("variant", "base")] = entry
    apart = [(n, v) for n, v in by_name.items() if len(v) > 1
             and len({tuple(sorted(e["cell_mix"].items())) for e in v.values()}) > 1]
    print(f"structural invariance: {len(apart)}/{len(by_name)} circuits reached "
          f"stage 3 as genuinely different netlists, and the rules above hold "
          f"for every mapping of every one of them")
    print("RESULT: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
