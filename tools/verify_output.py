"""Stage 7 against a string that was known before the simulation ran.

`tools/stage7_output.py` reads a byte stream off an output bus. On the puzzle
there is no way to check what it read -- if there were, the puzzle would be
solved -- so the check has to be made somewhere the answer is already written
down. That is what the corpus's `streamer` family is for: two circuits that emit
a declared ASCII string one byte per cycle and then go quiet, synthesised
through the same flow as everything else and mapped two ways each.

**What is compared, and how exactly.** The declared bytes against the bytes the
simulation produced, element by element -- not the rendered text, which would
compare the decoder against itself. The rendering is checked separately and
differently: it has to **round trip**. `unescape` below is a second, small
implementation that turns the rendered text back into bytes, and it shares no
code with `stage7_output.escape`. A decoder that dropped a control byte, or
rendered two different bytes the same way, fails that and would pass a
comparison of text against text.

**Three declared cycle numbers, not just the string.** The corpus generator
declares which cycle the first byte lands on and which cycles the busy flag
covers, both derived from the machine it writes rather than read back out of a
run. A tool that found the right bytes at the wrong cycles would be right by
accident, and on the puzzle that accident is not detectable.

Every mapping of every streamer must pass. Structural invariance is the point of
the corpus's second mapping: a stream that only survives one particular `abc`
run was a property of that run.

Usage:
    python tools/verify_output.py
    python tools/verify_output.py streamer_hello     # one circuit, both mappings
    python tools/verify_output.py --selftest         # and would it notice
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "sim"))
import harness                                                 # noqa: E402
import stage7_output                                           # noqa: E402

OUT_DIR = "out/synth"
FAMILY = "streamer"

# How many cycles past the declared end of the stream to keep clocking. Enough
# to see the bus go quiet and stay quiet, which is the half of "then idles" a
# run stopping at the last byte could not observe.
TAIL = 3

# The active low reset every generator in the corpus writes. Named here rather
# than looked for, and checked against the netlist's actual inputs before use, so
# a circuit that spelled it differently is an error rather than a silent run with
# the reset never asserted.
RESET_PORT = "rst_n"


def unescape(text):
    """The rendered text back to bytes. A second implementation, on purpose.

    Deliberately does not import `stage7_output.NAMED`: the point is to be a
    different piece of code that happens to agree, so the two disagreeing is
    evidence. It refuses anything it does not recognise rather than guessing,
    because a decoder whose output cannot be read back unambiguously is the
    defect this is looking for.
    """
    names = {"0": 0x00, "a": 0x07, "b": 0x08, "t": 0x09, "n": 0x0a,
             "v": 0x0b, "f": 0x0c, "r": 0x0d, "e": 0x1b, "\\": 0x5c}
    out, index = [], 0
    while index < len(text):
        character = text[index]
        if character != "\\":
            if not (0x20 <= ord(character) < 0x7f):
                raise ValueError(f"a raw control byte {ord(character):#04x} in "
                                 f"the rendering: it was not escaped")
            out.append(ord(character))
            index += 1
            continue
        if index + 1 >= len(text):
            raise ValueError("the rendering ends in a lone backslash")
        marker = text[index + 1]
        if marker == "x":
            out.append(int(text[index + 2:index + 4], 16))
            index += 4
        elif marker in names:
            out.append(names[marker])
            index += 2
        else:
            raise ValueError(f"unreadable escape \\{marker} in the rendering")
    return out


def entries():
    """Every streamer netlist in the corpus index, both mappings."""
    path = f"{OUT_DIR}/index.json"
    if not os.path.exists(path):
        sys.exit(f"{path} missing; run tools/stage5_corpus.py")
    with open(path, encoding="utf-8") as handle:
        index = json.load(handle)["circuits"]
    return [e for e in index if e["family"] == FAMILY]


def stimulus(truth, widths):
    """Reset, one trigger pulse, then nothing. The declared drive.

    Cycle 0 holds the reset low, cycle 1 raises the trigger for exactly one
    cycle, and every cycle after that leaves the design alone. The trigger is
    one cycle wide on purpose: the machine returns its index to zero at the end
    of the string, so a trigger still asserted there would start it again and
    "then idles" would never be observed.
    """
    trigger = truth["trigger"]
    reset = RESET_PORT
    cycles = truth["first_byte_cycle"] + truth["length"] + TAIL
    rows = []
    for cycle in range(cycles):
        row = {name: 0 for name in widths}
        row[reset] = 0 if cycle == 0 else 1
        row[trigger] = 1 if cycle == 1 else 0
        rows.append(row)
    return rows


def observe(entry, truth):
    """One circuit through the shared harness. Returns what the bus carried."""
    netlist = f"{entry['dir']}/netlist.v"
    if not os.path.exists(netlist):
        return None, f"{netlist} missing"
    top, module_ports = harness.module_of(netlist)
    ports = harness.port_widths(netlist)
    widths = {name: info["width"] for name, info in ports.items()
              if info["direction"] == "input" and name != "clk"}
    watch = {name: info["width"] for name, info in ports.items()
             if info["direction"] == "output"}
    for name in (truth["output"], truth["busy"]):
        if name not in watch:
            return None, f"{top} has no output {name!r}, it has {sorted(watch)}"
    for name in (truth["trigger"], RESET_PORT):
        if name not in widths:
            return None, (f"{top} has no input {name!r}, it has "
                          f"{sorted(widths)}; the stimulus below would drive "
                          f"nothing")

    rows = stimulus(truth, widths)
    bench = f"{entry['dir']}/tb_output.v"
    with open(bench, "w", encoding="utf-8") as handle:
        handle.write(harness.clocked_bench(top, module_ports, ["clk"], widths,
                                           rows, watch))
    code, output, _, files = harness.icarus(netlist, bench)
    if code != 0 or not files:
        return None, output.strip().splitlines()[-1] if output.strip() else "?"
    got = harness.samples(output)
    if len(got) != len(rows):
        return None, f"{len(got)} samples came back for {len(rows)} cycles"
    return {"values": [harness.value(s[truth["output"]]) for s in got],
            "busy": [harness.value(s[truth["busy"]]) for s in got],
            "cycles": len(rows)}, ""


def compare(truth, seen):
    """The declared string against what the bus carried. Returns the failures."""
    problems = []
    values = seen["values"]
    first = truth["first_byte_cycle"]
    last = first + truth["length"] - 1
    declared = truth["bytes"]

    got = values[first:last + 1]
    if got != declared:
        problems.append(f"bytes at cycles {first}..{last} are {got}, "
                        f"declared {declared}")

    # Where the stream actually is, found the way stage 7 finds it on a target:
    # from the first byte that is not idle to the last. A stream that landed in
    # the right place by arriving early and being padded would pass the check
    # above and fail this one.
    span = stage7_output.trim(values, truth["idle_byte"])
    if span is None:
        problems.append("the bus never left its idle byte")
    elif span != (first, last):
        problems.append(f"the non-idle span is cycles {span[0]}..{span[1]}, "
                        f"declared {first}..{last}")

    expected_busy = [1 if truth["busy_first_cycle"] <= c <= truth["busy_last_cycle"]
                     else 0 for c in range(seen["cycles"])]
    if seen["busy"] != expected_busy:
        where = [c for c, (a, b) in enumerate(zip(seen["busy"], expected_busy))
                 if a != b]
        problems.append(f"{truth['busy']} differs from the declared "
                        f"{truth['busy_first_cycle']}..{truth['busy_last_cycle']} "
                        f"at cycle(s) {where[:8]}")

    # The rendering, checked by round trip rather than against itself.
    text = stage7_output.render(got)
    try:
        back = unescape(text)
    except ValueError as problem:
        problems.append(f"the rendering {text!r} does not read back: {problem}")
        return problems
    if back != got:
        problems.append(f"the rendering {text!r} reads back as {back}, "
                        f"not as the {len(got)} bytes it was made from")
    unprintable = [b for b in declared if not 0x20 <= b < 0x7f]
    for byte in unprintable:
        if stage7_output.escape(byte) not in text:
            problems.append(f"byte {byte:#04x} is not printable and its escape "
                            f"{stage7_output.escape(byte)!r} is not in the "
                            f"rendering")
    return problems


def label(entry):
    return f"{entry['name']}[{entry.get('variant', 'base')}]"


def check(rows, verbose=True):
    """Every observation against its truth. Returns the labels that failed."""
    failed = []
    for entry, truth, seen in rows:
        problems = compare(truth, seen)
        if verbose:
            text = stage7_output.render(truth["bytes"])
            print(f"  {'ok  ' if not problems else 'FAIL'}  "
                  f"{label(entry):<28} {truth['length']:>2} bytes at cycles "
                  f"{truth['first_byte_cycle']}.."
                  f"{truth['first_byte_cycle'] + truth['length'] - 1}   "
                  f"{text!r}")
            for problem in problems:
                print(f"          {problem}")
        if problems:
            failed.append(label(entry))
    return failed


def gather(wanted=None, verbose=True):
    """Simulate every streamer once. Returns (rows, errors)."""
    rows, errors = [], []
    for entry in entries():
        if wanted and entry["name"] != wanted:
            continue
        with open(f"{entry['dir']}/truth.json", encoding="utf-8") as handle:
            truth = json.load(handle)
        seen, why = observe(entry, truth)
        if seen is None:
            errors.append((label(entry), why))
            if verbose:
                print(f"  FAIL  {label(entry):<28} did not simulate: {why}")
            continue
        rows.append((entry, truth, seen))
    return rows, errors


def selftest(rows):
    """Corrupt one byte on each side, in scratch copies, and require both to fail.

    Two directions, because they are two different defects. A wrong byte in the
    *stream* is stage 7 misreading the bus. A wrong byte in the *truth* is the
    answer key being wrong, which is the failure nothing downstream could see --
    `verify_corpus.py --selftest` exists for the same reason.

    Scratch copies rather than files on disk, the same way `verify_corpus.py`
    does it: `copy.deepcopy` of what was loaded, so nothing the corpus owns is
    written to and the corruption cannot survive the process.
    """
    print("the real corpus first, so nothing below is catching a defect that "
          "was already there")
    failed = check(rows, verbose=False)
    if failed:
        print(f"  the streamers do not pass as they stand: {failed}")
        return 1
    print(f"  all {len(rows)} netlist(s) decode exactly\n")

    entry, truth, seen = rows[0]
    missed = []

    stream = copy.deepcopy(seen)
    at = truth["first_byte_cycle"] + truth["length"] // 2
    stream["values"][at] = (stream["values"][at] + 1) & 0xff
    caught = compare(truth, stream)
    print(f"  {'caught' if caught else 'MISSED'}  one byte of the decoded "
          f"stream changed, at cycle {at}, on {label(entry)}")
    if not caught:
        missed.append("a corrupted stream")

    key = copy.deepcopy(truth)
    index = key["length"] // 2
    key["bytes"][index] = (key["bytes"][index] + 1) & 0xff
    key["string"] = "".join(chr(b) for b in key["bytes"])
    caught = compare(key, seen)
    print(f"  {'caught' if caught else 'MISSED'}  one byte of the declared "
          f"string changed, at index {index}, on {label(entry)}")
    if not caught:
        missed.append("a corrupted answer key")

    # The round trip's own known-bad input. A renderer that drops what it cannot
    # print passes a bytes-against-bytes comparison and fails here, which is the
    # whole reason `unescape` is a second implementation.
    try:
        unescape("OK\x07 42")
        print("  MISSED  a raw control byte left in the rendering")
        missed.append("an unescaped control byte")
    except ValueError:
        print("  caught  a raw control byte left in the rendering")

    print(f"\n  {3 - len(missed)}/3 caught")
    if missed:
        print("\nRESULT: fail, this check does not notice: " + ", ".join(missed))
        return 1
    print("\nRESULT: pass, a wrong byte on either side is caught and the real "
          "corpus is not")
    return 0


def main(argv):
    wanted, self_test = None, False
    for item in argv:
        if item == "--selftest":
            self_test = True
        elif wanted is None and not item.startswith("-"):
            wanted = item
        else:
            sys.exit("usage: python tools/verify_output.py [<circuit>] "
                     "[--selftest]")

    known = {e["name"] for e in entries()}
    if not known:
        print(f"no {FAMILY} circuits in {OUT_DIR}/index.json; run "
              f"tools/stage5_corpus.py")
        print("\nRESULT: fail")
        return 1
    if wanted and wanted not in known:
        sys.exit(f"{wanted!r} is not a {FAMILY} circuit; the corpus has "
                 f"{sorted(known)}")

    print(f"stage 7 against strings declared before the simulation ran\n")
    rows, errors = gather(wanted, verbose=not self_test)
    if errors:
        for name, why in errors:
            print(f"  FAIL  {name}: {why}")
        print(f"\nRESULT: fail, {len(errors)} netlist(s) did not simulate")
        return 1
    if not rows:
        print("\nRESULT: fail, nothing to check")
        return 1

    if self_test:
        return selftest(rows)

    failed = check(rows)
    circuits = len({e["name"] for e, _, _ in rows})
    if failed:
        print(f"\nRESULT: fail, {len(failed)} of {len(rows)} netlist(s) do not "
              f"emit the string their answer key declares")
        return 1
    print(f"\nRESULT: pass, {circuits} circuit(s) as {len(rows)} netlist(s), "
          f"every byte exact and every escape read back. Note the limit: this "
          f"says\n  stage 7 reads a stream correctly where a stream was put "
          f"there on purpose, not that the puzzle emits one.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
