"""Easter-egg hunt, domain B2: decode the VCD input attempts as text/graphics.

Extracts the two enable-framed 121-bit I sequences from
puzzle/example_inputs.vcd (per rising clk edge, same sampling rule as
tools/sim/make_puzzle_stimulus.py: inputs change on falling edges, so the
value standing at a rising edge is what that edge samples), then runs a
fixed battery of deterministic decoders over each attempt, over the two
attempts concatenated, and over a fixed-seed random control vector:

  (a) 8-bit ASCII, MSB-first and LSB-first, leftover bits reported
  (b) 7-bit ASCII, both orders, leftover bits reported
  (c) 11x11 grid render (121 = 11*11), row-major and column-major, both
      polarities, written under out/eggs/, with ink count and 4-connected
      component count (the concatenated 242 bits render as 11x22 / 22x11)
  (d) run-length report; a Morse reading is attempted only if the 1-run
      lengths form exactly two clusters in a dot/dash-like ratio (>= 2x),
      otherwise "no Morse structure" is stated
  (e) integer stats: bit count, Hamming weight, and Hamming distance to the
      winning 121-bit input read from out/puzzle/solution_post_reset.json
      (only the trace's I/enable fields are read)
  (f) 11-bit words (121 = 11 chars x 11 bits), LSB-first and MSB-first per
      word -- added after the 11x11 grid render showed bit positions 7..10
      of every word empty, i.e. each word is a value below 128

Every byte decoding reports a printability metric (fraction of bytes in
[0x20, 0x7e]); the decoded string is printed only if >= 60% printable,
otherwise only the metric and the printable fragments.

The control is a random 121-bit vector from seed 20260905; its metrics are
the noise floor and are printed side by side.

No brute force over 2^121 is attempted; exactly the decodings above run.

Usage:
    python tools/egg_vcd_decode.py            # the full report
    python tools/egg_vcd_decode.py --selftest # "HI" through the 8-bit decoder
"""

import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from read_vcd import parse  # noqa: E402  (reused, not modified)

VCD = os.path.join(ROOT, "puzzle", "example_inputs.vcd")
SOLUTION = os.path.join(ROOT, "out", "puzzle", "solution_post_reset.json")
EGGS = os.path.join(ROOT, "out", "eggs")
CONTROL_SEED = 20260905


# ---------------------------------------------------------------- extraction

def header_records(path):
    """The $date/$version/$comment records, verbatim (small text)."""
    text = open(path, encoding="utf-8", errors="replace").read()
    records = []
    for keyword in ("date", "version", "timescale", "comment"):
        for match in re.finditer(r"\$" + keyword + r"\s+(.*?)\s*\$end",
                                 text[:text.index("#0")], re.S):
            records.append((keyword, " ".join(match.group(1).split())))
    return records


def declaration_records(path):
    """Every $scope/$var record verbatim, and the var types seen.

    The $comment record says 'Show the parameter values.'; VCD can declare
    $var parameter entries whose constant values are dumped once, so this
    checks deterministically whether any exist in this file.
    """
    text = open(path, encoding="utf-8", errors="replace").read()
    head = text[:text.index("$enddefinitions")]
    records = re.findall(r"\$(?:scope|var|upscope)\b.*?\$end", head, re.S)
    var_types = re.findall(r"\$var\s+(\w+)", head)
    return records, sorted(set(var_types))


def sampled_inputs(path):
    """(rst_n, enable, I) as sampled by each rising clk edge."""
    signals, changes = parse(path)
    symbol = {info["name"]: sym for sym, info in signals.items()}
    for required in ("clk", "rst_n", "enable", "I"):
        if required not in symbol:
            sys.exit(f"{path} has no signal named {required!r}")
    state = {sym: "x" for sym in signals}
    samples = []
    previous_clk = "x"
    for _time, sym, value in changes:
        if sym == symbol["clk"] and value == "1" and previous_clk != "1":
            samples.append((state[symbol["rst_n"]],
                            state[symbol["enable"]],
                            state[symbol["I"]]))
        if sym in state:
            state[sym] = value
        if sym == symbol["clk"]:
            previous_clk = value
    return samples


def enable_framed(samples):
    """Contiguous runs of enable == '1': [(start_cycle, [bits])]."""
    spans, current, start = [], None, None
    for i, (_r, en, ival) in enumerate(samples):
        if en == "1":
            if current is None:
                current, start = [], i
            current.append(1 if ival == "1" else 0)
        elif current is not None:
            spans.append((start, current))
            current = None
    if current is not None:
        spans.append((start, current))
    return spans


def winning_input(path):
    """The enable-framed I bits of the stage 6 trace. Only trace[*].I/enable."""
    trace = json.load(open(path))["trace"]
    return [int(step["I"]) for step in trace if step["enable"] == 1]


# ----------------------------------------------------------------- decoders

def printable_fraction(byte_values):
    if not byte_values:
        return 0.0
    return sum(1 for b in byte_values if 0x20 <= b <= 0x7E) / len(byte_values)


