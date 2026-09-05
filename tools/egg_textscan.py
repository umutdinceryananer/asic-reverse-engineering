#!/usr/bin/env python3
"""Easter-egg text scan over the puzzle's upstream text channel.

Targets (the only files scanned; our own docs/ and tools/ are not egg space):

    puzzle/README.md
    puzzle/warmup/00_source.v
    puzzle/warmup/01_netlist.v
    puzzle/warmup/02_netlist_with_power_rails.v
    puzzle/warmup/03_post_place_and_route.def

What it does, deterministically:

  1. Extracts every comment (Verilog //, /* */; DEF #; Markdown <!-- -->)
     and lists them verbatim.
  2. Dumps all module / instance / net / pin names from 01_netlist.v and the
     DEF to out/eggs/names_warmup.json, and reports distinct name prefixes
     with counts.
  3. Acrostic scan: first characters of consecutive non-blank lines, of
     comments in order, and of instance names (file order and sorted order).
     Every window of length >= 4 that is a dictionary word is reported,
     beside the SAME scan on a control: the identical sequence reversed.
  4. Numbers-as-ASCII: runs of >= MIN_RUN integer literals whose values all
     fall in 32..126 are decoded; a decode containing a dictionary word of
     length >= 4 is reported, beside two controls (lines reversed, and the
     global integer sequence reversed).
  5. Token audit: every alphabetic token that is neither a Verilog/DEF
     keyword, a library/tool artifact, nor a known design identifier is
     listed as unclassified for a human to judge.
  6. Byte-level oddities: non-ASCII bytes, trailing whitespace (a classic
     whitespace-steganography channel), tab/space mixes and CR bytes are
     counted per file; any line with trailing whitespace is listed.

--selftest plants an acrostic and an ASCII run in synthetic files, asserts
both are found, and asserts the reversed controls do not reproduce them.

Output: human-readable report on stdout plus a full JSON report at
out/eggs/textscan_report.json. Exit 0 on success, 1 on selftest failure.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "out" / "eggs"

SOURCES = {
    "README.md": REPO / "puzzle" / "README.md",
    "00_source.v": REPO / "puzzle" / "warmup" / "00_source.v",
    "01_netlist.v": REPO / "puzzle" / "warmup" / "01_netlist.v",
    "02_netlist_with_power_rails.v": REPO / "puzzle" / "warmup" / "02_netlist_with_power_rails.v",
    "03_post_place_and_route.def": REPO / "puzzle" / "warmup" / "03_post_place_and_route.def",
}

MIN_WORD = 4          # shortest dictionary word reported anywhere
MIN_RUN = 4           # shortest integer run decoded as ASCII
MAX_ACROSTIC = 12     # longest acrostic window tried

# ---------------------------------------------------------------- dictionary

SYSTEM_WORDS = Path("/usr/share/dict/words")

# Fallback so --selftest is meaningful on a machine without a word list.
FALLBACK_WORDS = {
    "secret", "hello", "world", "street", "jane", "puzzle", "answer",
    "hidden", "easter", "egg", "gold", "prize", "success", "again",
    "shift", "adder", "register", "clock", "reset", "enable", "wire",
    "input", "output", "module", "layer", "metal", "logic", "gate",
}


def load_dictionary():
    """Lowercase alphabetic words of length >= MIN_WORD, deterministic."""
    if SYSTEM_WORDS.exists():
        words = set()
        for line in SYSTEM_WORDS.read_text(encoding="utf-8", errors="replace").splitlines():
            w = line.strip()
            if len(w) >= MIN_WORD and w.isalpha() and w == w.lower():
                words.add(w)
        return words, f"{SYSTEM_WORDS} ({len(words)} words after filter)"
    return set(FALLBACK_WORDS), f"embedded fallback ({len(FALLBACK_WORDS)} words)"


# ---------------------------------------------------------------- comments

ESCAPED_ID = re.compile(r"\\\S+")           # Verilog escaped identifier: \foo/bar[0]
V_LINE = re.compile(r"//(.*)")
V_BLOCK = re.compile(r"/\*(.*?)\*/", re.S)
MD_BLOCK = re.compile(r"<!--(.*?)-->", re.S)
DEF_LINE = re.compile(r"#(.*)")


def extract_comments(label, text):
    """Return list of (kind, comment_text). Escaped identifiers are masked
    first in Verilog so \\add0/_00_ never fakes a // comment."""
    out = []
    if label.endswith(".v"):
        masked = ESCAPED_ID.sub(lambda m: " " * len(m.group(0)), text)
        for m in V_BLOCK.finditer(masked):
            out.append(("block", m.group(1).strip()))
        no_block = V_BLOCK.sub(" ", masked)
        for m in V_LINE.finditer(no_block):
            out.append(("line", m.group(1).strip()))
    elif label.endswith(".def"):
        for m in DEF_LINE.finditer(text):
            out.append(("hash", m.group(1).strip()))
    elif label.endswith(".md"):
        for m in MD_BLOCK.finditer(text):
            out.append(("html", m.group(1).strip()))
    return out


