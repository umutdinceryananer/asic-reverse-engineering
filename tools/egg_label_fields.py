"""Easter-egg sweep, gap A1-fields: label-record fields as a channel, raw.

egg_gds_strings.py counted PRESENTATION, MAG and ANGLE records but never
decoded them. This tool walks the raw GDS record stream (no gdstk) and,
per file:

  1. Attributes every PRESENTATION / STRANS / MAG / ANGLE record to its
     containing element (TEXT / SREF / AREF), keeps the per-TEXT values in
     file order, and reports the distinct-value histogram per (layer,
     texttype). Any label whose fields deviate from the dominant value of
     its own layer is a candidate; every deviating sequence is put through
     deterministic bit/ASCII decode attempts (deviation bitmap MSB- and
     LSB-first, values as ASCII codes).
  2. Scans every ASCII-typed record (STRING, STRNAME, SNAME, LIBNAME,
     PROPVALUE) for its pad region: everything after the first NUL byte
     must be NUL. A non-NUL byte there is invisible to every standard
     reader and would be a real channel; the tool fails loudly (exit 1).

The control is a stock PDK cell GDS scanned identically, to establish the
flow-default field values.

Usage:
    .venv-linux/bin/python tools/egg_label_fields.py            # battery:
        control + warmup + puzzle -> out/eggs/label_fields.json
    .venv-linux/bin/python tools/egg_label_fields.py FILE...    # ad hoc
    .venv-linux/bin/python tools/egg_label_fields.py --selftest

--selftest plants one non-default PRESENTATION in a stream of default
labels and one non-NUL pad byte behind a STRING terminator, in synthetic
byte streams, and checks both are caught (and that a clean stream yields
neither), exiting 1 otherwise.
"""

import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RECORD_NAMES = {
    0x00: "HEADER", 0x01: "BGNLIB", 0x02: "LIBNAME", 0x03: "UNITS",
    0x04: "ENDLIB", 0x05: "BGNSTR", 0x06: "STRNAME", 0x07: "ENDSTR",
    0x08: "BOUNDARY", 0x09: "PATH", 0x0A: "SREF", 0x0B: "AREF",
    0x0C: "TEXT", 0x0D: "LAYER", 0x0E: "DATATYPE", 0x0F: "WIDTH",
    0x10: "XY", 0x11: "ENDEL", 0x12: "SNAME", 0x13: "COLROW",
    0x15: "NODE", 0x16: "TEXTTYPE", 0x17: "PRESENTATION", 0x19: "STRING",
    0x1A: "STRANS", 0x1B: "MAG", 0x1C: "ANGLE", 0x21: "PATHTYPE",
    0x22: "GENERATIONS", 0x26: "ELFLAGS", 0x2A: "NODETYPE",
    0x2B: "PROPATTR", 0x2C: "PROPVALUE", 0x2D: "BOX", 0x2E: "BOXTYPE",
    0x2F: "PLEX",
}
TEXT, SREF, AREF, ENDEL = 0x0C, 0x0A, 0x0B, 0x11
LAYER, TEXTTYPE, PRESENTATION, STRANS = 0x0D, 0x16, 0x17, 0x1A
MAG, ANGLE, STRING = 0x1B, 0x1C, 0x19
STRNAME, SNAME, LIBNAME, PROPVALUE = 0x06, 0x12, 0x02, 0x2C
ASCII_RECORDS = {STRING: "STRING", STRNAME: "STRNAME", SNAME: "SNAME",
                 LIBNAME: "LIBNAME", PROPVALUE: "PROPVALUE"}
CONTAINERS = {TEXT: "TEXT", SREF: "SREF", AREF: "AREF"}
FIELDS = ("presentation", "strans", "mag", "angle", "presence")

CONTROL = ROOT / "pdk/sky130_fd_sc_hd/sky130_fd_sc_hd__conb_1.gds"
BATTERY = [ROOT / "puzzle/warmup/04_final.gds", ROOT / "puzzle/puzzle.gds"]
OUT_JSON = ROOT / "out/eggs/label_fields.json"


