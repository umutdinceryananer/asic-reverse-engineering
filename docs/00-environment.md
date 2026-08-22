# Phase 0, environment and first survey

Toolchain, PDK identity, layer semantics, and what the two supplied layouts
actually contain.

## Upstream files

`puzzle/` is a git submodule pinned to `janestreet/asic-puzzle-2026`. It is
upstream and read only. Clone this repository with `--recursive`, or run
`git submodule update --init` in an existing clone.

| File | What it is |
|---|---|
| `puzzle/puzzle.gds` | The real layout. 200 x 352.72 um. |
| `puzzle/example_inputs.vcd` | Input waveforms only. Explicitly *not* the inputs that raise `success`, and carries no expected outputs. |
| `puzzle/layout.png` | Annotated floorplan showing port positions and the "output generator" region. |
| `puzzle/warmup/00_source.v` | Verilog source of the calibration design. |
| `puzzle/warmup/01_netlist.v` | Synthesized gate level netlist. |
| `puzzle/warmup/02_netlist_with_power_rails.v` | Same, with VPWR and VGND added. |
| `puzzle/warmup/03_post_place_and_route.def` | Placement and routing with cell *and* net names preserved. |
| `puzzle/warmup/04_final.gds` | Final layout, internal names stripped. |

The DEF file is the most useful calibration asset in the set. It names every
cell instance and every net at the same coordinates the GDS uses, so extraction
can be checked instance by instance and net by net rather than only through
simulation. A functional mismatch tells you the netlist is wrong; the DEF tells
you *which* net is wrong.

## Toolchain

