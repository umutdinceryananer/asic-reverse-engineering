"""Easter-egg sweep, domain A1+A2: every text-bearing GDS record, raw.

egg_labels.py reads labels through gdstk, which surfaces TEXT elements
(their STRING records). The GDS stream has other records that can carry
ASCII: PROPVALUE (properties attached to any element), and the name
records themselves. This tool walks the raw record stream and reports:

  1. A histogram of every record type present, by name.
  2. Every PROPATTR/PROPVALUE pair, with the payload text.
  3. Every STRING payload NOT accounted for by gdstk's label inventory
     for the same file (count comparison per distinct text).

Usage:
    .venv-linux/bin/python tools/egg_gds_strings.py puzzle/puzzle.gds
    .venv-linux/bin/python tools/egg_gds_strings.py --selftest

--selftest feeds the scanner a synthetic record stream carrying one
PROPVALUE and one STRING and checks both are recovered verbatim, and that
the record-type histogram is exact.
"""

import struct
import sys
from collections import Counter
from pathlib import Path

import gdstk

RECORD_NAMES = {
    0x00: "HEADER", 0x01: "BGNLIB", 0x02: "LIBNAME", 0x03: "UNITS",
    0x04: "ENDLIB", 0x05: "BGNSTR", 0x06: "STRNAME", 0x07: "ENDSTR",
    0x08: "BOUNDARY", 0x09: "PATH", 0x0A: "SREF", 0x0B: "AREF",
    0x0C: "TEXT", 0x0D: "LAYER", 0x0E: "DATATYPE", 0x0F: "WIDTH",
    0x10: "XY", 0x11: "ENDEL", 0x12: "SNAME", 0x13: "COLROW",
    0x15: "NODE", 0x16: "TEXTTYPE", 0x17: "PRESENTATION", 0x19: "STRING",
    0x1A: "STRANS", 0x1B: "MAG", 0x1C: "ANGLE", 0x1F: "REFLIBS",
    0x20: "FONTS", 0x21: "PATHTYPE", 0x22: "GENERATIONS", 0x23: "ATTRTABLE",
    0x26: "ELFLAGS", 0x2A: "NODETYPE", 0x2B: "PROPATTR", 0x2C: "PROPVALUE",
    0x2D: "BOX", 0x2E: "BOXTYPE", 0x2F: "PLEX", 0x32: "TAPENUM",
    0x33: "TAPECODE", 0x36: "FORMAT", 0x37: "MASK", 0x38: "ENDMASKS",
}
PROPATTR, PROPVALUE, STRING = 0x2B, 0x2C, 0x19


def scan(blob):
    """Return (record-type histogram, [(attr, text)] properties, [texts])."""
    histogram = Counter()
    properties = []
    strings = []
    pending_attr = None
    offset = 0
    while offset + 4 <= len(blob):
        (length,) = struct.unpack(">H", blob[offset:offset + 2])
        rectype = blob[offset + 2]
        if length < 4:
            break
        payload = blob[offset + 4:offset + length]
        histogram[RECORD_NAMES.get(rectype, f"0x{rectype:02X}")] += 1
        if rectype == PROPATTR:
            (pending_attr,) = struct.unpack(">h", payload[:2])
        elif rectype == PROPVALUE:
            text = payload.rstrip(b"\0").decode("ascii", "replace")
            properties.append((pending_attr, text))
            pending_attr = None
        elif rectype == STRING:
            strings.append(payload.rstrip(b"\0").decode("ascii", "replace"))
        offset += length
    return histogram, properties, strings


def run(path):
    blob = Path(path).read_bytes()
    histogram, properties, strings = scan(blob)
    print(f"=== {path} ===")
    print("record types: " + ", ".join(
        f"{name} x{count}" for name, count in sorted(histogram.items())))
    unknown = [name for name in histogram if name.startswith("0x")]
    print(f"unknown record types: {unknown or 'none'}")
    print(f"PROPATTR/PROPVALUE pairs: {len(properties)}")
    for attr, text in properties:
        print(f"  attr {attr}: {text!r}")

    # Compare raw STRING payloads against gdstk's label texts, per distinct
    # text: a STRING gdstk does not report as a label would be a hidden one.
    library = gdstk.read_gds(str(path))
    label_texts = Counter(
        label.text for cell in library.cells for label in cell.labels)
    raw_texts = Counter(strings)
    hidden = raw_texts - label_texts
    print(f"STRING records: {sum(raw_texts.values())} raw vs "
          f"{sum(label_texts.values())} gdstk labels")
    if hidden:
        print("STRING records gdstk did not surface as labels:")
        for text, count in hidden.most_common():
            print(f"  x{count} {text!r}")
    else:
        print("every STRING record is accounted for by a gdstk label")
    print()
    return 0


def record(rectype, datatype, payload):
    body = payload + (b"\0" if len(payload) % 2 else b"")
    return struct.pack(">HBB", 4 + len(body), rectype, datatype) + body


def selftest():
    stream = (
        record(0x00, 0x02, struct.pack(">h", 600))          # HEADER
        + record(0x2B, 0x02, struct.pack(">h", 42))          # PROPATTR 42
        + record(0x2C, 0x06, b"planted property")            # PROPVALUE
        + record(0x19, 0x06, b"planted string")              # STRING
        + record(0x04, 0x00, b"")                            # ENDLIB
    )
    histogram, properties, strings = scan(stream)
    failures = []
    if properties != [(42, "planted property")]:
        failures.append(f"properties came back as {properties!r}")
    if strings != ["planted string"]:
        failures.append(f"strings came back as {strings!r}")
    expected = Counter({"HEADER": 1, "PROPATTR": 1, "PROPVALUE": 1,
                        "STRING": 1, "ENDLIB": 1})
    if histogram != expected:
        failures.append(f"histogram came back as {dict(histogram)!r}")
    if failures:
        for line in failures:
            print(f"SELFTEST FAIL: {line}")
        return 1
    print("SELFTEST PASS: PROPVALUE and STRING recovered verbatim, "
          "record histogram exact (3 checks)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if not argv:
        print(__doc__)
        return 2
    status = 0
    for path in argv:
        status = max(status, run(path))
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
