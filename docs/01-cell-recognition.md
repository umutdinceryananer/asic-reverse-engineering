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


## The 22 fallbacks have a testable cause, and the machinery to test it

`docs/references.md` §3 puts a name to the drift. `tools/fetch_pdk.py` pulls the
upstream *library* repository, `google/skywater-pdk-libs-sky130_fd_sc_hd`. Every
manufactured sky130 flow — this puzzle's included, presumably — consumes
**`sky130A` as built by open_pdks**, which re-renders cell layouts through Magic
on the way through. That is exactly the class of difference that shows on poly,
licon1 and npc while leaving metal intact, which is what the table above records.

**Tested library against library, without opening a puzzle file.**
`tools/fetch_open_pdks.py` fetches the open_pdks build of the same library into
`pdk/open_pdks_sky130A/`, a separate cache that stage 1's glob cannot see, and
`tools/compare_libraries.py` compares the two cell by cell on the nanometre grid.
**9 of 437 shared cells differ:**

```
  a2111o_1          122/16 pwell pin (2->2)
  a2111oi_0          66/20 poly (5->5)
  and2_0             95/20 npc (1->1)
  and4b_2            66/20 poly (6->6)          <- one of the puzzle's three
  buf_16             66/20 poly (2->2)
  clkdlybuf4s15_1    66/20 poly (4->4), 66/44 licon1 (24->24)
  clkdlybuf4s18_1    66/20 poly (4->4)
  conb_1             95/20 npc (2->2)           <- one of the puzzle's three
  o211a_2            66/20 poly (5->6), 66/44 licon1 (27->27)   <- and the third
```

All three cell types the puzzle falls back on are in that list, **on exactly the
layers this document already records for them** — `o211a_2` on poly and licon1,
`conb_1` on npc, `and4b_2` on poly — and `o211a_2` gains the one extra poly
polygon this document says the puzzle's copy carries. Eight of the nine
differences are confined to poly, licon1 and npc; the ninth, `a2111o_1`, moves on
`122/16 pwell pin`, which is outside that signature and is reported as such
rather than rounded into it.

**The warm up cannot test this and is not expected to.** It places 230 cells,
none of them among the nine, so stage 1 answers `exact 230, structural 0` under
*both* libraries and no definition changes tier. That is the check that the
second library does not break what works — not evidence for the hypothesis.

### What the author runs, and what each outcome means

One command, on the target the assistant does not touch:

```bash
python tools/fetch_open_pdks.py                                   # once
python tools/stage1_cells.py puzzle --library pdk/open_pdks_sky130A
```

It prints the tiers side by side against the standard library and names every
definition that changed tier. It writes `instances.open_pdks_sky130A.json`, never
`instances.json`, so the committed pipeline's numbers stay reproducible.

| Outcome | What it means |
|---|---|
| structural **22 → 0** | The puzzle was drawn against an open_pdks-built sky130A. The fallback tier stops being a workaround and becomes a measured safety net — it recovered exactly the cells a library mismatch cost, and the mismatch is now identified. |
| **unchanged, 22 → 22** | The hypothesis is dead. open_pdks is not what moved those cells, and the 9-cell list above is a real but unrelated difference. Look elsewhere: a different open_pdks revision, or a vendor library. |
| **partial**, 22 → n | The number is the answer. `22 - n` placements are explained by open_pdks and `n` are not, and the per-definition list says which cells are still unaccounted for. |

**What no outcome establishes.** Stage 1's exact digest hashes every layer, so
`22 → 0` would show that this library is the one that drew the target, not that
the difference was poly, licon1 and npc specifically. Only
`compare_libraries.py` speaks to the second, and it is a statement about two
libraries rather than about the puzzle.

**The pin, and a correction to the guess in `docs/references.md`.** That file
suggests open_pdks `e6f9c887`, the revision a cited tapeout used. A build at
that revision is published and its `o211a_2`, `conb_1` and `and4b_2` are
byte-identical to the upstream library — pinning there would have changed
nothing. The geometry changes between the published builds `823ec23c`
(2025-05-24, still identical) and **`8afc8346` (2025-07-14, differs)**, which is
what `fetch_open_pdks.py` pins: the earliest published build carrying it.

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
