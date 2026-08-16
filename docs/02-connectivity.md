# Stage 2, connectivity extraction

Layout to `out/<target>/netlist.json`: which cell pins are wired to which.

Running record. Verilog emission and the simulation gate are not done yet; see
the end.

## Extractor

KLayout's `LayoutToNetlist`, driven from the `klayout` pip module, so this stage
runs in the same cross platform venv as stage 1 with no Docker.

## Connectivity stack

The spec warns not to rely on defaults, because a wrong connectivity rule
produces a netlist that is structurally plausible and functionally wrong. The
stack is therefore written out in `tools/stage2_nets.py` and reproduced here.

| Layer | GDS | Role |
|---|---|---|
| `li1` | 67/20 | local interconnect, **where standard cell pins live** |
| `mcon` | 67/44 | li1 to met1 |
| `met1` | 68/20 | metal 1 |
| `via` | 68/44 | met1 to met2 |
| `met2` | 69/20 | metal 2 |
| `via2` | 69/44 | met2 to met3 |
| `met3` | 70/20 | metal 3 |
| `via3` | 70/44 | met3 to met4 |
| `met4` | 71/20 | metal 4 |
| `via4` | 71/44 | met4 to met5 |
| `met5` | 72/20 | metal 5 |

Each routing layer is connected to itself, so touching shapes merge, and to the
via above it. `li1` has to be included: leaving it out disconnects every cell
from the routing, since cell pins are on li1 and nothing else reaches them.

Layers deliberately excluded: `poly`, `diff`, `licon1`, and the wells. Those are
inside the cells, and cells are being treated as black boxes with pins. Tracing
them would extract devices rather than a gate level netlist.

## Is the declared stack right?

Writing the stack out explicitly only helps if what is written is correct, and
"it looks correct" is not evidence. `tools/stack_sensitivity.py` measures it:
drop one routing layer, re-extract, and count how many nets change. Nets are
compared as sets of (placement, pin).

```
full stack: 86 nets carrying a cell pin
same stack extracted twice: identical, so the key is stable

dropped    nets  unchanged   broken
met5         86         86        0
met4        121         82        4
met3        111         75       11
met2        287          7       79
met1        529          4       82
li1          90          2       84
```

Damage grows monotonically downward, which is what a correct stack should do:
the lower layers sit closer to the cells and everything above routes over them.
A rising net count is the signature of a net being cut into pieces, not of extra
information — `met1` removed yields six times the nets.

Dropping `li1` breaks 84 of 86. The two survivors are `VPWR` and `VGND`, which
still reach cells over the met1 rails, and the pins that remain lose their names,
since the pin labels are on 67/5.

`met5` carries no signal connectivity in the warm up at all. That is a stack
wider than this layout needs, which is the safe direction to be wrong in: an
over-wide stack inspects a layer for nothing, an under-wide one silently cuts a
wire. The puzzle is a larger design and may use it.

The identity run matters as much as the table. The first version of this
measurement keyed nets on the extractor's own `subcircuit.id()`, which is
assigned per run and is not stable across two runs, so it reported 67 of 86 nets
as changed when nothing had changed. The tool now extracts the unmodified stack
twice and refuses to print anything if the two disagree.

## Net names

Text layers are attached so nets carry real names instead of `$1`, `$2`:

| Text layer | Attached to |
|---|---|
| 67/5 | `li1` |
| 68/5 | `met1` |
| 70/5 | `met3` |
| 71/5 | `met4` |
| 72/5 | `met5` |

This is what makes the extraction cheap. The cells keep their pin labels, so
`nand2_2` comes back with pins `A`, `B`, `Y`, `VPWR`, `VGND` and `dfrtp_2` with
`CLK`, `D`, `Q`, `RESET_B`. No LEF parsing and no geometric pin inference is
needed to know which shape is which pin.

## Hierarchy is kept

Extraction is hierarchical, not flat. Each standard cell becomes its own circuit
with named pins, so the top level netlist is already a graph over cell pins,
which is exactly what stage 3 wants. It is also much faster than flattening the
puzzle into a single sea of polygons.

A side effect worth noting: cell internal nets stay inside their own circuit.
`nand2_2` comes back with one unnamed internal net, which is the node between
its two series NMOS devices, exactly the node identified by hand in lesson 0 as
the li1 shape that reaches no rail and carries no pin.

## Mapping subcircuits back to stage 1

**Position alone is not a key.** A GDS origin is where the cell's own origin
landed, not its lower left corner, so a flipped cell extends left and down from
it. Two placements of different cells can therefore share an origin: the warm
up's 230 instances occupy only 178 distinct origins.

The symptom of getting this wrong was subtle. Net counts stayed correct, and net
`B` was reported as reaching a `dfrtp_2` pin `A1` — a pin `dfrtp_2` does not
have. The DEF says that net reaches a `mux2_1` pin `A1`.

