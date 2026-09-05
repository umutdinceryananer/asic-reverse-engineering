#!/usr/bin/env python3
"""egg_bitmap.py -- generalized bitmap scan over a GDS layout.

Looks for "pixel fields": >= MIN_INK identical (or, in the relaxed pass,
merged-rectangle) axis-aligned near-square polygons whose centers sit on a
uniform pitch lattice with sane dimensions and fill.  The known Jane Street
emblem (met2, both layouts) must be re-found; anything else is a candidate.

Passes
  strict   one exact square size per field
  relaxed  rectangles whose sides are 1..MAX_MULT integer multiples of a unit
           are decomposed into unit pixels first (catches merged rectangles)

Modes
  egg_bitmap.py warmup|puzzle            top-cell-owned geometry, all layers
  egg_bitmap.py warmup|puzzle --flat     hierarchy flattened, all layers
  egg_bitmap.py warmup|puzzle --control  hierarchy flattened, li1/met1 drawing
                                         only (67/20, 68/20): standard-cell
                                         routing must NOT register
  egg_bitmap.py --selftest               planted 20x20 found; merged variant
                                         found only by relaxed; fixed-seed
                                         scattered squares rejected

Every declared field is rendered as ASCII art to
  out/eggs/bitmap_<target>_<layer>_<dt>[_relaxed][_flat].txt
and reported as one JSON line on stdout.
"""

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGETS = {
    "warmup": REPO / "puzzle" / "warmup" / "04_final.gds",
    "puzzle": REPO / "puzzle" / "puzzle.gds",
}
OUT_DIR = REPO / "out" / "eggs"

MIN_INK = 50          # squares needed before a field is declared
MAX_DIM = 1024        # rows/cols above this is a snap grid, not a picture
MIN_FILL = 0.10       # ink / (rows*cols)
MIN_DIM = 2           # a picture is 2-D; 1-D rows are not this detector's job
SQ_RATIO = 1.2        # near-square: max side / min side
MAX_MULT = 4          # relaxed: sides up to this many units
MIN_UNIT_COUNT = 10   # relaxed: a unit candidate needs this many rects
CONTROL_LAYERS = {(67, 20), (68, 20)}  # li1, met1 drawing


# ---------------------------------------------------------------- geometry --

def collect_rects(gds_path, flat):
    """(layer, dt) -> list of (x0, y0, x1, y1) in nm ints, rectangles only."""
    import gdstk

    lib = gdstk.read_gds(str(gds_path))
    tops = lib.top_level()
    rects = defaultdict(list)
    for top in tops:
        polys = top.get_polygons(depth=None) if flat else top.polygons
        for poly in polys:
            pts = poly.points
            if len(pts) != 4:
                continue
            xs = sorted({int(round(v * 1000)) for v in pts[:, 0]})
            ys = sorted({int(round(v * 1000)) for v in pts[:, 1]})
            if len(xs) != 2 or len(ys) != 2:
                continue
            rects[(poly.layer, poly.datatype)].append((xs[0], ys[0], xs[1], ys[1]))
    return rects


def lattice_pitch(values):
    """gcd of gaps between sorted unique coordinates; None if < 2 values."""
    if len(values) < 2:
        return None
    pitch = 0
    for a, b in zip(values, values[1:]):
        pitch = math.gcd(pitch, b - a)
    return pitch or None


