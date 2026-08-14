# Phase 1, cell recognition

Mapping every placement in a layout to a library cell, by name and again by
geometry, and checking both against the answer key that ships with the warm up.

## What was built

| Tool | Does |
|---|---|
| `tools/extract_cells.py` | walks the top cell, emits every placement with cell type, position and orientation |
| `tools/compare_def.py` | checks that instance list against `03_post_place_and_route.def` |
| `tools/cell_signature.py` | identifies cells from geometry alone, and measures how well that works |

## Two conventions that have to be reconciled

**Orientation.** Standard cells sit in rows, and alternate rows are flipped
vertically so neighbours can share a power rail. GDS records this as "mirror
about the x axis, then rotate", DEF as a name. Working the transforms through:

| GDS mirror | GDS rotation | DEF | Point map |
|---|---|---|---|
| no | 0 | `N` | (x, y) |
| no | 90 | `W` | (-y, x) |
| no | 180 | `S` | (-x, -y) |
| no | 270 | `E` | (y, -x) |
| yes | 0 | `FS` | (x, -y) |
| yes | 90 | `FW` | (y, x) |
| yes | 180 | `FN` | (-x, y) |
| yes | 270 | `FE` | (-y, -x) |

Only `N`, `S`, `FN` and `FS` appear in these layouts, which is expected: cells
in rows are never rotated by 90 degrees, only flipped.

**Placement point.** GDS stores where the cell's own origin landed. DEF stores
the lower left corner of the placed cell. For `N` these coincide; for a flipped
placement they do not. The footprint is read from the `areaid.sc` layer (81/4),
which every standard cell carries, and its corners are transformed to produce a
comparable lower left. Every cell in both files has this layer, so no placement
needed a fallback.

## Verification against the DEF

The warm up DEF names every instance with its cell type, position and
orientation, which makes it a per instance answer key rather than a per count
one. Matching is done on position, since instance names do not survive into the
GDS.

```
DEF declares 230 components, parsed 230
GDS yields  230 components

exact matches      230/230  (100.00%)
wrong cell type    0
wrong orientation  0
in DEF, not in GDS 0
in GDS, not in DEF 0
```

The Phase 1 exit criterion is met. Note what the 230 excludes: the GDS holds
1099 placements, of which 869 are `VIA_*` cells. Those are routing vias, which
DEF carries in its net sections rather than as components. Separating them is
the first thing the extractor does.

## Recognition without names

Reading the name off the reference is only available because these files kept
their names. The name independent path uses two signatures.

**Profile**, the countable version of what you could see in a picture:
footprint, transistor count, PMOS and NMOS split, contact count. Transistors are
counted directly from the rule that poly crossing diff *is* a transistor, by
intersecting the two layers and counting the resulting pieces. Intersecting
those pieces with `nwell` separates PMOS from NMOS.

Sanity checks on the counts:

| Cell | Transistors | Reading |
|---|---|---|
| `nand2_2` | 8 (4P, 4N) | matches the hand analysis in lesson 0 |
| `nor2_2` | 8 (4P, 4N) | dual of NAND, same cost |
| `dfrtp_2` | 30 | a flip flop is expensive |
| `clkbuf_16` | 40 (20P, 20N) | drive 16, many fingers on two poly shapes |
| `tapvpwrvgnd_1` | 0 | a well tap holds no devices |
| `VIA_*` | 0 | routing only |
| `INTERNAL_3`, `INTERNAL_7` | 0 | independent confirmation that the marker cells carry no circuit |

**Digest**, a hash of every polygon after translating the cell so its lower left
sits at the origin, with coordinates snapped to the database grid. Cell
definitions are never rotated, only their placements are, so no rotation
invariance is needed here.

Cross file test, using the warm up as the reference library and asking it to
name the cells in the puzzle:

```
identified 26, unidentified 54
```

All 26 shared cells resolved to the correct name, none wrongly. The 54 misses
are cell types the warm up never uses; naming those needs the sky130 library
GDS as the reference, which is not required here because the puzzle kept its
names.

## The result that matters most

The digest separates every cell. The coarse profile does not, and not by a
small margin:

```
66 cells with transistors fall into 22 profiles
53 of them are NOT separated by profile alone
```

The clearest case is the first one: `nand2_2`, `nor2_2` and `or2_2` are all
2.30 x 2.72 um with 8 transistors. NAND and NOR are duals of each other, so
they cost exactly the same; which one you get depends on which devices are in
series and which in parallel, and that is wiring, not geometry counts.

> Footprint and transistor count tell you what a cell costs, not what it does.
> Function lives in the connections.

This is the argument for Phase 2. No amount of refinement to cell level
measurement recovers the circuit, because at cell level the information is
genuinely absent.

## Puzzle instance list

```
placements 9875
  logic     728
  physical  890
  via      8221
  other      36     the layer 200/0 marker row
```

Written to `out/puzzle_cells.json`.

Correction to an earlier count: `docs/00-environment.md` reports 722 logic
cells. That treated the six `conb_1` instances as physical. `conb_1` is a
constant generator whose outputs drive real nets, so it belongs to the logic
group and the figure is 728.

Sequential elements, unchanged: 84 `dfrtp_2`, 4 `dfstp_2`, 4 `dfxtp_2`, so 92
bits of state.

## What is not done

The 54 puzzle cell types absent from the warm up are identified by name, not by
geometry. Closing that would mean pulling in the sky130 standard cell GDS and
digesting it as a reference library. Worth doing if the names are ever in
doubt; not on the critical path while they are present and self consistent.

The harder version of this problem does not arise here. Both layouts keep their
cell hierarchy, so each cell is a separate definition whose geometry can be
hashed. A fully flattened layout would need the library patterns to be found
inside one undifferentiated sea of polygons, which is a different and much
harder matching problem.
