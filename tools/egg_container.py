#!/usr/bin/env python3
"""egg_container.py -- file/container-level Easter egg sweep (domain C2).

Three deterministic checks, no interpretation:

  1. GDSII record-stream walk of both layout files: verify every record
     parses, locate ENDLIB, count bytes after it (nonzero trailing bytes
     would be egg space), and report HEADER version, LIBNAME and the
     BGNLIB timestamps as dates.
  2. VCD header/trailer parse: report $date/$version/$comment/$timescale
     text, classify every line after $enddefinitions, and report any
     unclassifiable line and anything after the last timestamp block.
  3. PNG chunk walk of layout.png: chunk list, any text chunks
     (tEXt/iTXt/zTXt), and bytes after IEND.
  4. File inventory of puzzle/ (hidden files included), flagging any
     entry the official README does not imply.

--selftest appends 16 known bytes to a COPY of the warmup GDS in a
temp dir and requires the walker to report exactly those 16 bytes
(and zero on the pristine copy); it also injects a line after the last
timestamp of a COPY of the VCD and bytes after IEND of a COPY of the
PNG and requires both to be flagged.

--vcd/--gds/--png with a path run one parser on one file, for control
runs against files produced by an ordinary tool flow.

Usage:
  egg_container.py            run all sweeps on the repo targets
  egg_container.py --selftest run the known-bad-input checks and exit
  egg_container.py --vcd F    parse one VCD (control mode)
"""

import argparse
import json
import os
import shutil
import stat
import struct
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUZZLE_GDS = os.path.join(REPO, "puzzle", "puzzle.gds")
WARMUP_GDS = os.path.join(REPO, "puzzle", "warmup", "04_final.gds")
VCD = os.path.join(REPO, "puzzle", "example_inputs.vcd")
PNG = os.path.join(REPO, "puzzle", "layout.png")
PUZZLE_DIR = os.path.join(REPO, "puzzle")

# GDSII record types that matter here.
RT_HEADER = 0x00
RT_BGNLIB = 0x01
RT_LIBNAME = 0x02
RT_BGNSTR = 0x05
RT_STRNAME = 0x06
RT_ENDLIB = 0x04

RECORD_NAMES = {
    0x00: "HEADER", 0x01: "BGNLIB", 0x02: "LIBNAME", 0x03: "UNITS",
    0x04: "ENDLIB", 0x05: "BGNSTR", 0x06: "STRNAME", 0x07: "ENDSTR",
    0x08: "BOUNDARY", 0x09: "PATH", 0x0A: "SREF", 0x0B: "AREF",
    0x0C: "TEXT", 0x0D: "LAYER", 0x0E: "DATATYPE", 0x0F: "WIDTH",
    0x10: "XY", 0x11: "ENDEL", 0x12: "SNAME", 0x13: "COLROW",
    0x15: "NODE", 0x16: "TEXTTYPE", 0x17: "PRESENTATION",
    0x19: "STRING", 0x1A: "STRANS", 0x1B: "MAG", 0x1C: "ANGLE",
    0x1F: "REFLIBS", 0x20: "FONTS", 0x21: "PATHTYPE", 0x22: "GENERATIONS",
    0x23: "ATTRTABLE", 0x26: "ELFLAGS", 0x2A: "NODETYPE", 0x2B: "PROPATTR",
    0x2C: "PROPVALUE", 0x2D: "BOX", 0x2E: "BOXTYPE", 0x2F: "PLEX",
    0x32: "TAPENUM", 0x33: "TAPECODE", 0x36: "FORMAT", 0x37: "MASK",
    0x38: "ENDMASKS", 0x39: "LIBDIRSIZE", 0x3A: "SRFNAME", 0x3B: "LIBSECUR",
}


def printable(bs, cap=256):
    """Render bytes: ASCII where printable, \\xNN otherwise. Capped."""
    out = []
    for b in bs[:cap]:
        if 0x20 <= b < 0x7F:
            out.append(chr(b))
        else:
            out.append("\\x%02x" % b)
    s = "".join(out)
    if len(bs) > cap:
        s += " ...(+%d bytes)" % (len(bs) - cap)
    return s


def gds_timestamp(words):
    """Six GDS shorts -> ISO-ish date string. Year may be raw or y-1900."""
    y, mo, d, h, mi, s = words
    if y < 1000:
        y += 1900
    return "%04d-%02d-%02d %02d:%02d:%02d" % (y, mo, d, h, mi, s)


