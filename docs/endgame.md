# Endgame — 23 August to 4 September 2026

The build is done, stage 7 included. From here the critical path is the
author's time, not tooling. This file replaces the stale dates in
`docs/jane-street-asic-roadmap.md`; the phase logic there still stands. It is
also the working road map: what to run, in what order, and — the part no
checklist had — **how to do the interpretation**.

Rule carried over: submit by 2 September, not 4 — the relocation risk sits
exactly on the deadline.

## Read this first: one ordering change

An earlier version of this file put stage 7 on 29–31 August. That is too late,
for two reasons.

**The string may be the strongest clue you have.** If the chip emits text that
names what it computes, spending analysis week without it means saving your best
evidence for last.

**Stage 6 has never run on the puzzle.** Nobody knows what it costs at 92 flops
and depth ~121–160. Started today, a problem leaves nine days to solve it;
started on the 29th, two.

So: **start stage 6 today and study while it runs.**

## Phase 0 — today, about an hour of attention

```bash
python tools/review_packet.py --preflight      # is Docker up; ten seconds
python tools/stage1_cells.py puzzle --library pdk/open_pdks_sky130A
```

The second is cheap and **both answers are writeup material**: if the 22
structural fallbacks drop to 0 the open_pdks hypothesis is confirmed; if they do
not, that is a dead end worth one honest sentence.

Then start the long one and leave it:

```bash
python tools/stage6_invert.py puzzle --post-reset
```

Read lecture 07 while it runs. It is the shortest, and you need it the moment
stage 6 returns.

- [x] Package 6 (stage 7, output extraction) handed over, returned and
      validated. Last planned package. Landed as `83bddd3`: the shared Icarus
      harness, `stage7_output.py`, `verify_output.py`, the `streamer` corpus
      family, and problems 52 and 53.
- [x] Commit the untracked docs. Nine files, not five: `docs/05` refreshed,
      lectures 04–**07**, `references.md` with the open_pdks revision
      correction, `design-competition-toolchain.md`, this file, and `README.md`
      — the first eight as `d4527f9`, the README with the handover audit.
- [x] Handover audit: docs/05 and lectures 04–05 re-checked against live runs
      after the corpus grew to 99 circuits, and `docs/05` put under
      `verify_figures.py` so it cannot go stale unwatched again.
- [ ] Phase 0 above.
- [ ] `decode_marker_row.py puzzle/puzzle.gds` — the Morse egg, for the form.
      Takes a GDS path, not a target name.

## Phase 1 — get the answer (23–25 Aug, hopefully one day)

When stage 6 returns a trace, **before believing any of it**:

```bash
python tools/sim/replay.py puzzle --solution out/puzzle/solution_post_reset.json
python tools/stage7_output.py puzzle --solution out/puzzle/solution_post_reset.json --extend 64
```

Then raise `--extend` until the tail goes idle — **the trimmed span must end
before the last simulated cycle**, or you are reading a prefix. Run it a second
time with `--after zeros`. If the two agree the stream does not depend on what
happens after the trace; if they disagree, that disagreement goes in the
writeup.

### If stage 6 does not give you what you want

| Symptom | What it means | What to do |
|---|---|---|
| exits 1, "looked to depth N" | the answer is deeper | `--start N --depth 160`, resume rather than restart |
| running for hours | a signal, not a hang | in another terminal, bound it: `--depth` small, and see what the scale costs |
| it refuses | one of the three modelled refusals | `docs/problems.md` 50, and `CLAUDE.md`'s stage 6 cycle model |
| a trace, but **replay fails** | **not a solution** — a modelling error in `graph.json` | do not believe the trace. Find the cause first |

The last row is the rule the whole pipeline is built on. A solver result is a
claim about the model, not about the circuit.

## Phase 2 — interpretation (25–29 Aug, author only)

This is the real work and the part no tool does. Seven questions, ordered by
information per hour, each with the command that answers it. Write findings into
a dated notes file as you go; the writeup is assembled from those, not from
memory.

**1. What does the chip say?** The string from Phase 1. It may name the function
outright.

**2. What does winning mean?**
```bash
python tools/stage4_cone.py puzzle
```
The `success` condition as a readable expression over R0's 57 bits. The warm
up's was `a + b == 496`. Look at its shape: a carry chain (addition, comparison),
an XOR tree (checksum, parity), an equality against a constant. **Even if the
whole circuit stays opaque you can usually name this** — and that is exactly what
the 26 August checkpoint below falls back to.

