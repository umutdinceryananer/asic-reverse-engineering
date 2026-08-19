"""A review packet, generated rather than written.

Whoever reviews this work should not be reading a summary the author composed.
A summary carries the author's framing, omits what the author does not know is
missing, and points at the places the author already looked -- which are exactly
the places where nothing will be found.

So this emits evidence instead of narrative:

  * every gate command, run fresh, with the tool's own words as output
  * every score beside its null model, so a number that a criterion doing
    nothing would also achieve cannot pass for a result
  * the answer keys the repository holds, and which of them anything reads
  * the defect register, unedited
  * what is unverified, listed by the author because a reviewer cannot see the
    absence of a check as easily as the presence of one

The last of those is the only part written rather than measured, and it is
deliberately pointed at the author's blind spots rather than away from them.

Gates that fail are included as failures. A packet that only ran the passing
commands would be worse than no packet.

**This file is evidence of record, so its own reporting is checked.** A review
found three ways it was misreporting by accident: the defect register was
truncated to zero rows by a slice that stopped at a markdown table separator,
the "read by" column was a substring search over basenames and got every row
wrong in one direction or the other, and a tool that measures without asserting
was rendered in the same **pass** cell as a real gate. `verify()` below
re-derives what this file claims and refuses to write the packet if a claim
does not hold.

Usage:
    python tools/review_packet.py                 # -> out/review.md
    python tools/review_packet.py --quick         # skip the container gates
"""

import ast
import io
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "out/review.md"

# Every gate, in the order the pipeline runs. `container` marks the ones that
# need Docker, so a reviewer without it still gets the rest.
#
# `kind` separates a gate from a report. A gate asserts and can exit non-zero; a
# report measures and always exits 0. Both are worth running and only one is
# evidence that something held, and rendering them in the same **pass** cell
# made `corpus_reach.py` -- which `CLAUDE.md` itself labels "not a gate" -- read
# as a passing check. `verify()` re-derives the distinction from each tool's
# source rather than trusting the word written here.
GATES = [
    ("stage 1 and 2, against the DEF ground truth",
     ["tools/compare_def.py", "warmup"], False, "gate"),
    ("stage 2, an independent second extractor",
     ["tools/stage2_unionfind.py", "warmup"], False, "gate"),
    ("stage 2, the same on the puzzle",
     ["tools/stage2_unionfind.py", "puzzle"], False, "gate"),
    ("stage 2, simulation against the reference, warm up",
     ["tools/sim/run.py", "warmup"], True, "gate"),
    ("stage 2, simulation against the real VCD, puzzle",
     ["tools/sim/run.py", "puzzle"], True, "gate"),
    ("stage 3, round trip through the graph, warm up",
     ["tools/sim/run.py", "warmup", "--netlist", "out/warmup/graph.v"], True,
     "gate"),
    ("stage 3, round trip through the graph, puzzle",
     ["tools/sim/run.py", "puzzle", "--netlist", "out/puzzle/graph.v"], True,
     "gate"),
    ("stage 3, annotations derived a second time, warm up",
     ["tools/stage3_crosscheck.py", "warmup"], False, "gate"),
    ("stage 3, annotations derived a second time, puzzle",
     ["tools/stage3_crosscheck.py", "puzzle"], False, "gate"),
    ("stage 3, and would that cross check notice if it were wrong",
     ["tools/stage3_crosscheck.py", "warmup", "--selftest"], False, "gate"),
    ("stage 4, liberty functions against the PDK's behavioural models",
     ["tools/verify_functions.py"], True, "gate"),
    ("stage 4, and which parser mistakes that comparison could expose",
     ["tools/verify_functions.py", "--selftest"], False, "gate"),
    ("stage 4, register grouping against the corpus",
     ["tools/stage4_registers.py", "--score"], False, "gate"),
    ("stage 4, the same criteria compared head to head",
     ["tools/stage4_registers.py", "--compare"], False, "gate"),
    ("stage 4, against the warm up's own hierarchy from the DEF",
     ["tools/verify_blocks.py"], False, "gate"),
    ("stage 5, the corpus against its declared answer key",
     ["tools/verify_corpus.py"], False, "gate"),
    ("stage 5, and every rule against the corruption it exists to catch",
     ["tools/verify_corpus.py", "--selftest"], False, "gate"),
    ("the size bound on what the corpus could ever name",
     ["tools/corpus_reach.py", "puzzle"], False, "report"),
]

