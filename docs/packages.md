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

Final numbers: corpus 97 circuits / 193 netlists, `verify_corpus` 12 rules and
738 uses; `--score` 117/133 beside a null model of 109/133, and 8 of the 24
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

**The matrix.** Exact match is over all 133 netlists; NMI and purity over the
ten whose ground truth has more than one class. The warm up columns are
membership, not sizes.

| Criterion | exact | NMI | purity | warm up | warm up NMI |
|---|---|---|---|---|---|
| control signature *(committed)* | **117** | 0.0014 | 0.5062 | `[16]` wrong | 0.000 |
| colour refinement | 97 | 0.1867 | 0.75 | `[16]` wrong | 0.000 |
| + flow split (DANA) | 91 | 0.3733 | 1.0 | 16 singletons | 0.400 |
| + connected components | 80 | **0.5476** | 0.80 | **`[8, 8]` correct** | **1.000** |
| + components + flow split | 49 | 0.3733 | 1.0 | 16 singletons | 0.400 |
| placement locality | *n/a* | *n/a* | *n/a* | **`[8, 8]` correct** | **1.000** |
| *null: one group* | *109* | *0.0* | *0.5* | `[16]` | 0.000 |
| *null: every flop its own* | *7* | *0.3733* | *1.0* | 16 singletons | 0.400 |
| *null: interleaved, right sizes* | — | — | — | `[8, 8]` **wrong members** | 0.000 |

Four things for the decision, none of them a recommendation:

1. **Exact match and NMI rank the criteria in opposite orders**, and on the ten
   netlists that ask the question the committed criterion scores the one-group
   null model's numbers to three decimal places.
2. **DANA's split pass is not the fix its own paper's sentence predicts.** Run
   to a fixpoint it is the all-singletons degenerate on every shift register.
   It has two properties nothing else here has: it does not split a plain
   register, and on the R0 analogue it is the only criterion that recovers a
   whole register — two of the seven.
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

## Package 5 — QUEUED. Provenance
Tool pinning; an `open_pdks` test; the writeup skeleton; and the decision on
whether `docs/references.md` is committed.

## Out of scope for workers, always
Anything touching `puzzle/puzzle.gds`, `puzzle/example_inputs.vcd`,
`out/puzzle/`; running any tool with target `puzzle`; interpreting what the
puzzle computes; the writeup; the lectures.