def fit_grid(centers, unit_w, unit_h):
    """Try to explain center points (2*nm ints) as a uniform-pitch bitmap."""
    centers = sorted(set(centers))
    xs = sorted({c[0] for c in centers})
    ys = sorted({c[1] for c in centers})
    px = lattice_pitch(xs)
    py = lattice_pitch(ys)
    if px is None or py is None:
        return None, "one-dimensional"
    # centers are stored doubled (2*nm) so odd nm centers stay integral
    if px < 2 * unit_w or py < 2 * unit_h:
        return None, "pitch below pixel size (overlapping lattice)"
    cols = (xs[-1] - xs[0]) // px + 1
    rows = (ys[-1] - ys[0]) // py + 1
    if cols < MIN_DIM or rows < MIN_DIM:
        return None, "not two-dimensional"
    if cols > MAX_DIM or rows > MAX_DIM:
        return None, f"grid {rows}x{cols} exceeds {MAX_DIM} (snap grid, not a picture)"
    occupied = {((c[1] - ys[0]) // py, (c[0] - xs[0]) // px) for c in centers}
    fill = len(occupied) / (rows * cols)
    if len(occupied) < MIN_INK:
        return None, "too few distinct pixels"
    if fill < MIN_FILL:
        return None, f"fill {fill:.4f} below {MIN_FILL}"
    return {
        "rows": int(rows), "cols": int(cols),
        "pitch_x_nm": px / 2, "pitch_y_nm": py / 2,
        "origin_nm": (xs[0] / 2, ys[0] / 2),
        "occupied": occupied,
        "ink": len(occupied),
        "fill": round(fill, 4),
        "components": count_components(occupied),
    }, None


def count_components(occupied):
    seen = set()
    n = 0
    for cell in occupied:
        if cell in seen:
            continue
        n += 1
        stack = [cell]
        seen.add(cell)
        while stack:
            r, c = stack.pop()
            for nb in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if nb in occupied and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
    return n


# --------------------------------------------------------------- detection --

def strict_fields(rect_list):
    """One exact size per field. Yields (field, size_nm, n_sizes=1, why)."""
    by_size = defaultdict(list)
    for x0, y0, x1, y1 in rect_list:
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0 or max(w, h) / min(w, h) > SQ_RATIO:
            continue
        by_size[(w, h)].append((x0 + x1, y0 + y1))  # doubled center
    out = []
    for (w, h), centers in sorted(by_size.items()):
        if len(centers) < MIN_INK:
            continue
        field, why = fit_grid(centers, w, h)
        out.append(((w, h), len(centers), field, why))
    return out


def relaxed_fields(rect_list):
    """Decompose integer-multiple rectangles into unit pixels, then fit."""
    dims = Counter()
    for x0, y0, x1, y1 in rect_list:
        dims[min(x1 - x0, y1 - y0)] += 1
    candidates = [u for u, n in dims.most_common() if n >= MIN_UNIT_COUNT][:6]
    out = []
    for u in candidates:
        pixels = []
        sizes_used = set()
        for x0, y0, x1, y1 in rect_list:
            w, h = x1 - x0, y1 - y0
            if w % u or h % u:
                continue
            a, b = w // u, h // u
            if not (1 <= a <= MAX_MULT and 1 <= b <= MAX_MULT):
                continue
            sizes_used.add((w, h))
            for i in range(a):
                for j in range(b):
                    pixels.append((2 * x0 + (2 * i + 1) * u,
                                   2 * y0 + (2 * j + 1) * u))
        if len(pixels) < MIN_INK:
            continue
        field, why = fit_grid(pixels, u, u)
        out.append(((u, u), len(pixels), field, why, len(sizes_used)))
    return out


def render(field, path, header_lines):
    rows, cols, occ = field["rows"], field["cols"], field["occupied"]
    lines = list(header_lines)
    for r in range(rows - 1, -1, -1):  # top of chip first
        lines.append("".join("#" if (r, c) in occ else "." for c in range(cols)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def scan(target, gds_path, flat, control):
    rects = collect_rects(gds_path, flat=flat or control)
    if control:
        rects = {k: v for k, v in rects.items() if k in CONTROL_LAYERS}
    suffix = "_flat" if flat else ("_control" if control else "")
    found = []
    for (layer, dt) in sorted(rects):
        rect_list = rects[(layer, dt)]
        for (w, h), n_raw, field, why in strict_fields(rect_list):
            tag = f"L{layer}/{dt} strict size={w}x{h}nm n={n_raw}"
            if field is None:
                print(f"  reject {tag}: {why}")
                continue
            emit(target, "strict", layer, dt, (w, h), 1, field, suffix, found)
        for (u, _), n_px, field, why, n_sizes in relaxed_fields(rect_list):
            tag = f"L{layer}/{dt} relaxed unit={u}nm pixels={n_px} sizes={n_sizes}"
            if field is None:
                print(f"  reject {tag}: {why}")
                continue
            emit(target, "relaxed", layer, dt, (u, u), n_sizes, field, suffix, found)
    return found


def emit(target, mode, layer, dt, size, n_sizes, field, suffix, found):
    rec = {
        "target": target, "pass": mode, "layer": layer, "datatype": dt,
        "unit_nm": size[0], "unit_h_nm": size[1], "distinct_sizes": n_sizes,
        "rows": field["rows"], "cols": field["cols"],
        "pitch_x_nm": field["pitch_x_nm"], "pitch_y_nm": field["pitch_y_nm"],
        "origin_nm": list(field["origin_nm"]),
        "ink": field["ink"], "fill": field["fill"],
        "components": field["components"],
    }
    name = f"bitmap_{target}_{layer}_{dt}"
    if mode == "relaxed":
        name += "_relaxed"
    name += f"{suffix}.txt"
    out = OUT_DIR / name
    hdr = [f"# {json.dumps(rec, sort_keys=True)}"]
    render(field, out, hdr)
    rec["render"] = str(out)
    found.append(rec)
    print("FIELD " + json.dumps(rec, sort_keys=True))


# ---------------------------------------------------------------- selftest --

def selftest():
    rng = random.Random(20260905)
    failures = []

    # 1. planted 20x20 bitmap, unit 300 nm, pitch 300 nm, ~55% fill
    occ = {(r, c) for r in range(20) for c in range(20) if rng.random() < 0.55}
    occ |= {(0, 0), (19, 19)}  # pin the extent
    planted = [(c * 300, r * 300, c * 300 + 300, r * 300 + 300) for r, c in occ]
    hits = [f for _, _, f, _ in strict_fields(planted) if f]
    ok = (len(hits) == 1 and hits[0]["rows"] == 20 and hits[0]["cols"] == 20
          and hits[0]["ink"] == len(occ))
    print(f"selftest 1 planted 20x20 ({len(occ)} ink): "
          f"{'found' if ok else 'FAILED'} "
          f"{[(h['rows'], h['cols'], h['ink']) for h in hits]}")
    if not ok:
        failures.append("planted bitmap not found")

    # 2. same bitmap with horizontal runs merged into rectangles:
    #    strict must not see the full field, relaxed must recover it exactly
    merged = []
    for r in range(20):
        c = 0
        while c < 20:
            if (r, c) in occ:
                run = c
                while run < 20 and (r, run) in occ and run - c < MAX_MULT:
                    run += 1
                merged.append((c * 300, r * 300, run * 300, r * 300 + 300))
                c = run
            else:
                c += 1
    s_hits = [f for _, _, f, _ in strict_fields(merged) if f and f["ink"] == len(occ)]
    r_hits = [f for _, _, f, _, _ in relaxed_fields(merged)
              if f and f["rows"] == 20 and f["cols"] == 20 and f["ink"] == len(occ)]
    ok = not s_hits and len(r_hits) >= 1
    print(f"selftest 2 merged rects ({len(merged)} rects): strict full-field "
          f"{len(s_hits)} (want 0), relaxed exact {len(r_hits)} (want >=1): "
          f"{'ok' if ok else 'FAILED'}")
    if not ok:
        failures.append("merged-rectangle recovery wrong")

    # 3. 200 same-size squares scattered at random (5 nm snap, no pitch grid):
    #    both passes must reject
    scatter = []
    for _ in range(200):
        x = 5 * rng.randrange(0, 20000)
        y = 5 * rng.randrange(0, 20000)
        scatter.append((x, y, x + 300, y + 300))
    s_bad = [f for _, _, f, _ in strict_fields(scatter) if f]
    r_bad = [f for _, _, f, _, _ in relaxed_fields(scatter) if f]
    ok = not s_bad and not r_bad
    print(f"selftest 3 scattered squares: strict {len(s_bad)} relaxed "
          f"{len(r_bad)} fields (want 0/0): {'ok' if ok else 'FAILED'}")
    if not ok:
        failures.append("scattered squares accepted")

    if failures:
        print("SELFTEST FAILED: " + "; ".join(failures))
        return 1
    print("SELFTEST PASSED (3/3)")
    return 0


# --------------------------------------------------------------------- cli --

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", nargs="?", choices=sorted(TARGETS))
    ap.add_argument("--flat", action="store_true",
                    help="flatten the hierarchy before scanning")
    ap.add_argument("--control", action="store_true",
                    help="flattened li1/met1 drawing only; expect no fields")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--max-mult", type=int, default=MAX_MULT,
                    help="relaxed pass: max units per rectangle side")
    args = ap.parse_args()
    globals()["MAX_MULT"] = args.max_mult

    if args.selftest:
        sys.exit(selftest())
    if not args.target:
        ap.error("target required unless --selftest")

    gds = TARGETS[args.target]
    mode = "control(flat li1/met1)" if args.control else ("flat" if args.flat else "top-cell")
    print(f"scan target={args.target} gds={gds} mode={mode} "
          f"thresholds: ink>={MIN_INK} fill>={MIN_FILL} dims {MIN_DIM}..{MAX_DIM}")
    found = scan(args.target, gds, args.flat, args.control)
    print(f"pixel fields declared: {len(found)}")
    if args.control and found:
        print("CONTROL VIOLATION: standard-cell routing registered as a pixel field")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
