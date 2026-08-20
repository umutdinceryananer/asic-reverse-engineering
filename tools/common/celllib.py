"""The PDK's cells as behaviour, generated from liberty.

Stage 3 writes a *blackbox* library: module interfaces with no bodies, which is
all a connectivity walk needs. From stage 4 onward that is not enough. A miter
cannot be built out of blackboxes -- two netlists of opaque boxes are equivalent
if and only if they are wired identically, which is a question about names, not
about behaviour -- and stage 6 cannot unroll a transition relation it cannot
evaluate.

So this emits the same cells with bodies, and the bodies come from the one
authority the repository trusts for what a cell computes:

    pin (Y)  { function : "(!A) | (!B)"; }
    ff (IQ, IQ_N) { clocked_on : CLK; next_state : D; clear : !RESET_B; }

Those expressions are parsed by `common.boolexpr`, the parser
`tools/verify_functions.py` checks against the PDK's own behavioural Verilog
over 850 truth tables. So this library is not a second, unverified reading of
the cells: it is the reading that already has a gate under it, re-emitted in a
form Yosys can read.

**It is deliberately not the PDK's own `.v` models.** Those exist and stage 2's
simulation uses them, which is the point: the equivalence check and the
simulation that cross-checks its result must not both rest on the same file. The
PDK models are UDP-based and carry timing and `x` propagation that a solver
cannot use; this is two-valued and structural.

Physical-only cells -- decap, tap, fill -- have no outputs and, for
`tapvpwrvgnd_1`, no liberty entry at all. They are emitted as empty modules and
reported, because a netlist instantiating one is not thereby broken and a
missing module would stop Yosys dead.

Usage as a library:
    from common.celllib import write
    written, empty = write(library, "out/warmup/celllib.v", cells)
"""

import sys

from common import boolexpr, liberty


def verilog(node):
    """A parsed liberty expression as a Verilog expression.

    Fully parenthesised on the way out. The parser has already settled
    precedence -- and `docs/problems.md` 8 is what happens when an expression is
    re-emitted with the grouping left to whoever reads it next.
    """
    if node.kind == "const":
        return f"1'b{node.value}"
    if node.kind == "var":
        return node.value
    if node.kind == "not":
        return f"(~{verilog(node.children[0])})"
    joiner = " & " if node.kind == "and" else " | "
    return "(" + joiner.join(verilog(c) for c in node.children) + ")"


def expression(text):
    return verilog(boolexpr.parse(text))


def edge_of(condition, what, cell):
    """An asynchronous control expression as a Verilog edge and a level.

    `clear : "!RESET_B"` clears while RESET_B is low, so the event that starts
    it is `negedge RESET_B`. Liberty writes these bare rather than
    parenthesised, and reading the level off the first character is right here
    and wrong for every combinational function in the library -- which is
    problem 31. `liberty.pin_of` is the function that knows the difference.
    """
    pin, level = liberty.pin_of(condition)
    if pin is None:
        sys.exit(f"{cell}: cannot read a pin out of {what} {condition!r}")
    return ("negedge" if level == "low" else "posedge"), pin, level


def flop_body(cell, entry):
    """A liberty `ff` group as a Verilog always block.

    Only `ff` is handled. A latch would need a level sensitive body and this
    library's two targets contain none; guessing at one silently is worse than
    stopping, so it stops.
    """
    state = entry["sequential"]
    if state["kind"] != "ff":
        sys.exit(f"{cell}: sequential kind {state['kind']!r} is not handled; "
                 f"only `ff` is, and nothing in either target uses another")
    inner, outer = (state["state"] + ["IQ", "IQ_N"])[:2]

    clock_edge, clock_pin, _ = edge_of(state["clocked_on"], "clocked_on", cell)
    events = [f"{clock_edge} {clock_pin}"]
    branches = []
    # Preset before clear, matching liberty's own precedence for the cells that
    # carry both: `dfbbp_1` holds SET_B dominant.
    for field, value in (("preset", "1'b1"), ("clear", "1'b0")):
        if not state.get(field):
            continue
        edge, pin, level = edge_of(state[field], field, cell)
        events.append(f"{edge} {pin}")
        test = f"~{pin}" if level == "low" else pin
        branches.append(f"if ({test}) {inner} <= {value};")

    lines = [f"  reg {inner};",
             f"  always @({' or '.join(events)})"]
    for index, branch in enumerate(branches):
        lines.append(f"    {'' if index == 0 else 'else '}{branch}")
    lines.append(f"    {'else ' if branches else ''}{inner} <= "
                 f"{expression(state['next_state'])};")
    lines.append(f"  wire {outer} = ~{inner};")
    return lines


def module_for(cell, entry):
    """One cell as a Verilog module, or None if it has no behaviour to state."""
    if entry is None:
        return [f"module {cell} ();", "endmodule"], True
    pins = entry["pins"]
    outputs = {p: i for p, i in pins.items() if i["direction"] == "output"}
    sequential = entry["sequential"]
    if not outputs and not sequential:
        names = ", ".join(sorted(pins))
        head = [f"module {cell} ({names});" if names else f"module {cell} ();"]
        head += [f"  {pins[p]['direction']} {p};" for p in sorted(pins)]
        return head + ["endmodule"], True

    lines = [f"module {cell} ({', '.join(sorted(pins))});"]
    for pin in sorted(pins):
        lines.append(f"  {pins[pin]['direction']} {pin};")
    if sequential:
        lines += flop_body(cell, entry)
    for pin in sorted(outputs):
        function = outputs[pin]["function"]
        if not function:
            sys.exit(f"{cell}.{pin} is an output with no liberty function; "
                     f"this library cannot state what it computes")
        lines.append(f"  assign {pin} = {expression(function)};")
    lines.append("endmodule")
    return lines, False


def write(library, path, cells):
    """Emit a module for each named cell. Returns (with behaviour, empty).

    `cells` is the exact set a netlist instantiates rather than the whole
    library, so a cell that is missing from liberty is reported against a
    netlist that actually uses it.
    """
    lines = ["// Generated by tools/common/celllib.py from the PDK's liberty.",
             "// Behaviour, not interfaces: this is what a miter and a solver",
             "// need and what stage 3's blackbox library deliberately omits.",
             "// The expressions come from `function` and the `ff` groups, read",
             "// by the parser tools/verify_functions.py gates.",
             ""]
    behaviour, empty = 0, []
    for cell in sorted(cells):
        body, is_empty = module_for(cell, library.get(cell))
        lines += body + [""]
        if is_empty:
            empty.append(cell)
        else:
            behaviour += 1
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return behaviour, empty