**3. Where does the input go?** `I` is one bit, so input is serial. Follow `I`'s
cone in `graph.json`: which flops does it reach first? That is the input
register. Then ask what consumes it.

**4. Do R0's 72 bits have a structure?**
```bash
python tools/stage4_registers.py puzzle
```
Read `bit_order.method` in `registers.json`: `shift` means a serial register or
accumulator, `ripple` means an adder or counter, `null` means the bits do not
depend on one another at all — and `why` says which. A guessed order would be
worse than none, which is why it refuses rather than inventing one.

**5. Which register feeds which?** The same run prints a **register dependency
graph**, `R0 -> R1` and so on. Input register, then datapath, then output
register is a shape you can often read straight off it.

**6. Use the hint.** *"The circuit is physically arranged to hint at its
functionality, so look closely at the layout!"* — that is the author's own
invitation. `layout.png` is yours to look at, and the same run prints the
**placement clusters** with their bounding boxes. **Blocks that sit together are
one function.** On the warm up, placement locality alone got the right answer
without reading a wire.

**7. Test the candidate cuts.** The same run prints *candidate splits, reported
and not applied* — refinement wants to cut R0 into 23, 22, 8, 4, 4, 4, 2, 2 and
three singletons. Those are **hypotheses, not answers**. Cross-check each against
(4) and (6): does the 23-bit group form a chain? Do its members sit together on
the die? Two yeses make it a real block.

**And cross-check the other way.** The winning input is 121 bits. Is it
structured? ASCII? A number? What the circuit expects tells you what it is. A
mismatch between the trace and your reading is a finding about one of them.

- 26 Aug checkpoint (kept from the old roadmap): if the whole circuit is still
  opaque, narrow to the success condition and describe the rest structurally.
  Question 2 is that fallback, and it is a respectable answer, not a failure.

## Where the lectures fit

Do not read all eight and then start. Interleave:

| When | Lecture | Why |
|---|---|---|
| Phase 0, while stage 6 runs | **07** | needed immediately |
| Phase 1, while waiting | **06** | you cannot read stage 6's output without knowing what it did |
| Before Phase 2 | **03 + 04** | cones, registers, bit order — the vocabulary of interpretation |
| While writing up | **00, 01, 02, 05** | the "approach" section comes from these |

00–02 describe work that is already finished. They matter for the writeup, not
for the interpretation.

## 29–31 Aug — answer and writeup

- [ ] `docs/writeup.md`, the graded artifact, in the author's hand, on the
      form's four fields: approach / tools built / problems hit
      (docs/problems.md is this, curated) / how the answer was recovered.
      House style per docs/references.md §4: numbers in tables beside their
      baselines, dead ends in one sentence each, adverse results printed in
      the same table as favourable ones.
- [ ] Easter-egg field: emblem (= Jane Street logo, measured), Morse row,
      PER ARENAM AD ASTRA, repo sweep.
- [ ] Draft done by 30 Aug; one full read-through on 31 Aug.

## 1–2 Sep — submit

- [ ] Final packet regeneration; verify_blocks stays the one honest red unless
      the author commits a criterion — either way one sentence in the writeup.
- [ ] Submit the form. Publication-consent and country fields decided.
- [ ] Do not wait for the 4th.

## 4 Sep — after close

- [ ] Repository public. Writeup link mailed per the announcement's invitation.
- [x] Lecture 07 (stage 7) — written 23 Aug, after its gates passed, which is
      the standing rule met rather than waived. All eight lectures are in.
- [ ] docs/design-competition-toolchain.md: revisit when the follow-up
      competition's rules are published.

## When to ask the assistant, and when not to

**Ask:** what a carry chain looks like in a netlist, how to tell a shift chain
from a ripple chain, what an SMT2 fragment is saying, a tool erroring, a concept
that will not land. Debugging and general patterns.

**Do not:** paste puzzle files or `out/puzzle/` contents. Interpretation is the
author's side of the split, and half the writeup's value is that the seam
between what the pipeline determined and what needed a person is real. Ask about
the concept; read the data yourself.

## Standing boundaries, unchanged to the end

The pipeline runs on the puzzle by the author's hand only. Interpretation of
what the circuit computes, the winning input's meaning, and the writeup are
the author's. Assistant stays available for concepts, debugging and general
patterns — the same split CLAUDE.md has carried from the start.
