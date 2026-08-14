"""Shared GDS geometry helpers: orientations, footprints, fingerprints.

The orientation handling is the fiddly part and it is centralised here so that
every stage agrees on it.

A placement transform is one of the eight symmetries of a rectangle: mirror
about the x axis or not, times a rotation by 0, 90, 180 or 270 degrees. GDS
stores the pair, DEF and LEF give it a name. Because these eight form a group,
transforms compose, which matters in stage 1: if a cell *definition* turns out
to be stored in some orientation relative to the PDK original, then the
orientation of a *placement* of it is the composition of the two.

Composition is done by 2x2 integer matrix multiplication rather than by a hand
written case table, because a case table for a group of order eight is a
reliable source of quiet bugs.
"""

import hashlib

import gdstk

AREAID_SC = (81, 4)
NWELL = (64, 20)
DIFF = (65, 20)
POLY = (66, 20)
LICON = (66, 44)
LI1 = (67, 20)
MCON = (67, 44)

# Layers used for the fallback fingerprint.
#
# The PDK revision that drew the puzzle is not exactly the one we fetch, and the
# drift shows up on `poly`, `licon1` and `npc` as small shape edits of the kind a
# DRC fix produces. The layers below carried through unchanged on every cell
# where that happened, and between them `diff` and `li1` still encode the
# series/parallel wiring that separates a gate from its dual. Excluding poly
# loses the gate shapes, which is why this tier also pins the transistor count
# and the pin names.
STABLE_LAYERS = {NWELL, DIFF, LI1, MCON}

# Pin names live on the li1 and met1 label purposes.
LABEL_LAYERS = {67, 68}
LABEL_TEXTTYPE = 5

# (mirrored about x, rotation in degrees) -> DEF/LEF orientation name.
DEF_NAME = {
    (False, 0): "N",
    (False, 90): "W",
    (False, 180): "S",
    (False, 270): "E",
    (True, 0): "FS",
    (True, 90): "FW",
    (True, 180): "FN",
    (True, 270): "FE",
}

ORIENTATIONS = list(DEF_NAME)

_ROTATION = {
    0: (1, 0, 0, 1),
    90: (0, -1, 1, 0),
    180: (-1, 0, 0, -1),
    270: (0, 1, -1, 0),
}
_MIRROR_X = (1, 0, 0, -1)
_IDENTITY = (1, 0, 0, 1)


def _matmul(a, b):
    return (
        a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
        a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
    )


def matrix(orientation):
    """Matrix for an orientation, mirror applied first then rotation."""
    mirrored, rotation = orientation
    return _matmul(_ROTATION[rotation], _MIRROR_X if mirrored else _IDENTITY)


_BY_MATRIX = {matrix(o): o for o in ORIENTATIONS}


def compose(first, second):
    """Orientation of applying `first`, then `second`."""
    return _BY_MATRIX[_matmul(matrix(second), matrix(first))]


def transform(x, y, orientation):
    a, b, c, d = matrix(orientation)
    return a * x + b * y, c * x + d * y


def from_reference(reference):
    """Orientation of a gdstk placement, as a (mirrored, rotation) pair."""
    import math
    rotation = round(math.degrees(reference.rotation)) % 360
    if rotation not in _ROTATION:
        raise ValueError(f"unsupported rotation {rotation}")
    return (bool(reference.x_reflection), rotation)


def bounds(polygons):
    boxes = [p.bounding_box() for p in polygons]
    return (min(b[0][0] for b in boxes), min(b[0][1] for b in boxes),
            max(b[1][0] for b in boxes), max(b[1][1] for b in boxes))


def footprint(cell):
    """The cell's official rectangle, from areaid.sc, else its full extent."""
    marked = [p for p in cell.polygons if (p.layer, p.datatype) == AREAID_SC]
    return bounds(marked or cell.polygons) if cell.polygons else None


def placed_lower_left(box, origin, orientation):
    """Lower left corner of a footprint once placed, the point DEF records."""
    x0, y0, x1, y1 = box
    corners = [transform(x, y, orientation)
               for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    return (round(min(c[0] for c in corners) + origin[0], 3),
            round(min(c[1] for c in corners) + origin[1], 3))


def digest(cell, orientation=(False, 0), layers=None):
    """Hash of a cell's geometry under an orientation, translation removed.

    Coordinates are snapped to the 1 nm database grid before hashing so two
    identical cells cannot differ by a floating point hair. The shape is
    translated using the whole cell's extent, not just the selected layers, so
    that a subset hash still sits in the cell's own frame and stays comparable.

    `layers` restricts the hash to a set of (layer, datatype) pairs.
    """
    if not cell.polygons:
        return None

    shapes = []
    extent = []
    for polygon in cell.polygons:
        points = [transform(x, y, orientation) for x, y in polygon.points]
        extent.extend(points)
        if layers is None or (polygon.layer, polygon.datatype) in layers:
            shapes.append((polygon.layer, polygon.datatype, points))
    if not shapes:
        return None

    ox = min(p[0] for p in extent)
    oy = min(p[1] for p in extent)

    canonical = sorted(
        (layer, datatype,
         tuple(sorted((round((x - ox) * 1000), round((y - oy) * 1000))
                      for x, y in points)))
        for layer, datatype, points in shapes
    )
    return hashlib.sha256(repr(canonical).encode()).hexdigest()[:16]


def on_layer(cell, key):
    return [p for p in cell.polygons if (p.layer, p.datatype) == key]


def transistors(cell):
    """(total, pmos, nmos), counted as poly-over-diff crossings."""
    poly, diff = on_layer(cell, POLY), on_layer(cell, DIFF)
    if not poly or not diff:
        return 0, 0, 0
    gates = gdstk.boolean(poly, diff, "and")
    nwell = on_layer(cell, NWELL)
    pmos = len(gdstk.boolean(gates, nwell, "and")) if nwell else 0
    return len(gates), pmos, len(gates) - pmos


def pin_names(cell):
    """The set of pin labels a cell carries, which no transform changes."""
    return tuple(sorted({
        label.text for label in cell.labels
        if label.layer in LABEL_LAYERS and label.texttype == LABEL_TEXTTYPE
    }))


def structural_key(cell, orientation=(False, 0)):
    """Fallback identity: stable layers, plus pin names and transistor count.

    Alone, the stable layer hash leaves ten pairs of cells tied, all of them
    low power isolation cells drawn identically to a plain logic gate. Adding
    the pin names and the transistor count separates every one of them.
    """
    key = digest(cell, orientation, STABLE_LAYERS)
    if key is None:
        return None
    return (key, pin_names(cell), transistors(cell)[0])


def fingerprint_index(cells, key_function=digest):
    """key -> (cell name, orientation the cell is drawn in), over all eight.

    Indexing every orientation means a definition stored rotated or mirrored
    relative to the library original still resolves, and tells us which
    orientation it is in so a placement's own transform can be composed onto it.

    Keys that would land on more than one library cell are dropped rather than
    resolved arbitrarily; an ambiguous fingerprint is not an identification.
    """
    index = {}
    ambiguous = set()
    for cell in cells:
        for orientation in ORIENTATIONS:
            key = key_function(cell, orientation)
            if key is None:
                continue
            previous = index.get(key)
            if previous is None:
                index[key] = (cell.name, orientation)
            elif previous[0] != cell.name:
                ambiguous.add(key)
    for key in ambiguous:
        index.pop(key, None)
    return index
