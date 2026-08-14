# Solver Pipeline Specification

Companion to `jane-street-asic-roadmap.md`. That document schedules the work.
This one specifies what gets built.

Reference this file from `CLAUDE.md` so it is loaded at the start of a session.

## Intent

Build a program that takes `puzzle.gds` and produces the answer string, rather
than reaching the answer by hand and writing tooling only where convenient. The
deliverable is the pipeline. The puzzle answer is its first test case.

This is a harder target than solving the puzzle directly. Understanding a circuit
is cheaper than writing a program that understands circuits. The tradeoff is
accepted because a general extractor and analyzer is the artifact worth showing,
and because it carries over to the design competition that follows later in the
year.

## Architectural constraint

No language model runs inside the pipeline. Every stage is deterministic and
reproducible from the same inputs. Permitted components are layout and EDA tools,
graph algorithms, structural pattern matching, functional equivalence checking
and SAT or SMT solvers.

This constraint is load bearing rather than cosmetic. It is what makes the
pipeline a reverse engineering tool rather than a wrapper, it keeps the result
reproducible by anyone who clones the repository, and it keeps the submission
inside the puzzle rules. Model assistance is used to write the pipeline, not to
run inside it.

## Stages

Each stage reads the previous stage's artifact from `out/` and writes its own.
Stages are independently runnable and independently testable. No stage reaches
back into the GDS except stages 1 and 2.

### Stage 1, cell recognition

Input. `puzzle.gds`, PDK standard cell library.

Output. `out/<target>/instances.json`, a list of records carrying instance id,
library cell name, origin, orientation.

Method. Attempt hierarchy first. A GDS holds structure references, and if the
puzzle retains cell definitions the library names may be directly readable. Do
not assume this survives. Implement geometry matching as the primary path and
treat any surviving hierarchy as a cross check.

Geometry matching builds a fingerprint per library cell from the PDK GDS, keyed
on the polygon set of the identifying layers, normalized for the eight possible
orientations. Layout placements are fingerprinted the same way and matched.

Verification. Run against the warm up GDS. Instance types and counts must equal
the shipped reference netlist exactly.

Failure modes. Unmatched placements usually mean an unhandled orientation, a
filler or decap cell absent from the fingerprint set, or a cell abutment that
merged polygons across a boundary. Log every unmatched placement with its
bounding box for manual inspection rather than dropping it silently.

### Stage 2, connectivity extraction

Input. `puzzle.gds`, `instances.json`.

Output. `out/<target>/netlist.json` and `out/<target>/netlist.v`.

Method. Use the KLayout LVS netlist extractor as the primary path. It already
handles layer connectivity rules, via linkage and pin resolution, and
reimplementing it is not a good use of the schedule.

Specify the connectivity stack explicitly rather than relying on defaults.
Metal layers connect through their via layers, and cell pins attach on the layer
the PDK designates. Record the exact extractor configuration in
`docs/02-connectivity.md`, since a wrong connectivity rule produces a netlist
that is structurally plausible and functionally wrong.

Implement a fallback for the case where the extractor misbehaves. Union find
over touching polygons per layer, then merge across layers through via overlap.
Each resulting set is one net.

Verification. Simulate the recovered warm up netlist and confirm it raises
success exactly when the two shift register operands sum to 496.

Failure modes. Shorted nets from an overly permissive connectivity rule, and
floating pins from an overly strict one. Both show up as sample vector
mismatches. Compare net count against the reference netlist before simulating.

### Stage 3, normalization

Input. `netlist.v`.

Output. `out/<target>/graph.json`, a directed graph with derived annotations.

Method. Read the netlist into Yosys, then export a graph carrying the following
derived properties.

- Clock nets, identified by fanout into flip flop clock pins
- Reset and set nets, identified the same way
- Flip flop inventory with clock, enable, reset and data source per instance
- Primary inputs and outputs
- Constant nets tied to supply rails
- Combinational cone membership per net

Verification. Round trip. Write the graph back to Verilog and confirm the result
still passes the stage 2 simulation.

### Stage 4, structural detectors

Input. `graph.json`.

Output. `out/<target>/blocks.json`, a partition of the netlist into named
functional blocks with confidence and evidence per block.

Method. Two detection strategies, run in order.

Structural detection matches graph topology against known shapes. Registers are
flip flop sets sharing clock, enable and reset. A shift register is a register
where each bit's data input is the previous bit's output. A counter is a
register whose data input is its own output through an incrementer. An LFSR is a
register with XOR taps in the feedback path. An adder shows a carry chain. A
comparator reduces a wide difference or equality to one bit.