# ---------------------------------------------------------------- names

def parse_netlist_names(text):
    """Module, wire and instance names from a Yosys-style structural netlist."""
    modules = re.findall(r"^\s*module\s+(\S+)", text, re.M)
    wires = []
    for m in re.finditer(r"^\s*wire\s+(\\\S+|\w+)\s*;", text, re.M):
        wires.append(m.group(1).lstrip("\\"))
    instances = []
    # "  celltype instname (" — instname may be escaped.
    for m in re.finditer(r"^\s*(sky130_fd_sc_hd__\w+)\s+(\\\S+|\S+)\s*\(", text, re.M):
        instances.append({"cell": m.group(1), "name": m.group(2).lstrip("\\")})
    return {"modules": modules, "wires": wires, "instances": instances}


def parse_def_names(text):
    """Component, pin and net names from a DEF."""
    def section(kw):
        m = re.search(rf"^{kw}\s+\d+\s*;\s*$(.*?)^END {kw}", text, re.S | re.M)
        return m.group(1) if m else ""

    comps = re.findall(r"^\s*-\s+(\S+)\s+(\S+)", section("COMPONENTS"), re.M)
    pins = re.findall(r"^\s*-\s+(\S+)\s+\+", section("PINS"), re.M)
    nets = re.findall(r"^\s*-\s+(\S+)", section("NETS"), re.M)
    snets = re.findall(r"^\s*-\s+(\S+)", section("SPECIALNETS"), re.M)
    return {
        "components": [{"name": n, "cell": c} for n, c in comps],
        "pins": pins,
        "nets": nets,
        "specialnets": snets,
    }


def name_prefix(name):
    """Leading token of a hierarchical/bus name: up to first / . [ or digit-run
    boundary of a trailing _NN_ style suffix."""
    head = re.split(r"[/.\[]", name, 1)[0]
    head = re.sub(r"_\d+_?$", "", head)
    return head or name


# ---------------------------------------------------------------- acrostics

def first_alpha(s):
    for ch in s:
        if ch.isalpha():
            return ch.lower()
    return None


def acrostic_string(items):
    return "".join(c for c in (first_alpha(i) for i in items) if c)


def dictionary_windows(s, words):
    """All windows of length MIN_WORD..MAX_ACROSTIC in s that are words."""
    hits = []
    n = len(s)
    for length in range(MIN_WORD, MAX_ACROSTIC + 1):
        for i in range(0, n - length + 1):
            w = s[i:i + length]
            if w in words:
                hits.append({"word": w, "pos": i, "len": length})
    return hits


def acrostic_scan(name, items, words):
    fwd = acrostic_string(items)
    rev = acrostic_string(list(reversed(items)))
    return {
        "sequence": name,
        "n_items": len(items),
        "forward_hits": dictionary_windows(fwd, words),
        "control_reversed_hits": dictionary_windows(rev, words),
    }


# ---------------------------------------------------------------- numbers

INT_TOKEN = re.compile(r"(?<![\w'])(\d+)(?![\w'])")
BASED_HEX = re.compile(r"'h\s*([0-9a-fA-F_]+)")
BASED_BIN = re.compile(r"'b\s*([01_xz]+)")


def integer_stream(text):
    """All standalone decimal integers in reading order (line, value)."""
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        for m in INT_TOKEN.finditer(line):
            out.append((ln, int(m.group(1))))
    return out


