"""Liberty's function expressions against the PDK's own behavioural models.

From stage 4 onward the pipeline stops carrying cell functions around and starts
*computing* with them: a cone is composed into one expression, and stage 6 writes
the design out to SMT2. Everything after this point inherits whatever the
expression parser believes.

Liberty is one statement of what a cell does. The behavioural Verilog model in
the same PDK is another, written by different people for a different tool. This
puts every cell through both and compares the truth tables.

Precedence is the thing most worth checking. `(A1&B1) | (A2&B1)` parsed left to
right rather than with `&` binding tighter still evaluates, still produces a
plausible circuit, and is wrong for every cell whose function mixes the two --
which is most of the interesting ones.

Usage:
    python tools/verify_functions.py            # every cell both targets use
    python tools/verify_functions.py --all      # every combinational cell
    python tools/verify_functions.py --selftest # and would it notice if wrong
"""

import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import boolexpr, liberty
from common.lef import functional_pins, load as load_lef
from stage1_cells import PDK_DIR, TARGETS

IMAGE = "gds-teardown-sim:latest"
MAX_INPUTS = 8          # 2**8 vectors per cell; nothing in this library is wider


def cells_in_use():
    """Every cell type either target instantiates, from the graphs themselves."""
    used = set()
    for target in TARGETS:
        path = os.path.join("out", target, "graph.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            graph = json.load(handle)
        used.update(cell["type"] for cell in graph["cells"].values())
    return sorted(used)


def combinational(cell, lib, lef):
    """Cells this can check: combinational, with a parseable function per output.

    Sequential cells are excluded because a truth table is not what they have.
    Their liberty statement is checked differently, by stage 3's cross check.
    """
    entry = lib.get(cell)
    if not entry or entry["sequential"]:
        return None
    pins = functional_pins(lef.get(cell, {"pins": {}}))
    inputs = sorted(p for p, d in pins.items() if d == "input")
    outputs = sorted(p for p, d in pins.items() if d == "output")
    if not inputs or not outputs or len(inputs) > MAX_INPUTS:
        return None
    trees = {}
    for pin in outputs:
        text = entry["pins"].get(pin, {}).get("function")
        if not text:
            return None
        trees[pin] = boolexpr.parse(text)
    return inputs, outputs, trees


def testbench(entries, path):
    """One module per cell, sweeping every input pattern and printing outputs."""
    lines = ["`timescale 1ns/1ps", "module tb;", "  integer pattern;", "  reg clk;"]
    for index, (cell, inputs, outputs, _) in enumerate(entries):
        lines.append(f"  reg  [{max(len(inputs) - 1, 0)}:0] i{index};")
        for pin in outputs:
            lines.append(f"  wire o{index}_{pin};")
        wiring = ", ".join(
            [f".{pin}(i{index}[{position}])" for position, pin in enumerate(inputs)]
            + [f".{pin}(o{index}_{pin})" for pin in outputs])
        lines.append(f"  {cell} u{index} ({wiring});")
    lines.append("  initial begin")
    for index, (cell, inputs, outputs, _) in enumerate(entries):
        lines.append(f"    for (pattern = 0; pattern < {1 << len(inputs)}; "
                     f"pattern = pattern + 1) begin")
        lines.append(f"      i{index} = pattern[{max(len(inputs) - 1, 0)}:0];")
        lines.append("      #2;")
        for pin in outputs:
            lines.append(f'      $display("{index} {pin} %0d %0b", pattern, '
                         f"o{index}_{pin});")
        lines.append("    end")
    lines.append("    $finish;")
    lines.append("  end")
    lines.append("endmodule")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def simulate(entries, work):
    """Icarus over the PDK models, with the flags the models actually need."""
    files, includes, missing = [], set(), []
    for cell, *_ in entries:
        found = glob.glob(os.path.join(PDK_DIR, "cells", "*", f"{cell}.v"))
        if not found:
            missing.append(cell)
            continue
        path = found[0].replace("\\", "/")
        files.append(path)
        includes.add(os.path.dirname(path))
    if missing:
        sys.exit(f"no behavioural model in the PDK cache for {missing}")

    bench = f"{work}/functions_tb.v".replace("\\", "/")
    testbench(entries, bench)
    # FUNCTIONAL and UNIT_DELAY are not optional: without them the behavioural
    # views compile and every output stays x, which stage 2 paid for once.
    command = ("iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY=#1 -o /tmp/fn.vvp "
               + " ".join(f"-I {d}" for d in sorted(includes)) + " "
               + " ".join(files) + f" {bench} && vvp /tmp/fn.vvp")
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{os.path.abspath('.')}:/work",
         "-w", "/work", IMAGE, "bash", "-c", command],
        capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        sys.exit("icarus failed")

    observed = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        index, pin, pattern, value = int(parts[0]), parts[1], int(parts[2]), parts[3]
        observed[(index, pin, pattern)] = value
    return observed


