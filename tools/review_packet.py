"""A review packet, generated rather than written.

Whoever reviews this work should not be reading a summary the author composed.
A summary carries the author's framing, omits what the author does not know is
missing, and points at the places the author already looked -- which are exactly
the places where nothing will be found.

So this emits evidence instead of narrative:

  * every gate command, run fresh, with the tool's own words as output
  * every score beside its null model, so a number that a criterion doing
    nothing would also achieve cannot pass for a result
  * the answer keys the repository holds, and which of them anything uses
  * the defect register, unedited
  * what is unverified, listed by the author because a reviewer cannot see the
    absence of a check as easily as the presence of one

The last of those is the only part written rather than measured, and it is
deliberately pointed at the author's blind spots rather than away from them.

Gates that fail are included as failures. A packet that only ran the passing
commands would be worse than no packet.

Usage:
    python tools/review_packet.py                 # -> out/review.md
    python tools/review_packet.py --quick         # skip the container gates
"""

import io
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = "out/review.md"

# Every gate, in the order the pipeline runs. `container` marks the ones that
# need Docker, so a reviewer without it still gets the rest.
GATES = [
    ("stage 1 and 2, against the DEF ground truth",
     ["tools/compare_def.py", "warmup"], False),
    ("stage 2, an independent second extractor",
     ["tools/stage2_unionfind.py", "warmup"], False),
    ("stage 2, the same on the puzzle",
     ["tools/stage2_unionfind.py", "puzzle"], False),
    ("stage 2, simulation against the reference, warm up",
     ["tools/sim/run.py", "warmup"], True),
    ("stage 2, simulation against the real VCD, puzzle",
     ["tools/sim/run.py", "puzzle"], True),
    ("stage 3, round trip through the graph, warm up",
     ["tools/sim/run.py", "warmup", "--netlist", "out/warmup/graph.v"], True),
    ("stage 3, round trip through the graph, puzzle",
     ["tools/sim/run.py", "puzzle", "--netlist", "out/puzzle/graph.v"], True),
    ("stage 3, annotations derived a second time, warm up",
     ["tools/stage3_crosscheck.py", "warmup"], False),
    ("stage 3, annotations derived a second time, puzzle",
     ["tools/stage3_crosscheck.py", "puzzle"], False),
    ("stage 3, and would that cross check notice if it were wrong",
     ["tools/stage3_crosscheck.py", "warmup", "--selftest"], False),
    ("stage 4, liberty functions against the PDK's behavioural models",
     ["tools/verify_functions.py"], True),
    ("stage 4, and which parser mistakes that comparison could expose",
     ["tools/verify_functions.py", "--selftest"], False),
    ("stage 4, register grouping against the corpus",
     ["tools/stage4_registers.py", "--score"], False),
    ("stage 4, the same criteria compared head to head",
     ["tools/stage4_registers.py", "--compare"], False),
    ("stage 4, against the warm up's own hierarchy from the DEF",
     ["tools/verify_blocks.py"], False),
    ("stage 5, the corpus against its declared answer key",
     ["tools/verify_corpus.py"], False),
    ("stage 5, and every rule against the corruption it exists to catch",
     ["tools/verify_corpus.py", "--selftest"], False),
    ("the size bound on what the corpus could ever name",
     ["tools/corpus_reach.py", "puzzle"], False),
]

# Ground truth the repository holds. `used_by` is filled in by grepping, not by
# memory, because the whole reason this section exists is that one of these sat
# unused for a week while a synthetic corpus was built to replace it.
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
    ("stages 6 and 7",
     "Not started. No inversion, no output extraction."),
]


def shell(command, timeout=900):
    started = time.time()
    try:
        result = subprocess.run([sys.executable] + command, capture_output=True,
                                text=True, timeout=timeout)
        return result.returncode, result.stdout, time.time() - started
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s", time.time() - started
    except Exception as error:                      # noqa: BLE001
        return None, f"could not run: {error}", time.time() - started


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


def used_by(needle):
    hits = []
    for root, dirs, files in os.walk("tools"):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if not name.endswith((".py", ".v")):
                continue
            path = os.path.join(root, name)
            try:
                if needle in open(path, encoding="utf-8", errors="replace").read():
                    hits.append(path.replace("\\", "/"))
            except OSError:
                continue
    return sorted(hits)


def main(quick=False):
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
    results = []
    for title, command, needs_container in GATES:
        if quick and needs_container:
            results.append((title, command, None, "(skipped, --quick)", 0.0))
            continue
        code, output, seconds = shell(command)
        results.append((title, command, code, output, seconds))

    w("| Gate | Exit | Seconds |\n|---|---|---|\n")
    for title, command, code, output, seconds in results:
        state = "skipped" if code is None and "--quick" in str(output) else (
            "**pass**" if code == 0 else f"**FAIL ({code})**")
        w(f"| {title} | {state} | {seconds:.1f} |\n")
    w("\n")

    for title, command, code, output, seconds in results:
        w(f"### {title}\n\n")
        w(f"```\n$ python {' '.join(command)}\n")
        text = output.strip()
        if len(text) > 6000:
            text = text[:3000] + "\n...\n[trimmed]\n...\n" + text[-3000:]
        w(text + "\n")
        w(f"\n[exit {code}]\n```\n\n")

    w("## Answer keys the repository holds\n\n")
    w("Which of these anything reads, found by searching `tools/` rather than "
      "from memory.\n\n")
    w("| File | What it is | Read by |\n|---|---|---|\n")
    for path, what in GROUND_TRUTH:
        stem = os.path.basename(path).rsplit(".", 1)[0]
        hits = used_by(stem)
        w(f"| `{path}` | {what} | "
          f"{', '.join(f'`{h}`' for h in hits) if hits else '**nothing**'} |\n")
    w("\n`00_source.v` and `01_netlist.v` were unread for the first five stages "
      "of this\nwork. `01_netlist.v` and the DEF both name every instance with "
      "the hierarchy it\ncame from, which is an exact block partition of a real "
      "design. Stage 4 was being\nscored against a synthetic corpus instead. "
      "`tools/verify_blocks.py` now uses it,\nand stage 4 fails it.\n\n")

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
        register = open("docs/problems.md", encoding="utf-8").read()
        count = register.count("\n### ")
        w(f"`docs/problems.md` holds {count} entries with symptom, cause, fix "
          f"and whether\nthe fix is understood or only worked around. It is "
          f"kept because the failures are\nmore transferable than the "
          f"successes.\n\n")
        start = register.index("## Summary")
        end = register.index("---", start)
        w(register[start:end].strip() + "\n\n")
    except (OSError, ValueError):
        w("(docs/problems.md not readable)\n\n")

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

    os.makedirs("out", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(out.getvalue())
    failed = [t for t, c, code, o, s in results if code not in (0, None)]
    print(f"wrote {OUT}, {len(out.getvalue())} bytes")
    print(f"  {len(results)} gates run, {len(failed)} failing")
    for title in failed:
        print(f"    FAIL {title}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args not in ([], ["--quick"]):
        sys.exit("usage: python tools/review_packet.py [--quick]")
    sys.exit(main(quick=bool(args)))