The key is position **and** orientation together. The mapping now also asserts
that stage 1 and the extractor agree on the cell at each placement, which is a
free cross check on 230 and 1618 placements respectively.

## Verification

`tools/compare_def.py <target>` runs two gates against the warm up DEF.

**Components.** Every placement matched on position must agree on cell type and
orientation.

**Nets.** A netlist is a partition of cell pins into nets, so the gate is that
our partition equals the DEF's. Net names are not used for matching, because the
extractor only recovers a name where a label happens to sit on the geometry.
Two nets are the same net when they hold the same set of (instance, pin) pairs.

Instance names do not survive into the GDS, so our instance ids are bridged to
DEF instance names through position, using the placement list that the component
gate has already validated.

```
=== components ===
DEF declares 230, parsed 230; stage 1 gives 230
exact matches 230/230

=== nets ===
DEF declares 84 signal nets and 2 special nets
stage 2 gives 86 nets carrying a cell pin
signal nets matched exactly 84/84
  recovered nets with no DEF counterpart: 0
  DEF nets not recovered:                 0

  special (power) nets, DEF '*' expanded to every component:
    VGND: DEF expects 460 pins (230 on routing layers), stage 2 has 230
      missing 0, unexpected 0
      body ties not on the routing stack, expected to be absent: {'VNB': 230}
    VPWR: DEF expects 460 pins (230 on routing layers), stage 2 has 230
      missing 0, unexpected 0
      body ties not on the routing stack, expected to be absent: {'VPB': 230}

RESULT: clean match
```

Two details in that output.

Power nets in a DEF use `*` for the instance, meaning every component. Expanding
the wildcard is the difference between comparing two pins and comparing the 460
the net really holds.

`VNB` and `VPB` are body ties. They reach a cell through the wells, which are
not part of a routing stack, so an extractor walking upward from li1 will never
see them. Their absence is expected, and a gate level netlist does not carry
them either.

## Results

| | warm up | puzzle |
|---|---|---|
| Instances linked to stage 1 | 230 | 1618 |
| Nets carrying a cell pin | 86 | 725 |
| signal | 84 | 723 |
| power | 2 | 2 |
| named by a label | 8 | 15 |
| Nets with no cell pin | 3 | 3 |
| Max fanout | 16 | 88 |

The puzzle's signal count is one lower than the extractor first reported; see
the union find fallback below for the connection that was being lost.

The warm up's 8 named nets are its six ports plus the two rails. The puzzle's 15
are `clk`, `rst_n`, `enable`, `I`, `success`, `O[0]` through `O[7]`, and the two
rails, which is the full port list from the layout labels.

Nets with no cell pin at all are not netlist entries. In both targets all three
are the Jane Street emblem, drawn in met2 and connected to nothing. Measured
rather than eyeballed, and the two layouts carry the identical artwork:

| | warm up | puzzle |
|---|---|---|
| Top cell's own met2 shapes | 1366 | 1366 |
| Distinct shape sizes | 1, all 0.3 x 0.3 um | 1, all 0.3 x 0.3 um |
| Extent | 17.10 x 17.10 um | 17.10 x 17.10 um |
| Placed at | x 65.90, y 66.20 | x 34.90, y 35.20 |
| Die | 100 x 100 um | 200 x 353 um |

Uniform pixels confined to one small square are not routing: real wires vary in
size and span the die. Nothing in either layout's pin-less nets is unexplained.

Signal nets touching fewer than two cell pins are the primary ports, whose other
end is the die boundary rather than another cell. In the puzzle that set is the
eight `O` bits, `clk`, and one `conb_1` `HI` output that nothing consumes.

## Verilog emission

The layout says which pins are connected, not which one drives. Verilog needs
that, and guessing from names would mostly work in this library, `X`, `Y` and
`Q` being outputs. "Mostly" is how a netlist ends up structurally plausible and
functionally wrong, so directions come from the PDK's LEF abstract views
instead. `tools/fetch_pdk.py` now takes the 437 `.lef` files alongside the GDS,
same pinned commit; `tools/common/lef.py` parses them. All 437 macros parse with
no pin of unknown direction, and the `SIZE` they declare matches the footprints
measured off the GDS in stage 1.

One trap there. Filtering pins on `USE SIGNAL` looks right and is not: 69 pins
across the library are `USE CLOCK`, so that filter drops every flip-flop clock
connection, silently. The rule is to exclude supplies rather than to include
signals.

Ports are the named nets at the top level. Labels inside cells stay inside their
own circuit, so the only labels landing on top level nets are the ones on the
die's own pin geometry. A port's direction follows from what it reaches: if any
pin on the net is an output the die drives outward, otherwise every pin is
listening and the die is driven.

