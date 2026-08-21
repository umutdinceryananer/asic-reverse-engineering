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

## Package 3 — PART DONE. Annotation blind spots, corpus additions
Done: `stage3_crosscheck.compare()` extended to the seven field groups it never
read (hold, reset/set level, cell and kind, cone root values, constant nets, net
names, transparent types, carried cell_functions), 17 corruptions, all caught,
subject checked to agree before it is broken. Stage 3's hold search no longer
tests the cell's name: `mux2i` is an inverting mux and the rule is now the
liberty function's cofactor, which accepts exactly the four `mux2_*` outputs in
the library and rejects the three `mux2i_*`. `verify_annotations.py` holds the
warm up's annotations to `00_source.v`. `verify_cone.py` proves the composed
cone equivalent to `a + b == 496`, sharing no code with anything.
Commits e9560c0, 56ea75f.

NOT DONE, and carried forward:
- Task 1's corpus subjects for the selftest. The corpus has no `netlist.json`
  -- it is synthesised, never laid out -- so this pass cannot read it without a
  second Verilog netlist reader with alias resolution, which is a new unchecked
  surface inside the one tool whose value is independence. The two fields the
  warm up cannot confirm positively (set level, constant nets) are named in the
  selftest's own output instead of being implied.
- Task 4 in full: warmup_twin, `00_source.v` as a corpus entry, the mux2i
  witness netlist, and the two undeclared enables. Nothing in the corpus has
  changed, so no recording moved and none needed to.
- Task 5's `docs/06` sentence is done; the rest of Task 5 follows Task 4.

## Package 3 (original scope) — Annotation blind spots, corpus additions
- Extend `stage3_crosscheck.compare()` to the fields it never reads (enable/
  hold, reset/set levels, cone_roots values, constant_nets, net_names), one
  selftest corruption per new field.
- Warmup-RTL annotation check from `00_source.v` (16 holds on `en`, async
  `rst_n` low, one clock) — the hold annotation's first external check.
- Commit the cone validation as `tools/verify_cone.py` (logic exists from
  review), wire into the packet.
- Corpus: a warmup-shaped circuit (two identical registers sharing every
  control), `00_source.v` as a corpus entry, declare the missing enables
  (accumulator, composed_counter_compare), mux2i polarity fix in stage 3.
- Carry-along: one sentence in docs/06 on the miter's common-mode boundary
  (both sides read cells through celllib, so it proves structure, not cell
  semantics — verify_functions and replay cover those).
- RULE: any corpus change re-records RECORDED/RECORDED_CRITERIA in
  stage4_registers.py and the verify_corpus numbers IN THE SAME COMMIT, with
  the why in the commit message.

## Package 4 — PENDING, low priority
Stage-1 fallback-tier experiment under `compare_def` (force mux2_1 through
tier 2 on warmup); stale doc numbers not already fixed in passing.

## Out of scope for workers, always
Anything touching `puzzle/puzzle.gds`, `puzzle/example_inputs.vcd`,
`out/puzzle/`; running any tool with target `puzzle`; interpreting what the
puzzle computes; the writeup; the lectures.
