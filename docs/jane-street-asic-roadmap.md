# Jane Street ASIC Puzzle, Working Plan

Working document for the 2026 Jane Street ASIC reverse engineering puzzle.
Submission closes 4 September 2026.

## Scope

Recover the function of an ASIC from its layout alone. The published material is
the full mask set, meaning metal, routing and active transistor layers, together
with a small set of sample input and output pairs. No RTL, no netlist, no labels.

Three deliverables in order.

1. A gate level netlist recovered from the GDS
2. An account of what the circuit computes
3. The input that drives the `success` signal high, and the string it yields

A warm up example ships with the puzzle. It is a binary adder distributed with
its Verilog source, its synthesized netlist and its GDS. It exists to calibrate
the extraction flow before touching the real layout.

Starting point is no prior hardware background. The plan compensates by
front loading tooling and by calibrating every step against a circuit whose
answer is already known.

## Repository visibility

Keep this repository private until 4 September 2026. It will accumulate the
recovered netlist, the analysis and eventually the answer, and a public copy
before the deadline spoils the puzzle for everyone still working on it. Flip it
to public once submissions close, at which point the writeup can be published
independently.

## Assistance model

The puzzle rules permit AI assistance for building the tooling needed to solve
it. The split below keeps that permission intact while still moving fast.

Open to assistance without restriction.

- All extraction, simulation and analysis tooling under `tools/`
- Library and API questions, debugging, refactoring
- Generation of synthetic circuits for calibration, and teaching material built
  on top of them
- Explanation of any layout, netlist or logic concept in the abstract
- Discussion of an observation carried over from the puzzle netlist, phrased as a
  general pattern rather than as a request to identify the circuit

Kept in hand.

- The identification of what the puzzle circuit computes
- The derivation of the input that satisfies the success condition
- The writeup

The writeup states which tooling was used and how it was built. That account is
the substance of the submission rather than a disclaimer attached to it.

## Environment

Target is a Linux workstation. The primary machine is memory constrained, so
prefer scripted headless flows and reserve the GUI for visual inspection only.

| Component | Purpose | Note |
|---|---|---|
| OSS CAD Suite | Yosys, nextpnr, Icarus Verilog, solvers, in one archive | Single tarball, no build step |
| KLayout | GDS inspection and the Python scripting API | Also provides the LVS netlist extractor |
| Magic VLSI | Second opinion on extraction | Optional, useful when KLayout output looks wrong |
| gdstk | Programmatic GDS reading from Python | Lighter than driving KLayout for batch work |
| Verilator | Faster simulation than Icarus on large netlists | Optional |
| Z3 | Constraint solving over the recovered netlist | Phase 6 only |
| Open PDK cell library | Ground truth for cell recognition | Shipped with or referenced by the puzzle repo |

Verify the toolchain before Phase 1 by synthesizing and simulating any trivial
Verilog module end to end.

## Repository layout

Paths under `puzzle/` are placeholders until the upstream repository is cloned
and its actual structure recorded in `docs/00-environment.md`.

```
docs/
  00-environment.md        toolchain versions, install notes, PDK location
  01-cell-recognition.md   layer semantics, cell geometry notes, match rates
  02-connectivity.md       via and metal traversal notes, extractor settings
  03-simulation.md         testbench design, sample vector results
  04-netlist-reading.md    sequential logic patterns, calibration results
  05-function-analysis.md  analysis of the recovered puzzle netlist
  06-solve.md              inverse problem, method and result
  writeup.md               submission text
tools/
  extract_cells.py         layout placements to cell instance list
  extract_nets.py          metal and via traversal to net list
  emit_verilog.py          instance and net list to structural Verilog
  compare_netlist.py       recovered netlist against reference
  analyze/
    find_registers.py      flip flop grouping into named registers
    clock_domains.py       clock and reset tree tracing
    trace_cone.py          fan in cone extraction for a given net
    truth_table.py         truth table derivation for an isolated block
  sim/                     testbenches and vector harnesses
synth/                     synthetic circuits used for calibration
out/
  warmup/                  artifacts from the extraction calibration run
  synth/                   artifacts from the analysis calibration run
  puzzle/                  artifacts from the real run
puzzle/                    upstream files, read only
```

