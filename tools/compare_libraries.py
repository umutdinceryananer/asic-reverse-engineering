"""Two cell libraries, cell by cell, on the layers that tell them apart.

Stage 1 falls back from exact geometry to a structural key on 22 of the puzzle's
1618 placements, and `docs/references.md` section 3 names the candidate cause:
the target was drawn against `sky130A` as built by **open_pdks**, which
re-renders cell layouts through Magic, while `pdk/sky130_fd_sc_hd/` comes from
the upstream *library* repository, which does not.

That hypothesis is testable without opening a puzzle file, and this is the test.
It compares every cell present in both libraries, polygon by polygon on the
nanometre grid, and reports which cells differ and **on which layers**. The
layer breakdown is the part that matters: a difference confined to poly, licon1
and npc, with metal and diffusion untouched, is the signature of a re-render
rather than of a different cell.

**This is the evidence the author needs before running anything on the puzzle.**
The warm up places 230 cells and none of them drift, so the warm up cannot test
the hypothesis at all -- it can only show that a second library does not break
what already works. The list below can, because it covers every cell in the
library whether or not any target places it.

**What it cannot conclude.** Stage 1's exact digest hashes every layer, so a
puzzle run whose fallbacks drop to zero would establish "this library is the one
that drew the target" and not "the difference was poly, licon1 and npc". Those
are separate statements and only this comparison speaks to the second.

Usage:
    python tools/compare_libraries.py
    python tools/compare_libraries.py --layers      # the layer census, in full
    python tools/compare_libraries.py --selftest    # and would it notice
"""

import os
import sys
from collections import Counter, defaultdict

import gdstk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage1_cells import PDK_DIR, load_library
import fetch_open_pdks

# Layer numbers this PDK draws on, for the report. `docs/00-environment.md`
# carries the full stack; these are the ones a re-render is expected to move.
LAYER_NAMES = {
    (64, 20): "nwell", (65, 20): "diff", (66, 20): "poly",
    (66, 15): "poly label", (66, 44): "licon1", (67, 20): "li1",
    (67, 44): "mcon", (68, 20): "met1", (69, 20): "met2",
    (95, 20): "npc", (94, 20): "nsdm", (93, 44): "psdm",
    (64, 16): "nwell pin", (67, 16): "li1 pin", (68, 16): "met1 pin",
    (122, 16): "pwell pin", (81, 4): "areaid.sc",
}

# What the hypothesis says a Magic re-render should touch, and nothing else.
RERENDER = {(66, 20), (66, 15), (66, 44), (95, 20)}


def shapes(cell):
    """Every polygon as (layer, datatype, points on the nm grid), sorted.

    The same snapping `common/gds.digest` uses, and the same reason: two
    libraries that agree to the nanometre must compare equal whatever floating
    point did on the way in. Origin-relative, so a cell drawn at a different
    offset is not reported as different geometry.
    """
    if not cell.polygons:
        return {}
    left = min(min(p[0] for p in poly.points) for poly in cell.polygons)
    bottom = min(min(p[1] for p in poly.points) for poly in cell.polygons)
    by_layer = defaultdict(list)
    for poly in cell.polygons:
        points = tuple(sorted((round((x - left) * 1000),
                               round((y - bottom) * 1000))
                              for x, y in poly.points))
        by_layer[(poly.layer, poly.datatype)].append(points)
    return {layer: sorted(polys) for layer, polys in by_layer.items()}


def index(cells):
    """{name: shapes}, first definition wins, hierarchical cells noted."""
    out, hierarchical = {}, []
    for cell in cells:
        if cell.name in out:
            continue
        if cell.references:
            hierarchical.append(cell.name)
        out[cell.name] = shapes(cell)
    return out, hierarchical


def differences(left, right):
    """Cells present in both and differing, with the layers that differ."""
    rows = []
    for name in sorted(set(left) & set(right)):
        moved = []
        for layer in sorted(set(left[name]) | set(right[name])):
            before = left[name].get(layer, [])
            after = right[name].get(layer, [])
            if before != after:
                moved.append((layer, len(before), len(after)))
        if moved:
            rows.append((name, moved))
    return rows


def describe(layer):
    return LAYER_NAMES.get(layer, "")


def compare(standard, alternate, verbose=True):
    """Returns (rows, off_signature). `off_signature` is the finding."""
    left, left_hier = index(standard)
    right, right_hier = index(alternate)
    if verbose:
        print(f"  standard   {len(left)} cells"
              + (f", {len(left_hier)} hierarchical" if left_hier else ""))
        print(f"  alternate  {len(right)} cells"
              + (f", {len(right_hier)} hierarchical" if right_hier else ""))
        only_left = sorted(set(left) - set(right))
        only_right = sorted(set(right) - set(left))
        if only_left:
            print(f"  only in the standard library: {len(only_left)} "
                  f"{only_left[:4]}")
        if only_right:
            print(f"  only in the alternate library: {len(only_right)} "
                  f"{only_right[:4]}")

    rows = differences(left, right)
    shared = len(set(left) & set(right))
    if verbose:
        print(f"\n{len(rows)} of {shared} shared cells differ\n")
        for name, moved in rows:
            parts = ", ".join(
                f"{layer[0]}/{layer[1]}"
                + (f" {describe(layer)}" if describe(layer) else "")
                + f" ({before}->{after})"
                for layer, before, after in moved)
            print(f"  {name:<24} {parts}")

    touched = {layer for _name, moved in rows for layer, _b, _a in moved}
    off_signature = sorted(touched - RERENDER)
    if verbose:
        print(f"\nlayers that differ anywhere: "
              f"{sorted(f'{l}/{d}' for l, d in touched)}")
        named = sorted(f"{l}/{d} {describe((l, d))}".strip()
                       for l, d in RERENDER)
        print(f"the re-render signature is {named}")
        if off_signature:
            print(f"  OUTSIDE it: "
                  f"{sorted(f'{l}/{d} {describe((l, d))}'.strip() for l, d in off_signature)}")
            print(f"  A difference outside poly, licon1 and npc is not a "
                  f"re-render's signature.")
        else:
            print(f"  nothing differs outside it")
    return rows, off_signature


