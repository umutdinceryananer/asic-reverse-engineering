"""Stage 1, cell recognition. Layout to instance list.

Identifies every placement in a layout and writes `out/<target>/instances.json`.

Geometry is the primary path, as the spec requires. Each cell definition in the
layout is fingerprinted and looked up in an index built from the PDK's own cell
GDS files, covering all eight orientations. Names that happen to have survived
in the layout hierarchy are used only as a cross check, and any disagreement is
reported rather than resolved silently.

That ordering matters. A stripped layout gives no names at all, so a pipeline
that leans on them is not a reverse engineering tool. Here the names do survive,
which is precisely what makes this a good place to prove the geometric path
works: we can check its answer against them.

Usage:
    python tools/fetch_pdk.py            # once, populates pdk/
    python tools/stage1_cells.py warmup
    python tools/stage1_cells.py puzzle
"""

import glob
import json
import os
import sys
from collections import Counter

import gdstk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.gds import (DEF_NAME, compose, digest, fingerprint_index,
                        footprint, from_reference, placed_lower_left,
                        structural_key)

TARGETS = {
    "warmup": {
        "gds": "puzzle/warmup/04_final.gds",
        "def": "puzzle/warmup/03_post_place_and_route.def",
    },
    "puzzle": {
        "gds": "puzzle/puzzle.gds",
        "def": None,
    },
}

PDK_DIR = os.path.join("pdk", "sky130_fd_sc_hd")

# Placements that are not library cells. Routing vias are geometry the router
# emitted, and they belong to nets rather than to the component list.
VIA_PREFIX = "VIA_"

PHYSICAL_ONLY = ("tapvpwrvgnd", "decap", "fill", "diode")


def load_library():
    paths = sorted(glob.glob(os.path.join(PDK_DIR, "*.gds")))
    if not paths:
        sys.exit(f"no cell GDS in {PDK_DIR}, run tools/fetch_pdk.py first")
    cells = []
    for path in paths:
        cells.extend(gdstk.read_gds(path).cells)
    return cells


def role(name):
    if name.startswith(VIA_PREFIX):
        return "via"
    if any(key in name for key in PHYSICAL_ONLY):
        return "physical"
    return "logic"


def run(target):
    config = TARGETS[target]
    print(f"target      {target}")
    print(f"layout      {config['gds']}")

    library = load_library()
    exact_index = fingerprint_index(library)
    structural_index = fingerprint_index(library, structural_key)
    print(f"library     {len(library)} PDK cells")
    print(f"            {len(exact_index)} exact fingerprints, "
          f"{len(structural_index)} structural fallbacks")

    layout = gdstk.read_gds(config["gds"])
    tops = layout.top_level()
    if len(tops) != 1:
        sys.exit(f"expected one top cell, found {[c.name for c in tops]}")
    top = tops[0]

    # Fingerprint each definition once; a definition is placed many times.
    #
    # Exact geometry first. Where that misses because the PDK revision drifted,
    # fall back to the structural key, and record which tier answered so the
    # confidence of each identification stays visible downstream.
    resolved = {}
    for cell in layout.cells:
        if cell.references:
            continue
        hit = exact_index.get(digest(cell))
        if hit:
            resolved[cell.name] = (*hit, "exact")
            continue
        hit = structural_index.get(structural_key(cell))
        if hit:
            resolved[cell.name] = (*hit, "structural")

    instances = []
    unmatched = []
    disagreements = []

    for number, reference in enumerate(top.references):
        definition = reference.cell
        name = definition.name if hasattr(definition, "name") else str(definition)
        placement = from_reference(reference)

        hit = resolved.get(name)
        if hit is None:
            box = definition.bounding_box() if definition.polygons else None
            unmatched.append({
                "definition": name,
                "origin": [round(reference.origin[0], 3), round(reference.origin[1], 3)],
                "bbox": [round(v, 3) for v in (box[0][0], box[0][1], box[1][0], box[1][1])]
                        if box else None,
            })
            continue

        library_name, drawn_as, tier = hit
        orientation = compose(drawn_as, placement)

        record = {
            "id": f"i{number:05d}",
            "cell": library_name,
            "origin": [round(reference.origin[0], 3), round(reference.origin[1], 3)],
            "orient": DEF_NAME[orientation],
            "role": role(library_name),
            "match": tier,
        }

        box = footprint(definition)
        if box:
            record["lower_left"] = list(
                placed_lower_left(box, reference.origin, placement))

        if name != library_name:
            disagreements.append((name, library_name))
            record["hierarchy_name"] = name

        instances.append(record)

    # --- report -------------------------------------------------------------
    print(f"\nplacements  {len(top.references)}")
    print(f"identified  {len(instances)} by geometry")
    print(f"unmatched   {len(unmatched)}")

    roles = Counter(i["role"] for i in instances)
    for key in ("logic", "physical"):
        print(f"  {key:<9} {roles[key]}")

    tiers = Counter(i["match"] for i in instances)
    print(f"\nmatch tier: exact {tiers['exact']}, structural {tiers['structural']}")
    if tiers["structural"]:
        by_cell = Counter(i["cell"] for i in instances if i["match"] == "structural")
        print("  exact geometry missed these, PDK revision drift:")
        for name, count in by_cell.most_common():
            print(f"    {count:6d}  {name}")

    print("\ncross check against surviving hierarchy names")
    if disagreements:
        print(f"  {len(disagreements)} placements disagree:")
        for got, want in Counter(disagreements).most_common(10):
            print(f"    hierarchy says {got}, geometry says {want}")
    else:
        print("  every geometric identification matches the name in the layout")

    if unmatched:
        groups = Counter(u["definition"] for u in unmatched)
        print("\nunmatched placements, by definition:")
        for name, count in groups.most_common():
            sample = next(u for u in unmatched if u["definition"] == name)
            note = "routing via, not a library cell" if name.startswith(VIA_PREFIX) else \
                   "NOT A KNOWN LIBRARY CELL, inspect"
            print(f"  {count:6d}  {name:<36} bbox {sample['bbox']}  {note}")

    print("\norientations:")
    for orient, count in Counter(i["orient"] for i in instances).most_common():
        print(f"  {orient:<3} {count}")

    print("\ncell types:")
    for name, count in Counter(i["cell"] for i in instances).most_common(12):
        print(f"  {count:6d}  {name}")
    distinct = len({i["cell"] for i in instances})
    if distinct > 12:
        print(f"  ... {distinct - 12} more distinct types")

    out_dir = os.path.join("out", target)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "instances.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump({
            "target": target,
            "source_gds": config["gds"],
            "pdk": {"dir": PDK_DIR, "cells": len(library)},
            "instances": instances,
            "unmatched": unmatched,
        }, handle, indent=1)
    print(f"\nwrote {out_path}")

    unknown = [u for u in unmatched if not u["definition"].startswith(VIA_PREFIX)]
    return 0 if not unknown else 2


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage1_cells.py [{' | '.join(TARGETS)}]")
    sys.exit(run(args[0]))
