"""Stage 4's composed cone, read back by something that shares no code with it.

`tools/stage4_cone.py` walks a cone, substitutes names and emits a listing of
single assignments. Until now nothing checked that the listing computes what the
netlist computes -- it was the one artifact in the repository with no check of
any kind, and it is the artifact a person reads when deciding what the circuit
does. A listing that is wrong is worse than no listing, because it is
persuasive.

**Nothing here is imported from the repository.** Not `common.boolexpr`, which
parses the same syntax; not stage 3's graph; not stage 4's cone walk. The
tokenizer, the parser and the evaluator below are written out again, badly on
purpose in the sense that they are the obvious implementation rather than the
shared one. Two implementations of a grammar agreeing is worth something. One
implementation agreeing with itself is worth nothing.

**What is asserted for the warm up.** `puzzle/warmup/00_source.v` and the
puzzle's published description both say what this design is: two 8 bit operands
shifted in serially, added, and compared against 496. That is the *spec*, not
something this pipeline derived, and it is what makes the warm up a test case:

    1. exactly 15 of the 65536 assignments of the 16 register bits satisfy the
       cone. Fifteen because a + b = 496 with a, b <= 255 needs a >= 241.
    2. the cone is *equivalent* to `a + b == 496` -- not merely agreeing on the
       count -- under one assignment of bit weights.

The weights are not given. They are searched for, and the pairing they are
searched over is read out of the listing itself: an adder couples a_i with b_i,
so every gate whose support is exactly two register bits names one such pair.
Eight pairs, partitioning all sixteen bits, is a property of the listing that
has to hold before any weight is tried.

**And the bit order, cross checked.** Stage 4 orders a register's bits by
following D <- Q through the netlist -- a walk over wires that knows nothing
about arithmetic. This file solves for one weight per operand pair -- a search
over functions that knows nothing about wires. In a shift register those two
have to run together: the bit that entered first has been shifted the furthest
and carries the largest weight, or the smallest, but position determines
significance either way and does so monotonically. That agreement is the second
thing asserted here, and it is the only check in the repository where a
structural derivation and a functional one meet.

**What it cannot do.** The evaluation is exhaustive over 2^support, so it stops
at a support the machine cannot enumerate. The puzzle's success cone depends on
57 bits and this will refuse it and say so; that cone is stage 6's miter to
check, not this one's.

Usage:
    python tools/verify_cone.py warmup
    python tools/verify_cone.py warmup --cone out/warmup/broken_cone.json
    python tools/verify_cone.py warmup --registers out/warmup/scrambled.json
"""

import json
import math
import os
import re
import sys
from itertools import permutations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage1_cells import TARGETS

# Above this the exhaustive sweep stops being a check and starts being a wait.
# 2^22 is a few seconds; the puzzle's success cone is 2^57.
MAX_SUPPORT = 22

# The warm up's published function. Both numbers come from the puzzle's own
# description of its worked example and from `puzzle/warmup/00_source.v`
# (`assign eq = (val == 9'd496)`), so they are the specification this checks
# against and not a result this repository derived.
EXPECTED = {
    "warmup": {"operands": 2, "width": 8, "constant": 496, "satisfying": 15},
}

TOKEN = re.compile(r"\s*([A-Za-z_]\w*(?:\[\d+\])?|[01](?![\w\[])|[!&|()])")


def tokenise(text):
    out, at = [], 0
    while at < len(text):
        found = TOKEN.match(text, at)
        if not found:
            if not text[at:].strip():
                break
            raise SystemExit(f"cannot tokenise {text!r} at {text[at:at + 16]!r}")
        out.append(found.group(1))
        at = found.end()
    return out


def parse(tokens):
    """Recursive descent, `!` over `&` over `|`. Raises on anything else."""
    at = [0]

    def peek():
        return tokens[at[0]] if at[0] < len(tokens) else None

    def take(expected=None):
        if at[0] >= len(tokens):
            raise SystemExit(f"expression ends early: {tokens!r}")
        token = tokens[at[0]]
        if expected and token != expected:
            raise SystemExit(f"expected {expected!r}, found {token!r}")
        at[0] += 1
        return token

    def primary():
        token = peek()
        if token == "(":
            take("(")
            inner = disjunction()
            take(")")
            return inner
        if token == "!":
            take("!")
            return ("not", primary())
        token = take()
        if token in ("0", "1"):
            return ("const", int(token))
        if token in ("&", "|", ")"):
            raise SystemExit(f"unexpected {token!r}")
        return ("var", token)

    def conjunction():
        node = primary()
        while peek() == "&":
            take("&")
            node = ("and", node, primary())
        return node

    def disjunction():
        node = conjunction()
        while peek() == "|":
            take("|")
            node = ("or", node, conjunction())
        return node

    tree = disjunction()
    if at[0] != len(tokens):
        raise SystemExit(f"trailing tokens {tokens[at[0]:]!r}")
    return tree


