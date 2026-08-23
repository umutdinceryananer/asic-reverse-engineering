"""Every figure the documentation states, against the run that produces it.

A number in a document is a measurement that happened once. It was true when
somebody ran the tool, it stays on the page after the tool stops producing it,
and nothing in a markdown file can tell you which of those two it is. This
repository has recorded that failure more than once -- `docs/problems.md` 44's
neighbourhood is full of it, and Package 3's whole first commit was stale
figures.

So this runs the tools and checks the documents against them, two ways.

**Three mechanisms, because documents quote three kinds of figure.**

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

**And `docs/05-synthetic-corpus.md`, which needed a third.** Its figures are
corpus sizes, rule counts and group counts, so neither of the two above fits --
and it is the document that most needed one. Its tables went stale twice, both
times because no gate watched them, and the second time the prose above a table
was refreshed while the table under it was not. Two shapes now cover it:

    FENCES        a fenced block presented as tool output must BE tool output.
                  Every non-blank line of it has to appear in the named run,
                  which puts twelve rule counts under one registry entry.
    DOC_NUMBERS   a number quoted in the document must equal the number the run
                  prints. Both sides capture the same groups, in the same order.

Unlike `FIGURES`, both of these read the **document** as well as the run, so a
digit changed in `docs/05` fails this gate rather than passing it quietly.

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
    # `--list` prints the catalogue and returns before it touches Yosys, so it
    # is container-free like the rest -- measured, not assumed: it exits 0 with
    # docker off PATH. It is the only run that reports the group and family
    # counts docs/05 tabulates.
    "catalogue": ["tools/stage5_corpus.py", "--list"],
    "corpus-selftest": ["tools/verify_corpus.py", "--selftest"],
}

# Documents whose criteria tables are checked row by row against the runs.
TABLE_DOCS = ("docs/04-detectors.md", "docs/packages.md")

# (what it is, which run must contain it, the pattern that must match there).
# Figures that are not in a table. A pattern is a regex over that run's output.
FIGURES = [
    ("the null model that returns one group", "score",
     r"one group, and do nothing\s+109/137"),
    ("the null model that splits every flop", "score",
     r"every flop its own register\s+7/137"),
    ("netlists with a flop level membership", "score",
     r"membership ground truth on 123/137"),
    ("netlists on the 0/0 convention branch", "score",
     r"109\s+one class, answer agrees"),
    ("netlists with no membership at all", "score", r"14\s+no membership"),
    ("netlists whose truth has more than one class", "compare",
     r"over the 14 netlists"),
    ("hand computed metric rows", "selftest", r"7/7 rows reproduced"),
    ("the NMI normalisation, named in the output", "selftest",
     r"arithmetic mean, 2 I\(C;T\) / \(H\(C\) \+ H\(T\)\)"),
    ("groups spanning two seed groups", "compare",
     r"groups spanning two seed groups\s+0"),
    ("netlists the flow split properly refines", "compare",
     r"netlists it refines properly\s+46"),
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
     r"99 circuits as 197 netlists.*12 rules, 762 uses"),
    # docs/05 claims fifteen corruptions and full rule coverage. Both halves,
    # because "every corruption caught" and "every rule covered" are different
    # sentences and the document says both.
    ("the corpus selftest's corruptions", "corpus-selftest",
     r"all 15 corruptions were caught and every rule was tripped"),
    ("the corpus selftest's rule coverage", "corpus-selftest",
     r"rule coverage: 12/12 rules"),
]

# Fenced blocks a document presents as tool output. (document, run, the line
# the block starts with). Every non-blank line between there and the closing
# fence must appear in that run's output -- not contiguously, because the tool
# prints other sections between them, but line for line.
FENCES = [
    ("docs/05-synthetic-corpus.md", "corpus",
     "99 circuits as 197 netlists {'base'"),
]


def family_count(text):
    """How many families the catalogue printed, from its own dict."""
    found = re.search(r"families: \{(.*?)\}", text, re.S)
    return (str(found.group(1).count("': ")),) if found else None


# (label, document, pattern over the document, run, pattern or callable over the
# run). Both sides must capture the same groups in the same order. Written one
# figure per entry rather than several, so a failure names the figure rather
# than a line.
#
# **What this does not reach**, said plainly because docs/05 quotes them and
# they look covered: the cell and state-element totals, the held-out split, and
# the vocabulary percentages. The first three come from a full
# `stage5_corpus.py` build, which needs Docker and forty minutes; the last comes
# from `corpus_reach.py puzzle`, which needs the target. Neither can be one of
# the container-free runs above.
DOC_NUMBERS = [
    ("docs/05: circuits whose two mappings differ",
     "docs/05-synthetic-corpus.md",
     r"and (\d+) of (\d+) land on genuinely\s+different cell mixes",
     "corpus", r"structural invariance: (\d+)/(\d+) circuits"),
    ("docs/05: holds the structural search finds",
     "docs/05-synthetic-corpus.md",
     r"finds (\d+) of \d+ declared enables",
     "corpus", r"found structurally (\d+)"),
    ("docs/05: holds the corpus declares",
     "docs/05-synthetic-corpus.md",
     r"finds \d+ of (\d+) declared enables",
     "corpus", r"holds declared (\d+):"),
    ("docs/05: circuits in the catalogue",
     "docs/05-synthetic-corpus.md",
     r"^(\d+) circuits, \d+ families",
     "catalogue", r"corpus: (\d+) circuits"),
    ("docs/05: families in the catalogue",
     "docs/05-synthetic-corpus.md",
     r"^\d+ circuits, (\d+) families",
     "catalogue", family_count),
]

# The group table in docs/05, against the catalogue's own tally. One entry per
# group, generated rather than typed, because five near-identical entries are
# five chances to typo one.
for _group in ("positive", "negative", "composed", "structure", "scale"):
    DOC_NUMBERS.append((
        f"docs/05: the {_group} group's size",
        "docs/05-synthetic-corpus.md",
        rf"\| {_group} \| (\d+) \|",
        "catalogue", rf"'{_group}': (\d+)"))


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


def fenced_block(path, opens_with):
    """The fenced block beginning with this line, as its list of lines."""
    lines = open(path, encoding="utf-8").read().splitlines()
    for index, line in enumerate(lines):
        if line.startswith(opens_with):
            block = []
            for follow in lines[index:]:
                if follow.strip() == "```":
                    return block
                block.append(follow)
            return block
    return None


def captured(spec, text):
    """The groups a pattern or a callable pulls out of some text, or None."""
    if callable(spec):
        return spec(text)
    found = re.search(spec, text, re.M | re.S)
    return found.groups() if found else None


def check(doc_rows, figures, outputs, verbose=True, fences=None,
          doc_numbers=None):
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

    fences = FENCES if fences is None else fences
    doc_numbers = DOC_NUMBERS if doc_numbers is None else doc_numbers

    if verbose and (fences or doc_numbers):
        print("\nand the documents that quote a run directly")
    for path, where, opens_with in fences:
        label = f"{os.path.basename(path)} fence, {opens_with[:28]}"
        block = fenced_block(path, opens_with)
        if block is None:
            report(False, f"{label[:44]:<44}", "no such fence in the document")
            continue
        if where not in outputs:
            report(False, f"{label[:44]:<44}", f"no run named {where!r}")
            continue
        printed = {line.strip() for line in outputs[where].splitlines()}
        astray = [line.strip() for line in block
                  if line.strip() and line.strip() not in printed]
        report(not astray, f"{label[:44]:<44}",
               f"{len(block)} lines" if not astray
               else f"{len(astray)} line(s) the run does not print: "
                    f"{astray[0][:60]!r}")

    for label, path, doc_pattern, where, run_spec in doc_numbers:
        if where not in outputs:
            report(False, f"{label[:44]:<44}", f"no run named {where!r}")
            continue
        said = captured(doc_pattern, open(path, encoding="utf-8").read())
        printed = captured(run_spec, outputs[where])
        if said is None:
            report(False, f"{label[:44]:<44}", "the document does not say it")
        elif printed is None:
            report(False, f"{label[:44]:<44}", f"the {where} run does not")
        else:
            report(said == printed, f"{label[:44]:<44}",
                   f"{'/'.join(said)}" if said == printed
                   else f"document says {'/'.join(said)}, the run prints "
                        f"{'/'.join(printed)}")
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

    print(f"the subject first: {len(doc_rows)} table rows, "
          f"{len(FIGURES)} registry figures, {len(FENCES)} quoted fence(s) "
          f"and {len(DOC_NUMBERS)} document numbers")
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
    # The two mechanisms docs/05 needed, each fed a corruption of its own.
    # These are the ones that read the *document*, so they are the only ones
    # that would notice a digit changed there.
    document = [
        ("a docs/05 number that no longer matches the run",
         # The document's own real sentence, held against the wrong figure in
         # the run: 54 circuits differ, 46 enables are declared. A digit
         # changed on either side is indistinguishable from this.
         dict(doc_numbers=[
             ("the differing-mappings count against the wrong run figure",
              DOC_NUMBERS[0][1], r"and (\d+) of \d+ land on genuinely",
              DOC_NUMBERS[0][3], r"holds declared (\d+):")],
              fences=[])),
        ("a docs/05 fence line the run does not print",
         dict(fences=[(FENCES[0][0], FENCES[0][1], "no such line anywhere")],
              doc_numbers=[])),
    ]
    for label, kwargs in document:
        found = check([], [], outputs, verbose=False, **kwargs)
        print(f"  {'caught' if found else 'MISSED'}  {label}")
        if found:
            print(f"          {found[0].strip()}")
        else:
            missed.append(label)

    total = len(corruptions) + len(document)
    print(f"\n  {total - len(missed)}/{total} caught")
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
          f"{len(FIGURES)} registry figures, {len(FENCES)} quoted fence(s), "
          f"{len(DOC_NUMBERS)} document numbers, {len(RUNS)} runs")
    if problems:
        print(f"\nRESULT: fail, {len(problems)} figure(s) are not produced by "
              f"the run that\n  is supposed to produce them")
        return 1
    print("\nRESULT: pass. Note the limit: this checks the figures it was told "
          "about.\n  The table half follows a document that gains a row; the "
          "registry, fence and\n  document-number halves do not, and a figure "
          "added to a document and not\n  registered here is unchecked.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        sys.exit(selftest())
    if args:
        sys.exit("usage: python tools/verify_figures.py [--selftest]")
    sys.exit(run())
