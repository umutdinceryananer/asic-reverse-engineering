"""Which li1 shapes of a library cell are the same terminal as a declared pin.

The problem this exists to solve, found by the union find fallback disagreeing
with the KLayout extraction on the puzzle:

A cell's input is a transistor gate. The gate is one poly shape, and it can be
contacted from li1 in more than one place. The LEF declares only some of those
contacts as the pin -- for `a31oi_2` the A1 port is one rectangle, while a
second li1 pad sits over the same poly and is not offered as a pin. The router
nevertheless landed a via on that second pad.

Stage 2's connectivity stack starts at li1 and deliberately excludes poly,
because cells are black boxes. That is the right model, but it means two li1
pads on one gate look like two unrelated nets. The consequence measured on the
puzzle: net `$1447` reached `a31oi_2.A1` and `a311o_2.A1` and had **no driver at
all**, while the signal that really drives it sat in a different net. That is
precisely the "floating pins from an overly strict connectivity rule" failure
`docs/solver-pipeline.md` names.

The obvious repair -- extend the stack down through licon1 to poly -- was tried
and rejected. It does fix this, and leaves the warm up bit for bit identical,
but it also dissolves `conb_1`: that cell ties its constant outputs to the rails
through poly, so `LO` merges into `VGND` and `HI` into `VPWR`, and the extractor
starts reporting pins named `LO,VGND`. A gate level netlist needs `conb_1` to
stay a cell with outputs.

So the rule is narrower, and it is a rule about cells rather than about layers:

    Two li1 shapes joined by a poly gate are the same terminal.
    Two DECLARED pins of one cell are never the same net; if the grouping says
    they are, the model has reached inside the cell and the group is discarded.

Only gate contacts count. Diffusion contacts are left alone, because joining
source and drain shapes would conduct through transistors and short the design
together.

What comes out is a list of "extra pads" per cell: points that are electrically
a declared pin but lie outside the pin's declared rectangles. An extractor can
probe those points and merge whatever it finds there into the pin's net.
"""

import os

import gdstk

LI1 = (67, 20)
LICON1 = (66, 44)
POLY = (66, 20)


def _boxes(polygons):
    return [(p.bounding_box(), p) for p in polygons]


def _centre(box):
    (x0, y0), (x1, y1) = box
    return (round((x0 + x1) / 2, 4), round((y0 + y1) / 2, 4))


def _bbox_overlap(a, b):
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    return ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1


def _touches(a, b):
    """Exact contact test, bounding boxes first because most pairs miss."""
    if not _bbox_overlap(a[0], b[0]):
        return False
    return len(gdstk.boolean([a[1]], [b[1]], "and")) > 0


def _covers(shape, rects):
    """Does this drawn li1 shape carry any of a pin's declared rectangles?

    Overlap, not containment: a LEF PORT is a set of rectangles saying where the
    pin may be contacted, and the drawn polygon is usually their union and often
    larger. `conb_1`'s ground shape spans both of VGND's rectangles and extends
    past them, so a containment test assigned it to no pin at all -- which hid
    the very conflict the caller depends on.

    Exact overlap, not bounding boxes. These shapes are frequently L shaped and
    their boxes overlap pins they do not touch: `conb_1`'s ground shape has a
    box reaching up into HI's rectangle while the polygon itself stays clear.
    Bounding boxes are used only to skip pairs that cannot possibly meet.
    """
    box, polygon = shape
    for rx0, ry0, rx1, ry1 in rects:
        if not _bbox_overlap(box, ((rx0, ry0), (rx1, ry1))):
            continue
        rectangle = gdstk.rectangle((rx0, ry0), (rx1, ry1))
        if gdstk.boolean([polygon], [rectangle], "and"):
            return True
    return False


def extra_pads(cell, lef_entry):
    """li1 pads that are electrically a declared pin but sit outside it.

    Each entry is {"pin", "pad", "anchor"}: the pin's name, the centre of the
    undeclared pad, and the centre of a shape that *is* the declared pin on the
    same node. Both points are in the cell's own coordinates. An extractor needs
    the anchor as well as the pad, because knowing the pad is A1 is not enough:
    the two sit in different extracted nets and something has to join them.

    Also returns the groups rejected for spanning two declared pins, so a caller
    can report them rather than have them disappear.
    """
    li1 = _boxes([p for p in cell.polygons if (p.layer, p.datatype) == LI1])
    licon = _boxes([p for p in cell.polygons if (p.layer, p.datatype) == LICON1])
    poly = _boxes([p for p in cell.polygons if (p.layer, p.datatype) == POLY])
    if not li1 or not licon or not poly:
        return [], []

    # Which gate does each li1 shape reach, through a contact?
    on_gate = {}
    for gate_index, gate in enumerate(poly):
        for contact in licon:
            if not _touches(contact, gate):
                continue
            for shape_index, shape in enumerate(li1):
                if _touches(shape, contact):
                    on_gate.setdefault(gate_index, set()).add(shape_index)

    # Group transitively, not one poly at a time. A single li1 shape can sit on
    # two gates and so tie them together, and taking each gate in isolation
    # misses that. `conb_1` is exactly this case: its constant outputs reach the
    # rails through a chain of poly and li1, and only the transitive grouping
    # shows that `LO` and `VGND` are one node -- which is what makes the guard
    # below reject it instead of quietly rewriting a cell output into a rail.
    parent = list(range(len(li1)))

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for members in on_gate.values():
        members = sorted(members)
        for other in members[1:]:
            parent[find(other)] = find(members[0])

    groups = {}
    for shape_index in range(len(li1)):
        groups.setdefault(find(shape_index), set()).add(shape_index)

    ports = {name: info.get("ports", {}).get("li1", [])
             for name, info in lef_entry["pins"].items()}
    # Every pin a shape carries, not the first one found: a shape matching two
    # declared pins is itself a contradiction and has to stay visible.
    pin_of = {}
    for shape_index, shape in enumerate(li1):
        matched = {name for name, rects in ports.items()
                   if rects and _covers(shape, rects)}
        if matched:
            pin_of[shape_index] = matched

    pads = []
    conflicts = []
    for members in groups.values():
        if len(members) < 2:
            continue
        named = set()
        for shape_index in members:
            named |= pin_of.get(shape_index, set())
        if len(named) > 1:
            # Two declared pins in one node. Either the cell really ties them
            # together, as conb_1 does, or the grouping has reached somewhere it
            # should not. Both mean: leave this cell's pins as declared.
            conflicts.append(sorted(named))
            continue
        if len(named) != 1:
            continue
        pin = named.pop()
        declared_shapes = [i for i in members if i in pin_of]
        undeclared = [i for i in members if i not in pin_of]
        if not declared_shapes or not undeclared:
            continue
        anchor = _centre(li1[declared_shapes[0]][0])
        for shape_index in undeclared:
            pads.append({"pin": pin, "pad": _centre(li1[shape_index][0]),
                         "anchor": anchor})
    return pads, conflicts


def build(cell_names, pdk_dir, lef):
    """Cell name -> extra pads, for the cells a target actually uses."""
    table = {}
    conflicts = {}
    for name in sorted(cell_names):
        path = os.path.join(pdk_dir, f"{name}.gds")
        if not os.path.exists(path) or name not in lef:
            continue
        library = gdstk.read_gds(path)
        cell = next((c for c in library.cells if c.name == name), None)
        if cell is None:
            continue
        pads, clash = extra_pads(cell, lef[name])
        if pads:
            table[name] = pads
        if clash:
            conflicts[name] = clash
    return table, conflicts
