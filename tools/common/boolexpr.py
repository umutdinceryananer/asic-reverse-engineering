"""Liberty function expressions, parsed once and evaluated many times.

A cell's `function` is the only statement of what it computes, and from stage 4
onward the pipeline has to do more than carry it around: a cone has to be
composed into one expression, and stage 6 has to write the whole design out to
SMT2. Both need the expression as a tree rather than a string.

The grammar this library uses is small. Measured over all 429 cells, the only
characters appearing outside identifiers are `(`, `)`, `!`, `&`, `|` and space.
There is no `^`: `xnor2` is written out as `(!A&!B) | (A&B)`. Constants `0` and
`1` appear alone, in `conb_1`.

Precedence is the usual one and it matters. `A|B&C` is `A | (B&C)`, and reading
it left to right instead would make `o21a`'s function wrong in a way that still
evaluates and still looks like a circuit.
"""

import re

TOKEN = re.compile(r"\s*(?:(?P<op>[()!&|])|(?P<name>[A-Za-z_][A-Za-z_0-9]*|[01]))")


class Node:
    """A parsed expression. `inputs` is every identifier it reads."""

    __slots__ = ("kind", "value", "children", "inputs")

    def __init__(self, kind, value=None, children=()):
        self.kind = kind                    # const | var | not | and | or
        self.value = value
        self.children = tuple(children)
        if kind == "var":
            self.inputs = frozenset({value})
        else:
            self.inputs = frozenset().union(
                *(c.inputs for c in self.children)) if self.children else frozenset()

    def __repr__(self):
        if self.kind == "const":
            return str(self.value)
        if self.kind == "var":
            return self.value
        if self.kind == "not":
            return f"!{self.children[0]!r}"
        joiner = "&" if self.kind == "and" else "|"
        return "(" + joiner.join(repr(c) for c in self.children) + ")"


def tokenise(text):
    position, out = 0, []
    while position < len(text):
        match = TOKEN.match(text, position)
        if not match:
            if text[position:].strip() == "":
                break
            raise ValueError(f"cannot tokenise {text!r} at {position}: "
                             f"{text[position:position + 12]!r}")
        out.append(match.group("op") or match.group("name"))
        position = match.end()
    return out


def parse(text):
    """One expression to a tree. Raises rather than guessing on anything odd."""
    tokens = tokenise(text)
    position = 0

    def peek():
        return tokens[position] if position < len(tokens) else None

    def take(expected=None):
        nonlocal position
        if position >= len(tokens):
            raise ValueError(f"{text!r} ends early")
        token = tokens[position]
        if expected and token != expected:
            raise ValueError(f"{text!r}: expected {expected!r}, found {token!r}")
        position += 1
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
            return Node("not", children=(primary(),))
        token = take()
        if token in ("0", "1"):
            return Node("const", int(token))
        if token in ("(", ")", "&", "|"):
            raise ValueError(f"{text!r}: unexpected {token!r}")
        return Node("var", token)

    def conjunction():
        parts = [primary()]
        while peek() == "&":
            take("&")
            parts.append(primary())
        return parts[0] if len(parts) == 1 else Node("and", children=parts)

    def disjunction():
        parts = [conjunction()]
        while peek() == "|":
            take("|")
            parts.append(conjunction())
        return parts[0] if len(parts) == 1 else Node("or", children=parts)

    tree = disjunction()
    if position != len(tokens):
        raise ValueError(f"{text!r}: trailing {tokens[position:]!r}")
    return tree


def evaluate(node, values):
    """The expression under an assignment of 0 or 1 to each identifier."""
    kind = node.kind
    if kind == "const":
        return node.value
    if kind == "var":
        try:
            return values[node.value]
        except KeyError:
            raise KeyError(f"no value given for pin {node.value!r}") from None
    if kind == "not":
        return 1 - evaluate(node.children[0], values)
    if kind == "and":
        return int(all(evaluate(c, values) for c in node.children))
    if kind == "or":
        return int(any(evaluate(c, values) for c in node.children))
    raise ValueError(f"unknown node kind {kind!r}")


def table(node, order=None):
    """The full truth table, as {(bit, ...): output}. For small cells only."""
    names = sorted(order or node.inputs)
    rows = {}
    for pattern in range(1 << len(names)):
        bits = tuple((pattern >> index) & 1 for index in range(len(names)))
        rows[bits] = evaluate(node, dict(zip(names, bits)))
    return names, rows


def compile_functions(cell_functions):
    """Every cell's every output, parsed. Raises on the first one that will not.

    Called once at the top of a stage so that a malformed expression stops the
    run there, rather than at whatever moment a cone happens to reach that cell.
    """
    out = {}
    for cell, pins in cell_functions.items():
        for pin, text in pins.items():
            if not text:
                continue
            try:
                out[(cell, pin)] = parse(text)
            except ValueError as error:
                raise ValueError(f"{cell}.{pin}: {error}") from None
    return out
