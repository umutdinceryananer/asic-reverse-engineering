"""Stage 6. The netlist run backwards: which inputs drive the output high.

Stages 1 to 5 answer "what is this". This asks "what do I type into it", and the
design is sequential, so it is not a single SAT question. It is bounded model
checking: unroll the transition relation to depth K, assert the output high at
cycle K, and ask a solver for the inputs.

**The transition relation is built from `graph.json`, not exported from Yosys.**
Everything needed is already there and already checked. `cell_functions` carries
each cell's liberty function -- which is why `docs/solver-pipeline.md` insists
cells stop being blackboxes at stage 3 -- and `common/boolexpr` parses it with
the parser `verify_functions.py` gates against the PDK's own behavioural models.
`flipflops` carries clock, data, reset and set per flop, and
`stage3_crosscheck.py` derives all of it a second time. Going through
`yosys-smtbmc` instead would mean re-solving the sky130 cell resolution problem
in a second place and taking the answer on trust; this way the export rests on
what already has gates under it.

**The cycle model.**

    S(t)      the flops as they stand during cycle t, asynchronous reset and
              set already applied
    r(t)      reset active, computed from the net at each flop's reset pin
    comb(t)   every combinational net, from the inputs at t and S(t)
    S(t+1)    reset or set value if r(t) or r(t+1), otherwise D(t)

`r(t) or r(t+1)` is what makes the reset asynchronous rather than clocked: a
level held across the edge clears the flop whichever side of the edge it
arrives. That is only well defined when a flop's reset net does not itself
depend on a flop, and this tool checks that and refuses rather than quietly
solving a design it has mis-modelled. It refuses a second shape for the same
reason: a flop carrying **both** an asynchronous set and an asynchronous clear
is one this model describes two different ways -- unsatisfiable at cycle 0,
set-dominates from cycle 1 -- and no design here has one. The clock is not a signal here at all --
clock tree cells are dropped and the clock port is implicit in the cycle.

**The initial state is free, and that matters more than it looks.** `rst_n` is
an input the solver controls like any other; nothing here asserts a reset
preamble. But a free initial state lets the solver answer with a trace that only
works from one particular power-up state, and a chip does not power up in a
state anyone chose. So after finding a trace this asks the solver the opposite
question -- is there an initial state under which these same inputs do *not*
drive the output high -- and if there is, pins that state as a second copy of
the design and solves again. The loop ends when no such state exists, and the
trace is then good from every power-up state, which is what makes it usable and
what makes `tools/sim/replay.py` able to replay it from `x`.

That loop is also why no reset gets baked in: if a reset is needed the solver
finds it, and if it is not -- the warm up's registers are fully overwritten
after eight shifts -- it does not waste a cycle on one.

**`--post-reset` asks the smaller question, and the announcement says it is the
right one.** The published hint is "Don't forget to toggle `rst_n` before each
input attempt", quoted verbatim in `docs/references.md` section 6. Somebody who
has just toggled `rst_n` is not starting from an arbitrary state: every flop
with an asynchronous clear is at 0 and every flop with an asynchronous preset is
at 1, and only the flops with neither are unknown. Under `--post-reset` those
are pinned and the rest stay free, so the solver quantifies over 2^(free flops)
starting states instead of 2^(all of them).

The default stays universal, because a trace good from every state is good from
the post-reset ones too and the reverse does not hold. But on the puzzle the
difference is 92 free bits against 4 -- 88 of its 92 flops carry `rst_n`, 84 as
a clear and 4 as a preset -- and solving for robustness across all 2^92 is
solving a harder problem than the author poses. Both modes print the set they
quantified over, so the two runs can be compared rather than assumed equal.

Nothing here is believed until `tools/sim/replay.py` reproduces it against
stage 2's netlist. A trace that does not reproduce is a modelling defect in this
file, not a solution.

Usage:
    python tools/stage6_invert.py warmup
    python tools/stage6_invert.py warmup --post-reset     # start states as
                                                          # rst_n leaves them;
                                                          # writes
                                                          # solution_post_reset
    python tools/stage6_invert.py warmup --depth 6        # a bound below the
                                                          # answer: exits 1
    python tools/stage6_invert.py warmup --property S
    python tools/stage6_invert.py --graph out/synth/x/graph.json --depth 4
    python tools/stage6_invert.py --selftest            # the two driver
                                                        # checks, on
                                                        # synthetic graphs;
                                                        # no container
"""

import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import boolexpr
from stage1_cells import TARGETS