def _rewrite(text, precedence=True, swap=False, greedy_not=False):
    """The same grammar, deliberately got wrong in one of three ways.

    Each is a mistake a parser written without care actually makes, and each
    still parses every expression in the library and still yields a plausible
    circuit. They exist so the question "would the comparison below notice?" has
    an answer rather than an assumption.
    """
    tokens = boolexpr.tokenise(text)
    position = 0
    AND, OR = ("or", "and") if swap else ("and", "or")

    def primary():
        nonlocal position
        token = tokens[position]
        if token == "(":
            position += 1
            inner = disjunction()
            position += 1                       # ")"
            return inner
        if token == "!":
            position += 1
            # greedy_not: `!A&B` read as `!(A&B)` instead of `(!A)&B`
            return boolexpr.Node("not", children=(
                disjunction() if greedy_not else primary(),))
        position += 1
        if token in ("0", "1"):
            return boolexpr.Node("const", int(token))
        return boolexpr.Node("var", token)

    def conjunction():
        nonlocal position
        parts = [primary()]
        while position < len(tokens) and tokens[position] == "&":
            position += 1
            parts.append(primary())
        return parts[0] if len(parts) == 1 else boolexpr.Node(AND, children=parts)

    def disjunction():
        nonlocal position
        if not precedence:
            # one precedence level, left associative: `A|B&C` becomes `(A|B)&C`
            left = primary()
            while position < len(tokens) and tokens[position] in ("&", "|"):
                kind = AND if tokens[position] == "&" else OR
                position += 1
                left = boolexpr.Node(kind, children=(left, primary()))
            return left
        parts = [conjunction()]
        while position < len(tokens) and tokens[position] == "|":
            position += 1
            parts.append(conjunction())
        return parts[0] if len(parts) == 1 else boolexpr.Node(OR, children=parts)

    return disjunction()


WRONG_PARSERS = {
    "one precedence level": dict(precedence=False),
    "and and or exchanged": dict(swap=True),
    "negation binds greedily": dict(greedy_not=True),
}

HAND_WRITTEN = [
    ("A&B", ("A", "B"), [0, 0, 0, 1]),
    ("A|B", ("A", "B"), [0, 1, 1, 1]),
    ("!A", ("A",), [1, 0]),
    ("(!A)", ("A",), [1, 0]),
    ("(!A&!B) | (A&B)", ("A", "B"), [1, 0, 0, 1]),
    # Pattern p assigns bit i of p to names[i]. Written the other way round the
    # first time, which made three of these eight wrong and the parser look
    # broken -- and these tables are the *only* thing covering precedence, since
    # no function in the library exercises it. Each row below was checked by
    # hand: `!A&B` is true only at A=0 B=1, which is p=2.
    ("A|B&C", ("A", "B", "C"), [0, 1, 0, 1, 0, 1, 1, 1]),
    ("!A&B", ("A", "B"), [0, 0, 1, 0]),
    ("(A1&B1) | (A2&B1)", ("A1", "A2", "B1"), [0, 0, 0, 0, 0, 1, 1, 1]),
]


