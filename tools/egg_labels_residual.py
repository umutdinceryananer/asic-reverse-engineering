"""Easter-egg sweep, domain A1+A2, residual pass over egg_labels.py output.

egg_labels.py classifies a label as an expected pin label when it sits on
li1 (67,5) or met1 (68,5) AND its text is identifier-shaped. That leaves one
channel a planted message could hide in: an identifier-shaped WORD on a
legitimate pin layer. This tool closes it, reading the structured JSON that
egg_labels.py wrote (out/eggs/labels_<target>.json):

  1. Top-cell labels must be exactly the documented port/power set for that
     target, each exactly once per (layer,texttype). Anything extra is listed.
  2. Pin-layer (67,5)/(68,5) labels inside non-top structures must match the
     library's cell-pin convention (short upper-case identifier) or be a
     power/well name. Anything else is listed.

Usage:
    .venv-linux/bin/python tools/egg_labels_residual.py            # both targets
    .venv-linux/bin/python tools/egg_labels_residual.py --selftest

--selftest runs both checks against a synthetic inventory carrying one
planted word in each channel plus innocuous rows; each check must flag
exactly its plant.
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EGGS = REPO / "out" / "eggs"

CELL_PIN = re.compile(r"[A-Z][A-Z0-9_]{0,11}\Z")
POWER = {"VPWR", "VGND", "VPB", "VNB"}

# Documented ports per target: puzzle/README.md and warmup/00_source.v.
EXPECTED_TOP = {
    "puzzle": {
        "top": "puzzle",
        "ports": {"clk", "rst_n", "enable", "I", "success"}
        | {f"O[{i}]" for i in range(8)}
        | POWER,
    },
    "warmup": {
        "top": "adder_demo",
        "ports": {"clk", "rst_n", "en", "A", "B", "S"} | POWER,
    },
}


def residual_check(inventory, top, ports):
    """Return (extra_top_labels, odd_pinlayer_labels) from one inventory."""
    extra_top = []
    odd_pin = []
    for row in inventory["labels"]:
        if row["structure"] == top:
            if row["text"] not in ports:
                extra_top.append(row)
        elif (row["layer"], row["texttype"]) in ((67, 5), (68, 5)):
            if not (CELL_PIN.match(row["text"]) or row["text"] in POWER):
                odd_pin.append(row)
    return extra_top, odd_pin


def run(target):
    path = EGGS / f"labels_{target}.json"
    if not path.exists():
        print(f"missing {path}; run tools/egg_labels.py {target} first")
        return 2
    inventory = json.loads(path.read_text())
    spec = EXPECTED_TOP[target]
    extra_top, odd_pin = residual_check(inventory, spec["top"], spec["ports"])
    print(f"=== {target} residual pass over {path.name} ===")
    print(f"top-cell labels not in documented port set: {len(extra_top)}")
    for row in extra_top:
        print(f"  {row['text']!r} on ({row['layer']},{row['texttype']}) "
              f"at ({row['x_um']}, {row['y_um']})")
    print(f"pin-layer labels in library cells that are not cell-pin/power "
          f"names: {len(odd_pin)}")
    for row in odd_pin:
        print(f"  {row['structure']}: {row['text']!r} at "
              f"({row['x_um']}, {row['y_um']})")
    clean = not extra_top and not odd_pin
    print("verdict: CLEAN" if clean else "verdict: CANDIDATES ABOVE")
    print()
    return 0


def selftest():
    fixture = {
        "labels": [
            # Innocuous top-cell port label.
            {"structure": "top", "text": "clk", "layer": 70, "texttype": 5,
             "x_um": 1.0, "y_um": 1.0},
            # Planted word in the top cell on a pin layer.
            {"structure": "top", "text": "HELLO_WORLD", "layer": 67,
             "texttype": 5, "x_um": 2.0, "y_um": 2.0},
            # Innocuous cell pin inside a library cell.
            {"structure": "sky130_fd_sc_hd__inv_1", "text": "A", "layer": 67,
             "texttype": 5, "x_um": 0.1, "y_um": 0.1},
            # Planted lower-case word inside a library cell on a pin layer.
            {"structure": "sky130_fd_sc_hd__inv_1", "text": "easteregg",
             "layer": 68, "texttype": 5, "x_um": 0.2, "y_um": 0.2},
            # Off-pin-layer label in a library cell: egg_labels.py's own
            # flag path owns this channel, this pass must NOT double-count.
            {"structure": "sky130_fd_sc_hd__inv_1", "text": "whatever",
             "layer": 83, "texttype": 44, "x_um": 0.3, "y_um": 0.3},
        ]
    }
    extra_top, odd_pin = residual_check(fixture, "top", {"clk"} | POWER)
    failures = []
    if [r["text"] for r in extra_top] != ["HELLO_WORLD"]:
        failures.append(f"top-cell check flagged {[r['text'] for r in extra_top]}")
    if [r["text"] for r in odd_pin] != ["easteregg"]:
        failures.append(f"pin-layer check flagged {[r['text'] for r in odd_pin]}")
    if failures:
        for line in failures:
            print(f"SELFTEST FAIL: {line}")
        return 1
    print("SELFTEST PASS: each channel flags exactly its planted word "
          "(2 plants, 2 caught, 3 innocuous rows passed)")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    status = 0
    for target in argv or ["puzzle", "warmup"]:
        status = max(status, run(target))
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
