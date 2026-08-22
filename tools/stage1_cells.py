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

**A second library can be passed in, and the tiers compared.** 22 of the
puzzle's placements resolve by the structural fallback rather than by exact
geometry, and `docs/references.md` section 3 names a candidate cause: the target
was drawn against `sky130A` as built by open_pdks, which re-renders cell layouts
through Magic. `tools/fetch_open_pdks.py` fetches that library into a separate
cache and `--library` points this at it. Given one, the run resolves every
definition **twice** and prints the tiers side by side, so the answer to "does
the fallback go away" is one command rather than two runs and a diff.

A non-default library writes `instances.<name>.json` rather than
`instances.json`: the committed pipeline's numbers come from the standard
library, and an experiment must not overwrite the artifact every later stage
reads.

Usage:
    python tools/fetch_pdk.py            # once, populates pdk/
    python tools/stage1_cells.py warmup
    python tools/stage1_cells.py puzzle
    python tools/stage1_cells.py warmup --library pdk/open_pdks_sky130A
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


def load_library(directory=None):
    """Every cell definition in a library directory.

    One `.gds` per cell in `pdk/sky130_fd_sc_hd/`, or one merged file holding
    the whole library as open_pdks publishes it. Both work: this reads whatever
    `.gds` files are there and takes every cell out of each.
    """
    directory = directory or PDK_DIR
    paths = sorted(glob.glob(os.path.join(directory, "*.gds")))
    if not paths:
        sys.exit(f"no cell GDS in {directory}, run tools/fetch_pdk.py "
                 f"(or tools/fetch_open_pdks.py) first")
    cells = []
    for path in paths:
        cells.extend(gdstk.read_gds(path).cells)
    return cells


def resolve_definitions(layout, library):
    """Every layout definition to (library cell, orientation, tier).

    Exact geometry first. Where that misses because the PDK revision drifted,
    fall back to the structural key, and record which tier answered so the
    confidence of each identification stays visible downstream.
    """
    exact_index = fingerprint_index(library)
    structural_index = fingerprint_index(library, structural_key)
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
    return resolved, len(exact_index), len(structural_index)


def role(name):
    if name.startswith(VIA_PREFIX):
        return "via"
    if any(key in name for key in PHYSICAL_ONLY):
        return "physical"
    return "logic"


def run(target, library_dir=None):
    config = TARGETS[target]
    library_dir = library_dir or PDK_DIR
    alternate = os.path.normpath(library_dir) != os.path.normpath(PDK_DIR)
    print(f"target      {target}")
    print(f"layout      {config['gds']}")

    library = load_library(library_dir)
    print(f"library     {len(library)} cells from "
          f"{library_dir.replace(os.sep, '/')}")

    layout = gdstk.read_gds(config["gds"])
    tops = layout.top_level()
    if len(tops) != 1:
        sys.exit(f"expected one top cell, found {[c.name for c in tops]}")
    top = tops[0]

    # Fingerprint each definition once; a definition is placed many times.
    resolved, exact_count, structural_count = resolve_definitions(layout,
                                                                  library)
    print(f"            {exact_count} exact fingerprints, "
          f"{structural_count} structural fallbacks")

    # With an alternate library, resolve a second time against the standard one
    # so the two tier counts are in the same report rather than in two runs.
    baseline = None
    if alternate:
        baseline, _e, _s = resolve_definitions(layout, load_library(PDK_DIR))

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

    if baseline is not None:
        # Per tier, what changed. Counted over placements rather than over
        # definitions, because a definition placed 300 times is 300 of the
        # 1618 and one of the 437.
        was = Counter()
        for reference in top.references:
            definition = reference.cell
            name = definition.name if hasattr(definition, "name") \
                else str(definition)
            hit = baseline.get(name)
            was[hit[2] if hit else "unmatched"] += 1
        print(f"\nagainst the standard library, "
              f"{PDK_DIR.replace(os.sep, '/')}")
        print(f"  {'tier':<12}{'standard':>10}{'alternate':>12}{'':>4}change")
        for tier in ("exact", "structural", "unmatched"):
            before = was[tier]
            after = tiers[tier] if tier != "unmatched" else len(unmatched)
            delta = after - before
            print(f"  {tier:<12}{before:>10}{after:>12}    "
                  f"{delta:+d}" if delta else
                  f"  {tier:<12}{before:>10}{after:>12}    same")
        moved = []
        for name, hit in sorted(resolved.items()):
            old = baseline.get(name)
            if old and old[2] != hit[2]:
                moved.append((name, old[2], hit[2]))
        if moved:
            print(f"  {len(moved)} definition(s) changed tier:")
            for name, before, after in moved[:20]:
                print(f"    {name:<40} {before} -> {after}")
        else:
            print(f"  no definition changed tier")

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
    # An alternate library never overwrites the artifact every later stage
    # reads. The committed pipeline's numbers come from the standard library.
    name = "instances.json" if not alternate else \
        f"instances.{os.path.basename(os.path.normpath(library_dir))}.json"
    out_path = os.path.join(out_dir, name)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump({
            "target": target,
            "source_gds": config["gds"],
            "pdk": {"dir": library_dir.replace(os.sep, "/"),
                    "cells": len(library)},
            "instances": instances,
            "unmatched": unmatched,
        }, handle, indent=1)
    print(f"\nwrote {out_path}")

    unknown = [u for u in unmatched if not u["definition"].startswith(VIA_PREFIX)]
    return 0 if not unknown else 2


if __name__ == "__main__":
    args = sys.argv[1:]
    library_dir = None
    if "--library" in args:
        index = args.index("--library")
        if index + 1 >= len(args):
            sys.exit("--library needs a directory")
        library_dir = args[index + 1]
        args = args[:index] + args[index + 2:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage1_cells.py "
                 f"[{' | '.join(TARGETS)}] [--library <dir>]")
    sys.exit(run(args[0], library_dir))