IMAGE = "gds-teardown-eda:latest"
DEFAULT_DEPTH = 16
# How many counterexample initial states to pin before giving up at a depth and
# trying a deeper one. Each round is one extra copy of the unrolled design.
MAX_ROUNDS = 8

VALUE = re.compile(r"\(\s*([A-Za-z_][\w]*)\s+(true|false)\s*\)")


class Design:
    """A `graph.json` as a transition relation.

    Everything this reads was written by stage 3 and re-derived by
    `stage3_crosscheck.py`. Nothing is inferred from a cell's name.
    """

    def __init__(self, graph):
        self.graph = graph
        ports = graph["ports"]
        functions = boolexpr.compile_functions(graph["cell_functions"])

        # Every net a cell drives, before deciding which of them are signals.
        produced = {}
        for instance, cell in sorted(graph["cells"].items()):
            if instance in graph["flipflops"]:
                continue
            for pin in sorted(graph["cell_functions"].get(cell["type"], {})):
                wires = cell["connections"].get(pin)
                if wires:
                    # A plain assignment here let a second cell on the same net
                    # overwrite the first, silently, so the double-driver check
                    # further down could only ever see a cell against a
                    # constant, an input or a flop -- never a cell against
                    # another cell. This library has no tristate, so one driver
                    # per net is structural and a collision is a defect.
                    if wires[0] in produced:
                        prev = produced[wires[0]]
                        sys.exit(f"net {wires[0]} is driven by two cells: "
                                 f"{prev[0]}.{prev[1]} and {instance}.{pin}")
                    produced[wires[0]] = (instance, pin,
                                          functions[(cell["type"], pin)])

        # The clock tree, walked back from the flops rather than read off
        # `graph["clock_nets"]`. That field names the nets *at the flop pins*:
        # the warm up's tree is clk -> n8 -> {n18, n41}, and it lists n18 and
        # n41 only. Modelling n8 as a signal makes the clock port a free
        # variable the solver has to choose, in a model where a cycle already
        # is an edge.
        clock_nets = set(graph["clock_roots"])
        stack = [record["clock"] for record in graph["flipflops"].values()
                 if record.get("clock")]
        stack += list(graph["clock_nets"])
        while stack:
            net = stack.pop()
            if net in clock_nets:
                continue
            clock_nets.add(net)
            source = produced.get(net)
            if source:
                instance, _pin, tree = source
                stack += [w[0] for w in
                          (cell["connections"].get(name)
                           for name in tree.inputs
                           for cell in [graph["cells"][instance]]) if w]

        # Which ports carry a clock. The clock is not modelled as a signal --
        # a cycle *is* an edge -- so these are neither free inputs nor part of
        # the reported trace.
        self.clock_ports = sorted(
            name for name, info in ports.items()
            if info["direction"] == "input"
            and any(bit in clock_nets for bit in info["bits"]))
        self.inputs = [(name, ports[name]["bits"]) for name in sorted(ports)
                       if ports[name]["direction"] == "input"
                       and name not in self.clock_ports]
        self.outputs = {name: info["bits"] for name, info in ports.items()
                        if info["direction"] == "output"}

        # Where every net comes from. A net with no entry here is undriven, and
        # asking the solver about one is how a mis-modelled design looks.
        self.driver = {}
        for name, info in ports.items():
            if info["direction"] == "input":
                for index, bit in enumerate(info["bits"]):
                    self.driver[bit] = ("input", name, index)
        for net, value in (graph.get("constant_nets") or {}).items():
            self.driver[net] = ("const", int(value))
        self.flops = dict(sorted(graph["flipflops"].items()))
        for instance, record in self.flops.items():
            self.driver[record["q"]] = ("flop", instance)

        self.clock_nets = clock_nets
        self.cells = []
        constants = (graph.get("constant_nets") or {})
        skipped = 0
        for net, (instance, pin, tree) in sorted(produced.items()):
            if net in clock_nets:
                continue                        # a clock tree cell: not a signal
            # A tie cell drives a constant, and stage 3 has already written that
            # output into `constant_nets`, where a cone stops. The same fact
            # arrives here a second time as a cell that produces a net, so the
            # generic check below would read one driver as two. Skip it -- but
            # only after the cell's own function agrees with what was recorded.
            # A disagreement is a mis-identified cell, which is the thing this
            # path must not hide. `int` on both sides because stage 3 writes an
            # int from a liberty function and a string for a `const:` literal.
            recorded = constants.get(net)
            if recorded is not None:
                if tree.kind == "const" and int(tree.value) == int(recorded):
                    skipped += 1
                    continue
                sys.exit(f"net {net}: recorded constant {recorded} but driven "
                         f"by {instance}.{pin}, whose function is not that "
                         f"constant")
            if net in self.driver:
                sys.exit(f"net {net} is driven by more than one thing: "
                         f"{self.driver[net]} and {instance}.{pin}")
            self.driver[net] = ("cell", instance, pin)
            self.cells.append((net, instance, pin, tree))
        self.constants_skipped = skipped
        self.pins = {i: c["connections"] for i, c in graph["cells"].items()}
        self.tree_of = {(i, p): t for _n, i, p, t in self.cells}
        self.width = {port: len(bits) for port, bits in self.inputs}
        self.undriven = sorted(self.missing())

        # An asynchronous reset held across a clock edge clears the flop from
        # either side of it, so the model needs the reset at t and at t+1. That
        # is only a definition and not a loop while the reset cone reaches no
        # flop, and a synchronous reset folded into D would break it.
        self.state_controlled = sorted(self.controls_touching_state())

        # A flop carrying an asynchronous set AND an asynchronous clear is one
        # this model describes two different ways, so it is refused rather than
        # solved. At cycle 0 the two are independent implications -- `clear =>
        # q is false` and `preset => q is true` -- so both asserted at once is
        # UNSATISFIABLE, and the solver would report "no trace" for a design
        # that has one. From cycle 1 on, `preset` is applied after `clear` in
        # the nested `ite`, so set dominates and both asserted is perfectly
        # satisfiable. Two answers to one question.
        #
        # Nothing here has such a flop -- the warm up has none, no corpus
        # netlist has one, and the puzzle's cells are `dfrtp` (clear), `dfstp`
        # (preset) and `dfxtp` (neither), each carrying one. That is why the
        # disagreement was reachable only in principle. It is checked rather
        # than assumed because `--post-reset` pins a value for exactly these
        # flops and `post_reset_state` resolves the tie the *cycle 1* way,
        # which would contradict cycle 0 for a design that had one.
        self.both_controls = sorted(
            instance for instance, record in self.flops.items()
            if record.get("reset") and record.get("set"))

    def post_reset_state(self):
        """Every flop an asynchronous control pins, and to what.

        A partial assignment: flops with neither a reset nor a set are absent
        and stay free. A flop carrying *both* would need the two ordered, and
        this model orders them one way at cycle 0 and the other from cycle 1
        on, so `Design` refuses such a design outright and the ordering below
        never decides anything. See `both_controls`.

        The *level* of the control is not consulted and must not be. This is
        the state after the reset has been asserted and released, not a
        statement about which polarity asserts it -- a `dfrtp` leaves 0 whether
        its clear is active high or active low.
        """
        pinned = {}
        for instance, record in self.flops.items():
            if record.get("set"):
                pinned[instance] = True
            elif record.get("reset"):
                pinned[instance] = False
        return pinned

    def support(self, net, seen=None):
        """Every net reachable backwards from this one, through cells."""
        seen = set() if seen is None else seen
        if net in seen:
            return seen
        seen.add(net)
        entry = self.driver.get(net)
        if entry and entry[0] == "cell":
            _, instance, pin = entry
            for name in self.tree_of[(instance, pin)].inputs:
                wires = self.pins[instance].get(name)
                if wires:
                    self.support(wires[0], seen)
        return seen

    def missing(self):
        """Nets something reads and nothing drives, or reads and should not.

        A clock net read by anything other than a flop's clock pin is the
        second kind. The cycle model has no value for it -- a cycle is an edge,
        not a waveform -- so a design that gates or samples its own clock is one
        this file cannot describe, and it says so instead of solving something
        else.
        """
        gaps = set()
        for _net, instance, _pin, tree in self.cells:
            for name in tree.inputs:
                wires = self.pins[instance].get(name)
                if not wires:
                    gaps.add(f"{instance}.{name} unconnected")
                elif wires[0] in self.clock_nets:
                    gaps.add(f"{instance}.{name} reads the clock net "
                             f"{wires[0]}")
                elif wires[0] not in self.driver:
                    gaps.add(wires[0])
        for instance, record in self.flops.items():
            for field in ("data", "reset", "set"):
                net = record.get(field)
                if net and net not in self.driver:
                    gaps.add(net)
        return gaps

    def controls_touching_state(self):
        """Flops whose reset or set is computed from another flop's output."""
        bad = set()
        for instance, record in self.flops.items():
            for field in ("reset", "set"):
                net = record.get(field)
                if not net:
                    continue
                if any(self.driver.get(n, ("",))[0] == "flop"
                       for n in self.support(net)):
                    bad.add(f"{instance}.{field}")
        return bad