def selftest():
    """Is the parser right, and which mistakes would the model check notice?"""
    print("the parser against hand written truth tables")
    wrong = 0
    rows = 0
    for text, names, expected in HAND_WRITTEN:
        tree = boolexpr.parse(text)
        for pattern, want in enumerate(expected):
            values = {n: (pattern >> i) & 1 for i, n in enumerate(names)}
            rows += 1
            got = boolexpr.evaluate(tree, values)
            if got != want:
                print(f"  WRONG {text!r} {values} -> {got}, expected {want}")
                wrong += 1
    print(f"  {rows} rows over {len(HAND_WRITTEN)} expressions, {wrong} wrong")

    print("\nwhich parser mistakes this library's own functions would expose")
    lib = liberty.load(PDK_DIR)
    functions = []
    for cell, entry in sorted(lib.items()):
        for pin, info in sorted(entry["pins"].items()):
            text = info.get("function")
            if text and len(boolexpr.parse(text).inputs) <= MAX_INPUTS:
                functions.append((cell, pin, text))

    caught = {}
    for label, options in WRONG_PARSERS.items():
        differs = []
        for cell, pin, text in functions:
            right = boolexpr.parse(text)
            try:
                bad = _rewrite(text, **options)
            except (ValueError, IndexError):
                continue
            names = sorted(right.inputs)
            for pattern in range(1 << len(names)):
                values = {n: (pattern >> i) & 1 for i, n in enumerate(names)}
                if boolexpr.evaluate(right, values) != boolexpr.evaluate(bad, values):
                    differs.append(f"{cell}.{pin}")
                    break
        caught[label] = differs
        state = f"{len(differs)}/{len(functions)} functions expose it"
        print(f"  {label:<26} {state}")
        if differs:
            print(f"  {'':<26} e.g. {differs[:3]}")

    blind = [label for label, differs in caught.items() if not differs]
    if blind:
        print(f"\n  NOT exposed by any function in this library: {blind}")
        print("  This library parenthesises every conjunction --")
        print("  `(A1&B1) | (A2&B1)` -- so precedence never decides anything in")
        print("  it. The comparison against the behavioural models is real")
        print("  evidence about identifiers, negation and grouping, and is no")
        print("  evidence at all about precedence. The hand written cases above")
        print("  are what covers that, and they are the only thing that does.")

    if wrong:
        print("\nRESULT: fail, the parser is wrong")
        return 1
    if len(blind) == len(WRONG_PARSERS):
        print("\nRESULT: fail, no mistake would be exposed by anything")
        return 1
    print(f"\nRESULT: pass. {len(WRONG_PARSERS) - len(blind)} of "
          f"{len(WRONG_PARSERS)} mistakes are caught by the model comparison, "
          f"the rest by the tables above.")
    return 0


def run(everything=False):
    lef = load_lef(PDK_DIR)
    lib = liberty.load(PDK_DIR)
    candidates = sorted(lib) if everything else cells_in_use()
    if not candidates:
        sys.exit("no graphs found; run tools/stage3_graph.py first")

    entries, skipped = [], []
    for cell in candidates:
        shape = combinational(cell, lib, lef)
        if shape is None:
            skipped.append(cell)
            continue
        inputs, outputs, trees = shape
        entries.append((cell, inputs, outputs, trees))

    print(f"{len(candidates)} cell types considered, {len(entries)} combinational "
          f"with a parseable function, {len(skipped)} skipped")
    vectors = sum(1 << len(inputs) for _, inputs, _, _ in entries)
    print(f"{vectors} input patterns to compare")

    work = os.path.join("out", "synth")
    os.makedirs(work, exist_ok=True)
    observed = simulate(entries, work)

    mismatches, checked, silent = [], 0, []
    for index, (cell, inputs, outputs, trees) in enumerate(entries):
        for pattern in range(1 << len(inputs)):
            values = {pin: (pattern >> position) & 1
                      for position, pin in enumerate(inputs)}
            for pin in outputs:
                key = (index, pin, pattern)
                if key not in observed:
                    silent.append((cell, pin))
                    continue
                seen = observed[key]
                mine = boolexpr.evaluate(trees[pin], values)
                checked += 1
                if seen not in ("0", "1"):
                    mismatches.append((cell, pin, values, mine, seen))
                elif int(seen) != mine:
                    mismatches.append((cell, pin, values, mine, int(seen)))

    print(f"\n{checked} (cell, output, pattern) comparisons")
    if silent:
        unique = sorted(set(silent))
        print(f"  {len(unique)} outputs the simulation never reported: {unique[:6]}")
    if mismatches:
        print(f"\n{len(mismatches)} DISAGREEMENTS between liberty and the model")
        for cell, pin, values, mine, seen in mismatches[:12]:
            print(f"  {cell}.{pin} {values}: liberty says {mine}, model says {seen}")
        print("\nRESULT: fail")
        return 1
    if silent:
        print("\nRESULT: fail, some outputs were never observed")
        return 1
    print("  every one agrees")
    print("\nRESULT: pass")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--selftest"]:
        sys.exit(selftest())
    if args not in ([], ["--all"]):
        sys.exit("usage: python tools/verify_functions.py [--all | --selftest]")
    sys.exit(run(everything=bool(args)))
