"""Decode the row of marker rectangles on layer 200/0 as Morse code.

The puzzle GDS places 36 blank rectangles on layer 200/0 in a single row below
the core area. They carry no diff or poly, so they are not circuit elements.
Their widths come in exactly two sizes with a 1:3 ratio and the gaps between
them are 1, 3 or 7 of the smaller width, which is the timing convention of
International Morse: dot, dash, intra-character gap, inter-character gap and
word gap.

Usage:
    python tools/decode_marker_row.py puzzle/puzzle.gds
"""

import sys
from collections import Counter

import gdstk

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F",
    "--.": "G", "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L",
    "--": "M", "-.": "N", "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R",
    "...": "S", "-": "T", "..-": "U", "...-": "V", ".--": "W", "-..-": "X",
    "-.--": "Y", "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
}

MARKER_LAYER = (200, 0)


def marker_cells(library):
    """Cell name -> width, for cells whose only geometry is on the marker layer."""
    widths = {}
    for cell in library.cells:
        layers = {(p.layer, p.datatype) for p in cell.polygons}
        if layers == {MARKER_LAYER}:
            (x0, _), (x1, _) = cell.bounding_box()
            widths[cell.name] = x1 - x0
    return widths


def decode(path):
    library = gdstk.read_gds(path)
    widths = marker_cells(library)
    if not widths:
        sys.exit(f"no cells found whose geometry is only on layer {MARKER_LAYER}")

    print("marker cells:")
    for name, width in sorted(widths.items(), key=lambda kv: kv[1]):
        print(f"  {name:14s} width {width:.3f} um")

    unit = min(widths.values())
    print(f"\nbase unit (dot width) = {unit:.3f} um")

    # Collect every placement of a marker cell, anywhere in the hierarchy.
    marks = []
    for cell in library.cells:
        for reference in cell.references:
            name = reference.cell.name if hasattr(reference.cell, "name") else str(reference.cell)
            if name in widths:
                marks.append((reference.origin[0], reference.origin[1], widths[name]))

    rows = Counter(round(y, 3) for _, y, _ in marks)
    print(f"placements: {len(marks)} across {len(rows)} row(s) at y = "
          f"{', '.join(f'{y:.2f}' for y in sorted(rows))}")

    for row_y in sorted(rows):
        row = sorted((x, w) for x, y, w in marks if round(y, 3) == row_y)
        symbols = []
        text = []
        for index, (x, width) in enumerate(row):
            symbols.append("." if round(width / unit) == 1 else "-")
            if index + 1 < len(row):
                gap = round((row[index + 1][0] - (x + width)) / unit)
                if gap >= 7:
                    text.append("".join(symbols))
                    text.append(" ")
                    symbols = []
                elif gap >= 3:
                    text.append("".join(symbols))
                    symbols = []
        text.append("".join(symbols))

        print(f"\nrow y={row_y:.2f}, {len(row)} marks")
        print("  morse:  " + " ".join(t if t != " " else "/" for t in text if t))
        decoded = "".join(" " if t == " " else MORSE.get(t, f"[{t}]") for t in text)
        print(f"  text:   {decoded}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    decode(sys.argv[1])
