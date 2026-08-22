"""The same input twice, under two hash seeds, byte for byte.

Python randomises the hash of strings and of anything built from them, per
process, unless `PYTHONHASHSEED` says otherwise. Any code that iterates a `set`
or a `dict` keyed on strings and writes the result out is therefore
nondeterministic across runs, and it does not announce itself: the answer is
correct every time and the bytes differ.

That matters more here than in most repositories. Stage 4's numbers are held to
recordings -- `RECORDED`, `RECORDED_CRITERIA`, `RECORDED_DEMONSTRATIONS` -- and
a recording is only worth having if the thing recorded is reproducible. An
artifact whose group order shuffles between runs cannot be diffed, cannot be
bisected, and turns every re-record into a coin toss.

Package 4 added three things that build partitions out of sets and dictionaries
keyed on instance names: the flow split, the placement clustering and the bit
order. This runs each of them twice, under `PYTHONHASHSEED=1` and
`PYTHONHASHSEED=424242`, and compares the bytes.

**What this does not cover.** Only the cases listed in `CASES`. It is not a
sweep over every artifact the pipeline writes, and a new tool that shuffles its
output will not be caught unless somebody adds it here.

Usage:
    python tools/verify_determinism.py
    python tools/verify_determinism.py --selftest    # and would it notice
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Two seeds rather than one: `PYTHONHASHSEED=0` disables randomisation
# altogether, which would make every run agree for the wrong reason. These are
# two different randomisations, so agreement means the output does not depend on
# one.
SEEDS = ("1", "424242")

# A corpus circuit at the size that matters. `scale_datapath` is the R0 analogue,
# 90 flops in seven declared registers, and it exercises the flow split, the
# refinement and the bit order all at once -- a four flop register would not.
CORPUS_DRIVER = (
    "import json,sys;"
    "sys.path.insert(0,'tools');"
    "import stage4_registers as s;"
    "index=json.load(open('out/synth/index.json',encoding='utf-8'))['circuits'];"
    "row=[e for e in index if e['name']=='scale_datapath_w16_b8'"
    " and e['variant']=='base'][0];"
    "g=json.load(open(row['dir']+'/graph.json',encoding='utf-8'));"
    "print(json.dumps(s.analyse(g),indent=1));"
    "print(json.dumps({n:sorted((len(m) for m in c(g).values()),reverse=True)"
    " for n,c in s.CRITERIA.items()},indent=1))"
)

# (label, argv, artifact or None to compare stdout)
CASES = [
    ("registers.json on the warm up, bit_order included",
     ["tools/stage4_registers.py", "warmup"], "out/warmup/registers.json"),
    ("every criterion compared, over the corpus",
     ["tools/stage4_registers.py", "--compare"], None),
    ("analyse() and every criterion on scale_datapath_w16_b8",
     ["-c", CORPUS_DRIVER], None),
]


def once(argv, seed, artifact):
    """One run under one seed. Returns (stdout bytes, artifact bytes or None)."""
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    done = subprocess.run([sys.executable] + argv, capture_output=True,
                          env=env, timeout=900)
    if done.returncode != 0:
        return None, (done.stderr or done.stdout or b"").decode(
            "utf-8", "replace")[-400:]
    body = done.stdout
    if artifact is not None:
        if not os.path.exists(artifact):
            return None, f"{artifact} was not written"
        with open(artifact, "rb") as handle:
            body = handle.read()
    return body, ""


def check(cases, verbose=True):
    """Every case under both seeds. Returns the ones that differed."""
    problems = []
    for label, argv, artifact in cases:
        outputs, failure = [], ""
        for seed in SEEDS:
            body, why = once(argv, seed, artifact)
            if body is None:
                failure = f"seed {seed}: {why}"
                break
            outputs.append(body)
        if failure:
            if verbose:
                print(f"  FAIL  {label}")
                print(f"        {failure}")
            problems.append(label)
            continue
        same = outputs[0] == outputs[1]
        where = artifact or "stdout"
        if verbose:
            size = len(outputs[0])
            print(f"  {'ok  ' if same else 'FAIL'}  {label}")
            print(f"        {where}, {size} bytes, seeds "
                  f"{SEEDS[0]} and {SEEDS[1]}"
                  + ("" if same else "   BYTES DIFFER"))
        if not same:
            first = next((n for n, (a, b) in
                          enumerate(zip(outputs[0], outputs[1])) if a != b),
                         min(len(outputs[0]), len(outputs[1])))
            if verbose:
                head = outputs[0][max(0, first - 40):first + 40]
                print(f"        first difference at byte {first}: "
                      f"{head.decode('utf-8', 'replace')!r}")
            problems.append(label)
    return problems


# Nondeterminism planted on purpose, for `--selftest`. The first is the textbook
# shape -- a set of strings iterated into a list -- and the second puts the same
# shape inside the real code path, replacing the function that gives registers
# their stable names with one that orders them by set iteration.
#
# **The second was written against the warm up first, and was inert.** The warm
# up's sixteen flops sit under ONE control signature, so `group_names` was handed
# a single group, a set of one tuple has no order to shuffle, and the plant
# produced identical bytes under both seeds -- a corruption that could not
# corrupt. It runs on `scale_datapath` instead, with the refinement standing in
# for the control signature so there are 65 groups to shuffle. Same lesson as
# the diamond in `verify_grouping.py`: a known-bad input has to be able to be
# bad.
PLANTED_PLAIN = (
    "print(list({'alpha','beta','gamma','delta','epsilon','zeta','eta'}))"
)
PLANTED_REAL = (
    "import json,sys;"
    "sys.path.insert(0,'tools');"
    "import stage4_registers as s;"
    "index=json.load(open('out/synth/index.json',encoding='utf-8'))['circuits'];"
    "row=[e for e in index if e['name']=='scale_datapath_w16_b8'"
    " and e['variant']=='base'][0];"
    "g=json.load(open(row['dir']+'/graph.json',encoding='utf-8'));"
    "s.control_groups=s.refined_to_fixed_point;"
    "s.group_names=lambda gr,groups:{f'R{i}':list(m) for i,m in"
    " enumerate({tuple(v) for v in groups.values()})};"
    "print(json.dumps(s.analyse(g),indent=1))"
)


def selftest():
    print("the check against nondeterminism planted on purpose\n")
    print("the real cases first, so nothing below is catching a defect that "
          "was already there")
    problems = check(CASES, verbose=False)
    if problems:
        print(f"  the pipeline is already nondeterministic: {problems}")
        print("\nRESULT: fail")
        return 1
    print(f"  all {len(CASES)} are byte identical\n")

    planted = [
        ("a set of strings iterated into a list", ["-c", PLANTED_PLAIN], None),
        ("group_names ordered by set iteration, inside analyse(), on a "
         "design with 65 groups", ["-c", PLANTED_REAL], None),
    ]
    missed = []
    for case in planted:
        found = check([case], verbose=False)
        print(f"  {'caught' if found else 'MISSED'}  {case[0]}")
        if not found:
            missed.append(case[0])
    print(f"\n  {len(planted) - len(missed)}/{len(planted)} caught")
    if missed:
        print("\nRESULT: fail, this check does not notice: " + ", ".join(missed))
        return 1
    print("\nRESULT: pass, planted nondeterminism is caught and the real "
          "cases are not")
    return 0


def run():
    print(f"the same input twice, under PYTHONHASHSEED={SEEDS[0]} and "
          f"{SEEDS[1]}\n")
    problems = check(CASES)
    if problems:
        print(f"\nRESULT: fail, {len(problems)} of {len(CASES)} case(s) are "
              f"not reproducible.\n  An artifact whose bytes depend on the "
              f"hash seed cannot be diffed, bisected\n  or recorded.")
        return 1
    print(f"\nRESULT: pass, all {len(CASES)} byte identical under both seeds. "
          f"Note the limit:\n  only the cases listed in CASES are covered, and "
          f"a new tool that shuffles its\n  output is not caught unless "
          f"somebody adds it.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        sys.exit(selftest())
    if args:
        sys.exit("usage: python tools/verify_determinism.py [--selftest]")
    sys.exit(run())
