"""Read a VCD waveform into a signal timeline, and decode byte outputs as text.

`puzzle/example_inputs.vcd` is the closest thing to a golden test vector the
puzzle ships. It drives the design and records what came back out, so a
recovered netlist can be checked against it directly: same inputs in, same
outputs out.

Usage:
    python tools/read_vcd.py puzzle/example_inputs.vcd
    python tools/read_vcd.py puzzle/example_inputs.vcd --ascii O
"""

import re
import sys

VAR = re.compile(r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(.+?)\s*\$end")


def parse(path):
    """Return (signals, changes) where changes is a list of (time, symbol, value)."""
    text = open(path, encoding="utf-8", errors="replace").read()

    signals = {}
    for width, symbol, name in VAR.findall(text):
        signals[symbol] = {"name": name.split()[0], "width": int(width)}

    body = text[text.index("$enddefinitions"):]
    changes = []
    time = 0
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith("#"):
            time = int(line[1:])
        elif line[0] in "bB":
            value, _, symbol = line[1:].partition(" ")
            if symbol:
                changes.append((time, symbol.strip(), value))
        elif line[0] in "01xXzZ" and len(line) > 1:
            changes.append((time, line[1:].strip(), line[0]))
    return signals, changes


def timeline(signals, changes):
    """Per timestamp snapshot of every signal, only at times something changed."""
    state = {symbol: "x" for symbol in signals}
    rows = []
    current = None
    for time, symbol, value in changes:
        if current is not None and time != current:
            rows.append((current, dict(state)))
        current = time
        if symbol in state:
            state[symbol] = value
    if current is not None:
        rows.append((current, dict(state)))
    return rows


def as_int(value):
    try:
        return int(value, 2)
    except ValueError:
        return None


def report(path, ascii_signal=None):
    signals, changes = parse(path)

    print(f"file    {path}")
    print(f"signals {len(signals)}")
    for symbol, info in signals.items():
        print(f"  {info['name']:<10} width {info['width']:<3} symbol {symbol!r}")

    rows = timeline(signals, changes)
    print(f"\n{len(rows)} timestamps with activity, "
          f"t = {rows[0][0]} .. {rows[-1][0]}\n")

    order = sorted(signals, key=lambda s: signals[s]["name"])
    header = "time".rjust(10) + "  " + "  ".join(
        signals[s]["name"].rjust(max(6, signals[s]["width"])) for s in order)
    print(header)
    print("-" * len(header))
    for time, state in rows[:40]:
        cells = []
        for symbol in order:
            value = state[symbol]
            width = max(6, signals[symbol]["width"])
            number = as_int(value)
            cells.append((f"{number}" if number is not None else value).rjust(width))
        print(f"{time:>10}  " + "  ".join(cells))
    if len(rows) > 40:
        print(f"... {len(rows) - 40} more timestamps")

    if ascii_signal:
        symbol = next((s for s in signals if signals[s]["name"] == ascii_signal), None)
        if symbol is None:
            sys.exit(f"no signal named {ascii_signal!r}")
        print(f"\n{ascii_signal} decoded as ASCII, in order of change:")
        text = []
        previous = None
        for time, _, value in ((t, s, v) for t, s, v in changes if s == symbol):
            number = as_int(value)
            if number is None or number == previous:
                continue
            previous = number
            char = chr(number) if 32 <= number <= 126 else f"\\x{number:02x}"
            text.append(char)
            print(f"  t={time:<12} 0x{number:02x}  {char!r}")
        print(f"\n  joined: {''.join(text)!r}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    signal = args[args.index("--ascii") + 1] if "--ascii" in args else None
    report(args[0], signal)