def gds_real(payload):
    """8-byte GDSII excess-64 base-16 real."""
    if len(payload) != 8:
        return None
    sign = -1.0 if payload[0] & 0x80 else 1.0
    exponent = (payload[0] & 0x7F) - 64
    mantissa = int.from_bytes(payload[1:8], "big")
    return sign * mantissa * (16.0 ** exponent) / (1 << 56)


def fmt(value):
    return "absent" if value is None else f"{value:.9g}"


def presentation_meaning(value):
    fonts = ["font0", "font1", "font2", "font3"]
    vjust = {0: "top", 1: "middle", 2: "bottom"}
    hjust = {0: "left", 1: "center", 2: "right"}
    return (f"{fonts[(value >> 4) & 3]},"
            f"{vjust.get((value >> 2) & 3, '?')},"
            f"{hjust.get(value & 3, '?')}")


def scan(blob):
    """One pass over a raw GDS byte stream.

    Returns (labels, field_by_container, pad_findings, pad_stats) where
    labels is the file-ordered list of TEXT elements with their fields,
    field_by_container counts every PRESENTATION/STRANS/MAG/ANGLE record
    by the element type that holds it (accounting for the file totals),
    pad_findings lists every non-NUL pad byte occurrence, and pad_stats
    summarises the ASCII-record pad scan.
    """
    labels = []
    field_by_container = Counter()
    pad_findings = []
    pad_stats = {"records_scanned": 0, "padded_records": 0,
                 "odd_length_contents": 0,
                 "pad_length_histogram": Counter(), "by_record": Counter()}
    container = None
    current = None
    offset = 0
    while offset + 4 <= len(blob):
        (length,) = struct.unpack(">H", blob[offset:offset + 2])
        rectype = blob[offset + 2]
        if length < 4:
            break
        payload = blob[offset + 4:offset + length]

        if rectype in CONTAINERS:
            container = CONTAINERS[rectype]
            if rectype == TEXT:
                current = {"layer": None, "texttype": None,
                           "presentation": None, "strans": None,
                           "mag": None, "angle": None, "text": None}
        elif rectype == ENDEL:
            if current is not None:
                labels.append(current)
                current = None
            container = None
        elif rectype == LAYER and current is not None:
            (current["layer"],) = struct.unpack(">h", payload[:2])
        elif rectype == TEXTTYPE and current is not None:
            (current["texttype"],) = struct.unpack(">h", payload[:2])
        elif rectype in (PRESENTATION, STRANS):
            field_by_container[(RECORD_NAMES[rectype], container)] += 1
            if current is not None:
                (value,) = struct.unpack(">H", payload[:2])
                key = "presentation" if rectype == PRESENTATION else "strans"
                current[key] = float(value)
        elif rectype in (MAG, ANGLE):
            field_by_container[(RECORD_NAMES[rectype], container)] += 1
            if current is not None:
                key = "mag" if rectype == MAG else "angle"
                current[key] = gds_real(payload)

        if rectype in ASCII_RECORDS:
            name = ASCII_RECORDS[rectype]
            pad_stats["records_scanned"] += 1
            pad_stats["by_record"][name] += 1
            nul = payload.find(b"\0")
            if nul < 0:
                content, pad = payload, b""
            else:
                content, pad = payload[:nul], payload[nul + 1:]
                pad_stats["padded_records"] += 1
                pad_stats["pad_length_histogram"][len(pad) + 1] += 1
            if len(content) % 2 == 1:
                pad_stats["odd_length_contents"] += 1
            bad = [b for b in pad if b != 0]
            if bad:
                pad_findings.append({
                    "record": name, "offset": offset,
                    "content": content.decode("ascii", "replace"),
                    "non_nul_pad_bytes": len(bad),
                    "pad_values": sorted(set(bad))})
            if rectype == STRING and current is not None:
                current["text"] = content.decode("ascii", "replace")
        offset += length
    return labels, field_by_container, pad_findings, pad_stats


