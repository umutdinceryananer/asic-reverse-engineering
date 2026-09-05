"""Full (layer, datatype) inventory of a GDS layout, for the Easter-egg hunt.

For each GDS this tool counts polygons, path elements and labels per
(layer, datatype) pair, twice: once for the top cell's own geometry and once
summed over the full hierarchy (references weighted by repetition count),
because routing lives inside placements in these layouts (CLAUDE.md).

Every observed pair is classified against the sky130 layer map recorded in
docs/00-environment.md, plus the three known non-PDK layers:
  200/0  marker row (the known Morse egg, cells INTERNAL_3 / INTERNAL_7)
  235/4  prBndry, die / place-and-route boundary
  236/0  per-cell outline inside standard cells

Any other pair is a CANDIDATE.  For a candidate (and for 200/0 whenever it
carries anything beyond the pure marker cells) the tool reports shape count,
bbox and width/height distribution, and runs three deterministic
interpreters over the flattened rectangles:
  1. Morse timing      (same convention as tools/decode_marker_row.py,
                        reimplemented here; that tool is not modified)
  2. binary-by-width / presence-on-pitch, packed to ASCII both bit orders
  3. pixel-grid bitmap (render written under out/eggs/)

Each interpreter refuses or reports noise on inputs that do not fit its
convention; the same three interpreters are also run on a control slice
(the top cell's own met3 70/20 shapes) which must come back refused/noise.
The known 200/0 row is used as the positive control for the Morse
interpreter: it must reproduce the recorded string.

Usage:
    .venv-linux/bin/python tools/egg_layers.py puzzle
    .venv-linux/bin/python tools/egg_layers.py warmup
    .venv-linux/bin/python tools/egg_layers.py <path.gds> --name mytarget
    .venv-linux/bin/python tools/egg_layers.py --selftest

Output: out/eggs/layers_<target>.json and structured stdout. Exit 0 on a
clean run, 1 on selftest failure or a broken control.
"""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import gdstk

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {
    "puzzle": ROOT / "puzzle" / "puzzle.gds",
    "warmup": ROOT / "puzzle" / "warmup" / "04_final.gds",
}
OUT_DIR = ROOT / "out" / "eggs"

# The layer map of docs/00-environment.md, verbatim.
KNOWN_DOC = {
    (64, 20): "nwell.drawing", (64, 16): "nwell.pin", (64, 5): "nwell.label",
    (64, 59): "pwell.label",
    (65, 20): "diff.drawing", (65, 44): "tap.drawing",
    (66, 20): "poly.drawing", (66, 44): "licon1.drawing",
    (67, 20): "li1.drawing", (67, 16): "li1.pin", (67, 5): "li1.label",
    (67, 44): "mcon.drawing",
    (68, 20): "met1.drawing", (68, 16): "met1.pin", (68, 5): "met1.label",
    (68, 44): "via.drawing",
    (69, 20): "met2.drawing", (69, 44): "via2.drawing",
    (70, 20): "met3.drawing", (70, 16): "met3.pin", (70, 5): "met3.label",
    (70, 44): "via3.drawing",
    (71, 20): "met4.drawing", (71, 16): "met4.pin", (71, 5): "met4.label",
    (71, 44): "via4.drawing",
    (72, 20): "met5.drawing", (72, 16): "met5.pin", (72, 5): "met5.label",
    (78, 44): "hvtp.drawing", (81, 4): "areaid.sc", (83, 44): "text",
    (93, 44): "nsdm.drawing", (94, 20): "psdm.drawing", (95, 20): "npc.drawing",
    (122, 16): "pwell.pin",
}
# Standard sky130 pairs absent from the doc's table (which lists only pairs
# that carried geometry when it was written). Present = worth noting, not
# automatically an egg.
KNOWN_SKY130_EXTRA = {
    (64, 44): "pwell.drawing", (69, 16): "met2.pin", (69, 5): "met2.label",
    (65, 16): "diff.pin", (66, 16): "poly.pin", (66, 5): "poly.label",
    (72, 44): "pad.drawing?",
}
KNOWN_NONPDK = {
    (200, 0): "marker row (known Morse egg)",
    (235, 4): "prBndry die/PR boundary",
    (236, 0): "per-cell outline inside std cells",
}

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
}

KNOWN_MORSE_TEXT = "PER ARENAM AD ASTRA"


# ---------------------------------------------------------------- inventory

