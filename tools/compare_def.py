"""Check an extracted cell list against the DEF that produced the layout.

The warm up ships `03_post_place_and_route.def`, which names every instance,
its cell type, its position and its orientation. That makes it a per instance
answer key rather than a per count one: if the extraction is wrong, this says
*which* placement is wrong instead of only that something is.

Matching is done on position, because instance names do not survive into the
GDS. Two placements are the same placement if their lower left corners agree.

Usage:
    python tools/compare_def.py puzzle/warmup/04_final.gds \
                                puzzle/warmup/03_post_place_and_route.def
"""

import re
import sys
from collections import Counter

from extract_cells import classify, extract

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


def compare(gds_path, def_path):
    declared, def_records = parse_def(def_path)
    print(f"DEF declares {declared} components, parsed {len(def_records)}")
    if declared != len(def_records):
        print("  parser missed some, the comparison below is not trustworthy")

    _, instances = extract(gds_path)
    gds_records = [i for i in instances if classify(i["cell"]) in ("logic", "physical")]
    print(f"GDS yields  {len(gds_records)} components\n")

    by_position = {}
    duplicates = 0
    for record in gds_records:
        key = tuple(record["lower_left"])
        if key in by_position:
            duplicates += 1
        by_position[key] = record
    if duplicates:
        print(f"warning: {duplicates} GDS placements share a lower left corner\n")

    matched = 0
    wrong_cell = []
    wrong_orient = []
    not_found = []

    for record in def_records:
        found = by_position.pop(record["lower_left"], None)
        if found is None:
            not_found.append(record)
            continue
        if found["cell"] != record["cell"]:
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
                      f"{want['orient']}, GDS says {got['cell']} {got['orient']}")
            if len(rows) > 10:
                print(f"  ... and {len(rows) - 10} more")

    if not_found:
        print("\nin DEF but not found in GDS:")
        for record in not_found[:10]:
            print(f"  {record['instance']:<40} {record['cell']} "
                  f"at {record['lower_left']} {record['orient']}")
        if len(not_found) > 10:
            print(f"  ... and {len(not_found) - 10} more")
        print("\n  by cell type:", dict(Counter(r["cell"] for r in not_found)))

    if by_position:
        print("\nin GDS but not in DEF:")
        for key, record in list(by_position.items())[:10]:
            print(f"  {record['cell']} at {key} {record['orient']}")
        if len(by_position) > 10:
            print(f"  ... and {len(by_position) - 10} more")

    ok = matched == total and not by_position
    print("\nRESULT:", "clean match" if ok else "MISMATCH, do not proceed")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(compare(sys.argv[1], sys.argv[2]))