def dominant_by_layer(labels, field):
    """Modal value of a field per (layer, texttype)."""
    per_layer = {}
    for label in labels:
        key = f"{label['layer']}/{label['texttype']}"
        per_layer.setdefault(key, Counter())[value_of(label, field)] += 1
    return {key: counts.most_common(1)[0][0]
            for key, counts in per_layer.items()}


def value_of(label, field):
    if field == "presence":
        return "".join(flag for flag, key in
                       (("P", "presentation"), ("S", "strans"),
                        ("M", "mag"), ("A", "angle"))
                       if label[key] is not None) or "-"
    return fmt(label[field])


def find_deviants(labels, field):
    dominants = dominant_by_layer(labels, field)
    deviants = []
    for index, label in enumerate(labels):
        key = f"{label['layer']}/{label['texttype']}"
        value = value_of(label, field)
        if value != dominants[key]:
            deviants.append({"index": index, "layer": key,
                             "text": label["text"], "value": value,
                             "dominant": dominants[key]})
    return dominants, deviants


def bits_to_ascii(bits, msb_first):
    chars = []
    for start in range(0, len(bits) - len(bits) % 8, 8):
        chunk = bits[start:start + 8]
        if not msb_first:
            chunk = chunk[::-1]
        chars.append(int("".join(map(str, chunk)), 2))
    printable = [c for c in chars if 32 <= c <= 126]
    fraction = len(printable) / len(chars) if chars else 0.0
    decoded = "".join(chr(c) for c in chars) if chars else ""
    return decoded, fraction


def decode_attempts(labels, field, deviants):
    """Deterministic decode attempts on a deviating sequence."""
    attempts = []
    deviant_set = {d["index"] for d in deviants}
    bits = [1 if i in deviant_set else 0 for i in range(len(labels))]
    for msb in (True, False):
        decoded, fraction = bits_to_ascii(bits, msb)
        good = fraction >= 0.8 and len(decoded) >= 2
        attempts.append({
            "channel": field, "method":
                f"deviation bitmap over all {len(labels)} labels, "
                f"{'MSB' if msb else 'LSB'}-first bytes",
            "symbols": len(bits), "printable_fraction": round(fraction, 3),
            "decoded": decoded if good else None,
            "verdict": "printable" if good else "not printable"})
    codes = []
    for deviant in deviants:
        try:
            codes.append(int(round(float(deviant["value"]))))
        except ValueError:
            codes.append(-1)
    printable = [c for c in codes if 32 <= c <= 126]
    fraction = len(printable) / len(codes) if codes else 0.0
    good = fraction >= 0.8 and len(codes) >= 2
    attempts.append({
        "channel": field,
        "method": "deviating values as ASCII codes, file order",
        "symbols": len(codes), "printable_fraction": round(fraction, 3),
        "decoded": "".join(chr(c) if 32 <= c <= 126 else "." for c in codes)
                   if good else None,
        "verdict": "printable" if good else
                   ("not printable" if codes else "empty")})
    return attempts


