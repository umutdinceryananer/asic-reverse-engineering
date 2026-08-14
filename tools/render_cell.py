"""Render one cell from a GDS file to SVG, optionally only selected layers.

Looking at a standard cell one layer group at a time is the fastest way to see
what the geometry means. Rendering the device layers alone (nwell, diff, poly)
shows the transistors; adding the interconnect layers on top shows how they are
wired into a gate.

Usage:
    python tools/render_cell.py puzzle/puzzle.gds sky130_fd_sc_hd__inv_2 out.svg
    python tools/render_cell.py puzzle/puzzle.gds sky130_fd_sc_hd__inv_2 dev.svg --layers device
    python tools/render_cell.py puzzle/puzzle.gds --list
"""

import sys

import gdstk

# (layer, datatype) -> (readable name, fill colour)
STYLE = {
    (64, 20): ("nwell", "#d9d2e9"),
    (65, 20): ("diff", "#00a000"),
    (65, 44): ("tap", "#006000"),
    (66, 20): ("poly", "#d00000"),
    (66, 44): ("licon1", "#000000"),
    (67, 20): ("li1", "#8000c0"),
    (67, 44): ("mcon", "#000000"),
    (68, 20): ("met1", "#0060d0"),
    (68, 44): ("via", "#000000"),
    (69, 20): ("met2", "#e000a0"),
    (69, 44): ("via2", "#000000"),
    (70, 20): ("met3", "#00b0b0"),
    (71, 20): ("met4", "#b08000"),
    (72, 20): ("met5", "#808080"),
    (93, 44): ("nsdm", "#ffd0d0"),
    (94, 20): ("psdm", "#d0d0ff"),
    (95, 20): ("npc", "#a0a000"),
    (78, 44): ("hvtp", "#ffe0b0"),
    (81, 4): ("areaid.sc", "#cccccc"),
    (235, 4): ("prBndry", "#404040"),
    (200, 0): ("marker", "#ff8000"),
}

GROUPS = {
    # What physically makes a transistor.
    "device": {(64, 20), (65, 20), (65, 44), (66, 20)},
    # How the transistors get wired together.
    "interconnect": {(66, 44), (67, 20), (67, 44), (68, 20), (68, 44), (69, 20)},
    # Implant and marker layers, no geometry you can point at in a photo.
    "implant": {(93, 44), (94, 20), (95, 20), (78, 44), (81, 4), (235, 4)},
}


def svg_style(keys):
    style = {}
    for key in keys:
        _, colour = STYLE.get(key, ("?", "#999999"))
        style[key] = {
            "fill": colour,
            "stroke": colour,
            "stroke-width": "0.01",
            "fill-opacity": "0.55",
        }
    return style


def render(gds_path, cell_name, out_path, group=None):
    library = gdstk.read_gds(gds_path)
    cells = {c.name: c for c in library.cells}
    if cell_name not in cells:
        sys.exit(f"cell {cell_name!r} not in {gds_path}")
    source = cells[cell_name]

    wanted = GROUPS.get(group) if group else None
    if group and wanted is None:
        sys.exit(f"unknown layer group {group!r}, pick from {sorted(GROUPS)}")

    target = gdstk.Cell(cell_name.replace("__", "_") + ("_" + group if group else ""))
    present = {}
    for polygon in source.polygons:
        key = (polygon.layer, polygon.datatype)
        if wanted is not None and key not in wanted:
            continue
        target.add(polygon.copy())
        present[key] = present.get(key, 0) + 1

    if not present:
        sys.exit(f"no geometry left after filtering {cell_name!r} to group {group!r}")

    (x0, y0), (x1, y1) = source.bounding_box()
    print(f"cell    {cell_name}")
    print(f"extent  {x1 - x0:.3f} x {y1 - y0:.3f} um")
    print(f"filter  {group or 'all layers'}")
    print("layers drawn:")
    for key in sorted(present):
        name, _ = STYLE.get(key, ("unmapped", ""))
        print(f"  {key[0]:>3}/{key[1]:<3} {name:<10} {present[key]:>3} shapes")

    target.write_svg(out_path, scaling=100, shape_style=svg_style(present),
                     background="#ffffff", pad=8)
    print(f"\nwrote {out_path}")


def list_cells(gds_path):
    library = gdstk.read_gds(gds_path)
    for cell in sorted(library.cells, key=lambda c: c.name):
        (x0, y0), (x1, y1) = cell.bounding_box()
        print(f"  {cell.name:<45} {x1 - x0:7.3f} x {y1 - y0:6.3f} um  "
              f"{len(cell.polygons):>4} polygons")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[1] == "--list":
        list_cells(args[0])
    elif len(args) >= 3:
        group = None
        if "--layers" in args:
            group = args[args.index("--layers") + 1]
        render(args[0], args[1], args[2], group)
    else:
        sys.exit(__doc__)