def group_decode(bits, width, order):
    """bits -> byte values of `width` bits, `order` in {msb, lsb}; leftover."""
    usable = len(bits) - (len(bits) % width)
    values = []
    for i in range(0, usable, width):
        chunk = bits[i:i + width]
        if order == "lsb":
            chunk = chunk[::-1]
        value = 0
        for bit in chunk:
            value = (value << 1) | bit
        values.append(value)
    leftover = bits[usable:]
    return values, leftover


def render_string(byte_values):
    return "".join(chr(b) if 0x20 <= b <= 0x7E else f"\\x{b:02x}"
                   for b in byte_values)


def printable_fragments(byte_values, minimum=2, keep=5):
    fragments, run = [], []
    for b in byte_values:
        if 0x20 <= b <= 0x7E:
            run.append(chr(b))
        else:
            if len(run) >= minimum:
                fragments.append("".join(run))
            run = []
    if len(run) >= minimum:
        fragments.append("".join(run))
    return fragments[:keep]


def report_bytes(label, bits, width, order, out):
    values, leftover = group_decode(bits, width, order)
    frac = printable_fraction(values)
    line = (f"    {label:<12} {len(values)} chars, "
            f"{len(leftover)} leftover bit(s) {''.join(map(str, leftover))!r}, "
            f"printable {frac:.2f}")
    if frac >= 0.60:
        line += f"  -> {render_string(values)!r}"
    else:
        frags = printable_fragments(values)
        line += f"  fragments: {frags!r}"
    out.append(line)
    return frac


def words11(bits, order):
    """11-bit words -> values. order 'lsb': bit i of a word weighs 2**i."""
    values = []
    for i in range(0, len(bits) - (len(bits) % 11), 11):
        chunk = bits[i:i + 11]
        if order == "lsb":
            chunk = chunk[::-1]
        value = 0
        for bit in chunk:
            value = (value << 1) | bit
        values.append(value)
    return values


def report_words11(label, bits, order, out):
    values = words11(bits, order)
    frac = printable_fraction(values)
    line = (f"    {label:<12} {len(values)} words, printable {frac:.2f}")
    if frac >= 0.60:
        line += f"  -> {render_string(values)!r}"
    else:
        line += f"  values: {values}"
    out.append(line)
    return frac


def grid(bits, rows, cols, major, polarity):
    """121/242 bits -> list of text rows. polarity 0: 1=ink; 1: 0=ink."""
    assert len(bits) == rows * cols
    cells = [[0] * cols for _ in range(rows)]
    for index, bit in enumerate(bits):
        if major == "row":
            r, c = divmod(index, cols)
        else:
            c, r = divmod(index, rows)
        cells[r][c] = bit ^ polarity
    return ["".join("#" if cell else "." for cell in row) for row in cells]


def components(rows_text):
    """4-connected components of '#' cells."""
    ink = {(r, c) for r, line in enumerate(rows_text)
           for c, ch in enumerate(line) if ch == "#"}
    seen, count = set(), 0
    for cell in sorted(ink):
        if cell in seen:
            continue
        count += 1
        stack = [cell]
        while stack:
            r, c = stack.pop()
            if (r, c) in seen or (r, c) not in ink:
                continue
            seen.add((r, c))
            stack.extend([(r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)])
    return len(ink), count


