"""Check stage 1 and stage 2 output against the DEF that produced the layout.

The warm up ships `03_post_place_and_route.def`, which names every instance and
every net. That makes it an answer key at the level of individual placements and
individual connections, rather than only at the level of counts. When the
extraction is wrong it says *which* placement or *which* net is wrong.

Two gates.

**Components.** Every placement, matched on position, must agree on cell type
and orientation.

**Nets.** A netlist is a partition of cell pins into nets, so the check is that
our partition equals the DEF's. Net names are not used for matching, because the
extractor only recovers a name where a label happened to sit on the geometry;
two nets are the same net when they hold the same set of (instance, pin) pairs.

Usage:
    python tools/stage1_cells.py warmup
    python tools/stage2_nets.py warmup
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
CONNECTION = re.compile(r"\(\s*(\S+)\s+(\S+)\s*\)")


def read(path):
    return open(path, encoding="utf-8").read()


def def_scale(text):
    unit = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;", text)
    return int(unit.group(1)) if unit else 1000


def parse_components(text):
    scale = def_scale(text)
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


def parse_nets(text, section="NETS"):
    """Net name -> set of (instance, pin), plus the ports it reaches.

    Only the header of each net entry carries connections. Everything after the
    first '+' is routing, and that also contains parenthesised pairs, so the
    split has to happen before the connection pairs are pulled out.
    """
    marker = f"\n{section} "
    if marker not in text:
        return None, {}
    start = text.index(marker)
    end = text.index(f"END {section}", start)
    declared = int(re.search(rf"{section}\s+(\d+)\s*;", text[start:]).group(1))

    nets = {}
    for chunk in text[start:end].split(";"):
        stripped = chunk.strip()
        if not stripped.startswith("-"):
            continue
        header = stripped.split("+")[0]
        name = header.split()[1]
        connections = set()
        ports = set()
        for instance, pin in CONNECTION.findall(header):
            if instance == "PIN":
                ports.add(pin)
            else:
                connections.add((instance, pin))
        nets[name] = {"connections": connections, "ports": ports}
    return declared, nets


def compare_components(text, target):
    path = os.path.join("out", target, "instances.json")
    if not os.path.exists(path):
        sys.exit(f"{path} missing, run tools/stage1_cells.py {target} first")
    stage1 = json.load(open(path, encoding="utf-8"))

    declared, records = parse_components(text)
    print("=== components ===")
    print(f"DEF declares {declared}, parsed {len(records)}; "
          f"stage 1 gives {len(stage1['instances'])}")

    by_position = {tuple(i["lower_left"]): i
                   for i in stage1["instances"] if "lower_left" in i}

    matched = 0
    problems = []
    for record in records:
        found = by_position.pop(record["lower_left"], None)
        if found is None:
            problems.append(("missing", record, None))
        elif found["cell"] != record["cell"]:
            problems.append(("wrong cell", record, found))
        elif found["orient"] != record["orient"]:
            problems.append(("wrong orientation", record, found))
        else:
            matched += 1

    print(f"exact matches {matched}/{len(records)}")
    for kind, want, got in problems[:10]:
        print(f"  {kind} at {want['lower_left']}: DEF {want['cell']} "
              f"{want['orient']}, got {got and (got['cell'], got['orient'])}")
    if by_position:
        print(f"  {len(by_position)} recovered placements are not in the DEF")

    ok = matched == len(records) and not by_position and not problems
    return ok, {tuple(i["lower_left"]): i["id"]
                for i in stage1["instances"] if "lower_left" in i}, records


def compare_nets(text, target, position_to_id, components):
    path = os.path.join("out", target, "netlist.json")
    if not os.path.exists(path):
        sys.exit(f"{path} missing, run tools/stage2_nets.py {target} first")
    stage2 = json.load(open(path, encoding="utf-8"))

    print("\n=== nets ===")

    # Our instance ids carry no DEF name, so bridge them through position.
    id_to_def_name = {}
    for record in components:
        instance_id = position_to_id.get(record["lower_left"])
        if instance_id:
            id_to_def_name[instance_id] = record["instance"]

    declared, def_nets = parse_nets(text, "NETS")
    special, def_special = parse_nets(text, "SPECIALNETS")
    print(f"DEF declares {declared} signal nets and {special} special nets")

    recovered = {}
    for net in stage2["nets"]:
        pins = frozenset(
            (id_to_def_name.get(c["instance"], c["instance"]), c["pin"])
            for c in net["connections"]
        )
        recovered[net["name"]] = {"pins": pins, "kind": net["kind"]}
    print(f"stage 2 gives {len(recovered)} nets carrying a cell pin")

    signal = {n: v for n, v in recovered.items() if v["kind"] == "signal"}
    reference = {name: net["connections"] for name, net in def_nets.items()}

    # Match on the pin set. A netlist is a partition of pins into nets, so the
    # partitions have to be equal; the names attached to them do not.
    by_pins = {}
    for name, connections in reference.items():
        by_pins.setdefault(frozenset(connections), []).append(name)

    matched, mismatched, extra = [], [], []
    for name, net in signal.items():
        hit = by_pins.get(net["pins"])
        if hit:
            matched.append((name, hit[0]))
            hit.pop(0)
            if not hit:
                by_pins.pop(net["pins"])
        else:
            extra.append((name, net["pins"]))

    leftover = [(names[0], pins) for pins, names in by_pins.items() for _ in names]

    print(f"signal nets matched exactly {len(matched)}/{len(reference)}")
    print(f"  recovered nets with no DEF counterpart: {len(extra)}")
    print(f"  DEF nets not recovered:                 {len(leftover)}")

    for name, pins in extra[:5]:
        print(f"\n  recovered {name!r} holds {len(pins)} pins:")
        for pin in sorted(pins)[:8]:
            print(f"    {pin}")
        closest = max(reference.items(),
                      key=lambda kv: len(kv[1] & pins), default=(None, set()))
        if closest[0]:
            overlap = closest[1] & pins
            print(f"    closest DEF net {closest[0]!r}: {len(overlap)} shared, "
                  f"{len(closest[1] - pins)} missing, {len(pins - closest[1])} extra")

    for name, pins in leftover[:5]:
        print(f"\n  DEF net {name!r} was not recovered, {len(pins)} pins")

    # Power nets in a DEF use '*' for the instance, meaning every component.
    # Expanding it is the difference between comparing two pins and comparing
    # the several hundred the net really holds.
    #
    # VNB and VPB are body ties. They reach the cell through the wells, which
    # are not part of a routing stack, so an extractor that walks li1 upward
    # will never see them. Their absence is expected rather than a defect, and
    # a gate level netlist does not carry them either.
    BODY_TIES = {"VNB", "VPB"}

    power_ok = True
    if def_special:
        all_instances = {record["instance"] for record in components}
        print("\n  special (power) nets, DEF '*' expanded to every component:")
        for name, net in def_special.items():
            expected = set()
            for instance, pin in net["connections"]:
                if instance == "*":
                    expected |= {(i, pin) for i in all_instances}
                else:
                    expected.add((instance, pin))

            ours = recovered.get(name, {}).get("pins", frozenset())
            routable = {p for p in expected if p[1] not in BODY_TIES}
            missing = routable - ours
            extra_pins = ours - expected

            print(f"    {name}: DEF expects {len(expected)} pins "
                  f"({len(routable)} on routing layers), stage 2 has {len(ours)}")
            print(f"      missing {len(missing)}, unexpected {len(extra_pins)}")
            skipped = Counter(p[1] for p in expected - routable)
            if skipped:
                print(f"      body ties not on the routing stack, expected to be "
                      f"absent: {dict(skipped)}")
            if missing:
                power_ok = False
                for pin in sorted(missing)[:5]:
                    print(f"      missing: {pin}")

    return len(matched) == len(reference) and not extra and not leftover and power_ok


def main(target):
    def_path = TARGETS[target]["def"]
    if not def_path:
        sys.exit(f"target {target!r} has no DEF to check against")
    text = read(def_path)

    components_ok, position_to_id, components = compare_components(text, target)
    nets_ok = compare_nets(text, target, position_to_id, components)

    print("\nRESULT:", "clean match" if components_ok and nets_ok
          else "MISMATCH, do not proceed")
    return 0 if components_ok and nets_ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/compare_def.py [{' | '.join(TARGETS)}]")
    sys.exit(main(args[0]))