def decode_runs(stream, words):
    """Maximal runs of >= MIN_RUN printable-range ints; keep the run if its
    decode contains a dictionary word of length >= MIN_WORD."""
    hits, run = [], []
    def flush():
        if len(run) >= MIN_RUN:
            s = "".join(chr(v) for _, v in run)
            found = sorted({w for w in words
                            if len(w) >= MIN_WORD and w in s.lower()})
            if found:
                hits.append({"lines": [run[0][0], run[-1][0]],
                             "decoded": s, "words": found})
        run.clear()
    for ln, v in stream:
        if 32 <= v <= 126:
            run.append((ln, v))
        else:
            flush()
    flush()
    return hits


def hex_bin_ascii(text, words):
    """Verilog based literals decoded as ASCII bytes."""
    hits = []
    for m in BASED_HEX.finditer(text):
        digits = m.group(1).replace("_", "")
        if len(digits) >= 2 * MIN_RUN and len(digits) % 2 == 0:
            try:
                b = bytes.fromhex(digits)
            except ValueError:
                continue
            if all(32 <= x <= 126 for x in b):
                s = b.decode("ascii")
                found = sorted({w for w in words if len(w) >= MIN_WORD and w in s.lower()})
                if found:
                    hits.append({"literal": m.group(0), "decoded": s, "words": found})
    for m in BASED_BIN.finditer(text):
        bits = m.group(1).replace("_", "")
        if len(bits) >= 8 * MIN_RUN and len(bits) % 8 == 0 and set(bits) <= {"0", "1"}:
            b = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
            if all(32 <= x <= 126 for x in b):
                s = b.decode("ascii")
                found = sorted({w for w in words if len(w) >= MIN_WORD and w in s.lower()})
                if found:
                    hits.append({"literal": m.group(0), "decoded": s, "words": found})
    return hits


def numbers_scan(label, text, words):
    stream = integer_stream(text)
    rev_lines = "\n".join(reversed(text.splitlines()))
    return {
        "file": label,
        "n_integers": len(stream),
        "forward_hits": decode_runs(stream, words) + hex_bin_ascii(text, words),
        "control_lines_reversed_hits": decode_runs(integer_stream(rev_lines), words),
        "control_sequence_reversed_hits": decode_runs(list(reversed(stream)), words),
    }


# ---------------------------------------------------------------- token audit

VERILOG_KW = {
    "module", "endmodule", "input", "output", "inout", "wire", "reg",
    "assign", "always", "posedge", "negedge", "begin", "end", "if", "else",
    "or", "and", "not", "buf",
}
DEF_KW = {
    "version", "dividerchar", "busbitchars", "design", "units", "distance",
    "microns", "diearea", "row", "tracks", "gcellgrid", "vias", "viarule",
    "cutsize", "layers", "cutspacing", "enclosure", "rowcol",
    "nondefaultrules", "nondefaultrule", "layer", "width", "spacing",
    "components", "pins", "nets", "specialnets", "end", "do", "by", "step",
    "placed", "fixed", "source", "dist", "net", "use", "signal", "power",
    "ground", "clock", "direction", "port", "shape", "stripe", "followpin",
    "routed", "new", "pin", "rect", "taper", "unithd", "offset", "timing",
    "special",
}
TECH = {
    "li", "met", "mcon", "via", "sky", "fd", "sc", "hd", "vdd", "gnd",
    "vpwr", "vgnd", "vpb", "vnb", "cts", "ndr", "sky130",
}
# Cell function fragments that appear inside sky130_fd_sc_hd__<fn>_<drive>
CELL_FN = {
    "a2bb2o", "a2bb2oi", "a21bo", "a21boi", "a21o", "a21oi", "a22o", "a22oi",
    "a31o", "a31oi", "a32o", "a32oi", "a41o", "a41oi", "a211o", "a211oi",
    "a221o", "a221oi", "a222oi", "a311o", "a311oi", "a2111o", "a2111oi",
    "and2", "and2b", "and3", "and3b", "and4", "and4b", "and4bb", "buf",
    "bufbuf", "bufinv", "clkbuf", "clkdlybuf4s15", "clkdlybuf4s18",
    "clkdlybuf4s25", "clkdlybuf4s50", "clkinv", "clkinvlp", "conb", "decap",
    "dfbbn", "dfbbp", "dfrbp", "dfrtn", "dfrtp", "dfsbp", "dfstp", "dfxbp",
    "dfxtp", "diode", "dlclkp", "dlrbn", "dlrbp", "dlrtn", "dlrtp", "dlxbn",
    "dlxbp", "dlxtn", "dlxtp", "dlygate4sd1", "dlygate4sd2", "dlygate4sd3",
    "dlymetal6s2s", "dlymetal6s4s", "dlymetal6s6s", "ebufn", "edfxbp",
    "edfxtp", "einvn", "einvp", "fa", "fah", "fahcin", "fahcon", "fill",
    "ha", "inv", "lpflow", "macro", "maj3", "mux2", "mux2i", "mux4", "nand2",
    "nand2b", "nand3", "nand3b", "nand4", "nand4b", "nand4bb", "nor2",
    "nor2b", "nor3", "nor3b", "nor4", "nor4b", "nor4bb", "o2bb2a", "o2bb2ai",
    "o21a", "o21ai", "o21ba", "o21bai", "o22a", "o22ai", "o31a", "o31ai",
    "o32a", "o32ai", "o41a", "o41ai", "o211a", "o211ai", "o221a", "o221ai",
    "o2111a", "o2111ai", "o311a", "o311ai", "or2", "or2b", "or3", "or3b",
    "or4", "or4b", "or4bb", "probe", "probec", "sdfbbn", "sdfbbp", "sdfrbp",
    "sdfrtn", "sdfrtp", "sdfsbp", "sdfstp", "sdfxbp", "sdfxtp", "sdlclkp",
    "sedfxbp", "sedfxtp", "tap", "tapvgnd", "tapvgnd2", "tapvpwrvgnd",
    "xnor2", "xnor3", "xor2", "xor3",
}
DESIGN_ID = {
    "adder_demo", "shift_register", "adder8", "comparator496", "sr_a",
    "sr_b", "add0", "cmp0", "a_reg", "b_reg", "parallel_out", "serial_in",
    "sum", "val", "eq", "clk", "rst_n", "en", "clknet", "clkbuf", "net",
    "input", "output", "wire", "physical", "filler", "phy", "tap", "welltap",
    "antenna", "max", "leaf", "delay",
}
# README is prose; its ordinary English is mundane by definition. Only
# machine-looking tokens (long mixed alnum, base64/hex-ish) are flagged there.
MACHINE_TOKEN = re.compile(r"^(?=.*\d)(?=.*[a-zA-Z])[A-Za-z0-9+/=_-]{12,}$|^[0-9a-fA-F]{10,}$")

