"""Every figure the documentation states, against the run that produces it.

A number in a document is a measurement that happened once. It was true when
somebody ran the tool, it stays on the page after the tool stops producing it,
and nothing in a markdown file can tell you which of those two it is. This
repository has recorded that failure more than once -- `docs/problems.md` 44's
neighbourhood is full of it, and Package 3's whole first commit was stale
figures.

So this runs the tools and checks the documents against them, two ways.

**The tables, automatically and by value.** `docs/04-detectors.md` and
`docs/packages.md` both carry a criteria table whose rows are
`(exact, NMI, purity)`. Every such row must appear as one line of
`stage4_registers.py --compare`, or -- for the null models -- of `--score`.
Matched **numerically and not textually**, so the document may write `0.80`
where the tool prints `0.8`, and matched on the *triple* rather than on the
criterion's name, because the two documents name the same criterion three
different ways and a name-matching check would be a check on prose.

**The rest, from a registry.** Figures that are not in a table -- 21.76 um
between the warm up's two register clusters, 24 of 40320 weight assignments, 46
declared holds against 12 found -- are listed in `FIGURES` below with the run
that must contain each. Same discipline as `RECORDED` in `stage4_registers`: a
figure that moves fails until somebody re-records it deliberately.

**What this does not do**, said plainly because the gap is the interesting part:
it checks the figures it was told about, not every number in every document. The
table half is automatic and will follow a document that gains a row; the
registry half will not. A figure added to a document and not to `FIGURES` is
unchecked, and nothing here can see that.

Only container-free tools are run, so this needs no Docker.

Usage:
    python tools/verify_figures.py
    python tools/verify_figures.py --selftest    # and would it notice
"""

import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The container-free runs, and the label each is known by below.
RUNS = {
    "selftest": ["tools/stage4_registers.py", "--selftest"],
    "score": ["tools/stage4_registers.py", "--score"],
    "compare": ["tools/stage4_registers.py", "--compare"],
    "warmup": ["tools/stage4_registers.py", "warmup"],
    "blocks": ["tools/verify_blocks.py"],
    "cone": ["tools/verify_cone.py", "warmup"],
    "corpus": ["tools/verify_corpus.py"],
}

# Documents whose criteria tables are checked row by row against the runs.
TABLE_DOCS = ("docs/04-detectors.md", "docs/packages.md")

# (what it is, which run must contain it, the pattern that must match there).
# Figures that are not in a table. A pattern is a regex over that run's output.
FIGURES = [
    ("the null model that returns one group", "score",
     r"one group, and do nothing\s+109/133"),
    ("the null model that splits every flop", "score",
     r"every flop its own register\s+7/133"),
    ("netlists with a flop level membership", "score",
     r"membership ground truth on 119/133"),
    ("netlists on the 0/0 convention branch", "score",
     r"109\s+one class, answer agrees"),
    ("netlists with no membership at all", "score", r"14\s+no membership"),
    ("netlists whose truth has more than one class", "compare",
     r"over the 10 netlists"),
    ("hand computed metric rows", "selftest", r"7/7 rows reproduced"),
    ("the NMI normalisation, named in the output", "selftest",
     r"arithmetic mean, 2 I\(C;T\) / \(H\(C\) \+ H\(T\)\)"),
    ("groups spanning two seed groups", "compare",
     r"groups spanning two seed groups\s+0"),
    ("netlists the flow split properly refines", "compare",
     r"netlists it refines properly\s+42"),
    ("the coarsest control signature group on the R0 analogue", "compare",
     r"one group of 82"),
    ("whole registers recovered, per criterion", "compare",
     r"(?s)control signature\s+\[82, 8\]\s+0.*"
     r"\+ connected components\s+\[56, 18, 8, 5, 3\]\s+1.*"
     r"control \+ flow split\s+\[16, 8\][^\n]*\s2"),
    ("the warm up's true partition, by membership", "blocks",
     r"connected components\s+\[8, 8\]\s+CORRECT\s+1\.000\s+1\.000"),
    ("placement locality on the warm up", "blocks",
     r"placement locality\s+\[8, 8\]\s+CORRECT\s+1\.000\s+1\.000"),
    ("the interleaved null model's verdict", "blocks",
     r"interleaved, right sizes\s+\[8, 8\]\s+RIGHT SIZES, WRONG MEMBERS\s+"
     r"0\.000\s+0\.500"),
    ("the committed criterion on the warm up", "blocks",
     r"control signature\s+\[16\]\s+wrong\s+0\.000\s+0\.500"),
    ("the spatial plateau, lower edge", "blocks",
     r"3 rows\s+8\.16 um\s+\[8, 8\]"),
    ("the spatial plateau, upper edge", "blocks",
     r"8 rows\s+21\.76 um\s+\[8, 8\]"),
    ("below the plateau", "blocks", r"2 rows\s+5\.44 um\s+\[7, 6, 2\]"),
    ("above the plateau", "blocks", r"9 rows\s+24\.48 um\s+\[16\]"),
    ("weight assignments that make the cone equivalent", "cone",
     r"24 of the 40320 possible"),
    ("operand pairs at one position in two chains", "cone",
     r"all 8 pairs lie at one position in each of two chains, 0 \.\. 7 once "
     r"each"),
    ("which end of the shift register is bit 0", "cone",
     r"chain head is the least significant bit"),
    ("holds declared against holds found", "corpus",
     r"holds declared 46: found structurally 12"),
    ("the corpus size and rule count", "corpus",
     r"97 circuits as 193 netlists.*12 rules, 738 uses"),
]

NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
ROW = re.compile(r"^\|(.+)\|\s*$")


def run_all():
    """Every container-free run, once, as {label: combined output}."""
    outputs = {}
    for label, command in RUNS.items():
        done = subprocess.run([sys.executable] + command,
                              capture_output=True, text=True, timeout=900)
        outputs[label] = done.stdout + done.stderr
    return outputs


def tool_triples(outputs):
    """(exact, NMI, purity) triples the tools actually printed.

    From `--compare`'s table, and from `--score`'s degenerate table -- whose
    right hand pair is the one over the netlists that ask the question, and the
    one the documents quote.
    """
    triples = {}
    for line in outputs["compare"].splitlines():
        found = re.match(r"\s{2}(\S.*?)\s{2,}(\d+)/(\d+)\s+(\S+)\s+(\S+)\s*$",
                         line)
        if found and NUMBER.match(found.group(4)) and NUMBER.match(found.group(5)):
            triples[(int(found.group(2)), float(found.group(4)),
                     float(found.group(5)))] = found.group(1).strip()
    for line in outputs["score"].splitlines():
        found = re.match(r"\s{2}(\S.*?)\s{2,}(\d+)/(\d+)\s+(\S+)\s+(\S+)\s+"
                         r"(\S+)\s+(\S+)\s*$", line)
        if found and all(NUMBER.match(found.group(n)) for n in (6, 7)):
            triples[(int(found.group(2)), float(found.group(6)),
                     float(found.group(7)))] = found.group(1).strip()
    return triples


def table_rows(path):
    """Every markdown table row whose first three numeric cells are a triple.

    A row is taken only when it has at least three cells that are numbers once
    emphasis is stripped, which is what a criteria row looks like and what a
    prose row does not.
    """
    rows = []
    for number, line in enumerate(open(path, encoding="utf-8"), 1):
        found = ROW.match(line.rstrip("\n"))
        if not found:
            continue
        cells = [cell.strip().strip("*_`").strip()
                 for cell in found.group(1).split("|")]
        if not cells or cells[0].startswith("---"):
            continue
        numbers = [cell for cell in cells[1:] if NUMBER.match(cell)]
        if len(numbers) < 3:
            continue
        rows.append((number, cells[0], (int(float(numbers[0])),
                                        float(numbers[1]),
                                        float(numbers[2]))))
    return rows


