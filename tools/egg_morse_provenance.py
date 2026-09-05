"""Provenance for the Morse marker row: which cells, how many placements, where.

Complements tools/decode_marker_row.py (which decodes) by pinning the raw
provenance facts: the marker cells' geometry (layer set, polygon count, size),
the number of placements of each cell, which parent cell places them, and how
many distinct rows they form. Does not decode anything.

Usage:
    python tools/egg_morse_provenance.py puzzle/puzzle.gds
    python tools/egg_morse_provenance.py puzzle/warmup/04_final.gds   # control:
                                          # must report zero marker cells
    python tools/egg_morse_provenance.py --selftest
"""

import sys
from collections import Counter, defaultdict

import gdstk

MARKER_LAYER = (200, 0)


def marker_cells(library):
    """Cell name -> facts, for cells whose only geometry is on MARKER_LAYER."""
    facts = {}
    for cell in library.cells:
        layers = {(p.layer, p.datatype) for p in cell.polygons}
        if layers == {MARKER_LAYER}:
            (x0, y0), (x1, y1) = cell.bounding_box()
            facts[cell.name] = {
                "polygons": len(cell.polygons),
                "width": round(x1 - x0, 3),
                "height": round(y1 - y0, 3),
            }
    return facts


def placements(library, names):
    """(cell name -> count, cell name -> parent counter, y-row counter)."""
    counts = Counter()
    parents = defaultdict(Counter)
    rows = Counter()
    for cell in library.cells:
        for ref in cell.references:
            name = ref.cell.name if hasattr(ref.cell, "name") else str(ref.cell)
            if name in names:
                counts[name] += 1
                parents[name][cell.name] += 1
                rows[round(ref.origin[1], 3)] += 1
    return counts, parents, rows


def survey(library):
    """Cell name -> count of polygons on MARKER_LAYER, over every cell."""
    return {cell.name: n for cell in library.cells
            if (n := sum(1 for p in cell.polygons
                         if (p.layer, p.datatype) == MARKER_LAYER))}


def report(path):
    library = gdstk.read_gds(path)
    facts = marker_cells(library)
    print(f"file: {path}")
    print(f"marker layer: {MARKER_LAYER}")
    everywhere = survey(library)
    print("all layer-200/0 geometry in the library, by cell: "
          + (", ".join(f"{name} ({n})" for name, n in sorted(everywhere.items()))
             or "none"))
    if not facts:
        print("marker cells: NONE (no cell draws only on the marker layer)")
        return 1
    counts, parents, rows = placements(library, set(facts))
    for name in sorted(facts):
        f = facts[name]
        par = ", ".join(f"{p} x{n}" for p, n in sorted(parents[name].items()))
        print(f"cell {name}: {f['polygons']} polygon(s), "
              f"{f['width']:.3f} x {f['height']:.3f} um, "
              f"{counts[name]} placement(s), placed by: {par}")
    total = sum(counts.values())
    print(f"total placements: {total} across {len(rows)} distinct row y value(s): "
          + ", ".join(f"{y:.2f} ({n} marks)" for y, n in sorted(rows.items())))
    print(f"message instances: {len(rows)} "
          f"({'appears once' if len(rows) == 1 else 'REPEATS'})")
    return 0


def selftest():
    lib = gdstk.Library()
    m3 = lib.new_cell("M3")
    m3.add(gdstk.rectangle((0, 0), (1.38, 0.5), layer=200, datatype=0))
    m7 = lib.new_cell("M7")
    m7.add(gdstk.rectangle((0, 0), (4.14, 0.5), layer=200, datatype=0))
    other = lib.new_cell("X")
    other.add(gdstk.rectangle((0, 0), (0.3, 0.3), layer=69, datatype=20))
    mixed = lib.new_cell("MIXED")  # marker layer plus another: must NOT match
    mixed.add(gdstk.rectangle((0, 0), (1, 1), layer=200, datatype=0))
    mixed.add(gdstk.rectangle((0, 0), (1, 1), layer=69, datatype=20))
    top = lib.new_cell("TOP")
    for i in range(3):
        top.add(gdstk.Reference(m3, (i * 3.0, -5.0)))
    for i in range(2):
        top.add(gdstk.Reference(m7, (10.0 + i * 6.0, -5.0)))
    top.add(gdstk.Reference(other, (1.0, 1.0)))
    top.add(gdstk.Reference(mixed, (2.0, 2.0)))

    facts = marker_cells(lib)
    assert set(facts) == {"M3", "M7"}, facts
    assert survey(lib) == {"M3": 1, "M7": 1, "MIXED": 1}, survey(lib)
    assert facts["M3"]["width"] == 1.38 and facts["M7"]["width"] == 4.14
    counts, parents, rows = placements(lib, set(facts))
    assert counts == Counter({"M3": 3, "M7": 2}), counts
    assert parents["M3"] == Counter({"TOP": 3}), parents
    assert list(rows) == [-5.0] and rows[-5.0] == 5, rows
    print("selftest: 5 of 5 assertions passed (marker-only filter, "
          "whole-library survey, widths, per-cell counts, single row)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(report(sys.argv[1]))
