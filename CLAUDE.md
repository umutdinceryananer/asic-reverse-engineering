# gds-teardown

Recovering an ASIC's function from its layout, for the Jane Street 2026 puzzle.
**This is a competition submission.** Deadline 4 September 2026.

## Read these first

- `docs/solver-pipeline.md` — what gets built. The build spec, seven stages.
- `docs/jane-street-asic-roadmap.md` — when. Schedule, phase budgets, gates.

The deliverable is the pipeline, not the answer. The answer is its first test
case.

## Where the work stands

| Stage | State |
|---|---|
| 1, cell recognition | **done**, gated |
| 2, connectivity | **done** to spec, all five gates pass |
| 3, normalisation | not started, needs the `eda` image |
| 4, detectors | not started |
| 5, synthetic corpus | not started, build it *before* stage 4 |
| 6, inversion | not started |
| 7, output extraction | not started |

Lessons written: `docs/lectures/00`, `01`, `02`. The next one is owed when stage
3's gate passes; lessons are written after the gates, never before.

## Rules that bind this repository

**No language model runs inside the pipeline.** Every stage is a deterministic
program: layout and EDA tools, graph algorithms, structural matching,
equivalence checking, SAT and SMT. Model assistance writes the pipeline, it does
not run in it. A detector must be an algorithm, never a prompt.

**The puzzle rules restrict what an assistant may do with the puzzle files.**
The published rule is "don't feed the puzzle files directly into an AI tool, nor
use it to generate your writeups." The working split:

| Assistant does | Author does |
|---|---|
| Build every stage, detector and solver wrapper | Run the pipeline on `puzzle` |
| Validate against `warmup` and `synth`, whose answers are known | Interpret the block partition |
| Explain concepts, debug, refactor | Identify what the circuit computes |
| | Derive the winning input |
| | Write `docs/writeup.md` |

This is also the spec's own structure: the seam between what the pipeline
determined and what needed a person is the observation the writeup is about.

**Keep the repository private until 4 September 2026.**

## Environment

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt           # Linux, macOS
python tools/fetch_pdk.py        # ~10 MB into pdk/, pinned to one commit
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
python tools/stage1_cells.py warmup       # -> out/warmup/instances.json
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
```

Targets: `warmup` (full source and DEF as ground truth), `synth` (generated
ground truth, not built yet), `puzzle` (the real run). **No stage runs on
`puzzle` before it passes on a target with ground truth.**

## Verification gates

| Stage | Gate | Status |
|---|---|---|
| 1 | `compare_def.py warmup`: 230/230 on cell type, position and orientation | passing |
| 2 | same tool: 84/84 signal nets matched connection by connection | passing |
| 2 | `sim/run.py warmup`: all 65536 operand pairs, 15 successes, 0 mismatches | passing |
| 2 | `sim/run.py puzzle`: 312 cycles of the VCD, 0 mismatches, success never high | passing |
| 2 | `stage2_unionfind.py`: independent extractor agrees, 86/86 and 725/725 | passing |
| 3 | round trip: graph back to Verilog still passes the stage 2 simulation | todo |
| 4 | every circuit in the synthetic corpus recovered with correct parameters | todo |
| 6 | any solver trace reproduces in simulation before it is believed | todo |

## Facts worth not rediscovering

**PDK.** `sky130_fd_sc_hd`. Row height 2.720 um, site width 0.460 um. Layer map
in `docs/00-environment.md`. Pin labels survive in the layouts on li1 (67/5) and
met1 (68/5), so pin identity need not be inferred.

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
- **A passing test that was never able to fail is not evidence.** The puzzle
  simulation passed with a wrong netlist; the `conb_1` guard reported no
  conflict because it could not see the case it existed for. Exercise a check
  against a known-bad input once, or it is only silence.

## Documentation conventions

One document per stage in `docs/`, numbered to match. Do not merge them.

`docs/lectures/` holds step-by-step lessons in Turkish, written for someone with
no hardware background, numbered to match the stage they accompany. These are a
deliverable of every stage, not an afterthought: explain what is being done and
why while doing it, build up from first principles, and write them **after** the
stage's gates pass so they describe verified facts.