# Ground truth the repository holds.
GROUND_TRUTH = [
    ("puzzle/warmup/00_source.v", "the warm up's RTL: what the design is"),
    ("puzzle/warmup/01_netlist.v", "reference gate netlist, with hierarchy names"),
    ("puzzle/warmup/02_netlist_with_power_rails.v", "the same, with supplies"),
    ("puzzle/warmup/03_post_place_and_route.def",
     "placement and routing, with hierarchy names"),
    ("puzzle/warmup/04_final.gds", "the warm up layout, stage 1's input"),
    ("puzzle/example_inputs.vcd", "a real test vector for the puzzle"),
    ("puzzle/puzzle.gds", "the target"),
]

# What actually opens each of them, and by what mechanism.
#
# This was `grep tools/ for the basename stem`, and this section exists because
# one of these files sat unused for five stages -- so a wrong answer here is
# worse than no answer. Every row that search produced was wrong in one
# direction or the other. It credited this file with reading all seven, because
# this file names them. It credited twenty three tools with reading
# `puzzle.gds`, because the stem is `puzzle` and half the repository mentions
# the word. It credited `verify_blocks.py` with `01_netlist.v`, which that tool
# mentions in its opening paragraph and never opens. And it missed
# `stage2_nets.py`, `stage2_unionfind.py` and `stack_sensitivity.py`, which
# reach the layouts through `stage1_cells.TARGETS` and never name a path at all.
#
# So the claims are explicit, and `verify()` checks each against the tool's
# parsed source and refuses to write the packet if the registry has drifted:
#
#   "names it"        the path appears in the tool's *code*, docstrings
#                     excluded -- which is what separates opening a file from
#                     mentioning it in a usage line
#   "via TARGETS[k]"  the tool imports `stage1_cells.TARGETS`, subscripts it,
#                     and uses the key `k`; and TARGETS[...][k] names this path.
#                     Importing TARGETS is not enough on its own: five tools
#                     import it only to validate a command line argument.
#
# `00_source.v`, `01_netlist.v` and `02_netlist_with_power_rails.v` are read by
# nothing. That is the honest answer and the useful one: two of them name every
# instance with the block it came from, which is an exact block partition of a
# real design, and stage 4 was scored against a synthetic corpus instead.
READERS = {
    "puzzle/warmup/00_source.v": [],
    "puzzle/warmup/01_netlist.v": [],
    "puzzle/warmup/02_netlist_with_power_rails.v": [],
    "puzzle/warmup/03_post_place_and_route.def": [
        ("tools/stage1_cells.py", "names it"),
        ("tools/compare_def.py", "via TARGETS[def]"),
        ("tools/verify_blocks.py", "names it"),
    ],
    "puzzle/warmup/04_final.gds": [
        ("tools/stage1_cells.py", "names it"),
        ("tools/stage2_nets.py", "via TARGETS[gds]"),
        ("tools/stage2_unionfind.py", "via TARGETS[gds]"),
        ("tools/stack_sensitivity.py", "via TARGETS[gds]"),
    ],
    "puzzle/example_inputs.vcd": [
        ("tools/sim/make_puzzle_stimulus.py", "names it"),
    ],
    "puzzle/puzzle.gds": [
        ("tools/stage1_cells.py", "names it"),
        ("tools/stage2_nets.py", "via TARGETS[gds]"),
        ("tools/stage2_unionfind.py", "via TARGETS[gds]"),
        ("tools/stack_sensitivity.py", "via TARGETS[gds]"),
    ],
}

