# The toolchain, carried to the design competition

Status: an idea document, written 23 August 2026, before the competition's
rules are published. Nothing here is scheduled. The right time to act on it is
after 4 September, when the puzzle submission closes and this repository goes
public. Update this file when the actual announcement lands; every assumption
below is marked as one.

## What the competition is

The puzzle announcement states that a larger competition follows later in the
year: entrants design their own chip, and the most interesting designs are
fabricated. (Recorded in `docs/jane-street-asic-roadmap.md`, Follow up.) No
rules, dates or constraints are public yet — assume sky130-class open tooling
until told otherwise, since that is what the puzzle itself used.

## The inversion

This repository reads a chip out of a layout. A design competition runs the
same road in the other direction — RTL down to GDS. The reason the toolchain
still transfers is that almost none of it is direction-specific: it is a set
of gates that tie four views of one circuit together (RTL, netlist, layout,
behaviour), and a designer needs those ties exactly as much as a reverse
engineer does. What we built as extraction checks becomes design signoff.

## What transfers, tool by tool

| Asset | Here it does | There it does |
|---|---|---|
| `verify_equiv.py` (Yosys miter) | proves the recovered netlist equals the reference | proves the synthesised netlist equals your RTL — the standard signoff nobody skips |
| `stage1_cells.py` + `compare_def.py` | recover placements from GDS, check against DEF | check that the GDS you are about to submit places exactly what your DEF says — a last-mile tapeout check |
| `stage2_nets.py` + `stage2_unionfind.py` | extract connectivity two independent ways | LVS-adjacent: extract your own layout back and diff it against your netlist, catching what a flow bug silently dropped |
| `sim/run.py`, `sim/replay.py` harness | simulate recovered netlists under the PDK models | the testbench harness for the design, unchanged |
| `stage6_invert.py` (BMC out of `graph.json`) | finds the input that raises `success` | property checking on your own design: "can this state be reached", "is this output drivable" — bug hunting before tapeout |
| `stage5_corpus.py` + `verify_corpus.py` | synthetic circuits with declared answers | a regression corpus for whatever generator/flow the design uses; the answer-key discipline transfers whole |
| `verify_functions.py`, `common/liberty.py`, `common/cellnodes.py` | the PDK's cells, read three ways and cross-checked | the same library knowledge, needed the moment anything at gate level is touched |
| `review_packet.py` and the gate culture | evidence of record for a reviewer | evidence of record for the judges — a design whose checks are shown to be able to fail is exactly the "taking it further in some dimension" their rubric rewards |
| `docker/` environment, pinned PDK, `TOOL_VERSIONS` | reproducible extraction | reproducible build, which a fabricated design must have |
| `docs/problems.md` discipline | the defect register | the same, and their judging notes say an honest debugging trail is what they single out |

What does NOT transfer: the detectors (`stage4_*`) and the corpus-reach bound
are reverse-engineering-specific. They stay useful only if the design work
involves reading someone else's netlists.

## What a design entry needs that this repo does not have

- A design. The toolchain is scaffolding; the competition is won by what the
  chip does. (Assumption: "most interesting" is judged on the idea and the
  account, same as the puzzle's rubric weights the writeup.)
- A synthesis-to-GDS flow (OpenLane or equivalent). We consume its outputs;
  we have never driven it. `docs/references.md` §2-3 already catalogues the
  pinned, working example to copy: `18224-tapeout-s23-caravel`.
- Timing. Nothing here reads SDF or STA reports; a fabricated design cannot
  ignore them.
- Physical constraints of whatever shuttle they use (die area, pin budget,
  clock). Unknown until the rules land.

## The one idea worth writing down now

The puzzle taught a specific lesson worth designing INTO a chip: the emblem,
the Morse row, the layout-hints-at-function arrangement — the authors treat a
chip as a thing that carries its own account. A competition entry built with
this toolchain can go one further: ship the design WITH its own verification
packet — the RTL, the gates, the corruption selftests, the equivalence proofs,
and a `review.md` regenerated from a clean clone — so the judges receive not
a GDS but a GDS that proves itself. Nobody else's entry will have that, and it
is the part of this repository that was hardest to build and transfers for
free.

## When

After 4 September, in this order: (1) submission ships; (2) this repo goes
public; (3) the owed lectures get written; (4) when the competition rules are
published, revisit this file and decide whether to enter. Start a fresh
repository for the design and vendor this one's `tools/` rather than growing
the teardown repo sideways.
