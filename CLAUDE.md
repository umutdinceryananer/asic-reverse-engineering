# gds-teardown

Recovering an ASIC's function from its layout, for the Jane Street 2026 puzzle.
**This was a competition submission.** The deadline, 4 September 2026, has
passed and the repository is public.

## Read these first

- `docs/solver-pipeline.md` — what gets built. The build spec, seven stages.
- `docs/jane-street-asic-roadmap.md` — when. Schedule, phase budgets, gates.
- `docs/packages.md` — who, and in what order. The supervisor's package map;
  a package's status line moves in the commit that completes it.

The deliverable is the pipeline, not the answer. The answer is its first test
case.

## Where the work stands

| Stage | State |
|---|---|
| 1, cell recognition | **done**, gated |
| 2, connectivity | **done** to spec, all five gates pass |
| 3, normalisation | **done**, round trip passes on both targets |
| 4, detectors | steps 1 and 2 built, **register grouping fails the warm up's own hierarchy**. Naming not started |
| 5, synthetic corpus | **done**, 99 circuits / 197 netlists, gated by `verify_corpus.py` |
| 6, inversion | **done**: BMC out of `graph.json`, trace replayed in simulation. Gated on `warmup` at depth 8; the puzzle solved at depth 124, 121 serial bits, proven over every start state |
| 7, output extraction | **done**: the trace replayed, the output bus read, the bytes decoded. Gated against two corpus circuits whose string is declared before the run; on the puzzle it read `(* TWO STARS *)` at cycles 124-138 |

Lessons written: `docs/lectures/00` through `09`, one per stage plus two for
the machine move and the puzzle run itself. Lessons are written after the
gates, never before, so each describes verified facts rather than intentions.

## Rules that bind this repository

**No language model runs inside the pipeline.** Every stage is a deterministic
program: layout and EDA tools, graph algorithms, structural matching,
equivalence checking, SAT and SMT. Model assistance writes the pipeline, it does
not run in it. A detector must be an algorithm, never a prompt.