def check(doc_rows, figures, outputs, verbose=True):
    """Every figure against its run. Returns the list that did not hold."""
    problems = []

    def report(ok, label, detail=""):
        if verbose:
            print(f"  {'ok  ' if ok else 'FAIL'}  {label}"
                  f"{'   ' + detail if detail else ''}")
        if not ok:
            problems.append(label)

    triples = tool_triples(outputs)
    if verbose:
        print(f"the tools printed {len(triples)} distinct "
              f"(exact, NMI, purity) triples\n")
        print("criteria tables in the documents, matched by value")
    for path, number, name, triple in doc_rows:
        where = triples.get(triple)
        report(where is not None,
               f"{os.path.basename(path)}:{number} {name[:34]:<34}",
               f"{triple}" + (f" -> {where}" if where else " IN NO RUN"))

    if verbose:
        print("\nfigures that are not in a table, from the registry")
    for label, where, pattern in figures:
        if where not in outputs:
            report(False, label, f"no run named {where!r}")
            continue
        report(re.search(pattern, outputs[where]) is not None,
               f"{label[:44]:<44}", f"[{where}]")
    return problems


def collect_doc_rows():
    rows = []
    for path in TABLE_DOCS:
        if not os.path.exists(path):
            sys.exit(f"{path} is missing")
        for number, name, triple in table_rows(path):
            rows.append((path, number, name, triple))
    return rows


def selftest():
    """Would this notice? A doc row and a registry row, each made false."""
    print("running the container-free tools once, to check against\n")
    outputs = run_all()
    doc_rows = collect_doc_rows()

    print(f"the subject first: {len(doc_rows)} table rows and "
          f"{len(FIGURES)} registry figures")
    problems = check(doc_rows, FIGURES, outputs, verbose=False)
    if problems:
        print(f"  the real documents do not pass, so nothing below would "
              f"mean anything:")
        for problem in problems[:5]:
            print(f"    {problem}")
        print("\nRESULT: fail")
        return 1
    print("  all of them hold\n")

    corruptions = {
        "a table row whose exact count drifted":
            ([(p, n, name, (e + 1, m, u)) for p, n, name, (e, m, u)
              in doc_rows[:1]], FIGURES),
        "a table row whose NMI drifted in the fourth decimal":
            ([(p, n, name, (e, round(m + 0.0001, 4), u))
              for p, n, name, (e, m, u) in doc_rows[:1]], FIGURES),
        "a registry figure the run no longer produces":
            (doc_rows, FIGURES + [("a figure nothing prints", "compare",
                                   r"\b31337 netlists\b")]),
        "a registry figure pointing at a run that does not exist":
            (doc_rows, FIGURES + [("a figure from nowhere", "nowhere",
                                   r".")]),
    }
    missed = []
    for label, (rows, figures) in corruptions.items():
        found = check(rows, figures, outputs, verbose=False)
        print(f"  {'caught' if found else 'MISSED'}  {label}")
        if found:
            print(f"          {found[0].strip()}")
        else:
            missed.append(label)
    print(f"\n  {len(corruptions) - len(missed)}/{len(corruptions)} caught")
    if missed:
        print("\nRESULT: fail, this audit does not notice: " + ", ".join(missed))
        return 1
    print("\nRESULT: pass, every corruption is caught and the real documents "
          "are not")
    return 0


def run():
    print("every documented figure, against the run that produces it\n")
    outputs = run_all()
    doc_rows = collect_doc_rows()
    problems = check(doc_rows, FIGURES, outputs)
    print(f"\n{len(doc_rows)} table rows over {len(TABLE_DOCS)} documents, "
          f"{len(FIGURES)} registry figures, {len(RUNS)} runs")
    if problems:
        print(f"\nRESULT: fail, {len(problems)} figure(s) are not produced by "
              f"the run that\n  is supposed to produce them")
        return 1
    print("\nRESULT: pass. Note the limit: this checks the figures it was told "
          "about.\n  The table half follows a document that gains a row; the "
          "registry half does\n  not, and a figure added to a document and not "
          "to FIGURES is unchecked.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        sys.exit(selftest())
    if args:
        sys.exit("usage: python tools/verify_figures.py [--selftest]")
    sys.exit(run())