def cell_pair_counts(cell):
    """(layer, datatype) -> [n_polygons, n_path_elements, n_labels] for one cell."""
    counts = {}

    def bump(pair, slot):
        counts.setdefault(pair, [0, 0, 0])[slot] += 1

    for p in cell.polygons:
        bump((p.layer, p.datatype), 0)
    for fp in cell.paths:
        for lay, dt in zip(fp.layers, fp.datatypes):
            bump((lay, dt), 1)
    for lb in cell.labels:
        bump((lb.layer, lb.texttype), 2)
    return counts


def effective_counts(cell, memo):
    """Counts summed over the full hierarchy under `cell` (repetitions honoured)."""
    if cell.name in memo:
        return memo[cell.name]
    total = {k: list(v) for k, v in cell_pair_counts(cell).items()}
    for ref in cell.references:
        mult = ref.repetition.size if ref.repetition and ref.repetition.size else 1
        sub = effective_counts(ref.cell, memo)
        for pair, (a, b, c) in sub.items():
            slot = total.setdefault(pair, [0, 0, 0])
            slot[0] += a * mult
            slot[1] += b * mult
            slot[2] += c * mult
    memo[cell.name] = total
    return total


def classify(pair):
    if pair in KNOWN_DOC:
        return "pdk-doc", KNOWN_DOC[pair]
    if pair in KNOWN_NONPDK:
        return "nonpdk-known", KNOWN_NONPDK[pair]
    if pair in KNOWN_SKY130_EXTRA:
        return "sky130-extra", KNOWN_SKY130_EXTRA[pair]
    return "UNKNOWN", "not in any known table"


def build_inventory(library, top):
    top_counts = cell_pair_counts(top)
    eff = effective_counts(top, {})
    carriers = {}
    for cell in library.cells:
        for pair in cell_pair_counts(cell):
            carriers.setdefault(pair, []).append(cell.name)
    inventory = {}
    # Union in carrier pairs too: geometry in an UNREFERENCED cell would
    # appear in no effective count, and an egg could hide exactly there.
    for pair in sorted(set(eff) | set(top_counts) | set(carriers)):
        cls, name = classify(pair)
        t = top_counts.get(pair, [0, 0, 0])
        e = eff.get(pair, [0, 0, 0])
        inventory[pair] = {
            "class": cls, "name": name,
            "top": {"polygons": t[0], "paths": t[1], "labels": t[2]},
            "effective": {"polygons": e[0], "paths": e[1], "labels": e[2]},
            "cells_carrying": len(carriers.get(pair, [])),
        }
    return inventory, carriers


# ---------------------------------------------------------- rect extraction

def layer_rects(top, layer, datatype, depth=None):
    """Flattened bboxes (x0,y0,x1,y1) of all shapes on one pair, paths included."""
    polys = top.get_polygons(depth=depth, layer=layer, datatype=datatype)
    rects, nonrect = [], 0
    for p in polys:
        (x0, y0), (x1, y1) = p.bounding_box()
        rects.append((round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)))
        if abs(p.area() - (x1 - x0) * (y1 - y0)) > 1e-6:
            nonrect += 1
    return rects, nonrect


def rect_stats(rects):
    if not rects:
        return {"count": 0}
    xs0 = min(r[0] for r in rects); ys0 = min(r[1] for r in rects)
    xs1 = max(r[2] for r in rects); ys1 = max(r[3] for r in rects)
    wh = Counter((round(r[2] - r[0], 3), round(r[3] - r[1], 3)) for r in rects)
    return {
        "count": len(rects),
        "bbox_um": [xs0, ys0, xs1, ys1],
        "width_height_top10": [
            {"w": w, "h": h, "n": n}
            for (w, h), n in sorted(wh.items(), key=lambda kv: -kv[1])[:10]
        ],
        "distinct_sizes": len(wh),
    }


def cluster_widths(widths, tol=0.05):
    """Merge sorted widths within relative tolerance; return cluster centres."""
    centres = []
    for w in sorted(widths):
        if centres and w <= centres[-1][0] * (1 + tol):
            c, n = centres[-1]
            centres[-1] = ((c * n + w) / (n + 1), n + 1)
        else:
            centres.append((w, 1))
    return [c for c, _ in centres]


# ------------------------------------------------------------- interpreters

