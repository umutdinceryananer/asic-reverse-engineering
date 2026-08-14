"""Check a stage 1 instance list against the DEF that produced the layout.

The warm up ships `03_post_place_and_route.def`, which names every instance with
its cell type, position and orientation. That makes it a per instance answer key
rather than a per count one: when the extraction is wrong it says *which*
placement is wrong instead of only that something is.

Matching is on position, because instance names do not survive into the GDS.

Usage:
    python tools/stage1_cells.py warmup     # produces out/warmup/instances.json
    python tools/compare_def.py warmup
"""

import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage1_cells import TARGETS

COMPONENT = re.compile(
    r"-\s+(?P<inst>\S+)\s+(?P<cell>\S+)\s+.*?"
    r"\(\s*(?P<x>-?\d+)\s+(?P<y>-?\d+)\s*\)\s+(?P<orient>[A-Z]+)\s*;",
    re.DOTALL,
)


def parse_def(path):
    """Instance records from the COMPONENTS section, positions in microns."""
    text = open(path, encoding="utf-8").read()

    unit = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", text)
    scale = int(unit.group(1)) if unit else 1000

    start = text.index("\nCOMPONENTS")
    end = text.index("END COMPONENTS", start)
    declared = int(re.search(r"COMPONENTS\s+(\d+)\s*;", text[start:]).group(1))

    records = []
    for match in COMPONENT.finditer(text[start:end]):
        records.append({
            "instance": match.group("inst"),
            "cell": match.group("cell"),
            "lower_left": (round(int(match.group("x")) / scale, 3),
                           round(int(match.group("y")) / scale, 3)),
            "orient": match.group("orient"),
        })
    return declared, records


def compare(target):
    def_path = TARGETS[target]["def"]
    if not def_path:
        sys.exit(f"target {target!r} has no DEF to check against")

    instances_path = os.path.join("out", target, "instances.json")
    if not os.path.exists(instances_path):
        sys.exit(f"{instances_path} missing, run tools/stage1_cells.py {target} first")

    declared, def_records = parse_def(def_path)
    print(f"DEF declares {declared} components, parsed {len(def_records)}")
    if declared != len(def_records):
        print("  parser missed some, the comparison below is not trustworthy")

    with open(instances_path, encoding="utf-8") as handle:
        stage1 = json.load(handle)
    recovered = stage1["instances"]
    print(f"stage 1 gives {len(recovered)} instances\n")

    by_position = {}
    duplicates = 0
    for record in recovered:
        key = tuple(record.get("lower_left", []))
        if not key:
            continue
        if key in by_position:
            duplicates += 1
        by_position[key] = record
    if duplicates:
        print(f"warning: {duplicates} placements share a lower left corner\n")

    matched = 0
    wrong_cell, wrong_orient, not_found = [], [], []

    for record in def_records:
        found = by_position.pop(record["lower_left"], None)
        if found is None:
            not_found.append(record)
        elif found["cell"] != record["cell"]:
            wrong_cell.append((record, found))
        elif found["orient"] != record["orient"]:
            wrong_orient.append((record, found))
        else:
            matched += 1

    total = len(def_records)
    print(f"exact matches      {matched}/{total}  ({100 * matched / total:.2f}%)")
    print(f"wrong cell type    {len(wrong_cell)}")
    print(f"wrong orientation  {len(wrong_orient)}")
    print(f"in DEF, not in GDS {len(not_found)}")
    print(f"in GDS, not in DEF {len(by_position)}")

    for label, rows in (("wrong cell type", wrong_cell),
                        ("wrong orientation", wrong_orient)):
        if rows:
            print(f"\n{label}:")
            for want, got in rows[:10]:
                print(f"  at {want['lower_left']}  DEF says {want['cell']} "
                      f"{want['orient']}, stage 1 says {got['cell']} {got['orient']}")
            if len(rows) > 10:
                print(f"  ... and {len(rows) - 10} more")

    if not_found:
        print("\nin DEF but not recovered:")
        for record in not_found[:10]:
            print(f"  {record['instance']:<40} {record['cell']} "
                  f"at {record['lower_left']} {record['orient']}")
        print("\n  by cell type:", dict(Counter(r["cell"] for r in not_found)))

    if by_position:
        print("\nrecovered but not in DEF:")
        for key, record in list(by_position.items())[:10]:
            print(f"  {record['cell']} at {key} {record['orient']}")

    ok = matched == total and not by_position
    print("\nRESULT:", "clean match" if ok else "MISMATCH, do not proceed")
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/compare_def.py [{' | '.join(TARGETS)}]")
    sys.exit(compare(args[0]))
