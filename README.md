# gds-teardown

[![gates](https://github.com/umutdinceryananer/gds-teardown/actions/workflows/gates.yml/badge.svg)](https://github.com/umutdinceryananer/gds-teardown/actions/workflows/gates.yml)

**Recovering what a chip computes from a picture of the chip.**

No source code. No netlist. No labels. Just the mask layout — the polygons a
foundry would use to print silicon — and a question: *what does this thing do,
and what do you have to feed it to make it say something?*

This repository is the pipeline that answered that question, built for the
[Jane Street 2026 ASIC reverse-engineering puzzle](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/).

---

## The answer

```
(* TWO STARS *)
```

Fifteen bytes, read one per clock cycle off the chip's 8-bit output bus at
cycles 124–138, after a 121-bit input sequence that nothing in the puzzle tells
you and no human guessed.

And hidden in the layout itself, spelled in Morse code by 36 rectangles on an
unused mask layer:

```
PER ARENAM AD ASTRA        "through sand to the stars"
```

The chip turns out to be a message ROM. Feed it all zeros and it prints
`EMPTY SKY`. All ones gives `BIG BANG`. The sample inputs shipped with the
puzzle give `TRY AGAIN`. Only the recovered sequence gives `(* TWO STARS *)` —
and raises the `success` flag the puzzle asks for.

## What actually happened here

Three sentences for anyone, hardware background or not:

1. **A chip layout is a field of shapes with no names on them.** This one
   holds 9,875 cell placements. 1,618 of them are standard cells the pipeline
   recognises, and 728 of *those* are logic gates — the rest are filler, taps
   and decoupling, structure rather than computation. Nothing in the file says
   which is which, or where any wire goes.
2. **Seven programs turn those polygons back into a circuit** — recognising
   gates by their geometric fingerprints, tracing the metal wiring into a
   netlist, and working out what each piece does.
3. **Then a solver plays the circuit backwards.** Given "make this output go
   high", it computes the 121 input bits that do it — and a simulator replays
   them to read the answer off the output pins.

The interesting part is not that it worked. It is **how hard the repository
works to prove it worked**, which is what the rest of this page is about.

## The pipeline

| Stage | What it does | In → out |
|---|---|---|
| 1 | Recognise every standard cell by geometric fingerprint | GDS → `instances.json` |
| 2 | Trace the routing into a netlist, with a second extractor checking the first | GDS → `netlist.v` |
| 3 | Annotate the netlist into a graph: clocks, resets, logic cones, flop roles | netlist → `graph.json` |
| 4 | Group flip-flops into registers, order their bits, compose the success condition | graph → `registers.json` |
| 5 | Synthesise 99 circuits whose answers are known, to *score* stage 4 rather than trust it | → `out/synth/` |
| 6 | Bounded model checking: solve for the input sequence that raises `success` | graph → `solution.json` |
| 7 | Replay that trace in a real simulator and read the output bus, byte by byte | → `output.json` |

Each stage is documented in [`docs/`](docs/), numbered to match.

### The numbers on the target

| | |
|---|---|
| GDS placements read | 9,875 |
| Standard cells recovered | 1,618 — of which 728 logic, 890 physical-only |
| Flip-flops | 92 |
| Input sequence solved for | 121 serial bits, BMC depth 124 |
| Start states the trace is proven over | all 2^92, in 13 solver calls over 193.59 s |
| Replay through the independent simulator | 0 mismatches, 0 unknown |
| Bytes recovered | 15, at cycles 124–138 |

## Why you should not believe any of that

Because a reverse-engineering pipeline that is subtly wrong produces output that
looks exactly like output that is right. Every safeguard below exists because
something got past its absence — the full register is
[`docs/problems.md`](docs/problems.md), **57 entries**, each with symptom, root
cause, and whether the fix is understood or merely worked around.

- **A passing test that was never able to fail is not evidence.** Every gate is
  demonstrated against a deliberately broken input at least once. Most carry a
  `--selftest` that plants corruptions and counts how many were caught.
- **A corruption that was never able to corrupt is not a demonstration.** The
  other half of the same rule — three planted defects had to be moved off the
  warm-up target, because it was too simple for them to disturb anything.
- **A score a trivial implementation also achieves is not evidence.** Null
  models are printed beside every score, in the same run.
- **A solver result is a claim about the model, not about the circuit.** Stage
  6's answer is replayed through stage 2's netlist under the chip vendor's own
  gate models — a path sharing no code and no file with the solver. Demonstrated
  by corrupting one gate definition: the solver still said pass, the replay
  caught it.
- **Independent derivation over re-reading.** Connectivity has two extractors.
  Annotations are derived forwards and backwards. The clustering metrics are
  recomputed by an implementation sharing no code. The decoded output is read
  back by a second, separate parser.

Ten of those gates, plus a check that stage 1 reproduces its committed artifact
byte for byte, run in CI on every push — on Python 3.12, with no toolchain
installed beyond two pip wheels. The badge above is that subset, and the
workflow file says plainly why it is a subset: 14 gates need Docker, one needs a
corpus that takes forty minutes of Yosys to build, and one is red on purpose.

`tools/review_packet.py` runs the lot — **41 rows: 40 gates and one report** —
and writes a reviewable evidence file with every gate's status, runtime and full
output, stamped with the commit it was measured at. It refuses to write at all
if it cannot substantiate its own tables.

**One gate is red on purpose.** `verify_blocks.py` scores stage 4's register
grouping against the true answer, and the committed criterion gets it wrong. Six
criteria were measured instead of one being chosen, they disagree, and the
disagreement is reported rather than hidden. Solving the puzzle did not resolve
it, and the repository does not pretend otherwise.

### What the puzzle run itself cost

Stage 6's first contact with the real target found four defects the warm-up
could never have exposed — including one where a plain dictionary assignment
made driver conflicts invisible and the solver confidently reported
*"pass, a trace was found"* **for a design that does not exist.** That is
problem 55, and it is exactly why the replay check exists.

### It survived its own machine being sold

Mid-project the development Mac was sold. Everything was committed first, then
the whole pipeline was rebuilt on Linux from a pre-written runbook
([`docs/resurrection-runbook.md`](docs/resurrection-runbook.md)). Every
extraction artifact regenerated **byte-identical** across macOS/Python 3.14 and
Linux/Python 3.12, except three cases that are explained rather than excused.

## The easter eggs

The puzzle authors hid things, and the repository went looking with 15
deterministic decoders, every one paired with a negative control:

- **The Morse row.** 36 rectangles on mask layer 200/0, two widths in a 1:3
  ratio with 1/3/7-unit gaps — the timing convention of International Morse.
  16 of 16 valid tokens: `PER ARENAM AD ASTRA`.
- **The emblem.** 1,366 tiny metal squares on a 57 × 57 grid, identical in both
  layouts, connected to nothing. Measured against the Jane Street GitHub
  avatar: **91.29% pixel agreement.** The tempting "it's a QR code" reading was
  killed by measurement, not by opinion.
- **The message ROM**, found by simulation rather than by staring: `EMPTY SKY`,
  `BIG BANG`, `TRY AGAIN`, `(* TWO STARS *)`.

Most of what the decoders swept — text acrostics, bit-grids, mask labels, PNG
chunks, trailing container bytes — returned **nothing**, and that null result is
archived too. A search that only records its hits is not a search.

## Repository layout

```
tools/          the seven stages and every gate — 60 Python files, 21,891 lines
  common/         GDS, LEF, liberty and boolean-expression readers
  sim/            one simulation driver and one cycle model, shared
docs/           one document per stage (00–07), plus:
  problems.md     57 defects: symptom, root cause, fix status
  references.md   primary sources, both published hints, the emblem measurement
  resurrection-runbook.md   rebuilding the toolchain on a different OS
  lectures/       00–09, in Turkish: the whole project taught from scratch
                  to a reader with no hardware background
out/            artifacts the pipeline produced, kept as evidence
pdk/            the SkyWater sky130 cell library, pinned
puzzle/         the puzzle's published material
docker/         Icarus Verilog and Yosys images
```

### Running it

**Python 3.12 or later**, and Docker. The entire Python dependency surface is
two pinned packages, both shipping wheels for Windows, Linux and macOS:

```
gdstk==1.0.1
klayout==0.30.10
```

Everything heavier — Yosys, Icarus Verilog, z3 — lives in the two Docker images,
so the host needs no EDA toolchain at all. One optional tool,
`fetch_open_pdks.py`, needs 3.14 for the stdlib zstd decoder and says so if it
does not get it; nothing else in the pipeline does.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
python tools/fetch_pdk.py

DOCKER_BUILDKIT=0 docker build --target sim -t gds-teardown-sim -f docker/Dockerfile docker/
DOCKER_BUILDKIT=0 docker build --target eda -t gds-teardown-eda -f docker/Dockerfile docker/

python tools/stage1_cells.py puzzle       # and so on, through stage 7
python tools/review_packet.py             # run every gate, write the evidence
```

The full command list, with what each gate checks, is in
[`CLAUDE.md`](CLAUDE.md). Three targets share one interface: `warmup` (a worked
example shipped with its own source, so the pipeline can be calibrated against a
known answer), `synth` (99 generated circuits that write their own answer keys),
and `puzzle`. **No stage ran on the puzzle before it passed on a target whose
answer was already known.**

### Reproducing the headline

The recovered string and the trace that produced it are committed under
`out/puzzle/`, so the claim on this page can be read without running anything.
Re-deriving it is a different matter: the intermediate netlist and graph for the
puzzle are not committed, so a fresh clone runs stages 1 to 3 first. The evidence
packet is not committed either — `python tools/review_packet.py` regenerates it,
and the copy it writes is stamped with the commit it was measured at.

## Honest limits

- **The register partition on the target is unresolved.** 72 of the 92
  flip-flops sit under one control signature. Six criteria disagree about how to
  cut them, exact-match and information-theoretic scores rank those criteria in
  *opposite* orders, and adding two circuits to the corpus reordered the ranking
  again. Reported as a residue, not smoothed into an answer.
- **Functional coverage was never measured.** The corpus can only name a block
  if some circuit in it computes the same function, and no equivalence check was
  run across the target. What *was* measured is a one-directional bound.
- **The corpus is an answer key its own author wrote**, and its catalogue grew
  in response to measurements against the target — which weakens held-out scores
  in a known direction. The one circuit the author did not write found a gap the
  written ones had missed.
- **The evidence packet is regenerated, not committed at every commit.** Its
  stamp names the commit it was measured at; when that is behind HEAD it says
  so, rather than implying freshness.

## On model assistance

This was built with an AI assistant, and the repository says so in three places
rather than leaving it to be discovered: most of its commits carry a
`Co-Authored-By` trailer, [`CLAUDE.md`](CLAUDE.md) sits in the root as the
standing instructions, and this section exists.

The puzzle's own rule permits it for code and forbids it for two things — the
puzzle files and the writeup. **The working split used here was stricter than
the rule.** The assistant built the stages and the gates and validated them
against `warmup` and the synthetic corpus, whose answers were already known. It
never opened `puzzle.gds` or the sample waveform, and every run against the
`puzzle` target was the author's. The split is written out as a table in
`CLAUDE.md` and was held to for the project's whole length.

**One rule mattered more than the split:** no language model runs *inside* the
pipeline. Every stage is a deterministic program — geometry, graph algorithms,
structural matching, SAT and SMT. A detector is an algorithm, never a prompt.
That is why the gates mean anything: they check programs, and programs can be
re-run by anyone.

## Lectures

[`docs/lectures/`](docs/lectures/) teaches the whole project from first
principles, in **Turkish** — ten lessons, written after each stage's gates
passed rather than before, so they describe verified facts and not intentions.

## Licence and third-party content

The work in `tools/`, `docs/`, `docker/` and the repository root is MIT
licensed — see [`LICENSE`](LICENSE). Two directories carry other people's work
under their own terms: `pdk/` is the SkyWater sky130 standard cell library
(Apache 2.0), and `puzzle/` is Jane Street's published puzzle material. Both are
vendored so this repository stays readable independently of its upstreams.

## Acknowledgements

Jane Street, for a puzzle whose layout is arranged to hint at its own function —
and who hid *per arenam ad astra* in the sand, where somebody would have to
decode it to find it. The SkyWater sky130 open PDK. KLayout, gdstk, Yosys,
Icarus Verilog and z3.