def interp_morse(rects):
    """International Morse timing over rows of rectangles. Same convention as
    tools/decode_marker_row.py: width 1 unit = dot, 3 = dash; gap 1 = intra,
    >=3 char, >=7 word."""
    if len(rects) < 5:
        return {"status": "refused", "reason": f"only {len(rects)} marks (<5)"}
    widths = [r[2] - r[0] for r in rects]
    heights = [r[3] - r[1] for r in rects]
    if max(heights) > min(heights) * 1.05:
        return {"status": "refused", "reason": "heights not uniform"}
    wc = cluster_widths(widths)
    if len(wc) > 2:
        return {"status": "refused", "reason": f"{len(wc)} width classes (need 1-2)"}
    if len(wc) == 2 and not (2.7 <= wc[1] / wc[0] <= 3.3):
        return {"status": "refused",
                "reason": f"width ratio {wc[1] / wc[0]:.2f} not ~3"}
    unit = wc[0]
    rows = {}
    for r in rects:
        rows.setdefault(round((r[1] + r[3]) / 2, 3), []).append(r)
    tokens, bad_gap = [], 0
    for y in sorted(rows, reverse=True):
        row = sorted(rows[y])
        symbols = []
        for i, r in enumerate(row):
            symbols.append("." if round((r[2] - r[0]) / unit) == 1 else "-")
            if i + 1 < len(row):
                gap = (row[i + 1][0] - r[2]) / unit
                if gap < 0.5:
                    bad_gap += 1
                g = round(gap)
                if g >= 7:
                    tokens.append("".join(symbols)); tokens.append(" "); symbols = []
                elif g >= 3:
                    tokens.append("".join(symbols)); symbols = []
        tokens.append("".join(symbols))
        tokens.append(" ")
    if bad_gap:
        return {"status": "noise", "reason": f"{bad_gap} overlapping/irregular gaps"}
    letters = [t for t in tokens if t and t != " "]
    if not letters:
        return {"status": "noise", "reason": "no tokens"}
    valid = sum(1 for t in letters if t in MORSE)
    text = "".join(" " if t == " " else MORSE.get(t, "?") for t in tokens).strip()
    text = " ".join(text.split())
    if valid / len(letters) < 0.8 or valid < 3:
        return {"status": "noise",
                "reason": f"{valid}/{len(letters)} valid Morse tokens", "text": text}
    return {"status": "decoded", "text": text,
            "valid_tokens": f"{valid}/{len(letters)}", "unit_um": round(unit, 3)}


def _pack(bits):
    out = []
    for i in range(0, len(bits) - len(bits) % 8, 8):
        out.append(int("".join(map(str, bits[i:i + 8])), 2))
    return bytes(out)


def interp_binary(rects):
    """Widths as bits (2 classes) or presence-on-pitch (1 class), rows top to
    bottom, packed to bytes both bit orders, scored by printable fraction."""
    if len(rects) < 8:
        return {"status": "refused", "reason": f"only {len(rects)} marks (<8)"}
    rows = {}
    for r in rects:
        rows.setdefault(round((r[1] + r[3]) / 2, 3), []).append(r)
    wc = cluster_widths([r[2] - r[0] for r in rects])
    bits = []
    if len(wc) == 2:
        mid = (wc[0] + wc[1]) / 2
        for y in sorted(rows, reverse=True):
            for r in sorted(rows[y]):
                bits.append(0 if (r[2] - r[0]) < mid else 1)
        mode = "width(narrow=0,wide=1)"
    elif len(wc) == 1:
        for y in sorted(rows, reverse=True):
            row = sorted(rows[y])
            centres = [(r[0] + r[2]) / 2 for r in row]
            diffs = [b - a for a, b in zip(centres, centres[1:]) if b - a > 1e-6]
            if not diffs:
                continue
            pitch = min(diffs)
            slots = [(c - centres[0]) / pitch for c in centres]
            if any(abs(s - round(s)) > 0.25 for s in slots):
                return {"status": "refused", "reason": "marks not on a pitch grid"}
            n = round(slots[-1]) + 1
            if n > 4096:
                return {"status": "refused", "reason": f"{n} slots (>4096)"}
            present = {round(s) for s in slots}
            bits.extend(1 if i in present else 0 for i in range(n))
        mode = "presence-on-pitch"
    else:
        return {"status": "refused", "reason": f"{len(wc)} width classes (need 1-2)"}
    if len(bits) < 16:
        return {"status": "refused", "reason": f"only {len(bits)} bits (<16)"}
    best = None
    for order, bs in (("msb", bits), ("lsb-per-byte", None)):
        if order == "lsb-per-byte":
            bs = []
            for i in range(0, len(bits) - len(bits) % 8, 8):
                bs.extend(reversed(bits[i:i + 8]))
        data = _pack(bs)
        printable = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
        frac = printable / len(data) if data else 0
        if best is None or frac > best[0]:
            best = (frac, order, data)
    frac, order, data = best
    if frac >= 0.9 and len(data) >= 2:
        return {"status": "decoded", "mode": mode, "bit_order": order,
                "nbits": len(bits),
                "text": data.decode("ascii", errors="replace")}
    return {"status": "noise", "mode": mode, "nbits": len(bits),
            "reason": f"best printable fraction {frac:.2f} (<0.9)",
            "hex_first16": data[:16].hex()}