| | warm up | puzzle |
|---|---|---|
| Ports | 6 | 13 |
| Inputs | `A`, `B`, `clk`, `en`, `rst_n` | `I`, `clk`, `enable`, `rst_n` |
| Outputs | `S` | `success`, `O[7:0]` |
| Instances emitted | 79 | 738 |

The warm up port list and directions match `00_source.v` exactly. Bus bits are
regrouped, so the puzzle declares `output [7:0] O`.

Instance counts against the reference netlist, cell type by cell type: identical
on all 79 logic instances, no differences. Physical only cells are dropped,
having no functional pins; the reference netlist carries them with empty
connection lists.

The puzzle's 738 emitted instances are the 728 logic cells plus 10 `diode_2`
antenna diodes. Those exist to bleed charge during manufacturing and compute
nothing, but they really are attached to a net, so they are emitted rather than
hidden. Stage 3 should filter them by role.

Power pins are left off the instances. The sky130 models only expose them under
`USE_POWER_PINS`, and the warm up's own reference netlist omits them too.

## Simulation gates

Both pass. `tools/sim/run.py <target>` compiles the recovered netlist against
the PDK's own cell models inside the container and runs it.

**Warm up.** Every one of the 65536 operand pairs, not a sample, because an
extraction defect that only shows on one carry pattern would survive a spot
check and the whole run costs seconds.

```
pairs checked    65536
success asserted 15
mismatches       0
RESULT: pass
```

Fifteen is the right number: `a + b == 496` with both operands at most 255
needs `a` between 241 and 255.

**Puzzle.** `example_inputs.vcd` replayed against the recovered netlist. The
VCD records what was driven in *and* what came back, so this is a functional
check on the real target rather than a smoke test.

```
cycles replayed      312
cycles compared on O 312
mismatches           0
cycles with success  0
RESULT: pass
```

The recovered netlist reproduces the published waveform byte for byte, both
`TRY AGAIN` responses included, and never raises success on those inputs.

## Four traps on the way to a working simulation

Worth recording, because each one produced a wrong answer that looked like a
different problem.

**Docker BuildKit could not reach the network.** `apt-get` failed inside
`docker build` while the identical command succeeded under `docker run`. The
build works with `DOCKER_BUILDKIT=0`. The image is also split into a `sim`
target with only Icarus and an `eda` target adding Yosys and z3, so a flaky
link cannot cost the gates that are ready to run.

**Cell models default to the behavioural view.** Without `-DFUNCTIONAL` the
wrappers include the behavioural models, which carry specify blocks and timing
checks and hold `x` without a timing annotated run. Every output stayed `x` and
the netlist looked broken. It was not: running the *reference* netlist through
the same testbench failed identically, which is what identified the harness
rather than the extraction as the problem. `-DFUNCTIONAL -DUNIT_DELAY=#1` fixes
it.

**Bus bits were escaped instead of selected.** The emitter declared
`output [7:0] O` but wrote connections as `\O[0]`, which Verilog reads as a
scalar unrelated to the vector. The bus had nothing driving it and simulated as
`z`. A bit of a declared vector has to be written as a select.

**The expected output stream was one cycle early.** The VCD is a zero delay
dump and at a rising edge timestamp the output change is listed *before* the
clock change, so snapshotting on the edge already captures the output that edge
produced. Sampling the next snapshot instead, which reads as the intuitive
choice, shifted every byte and made the netlist look one cycle slow when the
byte sequence was already exactly right.

## The union find fallback

`tools/stage2_unionfind.py`, the second extractor the spec asks for: union find
over touching polygons per layer, merged across layers through via overlap.

It exists because on the puzzle there is no answer key. The DEF gate and the
warm up simulation both need ground truth; the only evidence available on the
real target is a second extraction, written against different assumptions, that
agrees. So it shares as little as possible with the primary path:

| | primary | fallback |
|---|---|---|
| Geometry library | klayout | gdstk |
| Structure | hierarchical, cells stay cells | flat, absolute coordinates |
| Connectivity | the extractor's own solver | own union find |
| Pin identity | resolved by the extractor | cell labels placed by hand |

Two measured facts about these layouts make an exact implementation cheap.
Every polygon on a conductor layer is rectilinear, so slicing it into rectangles
along its own vertex y coordinates is lossless; and every coordinate is on the
1 nm grid, so integer arithmetic is exact and no tolerance has to be invented.
The warm up's 10318 conductor polygons become 13970 rectangles, the puzzle's
73683 become 103450.

Bounding boxes would not do. Sixteen percent of the shapes are not rectangles,
reaching twenty vertices, and comparing boxes would connect shapes that never
touch, which is the "overly permissive connectivity rule" the spec warns about.

Within a layer, shapes sharing an edge of positive length are one conductor.
Contact at a single corner is not treated as a connection and is counted
separately rather than assumed either way: the warm up has 2056 of them.

