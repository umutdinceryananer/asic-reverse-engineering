"""Re-measure the met2 emblem in both layouts and prove they are equal up to translation.

docs/references.md section 5.1 identifies the emblem as the Jane Street logo;
this tool does not repeat that identification. It re-measures what can be
measured locally: from each layout's top cell it takes every 0.30 x 0.30 um
square drawn on met2 (69/20) inside the documented emblem window (warmup
origin (65.90, 66.20), puzzle origin (34.90, 35.20), span 17.10 x 17.10 um),
snaps each square to the 0.30 um pitch grid, and asserts the two pixel sets
are equal up to translation. Expected from the docs: 57 x 57 grid, 1366 of
3249 pixels set.

Usage:
    python tools/egg_emblem_check.py             # the check, both layouts
    python tools/egg_emblem_check.py --control   # same extractor on windows
                                                 # away from the emblem: must
                                                 # find no pixel field
    python tools/egg_emblem_check.py --selftest  # perturb one pixel in memory:
                                                 # the equality must fail
"""

import sys
from collections import deque
from pathlib import Path

import gdstk

MET2 = (69, 20)
PITCH = 0.30
SPAN = 17.10
TOL = 0.001  # 1 nm: snap and size tolerance

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {
    "warmup": (str(ROOT / "puzzle/warmup/04_final.gds"), (65.90, 66.20)),
    "puzzle": (str(ROOT / "puzzle/puzzle.gds"), (34.90, 35.20)),
}
CONTROL_ORIGIN = (10.00, 10.00)  # same-size window, inside both dies,
                                 # disjoint from both emblem windows


def extract(path, origin):
    """Pixel set of snapped 0.3 um met2 squares in the window at origin.

    Returns (pixels, stats): pixels is a set of (col, row); stats counts what
    the top cell(s) own on met2 and how the window filtered it.
    """
    library = gdstk.read_gds(path)
    ox, oy = origin
    pixels = set()
    stats = {"top_met2_polygons": 0, "in_window": 0, "squares": 0,
             "off_grid": 0, "top_cells": []}
    for cell in library.top_level():
        stats["top_cells"].append(cell.name)
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != MET2:
                continue
            stats["top_met2_polygons"] += 1
            (x0, y0), (x1, y1) = poly.bounding_box()
            if x0 < ox - TOL or x1 > ox + SPAN + TOL:
                continue
            if y0 < oy - TOL or y1 > oy + SPAN + TOL:
                continue
            stats["in_window"] += 1
            w, h = x1 - x0, y1 - y0
            if abs(w - PITCH) > TOL or abs(h - PITCH) > TOL:
                continue
            if abs(poly.area() - PITCH * PITCH) > TOL:
                continue  # bbox is a square but the polygon is not
            stats["squares"] += 1
            col = (x0 - ox) / PITCH
            row = (y0 - oy) / PITCH
            if abs(col - round(col)) * PITCH > TOL or abs(row - round(row)) * PITCH > TOL:
                stats["off_grid"] += 1
                continue
            pixels.add((int(round(col)), int(round(row))))
    return pixels, stats


def normalise(pixels):
    """Translate so the minimum column and row are zero."""
    if not pixels:
        return frozenset()
    c0 = min(c for c, _ in pixels)
    r0 = min(r for _, r in pixels)
    return frozenset((c - c0, r - r0) for c, r in pixels)


def dims(pixels):
    if not pixels:
        return (0, 0)
    return (max(c for c, _ in pixels) + 1 - min(c for c, _ in pixels),
            max(r for _, r in pixels) + 1 - min(r for _, r in pixels))


def components(pixels):
    """Number of 4-connected components."""
    todo = set(pixels)
    n = 0
    while todo:
        n += 1
        queue = deque([todo.pop()])
        while queue:
            c, r = queue.popleft()
            for nb in ((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)):
                if nb in todo:
                    todo.remove(nb)
                    queue.append(nb)
    return n