def evaluate(node, values):
    kind = node[0]
    if kind == "const":
        return node[1]
    if kind == "var":
        return values[node[1]]
    if kind == "not":
        return 1 - evaluate(node[1], values)
    if kind == "and":
        return evaluate(node[1], values) & evaluate(node[2], values)
    return evaluate(node[1], values) | evaluate(node[2], values)


def variables(node, into=None):
    into = set() if into is None else into
    if node[0] == "var":
        into.add(node[1])
    for child in node[1:]:
        if isinstance(child, tuple):
            variables(child, into)
    return into


def read_listing(cone):
    """Each `lhs = rhs` line as (name, tree), in the order they were emitted."""
    rows = []
    for line in cone["listing"]:
        body = line.split("#")[0].strip()
        if not body:
            continue
        if "=" not in body:
            raise SystemExit(f"listing line is not an assignment: {line!r}")
        left, right = body.split("=", 1)
        rows.append((left.strip(), parse(tokenise(right.strip()))))
    return rows


def pairs_from(rows, support):
    """The operand pairing, read off the listing rather than supplied.

    An adder couples bit i of one operand with bit i of the other, and every
    gate that does so has exactly those two register bits in its support. The
    pairs are whatever those gates say they are; that they come out disjoint
    and covering is then a property of the listing, checked rather than assumed.
    """
    seen = []
    for _name, tree in rows:
        bits = variables(tree) & support
        if len(bits) == 2:
            pair = tuple(sorted(bits))
            if pair not in seen:
                seen.append(pair)
    return seen


def satisfying(rows, order):
    """Every assignment of the support that drives the last line high."""
    final = rows[-1][0]
    found = []
    for pattern in range(1 << len(order)):
        values = {bit: (pattern >> index) & 1
                  for index, bit in enumerate(order)}
        for name, tree in rows:
            values[name] = evaluate(tree, values)
        if values[final]:
            found.append(pattern)
    return found, final


def weigh(pairs, order, found, total, constant):
    """**Every** weight assignment making the cone equivalent, not the first.

    Searched, not supplied: every assignment of the powers of two to the pairs
    is tried, and a survivor has to satisfy the *converse* too -- no assignment
    outside the satisfying set may weigh `constant`. Agreeing on 15 rows and
    disagreeing on the other 65521 would not be equivalence.

    This returned the first survivor and stopped, and printed it as though the
    search had determined it. **It has not.** For the warm up 24 of the 40320
    assignments are equivalent, because `a + b == 496` with both operands under
    256 does not distinguish the four most significant pairs from one another
    at all -- 4! of them -- and which of the 24 came out depended on the order
    `permutations` happens to emit. `docs/problems.md` 47.

    The equivalence claim was never wrong. The weights beside it were being
    read as a derivation, and they are one member of a set. Returning the whole
    set is what lets the bit order cross check below mean something: stage 4
    derives an order from wires alone, and asking whether that order is *among*
    the arithmetically valid ones is a real question with 24 chances in 40320
    of passing by luck.
    """
    index_of = {bit: index for index, bit in enumerate(order)}
    counts = []
    for pattern in range(total):
        counts.append(tuple(
            ((pattern >> index_of[a]) & 1) + ((pattern >> index_of[b]) & 1)
            for a, b in pairs))
    inside = set(found)
    powers = [1 << k for k in range(len(pairs))]
    # The satisfying rows first, which is cheap and cuts 40320 to 24 here, then
    # the converse over every assignment on what is left.
    survivors = [w for w in permutations(powers)
                 if all(sum(c * x for c, x in zip(counts[m], w)) == constant
                        for m in found)]
    return [w for w in survivors
            if all((sum(c * x for c, x in zip(counts[m], w)) == constant)
                   == (m in inside) for m in range(total))]