One document per phase. Do not merge phase notes into a single file.

## Phases

### Phase 0, ground work

Budget 2 days, 13 to 14 August.

Clone the repository and record its structure. Install and verify the toolchain.
Open the warm up adder in KLayout and step through layer visibility one layer at
a time until the mapping between drawn geometry and circuit elements is legible.
Read the warm up Verilog source and its netlist alongside the layout.

Deliverable. `docs/00-environment.md` with toolchain versions, PDK path, layer
number to layer name mapping, and a short description of what each layer carries.

Exit criterion. Able to point at an arbitrary rectangle in the warm up GDS and
say which layer it belongs to and what it does.

### Phase 1, cell recognition

Budget 3 days, 15 to 17 August.

Extract the geometry of every standard cell in the PDK library. Write a matcher
that walks the layout hierarchy and maps each placement to a library cell name.
Handle mirrored and rotated placements. Record the match rate and inspect every
unmatched placement by hand.

Deliverable. `tools/extract_cells.py` and `docs/01-cell-recognition.md`.

Verification. Run against the warm up GDS. The recovered instance list must match
the reference netlist exactly, both in cell types and in counts.

Exit criterion. One hundred percent match on the warm up. Do not proceed on a
partial match. Errors introduced here become undiagnosable in later phases.

### Phase 2, connectivity extraction

Budget 3 days, 18 to 20 August.

Determine which cell pins connect to which nets by traversing metal layers and
vias. Use the KLayout LVS netlist extractor rather than writing traversal from
scratch. Emit the result as structural Verilog with named nets.

Deliverable. `tools/extract_nets.py`, `tools/emit_verilog.py`,
`docs/02-connectivity.md`.

Verification. Simulate the recovered warm up netlist in Icarus Verilog against an
exhaustive or randomized vector set and confirm it behaves as a binary adder.

Exit criterion. Recovered warm up netlist is functionally equivalent to the
reference.

### Gate, 20 August

If Phase 2 is not complete on the warm up by end of day 20 August, stop. The
remaining schedule does not absorb a slip here. The work already done retains
value as an introduction to layout and standard cell libraries.

### Phase 3, apply to the puzzle layout

Budget 1 day, 21 August.

Run the same pipeline against the puzzle GDS. Produce a simulatable structural
Verilog netlist. Build a testbench around the published sample input and output
pairs.

Deliverable. `out/puzzle/netlist.v`, `tools/sim/`, `docs/03-simulation.md`.

Verification. The recovered netlist reproduces every published sample pair. A
mismatch indicates an extraction defect, not a puzzle subtlety. Return to
Phase 2.

Exit criterion. All sample vectors reproduce. Mechanical work is complete.

### Phase 4, netlist reading calibration

Budget 2 days, 22 to 23 August.

Phase 5 requires reading sequential logic out of a flat gate list, which is a
distinct skill from extracting one. Acquire it on circuits whose answers are
already known rather than on the puzzle.

Write a set of synthetic RTL modules under `synth/` covering the structures most
likely to appear. Counters, shift registers, comparators, accumulators, small
finite state machines, LFSRs. Synthesize each with Yosys down to the same PDK
cell library, discard the source, and practice recovering the function from the
gate list alone.

Build the analysis tooling in parallel, since the same operations recur.

- Group flip flops into registers by shared clock and enable
- Trace clock and reset trees to find the sequencing structure
- Extract the fan in cone of any net back to primary inputs or register outputs
- Isolate a combinational block and derive its truth table by exhaustive
  simulation where the input width allows it

