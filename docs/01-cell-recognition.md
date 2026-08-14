# Stage 1, cell recognition

Layout to `out/<target>/instances.json`. Every placement identified by geometry,
with the names that happen to have survived used only to check the answer.

## What was built

| Tool | Does |
|---|---|
| `tools/fetch_pdk.py` | downloads the sky130 cell GDS library, pinned to one commit |
| `tools/common/gds.py` | orientations, footprints, fingerprints, transistor counting |
| `tools/stage1_cells.py` | identifies every placement, writes the instance list |
| `tools/compare_def.py` | gate: checks the instance list against the warm up DEF |
| `tools/cell_signature.py` | exploratory, profiles cells and measures how well signatures separate them |

## Why geometry leads

The spec requires geometry as the primary path with hierarchy as a cross check,
and that ordering is not a formality. A stripped layout carries no names, so a
recogniser that reads them is not a reverse engineering tool. Here the names do
survive, which makes this the right place to prove the geometric path works: its
answer can be checked against them, on every one of 1848 placements across the
two targets, and it agrees everywhere.

## Reference library

`tools/fetch_pdk.py` pulls 437 cell GDS files, about 4 MB, from
`google/skywater-pdk-libs-sky130_fd_sc_hd` pinned at `ac7fb61f`. Pinned rather
than tracked: an unpinned fetch would silently change what the pipeline
recognises if upstream ever redraws a cell.

## Two conventions that have to be reconciled

**Orientation.** Standard cells sit in rows, and alternate rows are flipped
vertically so neighbours can share a power rail. GDS records this as "mirror
about the x axis, then rotate", DEF as a name.

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

These eight form a group, so they compose, and stage 1 needs that. Fingerprints
are indexed under all eight orientations, so a definition drawn rotated relative
to the library original still resolves and reports which orientation it is in.
The orientation of a *placement* of it is then the composition of the two.
`common/gds.py` composes by 2x2 integer matrix multiplication rather than a case
table, because a hand written case table for a group of order eight is a
reliable source of quiet bugs.

Only `N`, `S`, `FN` and `FS` appear in these layouts, as expected: cells in rows
are flipped, never rotated by 90 degrees.

**Placement point.** GDS stores where the cell's own origin landed, DEF the
lower left corner of the placed cell. For `N` these coincide, for a flipped
placement they do not. The footprint comes from `areaid.sc` (81/4), which every
standard cell carries, and its corners are transformed to produce a comparable
lower left.

## Matching, and the PDK revision drift

Exact geometry matching worked for every cell in the warm up and for 1596 of
1618 placements in the puzzle. Three cell types missed:

| Cell | Placements | Layers that differ from the fetched PDK |
|---|---|---|
| `o211a_2` | 12 | `poly`, `licon1` |
| `conb_1` | 6 | `npc` |
| `and4b_2` | 4 | `poly` |

The revision that drew the puzzle is not exactly the one we fetch. The drift is
small and looks like DRC fixes: `o211a_2` carries one more poly polygon in the
puzzle than in the library, the other two differ only in coordinates. On every
one of them `nwell`, `diff`, `li1`, `mcon`, the implants and the pin layers came
through unchanged.

So stage 1 matches in two tiers and records which one answered.

**Tier 1, exact.** Hash of every polygon, translated to the origin, coordinates
snapped to the 1 nm database grid, indexed under all eight orientations.

**Tier 2, structural.** Hash restricted to `nwell`, `diff`, `li1` and `mcon`,
plus the set of pin names and the transistor count.

The layer choice is doing real work. Dropping `poly` loses the gate shapes, but
`diff` together with `li1` still encodes which devices are in series and which
in parallel, which is what separates a gate from its dual. Measured over the
whole library, that hash alone leaves 427 of 437 cells uniquely identified; the
ten remaining ties are all `lpflow_*` isolation cells drawn identically to a
plain logic gate, for instance `and2_1` against `lpflow_inputiso0n_1`. Adding
pin names and transistor count separates every one of them, leaving no ambiguous
fingerprint in the library at all.

An ambiguous fingerprint is never resolved arbitrarily. Keys that would land on
more than one library cell are dropped from the index, because a fingerprint
that matches two cells is not an identification.

## Results

| | warm up | puzzle |
|---|---|---|
| Placements | 1099 | 9875 |
| Identified | 230 | 1618 |
| by exact geometry | 230 | 1596 |
| by structural fallback | 0 | 22 |
| Logic cells | 79 | 728 |
| Physical only | 151 | 890 |
| Unmatched | 869 | 8257 |
| Hierarchy name disagreements | 0 | 0 |

Unmatched placements are logged with their bounding box rather than dropped. All
of them are accounted for: `VIA_*` routing constructs, which DEF carries in its
net sections rather than as components, and in the puzzle the 36 `INTERNAL_3`
and `INTERNAL_7` marker rectangles on layer 200/0, which hold no devices.

## Verification gate

```
python tools/stage1_cells.py warmup
python tools/compare_def.py warmup
```

```
DEF declares 230 components, parsed 230
stage 1 gives 230 instances

exact matches      230/230  (100.00%)
wrong cell type    0
wrong orientation  0
in DEF, not in GDS 0
in GDS, not in DEF 0

RESULT: clean match
```

Cell type, position and orientation together. Counts alone would not do:
swapping two cells or shifting everything by a fixed offset both leave the
counts intact.

## The result that matters most

An exact digest separates every cell in the library. The coarse profile that you
could read off a picture, footprint plus transistor count, does not:

```
66 cells with transistors fall into 22 profiles
53 of them are NOT separated by profile alone
```

`nand2_2`, `nor2_2` and `or2_2` are all 2.30 x 2.72 um with 8 transistors. NAND
and NOR are duals, so they cost exactly the same; which one you have depends on
which devices are in series and which in parallel, and that is wiring.

> Footprint and transistor count say what a cell costs, not what it does.
> Function lives in the connections.

This is the argument for stage 2, and it is also why the tier 2 fallback keeps
`li1`: the wiring layer is the part that carries identity.

## Notes

Sequential elements in the puzzle: 84 `dfrtp_2`, 4 `dfstp_2`, 4 `dfxtp_2`, so 92
bits of state. `dfstp` has an active low *set* rather than reset, so some
register leaves reset holding a non zero value.

Correction to `docs/00-environment.md`, which reports 722 logic cells: that
counted the six `conb_1` instances as physical. `conb_1` generates constants and
its outputs drive real nets, so it is logic and the figure is 728.

The harder version of this problem does not arise here. Both layouts keep their
cell hierarchy, so each cell is a separate definition whose geometry can be
hashed once and reused across all its placements. A fully flattened layout would
require finding library patterns inside one undifferentiated sea of polygons,
which is a different and much harder matching problem.
