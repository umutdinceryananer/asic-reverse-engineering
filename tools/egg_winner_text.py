"""Easter-egg hunt, B2 follow-up: the winner and attempt1-XOR-attempt2 as text.

B2 (tools/egg_vcd_decode.py) decoded the two failed 121-bit VCD attempts as
11-bit LSB-first ASCII and got a sentence, but two streams were left untried:

  winner  the winning 121-bit input, extracted exactly as B1's battery reads
          it: out/puzzle/solution_post_reset.json, trace[*].I where
          trace[*].enable == 1 (only those two fields are read)
  xor     attempt1 XOR attempt2, the two enable-framed 121-bit windows of
          puzzle/example_inputs.vcd under B2's own sampling rule (value
          standing at each rising clk edge), bitwise XORed

Both go through a fixed battery of deterministic decoders:

  11-bit LSB-first words (the framing that decoded the attempts), 11-bit
  MSB-first, and 7-bit / 8-bit ASCII in both bit orders.

A fixed-seed random 121-bit control (seed 20260905, same seed the hunt uses
everywhere) runs through the identical battery; its printable fractions are
the noise floor and are printed beside every result. A decoder whose control
floor is itself >= 0.60 is declared NON-DISCRIMINATING and says so: 95 of the
128 seven-bit codes are printable, so a random stream is printable-majority
under 7-bit framing by construction, and a printable fraction proves nothing
there. A decoded string is printed only when >= 0.60 of its characters are
printable; below that, only the fraction and printable fragments. No raw bit
dumps are printed.

Extraction and decode primitives are imported from egg_vcd_decode, not
re-implemented, so this tool cannot use a different framing than B2 did.

Usage:
    .venv-linux/bin/python tools/egg_winner_text.py            # the report
    .venv-linux/bin/python tools/egg_winner_text.py --selftest # plant + recover

Writes out/eggs/winner_text.json.
"""

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from egg_vcd_decode import (  # noqa: E402  (reused, not modified)
    VCD, SOLUTION, enable_framed, group_decode, hamming, printable_fraction,
    printable_fragments, render_string, sampled_inputs, winning_input)

OUT_JSON = os.path.join(ROOT, "out", "eggs", "winner_text.json")
CONTROL_SEED = 20260905
BITS = 121
PRINTABLE_MAJORITY = 0.60

# (label, word width, bit order). "lsb": first bit of a word weighs 2**0.
DECODERS = [
    ("11-bit LSB", 11, "lsb"),
    ("11-bit MSB", 11, "msb"),
    ("8-bit MSB", 8, "msb"),
    ("8-bit LSB", 8, "lsb"),
    ("7-bit MSB", 7, "msb"),
    ("7-bit LSB", 7, "lsb"),
]


def decode(bits, width, order):
    """One decode: values, leftover bit count, printable fraction."""
    values, leftover = group_decode(bits, width, order)
    return values, len(leftover), printable_fraction(values)


def decode_battery(bits):
    """Every decoder over one stream -> {label: record}."""
    records = {}
    for label, width, order in DECODERS:
        values, leftover, frac = decode(bits, width, order)
        record = {"chars": len(values), "leftover_bits": leftover,
                  "printable_fraction": round(frac, 4)}
        if frac >= PRINTABLE_MAJORITY:
            record["string"] = render_string(values)
        else:
            record["fragments"] = printable_fragments(values)
        records[label] = record
    return records


def verdict(frac, control_frac):
    """The hunt convention: at or below the control floor is NOISE."""
    if frac <= control_frac:
        return "NOISE (at or below control floor)"
    if frac < PRINTABLE_MAJORITY:
        return "SPECULATIVE at best (above floor, below printable majority)"
    if control_frac >= PRINTABLE_MAJORITY:
        return ("SPECULATIVE (weak: the decoder is non-discriminating, its "
                "own control floor is printable-majority)")
    return "SPECULATIVE (printable majority; confirmation needs corroboration)"


def report_stream(name, records, control):
    lines = [f"  [{name}]"]
    for label, _, _ in DECODERS:
        r, c = records[label], control[label]
        line = (f"    {label:<11} printable {r['printable_fraction']:.2f} "
                f"(control floor {c['printable_fraction']:.2f}, "
                f"{r['chars']} chars, {r['leftover_bits']} leftover)")
        if "string" in r:
            line += f"  -> {r['string']!r}"
        elif r["fragments"]:
            line += f"  fragments: {r['fragments']!r}"
        line += f"  [{verdict(r['printable_fraction'], c['printable_fraction'])}]"
        lines.append(line)
    return lines


# ---------------------------------------------------------------- selftest

def encode11_lsb(text):
    """Plant: each char as 11 bits, LSB first -- the inverse of the decoder."""
    bits = []
    for char in text:
        bits.extend((ord(char) >> i) & 1 for i in range(11))
    return bits


