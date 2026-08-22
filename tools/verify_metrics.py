"""Stage 4's grouping metrics, re-derived by an implementation that shares none.

`stage4_registers.nmi` and `purity` decide how every register-grouping criterion
in this repository is scored, and `--selftest` there holds them to seven hand
computed rows. Seven rows is a start and it is not a proof: they were chosen by
the same person who wrote the code, and a mistake that misses all seven misses
the check entirely.

So this computes both metrics a second way and asks the two to agree.

    NMI      here as `2 (H(C) + H(T) - H(C,T)) / (H(C) + H(T))`, from the joint
             entropy. `stage4_registers` sums `p log(p / pq)` over the joint
             distribution instead. The same quantity by a different identity,
             and a slip in either one moves only one of them.
    purity   here from a dict of lists and `Counter.most_common`;
             `stage4_registers` from a `Counter` of pairs and a running max.

Then the two are put to 4000 random partitions, which is where an
implementation agrees on every tidy example and parts company on a ragged one,
and to four invariants the definitions require whatever the implementation:
`NMI(T, T) = 1` for a non-trivial `T`, symmetry in the two arguments, a range of
`[0, 1]`, and purity never falling when the answer is refined.

**What this cannot catch, said here rather than left to be discovered.** NMI is
symmetric, so no table of partitions can expose an implementation that swapped
its two arguments in the normalisation -- the *numbers* would be identical. What
does expose it is the 0/0 convention, whose branches are deliberately not
symmetric: `nmi()` answers "one class, answer agrees" or "one class, answer
splits", and the hand table asserts the second. That is checked below too.

This exists because Package 4's own demonstrations were audited and three of
them turned out to be claims that could not fail, two of them false as printed
(`docs/problems.md` 48). The audit that found them lived in a scratch directory,
which made it a measurement that happened once. This is that measurement made a
program.

Usage:
    python tools/verify_metrics.py
    python tools/verify_metrics.py --selftest    # and would it notice
"""

import math
import random
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_registers as stage4

# Fixed, so two runs of this file compare the same partitions. A random audit
# that draws different samples each time cannot be re-recorded and cannot be
# bisected when it starts failing.
SEED = 20260822
TRIALS = 4000
INVARIANT_TRIALS = 600


def entropy(counts, total):
    return -sum((n / total) * math.log2(n / total) for n in counts if n)


def nmi_by_joint_entropy(answer, truth):
    """`I(C;T) = H(C) + H(T) - H(C,T)`. Returns None where NMI is undefined.

    The convention has to be reproduced as well as the arithmetic, because it
    is the convention that carries 109 of the corpus's 133 netlists.
    """
    total = len(truth)
    h_answer = entropy(Counter(answer[k] for k in truth).values(), total)
    h_truth = entropy(Counter(truth[k] for k in truth).values(), total)
    h_joint = entropy(Counter((answer[k], truth[k]) for k in truth).values(),
                      total)
    if h_truth == 0:
        return 1.0 if h_answer == 0 else None
    return 2 * (h_answer + h_truth - h_joint) / (h_answer + h_truth)


def purity_by_grouping(answer, truth):
    """Purity from a dict of lists rather than from a Counter of pairs."""
    clusters = {}
    for key in truth:
        clusters.setdefault(answer[key], []).append(truth[key])
    return sum(Counter(members).most_common(1)[0][1]
               for members in clusters.values()) / len(truth)


def labels(groups):
    return {item: index for index, members in enumerate(groups)
            for item in members}


def random_pair(rng):
    """One random truth and one random answer over the same items."""
    size = rng.randint(2, 14)
    truth = {i: rng.randrange(rng.randint(1, 4)) for i in range(size)}
    answer = {i: rng.randrange(rng.randint(1, 5)) for i in range(size)}
    return answer, truth