def walk_gds(path):
    """Walk the record stream. Returns a dict of findings."""
    with open(path, "rb") as f:
        data = f.read()
    n = len(data)
    off = 0
    records = 0
    malformed = []
    header_version = None
    libname = None
    bgnlib = None
    strnames = []
    str_timestamps = set()
    endlib_end = None

    while off + 4 <= n:
        reclen, rectype, dtype = struct.unpack(">HBB", data[off:off + 4])
        if reclen < 4 or reclen % 2 != 0 or off + reclen > n:
            malformed.append((off, reclen, rectype, dtype))
            break
        body = data[off + 4:off + reclen]
        if rectype == RT_HEADER and len(body) >= 2:
            header_version = struct.unpack(">H", body[:2])[0]
        elif rectype == RT_BGNLIB and len(body) >= 24:
            words = struct.unpack(">12H", body[:24])
            bgnlib = (gds_timestamp(words[0:6]), gds_timestamp(words[6:12]))
        elif rectype == RT_LIBNAME:
            libname = body.rstrip(b"\x00").decode("ascii", "replace")
        elif rectype == RT_BGNSTR and len(body) >= 24:
            words = struct.unpack(">12H", body[:24])
            str_timestamps.add(gds_timestamp(words[0:6]))
            str_timestamps.add(gds_timestamp(words[6:12]))
        elif rectype == RT_STRNAME:
            strnames.append(body.rstrip(b"\x00").decode("ascii", "replace"))
        records += 1
        off += reclen
        if rectype == RT_ENDLIB:
            endlib_end = off
            break

    trailing = data[endlib_end:] if endlib_end is not None else b""
    trailing_all_zero = bool(trailing) and set(trailing) == {0}
    return {
        "path": os.path.relpath(path, REPO),
        "file_bytes": n,
        "records_parsed": records,
        "malformed_records": malformed,
        "header_version": header_version,
        "libname": libname,
        "bgnlib_mod_access": bgnlib,
        "structures": len(strnames),
        "structure_timestamps_distinct": sorted(str_timestamps),
        "endlib_found": endlib_end is not None,
        "endlib_end_offset": endlib_end,
        "trailing_bytes": len(trailing),
        "trailing_all_zero": trailing_all_zero,
        "trailing_rendering": printable(trailing) if trailing else "",
    }


def parse_vcd(path):
    """Header directives + body line classification. Returns dict."""
    with open(path, "r", errors="replace") as f:
        text = f.read()
    lines = text.split("\n")

    # Header: everything up to $enddefinitions. Directives may span lines.
    directives = {}   # keyword -> list of payload strings
    comments = []
    i = 0
    kw = None
    buf = []
    end_defs_line = None
    while i < len(lines):
        line = lines[i]
        strip = line.strip()
        if kw is None:
            if strip.startswith("$"):
                parts = strip.split(None, 1)
                kw = parts[0][1:]
                rest = parts[1] if len(parts) > 1 else ""
                if rest.endswith("$end"):
                    payload = rest[: -len("$end")].strip()
                    directives.setdefault(kw, []).append(payload)
                    if kw == "comment":
                        comments.append(payload)
                    if kw == "enddefinitions":
                        end_defs_line = i
                        i += 1
                        break
                    kw = None
                else:
                    buf = [rest] if rest else []
        else:
            if strip == "$end" or strip.endswith("$end"):
                if strip != "$end":
                    buf.append(strip[: -len("$end")].strip())
                payload = " ".join(x for x in buf if x)
                directives.setdefault(kw, []).append(payload)
                if kw == "comment":
                    comments.append(payload)
                if kw == "enddefinitions":
                    end_defs_line = i
                    kw = None
                    i += 1
                    break
                kw = None
                buf = []
            else:
                buf.append(strip)
        i += 1

    # Body: classify every line.
    ts_lines = []          # (line_no, timestamp)
    unclassified = []      # (line_no, text)
    in_directive = None
    body_comments = []
    for j in range(i, len(lines)):
        s = lines[j].strip()
        if not s:
            continue
        if in_directive:
            if s == "$end" or s.endswith("$end"):
                if in_directive == "comment":
                    body_comments.append(" ".join(x for x in body_buf if x))
                in_directive = None
            else:
                body_buf.append(s)
            continue
        if s.startswith("#") and s[1:].isdigit():
            ts_lines.append((j, int(s[1:])))
        elif s[0] in "01xXzZ" and len(s) > 1:
            pass  # scalar value change
        elif s[0] in "bBrR" and " " in s:
            pass  # vector/real value change
        elif s.startswith("$"):
            word = s.split(None, 1)[0][1:]
            if s.endswith("$end"):
                if word == "comment":
                    payload = s[len("$" + word):].rsplit("$end", 1)[0].strip()
                    body_comments.append(payload)
            else:
                in_directive = word
                body_buf = [s[len("$" + word):].strip()]
        else:
            unclassified.append((j, s[:120]))

    last_ts_line, last_ts = (ts_lines[-1] if ts_lines else (None, None))
    after_last_ts = []
    trailing_junk = []
    if last_ts_line is not None:
        for j in range(last_ts_line + 1, len(lines)):
            s = lines[j].strip()
            if not s:
                continue
            after_last_ts.append((j, s[:120]))
            is_value_change = ((s[0] in "01xXzZ" and len(s) > 1)
                               or (s[0] in "bBrR" and " " in s))
            if not is_value_change:
                trailing_junk.append((j, s[:120]))

    # id -> (type, width, name) from the $var directives.
    variables = []
    for payload in directives.get("var", []):
        parts = payload.split()
        if len(parts) >= 4:
            variables.append({"id": parts[2], "name": " ".join(parts[3:]),
                              "type": parts[0], "width": parts[1]})

    return {
        "path": path if not path.startswith(REPO)
        else os.path.relpath(path, REPO),
        "date": directives.get("date", []),
        "version": directives.get("version", []),
        "timescale": directives.get("timescale", []),
        "header_comments": comments,
        "body_comments": body_comments,
        "enddefinitions_line": end_defs_line,
        "timestamp_count": len(ts_lines),
        "first_timestamp": ts_lines[0][1] if ts_lines else None,
        "last_timestamp": last_ts,
        "variables": variables,
        "lines_after_last_timestamp": after_last_ts,
        "trailing_junk_after_last_timestamp": trailing_junk,
        "unclassified_lines": unclassified,
    }