def chain_positions(path):
    """Where each register bit sits in its chain, from a `registers.json`.

    This file reads no code from the repository and this does not change that:
    what is loaded here is stage 4's *output*, a JSON document, and the point of
    the check below is that two derivations of the same fact -- one structural,
    one arithmetic -- agree. Importing the code that produced one of them would
    remove the only thing being tested.

    `R0[i]` is bit *i* of the boundary naming, which is position *i* in that
    register's `flops` list; `bit_order.chains` names the same instances in the
    order the netlist shifts them.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    positions, methods = {}, {}
    for row in data.get("registers", ()):
        order = row.get("bit_order") or {}
        methods[row["register"]] = order.get("method")
        place = {}
        for index, chain in enumerate(order.get("chains") or ()):
            for offset, flop in enumerate(chain):
                place[flop] = (index, offset, len(chain))
        for index, flop in enumerate(row.get("flops", ())):
            if flop in place:
                positions[f"{row['register']}[{index}]"] = place[flop]
    return positions, methods


def cross_check(pairs, solutions, positions, methods):
    """Structural bit order against arithmetic weight. Returns (lines, verdict).

    Two derivations that share nothing. Stage 4 orders a register's bits by
    following D <- Q through the netlist, which is a walk over wires and knows
    nothing about arithmetic. This file solves for the weight assignments that
    make the cone equivalent to `a + b == 496` over all 65536 assignments,
    which is a search over functions and knows nothing about wires. **In a
    shift register the two have to run together**: the bit that entered first
    has been shifted the furthest and carries the largest weight, or the
    smallest, but either way position determines significance monotonically.

    So the check is in two parts, and the first is the sharper one:

    1. the two bits of each operand pair sit in **different chains at the same
       position**. An adder couples bit *i* of one operand with bit *i* of the
       other, and stage 4 found the two chains without knowing that.
    2. the weights that order implies -- 2^position, or 2^(width-1-position) --
       are **among the assignments that actually make the cone equivalent**.

    Part 2 is asked against the whole solution set rather than against one
    member of it, because the set has 24 members here and picking one and
    comparing to it would be comparing to an artefact of iteration order. Which
    direction runs is reported rather than assumed: it depends on which end of
    the shift register the serial input enters, which is a property of the
    design.

    `verdict` is "pass", "fail", or "not applicable" when stage 4 derived no
    order to check.
    """
    lines = []
    missing = sorted({bit for pair in pairs for bit in pair}
                     - set(positions))
    if missing:
        registers = sorted({bit.split("[")[0] for bit in missing})
        for register in registers:
            lines.append(f"    {register}: stage 4 derived no bit order "
                         f"({methods.get(register)!r})")
        lines.append(f"    {len(missing)} of the cone's bits have no position, "
                     f"so there is nothing to")
        lines.append(f"    cross check. A register whose bits do not depend on "
                     f"one another has no")
        lines.append(f"    structural order, and stage 4 says so rather than "
                     f"guessing one.")
        return lines, "not applicable"

    problems, place = [], {}
    width = len(pairs)
    for pair in pairs:
        one, other = positions[pair[0]], positions[pair[1]]
        if one[0] == other[0]:
            problems.append(f"{pair[0]} and {pair[1]} are one operand pair and "
                            f"stage 4 puts both in chain {one[0]}; a pair "
                            f"couples one bit of each operand")
            continue
        if one[1] != other[1]:
            problems.append(f"{pair[0]} and {pair[1]} are one operand pair and "
                            f"stage 4 puts them at positions {one[1]} and "
                            f"{other[1]}; a pair sits at one depth in both "
                            f"chains")
            continue
        lines.append(f"    position {one[1]}   {pair[0]:<8} {pair[1]:<8} "
                     f"chains {one[0]} and {other[0]}")
        place[pair] = one[1]

    if not problems:
        if sorted(place.values()) != list(range(width)):
            problems.append(f"the {width} pairs sit at positions "
                            f"{sorted(place.values())}, which is not "
                            f"0 .. {width - 1} once each")
        else:
            valid = {tuple(w) for w in solutions}
            rising = tuple(1 << place[pair] for pair in pairs)
            falling = tuple(1 << (width - 1 - place[pair]) for pair in pairs)
            lines.append(f"    all {width} pairs lie at one position in each "
                         f"of two chains, 0 .. {width - 1} once each")
            if rising in valid:
                lines.append(f"    and 2^position is one of the "
                             f"{len(valid)} assignments that make the cone")
                lines.append(f"    equivalent: the chain head is the least "
                             f"significant bit, so the")
                lines.append(f"    first bit shifted in ends up as bit 0.")
            elif falling in valid:
                lines.append(f"    and 2^({width - 1} - position) is one of "
                             f"the {len(valid)} assignments that make the cone")
                lines.append(f"    equivalent: the chain head is the most "
                             f"significant bit.")
            else:
                problems.append(f"neither 2^position nor "
                                f"2^({width - 1} - position) is among the "
                                f"{len(valid)} weight assignments that make "
                                f"this cone equivalent; the order stage 4 "
                                f"derived from wires is not one the "
                                f"arithmetic allows")
    for problem in problems:
        lines.append(f"    MISMATCH  {problem}")
    return lines, "fail" if problems else "pass"


def run(target, path=None, registers_path=None):
    path = path or os.path.join("out", target, "cone.json")
    if not os.path.exists(path):
        sys.exit(f"{path} missing; run tools/stage4_cone.py {target}")
    with open(path, encoding="utf-8") as handle:
        cone = json.load(handle)

    rows = read_listing(cone)
    support = set(cone["support"])
    print(f"target {target}")
    print(f"  cone         {path.replace(os.sep, '/')}")
    print(f"  root         {cone['root']}, {cone['cells']} cells, "
          f"{len(rows)} listing lines")
    print(f"  support      {len(support)} register bits")

    declared = {v for _n, tree in rows for v in variables(tree)} \
        - {n for n, _t in rows}
    if declared != support:
        print(f"    listing reads {sorted(declared - support)[:4]} which the "
              f"declared support omits")
        print(f"    support declares {sorted(support - declared)[:4]} which "
              f"the listing never reads")
        print("\nRESULT: fail, the listing and its declared support disagree")
        return 1

    if len(support) > MAX_SUPPORT:
        print(f"\n  {len(support)} bits is 2^{len(support)} assignments and "
              f"this check is exhaustive.")
        print(f"  RESULT: not run. Above {MAX_SUPPORT} bits the sweep is not a "
              f"check, it is a wait.\n  A cone this wide is stage 6's miter to "
              f"settle, not this tool's.")
        return 2

    order = sorted(support)
    total = 1 << len(order)
    found, final = satisfying(rows, order)
    print(f"  root line    {final}")
    print(f"  satisfying   {len(found)} of {total}")

    spec = EXPECTED.get(target)
    if spec is None:
        print(f"\n  No published function for {target!r}, so the count above is "
              f"reported\n  and nothing is asserted. This tool checks a cone "
              f"against a spec, and\n  the puzzle's spec is what the pipeline "
              f"exists to recover.")
        return 0

    problems = []
    if len(found) != spec["satisfying"]:
        problems.append(f"{len(found)} assignments satisfy the cone, the "
                        f"specification implies {spec['satisfying']}")

    pairs = pairs_from(rows, support)
    covered = [bit for pair in pairs for bit in pair]
    print(f"  pairs        {len(pairs)} read off gates with two register bits: "
          f"{[tuple(int(b.split('[')[1][:-1]) for b in p) for p in pairs]}")
    if len(pairs) != spec["width"] or sorted(covered) != order:
        problems.append(f"{len(pairs)} operand pairs covering {len(set(covered))}"
                        f" bits; {spec['width']} disjoint pairs over "
                        f"{len(order)} bits were implied")
        print("\n".join(f"  {p}" for p in problems))
        print("\nRESULT: fail")
        return 1

    solutions = weigh(pairs, order, found, total, spec["constant"])
    if not solutions:
        problems.append(f"no assignment of bit weights makes this cone "
                        f"equivalent to a sum of {spec['operands']} operands "
                        f"equal to {spec['constant']}")
    else:
        print(f"  equivalent   to (a + b == {spec['constant']}) over all "
              f"{total} assignments, under")
        print(f"               {len(solutions)} of the "
              f"{math.factorial(len(pairs))} possible weight assignments. "
              f"One of them, and it is")
        print(f"               one and not the one -- `a + b == "
              f"{spec['constant']}` with both operands under 256")
        print(f"               does not tell the four most significant pairs "
              f"apart at all:")
        for pair, weight in sorted(zip(pairs, solutions[0]),
                                   key=lambda x: x[1]):
            print(f"                 {pair[0]} and {pair[1]} at weight {weight}")

    verdict = "not run"
    if solutions:
        registers = registers_path or os.path.join("out", target,
                                                   "registers.json")
        if not os.path.exists(registers):
            print(f"\n  {registers} missing; run tools/stage4_registers.py "
                  f"{target}")
            print(f"  RESULT: fail, the bit order cross check has nothing to "
                  f"read")
            return 1
        positions, methods = chain_positions(registers)
        print(f"\n  bit order, from {registers.replace(os.sep, '/')}, against "
              f"the weights above")
        lines, verdict = cross_check(pairs, solutions, positions, methods)
        print("\n".join(lines))
        if verdict == "fail":
            problems.append("stage 4's bit order and the arithmetic weights "
                            "disagree")

    if problems:
        for problem in problems:
            print(f"\n  {problem}")
        print("\nRESULT: fail, the listing does not compute the design's "
              "published function")
        return 1
    print(f"\nRESULT: pass, the listing computes a + b == {spec['constant']} "
          f"and nothing else,")
    print(f"  and stage 4's bit order agrees with the weights: {verdict}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    override = registers = None
    rest = []
    index = 0
    while index < len(args):
        if args[index] == "--cone":
            override, index = args[index + 1], index + 2
        elif args[index] == "--registers":
            registers, index = args[index + 1], index + 2
        else:
            rest.append(args[index])
            index += 1
    if len(rest) != 1 or rest[0] not in TARGETS:
        sys.exit(f"usage: python tools/verify_cone.py "
                 f"[{' | '.join(TARGETS)}] [--cone <path>] "
                 f"[--registers <path>]")
    sys.exit(run(rest[0], override, registers))