def check(nmi, purity, verbose=True):
    """Both metrics against this file's own implementations. Returns problems.

    `nmi` and `purity` are passed in rather than imported directly so that
    `--selftest` can hand this a deliberately wrong pair and watch it fail.
    """
    problems = []

    def report(ok, label, detail=""):
        if verbose:
            print(f"  {'ok  ' if ok else 'FAIL'}  {label}"
                  f"{'   ' + detail if detail else ''}")
        if not ok:
            problems.append(label)

    if verbose:
        print(f"the hand written table, recomputed from the joint entropy")
    for name, truth_groups, answer_groups, want_nmi, want_purity in \
            stage4.HAND_WRITTEN_METRICS:
        truth, answer = labels(truth_groups), labels(answer_groups)
        theirs, _branch = nmi(answer, truth)
        mine = nmi_by_joint_entropy(answer, truth)
        agree = ((mine is None) == (theirs is None) and
                 (mine is None or abs(mine - theirs) < 1e-9))
        # And both against the number written down on paper, so an error the
        # two implementations happen to share is still caught.
        matches_hand = (want_nmi is None and mine is None) or (
            want_nmi is not None and mine is not None
            and abs(mine - want_nmi) < 5e-5)
        pure = abs(purity_by_grouping(answer, truth)
                   - purity(answer, truth)) < 1e-12
        shown = "undefined" if mine is None else f"{mine:.4f}"
        report(agree and matches_hand and pure, f"{name:<38}",
               f"NMI {shown:>9}  purity "
               f"{purity_by_grouping(answer, truth):.4f}")

    if verbose:
        print(f"\n{TRIALS} random partitions, both metrics")
    rng = random.Random(SEED)
    disagreements = []
    for _trial in range(TRIALS):
        answer, truth = random_pair(rng)
        theirs, _branch = nmi(answer, truth)
        mine = nmi_by_joint_entropy(answer, truth)
        if (mine is None) != (theirs is None):
            disagreements.append("one call says NMI is undefined, the other "
                                 "returns a number")
        elif mine is not None and abs(mine - theirs) > 1e-9:
            disagreements.append(f"NMI {theirs} against {mine}")
        elif abs(purity(answer, truth)
                 - purity_by_grouping(answer, truth)) > 1e-12:
            disagreements.append("purity differs")
    report(not disagreements, f"{TRIALS} random partitions",
           f"{len(disagreements)} disagreement(s)"
           + (f": {disagreements[0]}" if disagreements else ""))

    if verbose:
        print(f"\ninvariants the definitions require, whatever the "
              f"implementation")
    rng = random.Random(SEED + 1)
    identical = symmetric = bounded = monotone = True
    for _trial in range(INVARIANT_TRIALS):
        answer, truth = random_pair(rng)
        if len(set(truth.values())) > 1:
            value, _branch = nmi(truth, truth)
            identical = identical and value is not None and abs(value - 1) < 1e-9
        forward, _b1 = nmi(answer, truth)
        backward, _b2 = nmi(truth, answer)
        if forward is not None and backward is not None:
            symmetric = symmetric and abs(forward - backward) < 1e-9
            bounded = bounded and -1e-9 <= forward <= 1 + 1e-9
        finer = {k: (answer[k], k % 2) for k in answer}
        monotone = monotone and (purity(finer, truth)
                                 >= purity(answer, truth) - 1e-12)
    report(identical, "NMI(T, T) is 1 for every non-trivial T")
    report(symmetric, "NMI is symmetric in its two arguments")
    report(bounded, "NMI stays inside [0, 1]")
    report(monotone, "purity never falls when the answer is refined")

    if verbose:
        print(f"\nthe degenerates, by definition rather than by measurement")
    truth = labels([list(range(8)), list(range(8, 16))])
    one_group = {i: "all" for i in range(16)}
    singletons = {i: i for i in range(16)}
    value, _branch = nmi(one_group, truth)
    report(value == 0.0, "one cluster scores NMI exactly 0", f"{value}")
    report(purity(singletons, truth) == 1.0,
           "all singletons scores purity exactly 1.0",
           f"{purity(singletons, truth)}")
    value, _branch = nmi(singletons, truth)
    report(value is not None and abs(value - 0.4) < 1e-12,
           "all singletons scores NMI 2(1)/(4+1)", f"{value}")

    if verbose:
        print(f"\nthe 0/0 convention, whose branches are not symmetric")
    four = labels([[0, 1, 2, 3]])
    _value, agreed = nmi({i: "all" for i in range(4)}, four)
    _value, split = nmi({0: "a", 1: "a", 2: "b", 3: "b"}, four)
    report(agreed == "one class, answer agrees" and
           split == "one class, answer splits",
           "the two single-class branches are distinguishable",
           f"{agreed!r} and {split!r}")
    if verbose:
        print("     NMI is symmetric, so no partition can expose an "
              "implementation that")
        print("     swapped its arguments in the normalisation -- the numbers "
              "would be")
        print("     identical. These branch labels are what can.")
    return problems


