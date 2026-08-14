# gds-teardown

Recovering an ASIC's function from its layout, for the Jane Street 2026 puzzle.
**This is a competition submission.** Deadline 4 September 2026.

## Read these first

- `docs/solver-pipeline.md` — what gets built. The build spec, seven stages.
- `docs/jane-street-asic-roadmap.md` — when. Schedule, phase budgets, gates.

The deliverable is the pipeline, not the answer. The answer is its first test
case.

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
python tools/fetch_pdk.py        # ~4 MB of sky130 cell GDS into pdk/, pinned
git submodule update --init      # upstream puzzle files into puzzle/
```

`gdstk` and `klayout` are pip wheels on all three platforms, so this setup is
portable. `klayout.db.LayoutToNetlist` supplies the stage 2 extractor, so no
Docker is needed until stage 3 brings in Yosys, Icarus and `yosys-smtbmc`.

## Running

Every stage takes a target, never a hard coded path.

```bash
python tools/stage1_cells.py warmup     # -> out/warmup/instances.json
python tools/compare_def.py warmup      # gate: must report 230/230
python tools/stage1_cells.py puzzle
```

Targets: `warmup` (full source and DEF as ground truth), `synth` (generated
ground truth), `puzzle` (the real run). **No stage runs on `puzzle` before it
passes on a target with ground truth.**

## Verification gates

| Stage | Gate |
|---|---|
| 1 | `compare_def.py warmup` reports 230/230 on cell type, position and orientation |
| 2 | recovered warm-up netlist raises success exactly when the operands sum to 496 |
| 2 | puzzle netlist reproduces `example_inputs.vcd`: same inputs give `TRY AGAIN`, success low |
| 3 | round trip, graph back to Verilog still passes the stage 2 simulation |
| 4 | every circuit in the synthetic corpus recovered with correct type and parameters |
| 6 | any solver trace reproduces in simulation before it is believed |

## Facts worth not rediscovering

- PDK is `sky130_fd_sc_hd`. Row height 2.720 um, site width 0.460 um.
- Layer map is in `docs/00-environment.md`. Pin labels survive in the layouts on
  li1 (67/5) and met1 (68/5), so pin identity need not be inferred.
- The fetched PDK revision is *not* exactly the one that drew the puzzle. Three
  cells differ on poly, licon1 or npc. Stage 1 handles this with a structural
  fallback tier; see `docs/01-cell-recognition.md`.
- `example_inputs.vcd` carries outputs as well as inputs. Two attempts of 121
  bits each, both answered `TRY AGAIN` with success low. It is a real test
  vector for the puzzle target.
- Puzzle ports: `clk`, `rst_n`, `enable`, `I` in; `success`, `O[7:0]` out. `I`
  is one bit, so input is serial. 92 flip-flops, so 92 bits of state.
- `VIA_*` placements are routing constructs, not components. `INTERNAL_3` and
  `INTERNAL_7` are marker rectangles on layer 200/0 with no devices.

## Documentation conventions

One document per stage in `docs/`, numbered to match. Do not merge them.

`docs/lectures/` holds step-by-step lessons in Turkish, written for someone with
no hardware background, numbered to match the phase they accompany. These are
a deliverable of every phase, not an afterthought: explain what is being done
and why while doing it, and build up from first principles rather than assuming
vocabulary.