def report_grids(name, bits, rows, cols, out):
    os.makedirs(EGGS, exist_ok=True)
    for major in ("row", "col"):
        for polarity in (0, 1):
            text = grid(bits, rows, cols, major, polarity)
            ink, comps = components(text)
            path = os.path.join(
                EGGS, f"vcd_{name}_grid_{rows}x{cols}_{major}_p{polarity}.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(text) + "\n")
            out.append(f"    grid {rows}x{cols} {major}-major polarity={polarity}: "
                       f"ink {ink}, components {comps}  ({os.path.relpath(path, ROOT)})")


def runs_of(bits):
    runs = []
    for bit in bits:
        if runs and runs[-1][0] == bit:
            runs[-1][1] += 1
        else:
            runs.append([bit, 1])
    return [(bit, length) for bit, length in runs]


def report_morse(bits, out):
    runs = runs_of(bits)
    one_runs = sorted({length for bit, length in runs if bit == 1})
    zero_runs = sorted({length for bit, length in runs if bit == 0})
    out.append(f"    runs: {len(runs)} total; 1-run lengths {one_runs}; "
               f"0-run lengths {zero_runs}")
    if len(one_runs) == 2 and one_runs[1] >= 2 * one_runs[0]:
        dot, dash = one_runs
        symbols = "".join("." if length == dot else "-"
                          for bit, length in runs if bit == 1)
        out.append(f"    Morse-like structure: dot={dot} dash={dash}, "
                   f"symbol stream {symbols!r} (word/letter gaps not decoded)")
    else:
        out.append("    no Morse structure (1-run lengths do not form two "
                   "clusters in a dot/dash-like ratio)")


def hamming(a, b):
    assert len(a) == len(b)
    return sum(x != y for x, y in zip(a, b))


def analyse(name, bits, winner, out):
    out.append(f"  [{name}] {len(bits)} bits, Hamming weight {sum(bits)}")
    fracs = {}
    for width in (8, 7):
        for order in ("msb", "lsb"):
            label = f"{width}-bit {order.upper()}"
            fracs[label] = report_bytes(label, bits, width, order, out)
    if len(bits) % 11 == 0:
        for order in ("lsb", "msb"):
            label = f"11-bit {order.upper()}"
            fracs[label] = report_words11(label, bits, order, out)
    if len(bits) == 121:
        report_grids(name, bits, 11, 11, out)
    elif len(bits) == 242:
        report_grids(name, bits, 11, 22, out)
        report_grids(name + "_tall", bits, 22, 11, out)
    report_morse(bits, out)
    if winner is not None and len(bits) == len(winner):
        out.append(f"    Hamming distance to winning input: {hamming(bits, winner)}")
    return fracs


# ---------------------------------------------------------------- selftest

def selftest():
    bits = [0, 1, 0, 0, 1, 0, 0, 0,   # 'H' = 0x48 MSB-first
            0, 1, 0, 0, 1, 0, 0, 1]   # 'I' = 0x49
    values, leftover = group_decode(bits, 8, "msb")
    text = render_string(values)
    assert text == "HI", f"selftest: expected 'HI', got {text!r}"
    assert leftover == [], f"selftest: unexpected leftover {leftover!r}"
    values_lsb, _ = group_decode(bits, 8, "lsb")
    assert render_string(values_lsb) == "\\x12\\x92", "selftest: LSB mismatch"
    g = grid([1, 0, 0, 1], 2, 2, "row", 0)
    assert g == ["#.", ".#"] and components(g) == (2, 2), "selftest: grid"
    morse_out = []
    report_morse([1, 0, 1, 1, 1, 0, 1], morse_out)  # dot gap dash gap dot
    assert any("Morse-like" in line for line in morse_out), "selftest: morse"
    flat_out = []
    report_morse([1, 0, 1, 0, 1], flat_out)
    assert any("no Morse structure" in line for line in flat_out), "selftest"
    hi11 = []
    for char in "HI":  # 11-bit words, LSB-first: bit i weighs 2**i
        hi11.extend((ord(char) >> i) & 1 for i in range(11))
    assert render_string(words11(hi11, "lsb")) == "HI", "selftest: words11"
    print("selftest: 'HI' decoded via 8-bit MSB; LSB, grid, components and "
          "both Morse branches checked. PASS")
    return 0


# -------------------------------------------------------------------- main

def main(argv):
    if "--selftest" in argv:
        return selftest()

    print(f"VCD: {os.path.relpath(VCD, ROOT)}")
    print("header records, verbatim (whitespace collapsed):")
    for keyword, value in header_records(VCD):
        print(f"  ${keyword}: {value}")

    var_records, var_types = declaration_records(VCD)
    print(f"declaration section: {len(var_records)} records, "
          f"$var types seen: {var_types}")
    if "parameter" in var_types:
        print("  parameter-typed vars EXIST — their dumped values follow")
    else:
        print("  no parameter-typed $var in this VCD: the $comment's "
              "'parameter values' are not in this file")

    samples = sampled_inputs(VCD)
    spans = enable_framed(samples)
    print(f"\n{len(samples)} rising clk edges; enable-framed spans: "
          f"{[(start, len(bits)) for start, bits in spans]}")

    winner = winning_input(SOLUTION)
    print(f"winning input ({os.path.relpath(SOLUTION, ROOT)}, trace I where "
          f"enable==1): {len(winner)} bits, Hamming weight {sum(winner)}")
    if len(winner) % 11 == 0:
        winner_out = []
        for order in ("lsb", "msb"):
            report_words11(f"11-bit {order.upper()}", winner, order, winner_out)
        print("winning input through the 11-bit word decoder:")
        print("\n".join(winner_out))

    out = []
    attempt_bits = []
    for number, (start, bits) in enumerate(spans, 1):
        attempt_bits.append(bits)
        analyse(f"attempt{number}", bits, winner, out)
    if len(attempt_bits) == 2 and len(attempt_bits[0]) == len(attempt_bits[1]):
        out.append(f"  Hamming distance attempt1 vs attempt2: "
                   f"{hamming(attempt_bits[0], attempt_bits[1])}")
    concatenated = [b for bits in attempt_bits for b in bits]
    analyse("concat", concatenated, None, out)

    rng = random.Random(CONTROL_SEED)
    control = [rng.randint(0, 1) for _ in range(121)]
    out.append("  --- control: fixed-seed random 121 bits "
               f"(seed {CONTROL_SEED}) — the noise floor ---")
    analyse("control", control, winner, out)

    print("\n".join(out))
    print("\nDeclared: no brute force over 2^121 was attempted; exactly the "
          "decodings listed above were run.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