# --------------------------------------------------------------------------
# SMT2


def input_var(cycle, port, index, width):
    return f"i_{cycle}_{port}" + (f"_{index}" if width > 1 else "")


def encode(design, depth, copies, property_port, pinned=None, want=True,
           predicted_names=None):
    """The unrolled design as SMT2.

    `copies` is one entry per initial state to satisfy simultaneously: `None`
    for a free one, or a {flop: bit} map for a pinned one. They share the input
    variables, which is exactly the question being asked -- one input sequence,
    good for all of these starting states.

    `pinned` fixes the inputs instead, and `want=False` asks for the output to
    be *low*; together those are the query that looks for a starting state the
    trace fails from.
    """
    lines = ["(set-logic QF_UF)"]
    assertions = []
    predicted_names = {} if predicted_names is None else predicted_names

    for cycle in range(depth + 1):
        for port, bits in design.inputs:
            for index in range(len(bits)):
                name = input_var(cycle, port, index, len(bits))
                lines.append(f"(declare-const {name} Bool)")
                if pinned is not None:
                    value = (pinned[cycle][port] >> index) & 1
                    assertions.append(f"(assert (= {name} "
                                      f"{'true' if value else 'false'}))")

    def term(net, copy, cycle):
        entry = design.driver.get(net)
        if entry is None:
            sys.exit(f"net {net} is read and nothing drives it")
        if entry[0] == "input":
            _, port, index = entry
            return input_var(cycle, port, index, design.width[port])
        if entry[0] == "const":
            return "true" if entry[1] else "false"
        if entry[0] == "flop":
            return f"q{copy}_{cycle}_{entry[1]}"
        return f"n{copy}_{cycle}_{net}"

    def smt(tree, instance, copy, cycle):
        if tree.kind == "const":
            return "true" if tree.value else "false"
        if tree.kind == "var":
            wires = design.pins[instance].get(tree.value)
            if not wires:
                sys.exit(f"{instance}.{tree.value} is read by the cell's "
                         f"function and is not connected")
            return term(wires[0], copy, cycle)
        if tree.kind == "not":
            return f"(not {smt(tree.children[0], instance, copy, cycle)})"
        operator = "and" if tree.kind == "and" else "or"
        parts = " ".join(smt(c, instance, copy, cycle) for c in tree.children)
        return f"({operator} {parts})"

    def active(record, field, copy, cycle):
        """Is this flop's reset (or set) asserted during that cycle?"""
        net = record.get(field)
        if not net:
            return None
        value = term(net, copy, cycle)
        return value if record[f"{field}_level"] == "high" else f"(not {value})"

    for copy, initial in enumerate(copies):
        for cycle in range(depth + 1):
            for instance in design.flops:
                lines.append(f"(declare-const q{copy}_{cycle}_{instance} Bool)")
            for net, _i, _p, _t in design.cells:
                lines.append(f"(declare-const n{copy}_{cycle}_{net} Bool)")

        for cycle in range(depth + 1):
            for net, instance, _pin, tree in design.cells:
                assertions.append(
                    f"(assert (= n{copy}_{cycle}_{net} "
                    f"{smt(tree, instance, copy, cycle)}))")

        for instance, record in design.flops.items():
            for cycle in range(depth + 1):
                now = f"q{copy}_{cycle}_{instance}"
                clear = active(record, "reset", copy, cycle)
                preset = active(record, "set", copy, cycle)
                if cycle == 0:
                    # A partial assignment: `--post-reset` pins the flops an
                    # asynchronous control settles and leaves the rest free, so
                    # membership is tested rather than assumed.
                    if initial is not None and instance in initial:
                        assertions.append(
                            f"(assert (= {now} "
                            f"{'true' if initial[instance] else 'false'}))")
                    # Otherwise free -- but a reset asserted in cycle 0 still
                    # holds, and the constraints below say so.
                    forced = []
                    if preset:
                        forced.append((preset, "true"))
                    if clear:
                        forced.append((clear, "false"))
                    for condition, value in forced:
                        assertions.append(
                            f"(assert (=> {condition} (= {now} {value})))")
                    continue
                previous = cycle - 1
                data = term(record["data"], copy, previous)
                held = data
                # Set dominates clear, matching how liberty orders the two on
                # the cells that carry both, and matching common/celllib.py.
                if clear:
                    was = active(record, "reset", copy, previous)
                    held = f"(ite (or {was} {clear}) false {held})"
                if preset:
                    was = active(record, "set", copy, previous)
                    held = f"(ite (or {was} {preset}) true {held})"
                assertions.append(f"(assert (= {now} {held}))")

        bits = design.outputs[property_port]
        goal = term(bits[0], copy, depth)
        if want:
            assertions.append(f"(assert {goal})")
        elif copy == 0:
            assertions.append(f"(assert (not {goal}))")

    lines += assertions
    lines.append("(check-sat)")
    wanted = []
    if pinned is None:
        wanted += [input_var(c, p, i, len(b))
                   for c in range(depth + 1) for p, b in design.inputs
                   for i in range(len(b))]
    wanted += [f"q0_0_{instance}" for instance in design.flops]
    # What the model says every output does at every cycle, not only at the one
    # the property names. The gate cannot assert the other cycles -- simulation
    # starts at `x` and this model started somewhere definite -- but a per cycle
    # comparison is worth printing beside the observed one.
    for cycle in range(depth + 1):
        for port, bits in sorted(design.outputs.items()):
            for bit in bits:
                name = term(bit, 0, cycle)
                if name not in ("true", "false"):
                    wanted.append(name)
    lines.append(f"(get-value ({' '.join(dict.fromkeys(wanted))}))")
    predicted_names.update(
        {(cycle, port, index): term(bit, 0, cycle)
         for cycle in range(depth + 1)
         for port, bits in design.outputs.items()
         for index, bit in enumerate(bits)})
    return "\n".join(lines) + "\n"