## What the fallback found

On the warm up the two extractions agree exactly, 86 nets out of 86.

On the puzzle they did not, and the disagreement was a real defect in the
primary netlist.

**Symptom.** Net `$1415` held `nor3_2.C`, `and2_2.X` and a pin the extractor had
invented a name for, `a31oi_2.$7`. Separately, net `$1447` held `a31oi_2.A1` and
`a311o_2.A1` — two inputs and **no driver at all**.

**Cause.** A cell input is a transistor gate, and a gate can be contacted from
li1 in more than one place. `a31oi_2` has its A1 gate contacted twice: the LEF
declares one pad as the pin, at (1.955, 0.995)-(2.665, 1.615), and the other, at
(2.905, 0.995)-(3.075, 1.325), is not offered as a pin at all. The router landed
a via stack on the undeclared one.

Our connectivity starts at li1 and excludes poly, so the two pads look like two
unrelated nets. The signal that really drives those `A1` inputs sat in the other
net, and the netlist carried an undriven wire.

This is the "floating pins from an overly strict connectivity rule" failure
mode, and it is worth noting what did *not* catch it: the puzzle simulation
passed 312 cycles with zero mismatches both before and after the repair. One
input vector exercising the design is not a proof that its structure is right.

**The obvious fix, rejected.** Extending the ladder down through licon1 to poly
does repair this, and leaves the warm up bit for bit identical. It also
dissolves `conb_1`: that cell ties its constant outputs to the rails through
poly, so `LO` merges into `VGND` and `HI` into `VPWR`, and the extractor starts
reporting pins called `LO,VGND`. Measured, it moved 16 nets to fix one. A gate
level netlist needs `conb_1` to remain a cell with outputs.

**The fix taken.** `tools/common/cellnodes.py` reads from the PDK which li1
shapes of a cell are the same terminal — grouped through gate contacts only,
never through diffusion, since joining source and drain would conduct through
transistors — and matches each group against the LEF's declared PORT geometry.
The rule is narrow, and its guard is the important half:

> Two li1 shapes joined by a poly gate are the same terminal.
> Two **declared** pins of one cell are never the same net. If the grouping says
> they are, the model has reached inside the cell and the group is discarded.

That guard is what protects `conb_1`, and it only works with transitive
grouping and exact geometry. Both were wrong in the first version: grouping one
poly at a time missed chains through a shared li1 shape, and testing pin
membership by bounding box assigned `conb_1`'s L shaped ground shape to `HI`,
whose rectangle its box overlaps and its polygon does not. Either error hid the
conflict and would have let the repair rewrite a cell output into a rail.

Applied to the two targets:

| | warm up | puzzle |
|---|---|---|
| Cell types used | 18 | 69 |
| Cells with an undeclared pad | 0 | 1, `a31oi_2` for `A1` |
| Cells rejected by the guard | 0 | 1, `conb_1` (`LO/VGND`, `HI/VPWR`) |
| Connections reattached | 0 | 1 |
| Nets before, after | 86, 86 | 726, 725 |

The risk surface is much wider than the one occurrence: 66 of the cell types in
the puzzle have a device node reached by disjoint li1 shapes. Only one had
routing land on the undeclared side, but that is a property of this layout, not
a guarantee.

## The check that needs no answer key

The defect above left a net with two loads and nothing driving it. That is
detectable without any ground truth, and `stage2_nets.py` now does it: every
internal signal net must have exactly one pin driving it. None means a
connection was lost, more than one means two outputs are shorted.

Input ports are excluded — they are driven from outside the die, so having no
internal driver is exactly what they should look like.

```
warm up: driver check,  79 internal signal nets: 0 undriven with a load, 0 with two drivers
puzzle:  driver check, 719 internal signal nets: 0 undriven with a load, 0 with two drivers
```

Before the repair the puzzle reported one undriven net. This is the check that
would have found the defect without a second extractor, and it costs nothing.

## Remaining difference between the two extractors

On the puzzle the fallback lists 15 nets the primary does not, each a single
`clkbuf_4` `X` output. Those outputs have no `mcon` on them at all: they reach
no metal and drive nothing. Working flat, the fallback sees a component of one
pin; working hierarchically, the primary gives that pin no top level net and so
omits it. Both are saying the terminal is unconnected.

The comparison classifies this rather than counting it as a disagreement, and
only after confirming the pin is genuinely absent from the other netlist rather
than sitting in some other net.

## Still open

**The BuildKit failure is worked around, not understood.** `apt-get` cannot
reach the network inside `docker build` under BuildKit while the identical
command succeeds under `docker run`. Building with `DOCKER_BUILDKIT=0` produces
the same image and is what the documented commands use, but the cause was never
diagnosed.