def selftest():
    """Would this notice? Cells made to differ on purpose."""
    standard = load_library(PDK_DIR)
    print("the comparison against libraries doctored on purpose\n")
    rows, _off = compare(standard, standard, verbose=False)
    print(f"  {'caught' if not rows else 'MISSED'}  a library compared with "
          f"itself reports no difference   ({len(rows)} rows)")
    missed = [] if not rows else ["identical libraries differ"]

    # One polygon moved by a nanometre, on a layer inside the signature.
    doctored = [c.copy(c.name) for c in standard]
    target = next(c for c in doctored
                  if c.name.endswith("__nand2_1") and c.polygons)
    poly = next(p for p in target.polygons if (p.layer, p.datatype) == (66, 20))
    poly.translate(0.001, 0)
    rows, off = compare(standard, doctored, verbose=False)
    hit = [name for name, _m in rows if name.endswith("__nand2_1")]
    print(f"  {'caught' if hit else 'MISSED'}  one poly polygon moved by 1 nm "
          f"  ({len(rows)} row(s): {hit})")
    if not hit:
        missed.append("a 1 nm move on poly")
    print(f"  {'ok' if not off else 'WRONG'}      and it is inside the "
          f"re-render signature   ({off or 'nothing outside'})")

    # And one on a layer outside the signature, which must be reported as such.
    # Chosen by scanning rather than by naming a layer: which layers a given
    # cell carries is a property of the library, and a hard coded (68, 20)
    # raised StopIteration on `nand2_1`, whose met1 is all pin geometry.
    doctored = [c.copy(c.name) for c in standard]
    target = next(c for c in doctored
                  if c.name.endswith("__nand2_1") and c.polygons)
    outside = sorted((p.layer, p.datatype) for p in target.polygons
                     if (p.layer, p.datatype) not in RERENDER)
    metal = next(p for p in target.polygons
                 if (p.layer, p.datatype) == outside[0])
    metal.translate(0.001, 0)
    rows, off = compare(standard, doctored, verbose=False)
    print(f"  {'caught' if off else 'MISSED'}  one {describe(outside[0]) or outside[0]} "
          f"polygon moved, reported as outside the signature   ({off})")
    if not off:
        missed.append("a move outside the signature")

    print(f"\n  {4 - len(missed)}/4 checks held")
    if missed:
        print("\nRESULT: fail, this comparison does not notice: "
              + ", ".join(missed))
        return 1
    print("\nRESULT: pass, the comparison sees a nanometre and tells the "
          "signature from outside it")
    return 0


def run(show_layers=False):
    if not os.path.exists(fetch_open_pdks.GDS):
        print(f"{fetch_open_pdks.GDS} is missing; run "
              f"tools/fetch_open_pdks.py first")
        return 2
    print(f"standard   {PDK_DIR.replace(os.sep, '/')}   "
          f"(upstream library, {fetch_open_pdks.LIBRARY})")
    print(f"alternate  {fetch_open_pdks.GDS.replace(os.sep, '/')}   "
          f"(open_pdks {fetch_open_pdks.OPEN_PDKS[:12]})\n")
    standard = load_library(PDK_DIR)
    alternate = gdstk.read_gds(fetch_open_pdks.GDS).cells
    rows, off_signature = compare(standard, alternate)

    if show_layers:
        print("\nlayer census, standard library")
        census = Counter()
        for cell in standard:
            for poly in cell.polygons:
                census[(poly.layer, poly.datatype)] += 1
        for layer, count in sorted(census.items()):
            print(f"  {layer[0]:>4}/{layer[1]:<3} {describe(layer):<18} "
                  f"{count:>7}")

    print(f"\nThis is a library against a library. It does not touch a target, "
          f"and the\nwarm up cannot test the hypothesis -- it places 230 cells "
          f"and none of them\ndrift. What the author runs on the puzzle, and "
          f"what each outcome means, is in\ndocs/01-cell-recognition.md.")
    if not rows:
        print("\nRESULT: the two libraries are identical on every shared "
              "cell, so the\n  hypothesis is dead: open_pdks is not what "
              "moved those cells.")
        return 1
    print(f"\nRESULT: {len(rows)} cells differ"
          + (f", and {len(off_signature)} layer(s) outside poly/licon1/npc are "
             f"involved" if off_signature else
             ", every difference confined to poly, licon1 and npc"))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        sys.exit(selftest())
    if args not in ([], ["--layers"]):
        sys.exit("usage: python tools/compare_libraries.py "
                 "[--layers | --selftest]")
    sys.exit(run(show_layers=bool(args)))