def check():
    results = {}
    ok = True
    for name, (path, origin) in TARGETS.items():
        pixels, stats = extract(path, origin)
        norm = normalise(pixels)
        w, h = dims(norm)
        comp = components(norm)
        results[name] = norm
        print(f"{name}: {path}")
        print(f"  top cell(s): {', '.join(stats['top_cells'])}, "
              f"own met2 polygons: {stats['top_met2_polygons']}")
        print(f"  window origin ({origin[0]:.2f}, {origin[1]:.2f}), span {SPAN:.2f}: "
              f"{stats['in_window']} met2 polygons inside, "
              f"{stats['squares']} are {PITCH:.2f} um squares, "
              f"{stats['off_grid']} off grid")
        print(f"  grid {w} x {h} = {w * h}, ink {len(norm)} "
              f"({100.0 * len(norm) / (w * h):.2f}%), "
              f"4-connected components: {comp}")
        for label, got, want in (("grid", (w, h), (57, 57)),
                                 ("ink", len(norm), 1366),
                                 ("components", comp, 3)):
            if got != want:
                ok = False
                print(f"  FAIL: {label} = {got}, expected {want}")
    equal = results["warmup"] == results["puzzle"]
    print(f"\npixel sets equal up to translation: {'YES' if equal else 'NO'}")
    if not equal:
        only_w = len(results["warmup"] - results["puzzle"])
        only_p = len(results["puzzle"] - results["warmup"])
        print(f"  warmup-only pixels: {only_w}, puzzle-only pixels: {only_p}")
        ok = False
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def control():
    """The same extractor over a met2 window away from the emblem."""
    ok = True
    for name, (path, origin) in TARGETS.items():
        cox, coy = CONTROL_ORIGIN
        # refuse a control window that overlaps the emblem window
        if abs(cox - origin[0]) < SPAN and abs(coy - origin[1]) < SPAN:
            sys.exit(f"control window overlaps the emblem window for {name}")
        pixels, stats = extract(path, CONTROL_ORIGIN)
        print(f"{name} control: window origin ({cox:.2f}, {coy:.2f}), span {SPAN:.2f}: "
              f"{stats['in_window']} met2 polygons inside, "
              f"{stats['squares']} snapped squares, pixel field size {len(pixels)}")
        if len(pixels) != 0:
            ok = False
            print(f"  FAIL: control window contains a pixel field")
    print("CONTROL PASS: no pixel field outside the emblem window"
          if ok else "CONTROL FAIL")
    return 0 if ok else 1


def selftest():
    failures = []

    # component counter on hand-made patterns
    three = {(0, 0), (0, 1), (5, 5), (5, 6), (10, 0)}
    if components(three) != 3:
        failures.append("components on 3-blob pattern")
    if components({(0, 0), (1, 0), (1, 1)}) != 1:
        failures.append("components on 1-blob pattern")
    if components(set()) != 0:
        failures.append("components on empty set")

    # equality up to translation on synthetic sets
    a = {(2, 3), (2, 4), (7, 7)}
    b = {(c + 10, r + 20) for c, r in a}  # pure translation
    if normalise(a) != normalise(b):
        failures.append("translated copy compares equal")

    # the required test: one pixel perturbed in memory, on the real extraction
    pixels, _ = extract(*TARGETS["warmup"])
    perturbed = set(pixels)
    moved = min(perturbed)
    perturbed.remove(moved)
    empty = next((c, r) for c in range(60) for r in range(60)
                 if (c, r) not in pixels)
    perturbed.add(empty)
    if normalise(pixels) == normalise(perturbed):
        failures.append("one-pixel perturbation must break equality")
    else:
        print(f"perturbation: moved pixel {moved} to {empty} in a copy of the "
              f"warmup extraction; equality check failed as required")

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}")
        return 1
    print("selftest: 5 of 5 checks passed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        sys.exit(selftest())
    if len(sys.argv) == 2 and sys.argv[1] == "--control":
        sys.exit(control())
    if len(sys.argv) != 1:
        sys.exit(__doc__)
    sys.exit(check())