WORD_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def audit_tokens(label, text):
    """Tokens that are neither keywords, tech/library artifacts, design
    identifiers, nor numeric-decorated variants of those."""
    odd = Counter()
    if label.endswith(".md"):
        for tok in re.findall(r"\S+", text):
            tok = tok.strip("()[]`.,;:!*#<>\"'")
            if MACHINE_TOKEN.match(tok) and not tok.startswith("http"):
                odd[tok] += 1
        return odd
    for tok in WORD_TOKEN.findall(text):
        t = tok.lower()
        if t in VERILOG_KW or t in DEF_KW or t in DESIGN_ID:
            continue
        base = re.sub(r"_\d+$", "", t)                 # drive strength / index
        base = re.sub(r"\d+$", "", base)               # trailing digits
        if base in VERILOG_KW or base in DEF_KW or base in DESIGN_ID or base in TECH:
            continue
        if t.startswith("sky130_fd_sc_hd__"):
            fn = re.sub(r"_\d+$", "", t[len("sky130_fd_sc_hd__"):])
            if fn in CELL_FN:
                continue
        if re.fullmatch(r"_\d+_", tok):                # Yosys temp names
            continue
        if re.fullmatch(r"row_\d+|via\d?_.*|m\d+m\d+_pr|cts_ndr_\d+", t):
            continue
        if re.fullmatch(r"(fanout|max_length|wire\d*|clone|delay\d*)", base):
            continue
        odd[tok] += 1
    return odd


# ---------------------------------------------------------------- bytes

def byte_oddities(path):
    raw = path.read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 126 or (b < 32 and b not in (9, 10, 13))]
    lines = raw.split(b"\n")
    trailing = [i + 1 for i, l in enumerate(lines) if l.rstrip(b"\r") != l.rstrip(b"\r").rstrip(b" \t")]
    return {
        "bytes": len(raw),
        "non_ascii_or_control": non_ascii[:20],
        "n_non_ascii_or_control": len(non_ascii),
        "cr_bytes": raw.count(b"\r"),
        "tab_bytes": raw.count(b"\t"),
        "lines_with_trailing_ws": trailing[:50],
        "n_lines_with_trailing_ws": len(trailing),
    }