def solve(path):
    """One z3 run in the eda container. Returns (sat, values, seconds)."""
    started = time.time()
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{os.path.abspath('.')}:/work",
         "-w", "/work", IMAGE, "z3", path.replace("\\", "/")],
        capture_output=True, text=True)
    seconds = time.time() - started
    output = result.stdout
    if output.lstrip().startswith("unsat"):
        return False, {}, seconds
    if not output.lstrip().startswith("sat"):
        print(output[-2000:])
        print(result.stderr[-2000:])
        sys.exit("z3 did not answer sat or unsat")
    values = {name: text == "true" for name, text in VALUE.findall(output)}
    return True, values, seconds


def trace_of(design, values, depth):
    """The solver's assignment as one dict of port values per cycle."""
    rows = []
    for cycle in range(depth + 1):
        row = {}
        for port, bits in design.inputs:
            number = 0
            for index in range(len(bits)):
                if values.get(input_var(cycle, port, index, len(bits))):
                    number |= 1 << index
            row[port] = number
        rows.append(row)
    return rows


def predicted_of(design, values, depth, names):
    """What the model says each output is, cycle by cycle."""
    rows = []
    for cycle in range(depth + 1):
        row = {}
        for port, bits in sorted(design.outputs.items()):
            number = 0
            for index in range(len(bits)):
                name = names.get((cycle, port, index))
                if name == "true" or (name and values.get(name)):
                    number |= 1 << index
            row[port] = number
        rows.append(row)
    return rows


