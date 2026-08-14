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
| Nets carrying a cell pin | 86 | 726 |
| signal | 84 | 724 |
| power | 2 | 2 |
| named by a label | 8 | 15 |
| Nets with no cell pin | 3 | 3 |
| Max fanout | 16 | 88 |

The warm up's 8 named nets are its six ports plus the two rails. The puzzle's 15
are `clk`, `rst_n`, `enable`, `I`, `success`, `O[0]` through `O[7]`, and the two
rails, which is the full port list from the layout labels.

Nets with no cell pin at all are not netlist entries. In the warm up all three
are the Jane Street logo, drawn in met2 and connected to nothing; it accounts
for 1366 of the layout's met2 shapes. The puzzle also has three, not yet
examined.

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

## Not done yet

- The simulation gate: the recovered warm up netlist raising success exactly
  when the two shift register operands sum to 496. That needs Icarus, so it
  waits on the stage 3 Docker image.
- The puzzle gate: driving the recovered puzzle netlist with
  `example_inputs.vcd` and requiring `TRY AGAIN` on `O` with `success` low.
- The union find fallback the spec asks for, in case the extractor misbehaves.
  It has not been needed; the per net gate passes exactly.