Python is the whole environment so far. `gdstk` and `klayout` both publish
wheels for Windows, Linux and macOS, so one `requirements.txt` reproduces the
setup on every machine.

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt           # Linux, macOS
```

| Component | Version | Purpose |
|---|---|---|
| Python | 3.14.3 | host |
| gdstk | 1.0.1 | GDS reading, geometry queries |
| klayout (module) | 0.30.10 | headless scripting API, LVS netlist extractor |
| numpy | 2.5.2 | pulled in by gdstk |

Still to install, when the relevant phase needs them:

| Component | Needed for | Note |
|---|---|---|
| KLayout GUI | visual layer inspection | native install per machine, not the pip module |
| Yosys, Icarus Verilog | synthesis and simulation | Linux stack, plan is a Docker image |
| Magic VLSI | independent second extraction | Linux only, see the verification note below |

## PDK

`sky130_fd_sc_hd`, the SkyWater 130 nm high density standard cell library. Read
directly off the cell names in both GDS files, no inference required. Both the
warm up and the puzzle use it, so tooling calibrated on one transfers to the
other.

Geometry constants that follow from the library and are worth having on hand:

- Standard cell row height 2.720 um
- Placement site width 0.460 um, so every cell width is a multiple of it
- Database unit 1 nm, user unit 1 um

## Layer map

Taken from the SkyWater PDK `gds_layers.csv`. Only the pairs that actually carry
geometry in these two files are listed.

| Layer/DT | Name | What it carries |
|---|---|---|
| 64/20 | nwell | N-well region, the tub the PMOS devices sit in |
| 64/16, 64/5 | nwell | pin, label |
| 64/59 | pwell | label |
| 65/20 | diff | active area, source and drain of a transistor |
| 65/44 | tap | active area tied to the surrounding well, for body contacts |
| 66/20 | poly | polysilicon; where it crosses `diff` it forms a transistor gate |
| 66/44 | licon1 | contact from diff or poly up to local interconnect |
| 67/20 | li1 | local interconnect, the first routing layer |
| 67/16, 67/5 | li1 | pin, label |
| 67/44 | mcon | contact from li1 up to met1 |
| 68/20 | met1 | metal 1 |
| 68/16, 68/5 | met1 | pin, label |
| 68/44 | via | met1 to met2 |
| 69/20 | met2 | metal 2 |
| 69/44 | via2 | met2 to met3 |
| 70/20 | met3 | metal 3 |
| 70/16, 70/5 | met3 | pin, label |
| 70/44 | via3 | met3 to met4 |
| 71/20 | met4 | metal 4 |
| 71/16, 71/5 | met4 | pin, label |
| 71/44 | via4 | met4 to met5 |
| 72/20 | met5 | metal 5 |
| 72/16, 72/5 | met5 | pin, label |
| 78/44 | hvtp | high threshold PMOS implant marker |
| 81/4 | areaid.sc | standard cell identifier marker |
| 83/44 | text | cell identity label, e.g. `dfxtp_2` |
| 93/44 | nsdm | N+ source/drain implant |
| 94/20 | psdm | P+ source/drain implant |
| 95/20 | npc | nitride poly cut, under licon1 |
| 122/16 | pwell | pin |
| 235/4 | prBndry | place and route boundary |
| 236/0 | not in the PDK table | present inside standard cells, unmapped |
| 200/0 | not a PDK layer | custom, used only by the marker row, see below |

## What is pinned, and what is only recorded

The distinction matters more than the pins do. A version somebody wrote in prose
is not a pin — `docs/references.md` §3 supplies the six-year-old counterexample,
a project whose SHA-pinned submodules still resolve while its prose-pinned Vivado
version is unbuildable.

| | How | Where |
|---|---|---|
| the cell library | **pinned**, by commit | `tools/fetch_pdk.py` `COMMIT` |
| the liberty corner | **pinned**, by name | `tools/fetch_pdk.py` `CORNER` |
| the open_pdks library | **pinned**, by open_pdks commit | `tools/fetch_open_pdks.py` `OPEN_PDKS` |
| the container base image | **pinned**, by digest | `docker/Dockerfile` |
| `yosys`, `z3`, `iverilog` | **recorded, floating** | `tools/TOOL_VERSIONS.recorded` |

**The apt packages are deliberately not pinned.** Pinning them by apt version
breaks the moment Debian moves a point release out of the archive; building them
from source is hours and a second toolchain to maintain. So each image records
its own tool versions at build time into `/opt/gds-teardown/TOOL_VERSIONS`, and
`tools/verify_toolchain.py` compares that manifest against the copy checked in
here. **The gate catching the drift is the mechanism.** The versions may move;
they cannot move silently, and a rebuild that changes one fails until somebody
re-records it with `--record`, which is a decision rather than a side effect.

What is recorded today:

```
base      debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241
debian    12.15
iverilog  Icarus Verilog version 11.0 (stable) ()
yosys     Yosys 0.23 (git sha1 7ce5011c24b)
z3        Z3 version 4.8.12 - 64 bit
```

`verify_toolchain.py <target>` also stamps `out/<target>/TOOL_VERSIONS` beside
that run's artifacts, so a `graph.json` or a `solution.json` can be traced to the
toolchain that produced it.

**The gap, stated rather than left to be found.** The container tools do not
stamp their own artifacts; the stamp happens when `verify_toolchain.py` is run
with a target, and the review packet runs it. A stage 6 run performed by hand
leaves a `solution.json` with no manifest beside it. Closing that means editing
`sim/run.py`, `sim/replay.py`, `verify_equiv.py`, `stage6_invert.py` and
`verify_functions.py`, which no package has yet admitted.

The stack in order, bottom to top: `diff`/`poly` form devices, `licon1` lifts
them to `li1`, `mcon` lifts `li1` to `met1`, then `via`, `via2`, `via3`, `via4`
climb through `met2` to `met5`. Connectivity extraction is a traversal of
exactly this ladder.

Two of these mappings are corroborated by the files themselves rather than only
by the table: pin names such as `A`, `B`, `Y`, `CLK`, `D`, `Q` appear as labels
on 67/5, and the top level port names appear on 70/5, which is consistent with
`li1.label` and `met3.label`.

## What the two layouts contain

| | warm up | puzzle |
|---|---|---|
| Top cell | `adder_demo` | `puzzle` |
| Extent | 100 x 100 um | 200 x 352.72 um |
| Placements | 1099 | 9875 |
| Distinct cells | 26 | 80 |
| Logic cells | ~90 | 722 |
| Physical only cells | ~150 | 896 |
| Via cells | ~850 | 8221 |
| Sequential elements | 16 `dfrtp_2` | 84 `dfrtp_2`, 4 `dfstp_2`, 4 `dfxtp_2` |

Both are flat: only the top cell contains references, everything below it is a
leaf. There is no module hierarchy to exploit in either file.

The warm up cell counts confirm the source exactly. Two 8 bit shift registers
give 16 flip flops, and the 16 `mux2_1` instances are the `else if (en)`
branch, synthesized as a mux on each flip flop's D input rather than as a clock
enable.

The puzzle has 92 sequential elements, so 92 bits of state. The three flip flop
flavours matter: `dfrtp` has an active low reset, `dfstp` an active low *set*,
and `dfxtp` neither. A register that comes out of reset non-zero is built from
the `dfstp` cells, which is worth remembering when the reset state turns out not
to be all zeroes.

## Puzzle ports

Read from the labels on the top cell, layers 70/5, 71/5 and 72/5.

| Port | Side | Note |
|---|---|---|
| `clk` | left | |
| `rst_n` | left | active low, "toggle it before each input attempt" per the announcement |
| `enable` | left | |
| `I` | left | single bit, so input arrives serially |
| `success` | right | the goal signal |
| `O[0]` .. `O[7]` | right | 8 bits, so the answer string comes out a byte at a time |
| `VPWR`, `VGND` | met4, met5 | power |

`layout.png` labels these `input` and `out[n]`; the GDS labels are `I` and
`O[n]`.

## The marker row

36 rectangles sit in a single row at y = -52.72 um, below the core area, on
layer 200/0. They contain no `diff` and no `poly`, so they cannot be circuit
elements. They come in two widths, 1.380 and 4.140 um, an exact 1:3 ratio, and
the gaps between them are 1, 3 or 7 times the smaller width.

That is International Morse timing. `tools/decode_marker_row.py` decodes it:

```
PER ARENAM AD ASTRA
```

"Through sand to the stars", a play on *per aspera ad astra*, sand being what
silicon is made from. The announcement mentions easter eggs hidden in the
circuit and the repository; this is one of them. It has no bearing on the
function of the design.

## Corrections to the working plan

Four statements in `jane-street-asic-roadmap.md` are contradicted by the files.

1. **The warm up is sequential, not combinational.** The Risks section assumes it
   "will not exercise sequential extraction". It contains 16 flip flops. This is
   good news: the calibration circuit does cover sequential extraction.

2. **There are no published output vectors.** Phase 3 verification asks the
   recovered netlist to "reproduce every published sample pair". `example_inputs.vcd`
   holds inputs only, and the README says outright they are not the inputs that
   raise `success`. That exit criterion cannot be met as written.

3. **The DEF file is unused by the plan.** It is a stronger and faster ground
   truth than simulation for Phases 1 and 2. See the table above.

4. **Magic is listed as optional.** Because of point 2 there is no functional
   ground truth for the puzzle extraction, which makes an independent second
   extractor the main cross check rather than a nicety.

Replacement verification strategy for the puzzle netlist, since point 2 removes
the intended one:

- Warm up equivalence, against the DEF instance and net lists and against
  simulation of the known source. This is the real evidence that the flow is
  correct, because the puzzle went through the same flow.
- Agreement between two independent extractors, KLayout LVS and Magic.
- Structural consistency: no floating nets, no multiply driven nets, every flip
  flop clock pin reached by the clock tree, port count matching the label set
  above.
