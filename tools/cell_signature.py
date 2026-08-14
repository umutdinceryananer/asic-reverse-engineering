"""Identify standard cells from geometry alone, without trusting their names.

Reading the cell name out of the GDS is the easy path, and it works here
because these files kept their names. A stripped layout would not, so this
builds the recognition that does not depend on them.

Two levels of signature.

A *profile* is what you could read off the picture by eye, made countable: the
footprint size, how many transistors, how many of them are PMOS, how many
contacts. The transistor count comes straight from the rule in lesson 0, that
poly crossing diff *is* a transistor -- intersect the two layers and count the
resulting pieces. Splitting those pieces by whether they fall inside the nwell
separates PMOS from NMOS.

A *digest* is an exact hash of the normalised geometry. Two cells with the same
digest are the same cell drawn in the same way. This is what actually
identifies a cell; the profile is what explains it to a human.

Usage:
    python tools/cell_signature.py puzzle/puzzle.gds
    python tools/cell_signature.py puzzle/puzzle.gds --match puzzle/warmup/04_final.gds
"""

import hashlib
import sys

import gdstk

NWELL = (64, 20)
DIFF = (65, 20)
POLY = (66, 20)
LICON = (66, 44)
LI1 = (67, 20)
AREAID = (81, 4)


def on(cell, key):
    return [p for p in cell.polygons if (p.layer, p.datatype) == key]


def transistors(cell):
    """(total, pmos, nmos) counted as poly-over-diff crossings."""
    poly, diff = on(cell, POLY), on(cell, DIFF)
    if not poly or not diff:
        return 0, 0, 0

    gates = gdstk.boolean(poly, diff, "and")
    total = len(gates)

    nwell = on(cell, NWELL)
    pmos = len(gdstk.boolean(gates, nwell, "and")) if nwell else 0
    return total, pmos, total - pmos


def footprint(cell):
    boxes = on(cell, AREAID) or cell.polygons
    if not boxes:
        return 0.0, 0.0
    corners = [p.bounding_box() for p in boxes]
    x0 = min(c[0][0] for c in corners)
    y0 = min(c[0][1] for c in corners)
    x1 = max(c[1][0] for c in corners)
    y1 = max(c[1][1] for c in corners)
    return round(x1 - x0, 3), round(y1 - y0, 3)


def profile(cell):
    width, height = footprint(cell)
    total, pmos, nmos = transistors(cell)
    return {
        "width": width,
        "height": height,
        "transistors": total,
        "pmos": pmos,
        "nmos": nmos,
        "poly_shapes": len(on(cell, POLY)),
        "diff_shapes": len(on(cell, DIFF)),
        "contacts": len(on(cell, LICON)),
        "li1_shapes": len(on(cell, LI1)),
        "labels": len(cell.labels),
    }


def digest(cell):
    """Hash of every polygon, translated so the cell's lower left sits at zero.

    Coordinates are rounded to the database grid before hashing so that two
    identical cells cannot differ by a floating point hair.
    """
    if not cell.polygons:
        return None
    corners = [p.bounding_box() for p in cell.polygons]
    ox = min(c[0][0] for c in corners)
    oy = min(c[0][1] for c in corners)

    shapes = []
    for polygon in cell.polygons:
        points = tuple(sorted(
            (round((x - ox) * 1000), round((y - oy) * 1000))
            for x, y in polygon.points
        ))
        shapes.append((polygon.layer, polygon.datatype, points))
    shapes.sort()
    return hashlib.sha256(repr(shapes).encode()).hexdigest()[:16]


def leaf_cells(library):
    return [c for c in library.cells if not c.references]


def describe(gds_path):
    library = gdstk.read_gds(gds_path)
    cells = leaf_cells(library)

    print(f"{gds_path}: {len(cells)} leaf cell definitions\n")
    header = (f"{'cell':<40} {'w x h':>13} {'tr':>4} {'P':>3} {'N':>3} "
              f"{'poly':>5} {'diff':>5} {'cont':>5} {'digest':>17}")
    print(header)
    print("-" * len(header))

    seen = {}
    for cell in sorted(cells, key=lambda c: c.name):
        p = profile(cell)
        d = digest(cell)
        seen.setdefault(d, []).append(cell.name)
        print(f"{cell.name:<40} {p['width']:>6.2f}x{p['height']:<6.2f} "
              f"{p['transistors']:>4} {p['pmos']:>3} {p['nmos']:>3} "
              f"{p['poly_shapes']:>5} {p['diff_shapes']:>5} {p['contacts']:>5} "
              f"{str(d):>17}")

    collisions = {d: names for d, names in seen.items() if len(names) > 1 and d}
    print("\nuniqueness check, exact geometry digest")
    if collisions:
        print("  geometry does NOT determine the cell, these share a digest:")
        for names in collisions.values():
            print(f"    {', '.join(names)}")
    else:
        print("  every cell definition has a distinct geometry digest")

    # The coarse profile is what you can read off a picture. It is much weaker
    # than the digest, and seeing exactly how much weaker is the point.
    by_profile = {}
    for cell in cells:
        p = profile(cell)
        if p["transistors"] == 0:
            continue
        key = (p["width"], p["height"], p["transistors"])
        by_profile.setdefault(key, []).append(cell.name)

    ambiguous = {k: v for k, v in by_profile.items() if len(v) > 1}
    counted = sum(len(v) for v in by_profile.values())
    print("\nuniqueness check, coarse profile (footprint + transistor count)")
    print(f"  {counted} cells with transistors fall into {len(by_profile)} profiles")
    if ambiguous:
        indistinct = sum(len(v) for v in ambiguous.values())
        print(f"  {indistinct} of them are NOT separated by profile alone:")
        for (w, h, t), names in sorted(ambiguous.items()):
            print(f"    {w}x{h}, {t} transistors -> {', '.join(sorted(names))}")


def match(unknown_path, library_path):
    """Recover names in one file using the cell definitions of another."""
    unknown = gdstk.read_gds(unknown_path)
    known = gdstk.read_gds(library_path)

    reference = {}
    for cell in leaf_cells(known):
        d = digest(cell)
        if d:
            reference[d] = cell.name

    print(f"reference library: {len(reference)} cells from {library_path}")
    print(f"identifying cells in {unknown_path}\n")

    named = unnamed = 0
    misses = []
    for cell in sorted(leaf_cells(unknown), key=lambda c: c.name):
        d = digest(cell)
        hit = reference.get(d)
        if hit:
            named += 1
            flag = "ok" if hit == cell.name else "DIFFERENT NAME"
            print(f"  {cell.name:<40} -> {hit:<40} {flag}")
        else:
            unnamed += 1
            misses.append(cell)

    print(f"\nidentified {named}, unidentified {unnamed}")
    if misses:
        print("\nnot in the reference library, so only their profile is known:")
        for cell in misses:
            p = profile(cell)
            print(f"  {cell.name:<40} {p['width']:>6.2f}x{p['height']:<6.2f} "
                  f"{p['transistors']:>3} transistors "
                  f"({p['pmos']} PMOS, {p['nmos']} NMOS)")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if "--match" in args:
        match(args[0], args[args.index("--match") + 1])
    else:
        describe(args[0])