Deliverable. `tools/analyze/`, `synth/`, `docs/04-netlist-reading.md` recording
the structural signature of each circuit type.

Verification. Given a synthesized netlist not previously seen, name the circuit
type and its parameters from the gate list alone.

Exit criterion. Correct identification on unseen synthetic examples without
consulting the source.

### Phase 5, function analysis

Budget 5 days, 24 to 28 August.

The open ended part. Apply the Phase 4 tooling and reading technique to the
recovered puzzle netlist. Group registers, identify the control structure,
isolate combinational blocks and derive what each computes. Trace `rst_n` and
`success` backwards to find what gates the success condition.

Two hints from the announcement are worth acting on directly. One block produces
output but does not participate in the success condition, so identify and set it
aside early. The physical arrangement of the layout is said to hint at function,
so inspect the floorplan visually alongside the netlist rather than working from
the netlist alone.

Deliverable. `docs/05-function-analysis.md` describing the datapath, the control
logic, and the success condition.

Exit criterion. Able to state in one paragraph what the circuit computes.

Checkpoint 26 August. If the structure is still opaque, narrow the goal from
understanding the whole circuit to understanding only the success condition. The
remaining logic can be described structurally in the writeup without being fully
explained.

### Phase 6, solve the inverse problem

Budget 2 days, 29 to 30 August.

Find the input that drives `success` high and read out the resulting string.

Two routes reach the same answer. The analytical route inverts the logic directly
from the Phase 5 understanding. The mechanical route converts the netlist to CNF
with Yosys and hands the satisfiability question to Z3 or a SAT solver.

Run the analytical route first. The mechanical route is faster and terminates
regardless of whether Phase 5 succeeded, but it produces the answer without
producing any account of how the circuit works, which is the part the submission
is judged on. Keep it for verifying a hand derived answer, or as a fallback after
the analytical route has been given a real attempt.

Deliverable. `docs/06-solve.md` with the input, the derivation and the string.

### Phase 7, writeup and submission

Budget 2 days, 31 August to 1 September.

The submission form asks for a short account of the approach. This is the graded
artifact. Cover the extraction flow, the analysis that identified the function,
the derivation of the input, and which parts of the tooling were written with
assistance. Note any easter eggs found, which the announcement says are hidden
both in the repository and in the circuit itself.

After submission closes the writeup may be published independently. The
announcement invites solvers to send a link, and selected writeups are referenced
in the follow up post.

Buffer 2 to 3 September. Deadline 4 September.

## Schedule summary

| Dates | Phase |
|---|---|
| 13 to 14 Aug | Ground work |
| 15 to 17 Aug | Cell recognition |
| 18 to 20 Aug | Connectivity extraction |
| 20 Aug | Go or no go gate |
| 21 Aug | Apply to puzzle layout |
| 22 to 23 Aug | Netlist reading calibration |
| 24 to 28 Aug | Function analysis |
| 26 Aug | Scope reduction checkpoint |
| 29 to 30 Aug | Inverse problem |
| 31 Aug to 1 Sep | Writeup |
| 2 to 3 Sep | Buffer |
| 4 Sep | Submission closes |

## Risks

Extraction defects that pass the warm up but fail on the puzzle layout. The warm
up is a small combinational circuit and will not exercise sequential extraction.
Treat Phase 3 sample vector failures as extraction bugs first.

Phase 5 has no lower bound on effort. The five day budget is an allocation, not
an estimate, and the 26 August checkpoint exists to convert an overrun into a
narrower deliverable rather than a missed one.

Schedule collision with relocation at the start of September. Phases 6 and 7 are
the ones most likely to be disrupted, which is why the buffer sits at the end
rather than in the middle. Pull them forward where possible.

## Follow up

The announcement states that a larger competition follows later in the year, in
which entrants design their own chip and the most interesting designs are
fabricated. The toolchain built here transfers directly, and so does the netlist
reading skill from Phase 4.