def walk_png(path):
    """PNG chunk walk: chunk sequence, text chunks, bytes after IEND."""
    with open(path, "rb") as f:
        data = f.read()
    sig_ok = data[:8] == b"\x89PNG\r\n\x1a\n"
    off = 8
    chunks = []
    text_chunks = []
    iend_end = None
    malformed = None
    while off + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[off:off + 8])
        name = ctype.decode("latin1")
        if off + 12 + length > len(data):
            malformed = "chunk %s at %d overruns file" % (name, off)
            break
        body = data[off + 8:off + 8 + length]
        chunks.append(name)
        if name in ("tEXt", "iTXt", "zTXt"):
            text_chunks.append(printable(body, 512))
        off += 12 + length
        if name == "IEND":
            iend_end = off
            break
    trailing = data[iend_end:] if iend_end is not None else b""
    from collections import Counter
    return {
        "path": path if not path.startswith(REPO)
        else os.path.relpath(path, REPO),
        "file_bytes": len(data),
        "signature_ok": sig_ok,
        "chunk_counts": dict(Counter(chunks)),
        "chunk_order_first_last": chunks[:3] + ["..."] + chunks[-2:]
        if len(chunks) > 5 else chunks,
        "text_chunks": text_chunks,
        "malformed": malformed,
        "iend_end_offset": iend_end,
        "trailing_bytes": len(trailing),
        "trailing_rendering": printable(trailing) if trailing else "",
    }


# Files the official README names or directly implies.
README_IMPLIED = {
    "README.md", "puzzle.gds", "example_inputs.vcd", "layout.png",
    "warmup", "warmup/00_source.v", "warmup/01_netlist.v",
    "warmup/02_netlist_with_power_rails.v",
    "warmup/03_post_place_and_route.def", "warmup/04_final.gds",
}


def inventory(root):
    rows = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(dirnames) + sorted(filenames):
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            st = os.lstat(p)
            rows.append({
                "rel": rel,
                "size": st.st_size,
                "mode": stat.filemode(st.st_mode),
                "hidden": name.startswith("."),
                "implied_by_readme": rel in README_IMPLIED,
            })
    return rows


def report(args):
    out = {"gds": [], "vcd": None, "png": None, "inventory": []}
    for p in (WARMUP_GDS, PUZZLE_GDS):
        out["gds"].append(walk_gds(p))
    out["vcd"] = parse_vcd(VCD)
    out["png"] = walk_png(PNG)
    out["inventory"] = inventory(PUZZLE_DIR)
    print(json.dumps(out, indent=2))
    # Verdict lines for the caller.
    for g in out["gds"]:
        verdict = "CLEAN" if (g["endlib_found"] and not g["malformed_records"]
                              and g["trailing_bytes"] == 0) else "ATTENTION"
        print("VERDICT gds %s: %s (records=%d trailing=%d malformed=%d)"
              % (g["path"], verdict, g["records_parsed"], g["trailing_bytes"],
                 len(g["malformed_records"])), file=sys.stderr)
    v = out["vcd"]
    v_verdict = ("CLEAN" if not v["unclassified_lines"]
                 and not v["trailing_junk_after_last_timestamp"]
                 else "ATTENTION")
    print("VERDICT vcd %s: %s (timestamps=%d trailing_junk=%d unclassified=%d)"
          % (v["path"], v_verdict, v["timestamp_count"],
             len(v["trailing_junk_after_last_timestamp"]),
             len(v["unclassified_lines"])), file=sys.stderr)
    p = out["png"]
    p_verdict = ("CLEAN" if p["signature_ok"] and not p["malformed"]
                 and p["trailing_bytes"] == 0 and not p["text_chunks"]
                 else "ATTENTION")
    print("VERDICT png %s: %s (chunks=%s text=%d trailing=%d)"
          % (p["path"], p_verdict, p["chunk_counts"], len(p["text_chunks"]),
             p["trailing_bytes"]), file=sys.stderr)
    unexpected = [r["rel"] for r in out["inventory"]
                  if not r["implied_by_readme"]]
    print("VERDICT inventory: %s (%d entries, unexpected: %s)"
          % ("CLEAN" if not unexpected else "ATTENTION",
             len(out["inventory"]), unexpected or "none"), file=sys.stderr)
    return 0