Functional detection is the fallback and the more reliable of the two.
Synthesis rewrites structure but preserves function, so a block that no longer
looks like a textbook adder still behaves as one. Isolate a candidate subgraph,
build a miter against a reference module of the same width, and ask a SAT solver
whether the two outputs can ever differ. An unsatisfiable result proves
equivalence.

The miter approach is what makes the detector set robust. Prefer it wherever the
candidate block is combinational and the input width permits.

Verification. Run against the synthetic corpus from stage 5. Every generated
circuit must be recovered with its correct type and parameters.

Failure modes. Blocks that span the boundary between two logical units, since
synthesis merges logic across module boundaries. Detectors should report
overlapping candidates rather than forcing a disjoint partition.

### Stage 5, synthetic corpus

Input. None. This stage generates its own ground truth.

Output. `synth/` with generated RTL, and `out/synth/` with the synthesized
netlists and expected block annotations.

Method. Write parameterized generators for the structures the puzzle is likely
to contain. Shift registers, counters, adders, subtractors, comparators,
accumulators, small finite state machines, LFSRs, multiplexers, decoders. Vary
width, depth and reset style.

Synthesize each through the same Yosys flow and the same PDK cell library used
by the puzzle, so that the cell vocabulary matches. Keep the source as the
expected answer.

This corpus is the test set for stage 4 and the reference library for the miter
checks. Build it before the detectors rather than after, since detectors written
without a test set cannot be validated.

Verification. Detector accuracy on held out generated circuits, reported as a
table in `docs/04-netlist-reading.md`.

### Stage 6, inversion

Input. `graph.json`, `blocks.json`, the identified success condition.

Output. `out/puzzle/solution.json` with the input sequence and the resulting
string.

Method. The design is sequential, so this is not a single SAT query. The
question is which input sequence over some number of clock cycles drives success
high, which is bounded model checking.

Use `yosys-smtbmc` against an SMT2 export of the netlist, in trace finding mode,
with the success signal as the property to violate. Increase the unroll depth
until a trace is found or the depth becomes impractical. Where the relevant logic
turns out to be combinational, a direct CNF export and a plain SAT call is faster.

Cross check any solver result by feeding the recovered input sequence back
through the stage 2 simulation. A trace that does not reproduce in simulation
indicates a modelling error in the export, not a solution.

Failure modes. Unroll depth too shallow, which returns no trace rather than an
error. Always report the depth reached alongside a negative result.

### Stage 7, output extraction

Input. The satisfying input sequence.

Output. The final answer string.

Method. The announcement identifies a region that produces output without
participating in the success condition. Earlier stages set it aside. Here it is
required. Simulate the full netlist including that region with the winning input
sequence and read the output.

## Repository layout

```
tools/
  stage1_cells.py          GDS to instance list
  stage2_nets.py           GDS and instances to netlist
  stage3_normalize.py      netlist to annotated graph
  stage4_detect.py         detector driver
  stage5_corpus.py         synthetic circuit generation and synthesis
  stage6_invert.py         bounded model checking driver
  stage7_output.py         final simulation and string extraction
  detectors/
    registers.py           flip flop grouping
    shift_register.py
    counter.py
    adder.py
    comparator.py
    lfsr.py
    miter.py               functional equivalence via SAT
  common/
    gds.py                 GDS reading helpers
    graph.py               netlist graph type and traversal
    solver.py              SAT and SMT invocation wrappers
  sim/
    testbench.v
    run.py
synth/                     generated RTL, one file per circuit
out/
  warmup/
  synth/
  puzzle/
docs/                      one document per stage, see roadmap
```

## Testing

The pipeline runs against three targets and the target is a command line
argument, not a hard coded path.

| Target | Ground truth available | Purpose |
|---|---|---|
| `warmup` | Full source and reference netlist | Validates stages 1 through 3 |
| `synth` | Generated source | Validates stages 4 and 6 |
| `puzzle` | Sample vectors only | The actual run |

No stage is applied to `puzzle` before it passes on the targets that have ground
truth. A stage that has not been validated produces output that looks correct and
cannot be checked, which is worse than no output.

## Scope for the available time

A fully automatic end to end solver is not reachable in three weeks. The
realistic target is a pipeline that is automatic through stage 4, with human
interpretation of the block partition, and automatic again for stages 6 and 7.

Record where the seam falls. The boundary between what the pipeline determined
and what required a person is the most interesting observation the project will
produce, and it belongs in the writeup rather than being smoothed over.

## Writeup obligations

The submission states which stages ran without intervention, where manual
interpretation was required and why, and that the pipeline itself was written
with model assistance while containing no model at runtime. Reproducibility is
the claim being made, so the repository should run end to end from a clean clone
once it is public.