def analyse(blob, name):
    labels, by_container, pad_findings, pad_stats = scan(blob)
    report = {"file": name, "text_elements": len(labels),
              "field_records_by_container": {
                  f"{rec} in {cont}": count for (rec, cont), count
                  in sorted(by_container.items(), key=lambda kv: str(kv[0]))},
              "per_layer": {}, "fields": {}, "pad_scan": None}
    layer_hist = {}
    for label in labels:
        key = f"{label['layer']}/{label['texttype']}"
        entry = layer_hist.setdefault(key, {f: Counter() for f in FIELDS})
        for field in FIELDS:
            entry[field][value_of(label, field)] += 1
    for key in sorted(layer_hist):
        report["per_layer"][key] = {
            "labels": sum(layer_hist[key]["presence"].values()),
            **{field: dict(layer_hist[key][field].most_common())
               for field in FIELDS}}
    for field in FIELDS:
        dominants, deviants = find_deviants(labels, field)
        entry = {"dominant_per_layer": dominants,
                 "deviating_labels": len(deviants),
                 "deviants": deviants[:200], "decode_attempts": []}
        if deviants:
            entry["decode_attempts"] = decode_attempts(labels, field,
                                                       deviants)
        if field == "presentation":
            entry["value_meanings"] = {
                value: presentation_meaning(int(float(value)))
                for value in sorted({fmt(l["presentation"]) for l in labels
                                     if l["presentation"] is not None})}
        report["fields"][field] = entry
    pad_stats["pad_length_histogram"] = dict(
        sorted(pad_stats["pad_length_histogram"].items()))
    pad_stats["by_record"] = dict(sorted(pad_stats["by_record"].items()))
    pad_stats["non_nul_pad_findings"] = pad_findings
    pad_stats["verdict"] = ("FAIL: non-NUL pad bytes present"
                            if pad_findings else "clean: every pad byte NUL")
    report["pad_scan"] = pad_stats
    return report


def print_summary(report):
    print(f"=== {report['file']} ===")
    print(f"TEXT elements: {report['text_elements']}; field records: " +
          ", ".join(f"{k} x{v}" for k, v in
                    report["field_records_by_container"].items()))
    for key, entry in report["per_layer"].items():
        parts = []
        for field in FIELDS:
            hist = entry[field]
            parts.append(field + "{" + " ".join(
                f"{v}:{n}" for v, n in hist.items()) + "}")
        print(f"  layer {key} ({entry['labels']} labels): "
              + " ".join(parts))
    for field in FIELDS:
        entry = report["fields"][field]
        count = entry["deviating_labels"]
        if not count:
            print(f"  {field}: no label deviates from its layer dominant")
            continue
        print(f"  {field}: {count} deviating labels")
        for attempt in entry["decode_attempts"]:
            shown = (repr(attempt["decoded"])
                     if attempt["decoded"] is not None
                     else attempt["verdict"])
            print(f"    decode [{attempt['method']}]: "
                  f"printable {attempt['printable_fraction']}: {shown}")
    pads = report["pad_scan"]
    print(f"  pad scan: {pads['records_scanned']} ASCII records "
          f"({', '.join(f'{k} x{v}' for k, v in pads['by_record'].items())}),"
          f" {pads['odd_length_contents']} odd-length contents, "
          f"{pads['padded_records']} padded -> {pads['verdict']}")
    print()


# --- selftest -------------------------------------------------------------

def record(rectype, datatype, payload, raw=False):
    body = payload if raw else payload + (b"\0" if len(payload) % 2 else b"")
    return struct.pack(">HBB", 4 + len(body), rectype, datatype) + body


def make_label(text, presentation=5, mag=0.17, angle=None):
    stream = (record(TEXT, 0, b"")
              + record(LAYER, 2, struct.pack(">h", 67))
              + record(TEXTTYPE, 2, struct.pack(">h", 5)))
    if presentation is not None:
        stream += record(PRESENTATION, 1, struct.pack(">H", presentation))
    stream += record(STRANS, 1, struct.pack(">H", 0))
    if mag is not None:
        # 0.17 is awkward in base 16; use gds_real's inverse on a value
        # that round-trips exactly: mantissa*16^(e-64)/2^56.
        stream += record(MAG, 5, bytes([64 + 0])
                         + int(mag * (1 << 56)).to_bytes(7, "big"))
    if angle is not None:
        stream += record(ANGLE, 5, bytes([64 + 2])
                         + int(angle / 256.0 * (1 << 56)).to_bytes(7, "big"))
    stream += (record(0x10, 3, struct.pack(">ii", 0, 0))
               + record(STRING, 6, text.encode())
               + record(ENDEL, 0, b""))
    return stream