# Written, not measured. Where a check and the code it checks share an author,
# a reviewer should assume the check inherits the code's blind spots.
UNVERIFIED = [
    ("tools/stage4_cone.py",
     "No check of any kind. It walks a cone, substitutes names and orders the "
     "result, and nothing confirms the listing matches the netlist. This is the "
     "artifact the analysis week is meant to read."),
    ("tools/stage4_registers.py",
     "Scored against a corpus this author wrote, and against the warm up, which "
     "it fails. No criterion is committed. The disagreement between criteria is "
     "unresolved and is the honest state, not a finished result."),
    ("tools/stage5_corpus.py",
     "The corpus is the answer key for most of stage 4, and this author wrote "
     "both. Its catalogue was extended four times in response to measurements "
     "against the target, which weakens held-out scores in a known direction. "
     "docs/05-synthetic-corpus.md states this."),
    ("liberty role derivation",
     "stage 3 and stage3_crosscheck.py both read cell roles from liberty. That "
     "reading is genuinely shared and neither checks it. Only the attribution "
     "-- which net reached which pin -- is derived twice."),
    ("expression precedence",
     "verify_functions.py compares 850 truth tables against the PDK models and "
     "no function in this library exercises operator precedence, so those 850 "
     "are no evidence about it. Eight hand written tables are, and three of the "
     "eight were wrong when first written."),
    ("this file's own reporting",
     "It is generated, which makes it look measured, and three of its sections "
     "were reporting something other than what they said: a truncated defect "
     "register, a substring search presented as an inventory, and a report "
     "rendered as a passing gate. Read a claim here as a claim."),
    ("stages 6 and 7",
     "Not started. No inversion, no output extraction."),
]


# --------------------------------------------------------------------------
# Reading a tool's source rather than grepping it. Everything in this section
# exists because a grep cannot tell a path a tool opens from a path a tool
# mentions, and cannot see a path a tool never names at all.


def parsed(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return ast.parse(handle.read())


def code_strings(path):
    """Every string constant in a module's code, with the docstrings removed.

    The distinction is the whole point. `verify_blocks.py` names `01_netlist.v`
    in its opening paragraph and opens only the DEF; `gds_survey.py` names
    `04_final.gds` in a usage line and reads whatever `argv` hands it. Comments
    never reach the tree at all, so they are excluded for free.
    """
    tree = parsed(path)
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        head = node.body[0] if node.body else None
        if (isinstance(head, ast.Expr) and isinstance(head.value, ast.Constant)
                and isinstance(head.value.value, str)):
            docstrings.add(id(head.value))
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings}


def names_path(strings, target):
    """Does this set of code strings resolve that path?

    Either whole, or as the components of an `os.path.join`, which is how
    `make_puzzle_stimulus.py` names the VCD.
    """
    if any(target in text for text in strings):
        return True
    parts = target.split("/")
    return len(parts) > 1 and all(part in strings for part in parts)


def targets_use(path):
    """(imports stage1_cells.TARGETS, subscripts it, the subscript keys used).

    Importing is not using. Five tools import TARGETS only to check a command
    line argument against it and never resolve a path, so the import on its own
    would credit them with reading a layout they never open.
    """
    tree = parsed(path)
    imports = any(isinstance(n, ast.ImportFrom) and n.module == "stage1_cells"
                  and any(a.name == "TARGETS" for a in n.names)
                  for n in ast.walk(tree))
    subscripts = any(isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                     and n.value.id == "TARGETS" for n in ast.walk(tree))
    keys = {n.slice.value for n in ast.walk(tree)
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
            and isinstance(n.slice.value, str)}
    return imports, subscripts, keys


def can_exit_non_zero(path):
    """Does this tool have any literal non-zero exit status in it?

    The mechanical form of "is this a gate or a report". A tool that only ever
    returns 0 measures; one that can return 1 asserts. `corpus_reach.py` and
    `stack_sensitivity.py` are the only two here with no such path, and
    `CLAUDE.md` calls both of them "not a gate" -- arrived at from the other
    direction, which is why it is worth deriving rather than declaring.
    """
    for node in ast.walk(parsed(path)):
        if isinstance(node, ast.Return) and node.value is not None:
            subtree = node.value
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "exit" and node.args):
            subtree = node.args[0]
        else:
            continue
        for inner in ast.walk(subtree):
            if (isinstance(inner, ast.Constant)
                    and isinstance(inner.value, int)
                    and not isinstance(inner.value, bool) and inner.value != 0):
                return True
    return False


def every_tool():
    found = []
    for root, dirs, files in os.walk("tools"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(root, name).replace("\\", "/"))
    return found


