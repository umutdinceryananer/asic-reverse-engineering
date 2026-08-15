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
| 2, connectivity | **done**, all four gates pass |
| 3, normalisation | not started, needs the `eda` image |
| 4, detectors | not started |
| 5, synthetic corpus | not started, build it *before* stage 4 |
| 6, inversion | not started |
| 7, output extraction | not started |

Lessons written: `docs/lectures/00`, `01`. **Ders 2 is owed** — stage 2 is
finished and gated, so it can be written from verified facts now.

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
python tools/sim/run.py      warmup       # gate: 65536 pairs, 0 mismatches

python tools/stage1_cells.py puzzle
python tools/stage2_nets.py  puzzle
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

## Traps already paid for

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

- Stage 2's union-find fallback, which `docs/solver-pipeline.md` asks for, is
  **not implemented**. The extractor has not misbehaved, but this is a skipped
  requirement rather than a satisfied one.
- The BuildKit network failure is worked around, not understood.

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

## Documentation conventions

One document per stage in `docs/`, numbered to match. Do not merge them.

`docs/lectures/` holds step-by-step lessons in Turkish, written for someone with
no hardware background, numbered to match the stage they accompany. These are a
deliverable of every stage, not an afterthought: explain what is being done and
why while doing it, build up from first principles, and write them **after** the
stage's gates pass so they describe verified facts.
