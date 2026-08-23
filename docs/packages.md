# Work plan, supervisor's package map

Tasks arrive as supervisor-written prompts. This file is the shared map so
every session names the work the same way. Update a package's status line in
the same commit that completes it. If a task prompt and this file disagree,
say so before working.

## Package 1 — DONE. Gate repair
`--score`/`--compare` given exit statuses they can fail with, against recorded
expectations. `verify_corpus` fails on an incomplete corpus; selftest grown to
15 corruptions covering all 12 rules. `review_packet` substantiates its own
tables (defect register, READERS, gate/report kinds) and refuses to write on a
failed claim. Commits 535d1a1, fab83b0, 87e5d76, c377548, b9a62d5.

## Package 2 — DONE. Stage 6 machinery, warmup only
`verify_equiv.py` proves the recovered netlist sequentially equivalent to
`01_netlist.v` (the project's first miter). `stage6_invert.py` solves for an
input trace out of `graph.json`, robust across start states, honest about
depth on a negative. `sim/replay.py` replays any trace through stage 2's
netlist before it is believed — demonstrated catching a corrupted-model trace.
The puzzle run is the author's. Commits bc8f15c, 59b2798, 06ddfe1.

## Package 3 — DONE. Annotation blind spots, corpus additions
`stage3_crosscheck.compare()` extended to the seven field groups it never read
(hold, reset/set level, cell and kind, cone root values, constant nets, net
names, transparent types, carried cell_functions); 17 corruptions, all caught,
subject checked to agree before it is broken. Stage 3's hold search identifies a
mux by its liberty function rather than its name, and `mux2i_witness` is the
pre-mapped circuit that makes the old rule visibly wrong and the new one
visibly right. `verify_annotations.py` holds the warm up's annotations to
`00_source.v`; `verify_cone.py` proves the composed cone equal to
`a + b == 496`, sharing no code with anything. Corpus grew to 97 circuits / 193
netlists: the two undeclared enables, `warmup_twin`, and the warm up's own RTL.
Commits e9560c0, 56ea75f, 897903b, b7e983c, 4602a40, fe96f15, 53deadb.

Final numbers **as Package 3 left them**; Package 6 added the `streamer`
family and every one of them moved, which is recorded there. Corpus 97 circuits
/ 193 netlists, `verify_corpus` 12 rules and 738 uses; `--score` 117/133 beside a null model of 109/133, and 8 of the 24
netlists that declare more than one register; `--compare` 117 / 97 / 80. Holds
**declared 46, found structurally 12** -- the other 34 are accounted for by name
in `ENABLE_HIDDEN_BY`, five mechanisms, which is the corpus admitting how many
the structural search misses rather than the search improving.

Two findings came out of it rather than in: problem 45, where one design mapped
two ways gives three different register partitions because a missed hold
*invents* a boundary; and problem 44, where the only corpus entry whose RTL
this author did not write found a gap 96 written ones could not.

Carried forward, deliberately not done:
- The cross-check's selftest still runs only on warmup. The corpus has no
  `netlist.json` -- it is synthesised, never laid out -- so reading it would
  need a second Verilog netlist reader with alias resolution, a new unchecked
  surface inside the tool whose value is independence. The four fields warmup
  can only disagree about are named in the selftest's own output.

## Package 4 — DONE. The register-partition decision matrix
`docs/references.md` §3 and §6 distil the published prior art this package
implements: DANA (TCHES 2020) for register grouping and scoring, WordRev for
bit order, and the announcement's two verbatim hints. **The goal is to measure
the options, not to pick a winner.** The committed criterion stays the control
signature and `verify_blocks` keeps scoring against it -- and keeps failing --
until the author decides otherwise. The deliverable is the matrix that decision
is made from.

- **A.** NMI and purity beside exact match in `--score` and `--compare`, with a
  stated convention for the 109 netlists whose ground truth is a single class
  and whose NMI is therefore 0/0, and a hand-computed table the implementation
  has to reproduce.
- **B.** DANA's successor/predecessor split as a pass over two seeds, measured
  on the corpus, on `verify_blocks`, and on the `scale_datapath` family, with
  the plain-register non-split demonstrated.
- **C.** Placement locality, warmup only and labelled as n=1, because the
  synthetic corpus is never placed and cannot score it.
- **D.** Bit order within a register, cross-checked against the arithmetic
  weights `verify_cone.py` derives independently.
- **E.** `stage6_invert.py --post-reset`, scoping the initial state to what the
  announcement's `rst_n` hint says the author will actually do.
- **F.** The authority recorded: the AI rule's three sentences and the two
  hints, each with its source.

**The matrix.** Exact match is over all 137 netlists; NMI and purity over the
fourteen whose ground truth has more than one class. The warm up columns are
membership, not sizes.

| Criterion | exact | NMI | purity | warm up | warm up NMI |
|---|---|---|---|---|---|
| control signature *(committed)* | **117** | 0.001 | 0.5525 | `[16]` wrong | 0.000 |
| colour refinement | 101 | 0.419 | 0.8214 | `[16]` wrong | 0.000 |
| + flow split (DANA) | 91 | **0.5019** | 1.0 | 16 singletons | 0.400 |
| + connected components | 80 | 0.3911 | 0.7623 | **`[8, 8]` correct** | **1.000** |
| + components + flow split | 49 | 0.5019 | 1.0 | 16 singletons | 0.400 |
| placement locality | *n/a* | *n/a* | *n/a* | **`[8, 8]` correct** | **1.000** |
| *null: one group* | *109* | *0.0* | *0.5481* | `[16]` | 0.000 |
| *null: every flop its own* | *7* | *0.3879* | *1.0* | 16 singletons | 0.400 |
| *null: interleaved, right sizes* | — | — | — | `[8, 8]` **wrong members** | 0.000 |

**Updated by Package 6**, which added two circuits for stage 7 to be gated
against and moved every figure in this table. What did *not* move: the shape of
the disagreement, and which criterion is committed. What did: the NMI column's
ordering. See Package 6 below and `docs/04-detectors.md`.

Four things for the decision, none of them a recommendation:

1. **Exact match and NMI rank the criteria in opposite orders**, and on the
   fourteen netlists that ask the question the committed criterion scores the
   one-group null model's NMI to three decimal places. **Which criterion tops
   the NMI column is not stable**: four netlists added in Package 6 moved it
   from connected components to the flow split, which is the strongest argument
   in this table for reporting a residue rather than committing a criterion.
2. **DANA's split pass is not the fix its own paper's sentence predicts.** Run
   to a fixpoint it is the all-singletons degenerate on every shift register.
   It has two properties nothing else here has: it does not split a plain
   register, and on the R0 analogue it recovers **two** of the seven declared
   registers whole, the most of any criterion — against one for connected
   components and none for the control signature or refinement.
3. **Placement locality gets the warm up right, membership included, without
   reading a wire.** The corpus cannot score it: nothing in `out/synth/` was
   ever placed, so **n = 1**, and its second data point is the puzzle read by
   the author.
4. **`verify_blocks` still fails, scored against the control signature.** That
   is deliberate. Committing a criterion is the author's decision; the rows
   above are what it is made from.

Commits 30b882e, d107733, 8e89b78, 1d38e99, 1276c7e, b1541c9, and this one.

Two findings came out of it rather than in. Problem 46: the block gate compared
sizes, so `[8, 8]` with the wrong eight in each group passed, and a deliberately
interleaved null model is now a permanent row so that column can never be
silent. Problem 47: the cone's weight solve stopped at its first hit and printed
one assignment as a derivation, when 24 of 40320 are equivalent — found because
two independent derivations of the bit order disagreed.

## Package 5 — DONE, except the two items that are the author's
Tool pinning; an `open_pdks` test; determinism; the packet's environment
honesty; and the three homed audits. **The writeup and the decision on whether
`docs/references.md` is committed are the author's and were left alone.**

- **DONE. Tool pinning.** The container base is pinned by digest in
  `docker/Dockerfile`. The apt packages are **recorded, not pinned** — each
  image writes its own versions into a baked manifest at build time and
  `tools/verify_toolchain.py` fails on drift against
  `tools/TOOL_VERSIONS.recorded`. Demonstrated by editing the recording:
  `DRIFT line 10 ... exit 1`. `verify_toolchain.py <target>` also stamps
  `out/<target>/TOOL_VERSIONS`. The gap that remains: the container tools do
  not stamp their own artifacts, which would mean editing five files no
  package has admitted.
- **DONE. The `open_pdks` test.** `tools/fetch_open_pdks.py` streams a
  prebuilt `sky130A` from the `ciel` releases, pinned to open_pdks
  `8afc8346`, and keeps 4.19 MB of the 64 MB it reads;
  `tools/compare_libraries.py` diffs it against the upstream library.
  **9 of 437 shared cells differ, and all three cell types the puzzle falls
  back on are among them, on exactly the layers `docs/01` already records.**
  `stage1_cells.py --library` answers 230/230 under both libraries on the warm
  up. The author's one-line puzzle command and what each outcome means are in
  `docs/01-cell-recognition.md`.
- **DONE. Determinism.** `tools/verify_determinism.py` runs three cases under
  `PYTHONHASHSEED=1` and `424242` and compares bytes; `--selftest` plants two
  nondeterminisms and catches both.

Added by Package 4, both out of its scope:

- **DONE. `docs/problems.md` 49.** `review_packet.py` establishes the runtime
  and both images before any container row runs, and a row that cannot run is
  **blocked** — neither pass nor FAIL, counted separately, stated at the top.
  The container flag is re-derived from each tool's source, in one direction,
  with `NATIVE_MODES` declaring the container-free modes of container tools.
  Demonstrated healthy (10 rows would run) and with docker off PATH (10
  blocked, 1 FAIL, and the FAIL is the genuine one).
- **Three audits that are not yet programs the repository runs.** Package 4's
  adversarial review lost five of its six lenses to a session limit; all five
  were then reconstructed by hand, and three of them as scripts. **Those
  scripts live in a scratch directory and will be lost**, which is precisely
  *a measurement that is not a program is a measurement that happened once*.
  They belong in `tools/`, and what each checks is recorded here so it can be
  rebuilt rather than re-derived:

  | Audit | What it establishes |
  |---|---|
  | the metrics, a second way | NMI recomputed as `H(C) + H(T) − H(C,T)` rather than as a sum over joint probabilities, and purity from a different data structure. Agrees on all 7 hand rows, on **4000 random partitions**, and on four invariants — `NMI(T,T)=1`, symmetry, range `[0,1]`, purity monotone under refinement. Also checks the degenerates by definition: one cluster exactly 0.0, all singletons exactly 1.0 purity and 0.4 NMI |
  | the documented figures | all **35** numeric claims in Package 4's diff, each against the run that is supposed to produce it, plus the reverse direction — a figure quoted in a doc that appears in no run |
  | spatial and bit order | single linkage recomputed by brute-force transitive closure at all 12 thresholds; the clustering identical under 100 shuffles of the flop and placement dicts; every consecutive pair of every chain verified against the netlist as a real `D <- Q` link and the only one; the unplaced branch exercised by removing a placement; and ripple depth shown to take the **longest** path by a chain-with-skip-edge, which discriminates it from shortest — a diamond does not |

  **DONE.** They are `tools/verify_metrics.py`, `tools/verify_grouping.py`
  (which takes a target) and `tools/verify_figures.py`. Each is a gate with a
  `--selftest` that plants wrong implementations and confirms the audit
  notices — 3, 4 and 4 corruptions caught, subject checked to agree first — and
  all six rows are in the packet. `verify_figures.py` matches document table
  rows **by value, not by name**, so the two documents may name a criterion
  three different ways and write `0.80` where the tool prints `0.8`; it states
  its own limit, which is that the registry half does not follow a document
  that gains a figure.

## Package 6 — DONE. Stage 7, output extraction
The last unbuilt stage of `docs/solver-pipeline.md`: turning a winning input
sequence into the string the chip emits. The submission's answer field asks for
*"the string value you recovered from the chip"*, and the announcement says the
output generator is *"safe to ignore during your initial reverse-engineering
steps, but you'll need to simulate it to get your final answer."* So stage 7 is
not another solver. It is the simulation stage 6's replay already runs, asked a
different question.

- **DONE. One driver, not two.** `tools/sim/harness.py` holds the cycle model
  and the Icarus invocation; `sim/replay.py` and `stage7_output.py` both call
  it, and `replay.py` keeps its own testbench because asserting a property is a
  different job from sampling a bus. Stage 2's `run.py` is left alone — its
  testbenches are hand written per target — and contributes `model_files`.
- **DONE. `tools/stage7_output.py`.** Replays a solution through **stage 2's**
  netlist, keeps clocking for `--extend N` cycles, and reports what every output
  carried per cycle: the table, the raw bytes, and the printable-ASCII rendering
  with everything else escaped. Writes `out/<target>/output.json`. **Both knobs
  are printed with every result, defaults included**, because neither can be
  derived from anything this repository has read. Measured on the warm up, the
  same trace extended four cycles three ways gives three different answers:
  `hold-last` leaves `S` at `1 1 1 1`, `zeros` drops `rst_n` and clears it to
  `0 0 0 0`, and `en=1,A=1` gives `1 0 0 0`.
- **DONE. The ground truth.** The corpus gained a `streamer` family: two
  circuits that emit a declared ASCII string one byte per cycle after a one
  cycle trigger, then idle. `HELLO WORLD` at 11 bytes and `OK\a 42\n` at 7,
  the second carrying `0x07` and `0x0a` so the escape path is exercised. Their
  flop counts are **derived from the string before synthesis** — every ASCII
  byte has bit 7 clear, so `opt` removes that flop and `O[7]` arrives from a
  `conb_1` — and stage 3 finds exactly what was declared, `[7, 4]` and `[7, 3]`.
  Corpus: **99 circuits / 197 netlists**, `verify_corpus` 12 rules and 762 uses.
- **DONE. The gate.** `tools/verify_output.py` drives the declared stimulus,
  decodes, and compares **bytes** against the answer key for every mapping of
  every streamer — not text against text, which would compare the decoder with
  itself. The rendering is checked by **round trip** through `unescape`, a
  second implementation sharing no code with `stage7_output.escape`. Three
  corruptions in `--selftest`: a byte wrong in the stream, a byte wrong in the
  answer key, and a raw control byte left unescaped. 3 of 3 caught.
- **DONE. `docs/07-output.md`.** The author's one-liner, what to look at first
  and in what order, and what stage 7 does not do — it never interprets the
  string.

**What the corpus change moved, and the finding in it.** The two streamers
declare two registers each, so four of the fourteen netlists whose ground truth
has more than one class are now theirs. Every figure in Package 4's matrix is
re-recorded here, and one of them is a result rather than a bookkeeping entry:

> On a streamer, **colour refinement is exactly right and connected components
> answers one group.** The index register feeds the ROM that feeds the output
> register, so the two are genuinely connected. That is the mirror of the warm
> up, where components is right and refinement is wrong.

Connected components went from 0.5476 NMI over ten netlists to 0.3911 over
fourteen, the flow split took the top of the column at 0.5019, and refinement
moved from third to second on exact match. Nothing was tuned; the ordering moved
by more than its own precision when four netlists arrived. **The ranking the
author was going to decide from is less stable than one reading of it suggested,
and that is worth more than the ranking was.**

Two smaller findings came out of it rather than in. **Problem 52**: `replay.py`
declared every output port as a scalar wire, invisible on a warm up whose only
output is one bit, and it would have left seven eighths of the puzzle's `O[7:0]`
floating at the last step of the pipeline. It surfaced because writing a second
consumer of the same simulation forced the widths to be read from the netlist.
**Problem 53**: moving the `docker run` into the harness made
`review_packet.uses_container` — which decides whether a row is blocked or run —
go stale inside one commit, and `verify()` refused to write the packet, which is
what it is for.

Edited outside the package's stated file list, and named here rather than
quietly: `docs/04-detectors.md` and `tools/verify_figures.py`. Both carry
recorded corpus figures — `verify_figures` matches `docs/04`'s criteria table
against the runs **by value** — so a corpus change that left them alone would
have failed the gate rather than passed it.

## Out of scope for workers, always
Anything touching `puzzle/puzzle.gds`, `puzzle/example_inputs.vcd`,
`out/puzzle/`; running any tool with target `puzzle`; interpreting what the
puzzle computes; the writeup; the lectures.