def verify():
    """Everything this file claims about the repository, re-derived.

    Returns the list of claims that did not hold. A packet that cannot
    substantiate its own tables is worse than no packet, so a non-empty list
    stops the write.
    """
    problems = []
    import stage1_cells                                    # noqa: PLC0415

    claimed = {path: {tool for tool, _ in rows} for path, rows in READERS.items()}

    # Forward: does every claim hold?
    for target, rows in READERS.items():
        for tool, mechanism in rows:
            if not os.path.exists(tool):
                problems.append(f"READERS names {tool}, which does not exist")
            elif mechanism == "names it":
                if not names_path(code_strings(tool), target):
                    problems.append(f"{tool} is claimed to name {target} in its "
                                    f"code, and does not")
            elif mechanism.startswith("via TARGETS["):
                key = mechanism[len("via TARGETS["):-1]
                imports, subscripts, keys = targets_use(tool)
                reachable = {config.get(key)
                             for config in stage1_cells.TARGETS.values()}
                if not (imports and subscripts and key in keys):
                    problems.append(f"{tool} is claimed to reach {target} "
                                    f"through TARGETS[{key}] and does not: "
                                    f"imports={imports} subscripts={subscripts} "
                                    f"key used={key in keys}")
                elif target not in reachable:
                    problems.append(f"TARGETS[...][{key}] does not name "
                                    f"{target}, claimed for {tool}")
            else:
                problems.append(f"unknown mechanism {mechanism!r} for {tool}")

    # Reverse, by name: a tool that resolves one of these paths and is not
    # registered. This is what would catch a new reader of an answer key.
    for tool in every_tool():
        if tool == "tools/review_packet.py":
            continue
        try:
            strings = code_strings(tool)
        except SyntaxError as error:
            problems.append(f"{tool} does not parse: {error}")
            continue
        for target in READERS:
            if names_path(strings, target) and tool not in claimed[target]:
                problems.append(f"{tool} names {target} in its code and is not "
                                f"in READERS")

    # Reverse, through TARGETS: a tool that resolves a layout that way and is
    # registered against nothing.
    registered = {tool for rows in READERS.values() for tool, _ in rows}
    for tool in every_tool():
        imports, subscripts, _ = targets_use(tool)
        if imports and subscripts and tool not in registered:
            problems.append(f"{tool} resolves a path through TARGETS and is "
                            f"not in READERS")

    # Is each row's declared kind what its own source says it is?
    for _, command, _, kind in GATES:
        tool = command[0]
        if kind not in ("gate", "report"):
            problems.append(f"{tool}: unknown kind {kind!r}")
        elif can_exit_non_zero(tool) != (kind == "gate"):
            problems.append(
                f"{tool} is declared a {kind} and its source disagrees: a "
                f"literal non-zero exit is "
                f"{'present' if kind == 'report' else 'absent'}")
    return problems


# --------------------------------------------------------------------------


def shell(command, timeout=900):
    started = time.time()
    try:
        result = subprocess.run([sys.executable] + command, capture_output=True,
                                text=True, timeout=timeout)
        return (result.returncode, result.stdout, result.stderr,
                time.time() - started)
    except subprocess.TimeoutExpired:
        return None, "", f"timed out after {timeout}s", time.time() - started
    except Exception as error:                      # noqa: BLE001
        return None, "", f"could not run: {error}", time.time() - started


def git(*args):
    try:
        return subprocess.run(["git"] + list(args), capture_output=True,
                              text=True).stdout.strip()
    except Exception:                               # noqa: BLE001
        return "(git unavailable)"


def inventory():
    rows = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs
                   if d not in (".git", ".venv", "__pycache__", "out", "pdk",
                                "synth", "puzzle", ".vscode")]
        for name in sorted(files):
            if not name.endswith((".py", ".md", ".v")):
                continue
            path = os.path.join(root, name).replace("\\", "/").lstrip("./")
            try:
                lines = sum(1 for _ in open(path, encoding="utf-8", errors="replace"))
            except OSError:
                continue
            rows.append((path, lines))
    return sorted(rows)