def interp_bitmap(rects, out_path=None):
    """Snap rectangle centres to an inferred grid and render an ASCII bitmap."""
    if len(rects) < 4:
        return {"status": "refused", "reason": f"only {len(rects)} marks (<4)"}
    cx = sorted({round((r[0] + r[2]) / 2, 4) for r in rects})
    cy = sorted({round((r[1] + r[3]) / 2, 4) for r in rects})

    def pitch(vals):
        diffs = [b - a for a, b in zip(vals, vals[1:]) if b - a > 1e-6]
        return min(diffs) if diffs else None

    px, py = pitch(cx), pitch(cy)
    if px is None and py is None:
        return {"status": "refused", "reason": "all marks at one point"}
    px = px or py
    py = py or px
    nx = round((cx[-1] - cx[0]) / px) + 1
    ny = round((cy[-1] - cy[0]) / py) + 1
    if nx > 400 or ny > 400:
        return {"status": "refused", "reason": f"grid {nx}x{ny} exceeds 400"}
    grid = [["." for _ in range(nx)] for _ in range(ny)]
    off_grid = 0
    for r in rects:
        gx = ((r[0] + r[2]) / 2 - cx[0]) / px
        gy = ((r[1] + r[3]) / 2 - cy[0]) / py
        if abs(gx - round(gx)) > 0.25 or abs(gy - round(gy)) > 0.25:
            off_grid += 1
            continue
        grid[ny - 1 - round(gy)][round(gx)] = "#"
    if off_grid / len(rects) > 0.1:
        return {"status": "refused",
                "reason": f"{off_grid}/{len(rects)} marks off the inferred grid"}
    lines = ["".join(row) for row in grid]
    filled = sum(row.count("#") for row in grid)
    result = {"status": "rendered", "grid": f"{nx}x{ny}",
              "filled": filled, "density": round(filled / (nx * ny), 3)}
    if out_path:
        Path(out_path).write_text("\n".join(lines) + "\n")
        result["render"] = str(out_path)
    else:
        result["lines"] = lines
    return result


def run_interpreters(rects, tag, render_path=None):
    return {
        "morse": interp_morse(rects),
        "binary": interp_binary(rects),
        "bitmap": interp_bitmap(rects, render_path),
        "input": tag,
    }


# ------------------------------------------------------------------- driver