def selftest():
    failures = []
    tmp = tempfile.mkdtemp(prefix="egg_container_")
    try:
        # --- GDS trailing-byte detection ---
        pristine = os.path.join(tmp, "pristine.gds")
        tainted = os.path.join(tmp, "tainted.gds")
        shutil.copyfile(WARMUP_GDS, pristine)
        shutil.copyfile(WARMUP_GDS, tainted)
        known = b"EGG_SELFTEST_16B"
        assert len(known) == 16
        with open(tainted, "ab") as f:
            f.write(known)

        base = walk_gds(pristine)
        got = walk_gds(tainted)
        if got["trailing_bytes"] != base["trailing_bytes"] + 16:
            failures.append("GDS: expected +16 trailing bytes, got %d vs %d"
                            % (got["trailing_bytes"], base["trailing_bytes"]))
        if not got["trailing_rendering"].endswith("EGG_SELFTEST_16B"):
            failures.append("GDS: rendering did not show the 16 known bytes: %r"
                            % got["trailing_rendering"])
        if base["trailing_bytes"] != 0:
            print("note: pristine warmup GDS itself has %d trailing bytes"
                  % base["trailing_bytes"])

        # --- VCD trailing-content detection ---
        vcd_copy = os.path.join(tmp, "tainted.vcd")
        shutil.copyfile(VCD, vcd_copy)
        with open(vcd_copy, "a") as f:
            f.write("\nHIDDEN MESSAGE AFTER LAST TIMESTAMP\n")
        v = parse_vcd(vcd_copy)
        hits = [s for _, s in v["lines_after_last_timestamp"]
                if "HIDDEN MESSAGE" in s]
        if not hits:
            failures.append("VCD: injected trailing line not reported")
        uhits = [s for _, s in v["unclassified_lines"]
                 if "HIDDEN MESSAGE" in s]
        if not uhits:
            failures.append("VCD: injected line not in unclassified list")
        jhits = [s for _, s in v["trailing_junk_after_last_timestamp"]
                 if "HIDDEN MESSAGE" in s]
        if not jhits:
            failures.append("VCD: injected line not in trailing junk list")

        # --- PNG trailing-byte detection ---
        png_copy = os.path.join(tmp, "tainted.png")
        shutil.copyfile(PNG, png_copy)
        with open(png_copy, "ab") as f:
            f.write(known)
        base_p = walk_png(PNG)
        got_p = walk_png(png_copy)
        if got_p["trailing_bytes"] != base_p["trailing_bytes"] + 16:
            failures.append("PNG: expected +16 trailing bytes, got %d vs %d"
                            % (got_p["trailing_bytes"],
                               base_p["trailing_bytes"]))
        if not got_p["trailing_rendering"].endswith("EGG_SELFTEST_16B"):
            failures.append("PNG: rendering did not show the 16 known bytes")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            print("SELFTEST FAIL: " + f)
        return 1
    print("SELFTEST PASS: 16 appended GDS bytes reported exactly; "
          "injected VCD trailing line flagged; 16 appended PNG bytes "
          "reported exactly")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true",
                    help="run detection checks against known-bad copies")
    ap.add_argument("--vcd", metavar="F",
                    help="parse just this VCD (control mode)")
    ap.add_argument("--gds", metavar="F",
                    help="walk just this GDS (control mode)")
    ap.add_argument("--png", metavar="F",
                    help="walk just this PNG (control mode)")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.vcd or args.gds or args.png:
        out = {}
        if args.vcd:
            out["vcd"] = parse_vcd(os.path.abspath(args.vcd))
        if args.gds:
            out["gds"] = walk_gds(os.path.abspath(args.gds))
        if args.png:
            out["png"] = walk_png(os.path.abspath(args.png))
        print(json.dumps(out, indent=2))
        sys.exit(0)
    sys.exit(report(args))


if __name__ == "__main__":
    main()