def search(design, depth, property_port, out_dir, start=0, initial=None):
    """Iterative deepening, with the robustness loop at each depth.

    `initial` is the constraint on every copy's starting state: None for a free
    one, or a partial {flop: bit} map. The robustness question is asked inside
    the same constraint, so `--post-reset` looks for a start state *among the
    post-reset ones* that defeats the trace, and the default looks among all of
    them.
    """
    timings = []
    for k in range(start, depth + 1):
        copies, rounds = [initial], 0
        while True:
            path = os.path.join(out_dir, f"bmc_k{k}.smt2")
            names = {}
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(encode(design, k, copies, property_port,
                                    predicted_names=names))
            sat, values, seconds = solve(path)
            size = os.path.getsize(path)
            timings.append({"depth": k, "copies": len(copies), "sat": sat,
                            "seconds": round(seconds, 2), "smt2_bytes": size})
            print(f"  depth {k:>3}  {len(copies)} start state(s)  "
                  f"{size / 1024:7.0f} KiB  {seconds:6.2f}s  "
                  f"{'trace found' if sat else 'no trace'}")
            if not sat:
                break
            rows = trace_of(design, values, k)

            # The opposite question: is there a start state these same inputs
            # fail from? An unsat here is what makes the trace usable.
            check = os.path.join(out_dir, f"bmc_k{k}_anystart.smt2")
            with open(check, "w", encoding="utf-8") as handle:
                handle.write(encode(design, k, [initial], property_port,
                                    pinned=rows, want=False))
            broken, counter, seconds = solve(check)
            timings.append({"depth": k, "check": "any start state",
                            "sat": broken, "seconds": round(seconds, 2)})
            if not broken:
                if initial is None:
                    print(f"          no start state defeats it: the trace "
                          f"holds from every one ({seconds:.2f}s)")
                else:
                    free = len(design.flops) - len(initial)
                    note = (" -- which is one state, so this query could not "
                            "have failed" if not free else "")
                    print(f"          no start state defeats it, among the "
                          f"2^{free} this mode allows{note}")
                    print(f"          ({seconds:.2f}s)")
                initial = {i: bool(values.get(f"q0_0_{i}"))
                           for i in design.flops}
                return (k, rows, initial,
                        predicted_of(design, values, k, names), timings)
            rounds += 1
            print(f"          a start state defeats it; pinning it and "
                  f"solving again (round {rounds})")
            if rounds >= MAX_ROUNDS:
                print(f"          {MAX_ROUNDS} rounds without a trace good "
                      f"from every start state; trying a deeper unrolling")
                break
            pinned = dict(initial or {})
            pinned.update({i: bool(counter.get(f"q0_0_{i}"))
                           for i in design.flops})
            copies.append(pinned)
    return None, None, None, None, timings