# ---------------------------------------------------------------- main scans

def run_scan(words, dict_src):
    report = {"dictionary": dict_src, "comments": {}, "names": {},
              "acrostics": [], "numbers": [], "token_audit": {}}

    texts = {}
    for label, path in SOURCES.items():
        texts[label] = path.read_text(encoding="utf-8", errors="replace")

    # 1. comments
    all_comments = []
    for label, text in texts.items():
        cs = extract_comments(label, text)
        report["comments"][label] = cs
        all_comments.extend(c for _, c in cs)

    # 2. names
    net_names = parse_netlist_names(texts["01_netlist.v"])
    def_names = parse_def_names(texts["03_post_place_and_route.def"])
    names_dump = {"01_netlist.v": net_names, "03_post_place_and_route.def": def_names}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "names_warmup.json").write_text(json.dumps(names_dump, indent=1))

    prefixes = Counter()
    for inst in net_names["instances"]:
        prefixes[name_prefix(inst["name"])] += 1
    for w in net_names["wires"]:
        prefixes[name_prefix(w)] += 1
    for c in def_names["components"]:
        prefixes[name_prefix(c["name"])] += 1
    for n in def_names["nets"]:
        prefixes[name_prefix(n)] += 1
    report["names"] = {
        "modules": net_names["modules"],
        "counts": {
            "netlist_wires": len(net_names["wires"]),
            "netlist_instances": len(net_names["instances"]),
            "def_components": len(def_names["components"]),
            "def_pins": def_names["pins"],
            "def_nets": len(def_names["nets"]),
            "def_specialnets": def_names["specialnets"],
        },
        "prefixes": dict(sorted(prefixes.items(), key=lambda kv: -kv[1])),
        "dump": str(OUT_DIR / "names_warmup.json"),
    }

    # 3. acrostics
    for label, text in texts.items():
        lines = [l for l in text.splitlines() if l.strip()]
        report["acrostics"].append(acrostic_scan(f"{label}:lines", lines, words))
    report["acrostics"].append(acrostic_scan("comments:in-order", all_comments, words))
    inst_file_order = [i["name"] for i in net_names["instances"]]
    comp_file_order = [c["name"] for c in def_names["components"]]
    report["acrostics"].append(acrostic_scan("01_netlist.v:instances:file-order", inst_file_order, words))
    report["acrostics"].append(acrostic_scan("01_netlist.v:instances:sorted", sorted(inst_file_order), words))
    report["acrostics"].append(acrostic_scan("def:components:file-order", comp_file_order, words))
    report["acrostics"].append(acrostic_scan("def:components:sorted", sorted(comp_file_order), words))

    # 4. numbers as ASCII
    for label, text in texts.items():
        report["numbers"].append(numbers_scan(label, text, words))

    # 5. token audit
    for label, text in texts.items():
        odd = audit_tokens(label, text)
        report["token_audit"][label] = dict(sorted(odd.items(), key=lambda kv: -kv[1]))

    # 6. byte-level oddities
    report["byte_oddities"] = {label: byte_oddities(path) for label, path in SOURCES.items()}

    return report


# ---------------------------------------------------------------- selftest