def analyse_target(name, gds_path):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    library = gdstk.read_gds(str(gds_path))
    tops = library.top_level()
    top = max(tops, key=lambda c: len(c.references))
    inventory, carriers = build_inventory(library, top)

    report = {
        "target": name, "gds": str(gds_path), "top_cell": top.name,
        "top_cells_in_library": [c.name for c in tops],
        "n_cells": len(library.cells),
        "n_top_references": len(top.references),
        "layers": {}, "candidates": [], "marker_checks": {}, "controls": {},
    }
    for pair, row in inventory.items():
        report["layers"]["%d/%d" % pair] = row

    # --- marker-layer consistency ------------------------------------
    # 200/0: everything must come from cells whose ONLY geometry is 200/0.
    pure_marker_cells = {
        c.name for c in library.cells
        if c.polygons and {(p.layer, p.datatype) for p in c.polygons} == {(200, 0)}
        and not c.paths and not c.labels
    }
    eff200 = inventory.get((200, 0), {"effective": {"polygons": 0, "paths": 0, "labels": 0}})
    marker_placements = sum(
        (ref.repetition.size or 1) if ref.repetition else 1
        for ref in top.references if ref.cell.name in pure_marker_cells
    )
    outside = (eff200["effective"]["polygons"] - marker_placements
               if (200, 0) in inventory else 0)
    report["marker_checks"]["200/0"] = {
        "effective_polygons": eff200["effective"]["polygons"],
        "pure_marker_cells": sorted(pure_marker_cells),
        "marker_cell_placements": marker_placements,
        "polygons_beyond_marker_cells": outside,
        "top_cell_own": inventory.get((200, 0), {}).get("top", {"polygons": 0})["polygons"]
        if (200, 0) in inventory else 0,
    }
    b = inventory.get((235, 4))
    report["marker_checks"]["235/4"] = {
        "top_polygons": b["top"]["polygons"] if b else 0,
        "effective_polygons": b["effective"]["polygons"] if b else 0,
    }
    o = inventory.get((236, 0))
    report["marker_checks"]["236/0"] = {
        "effective_polygons": o["effective"]["polygons"] if o else 0,
        "cells_carrying": o["cells_carrying"] if o else 0,
        "leaf_placements": len(top.references),
    }

    # --- candidates ----------------------------------------------------
    candidate_pairs = [p for p, row in inventory.items() if row["class"] == "UNKNOWN"]
    if (200, 0) in inventory and (outside != 0 or report["marker_checks"]["200/0"]["top_cell_own"]):
        candidate_pairs.append((200, 0))
    for pair in candidate_pairs:
        rects, nonrect = layer_rects(top, *pair)
        entry = {
            "pair": "%d/%d" % pair,
            "carried_by_cells": carriers.get(pair, [])[:20],
            "nonrect_polygons": nonrect,
            "stats": rect_stats(rects),
            "interpretations": run_interpreters(
                rects, "%s %d/%d flattened" % (name, *pair),
                OUT_DIR / ("bitmap_%s_%d_%d.txt" % (name, *pair))),
        }
        report["candidates"].append(entry)

    # --- positive control: the known Morse row -------------------------
    if (200, 0) in inventory:
        rects, _ = layer_rects(top, 200, 0)
        got = interp_morse(rects)
        report["controls"]["positive_morse_200_0"] = {
            **got, "expected": KNOWN_MORSE_TEXT,
            "match": got.get("text") == KNOWN_MORSE_TEXT,
        }

    # --- negative control: top-cell met3 slice -------------------------
    ctrl, nonrect = layer_rects(top, 70, 20, depth=0)
    report["controls"]["negative_met3_topcell"] = {
        "n_shapes": len(ctrl), "nonrect": nonrect,
        **{k: v for k, v in run_interpreters(ctrl, "met3 70/20 top-cell slice").items()
           if k != "input"},
    }

    out_json = OUT_DIR / f"layers_{name}.json"
    out_json.write_text(json.dumps(report, indent=1))
    return report, out_json


def print_report(report):
    print(f"== {report['target']}  top={report['top_cell']}  "
          f"cells={report['n_cells']}  placements={report['n_top_references']}")
    print(f"{'layer':>8} {'class':<13} {'name':<18} "
          f"{'top p/pa/l':>14} {'effective p/pa/l':>20} {'cells':>5}")
    for key, row in report["layers"].items():
        t, e = row["top"], row["effective"]
        print(f"{key:>8} {row['class']:<13} {row['name']:<18} "
              f"{t['polygons']:>5}/{t['paths']:>4}/{t['labels']:>3} "
              f"{e['polygons']:>9}/{e['paths']:>6}/{e['labels']:>3} "
              f"{row['cells_carrying']:>5}")
    print("marker checks:", json.dumps(report["marker_checks"]))
    print(f"candidates: {len(report['candidates'])}")
    for c in report["candidates"]:
        print(" ", json.dumps(c))
    for tag, ctl in report["controls"].items():
        summary = {k: (v.get("status") if isinstance(v, dict) else v)
                   for k, v in ctl.items() if k in ("morse", "binary", "bitmap",
                                                    "match", "n_shapes", "status", "text")}
        print(f"control {tag}: {json.dumps(summary)}")


# ------------------------------------------------------------------ selftest

def _rect(x0, y0, x1, y1, layer, datatype):
    return gdstk.rectangle((x0, y0), (x1, y1), layer=layer, datatype=datatype)


def _morse_rects(text, unit=1.0, h=1.0):
    rects, x = [], 0.0
    words = text.split(" ")
    for wi, word in enumerate(words):
        for ci, ch in enumerate(word):
            code = {v: k for k, v in MORSE.items()}[ch]
            for si, sym in enumerate(code):
                w = unit if sym == "." else 3 * unit
                rects.append((x, 0.0, x + w, h))
                x += w + unit
            x += 2 * unit  # 1 already added -> char gap 3
        x += 4 * unit      # -> word gap 7
    return rects