def make_stream(labels, strname=b"self", bad_pad=False):
    body = b"".join(labels)
    if bad_pad:
        # content "BAD", NUL terminator, then a smuggled 0x07 and one NUL:
        # invisible to any reader that stops at the first NUL.
        body += record(STRING, 6, b"BAD\x00\x07\x00", raw=True)
    return (record(0x00, 2, struct.pack(">h", 600))
            + record(0x01, 2, b"\0" * 24)
            + record(LIBNAME, 6, b"lib")
            + record(0x03, 5, b"\0" * 16)
            + record(0x05, 2, b"\0" * 24)
            + record(STRNAME, 6, strname)
            + body
            + record(0x07, 0, b"")
            + record(0x04, 0, b""))


def selftest():
    failures = []

    # Negative control: ten default labels, nothing planted.
    clean = make_stream([make_label(f"n{i}") for i in range(10)])
    report = analyse(clean, "clean")
    planted_free = all(report["fields"][f]["deviating_labels"] == 0
                       for f in FIELDS)
    if not planted_free:
        failures.append("clean stream reported a deviating label")
    if report["pad_scan"]["non_nul_pad_findings"]:
        failures.append("clean stream reported a non-NUL pad")
    if report["text_elements"] != 10:
        failures.append(f"clean stream: {report['text_elements']} labels")

    # Plant 1: one non-default PRESENTATION (6 = font0,middle,right)
    # among ten defaults (5 = font0,middle,center), at index 7.
    labels = [make_label(f"n{i}") for i in range(10)]
    labels[7] = make_label("n7", presentation=6)
    report = analyse(make_stream(labels), "deviant")
    deviants = report["fields"]["presentation"]["deviants"]
    if (report["fields"]["presentation"]["deviating_labels"] != 1
            or not deviants or deviants[0]["index"] != 7
            or deviants[0]["value"] != "6"):
        failures.append("planted PRESENTATION=6 at index 7 not caught: "
                        f"{deviants!r}")
    if not report["fields"]["presentation"]["decode_attempts"]:
        failures.append("deviating PRESENTATION produced no decode attempt")

    # Plant 2: a non-NUL byte behind a STRING terminator.
    report = analyse(make_stream([make_label("n0")], bad_pad=True), "pad")
    findings = report["pad_scan"]["non_nul_pad_findings"]
    if (len(findings) != 1 or findings[0]["record"] != "STRING"
            or findings[0]["content"] != "BAD"
            or findings[0]["pad_values"] != [7]):
        failures.append(f"planted non-NUL pad not caught: {findings!r}")
    if not report["pad_scan"]["verdict"].startswith("FAIL"):
        failures.append("pad verdict did not fail loudly")

    # And the real-real: MAG written here must read back exactly.
    labels_read, _, _, _ = scan(make_stream([make_label("m", mag=0.25)]))
    if fmt(labels_read[0]["mag"]) != "0.25":
        failures.append(f"gds_real round trip: {labels_read[0]['mag']!r}")

    if failures:
        for line in failures:
            print(f"SELFTEST FAIL: {line}")
        return 1
    print("SELFTEST PASS: clean stream silent, planted PRESENTATION "
          "deviant caught at the right index, planted non-NUL pad byte "
          "caught with the right value, MAG real round-trips (4 checks)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    paths = ([Path(p) for p in argv] if argv
             else [CONTROL] + BATTERY)
    reports = []
    status = 0
    for path in paths:
        report = analyse(path.read_bytes(), str(path.relative_to(ROOT)
                                                if path.is_absolute()
                                                and path.is_relative_to(ROOT)
                                                else path))
        report["role"] = ("control (flow default)" if path == CONTROL
                          else "target")
        print_summary(report)
        if report["pad_scan"]["non_nul_pad_findings"]:
            print(f"LOUD FAILURE: non-NUL pad bytes in {path}")
            status = 1
        reports.append(report)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"tool": "egg_label_fields.py", "reports": reports}, indent=2))
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
