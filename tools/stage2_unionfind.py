"""Stage 2 fallback extractor: connectivity by union find.

`docs/solver-pipeline.md` asks for this alongside the KLayout path: "union find
over touching polygons per layer, then merge across layers through via overlap.
Each resulting set is one net."

The point is not that KLayout is doubted. It is that on the puzzle there is no
answer key, so the only available evidence that the extraction is right is a
second extraction that agrees with it. Every real defect found in this project
surfaced through an independent second route to the same fact; this is that
route for the stage carrying the most risk.

Independence is the whole value, so this shares as little as possible with
`stage2_nets.py`:

  - a different geometry library, gdstk rather than klayout
  - flat, not hierarchical: the layout is flattened to absolute coordinates and
    every polygon competes on equal terms
  - its own touch test, its own connected components, its own pin attribution

What it deliberately does NOT change is the connectivity model. It walks the
same layer stack, because a difference in the model would produce differences
that say nothing about whether either implementation is correct.

Two facts about this layout make an exact implementation cheap, both measured
rather than assumed:

  - every polygon on a conductor layer is rectilinear, so slicing it into
    rectangles along its own vertex y coordinates is lossless
  - every coordinate sits on the 1 nm grid, so integer arithmetic is exact and
    no tolerance has to be invented

Sixteen percent of the shapes are not rectangles, reaching twenty vertices, so
comparing bounding boxes would connect shapes that never touch. That is exactly
the "overly permissive connectivity rule" the spec warns about.

Usage:
    python tools/stage1_cells.py warmup
    python tools/stage2_nets.py  warmup
    python tools/stage2_unionfind.py warmup      # compares against stage 2
"""

import json
import math
import os
import sys
from collections import Counter, defaultdict

import gdstk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import cellnodes
from common.gds import DEF_NAME
from common.lef import load as load_lef
from stage1_cells import PDK_DIR, TARGETS
from stage2_nets import LABELS, POWER, STACK

# Grid cell for the spatial hash, in nanometres. Only affects speed: a shape is
# filed under every cell its bounding box covers, so two shapes that touch
# always share at least one cell whatever the size.
GRID = 2000

NM = 1000  # micrometres to nanometres


class UnionFind:
    """Disjoint sets over integer ids, path halving plus union by size."""

    def __init__(self, count):
        self.parent = list(range(count))
        self.size = [1] * count

    def find(self, item):
        parent = self.parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, left, right):
        left, right = self.find(left), self.find(right)
        if left == right:
            return False
        if self.size[left] < self.size[right]:
            left, right = right, left
        self.parent[right] = left
        self.size[left] += self.size[right]
        return True


def rectangles(points):
    """Slice one rectilinear polygon into integer rectangles.

    Cut at every y coordinate the polygon itself uses. Within a slab the
    polygon's outline cannot change, so the vertical edges crossing the slab,
    read left to right, pair up into spans that are inside it. This is the
    even-odd rule, and it is exact for any simple rectilinear polygon, holes and
    concavities included.

    Returns None if the polygon has a non axis-aligned edge, so the caller can
    report it rather than silently mis-slicing it.
    """
    corners = [(int(round(x * NM)), int(round(y * NM))) for x, y in points]

    edges = []  # vertical edges only: (x, y_low, y_high)
    for index, (x0, y0) in enumerate(corners):
        x1, y1 = corners[(index + 1) % len(corners)]
        if x0 == x1 and y0 == y1:
            continue
        if x0 == x1:
            edges.append((x0, min(y0, y1), max(y0, y1)))
        elif y0 != y1:
            return None  # diagonal edge, not rectilinear

    if not edges:
        return []

    cuts = sorted({y for _, low, high in edges for y in (low, high)})
    out = []
    for low, high in zip(cuts, cuts[1:]):
        if low == high:
            continue
        crossing = sorted(x for x, edge_low, edge_high in edges
                          if edge_low <= low and edge_high >= high)
        for left, right in zip(crossing[0::2], crossing[1::2]):
            if right > left:
                out.append((left, low, right, high))
    return out


def collect(gds_path):
    """Every conductor shape in the layout, flattened, as integer rectangles.

    Returns (rects, layer_of, report). `rects` is a list of (x0, y0, x1, y1) in
    nanometres and `layer_of` the stack index each belongs to.
    """
    library = gdstk.read_gds(gds_path)
    top = library.top_level()[0]

    rects = []
    layer_of = []
    report = {"polygons": 0, "rectangles": 0, "not_rectilinear": []}

    for index, (name, layer, datatype) in enumerate(STACK):
        polygons = top.get_polygons(depth=None, layer=layer, datatype=datatype)
        report["polygons"] += len(polygons)
        for polygon in polygons:
            pieces = rectangles(polygon.points)
            if pieces is None:
                report["not_rectilinear"].append(name)
                continue
            for piece in pieces:
                rects.append(piece)
                layer_of.append(index)
        report[name] = len(polygons)
    report["rectangles"] = len(rects)
    return library, top, rects, layer_of, report