def run(target, graph_path, depth, property_port, start, post_reset=False):
    with open(graph_path, encoding="utf-8") as handle:
        graph = json.load(handle)
    design = Design(graph)

    out_dir = os.path.dirname(graph_path) or "."
    print(f"target {target}")
    print(f"  graph        {graph_path}")
    print(f"  {len(design.cells)} combinational cell outputs, "
          f"{len(design.flops)} flip flops")
    print(f"  {design.constants_skipped} tie cell output(s) skipped, "
          f"{len(graph.get('constant_nets') or {})} net(s) recorded constant")
    print(f"  clock ports  {design.clock_ports or 'none'}   "
          f"(implicit in the cycle, not solved for)")
    print(f"  free inputs  "
          f"{', '.join(f'{p}[{len(b)}]' for p, b in design.inputs)}")

    if design.undriven:
        print(f"\n  {len(design.undriven)} net(s) read and undriven: "
              f"{design.undriven[:8]}")
        print("RESULT: fail, the transition relation is incomplete")
        return 2
    if design.state_controlled:
        print(f"\n  reset or set computed from a flop: "
              f"{design.state_controlled[:8]}")
        print("  This model treats an asynchronous control as a function of "
              "the inputs alone.")
        print("RESULT: fail, refusing to solve a design this cycle model does "
              "not describe")
        return 2
    if design.both_controls:
        print(f"\n  {len(design.both_controls)} flop(s) carry both an "
              f"asynchronous set and an asynchronous")
        print(f"  clear: {design.both_controls[:8]}")
        print("  This model answers 'both asserted' two different ways. At "
              "cycle 0 the two")
        print("  are independent implications, so both at once is "
              "unsatisfiable and the")
        print("  solver would report no trace. From cycle 1 on, set is applied "
              "after clear")
        print("  and dominates. Neither answer is wrong on its own and the "
              "two disagree.")
        print("RESULT: fail, refusing to solve a design this cycle model "
              "describes twice")
        return 2

    if property_port is None:
        candidates = [p for p, b in design.outputs.items() if len(b) == 1]
        if "success" in design.outputs:
            property_port = "success"
        elif len(candidates) == 1:
            property_port = candidates[0]
        else:
            sys.exit(f"which output should go high? --property one of "
                     f"{sorted(design.outputs)}")
    if property_port not in design.outputs:
        sys.exit(f"{property_port} is not an output of this design: "
                 f"{sorted(design.outputs)}")
    print(f"  property     {property_port} high, at the deepest cycle")

    # The set of starting states the answer is quantified over, printed under
    # both modes so the two runs can be compared rather than assumed equal.
    pinned = design.post_reset_state() if post_reset else {}
    free = [i for i in design.flops if i not in pinned]
    if post_reset:
        clear = sum(1 for v in pinned.values() if not v)
        preset = sum(1 for v in pinned.values() if v)
        print(f"  start states --post-reset: {len(pinned)} of "
              f"{len(design.flops)} flops pinned by an asynchronous")
        print(f"               control, {clear} cleared and {preset} preset; "
              f"{len(free)} free, so the")
        print(f"               trace is proven over 2^{len(free)} = "
              f"{2 ** len(free) if len(free) < 64 else '2^' + str(len(free))} "
              f"starting states.")
        if free:
            print(f"               free: "
                  f"{sorted(free)[:8]}{' ...' if len(free) > 8 else ''}")
        print(f"               The announcement says to toggle rst_n before "
              f"each attempt, so")
        print(f"               this is the set the author actually starts "
              f"from. See docs/06.")
    else:
        print(f"  start states default: none pinned, so the trace is proven "
              f"over all")
        print(f"               2^{len(design.flops)} starting states. "
              f"--post-reset asks the smaller")
        print(f"               question the announcement's rst_n hint "
              f"describes.")
    print(f"\nsearching depths {start} to {depth}")

    started = time.time()
    found, rows, initial, predicted, timings = search(
        design, depth, property_port, out_dir, start,
        pinned if post_reset else None)
    total = time.time() - started

    if found is None:
        print(f"\n  no input sequence drives {property_port} high within "
              f"{depth + 1} cycles")
        print(f"  DEPTH REACHED: {depth}. A negative without its depth is not "
              f"a result; this one has been searched to {depth} and no "
              f"further.")
        print(f"  total {total:.1f}s over {len(timings)} solver calls")
        print("\nRESULT: fail")
        return 1

    print(f"\ntrace, {found + 1} cycles, {property_port} high at cycle {found}")
    header = "  cycle  " + "  ".join(f"{p:>6}" for p, _ in design.inputs)
    print(header)
    for cycle, row in enumerate(rows):
        marker = "  <- " + property_port if cycle == found else ""
        print(f"  {cycle:>5}  " +
              "  ".join(f"{row[p]:>6}" for p, _ in design.inputs) + marker)

    solution = {
        "target": target,
        "graph": graph_path.replace("\\", "/"),
        "depth": found,
        "property": {"port": property_port, "cycle": found, "value": 1},
        "clock_ports": design.clock_ports,
        "widths": {port: len(bits) for port, bits in design.inputs},
        "trace": rows,
        "predicted_outputs": predicted,
        "initial_state": initial,
        # True only under the default. Under --post-reset the trace is proven
        # over the post-reset states and no further, and `sim/replay.py` starts
        # its simulation from x -- so it warns, correctly, rather than being
        # told a robustness that was not established.
        "initial_state_independent": not post_reset,
        "start_states": {
            "mode": "post reset" if post_reset else "every state",
            "pinned": pinned,
            "free": sorted(free),
            "quantified_over": f"2^{len(free)}" if post_reset
                               else f"2^{len(design.flops)}",
        },
        "solver": {"image": IMAGE, "calls": timings,
                   "total_seconds": round(total, 2)},
    }
    # A separate file, because the two modes prove different things and the
    # weaker one must not silently replace the stronger. `sim/replay.py` takes
    # `--solution <path>`, so both can be replayed.
    out = os.path.join(out_dir, "solution_post_reset.json" if post_reset
                       else "solution.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(solution, handle, indent=1)
    print(f"\n  total {total:.1f}s over {len(timings)} solver calls")
    print(f"  wrote {out}")
    replay = f"tools/sim/replay.py {target}"
    if post_reset:
        replay += f" --solution {out.replace(os.sep, '/')}"
    print(f"\n  Not believed yet. Run {replay}\n  to put this trace through "
          f"stage 2's netlist in simulation; a trace that\n  does not reproduce "
          f"is a defect in this file's model, not a solution.")
    if post_reset:
        print(f"  It will warn that the trace was not proven independent of "
              f"the starting\n  state. That warning is correct under this "
              f"mode: the simulation begins at x\n  and this trace was proven "
              f"from the post-reset states only.")
    print("\nRESULT: pass, a trace was found")
    return 0


# --------------------------------------------------------------------------
# selftest
#
# Problems 54 and 55 both live in `Design.__init__`, and neither could be
# exercised by the warm up, whose `constant_nets` is empty. 54 was a check that
# fired on every correct tie cell; 55 was a check that could not fire at all.
# These cases are the standing demonstration that both now speak, and they need
# no container, no solver and no corpus: every one of them is settled while the
# design is being constructed.


def selftest_graph(recorded=0, second_driver=False, literal=False):
    """A small design carrying one tie cell, built in memory.

    `AND2` reads the tie cell's output so the constant is not merely declared.
    The flip flop gives the clock walk something to walk.
    """
    cells = {
        "tie": {"type": "TIE", "connections": {"LO": ["nlo"]}},
        "a1": {"type": "AND2",
               "connections": {"A": ["nlo"], "B": ["nin"], "X": ["nd"]}},
    }
    constant_nets = {"nlo": recorded}
    ports = {
        "clk": {"direction": "input", "bits": ["nclk"]},
        "din": {"direction": "input", "bits": ["nin"]},
        "o": {"direction": "output", "bits": ["nq"]},
    }
    if second_driver:
        cells["a2"] = {"type": "AND2",
                       "connections": {"A": ["nin"], "B": ["nin"],
                                       "X": ["nlo"]}}
    if literal:
        # A constant that is a net *name* rather than a cell output. Stage 3
        # writes these as strings (`stage3_graph.py:465`) and they have no
        # producer, so they are never skipped and never counted -- which is why
        # skipped and recorded are allowed to differ.
        cells["a3"] = {"type": "AND2",
                       "connections": {"A": ["const:1"], "B": ["nin"],
                                       "X": ["nr"]}}
        constant_nets["const:1"] = "1"
        ports["p"] = {"direction": "output", "bits": ["nr"]}
    return {
        "cells": cells,
        "flipflops": {
            "ff": {"cell": "FF", "kind": "ff", "clock": "nclk", "data": "nd",
                   "q": "nq", "reset": None, "set": None,
                   "reset_level": None, "set_level": None,
                   "clock_root": "nclk", "clock_inverted": False,
                   "reset_root": None, "reset_inverted": False,
                   "set_root": None, "set_inverted": False, "enable": None},
        },
        "cell_functions": {"TIE": {"LO": "0", "HI": "1"},
                           "AND2": {"X": "A&B"}},
        "constant_nets": constant_nets,
        "clock_nets": ["nclk"],
        "clock_roots": {"nclk": ["ff"]},
        "ports": ports,
    }


def selftest():
    """Build four synthetic graphs and check what `Design` does with each."""
    print("selftest: Design construction, four synthetic graphs")

    def build(**kwargs):
        try:
            return Design(selftest_graph(**kwargs)), None
        except SystemExit as refusal:
            return None, str(refusal)

    rows = []

    # The clean subject first. A corruption test on a subject that already
    # refuses proves nothing, and every corruption would look caught.
    design, refused = build()
    good = design is not None and design.constants_skipped == 1
    rows.append(("a tie cell that agrees", good,
                 "built, 1 skipped" if good else f"REFUSED: {refused}"))
    if not good:
        print(f"  {rows[0][0]:<34} {rows[0][2]}")
        print("\nRESULT: fail, the subject does not build before it is broken")
        return 1

    design, refused = build(recorded=1)
    good = bool(refused) and "nlo" in refused and "tie.LO" in refused
    rows.append(("the recorded constant flipped", good,
                 f"caught: {refused}" if good else "NOT CAUGHT"))

    design, refused = build(second_driver=True)
    good = (bool(refused) and "two cells" in refused
            and "tie.LO" in refused and "a2.X" in refused)
    rows.append(("a second cell on that net", good,
                 f"caught: {refused}" if good else "NOT CAUGHT"))

    # Legitimate, and the reason the two counts are allowed to differ.
    design, refused = build(literal=True)
    good = (design is not None and design.constants_skipped == 1
            and len(design.graph["constant_nets"]) == 2)
    rows.append(("a literal constant, no producer", good,
                 "built, 1 skipped of 2 recorded" if good
                 else f"REFUSED: {refused}"))

    for name, _good, note in rows:
        print(f"  {name:<34} {note}")

    wrong = [name for name, good, _note in rows if not good]
    if wrong:
        print(f"\nRESULT: fail, {len(wrong)} of {len(rows)} case(s) did not "
              f"behave: {', '.join(wrong)}")
        return 1
    print(f"\nRESULT: pass, {len(rows)} of {len(rows)} cases behaved as "
          f"specified")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selftest" in args:
        sys.exit(selftest())
    target, graph_path = None, None
    depth, property_port, start = DEFAULT_DEPTH, None, 0
    post_reset = False
    rest = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--post-reset":
            post_reset, index = True, index + 1
        elif token == "--depth":
            depth, index = int(args[index + 1]), index + 2
        elif token == "--start":
            start, index = int(args[index + 1]), index + 2
        elif token == "--property":
            property_port, index = args[index + 1], index + 2
        elif token == "--graph":
            graph_path, index = args[index + 1], index + 2
        else:
            rest.append(token)
            index += 1
    if graph_path is None:
        if len(rest) != 1 or rest[0] not in TARGETS:
            sys.exit(f"usage: python tools/stage6_invert.py "
                     f"[{' | '.join(TARGETS)}] [--depth N] [--start K] "
                     f"[--property PORT] [--post-reset]\n"
                     f"       python tools/stage6_invert.py --graph PATH "
                     f"[--depth N]")
        target = rest[0]
        graph_path = os.path.join("out", target, "graph.json")
    else:
        target = rest[0] if rest else os.path.basename(
            os.path.dirname(graph_path))
    if not os.path.exists(graph_path):
        sys.exit(f"{graph_path} missing; run tools/stage3_graph.py first")
    sys.exit(run(target, graph_path, depth, property_port, start,
                 post_reset))