def selftest(words):
    ok = True
    msgs = []

    # planted acrostic: first letters spell 'secret' inside noise lines
    noise = list("xqzkvjxqzwbvv")
    lines = [f"{c}_line noise;" for c in noise[:6]]
    lines += [f"{c}tuff planted;" for c in "secret"]
    lines += [f"{c}_line noise;" for c in noise[6:]]
    res = acrostic_scan("selftest:planted", lines, words)
    fwd_words = {h["word"] for h in res["forward_hits"]}
    rev_words = {h["word"] for h in res["control_reversed_hits"]}
    if "secret" not in fwd_words:
        ok = False
        msgs.append("FAIL: planted acrostic 'secret' not found")
    else:
        msgs.append(f"pass: planted acrostic found; forward hits={sorted(fwd_words)}")
    if "secret" in rev_words:
        ok = False
        msgs.append("FAIL: reversed control still contains 'secret'")
    else:
        msgs.append(f"pass: reversed control lacks the plant; control hits={sorted(rev_words)} "
                    f"(chance-level noise)")

    # planted number run: HELLO
    text = "ROW A 10120 10880 ;\nMARK 72 69 76 76 79 ;\nROW B 10120 13600 ;\n"
    scan = numbers_scan("selftest:numbers", text, words)
    fwd = {w for h in scan["forward_hits"] for w in h["words"]}
    rev = {w for h in scan["control_sequence_reversed_hits"] for w in h["words"]}
    if "hello" not in fwd:
        ok = False
        msgs.append("FAIL: planted 72 69 76 76 79 did not decode to 'hello'")
    else:
        msgs.append("pass: planted integer run decodes to 'hello'")
    if "hello" in rev:
        ok = False
        msgs.append("FAIL: reversed integer control still decodes 'hello'")
    else:
        msgs.append("pass: reversed integer control does not decode the plant")

    # comment extraction on all three syntaxes
    v = "wire \\a//b ;\n// real comment\n/* block\ncomment */\n"
    cs = extract_comments("x.v", v)
    if len(cs) != 2 or not any("real comment" in c for _, c in cs):
        ok = False
        msgs.append(f"FAIL: verilog comment extraction wrong: {cs}")
    else:
        msgs.append("pass: verilog comment extraction; escaped identifier not misread")
    d = extract_comments("x.def", "VERSION 5.8 ; # hash note\n")
    if len(d) != 1 or d[0][1] != "hash note":
        ok = False
        msgs.append(f"FAIL: def comment extraction wrong: {d}")
    else:
        msgs.append("pass: def comment extraction")

    return ok, msgs


# ---------------------------------------------------------------- entry

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    words, dict_src = load_dictionary()

    if args.selftest:
        ok, msgs = selftest(words)
        for m in msgs:
            print(m)
        print("SELFTEST", "PASS" if ok else "FAIL")
        return 0 if ok else 1

    report = run_scan(words, dict_src)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "textscan_report.json"
    out_path.write_text(json.dumps(report, indent=1))

    # ---- human summary
    print(f"dictionary: {report['dictionary']}")
    print("\n== comments ==")
    for label, cs in report["comments"].items():
        print(f"  {label}: {len(cs)}")
        for kind, c in cs:
            print(f"    [{kind}] {c!r}")
    print("\n== names ==")
    nc = report["names"]["counts"]
    print(f"  modules: {report['names']['modules']}")
    print(f"  netlist wires={nc['netlist_wires']} instances={nc['netlist_instances']} "
          f"def components={nc['def_components']} nets={nc['def_nets']}")
    print(f"  def pins: {nc['def_pins']}")
    print(f"  def specialnets: {nc['def_specialnets']}")
    print("  prefixes (count desc):")
    for p, n in report["names"]["prefixes"].items():
        print(f"    {p!r}: {n}")
    print("\n== acrostics (forward vs reversed control) ==")
    for a in report["acrostics"]:
        f = a["forward_hits"]
        r = a["control_reversed_hits"]
        print(f"  {a['sequence']} (n={a['n_items']}): forward={len(f)} control={len(r)}")
        for h in f:
            print(f"    FWD  {h['word']!r} at {h['pos']}")
        for h in r:
            print(f"    CTRL {h['word']!r} at {h['pos']}")
    print("\n== numbers as ASCII ==")
    for s in report["numbers"]:
        print(f"  {s['file']}: ints={s['n_integers']} forward={len(s['forward_hits'])} "
              f"ctrl_lines_rev={len(s['control_lines_reversed_hits'])} "
              f"ctrl_seq_rev={len(s['control_sequence_reversed_hits'])}")
        for h in s["forward_hits"]:
            print(f"    FWD  {h}")
        for h in s["control_lines_reversed_hits"]:
            print(f"    CTRL(lines) {h}")
        for h in s["control_sequence_reversed_hits"]:
            print(f"    CTRL(seq)   {h}")
    print("\n== unclassified tokens ==")
    for label, odd in report["token_audit"].items():
        print(f"  {label}: {len(odd)} distinct")
        for tok, n in odd.items():
            print(f"    {tok!r} x{n}")
    print("\n== byte oddities ==")
    for label, b in report["byte_oddities"].items():
        print(f"  {label}: bytes={b['bytes']} non_ascii/ctl={b['n_non_ascii_or_control']} "
              f"cr={b['cr_bytes']} tab={b['tab_bytes']} "
              f"trailing_ws_lines={b['n_lines_with_trailing_ws']} {b['lines_with_trailing_ws']}")
    print(f"\nfull report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
