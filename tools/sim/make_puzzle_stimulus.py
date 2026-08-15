"""Turn example_inputs.vcd into a per clock cycle table for the puzzle gate.

The VCD is the only functional ground truth the puzzle ships: it drives the
design and records what came back. Replaying it against the recovered netlist
is therefore a real check on the extraction, not just a smoke test.

Rather than have Verilog parse a VCD, this flattens it to two tables indexed by
clock cycle:

    out/puzzle/stimulus.txt   rst_n enable I   as sampled by each rising edge
    out/puzzle/expected.txt   O success        as they stand at that same edge

Both tables are indexed by the same cycle number, which took reading the raw
VCD to get right. The file is a zero delay dump, and at a rising edge timestamp
the output change is listed *before* the clock change:

    #1255000
    b1010100 %      <- O becomes 'T'
    1!              <- clk rises

So walking the events in order and snapshotting when the clock edge arrives
already captures the output the edge produced, not the previous one. Taking the
next snapshot instead, which reads as the intuitive choice, shifts the whole
expected stream one cycle early and every byte then appears to arrive late.

Inputs are different: they change on falling edges, so the value standing when
a rising edge arrives is the one that edge samples.

Unknown values are written as x, and the testbench skips comparing those.

Usage:
    python tools/sim/make_puzzle_stimulus.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from read_vcd import parse

VCD = os.path.join("puzzle", "example_inputs.vcd")
OUT = os.path.join("out", "puzzle")


def bit(value):
    return value if value in ("0", "1") else "x"


def vector(value, width):
    if value is None or any(c not in "01" for c in value):
        return "x" * width
    return value.rjust(width, "0")


def main():
    signals, changes = parse(VCD)
    symbol = {info["name"]: sym for sym, info in signals.items()}
    for required in ("clk", "rst_n", "enable", "I", "O", "success"):
        if required not in symbol:
            sys.exit(f"{VCD} has no signal named {required!r}")

    state = {sym: "x" for sym in signals}
    samples = []
    previous_clk = "x"

    for time, sym, value in changes:
        if sym == symbol["clk"] and value == "1" and previous_clk != "1":
            # Values as they stand immediately before this rising edge.
            samples.append({
                "time": time,
                "rst_n": bit(state[symbol["rst_n"]]),
                "enable": bit(state[symbol["enable"]]),
                "I": bit(state[symbol["I"]]),
                "O": vector(state[symbol["O"]], 8),
                "success": bit(state[symbol["success"]]),
            })
        if sym in state:
            state[sym] = value
        if sym == symbol["clk"]:
            previous_clk = value

    # Trailing state, so the last cycle has something to be compared against.
    samples.append({
        "time": None,
        "rst_n": bit(state[symbol["rst_n"]]),
        "enable": bit(state[symbol["enable"]]),
        "I": bit(state[symbol["I"]]),
        "O": vector(state[symbol["O"]], 8),
        "success": bit(state[symbol["success"]]),
    })

    cycles = len(samples) - 1
    print(f"{VCD}: {cycles} rising clock edges")

    periods = {samples[i + 1]["time"] - samples[i]["time"]
               for i in range(cycles - 1)}
    print(f"edge spacing values seen: {sorted(periods)[:5]}"
          f"{' ...' if len(periods) > 5 else ''}")

    os.makedirs(OUT, exist_ok=True)
    stimulus_path = os.path.join(OUT, "stimulus.txt")
    expected_path = os.path.join(OUT, "expected.txt")

    with open(stimulus_path, "w", encoding="utf-8") as handle:
        for sample in samples[:-1]:
            handle.write(f"{sample['rst_n']}{sample['enable']}{sample['I']}\n")

    with open(expected_path, "w", encoding="utf-8") as handle:
        for sample in samples[:-1]:
            handle.write(f"{sample['O']}{sample['success']}\n")

    defined = sum(1 for s in samples[:-1] if "x" not in s["O"])
    print(f"wrote {stimulus_path} and {expected_path}, {cycles} cycles")
    print(f"cycles with a defined O value: {defined}")

    text = []
    previous = None
    for sample in samples[:-1]:
        if "x" in sample["O"]:
            continue
        value = int(sample["O"], 2)
        if value != previous and 32 <= value <= 126:
            text.append(chr(value))
        previous = value
    print(f"expected output, printable characters in order: {''.join(text)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