def selftest():
    failures = []

    def check(name, ok):
        print(f"  {'pass' if ok else 'FAIL'}  {name}")
        if not ok:
            failures.append(name)

    # 1. Plant a known 11-char word in 11-bit LSB-first and recover it.
    planted = "EASTER EGGS"
    bits = encode11_lsb(planted)
    check("planted vector is 121 bits", len(bits) == BITS)
    values, leftover, frac = decode(bits, 11, "lsb")
    check("11-bit LSB recovers the planted word",
          render_string(values) == planted and leftover == 0)
    check("planted word is 100% printable", frac == 1.0)

    # 2. Control inside the selftest: the wrong bit order must NOT recover it.
    values_msb, _, _ = decode(bits, 11, "msb")
    check("11-bit MSB does not recover the planted word",
          render_string(values_msb) != planted)

    # 3. The battery covers all six decoders and flags the planted string.
    records = decode_battery(bits)
    check("battery runs all six decoders", len(records) == len(DECODERS))
    check("battery prints the planted string only under 11-bit LSB",
          records["11-bit LSB"].get("string") == planted)

    # 4. XOR of a vector with itself is all zero; with its complement, all one.
    a = [0, 1, 1, 0, 1]
    check("xor with self is zero", [x ^ y for x, y in zip(a, a)] == [0] * 5)
    b = [1 - v for v in a]
    check("xor with complement is one", [x ^ y for x, y in zip(a, b)] == [1] * 5)
    check("hamming agrees with xor weight",
          hamming(a, b) == sum(x ^ y for x, y in zip(a, b)))

    # 5. Verdict rule: at or below the floor is NOISE, plainly; and a
    #    decoder whose floor is itself printable-majority says it is weak.
    check("at the floor -> NOISE", verdict(0.27, 0.27).startswith("NOISE"))
    check("below the floor -> NOISE", verdict(0.10, 0.27).startswith("NOISE"))
    check("majority above floor -> not NOISE",
          not verdict(0.91, 0.27).startswith("NOISE"))
    check("majority over a printable-majority floor -> flagged weak",
          "non-discriminating" in verdict(0.94, 0.74))

    # 6. The control seed is deterministic.
    r1 = [random.Random(CONTROL_SEED).randint(0, 1) for _ in range(BITS)]
    r2 = [random.Random(CONTROL_SEED).randint(0, 1) for _ in range(BITS)]
    check("control vector is seed-deterministic", r1 == r2)

    print(f"\nselftest: {'PASS' if not failures else 'FAIL'} "
          f"({len(failures)} failure(s))")
    return 1 if failures else 0


# -------------------------------------------------------------------- main

def main(argv):
    if "--selftest" in argv:
        return selftest()

    # --- streams, by the extractions B1 and B2 already used ---
    winner = winning_input(SOLUTION)
    if len(winner) != BITS:
        sys.exit(f"{SOLUTION}: winning window is {len(winner)} bits, "
                 f"expected {BITS}")

    spans = enable_framed(sampled_inputs(VCD))
    if len(spans) != 2 or any(len(bits) != BITS for _, bits in spans):
        sys.exit(f"{VCD}: expected two {BITS}-bit enable windows, found "
                 f"{[(s, len(b)) for s, b in spans]}")
    attempt1, attempt2 = spans[0][1], spans[1][1]
    xor = [x ^ y for x, y in zip(attempt1, attempt2)]
    distance = hamming(attempt1, attempt2)

    print(f"winner: {os.path.relpath(SOLUTION, ROOT)}, trace I where "
          f"enable==1: {len(winner)} bits, Hamming weight {sum(winner)}")
    print(f"xor:    {os.path.relpath(VCD, ROOT)}, attempt1 XOR attempt2: "
          f"{len(xor)} bits, Hamming distance {distance} "
          f"(weight of the xor stream: {sum(xor)})")

    # --- control first: the floor has to stand before anything is read ---
    rng = random.Random(CONTROL_SEED)
    control_bits = [rng.randint(0, 1) for _ in range(BITS)]
    control = decode_battery(control_bits)
    non_discriminating = [label for label, _, _ in DECODERS
                          if control[label]["printable_fraction"]
                          >= PRINTABLE_MAJORITY]
    if non_discriminating:
        print(f"\nNON-DISCRIMINATING decoders (control floor itself >= "
              f"{PRINTABLE_MAJORITY:.2f}): {non_discriminating}. Random bits "
              f"read as printable-majority under these framings by "
              f"construction (95 of 128 seven-bit codes are printable), so a "
              f"printable fraction proves nothing there; their results can "
              f"only be NOISE or weak.")

    streams = {"winner": (winner, decode_battery(winner)),
               "xor": (xor, decode_battery(xor))}

    lines = []
    for name, (_bits, records) in streams.items():
        lines.extend(report_stream(name, records, control))
    lines.append(f"  [control] fixed-seed random {BITS} bits "
                 f"(seed {CONTROL_SEED}) -- the noise floor")
    for label, _, _ in DECODERS:
        c = control[label]
        line = (f"    {label:<11} printable {c['printable_fraction']:.2f} "
                f"({c['chars']} chars, {c['leftover_bits']} leftover)")
        if "string" in c:
            line += (f"  -> {c['string']!r}  (random bits; this is what "
                     f"noise looks like under this framing)")
        elif c["fragments"]:
            line += f"  fragments: {c['fragments']!r}"
        lines.append(line)
    print("\n" + "\n".join(lines))

    result = {
        "sources": {
            "winner": {"path": os.path.relpath(SOLUTION, ROOT),
                       "extraction": "trace[*].I where trace[*].enable == 1",
                       "bits": len(winner), "hamming_weight": sum(winner)},
            "xor": {"path": os.path.relpath(VCD, ROOT),
                    "extraction": "attempt1 XOR attempt2, enable-framed "
                                  "windows sampled at rising clk edges",
                    "bits": len(xor),
                    "hamming_distance_attempt1_attempt2": distance},
        },
        "control": {"seed": CONTROL_SEED, "bits": BITS, "decodes": control,
                    "non_discriminating_decoders": non_discriminating},
        "printable_majority_threshold": PRINTABLE_MAJORITY,
        "decodes": {name: {
            label: dict(records[label],
                        control_floor=control[label]["printable_fraction"],
                        verdict=verdict(records[label]["printable_fraction"],
                                        control[label]["printable_fraction"]))
            for label, _, _ in DECODERS}
            for name, (_bits, records) in streams.items()},
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1)
    print(f"\nwrote {os.path.relpath(OUT_JSON, ROOT)}")
    print("Declared: exactly the six decoders listed ran, over exactly the "
          "winner, the xor stream and the control; no brute force.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