def connect(rects, layer_of):
    """Union touching shapes within a layer and overlapping shapes across two.

    Within a layer, shapes that share an edge of positive length are one
    conductor: that is how a wire is drawn, as abutting rectangles. Contact at a
    single corner is not a connection and is counted separately rather than
    assumed either way.

    Across two adjacent stack entries the overlap must have positive area. A via
    conducts where it has area under the metal, not where it merely grazes an
    edge.
    """
    buckets = defaultdict(list)
    for index, (x0, y0, x1, y1) in enumerate(rects):
        layer = layer_of[index]
        for gx in range(x0 // GRID, x1 // GRID + 1):
            for gy in range(y0 // GRID, y1 // GRID + 1):
                buckets[(layer, gx, gy)].append(index)

    sets = UnionFind(len(rects))
    corner_only = 0

    def overlap(a, b):
        ax0, ay0, ax1, ay1 = rects[a]
        bx0, by0, bx1, by1 = rects[b]
        return (min(ax1, bx1) - max(ax0, bx0),
                min(ay1, by1) - max(ay0, by0))

    for (layer, gx, gy), members in buckets.items():
        for position, a in enumerate(members):
            for b in members[position + 1:]:
                dx, dy = overlap(a, b)
                if dx < 0 or dy < 0:
                    continue
                if dx == 0 and dy == 0:
                    corner_only += 1
                    continue
                sets.union(a, b)

        for b in buckets.get((layer + 1, gx, gy), ()):
            for a in members:
                dx, dy = overlap(a, b)
                if dx > 0 and dy > 0:
                    sets.union(a, b)

    return sets, corner_only


def index_rects(rects, layer_of):
    """Grid lookup for point queries, one bucket set per stack layer."""
    buckets = defaultdict(list)
    for index, (x0, y0, x1, y1) in enumerate(rects):
        layer = layer_of[index]
        for gx in range(x0 // GRID, x1 // GRID + 1):
            for gy in range(y0 // GRID, y1 // GRID + 1):
                buckets[(layer, gx, gy)].append(index)
    return buckets


def containing(buckets, rects, layer, x, y):
    """Which rectangle on `layer` covers this point, if any."""
    for index in buckets.get((layer, x // GRID, y // GRID), ()):
        x0, y0, x1, y1 = rects[index]
        if x0 <= x <= x1 and y0 <= y <= y1:
            return index
    return None


def transform_point(point, origin, rotation, reflected):
    """Place a point drawn inside a cell definition into layout coordinates."""
    x, y = point
    if reflected:
        y = -y
    if rotation:
        cos, sin = math.cos(rotation), math.sin(rotation)
        x, y = x * cos - y * sin, x * sin + y * cos
    return x + origin[0], y + origin[1]


def bridge_terminals(top, rects, layer_of, sets, stage1, pads):
    """Join li1 pads that are the same cell terminal but sit in different sets.

    Our connectivity starts at li1, so two contacts on one transistor gate look
    unrelated. `common/cellnodes.py` reads from the PDK which undeclared pad is
    which declared pin; here the two are actually joined, so the pin's label
    ends up on the routing that landed on the pad.

    Bridging rather than labelling matters: attributing the pad to the pin
    without joining the sets would report the pin twice, once in each set, and
    a pin in two nets is not a netlist.
    """
    if not pads:
        return 0, Counter()

    stack_index = {name: index for index, (name, _, _) in enumerate(STACK)}
    by_placement = {(r["origin"][0], r["origin"][1], r["orient"]): r
                    for r in stage1["instances"]}
    buckets = index_rects(rects, layer_of)
    joined = 0
    missing = Counter()

    for reference in top.references:
        origin = (round(reference.origin[0], 3), round(reference.origin[1], 3))
        rotation = round(math.degrees(reference.rotation)) % 360
        orientation = DEF_NAME[(bool(reference.x_reflection), rotation)]
        record = by_placement.get((origin[0], origin[1], orientation))
        if record is None:
            continue
        for entry in pads.get(record["cell"], ()):
            found = []
            for point in (entry["pad"], entry["anchor"]):
                x, y = transform_point(point, reference.origin,
                                       reference.rotation, reference.x_reflection)
                found.append(containing(buckets, rects, stack_index["li1"],
                                        int(round(x * NM)), int(round(y * NM))))
            if None in found:
                missing[f"{record['cell']}.{entry['pin']}"] += 1
                continue
            if sets.union(*found):
                joined += 1
    return joined, missing


def attribute(top, rects, layer_of, sets, stage1):
    """Tie each cell pin to the component its label lands in.

    Pin names come from the labels inside each cell definition, and which
    instance a label belongs to comes from the placement it was reached through.
    That is deliberately not the same route stage 2 takes -- it resolves pins
    inside a hierarchical extraction -- so agreement between the two means
    something.
    """
    stack_index = {name: index for index, (name, _, _) in enumerate(STACK)}
    label_layer = {(layer, datatype): stack_index[metal]
                   for metal, layer, datatype in LABELS}

    by_placement = {}
    for record in stage1["instances"]:
        by_placement[(record["origin"][0], record["origin"][1],
                      record["orient"])] = record

    buckets = index_rects(rects, layer_of)
    connections = defaultdict(set)
    unplaced = Counter()
    homeless = Counter()
    linked = 0

    for reference in top.references:
        origin = (round(reference.origin[0], 3), round(reference.origin[1], 3))
        rotation = round(math.degrees(reference.rotation)) % 360
        orientation = DEF_NAME[(bool(reference.x_reflection), rotation)]
        record = by_placement.get((origin[0], origin[1], orientation))
        if record is None:
            unplaced[reference.cell.name] += 1
            continue
        if record["cell"] != reference.cell.name:
            sys.exit(f"placement at {origin} {orientation} is {record['cell']} "
                     f"per stage 1 but {reference.cell.name} in the layout")
        linked += 1

        for label in reference.cell.labels:
            layer = label_layer.get((label.layer, label.texttype))
            if layer is None:
                continue
            x, y = transform_point(label.origin, reference.origin,
                                   reference.rotation, reference.x_reflection)
            hit = containing(buckets, rects, layer,
                             int(round(x * NM)), int(round(y * NM)))
            if hit is None:
                homeless[f"{record['cell']}.{label.text}"] += 1
                continue
            connections[sets.find(hit)].add((record["id"], record["cell"],
                                             label.text))

    # Top level labels name the nets they sit on; those are the design's ports.
    names = {}
    for label in top.labels:
        layer = label_layer.get((label.layer, label.texttype))
        if layer is None:
            continue
        hit = containing(buckets, rects, layer,
                         int(round(label.origin[0] * NM)),
                         int(round(label.origin[1] * NM)))
        if hit is not None:
            names.setdefault(sets.find(hit), label.text)

    return connections, names, linked, unplaced, homeless


def as_partition(nets):
    """A netlist reduced to what it really is: a partition of cell pins."""
    return {frozenset((c["instance"], c["pin"]) for c in net["connections"])
            for net in nets}


def run(target):
    config = TARGETS[target]
    instances_path = os.path.join("out", target, "instances.json")
    if not os.path.exists(instances_path):
        sys.exit(f"{instances_path} missing, run tools/stage1_cells.py {target} first")
    with open(instances_path, encoding="utf-8") as handle:
        stage1 = json.load(handle)

    print(f"target   {target}")
    print(f"layout   {config['gds']}")
    print(f"stage 1  {len(stage1['instances'])} instances\n")

    library, top, rects, layer_of, report = collect(config["gds"])
    print(f"conductor polygons {report['polygons']}, "
          f"sliced into {report['rectangles']} rectangles")
    if report["not_rectilinear"]:
        print("  NOT RECTILINEAR, not sliced:",
              dict(Counter(report["not_rectilinear"])))

    sets, corner_only = connect(rects, layer_of)
    if corner_only:
        print(f"corner-only contacts, not treated as connections: {corner_only}")

    lef = load_lef(PDK_DIR)
    used = {record["cell"] for record in stage1["instances"]}
    pads, clashes = cellnodes.build(used, PDK_DIR, lef)
    if pads:
        print("\ncell terminal map, undeclared pads treated as their pin:")
        for name, entries in sorted(pads.items()):
            print(f"  {name}: {sorted({entry['pin'] for entry in entries})}")
    if clashes:
        for name, clash in sorted(clashes.items()):
            print(f"  {name}: node spans declared pins {clash}, left as declared")

    joined, missing = bridge_terminals(top, rects, layer_of, sets, stage1, pads)
    if joined:
        print(f"  joined {joined} pad(s) to the set holding their declared pin")
    if missing:
        print(f"  PADS NOT FOUND IN THE LAYOUT: {dict(missing)}")

    components = {sets.find(index) for index in range(len(rects))}
    print(f"\nconnected components {len(components)}")

    connections, names, linked, unplaced, homeless = attribute(
        top, rects, layer_of, sets, stage1)
    print(f"\nplacements linked to stage 1: {linked}")
    if unplaced:
        print("  not linked, expected to be routing vias only:")
        for name, count in unplaced.most_common(5):
            print(f"    {count:6d}  {name}")
    if homeless:
        print("  PIN LABELS LANDING ON NO SHAPE:")
        for name, count in homeless.most_common(10):
            print(f"    {count:6d}  {name}")

    nets = []
    for root, pins in connections.items():
        name = names.get(root, f"$uf{root}")
        nets.append({
            "name": name,
            "named": root in names,
            "kind": "power" if name in POWER else "signal",
            "connections": sorted(
                ({"instance": i, "cell": c, "pin": p} for i, c, p in pins),
                key=lambda c: (c["instance"], c["pin"])),
        })

    signal = [n for n in nets if n["kind"] == "signal"]
    print(f"\nnets carrying at least one cell pin: {len(nets)}")
    print(f"  signal {len(signal)}")
    print(f"  power  {len(nets) - len(signal)}")
    print(f"  named  {sum(1 for n in nets if n['named'])}")

    out_dir = os.path.join("out", target)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "netlist_unionfind.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump({"target": target, "method": "union find over flat geometry",
                   "source_gds": config["gds"],
                   "connectivity": [list(entry) for entry in STACK],
                   "nets": nets}, handle, indent=1)
    print(f"\nwrote {out_path}")

    # --- the point of the exercise: do the two extractors agree? -------------
    primary_path = os.path.join(out_dir, "netlist.json")
    if not os.path.exists(primary_path):
        print(f"\n{primary_path} missing, run tools/stage2_nets.py {target} "
              "to compare the two extractions")
        return 0

    with open(primary_path, encoding="utf-8") as handle:
        primary = json.load(handle)

    ours = as_partition(nets)
    theirs = as_partition(primary["nets"])
    cell_of = {record["id"]: record["cell"] for record in stage1["instances"]}

    print("\n=== union find vs KLayout, as partitions of cell pins ===")
    print(f"KLayout   {len(theirs)} nets")
    print(f"union find {len(ours)} nets")
    print(f"identical  {len(ours & theirs)}")

    only_ours = ours - theirs
    only_theirs = theirs - ours
    if not only_ours and not only_theirs:
        print("\nRESULT: the two extractions agree exactly")
        return 0

    # A net one side reports and the other never mentions at all is a
    # difference in what gets listed, not a disagreement about what is wired to
    # what. Working flat, this extractor sees a cell output that reaches nothing
    # as a net of one pin; the hierarchical extractor gives that pin no
    # top level net and so omits it. Both are saying the terminal is unconnected.
    #
    # The distinction is only safe if the pin really is absent from the other
    # netlist rather than sitting in some other net, so that is checked and not
    # assumed.
    their_pins = {pin for net in theirs for pin in net}
    our_pins = {pin for net in ours for pin in net}

    def unlisted(group, other_pins):
        return {net for net in group
                if len(net) == 1 and not (net & other_pins)}

    ours_unlisted = unlisted(only_ours, their_pins)
    theirs_unlisted = unlisted(only_theirs, our_pins)
    conflict_ours = only_ours - ours_unlisted
    conflict_theirs = only_theirs - theirs_unlisted

    if ours_unlisted or theirs_unlisted:
        print(f"\n  unconnected terminals listed by one side only: "
              f"{len(ours_unlisted)} union find, {len(theirs_unlisted)} KLayout")
        cells = Counter(cell_of.get(next(iter(net))[0], "?")
                        for net in ours_unlisted | theirs_unlisted)
        for cell, count in cells.most_common(5):
            print(f"    {count:4d}  {cell.split('__')[-1]}")

    if not conflict_ours and not conflict_theirs:
        print("\nRESULT: the two extractions agree on every connection")
        return 0

    print(f"\n  only union find: {len(conflict_ours)}")
    print(f"  only KLayout:    {len(conflict_theirs)}")
    only_ours, only_theirs = conflict_ours, conflict_theirs

    def describe(net):
        pins = sorted(net)
        shown = ", ".join(f"{i}.{p}" for i, p in pins[:6])
        return f"{len(pins):3d} pins: {shown}{' ...' if len(pins) > 6 else ''}"

    for label, group in (("only union find", only_ours),
                         ("only KLayout", only_theirs)):
        for net in sorted(group, key=len, reverse=True)[:8]:
            print(f"    [{label}] {describe(net)}")

    print("\nRESULT: the two extractions disagree, investigate before trusting either")
    return 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage2_unionfind.py [{' | '.join(TARGETS)}]")
    sys.exit(run(args[0]))