def defect_register():
    """The register's summary table, its entry count, and its row count.

    The slice used to end at `register.index("---", start)`, which finds the
    `|---|---|---|---|` separator of the table's own header row, so every packet
    since it was written showed the heading, the header, and none of the rows
    underneath. The terminator wanted is the horizontal rule, which is a `---`
    alone on its line.

    The count was `register.count("\\n### ")`, which is one too many, because
    one heading in the register is a discussion and not a numbered entry.

    Returning both the entry count and the row count lets the caller check them
    against each other, which is how a register that grew an entry without a
    summary row becomes visible.
    """
    with open("docs/problems.md", encoding="utf-8") as handle:
        register = handle.read()
    entries = len(re.findall(r"(?m)^### \d+\.", register))
    start = register.index("## Summary")
    rule = re.compile(r"(?m)^-{3,}\s*$").search(register, start)
    if rule is None:
        raise ValueError("no horizontal rule after '## Summary' in problems.md")
    body = register[start:rule.start()].strip()
    rows = len(re.findall(r"(?m)^\| \d+ \|", body))
    return body, entries, rows


def main(quick=False):
    problems = verify()
    out = io.StringIO()
    w = out.write

    w("# Review packet\n\n")
    w("Generated by `tools/review_packet.py`. Rerun it and this file is "
      "reproduced.\n\n")
    w("Everything below except the last section is measured. The last section "
      "is written\nby the author and points at the author's own blind spots, "
      "which is the one thing\na reviewer cannot easily see: the absence of a "
      "check does not announce itself.\n\n")
    w(f"Commit `{git('rev-parse', '--short', 'HEAD')}` on "
      f"`{git('rev-parse', '--abbrev-ref', 'HEAD')}`.\n\n")

    w("## What this is\n\n")
    w("A pipeline that recovers an ASIC's function from its layout, for the "
      "Jane Street\n2026 puzzle. Seven stages. The deliverable is the pipeline; "
      "the puzzle is its first\ntest case. `docs/solver-pipeline.md` is the "
      "build spec and `docs/jane-street-asic-roadmap.md`\nis the schedule.\n\n")
    w("To reproduce: `docs/00-environment.md` and the Environment section of "
      "`CLAUDE.md`.\nThe container gates need Docker; the rest do not.\n\n")

    w("## Gates, run fresh\n\n")
    w("Failures are included. Exit status is the tool's own.\n\n")
    w("A **gate** asserts and can exit non-zero. A **report** measures and "
      "always exits 0,\nso it is evidence about the design and never evidence "
      "that something held. Which of\nthe two a row is comes from the tool's "
      "source and not from this table: a report used\nto be rendered in the "
      "same **pass** cell as a gate.\n\n")
    results = []
    for title, command, needs_container, kind in GATES:
        if quick and needs_container:
            results.append((title, command, kind, None, "", "", 0.0))
            continue
        code, output, errors, seconds = shell(command)
        results.append((title, command, kind, code, output, errors, seconds))

    w("| Row | Kind | Exit | Seconds |\n|---|---|---|---|\n")
    for title, command, kind, code, output, errors, seconds in results:
        if code is None:
            state = "skipped"
        elif kind == "report":
            state = "report" if code == 0 else f"**REPORT DIED ({code})**"
        else:
            state = "**pass**" if code == 0 else f"**FAIL ({code})**"
        w(f"| {title} | {kind} | {state} | {seconds:.1f} |\n")
    w("\n")

    for title, command, kind, code, output, errors, seconds in results:
        w(f"### {title}\n\n")
        w(f"```\n$ python {' '.join(command)}\n")
        text = output.strip()
        if len(text) > 6000:
            text = text[:3000] + "\n...\n[trimmed]\n...\n" + text[-3000:]
        w((text if text else "(nothing on stdout)") + "\n")
        # stderr, which used to be captured and then dropped. A tool that dies
        # through `sys.exit("message")` or a traceback writes there and nowhere
        # else, so a FAIL row sat above an empty block with no reason in it.
        trimmed = (errors or "").strip()
        if trimmed:
            if len(trimmed) > 4000:
                trimmed = trimmed[:2000] + "\n...\n[trimmed]\n...\n" + trimmed[-2000:]
            w("\n--- stderr ---\n" + trimmed + "\n")
        w(f"\n[exit {code}]\n```\n\n")

    w("## Answer keys the repository holds\n\n")
    w("Which of these anything reads, and by what mechanism. Every claim below "
      "is\nre-derived from the named tool's parsed source when this file is "
      "generated, and the\npacket is not written if one does not hold. "
      "Mentioning a path in a docstring is not\nreading it, and a tool that "
      "never names a path can still open it through\n"
      "`stage1_cells.TARGETS`.\n\n")
    w("| File | What it is | Read by |\n|---|---|---|\n")
    for path, what in GROUND_TRUTH:
        rows = READERS.get(path, [])
        who = ", ".join(f"`{tool}` ({how})" for tool, how in rows) or "**nothing**"
        w(f"| `{path}` | {what} | {who} |\n")
    w("\n`00_source.v` and `01_netlist.v` were unread for the first five stages "
      "of this\nwork, and are unread still. `01_netlist.v` and the DEF both name "
      "every instance\nwith the hierarchy it came from, which is an exact block "
      "partition of a real\ndesign. Stage 4 was being scored against a synthetic "
      "corpus instead.\n`tools/verify_blocks.py` now uses the DEF, and stage 4 "
      "fails it.\n\n")

    w("## Repository\n\n")
    rows = inventory()
    code_lines = sum(n for p, n in rows if p.endswith(".py"))
    doc_lines = sum(n for p, n in rows if p.endswith(".md"))
    w(f"{len([p for p, _ in rows if p.endswith('.py')])} Python files, "
      f"{code_lines} lines. "
      f"{len([p for p, _ in rows if p.endswith('.md')])} documents, "
      f"{doc_lines} lines.\n\n")
    w("`out/`, `synth/` and `pdk/` are generated and not in the repository.\n\n")
    w("| File | Lines |\n|---|---|\n")
    for path, lines in rows:
        w(f"| `{path}` | {lines} |\n")
    w("\n")

    w("## History\n\n```\n")
    w(git("log", "--oneline", "-40") + "\n```\n\n")

    w("## Defects already found and recorded\n\n")
    try:
        body, entries, table_rows = defect_register()
        w(f"`docs/problems.md` holds {entries} entries with symptom, cause, fix "
          f"and whether\nthe fix is understood or only worked around. It is "
          f"kept because the failures are\nmore transferable than the "
          f"successes. All {table_rows} summary rows follow.\n\n")
        w(body + "\n\n")
        if table_rows != entries:
            problems.append(f"docs/problems.md has {entries} entries and "
                            f"{table_rows} summary rows")
    except (OSError, ValueError, KeyError) as error:
        # Not swallowed. This section is the register of what went wrong, and a
        # packet that quietly prints "(not readable)" in its place is the same
        # class of defect as the slice that truncated it to nothing.
        w(f"**Could not read the defect register: "
          f"{type(error).__name__}: {error}**\n\n")
        problems.append(f"defect register unreadable: "
                        f"{type(error).__name__}: {error}")

    w("## Where the author's judgement is least reliable\n\n")
    w("Written, not measured. A reviewer can see a check that exists; a check "
      "that was\nnever written looks the same as a thing that needs no check.\n\n")
    for subject, why in UNVERIFIED:
        w(f"**{subject}.** {why}\n\n")
    w("The general shape, visible in `docs/problems.md`: the defect rate tracks "
      "whether\na check is external. Stages 1 and 2 are graded against a DEF, a "
      "reference netlist\nand a real VCD, and few defects survived them. Stage 5 "
      "is graded against an answer\nkey the same author wrote, and most of the "
      "recorded defects are there. Stage 4 was\nbeing graded against stage 5.\n\n")

    if problems:
        print(f"{len(problems)} claim(s) this packet makes about the repository "
              f"do not hold, so {OUT} was not written:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    os.makedirs("out", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(out.getvalue())
    gates = [r for r in results if r[2] == "gate"]
    reports = [r for r in results if r[2] == "report"]
    failed = [r[0] for r in results if r[3] not in (0, None)]
    print(f"wrote {OUT}, {len(out.getvalue())} bytes")
    print(f"  {len(gates)} gates and {len(reports)} reports run, "
          f"{len(failed)} failing")
    for title in failed:
        print(f"    FAIL {title}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args not in ([], ["--quick"]):
        sys.exit("usage: python tools/review_packet.py [--quick]")
    sys.exit(main(quick=bool(args)))
