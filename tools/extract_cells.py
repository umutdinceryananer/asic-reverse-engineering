"""Extract the cell instance list from a layout.

Walks the top cell of a GDS file and reports every placement: which library
cell, where, and in what orientation. This is the first half of recovering a
netlist -- it tells you *what* the circuit is built from, but not yet how the
pieces are wired.

Two things need care.

Orientation. Cells are placed in rows, and every other row is flipped upside
down so that neighbouring rows can share a power rail. GDS stores that as
"mirror about the x axis, then rotate", while DEF and LEF use names like N, FS,
FN and S. Getting the mapping wrong shifts everything downstream, so the two
conventions are reconciled here once.

Placement point. GDS records where the cell's own origin landed. DEF records
the lower left corner of the placed cell. For an unflipped cell these are the
same point, for a flipped one they are not. The cell footprint is read off the
`areaid.sc` layer (81/4), which every standard cell carries, and the corners are
transformed to get a comparable lower left.

Usage:
    python tools/extract_cells.py puzzle/warmup/04_final.gds
    python tools/extract_cells.py puzzle/puzzle.gds --json out/puzzle_cells.json
"""

import json
import math
import sys
from collections import Counter

import gdstk

AREAID_SC = (81, 4)

# (mirrored about x axis, rotation in degrees) -> DEF/LEF orientation name.
#
# GDS applies the mirror first and the rotation second. Working the two
# transforms through by hand gives the mapping below; for example mirror then
# rotate 180 sends (x, y) to (-x, y), which is a mirror about the y axis, and
# that is what DEF calls FN.
ORIENTATION = {
    (False, 0): "N",
    (False, 90): "W",
    (False, 180): "S",
    (False, 270): "E",
    (True, 0): "FS",
    (True, 90): "FW",
    (True, 180): "FN",
    (True, 270): "FE",
}


def transform(x, y, rotation, mirrored):
    """Apply a GDS placement transform to a point, mirror first then rotate."""
    if mirrored:
        y = -y
    if rotation == 90:
        x, y = -y, x
    elif rotation == 180:
        x, y = -x, -y
    elif rotation == 270:
        x, y = y, -x
    return x, y


def footprints(library):
    """Cell name -> (x0, y0, x1, y1) of its areaid.sc rectangle."""
    result = {}
    for cell in library.cells:
        boxes = [p.bounding_box() for p in cell.polygons
                 if (p.layer, p.datatype) == AREAID_SC]
        if not boxes:
            continue
        x0 = min(b[0][0] for b in boxes)
        y0 = min(b[0][1] for b in boxes)
        x1 = max(b[1][0] for b in boxes)
        y1 = max(b[1][1] for b in boxes)
        result[cell.name] = (x0, y0, x1, y1)
    return result


def placed_lower_left(box, origin, rotation, mirrored):
    """Lower left corner of a footprint once placed, the point DEF records."""
    x0, y0, x1, y1 = box
    corners = [transform(x, y, rotation, mirrored)
               for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    return (min(c[0] for c in corners) + origin[0],
            min(c[1] for c in corners) + origin[1])


def extract(gds_path):
    library = gdstk.read_gds(gds_path)
    tops = library.top_level()
    if len(tops) != 1:
        sys.exit(f"expected exactly one top cell, found {[c.name for c in tops]}")
    top = tops[0]
    boxes = footprints(library)

    instances = []
    for reference in top.references:
        cell = reference.cell
        name = cell.name if hasattr(cell, "name") else str(cell)

        rotation = round(math.degrees(reference.rotation)) % 360
        mirrored = bool(reference.x_reflection)
        if rotation not in (0, 90, 180, 270):
            sys.exit(f"unexpected rotation {rotation} on a {name} placement")

        record = {
            "cell": name,
            "origin": [round(reference.origin[0], 3), round(reference.origin[1], 3)],
            "orient": ORIENTATION[(mirrored, rotation)],
        }
        if name in boxes:
            x, y = placed_lower_left(boxes[name], reference.origin, rotation, mirrored)
            record["lower_left"] = [round(x, 3), round(y, 3)]
        instances.append(record)

    return top.name, instances


def classify(name):
    """Split placements into the groups that mean different things downstream."""
    if name.startswith("VIA_"):
        return "via"
    if not name.startswith("sky130_"):
        return "other"
    if any(k in name for k in ("tapvpwrvgnd", "decap", "fill", "diode")):
        return "physical"
    return "logic"


def report(gds_path, json_path=None):
    top_name, instances = extract(gds_path)

    groups = Counter(classify(i["cell"]) for i in instances)
    print(f"file       {gds_path}")
    print(f"top cell   {top_name}")
    print(f"placements {len(instances)}")
    for group in ("logic", "physical", "via", "other"):
        if groups[group]:
            print(f"  {group:<9} {groups[group]}")

    components = [i for i in instances if classify(i["cell"]) in ("logic", "physical")]
    print(f"\ncomponents (logic + physical, what DEF would list): {len(components)}")

    print("\norientations:")
    for orient, count in Counter(i["orient"] for i in components).most_common():
        print(f"  {orient:<3} {count}")

    print("\ncell types:")
    for name, count in Counter(i["cell"] for i in components).most_common():
        print(f"  {count:6d}  {name}")

    missing = sorted({i["cell"] for i in components if "lower_left" not in i})
    if missing:
        print("\nno areaid.sc footprint, cannot place a lower left corner:")
        for name in missing:
            print(f"  {name}")

    if json_path:
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump({"top": top_name, "instances": instances}, handle, indent=1)
        print(f"\nwrote {json_path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    out = args[args.index("--json") + 1] if "--json" in args else None
    report(args[0], out)