**The puzzle rules restrict what an assistant may do with the puzzle files.**
The rule has three sentences and this file used to quote one of them. All three,
from the [blog announcement](https://blog.janestreet.com/can-you-reverse-engineer-an-asic/),
5 August 2026:

> "Please don't feed the puzzle files directly into an AI tool, nor use it to
> generate your writeups. Feel free to use AI for writing any scripts or code
> you may need as part of solving the puzzle, though! **It's also fair game to
> use AI to work through the warm-up puzzle, see below.**"

The third sentence is explicit written authority for what this project does:
every validation here runs on `warmup` or on `synth`, and the assistant never
opens `puzzle/puzzle.gds` or `puzzle/example_inputs.vcd`. The working split
below is *stricter* than the published rule, which is a choice and is
defensible; the submission is stronger citing the rule than reconstructing it.

**Two hints, quoted verbatim, both verified against the primary source.** There
are exactly three official documents — the announcement above, the repository
README, and the submission form — and no hint, FAQ or erratum has appeared since
launch. Planning against a hint that will not come costs real time.

> "The circuit is physically arranged to hint at its functionality, so look
> closely at the layout!"

Authorial sanction for a placement-locality criterion in stage 4, which is the
failing gate. Implemented as `spatial_groups`; on the warm up it is the only
criterion that gets the answer right without reading a wire, and the synthetic
corpus cannot score it at all because nothing in it was ever placed.

> "Don't forget to toggle `rst_n` before each input attempt."

A statement about stage 6. Robustness across *every* start state was derived
from a warm up that needs no reset; on the puzzle it solves for 2^92 starting
states where the hint describes 2^4. `stage6_invert.py --post-reset` asks the
smaller question, and `docs/06-inversion.md` says which mode the puzzle run
should use.

`docs/references.md` §6 holds the three documents and what else was read out of
them. The working split:

| Assistant does | Author does |
|---|---|
| Build every stage, detector and solver wrapper | Run the pipeline on `puzzle` |
| Validate against `warmup` and `synth`, whose answers are known | Interpret the block partition |
| Explain concepts, debug, refactor | Identify what the circuit computes |
| | Derive the winning input |
| | Write `docs/writeup.md` |

This is also the spec's own structure: the seam between what the pipeline
determined and what needed a person is the observation the writeup is about.

**The repository was private until 4 September 2026**, the competition
deadline, so that a public copy could not spoil the puzzle for anyone still
working on it. That date has passed and it is public.

## Environment

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt           # Linux, macOS
python tools/fetch_pdk.py        # ~10 MB into pdk/, pinned to one commit
python tools/fetch_open_pdks.py  # the same cells as open_pdks builds them,
                                 # into pdk/open_pdks_sky130A/. 64 MB read,
                                 # 4.19 MB kept. Never touches the above.
git submodule update --init      # upstream puzzle files into puzzle/
```

`gdstk` and `klayout` are pip wheels on all three platforms. Icarus and Yosys
are not, so they live in a container:

```bash
DOCKER_BUILDKIT=0 docker build --target sim -t gds-teardown-sim -f docker/Dockerfile docker/
DOCKER_BUILDKIT=0 docker build --target eda -t gds-teardown-eda -f docker/Dockerfile docker/
```

`sim` carries only Icarus and is all stage 2 needs; `eda` adds Yosys and z3 for
stage 3 onward. **`DOCKER_BUILDKIT=0` is required on this machine**: under
BuildKit `apt-get` cannot reach the network, while the identical command works
under `docker run`. Not diagnosed, only worked around.

## Running

Every stage takes a target, never a hard coded path.

```bash
python tools/verify_toolchain.py warmup   # gate: the images' toolchain against
                                          # tools/TOOL_VERSIONS.recorded, and
                                          # stamps out/warmup/TOOL_VERSIONS
python tools/compare_libraries.py         # gate: the two cell libraries, cell
python tools/compare_libraries.py --selftest   # by cell, on the nm grid
python tools/verify_determinism.py        # gate: three cases under two hash
python tools/verify_determinism.py --selftest  # seeds, byte for byte

python tools/stage1_cells.py warmup       # -> out/warmup/instances.json
python tools/stage1_cells.py warmup --library pdk/open_pdks_sky130A
python tools/stage2_nets.py  warmup       # -> out/warmup/netlist.{json,v}
python tools/compare_def.py  warmup       # gate: 230/230 cells, 84/84 nets
python tools/stage2_unionfind.py warmup   # gate: second extractor agrees, 86/86
python tools/sim/run.py      warmup       # gate: 65536 pairs, 0 mismatches
python tools/stack_sensitivity.py warmup  # not a gate: justifies the layer stack

python tools/stage1_cells.py puzzle
python tools/stage2_nets.py  puzzle
python tools/stage2_unionfind.py puzzle   # gate: 725/725, the only check with
                                          # no ground truth behind it
python tools/sim/make_puzzle_stimulus.py  # VCD -> per-cycle tables
python tools/sim/run.py      puzzle       # gate: 312 cycles, 0 mismatches

python tools/stage3_graph.py warmup       # -> out/warmup/graph.{json,v}
python tools/sim/run.py warmup --netlist out/warmup/graph.v   # gate: round trip
python tools/stage3_graph.py puzzle
python tools/sim/run.py puzzle --netlist out/puzzle/graph.v   # gate: round trip
python tools/stage3_crosscheck.py warmup  # gate: annotations derived a second
python tools/stage3_crosscheck.py puzzle  # way, forwards instead of backwards
python tools/stage3_crosscheck.py warmup --selftest
python tools/verify_annotations.py warmup # gate: stage 3's annotations against
                                          # the RTL in 00_source.v
python tools/verify_equiv.py warmup       # gate: the recovered netlist proven
                                          # equal to 01_netlist.v, 153 points

python tools/stage5_corpus.py             # 99 circuits, 197 netlists -> synth/
python tools/stage5_corpus.py --list      # the catalogue, without synthesising
python tools/verify_corpus.py             # gate: 12 rules, 762 uses vs stage 3,
                                          # and fails if any graph is missing
python tools/verify_corpus.py --selftest  # gate: 15 corruptions, and every one
                                          # of the 12 rules tripped by one
python tools/corpus_reach.py puzzle       # not a gate: the size bound on what
                                          # the corpus could ever name

python tools/stage4_registers.py warmup   # -> out/warmup/registers.json
python tools/stage4_registers.py puzzle
python tools/stage4_registers.py --score  # gate: 117/137 exact, and NMI and
                                          # purity, against a recording
python tools/stage4_registers.py --compare  # gate: five criteria, same key
python tools/stage4_registers.py --selftest  # gate: the metrics against seven
                                          # hand computed rows
python tools/verify_metrics.py            # gate: the same metrics against an
python tools/verify_metrics.py --selftest # implementation sharing no code
python tools/verify_grouping.py warmup    # gate: placement clustering and bit
python tools/verify_grouping.py warmup --selftest   # order, against the netlist
python tools/verify_figures.py            # gate: every documented figure against
python tools/verify_figures.py --selftest # the run that produces it, docs/05
                                          # included, document side and all
python tools/verify_blocks.py             # gate: stage 4 against the warm up's
                                          # DEF hierarchy. CURRENTLY FAILING
python tools/stage4_cone.py puzzle        # the success condition, composed
python tools/stage4_cone.py puzzle --list # every cone root by size
python tools/verify_cone.py warmup        # gate: that listing proven equal to
                                          # a + b == 496 over all 65536, and
                                          # stage 4's bit order among the 24
                                          # weight assignments that make it so
python tools/verify_cone.py warmup --registers out/warmup/scrambled.json
python tools/verify_functions.py          # gate: liberty vs the PDK's own
                                          # behavioural models, 850 patterns
python tools/verify_functions.py --selftest  # gate: and which mistakes that
                                          # comparison could actually notice

python tools/stage6_invert.py warmup      # gate: BMC, -> out/warmup/solution.json
python tools/stage6_invert.py warmup --post-reset  # start states as a toggled
                                          # rst_n leaves them: 2^0 here, 2^4 on
                                          # the puzzle instead of 2^92.
                                          # -> out/warmup/solution_post_reset.json
python tools/sim/replay.py warmup --solution out/warmup/solution_post_reset.json
python tools/stage6_invert.py --selftest  # gate: the tie cell and double
                                          # driver checks, on synthetic
                                          # graphs; no container needed
python tools/stage6_invert.py warmup --depth 6   # a bound below the answer:
                                          # exits 1 and says how deep it looked
python tools/sim/replay.py warmup         # gate: that trace back through stage
                                          # 2's netlist in Icarus

python tools/stage7_output.py warmup      # the trace replayed and every output
                                          # read back, -> out/warmup/output.json
python tools/stage7_output.py warmup --extend 6
python tools/stage7_output.py warmup --extend 6 --after zeros
                                          # --after is hold-last | zeros |
                                          # port=value,... and is PRINTED, never
                                          # assumed: the three give three
                                          # different answers past cycle 8
python tools/verify_output.py             # gate: the corpus streamers decoded
                                          # against the strings they declare
python tools/verify_output.py --selftest  # gate: a byte wrong on either side,
                                          # and a control byte left unescaped
```

Targets: `warmup` (full source and DEF as ground truth), `synth` (generated
ground truth, not built yet), `puzzle` (the real run). **No stage runs on
`puzzle` before it passes on a target with ground truth.**

## Verification gates

| Stage | Gate | Status |
|---|---|---|
| 0 | `verify_toolchain.py`: both images' baked manifests against `tools/TOOL_VERSIONS.recorded`; base pinned by digest, apt packages recorded and floating | passing |
| 1 | `compare_def.py warmup`: 230/230 on cell type, position and orientation | passing |
| 1 | `compare_libraries.py`: the upstream library against open_pdks `8afc8346`, 9 of 437 shared cells differ, all three of the puzzle's fallback cell types among them on the layers `docs/01` records; `--selftest` catches a 1 nm move and tells the signature from outside it | passing |
| 1 | `stage1_cells.py warmup --library pdk/open_pdks_sky130A`: 230/230 under the alternate library too, no definition changes tier | passing |
| — | `verify_determinism.py`: `registers.json`, `--compare` and `analyse()` on `scale_datapath` byte identical under `PYTHONHASHSEED` 1 and 424242; `--selftest` catches 2 of 2 planted | passing |
| 2 | same tool: 84/84 signal nets matched connection by connection | passing |
| 2 | `sim/run.py warmup`: all 65536 operand pairs, 15 successes, 0 mismatches | passing |
| 2 | `sim/run.py puzzle`: 312 cycles of the VCD, 0 mismatches, success never high | passing |
| 2 | `stage2_unionfind.py`: independent extractor agrees, 86/86 and 725/725 | passing |
| 3 | round trip: graph back to Verilog still passes the stage 2 simulation | passing |
| 3 | `stage3_crosscheck.py`: annotations re-derived from stage 2's netlist, forwards; warmup 84/84 nets and puzzle 723/723 agree on roots, cones and flop wiring | passing |
| 3 | `stage3_crosscheck.py --selftest`: all 17 corruptions caught, one per field group; four fields the warm up can only be made to disagree about are named | passing |
| 3 | `verify_annotations.py warmup`: 16 flops, all holding on `en` low, async `rst_n` low, one clock root, no sets, against `00_source.v` | passing |
| 4 | `verify_cone.py warmup`: the composed listing proven equal to `a + b == 496` over all 65536 assignments, by an evaluator sharing no code; and stage 4's structural bit order among the 24 weight assignments that make it so | passing |
| 5 | `verify_corpus.py`: 12 rules, 762 uses against what stage 3 found, over both mappings of all 98 synthesised circuits and the one pre-mapped witness; a missing or stale `graph.json` fails rather than warning | passing |
| 5 | `verify_corpus.py --selftest`: all 15 corruptions caught, **and all 12 rules tripped by at least one of them** | passing |
| 4 | `verify_blocks.py`: the warm up's registers against the hierarchy its own DEF states, `[8, 8]`, by **membership** and not only by size | **failing**: the committed criterion answers `[16]` |
| 4 | `stage4_registers.py --score`: 117/137 exact beside a null model that gets 109/137; NMI 0.001 and purity 0.5525 over the fourteen netlists whose truth has more than one class, where the same null model scores 0.0 and 0.5481; every figure against a recording, and a move in either direction fails | passing, and it says the criterion is the null model on NMI |
| 4 | `stage4_registers.py --compare`: five criteria against their recordings, and two checked demonstrations the scores cannot show | passing |
| 4 | `stage4_registers.py --selftest`: seven hand computed NMI and purity rows reproduced, including both branches of the 0/0 convention | passing |
| 4 | `verify_metrics.py`: NMI and purity recomputed from the joint entropy, agreeing on the hand table, on 4000 random partitions and on four invariants; `--selftest` catches 3 of 3 wrong implementations | passing |
| 4 | `verify_grouping.py warmup`: single linkage against a brute force transitive closure at all 12 thresholds, determinism under 100 shuffles, every chain link checked against the graph; `--selftest` catches 4 of 4 | passing |
| — | `verify_figures.py`: 14 document table rows matched by value against the runs, 27 registry figures, and `docs/05`'s quoted fence and 10 of its numbers checked against the run that prints them; `--selftest` catches 6 of 6 | passing |
| 4 | `verify_functions.py`: every combinational cell's liberty function against the PDK's behavioural model, 850 patterns, 0 disagreements | passing |
| 4 | `verify_functions.py --selftest`: 2 of 3 deliberately wrong parsers are exposed by the library; the third is covered by hand written tables | passing |
| 4 | every circuit in the synthetic corpus recovered with correct parameters | todo |
| 3 | `verify_equiv.py warmup`: the recovered netlist proven sequentially equivalent to `01_netlist.v`, 153 correspondence points, all proven | passing |
| 6 | `stage6_invert.py --selftest`: four synthetic graphs put the tie cell check and the double driver check to known-bad input, 4 of 4; removing either guard turns its own case red. No container, no solver, no corpus | passing |
| 6 | `stage6_invert.py warmup`: a trace found at depth 8, proven to hold from every start state; `--post-reset` finds the same depth over the one state a toggled `rst_n` leaves, in 10 solver calls against 28 | passing |
| 6 | `sim/replay.py warmup`: that trace reproduces against **stage 2's** netlist and the output is high at the predicted cycle | passing |
| 7 | `stage7_output.py warmup --extend 6`: the trace replayed through the shared harness, one sample per cycle, every output read back. The warm up has no multi-bit output, and `stream NONE` is the right answer rather than a failure | passing |
| 7 | `verify_output.py`: both streamer circuits, both mappings, every byte exact against a string declared before the run, at the declared cycles, with the rendering read back by a second implementation | passing |
| 7 | `verify_output.py --selftest`: a byte changed in the stream, a byte changed in the answer key, and a raw control byte left in the rendering; 3 of 3 caught | passing |

## Facts worth not rediscovering

**The 22 fallback placements have a testable cause, and the machinery is
built.** The upstream library and the same library as **open_pdks** builds it
differ on 9 of 437 shared cells, and all three cell types the puzzle falls back
on are among them, on exactly the layers `docs/01-cell-recognition.md` records:
`o211a_2` poly and licon1, `conb_1` npc, `and4b_2` poly. Eight of the nine
differences are confined to poly, licon1 and npc; the ninth moves on `122/16`
pwell pin and is reported as outside that signature. **The warm up cannot test
it** -- it places none of the nine, and answers 230/230 under both libraries.
The author's command and what each outcome means are in `docs/01`.

**PDK.** `sky130_fd_sc_hd`. Row height 2.720 um, site width 0.460 um. Layer map
in `docs/00-environment.md`. Pin labels survive in the layouts on li1 (67/5) and
met1 (68/5), so pin identity need not be inferred.

**Three PDK views, three jobs. Do not substitute one for another.** GDS is
geometry, for stage 1's fingerprints and `common/cellnodes.py`'s terminal map.
LEF is the physical abstract: pin directions and PORT rectangles. **Liberty is
the only functional statement** — `clocked_on`, `next_state`, `clear`, `preset`,
and `function` per output. Stage 3's roles come from liberty, not from `USE
CLOCK` plus the cell name. This library publishes liberty as per cell, per
corner JSON; one corner is cached (`tt_025C_1v80`, 429 files), corners differing
only in timing.

**Liberty booleans are JSON strings.** `"clock": "false"`, and `bool("false")`
is true. Use `common/liberty.boolean()`. Getting this wrong marks every
combinational input as a clock and leaves the netlist valid.

**Liberty writes combinational functions parenthesised and sequential fields
bare.** `function : "(!A)"` but `clear : "!RESET_B"`. Reading the active level
off the first character therefore gets every `clear` right and all 21 inverters
in the library wrong. `liberty.pin_of` unwraps enclosing parentheses first;
`liberty.unwrap` strips only *enclosing* ones, so `(A)&(B)` survives.

**A constant a check always confirms is a check on nothing until something can
make it vary.** Both halves are needed: a circuit that produces the other
answer, and a producer able to report it. `verify_corpus.py` prints
`always <value>` beside any rule whose declared value never varies.

**Cells cannot be blackboxes past stage 3.** A graph can be walked without
knowing what a cell computes; an SMT2 or CNF export cannot be written. The
`function` expressions are carried in `graph.json` for stages 4 and 6.

**Detectors must normalise the drive strength suffix, and reason about
functions rather than cell types.** `a21oi_1` and `a21oi_2` compute the same
function. Corpus and puzzle overlap 4% on full cell names and 91% on functions;
matching on the full name would fail on the target. Beyond the suffix, 12 puzzle
cell *functions* never appear in the corpus at all, leaving about 9% of puzzle
cells that structural matching cannot name. `graph.json` carries every cell's
liberty function so a detector need not be limited that way.

**Vocabulary overlap is not functional coverage, and must not be quoted as it.**
The corpus can only name a puzzle block if some corpus circuit computes the same
function; a block built entirely from `nand2` scores 100% on vocabulary and may
still be unnameable. **Functional coverage measured so far is zero — no miter
has been run.** The real number is stage 4's residue report.

What *can* be measured before stage 4 is a one-directional bound, and
`tools/corpus_reach.py` measures it: a cone depending on more distinct inputs
than any corpus cone cannot be equivalent to one, so it cannot be named at all.
0 of the puzzle's 189 cones fall outside the envelope — but only since the
`scale_datapath` family was added. Without it the envelope stops at 33 inputs
and two puzzle cones of 57 are provably unnameable.

**Bits of one register do not share a clock net.** The puzzle's 92 flops sit on
16 `clkbuf_8` branches. Grouping flops by clock net splits every register.
Stage 3 now resolves this: all 16 branches walk back two hops to one root named
`clk`, and `graph.json` carries `clock_roots`, `reset_roots` and `set_roots`
with the flops under each. Which cells are transparent comes from liberty's
function — single output equal to single input, possibly inverted — never from
the cell's name, so `clkbuf`, `inv`, `buf` and `clkinv` are all covered and
`diode` and `conb_1` are correctly excluded. The corpus's `clock_tree` family
exists to make the failure visible, and `verify_corpus.py` asserts one root.

**A mux is identified by its function, never by its name.** `mux2i` is an
*inverting* mux, `(!A0&!S)|(!A1&S)`, so a flop whose D comes from one with its
own Q on a leg toggles rather than holds. The test was `"mux2" in the cell
name`, which admits it. The rule is now the cofactor: for some pin S the
function at S=0 must be identically another pin, positively. Across the
library's 429 cells exactly four outputs pass, the four `mux2_*`. The corpus's
`mux2i_witness` is a pre-mapped netlist that exists only so this rule has
something to reject: the detector as it stood before the fix records a hold on
it, and the detector now records none.

**A held register has no single structure.** Stage 3's search for a mux in front
of D with Q fed back finds 6 of the corpus's 30 declared enables. Four measured
shapes defeat it, and the fourth is the general case: `D = en ? (acc ^ lfsr) :
outr` maps to one `a21oi` with Q arriving two cells back, because once the data
leg is computed rather than a port, the mapper folds the select into the logic
that computes it. Do not extend the pattern list — **"does this register hold"
is a functional question**, ∃ an input assignment where D ≡ Q, and it belongs to
stage 4's solver. The structural count is a labelled lower bound.

**Yosys `clkbufmap` fails silently in two ways.** Its argument is
`-buf <cell> <out>:<in>`, so `X:A`; and it finds sinks by the `clkbuf_sink`
attribute, which cells from `dfflibmap`/`abc` do not carry. Read the blackbox
library first with clock pins marked from liberty.

**PDK cache layout matters.** `.gds` and `.lef` are flat in
`pdk/sky130_fd_sc_hd/`; `.v` keeps the library's directory structure, because
per-strength wrappers include their base by bare name and the sequential and mux
models reach up for UDP primitives with `../../models/...`.

**The fetched PDK revision is not the one that drew the puzzle.** Three cells
differ on poly, licon1 or npc. Stage 1 handles it with a structural fallback
tier; 22 of 1618 puzzle placements resolve that way.

**`example_inputs.vcd` carries outputs as well as inputs.** Two attempts of 121
bits each, both answered `TRY AGAIN` with success low, 312 rising edges total.
It is a real test vector for the puzzle target.

**Puzzle shape.** Ports `clk`, `rst_n`, `enable`, `I` in; `success`, `O[7:0]`
out. `I` is one bit, so input is serial. 728 logic cells, 92 flip-flops: 84
`dfrtp`, 4 `dfstp` (**set**, not reset), 4 `dfxtp`. The `dfstp` cells mean some
register leaves reset holding a non-zero value.

**Liberty's functions are fully parenthesised, so precedence is untested by
them.** `(A1&B1) | (A2&B1)`, never `A1&B1 | A2&B1`. A parser with `&` and `|` at
one precedence level agrees with the behavioural models on all 448 functions in
the library, so `verify_functions.py`'s 850 comparisons are evidence about
identifiers, negation and grouping and none at all about precedence. Eight hand
written truth tables are what cover it.

**Stage 7 reads the bus; it does not read the string.** `stage7_output.py`
replays a stage 6 solution through **stage 2's** netlist and reports what every
output carried, cycle by cycle, with non-printables escaped and nothing dropped.
Two knobs decide the answer and neither can be derived from anything here, so
both are printed with every result: `--extend N` keeps clocking past the trace,
because the string's length is unknown, and `--after` says what drives the
inputs once the trace runs out. Measured on the warm up: `hold-last`, `zeros`
and `en=1,A=1` give `S` as `1 1 1 1`, `0 0 0 0` and `1 0 0 0` over the same four
extension cycles. The default is `hold-last` and it says so in its own output.

**A stream's start, length and end are not observable from outside the circuit,
so the gate had to be a circuit whose string was written first.** The corpus's
`streamer` family emits a declared ASCII string one byte per cycle after a one
cycle trigger and then idles. Two of them, different lengths, one carrying
`0x07` and `0x0a` so the escape path is exercised. The flop counts are derived
from the *string* before synthesis: every ASCII byte has bit 7 clear, so the
output register is seven flops and `O[7]` comes from a `conb_1`. Stage 3 finds
seven.

**Stage 6's cycle model, and the three things it refuses.** A cycle is a clock
edge, so the clock is not a signal: clock tree cells are dropped and the clock
port is implicit. `S(t+1) = resetval if r(t) or r(t+1) else D(t)` is what makes
an asynchronous reset asynchronous -- a level held across the edge clears the
flop from either side of it. That is only a definition while a flop's reset net
does not depend on a flop, so `stage6_invert.py` refuses a design where it does;
refuses one where a clock net is read by anything but a flop's clock pin; and
refuses one where a flop carries **both** an asynchronous set and an
asynchronous clear, because the model orders those two one way at cycle 0
(independent implications, so both asserted is unsatisfiable) and the other from
cycle 1 on (set dominates). None of the three happens in the warm up or the
puzzle -- and the third is worth the guard rather than the assumption, because
the puzzle's `rst_n` is both the reset root *and* the set root, which is one net
on two different pins and not one flop with two. Problem 50.

**`graph.json`'s `clock_nets` is the nets *at the flop pins*, not the tree.**
The warm up's tree is `clk -> n8 -> {n18, n41}` and the field lists n18 and n41
only. Anything wanting the whole tree has to walk back from the flops.

**A free initial state makes bounded model checking answer the wrong question.**
The solver will happily return a trace that only works from one power-up state,
and nothing powers up in a state anyone chose. Measured on the warm up: every
depth from 0 to 7 yields such a trace. `stage6_invert.py` puts each candidate to
the opposite question -- is there a start state these inputs fail from -- and
pins any it finds as another copy of the design. Depth 8 is the first that
survives, and it needs no reset, because eight shifts overwrite the registers.

**`success` is a registered output.** The port is driven straight off a `dfrtp`,
so its own cone holds one signal. The condition lives in that flop's data cone:
47 cells over 57 bits of R0, no primary input and no constant reaching it. The
success condition is a function of stored state alone, which is why stage 6 is
bounded model checking and not a single SAT call.

**The warm up's own hierarchy is an answer key, and it went unused for five
stages.** `01_netlist.v` and `03_post_place_and_route.def` name every instance
with the block it came from — `sr_a` 16 cells, `sr_b` 16, `add0` 41, `cmp0` 3 —
so the true register partition is `[8, 8]`. `tools/verify_blocks.py` maps it onto
the recovered instances by position, orientation and cell, 230 of 230.

**Registers, derived by stage 4. No criterion is committed, because measurement
refuted the first choice and then refuted the ranking.**

| Criterion | exact /137 | NMI | purity |
|---|---|---|---|
| control signature | 117 | 0.001 | 0.5525 |
| colour refinement | 101 | 0.419 | 0.8214 |
| + flow split (DANA) | 91 | **0.5019** | **1.0** |
| + connected components | 80 | 0.3911 | 0.7623 |
| + components + flow split | 49 | 0.5019 | 1.0 |
| *null: one group, do nothing* | *109* | *0.0* | *0.5481* |
| *null: every flop its own* | *7* | *0.3879* | *1.0* |

**Exact match and NMI rank these in opposite orders**, and that is the most
useful thing stage 4 measures. Exact match compares size multisets, 109 of the
137 netlists declare one register, and the ranking is that majority talking. NMI
and purity above are over the fourteen netlists whose ground truth has more than
one class, and there the control signature scores the one-group null model's NMI
to three decimal places. On the warm up it is wrong, and connected components
and placement locality — the two the corpus ranks worst and cannot score at all
— are right. Where they disagree, that disagreement is the residue.

**And the NMI ordering is not stable.** Stage 7's two `streamer` circuits joined
the corpus as four netlists, four of the fourteen that ask the question. On them
**colour refinement is exactly right and connected components answers one
group** — the index register feeds the ROM that feeds the output register, so
the two are connected — which is the mirror of the warm up. That moved
connected components from 0.5476 over ten to 0.3911 over fourteen and put the
flow split on top. Nothing was tuned. Read the column as an ordering over
fourteen netlists, not as a settled ranking.

**A sixth criterion the corpus cannot score.** `spatial_groups` is single
linkage on stage 1's placements at a recorded 3 row heights. On the warm up it
answers `[8, 8]` with the correct membership, NMI 1.0, and the two clusters are
21.76 um apart. Nothing under `out/synth/` was ever placed, so **n = 1** and no
figure in `--score` or `--compare` covers it.

**A partition is a membership and the block gate was reading a histogram of
it.** `[8, 8]` says two groups of eight and nothing about which eight; there are
6435 such splits and `verify_blocks.py` accepted all of them. It now scores
membership beside sizes and carries a deliberately interleaved null model that
answers `[8, 8]` from no information at all, so the column has a known-bad input
standing in it. Problem 46.

**Bit order, where the structure gives one.** `bit_order` follows D <- Q for a
shift chain and ripple depth for a carry chain, and emits `"method": null` with
the reason for the 95 corpus groups that have neither — a plain register's bits
do not depend on one another, so there is nothing to order, and a guessed order
is worse than none. The warm up's sixteen flops under one control signature come
out as two chains of eight, which is `sr_a` and `sr_b` exactly.

The puzzle's 92 flops become 4 registers: R0 72 bits (reset), R1 12 bits (reset,
holds on one net), R2 4 bits (no reset, `dfxtp`), R3 4 bits (set, `dfstp`).
**R0 is unresolved** — 72 bits under one signature, which refinement wants to
cut into 23, 22, 8, 4, 4, 4, 2, 2 and three singletons. That is the residue, and
it is where a person reads.

A hold stage 3 misses is a split missed here -- and worse, a hold missed on
*some* bits of one register invents a split that is not there. Measured: the
warm up's own RTL mapped two ways gives [16] and [11, 5] from the same
criterion, because `abc -fast` folded five of sixteen muxes away. Problem 45.

**Puzzle structure, derived by stage 3.** 16 clock branches, each from a
`clkbuf_8`, twelve carrying six flops and four carrying five: 92 exactly.
`rst_n` is both the reset net and the set net, clearing 84 and presetting 4.
12 constant nets, six 1 and six 0, from the 6 `conb_1`. 12 flops hold their
value through a mux in front of D, all selected by one net. 189 cone roots =
92 data + 88 async + 9 primary outputs.

**`VIA_*` placements are routing constructs, not components.** `INTERNAL_3` and
`INTERNAL_7` are marker rectangles on layer 200/0 with no devices.

**Routing lives inside placements, not in the top cell.** The top cell owns
almost nothing on the routing layers: in the warm up 1 met1, 9 met3, 6 met4,
5 met5, plus 1366 met2 shapes that are the emblem. Summed over placements it is
1778 li1, 991 met1, 508 met2, 200 met3. Each `VIA_*` cell holds one via stack —
`VIA_M1M2_PR` is exactly one met1, one via, one met2. Anything that flattens or
reads only the top cell will conclude the design has no routing.

**Both layouts carry the same emblem.** 1366 identical 0.3 x 0.3 um met2 squares
spanning 17.10 x 17.10 um, at (65.90, 66.20) in the warm up and (34.90, 35.20) in
the puzzle. It explains all three pin-less nets in each target.

**A cell terminal can be contacted where the LEF declares no pin.** `a31oi_2`
has two li1 contacts on its A1 gate and offers one as the pin; the puzzle's
router used the other. Since the stack starts at li1 and excludes poly, the two
looked like separate nets and the netlist carried an undriven wire.
`common/cellnodes.py` resolves this from the PDK, guarded by the rule that two
*declared* pins of a cell are never one net (which is what stops `conb_1`'s
constant outputs being absorbed into the rails). 66 puzzle cell types have the
same risk; one had routing land on it. Found by the union find fallback, not by
any gate — **the puzzle simulation passed 312 cycles both before and after the
repair.**

**KLayout's `subcircuit.id()` is not stable across runs.** Keying a comparison
on it reported 67 of 86 nets as changed when nothing had changed. Key on
(position, orientation, cell) instead — the same rule stage 2 already needs for
mapping. Any tool comparing two extractions should first extract the unchanged
input twice and refuse to continue if the results differ.

## Traps already paid for

The full register, with symptoms, root causes and whether each fix is understood
or only worked around, is `docs/problems.md`. The ones most likely to bite again:

- **Position alone is not a placement key.** A GDS origin is where the cell's
  own origin landed, so a flipped cell extends left and down from it: the warm
  up's 230 instances share only 178 origins. Key on position *and* orientation.
- **Filtering LEF pins on `USE SIGNAL` drops every clock.** 69 pins in this
  library are `USE CLOCK`. Exclude supplies instead.
- **Cell models need `-DFUNCTIONAL -DUNIT_DELAY=#1`.** Without them the
  behavioural views compile and every output stays `x`.
- **A bit of a declared vector must be written `O[0]`, not `\O[0]`.** The
  escaped form is a separate scalar and leaves the bus undriven.
- **The VCD is a zero delay dump** and lists an output change *before* the clock
  change at the same timestamp, so snapshotting on the edge already captures
  what that edge produced.

## Known gaps

- The BuildKit network failure is worked around, not understood.
- The fallback lists 15 unconnected `clkbuf_4` outputs the primary omits. Both
  agree the terminal is unconnected; only the reporting differs. Classified in
  the comparison, not silently dropped.

## Working habits this project has already paid for

- **Open the primary artifact before reasoning from a secondary one.** The most
  expensive error here was declaring the VCD output-free on the strength of one
  README sentence.
- **Verify what a step produced, not its exit code.** `docker build | tail`
  reports `tail`'s status; a failed build looked successful twice.
- **When a result is "almost right", suspect the harness.** Running the
  *reference* netlist through the same testbench separated a broken harness from
  a broken extraction in one run.
- **Log what does not match rather than dropping it.** Every real defect this
  session surfaced through an unmatched-items report or an independent
  cross-check.
- **The round trip gate does not check stage 3's annotations.** `graph.v` is
  written from cells and connections alone, so clock roots, cones and the flop
  inventory could all be wrong and it would still pass. Those are what stage 4
  consumes. `stage3_crosscheck.py` derives them a second time, forwards, from
  stage 2's `netlist.json` rather than through Yosys.
- **A passing test that was never able to fail is not evidence.** The puzzle
  simulation passed with a wrong netlist; the `conb_1` guard reported no
  conflict because it could not see the case it existed for. Exercise a check
  against a known-bad input once, or it is only silence. `verify_corpus.py
  --selftest` is this rule made routine, and it caught its own blind spot on its
  first run.
- **Inventory the answer keys before building a substitute for them.** The warm
  up's RTL and reference netlist sat unread while a synthetic corpus was built to
  do their job. `tools/review_packet.py` lists every ground truth file and greps
  for what reads it, so "unused" is visible rather than remembered.
- **A score a trivial implementation also achieves is not evidence.** Print the
  null model beside every score, in the same run.
- **A failed build must not overwrite the answer key it failed to produce.**
  Docker Desktop stopped, all 93 circuits failed, and `stage5_corpus.py` wrote
  an index of zero over a good one; `verify_corpus.py` then reported 0/0 as a
  pass. It now refuses to rewrite the index if any circuit failed.
- **A measurement that is not a program is a measurement that happened once.**
  "The declared width equals the flip flops stage 3 finds, 86/86" sat in
  `docs/05` as prose for a session. Written as a tool instead, it immediately
  found six circuits whose answer key was wrong.
- **A check that fires on a real defect is not thereby a correct check.** The
  first reset rule reported the right circuits for the wrong reason and would
  have gone on reporting them after the fix.
- **Test at the size of the target, not at the size that is convenient.** The
  corpus's median circuit held four flip flops against the puzzle's 92, and the
  aggregate totals hid it. The `scale_datapath` family brackets the target at 90,
  178 and 354 flops so a scaling problem appears as a trend.
- **A gate needs an exit status, not just a verdict.** `--score` printed
  116/126 and ended in `return 0`; swapping the criterion for one that splits
  every flop printed 6/126 and still passed. Anything the pipeline calls a gate
  must be run once against a known-bad input, and what it should measure written
  down, or the printed number is the only thing doing the checking.
- **Every corruption caught is not every rule covered.** `verify_corpus.py
  --selftest` reported ten of ten and had tripped seven of its twelve rules. The
  question has two sides and only one was being asked.
- **A solver result is a claim about the model, not about the circuit.** Stage
  6 builds its transition relation from the same `graph.json` a defect would be
  in, so a corrupted `cell_functions` entry gives a confident, self consistent,
  wrong trace. `sim/replay.py` puts the trace through stage 2's netlist and the
  PDK's own models instead, which is the only thing that would notice.
  Demonstrated: one liberty function altered, solver still says pass, replay
  says fail.
- **Count rules, not facts.** "662 declared facts" is eleven rules times the
  corpus size. Four were constants; two have been made to vary, and the tool now
  labels the rest. Asking why one of them could never be non-zero found a real
  defect in `liberty.pin_of`.

## Documentation conventions

One document per stage in `docs/`, numbered to match. Do not merge them.

`docs/lectures/` holds step-by-step lessons in Turkish, written for someone with
no hardware background, numbered to match the stage they accompany. These are a
deliverable of every stage, not an afterthought: explain what is being done and
why while doing it, build up from first principles, and write them **after** the
stage's gates pass so they describe verified facts.