# Implementations that are wrong in ways somebody would plausibly write, for
# `--selftest`. Each is a one line change to the real thing.
def _nmi_max_normalised(answer, truth):
    counts, clusters, classes = stage4.contingency(answer, truth)
    total = len(truth)
    h_truth = stage4._entropy(classes.values(), total)
    h_answer = stage4._entropy(clusters.values(), total)
    if h_truth == 0:
        return (1.0, "one class, answer agrees") if h_answer == 0 else \
            (None, "one class, answer splits")
    info = 0.0
    for (cluster, klass), n in counts.items():
        joint = n / total
        info += joint * math.log2(joint / ((clusters[cluster] / total) *
                                           (classes[klass] / total)))
    return info / max(h_answer, h_truth), "defined"


def _nmi_convention_as_zero(answer, truth):
    value, branch = stage4.nmi(answer, truth)
    return (0.0, branch) if value is None else (value, branch)


def _purity_over_classes(answer, truth):
    """Majority per true class rather than per cluster: inverse purity."""
    classes = {}
    for key in truth:
        classes.setdefault(truth[key], []).append(answer[key])
    return sum(Counter(members).most_common(1)[0][1]
               for members in classes.values()) / len(truth)


WRONG = {
    "NMI normalised by max(H) rather than the mean":
        (_nmi_max_normalised, stage4.purity),
    "the 0/0 convention averaged in as 0.0":
        (_nmi_convention_as_zero, stage4.purity),
    "purity computed over true classes, which is inverse purity":
        (stage4.nmi, _purity_over_classes),
}


def selftest():
    """Would this audit notice? Three wrong implementations, each caught."""
    print("the audit against implementations that are wrong on purpose\n")
    missed = []
    for label, (nmi, purity) in WRONG.items():
        problems = check(nmi, purity, verbose=False)
        print(f"  {'caught' if problems else 'MISSED'}  {label}")
        if problems:
            print(f"          first complaint: {problems[0].strip()}")
        else:
            missed.append(label)
    print(f"\n  {len(WRONG) - len(missed)}/{len(WRONG)} caught")
    if missed:
        print("\nRESULT: fail, this audit does not notice: " + ", ".join(missed))
        return 1

    # And the subject has to agree before it is broken, or the three above
    # would be catching a defect that was already there.
    problems = check(stage4.nmi, stage4.purity, verbose=False)
    if problems:
        print(f"\nRESULT: fail, the real implementation does not pass either: "
              f"{problems[0]}")
        return 1
    print("\nRESULT: pass, every wrong implementation is caught and the real "
          "one is not")
    return 0


def run():
    print("stage 4's grouping metrics, against an implementation sharing "
          "nothing\n")
    problems = check(stage4.nmi, stage4.purity)
    if problems:
        print(f"\nRESULT: fail, {len(problems)} check(s) did not hold")
        return 1
    print("\nRESULT: pass, two implementations agree on the hand table, on "
          f"{TRIALS} random\n  partitions, and on every invariant the "
          f"definitions require")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        sys.exit(selftest())
    if args:
        sys.exit("usage: python tools/verify_metrics.py [--selftest]")
    sys.exit(run())
