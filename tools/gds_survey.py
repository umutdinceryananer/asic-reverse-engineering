"""Survey the structure of a GDS file.

This is the first thing to run against an unfamiliar layout. Three things come
out of it:

  - The cell inventory. In a standard cell design the top cell is almost
    entirely references to library cells, and those cell names usually identify
    the PDK outright.
  - The layer inventory. Which (layer, datatype) pairs carry geometry, and how
    much. Mapping these numbers to names is the Phase 0 deliverable.
  - The labels. Text placed on the layout, typically the port names. The warm up
    GDS is documented as having "many internal names removed", so whatever
    survives here is what the puzzle GDS will also give us.

Usage:
    python tools/gds_survey.py puzzle/warmup/04_final.gds
"""

import sys
from collections import Counter, defaultdict

import gdstk


def instance_count(reference):
    """Number of placements a reference stands for, allowing for arrays."""
    repetition = getattr(reference, "repetition", None)
    if repetition is None:
        return 1
    try:
        return max(1, repetition.size)
    except (AttributeError, TypeError):
        return 1


def reference_name(reference):
    cell = reference.cell
    return cell.name if hasattr(cell, "name") else str(cell)


def flatten_counts(cell, cache=None):
    """Recursively count how many times each cell is instantiated below `cell`.

    Results are memoised per cell rather than guarded by a visited set: a block
    placed twice contributes its contents twice, so the guard has to prevent
    recomputation, not recounting.
    """
    if cache is None:
        cache = {}
    if cell.name in cache:
        return cache[cell.name]

    counts = Counter()
    cache[cell.name] = counts
    for reference in cell.references:
        name = reference_name(reference)
        multiplier = instance_count(reference)
        counts[name] += multiplier
        child = reference.cell
        if hasattr(child, "references"):
            for sub_name, sub_count in flatten_counts(child, cache).items():
                counts[sub_name] += sub_count * multiplier
    return counts


def survey(path):
    library = gdstk.read_gds(path)

    print(f"file        {path}")
    print(f"library     {library.name}")
    print(f"unit        {library.unit} m")
    print(f"precision   {library.precision} m")
    print(f"cells       {len(library.cells)}")

    tops = library.top_level()
    print(f"top level   {', '.join(c.name for c in tops)}")

    for top in tops:
        (xmin, ymin), (xmax, ymax) = top.bounding_box()
        width = (xmax - xmin) * library.unit * 1e6
        height = (ymax - ymin) * library.unit * 1e6
        print(f"\n--- top cell {top.name} ---")
        print(f"extent      {width:.2f} x {height:.2f} um")

        counts = flatten_counts(top)
        total = sum(counts.values())
        print(f"instances   {total} placements of {len(counts)} distinct cells")
        for name, count in counts.most_common():
            print(f"  {count:6d}  {name}")

    print("\n--- hierarchy ---")
    composite = [c for c in library.cells if c.references]
    if len(composite) <= 1:
        print("  flat: only the top cell contains references")
    for cell in sorted(composite, key=lambda c: c.name):
        direct = Counter()
        for reference in cell.references:
            direct[reference_name(reference)] += instance_count(reference)
        print(f"  {cell.name} ({sum(direct.values())} direct placements)")
        for name, count in direct.most_common():
            print(f"    {count:6d}  {name}")

    print("\n--- layers ---")
    polygons_by_layer = Counter()
    paths_by_layer = Counter()
    cells_by_layer = defaultdict(set)
    for cell in library.cells:
        for polygon in cell.polygons:
            key = (polygon.layer, polygon.datatype)
            polygons_by_layer[key] += 1
            cells_by_layer[key].add(cell.name)
        for path in cell.paths:
            for layer, datatype in zip(path.layers, path.datatypes):
                paths_by_layer[(layer, datatype)] += 1
                cells_by_layer[(layer, datatype)].add(cell.name)

    keys = sorted(set(polygons_by_layer) | set(paths_by_layer))
    print(f"{'layer/dt':>10}  {'polygons':>9}  {'paths':>7}  cells using it")
    for key in keys:
        layer, datatype = key
        users = cells_by_layer[key]
        sample = ", ".join(sorted(users)[:3])
        if len(users) > 3:
            sample += f", +{len(users) - 3} more"
        print(
            f"{layer:>6}/{datatype:<3}  {polygons_by_layer[key]:>9}  "
            f"{paths_by_layer[key]:>7}  {sample}"
        )

    print("\n--- labels ---")
    label_total = 0
    for cell in library.cells:
        if not cell.labels:
            continue
        print(f"  {cell.name}: {len(cell.labels)} labels")
        for label in cell.labels:
            label_total += 1
            print(
                f"    layer {label.layer}/{label.texttype:<3} "
                f"@ ({label.origin[0]:.3f}, {label.origin[1]:.3f})  {label.text!r}"
            )
    if label_total == 0:
        print("  none")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    survey(sys.argv[1])