def selftest():
    failures = []

    def check(label, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label} {detail}")
        if not ok:
            failures.append(label)

    print("selftest: inventory classification")
    lib = gdstk.Library()
    leaf = lib.new_cell("leafA")
    leaf.add(_rect(0, 0, 1, 1, 67, 20), _rect(0, 0, 2, 2, 236, 0))
    topc = lib.new_cell("topc")
    topc.add(_rect(0, 0, 10, 10, 68, 20), _rect(0, 0, 10, 10, 235, 4))
    topc.add(gdstk.Label("N", (1, 1), layer=68, texttype=5))
    topc.add(gdstk.Reference(leaf, (0, 0)), gdstk.Reference(leaf, (5, 0)))
    inv, _ = build_inventory(lib, topc)
    cands = [p for p, r in inv.items() if r["class"] == "UNKNOWN"]
    check("clean library has zero candidates", cands == [], str(cands))
    check("effective doubles the leaf geometry",
          inv[(67, 20)]["effective"]["polygons"] == 2
          and inv[(67, 20)]["top"]["polygons"] == 0)

    leaf2 = lib.new_cell("leafB")
    leaf2.add(_rect(0, 0, 1, 1, 199, 7))
    topc.add(gdstk.Reference(leaf2, (0, 5)), gdstk.Reference(leaf2, (5, 5)))
    inv, _ = build_inventory(lib, topc)
    cands = [p for p, r in inv.items() if r["class"] == "UNKNOWN"]
    check("planted layer 199/7 is reported", cands == [(199, 7)], str(cands))
    check("planted layer effective count is 2",
          inv.get((199, 7), {}).get("effective", {}).get("polygons") == 2)

    print("selftest: morse interpreter")
    got = interp_morse(_morse_rects("SOS"))
    check("planted SOS decodes", got.get("status") == "decoded"
          and got.get("text") == "SOS", json.dumps(got))
    rng = random.Random(42)
    noise = []
    x = 0.0
    for _ in range(30):
        w = rng.uniform(0.5, 4.0)
        x += rng.uniform(0.1, 5.0)
        noise.append((x, 0.0, x + w, rng.uniform(0.5, 4.0)))
        x += w
    got = interp_morse(noise)
    check("seeded random rects do not decode as morse",
          got.get("status") != "decoded", json.dumps(got))

    print("selftest: binary interpreter")
    bits = [int(b) for ch in "HI" for b in format(ord(ch), "08b")]
    rects = [(i * 5.0, 0.0, i * 5.0 + (3.0 if b else 1.0), 1.0)
             for i, b in enumerate(bits)]
    got = interp_binary(rects)
    check("planted 'HI' decodes by width", got.get("status") == "decoded"
          and got.get("text") == "HI", json.dumps(got))
    got = interp_binary(noise)
    check("seeded random rects are not ascii",
          got.get("status") != "decoded", json.dumps(got))

    print("selftest: bitmap interpreter")
    grid = [(i * 2.0, j * 2.0, i * 2.0 + 1, j * 2.0 + 1)
            for i in range(3) for j in range(3) if (i, j) != (1, 1)]
    got = interp_bitmap(grid)
    check("3x3 grid minus centre renders 8/9", got.get("status") == "rendered"
          and got.get("grid") == "3x3" and got.get("filled") == 8, json.dumps(got))
    got = interp_bitmap([(0, 0, 1, 1), (1.5, 0, 2.5, 1), (1000, 0, 1001, 1),
                         (0, 5, 1, 6)])
    check("degenerate span is refused for grid size",
          got.get("status") == "refused" and "exceeds 400" in got.get("reason", ""),
          json.dumps(got))

    print(f"selftest: {len(failures)} failure(s)")
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", nargs="?", help="puzzle | warmup | path to a GDS")
    ap.add_argument("--name", help="target name for outputs (defaults from path)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())
    if not args.target:
        ap.error("give a target or --selftest")
    if args.target in TARGETS:
        name, path = args.target, TARGETS[args.target]
    else:
        path = Path(args.target)
        name = args.name or path.stem
    report, out_json = analyse_target(name, path)
    print_report(report)
    print(f"written: {out_json}")

    bad = False
    pos = report["controls"].get("positive_morse_200_0")
    if pos and not pos["match"]:
        print("BROKEN POSITIVE CONTROL: 200/0 did not reproduce the known string")
        bad = True
    neg = report["controls"]["negative_met3_topcell"]
    for interp in ("morse", "binary", "bitmap"):
        st = neg[interp]["status"]
        if st in ("decoded",):
            print(f"BROKEN NEGATIVE CONTROL: {interp} decoded the met3 slice")
            bad = True
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
