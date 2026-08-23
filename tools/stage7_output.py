"""Stage 7, output extraction. What the chip says, once the input is right.

Stage 6 finds an input sequence that drives the success output high. That is not
the answer. The submission form asks for *"the string value you recovered from
the chip"*, and the announcement is explicit that the output generator is "safe
to ignore during your initial reverse-engineering steps, but you'll need to
simulate it to get your final answer." So the last stage is a simulation, not a
solver: the trace goes back through the netlist and the output bus is read.

**Built on the replay path, not beside it.** `tools/sim/replay.py` already puts a
solver trace through **stage 2's** netlist under the PDK's own cell models, which
is the only cross check that would notice a wrong `cell_functions` entry in
`graph.json`. Stage 7 wants the same simulation with a different question asked
of it, so the cycle model and the Icarus invocation moved into
`tools/sim/harness.py` and both tools call it. There is one driver.

**Why `--extend` exists.** The trace ends at the cycle the property holds. A
string streaming out one byte per cycle is not obliged to have finished by then
-- or to have started. Nothing in the pipeline knows how long it is, so the
number of extra cycles is an argument and its value is printed with the result.

**Why `--after` exists, and why it is printed rather than assumed.** Once the
trace runs out, something has to drive the inputs, and what a real chip would
see is not derivable from anything this repository has read. Three policies:

    hold-last   the last row of the trace, repeated. The default, because the
                trace's last row is the only input assignment known to be
                consistent with the property holding, and because a design that
                streams after success most plausibly does so while the enable
                that got it there stays put.
    zeros       every input low. What a bench that stopped driving would give.
    a=1,b=0     named ports set, the rest held. Starts from hold-last and
                overrides only what is named.

The choice changes the answer and the real mechanism is unknown until the run
happens, so the policy and **the exact row it produces** are both printed and
both written into `output.json`. A default that hid itself would be a guess
wearing a result's clothes.

**What this does not do.** It never interprets the string. It reports the bytes
the bus carried, cycle by cycle, and renders them as text with non-printables
escaped. Which of those bytes are the answer, and what the answer means, is the
author's reading -- `CLAUDE.md`'s working split puts "identify what the circuit
computes" on the other side of the line and this is the last tool before it.

Usage:
    python tools/stage7_output.py warmup
    python tools/stage7_output.py warmup --extend 12
    python tools/stage7_output.py warmup --extend 12 --after zeros
    python tools/stage7_output.py warmup --solution out/warmup/solution_post_reset.json
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "sim"))
import harness                                                 # noqa: E402
from stage1_cells import TARGETS                               # noqa: E402

# The byte a quiet bus carries. A convention this tool states rather than one it
# derives: it is used only to trim leading and trailing idle from the stream,
# both renderings are printed, and the untrimmed list is what `output.json`
# carries first. The corpus declares its own `idle_byte` and
# `tools/verify_output.py` passes that through rather than assuming this one.
IDLE_BYTE = 0

# How a byte that is not printable ASCII is shown. Named escapes for the ones
# that have names, `\xNN` for the rest, and `\?` for a cycle the simulation
# left at x or z -- which is a fourth thing, and must not be shown as a byte.
NAMED = {0x00: r"\0", 0x07: r"\a", 0x08: r"\b", 0x09: r"\t", 0x0a: r"\n",
         0x0b: r"\v", 0x0c: r"\f", 0x0d: r"\r", 0x1b: r"\e", 0x5c: "\\\\"}

AFTER_POLICIES = ("hold-last", "zeros")


def escape(byte):
    """One byte, printable as itself or as an escape. Never dropped."""
    if byte is None:
        return r"\?"
    if byte in NAMED:
        return NAMED[byte]
    if 0x20 <= byte < 0x7f:
        return chr(byte)
    return f"\\x{byte:02x}"


def render(values):
    """A byte sequence as text, with everything unprintable shown."""
    return "".join(escape(v) for v in values)


def after_row(policy, last, widths):
    """The input row the extension cycles drive, and a sentence naming it.

    Returns (row, description). A per port policy starts from hold-last and
    overrides what it names, so a policy that mentions one port says nothing
    about the others by accident.
    """
    if policy == "zeros":
        return {name: 0 for name in widths}, "every input low"
    row = dict(last)
    if policy == "hold-last":
        return row, "the last row of the trace, repeated"
    named = []
    for item in policy.split(","):
        if "=" not in item:
            raise ValueError(f"--after {policy!r}: expected hold-last, zeros, "
                             f"or port=value pairs")
        port, text = item.split("=", 1)
        port, text = port.strip(), text.strip()
        if port not in widths:
            raise ValueError(f"--after {policy!r}: {port!r} is not an input of "
                             f"this design; it has {sorted(widths)}")
        row[port] = int(text, 0)
        named.append(port)
    return row, ("the last row of the trace, with "
                 + ", ".join(f"{p}={row[p]}" for p in named) + " overridden")


def stream_port(ports):
    """The output port a byte stream would arrive on, or None with the reason.

    The widest multi-bit output. Chosen by width from the netlist rather than by
    the name `O`, because the name is a fact about the puzzle and this has to
    run on the warm up too -- where there is no such port at all, and saying so
    is the correct answer rather than a failure.
    """
    buses = sorted(((info["width"], name) for name, info in ports.items()
                    if info["direction"] == "output" and info["width"] > 1),
                   reverse=True)
    if not buses:
        return None, "this design has no multi-bit output port"
    if len(buses) > 1 and buses[0][0] == buses[1][0]:
        tied = sorted(n for w, n in buses if w == buses[0][0])
        return None, (f"{len(tied)} output ports share the widest width "
                      f"{buses[0][0]}: {tied}. Name one with --port")
    return buses[0][1], f"the widest output port, {buses[0][0]} bits"


def trim(values, idle=IDLE_BYTE):
    """The span from the first non-idle byte to the last. (first, last) or None."""
    live = [i for i, v in enumerate(values) if v is not None and v != idle]
    return (live[0], live[-1]) if live else None


def run(target, solution_path=None, extend=0, after="hold-last", port=None):
    solution_path = solution_path or os.path.join("out", target, "solution.json")
    if not os.path.exists(solution_path):
        sys.exit(f"{solution_path} missing; run tools/stage6_invert.py {target}")
    with open(solution_path, encoding="utf-8") as handle:
        solution = json.load(handle)

    # Stage 2's netlist, for the same reason replay uses it: stage 6 solved
    # stage 3's graph, so reading the answer off the graph would be reading the
    # solver's own work back to itself.
    netlist = os.path.join("out", target, "netlist.v")
    if not os.path.exists(netlist):
        sys.exit(f"{netlist} missing; run tools/stage2_nets.py {target}")

    top, module_ports = harness.module_of(netlist)
    ports = harness.port_widths(netlist)
    widths = solution["widths"]
    clocks = solution["clock_ports"]
    watch = {name: info["width"] for name, info in ports.items()
             if info["direction"] == "output"}

    trace = list(solution["trace"])
    row, description = after_row(after, trace[-1], widths)
    rows = trace + [dict(row) for _ in range(extend)]
    notes = {}
    if extend:
        notes[len(trace) - 1] = "<- last trace cycle"
        notes[len(trace)] = "<- extension begins"

    chosen, why = (port, "named with --port") if port else stream_port(ports)
    if port and port not in watch:
        sys.exit(f"--port {port!r} is not an output of this design; it has "
                 f"{sorted(watch)}")

    print(f"target {target}")
    print(f"  solution   {solution_path.replace(os.sep, '/')}   "
          f"depth {solution['depth']}, {len(trace)} cycles")
    print(f"  under test {netlist.replace(os.sep, '/')}   module {top}")
    print(f"  property   {solution['property']['port']} is "
          f"{solution['property']['value']} at cycle "
          f"{solution['property']['cycle']}")
    print(f"  extend     {extend} cycle(s) past the trace, "
          f"{len(rows)} simulated in total")
    print(f"  after      {after}: {description}")
    print(f"             {', '.join(f'{p}={row[p]}' for p in sorted(widths))}")
    print(f"  stream     {chosen if chosen else 'NONE'}   ({why})")

    out_dir = os.path.join("out", target)
    bench = os.path.join(out_dir, "tb_output.v").replace("\\", "/")
    with open(bench, "w", encoding="utf-8") as handle:
        handle.write(harness.clocked_bench(top, module_ports, clocks, widths,
                                           rows, watch, notes))
    print(f"  testbench  {bench}, generated for this run\n")

    code, output, cells, files = harness.icarus(netlist, bench)
    if code != 0 or not files:
        print(output.strip())
        print("\nRESULT: simulation did not run")
        return 2
    observed = harness.samples(output)
    if len(observed) != len(rows):
        print(output.strip())
        print(f"\nRESULT: fail, {len(observed)} sample(s) came back for "
              f"{len(rows)} cycle(s)")
        return 2

    flags = sorted(n for n in watch if watch[n] == 1)
    values = [harness.value(s[chosen]) for s in observed] if chosen else []

    print(f"  {len(cells)} cell types, {len(files)} models, "
          f"{len(observed)} cycles sampled\n")
    header = f"  {'cycle':>5}  {'kind':<9}"
    header += "".join(f"  {name:>8}" for name in flags)
    if chosen:
        header += f"  {chosen + ' hex':>10}  {'char':>6}"
    print(header)
    for index, sample in enumerate(observed):
        kind = "trace" if index < len(trace) else "extension"
        line = f"  {sample['cycle']:>5}  {kind:<9}"
        line += "".join(f"  {sample[name]:>8}" for name in flags)
        if chosen:
            byte = values[index]
            line += f"  {('--' if byte is None else f'{byte:02x}'):>10}"
            line += f"  {escape(byte):>6}"
        print(line)

    span = trim(values) if chosen else None
    record = {
        "target": target,
        "solution": solution_path.replace(os.sep, "/"),
        "netlist": netlist.replace(os.sep, "/"),
        "module": top,
        "property": solution["property"],
        "trace_cycles": len(trace),
        "extend": extend,
        "after": {"policy": after, "means": description, "row": row},
        "flag_ports": flags,
        "stream_port": chosen,
        "stream_reason": why,
        "idle_byte": IDLE_BYTE,
        "cycles": [
            {"cycle": s["cycle"],
             "kind": "trace" if i < len(trace) else "extension",
             "inputs": rows[i],
             "outputs": {name: s[name] for name in sorted(watch)}}
            for i, s in enumerate(observed)],
    }
    if chosen:
        record["bytes"] = values
        record["text"] = render(values)
        record["trimmed"] = None if span is None else {
            "first_cycle": observed[span[0]]["cycle"],
            "last_cycle": observed[span[1]]["cycle"],
            "bytes": values[span[0]:span[1] + 1],
            "text": render(values[span[0]:span[1] + 1]),
            "rule": f"from the first byte that is not {IDLE_BYTE:#04x} to the "
                    f"last, a convention this tool states and does not derive",
        }

    out = os.path.join(out_dir, "output.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1)

    print()
    if not chosen:
        print(f"  no byte stream: {why}.")
        print(f"  The per cycle table above is the whole of what this target "
              f"emits.")
    else:
        print(f"  raw     {' '.join('--' if v is None else f'{v:02x}' for v in values)}")
        print(f"  text    {render(values)!r}")
        if span is None and all(v is None for v in values):
            print(f"  every cycle left {chosen} at x or z; the trace has not "
                  f"flushed this design's state and there is nothing to read")
        elif span is None:
            print(f"  every cycle carried the idle byte {IDLE_BYTE:#04x}; "
                  f"there is no stream to trim")
        else:
            first, last = span
            print(f"  trimmed cycles {observed[first]['cycle']} .. "
                  f"{observed[last]['cycle']}, "
                  f"{last - first + 1} byte(s)")
            print(f"          {render(values[first:last + 1])!r}")
            print(f"          from the first byte that is not "
                  f"{IDLE_BYTE:#04x} to the last, which is this tool's "
                  f"convention and not a reading of the design")
    print(f"\nwrote {out.replace(os.sep, '/')}")
    print(f"\nRESULT: pass, {len(observed)} cycles simulated under "
          f"--after {after} and --extend {extend}. What the bytes mean is not "
          f"this tool's\n  question -- stage 7 reports the stream, the author "
          f"reads it.")
    return 0


def main(argv):
    usage = (f"usage: python tools/stage7_output.py [{' | '.join(TARGETS)}] "
             f"[--solution <path>] [--extend N] [--after <policy>] "
             f"[--port <name>]\n"
             f"  --after  {' | '.join(AFTER_POLICIES)} | port=value,...")
    target, solution, extend, after, port = None, None, 0, "hold-last", None
    rest = list(argv)
    while rest:
        item = rest.pop(0)
        if item == "--solution":
            solution = rest.pop(0) if rest else None
        elif item == "--extend":
            extend = int(rest.pop(0)) if rest else None
        elif item == "--after":
            after = rest.pop(0) if rest else None
        elif item == "--port":
            port = rest.pop(0) if rest else None
        elif target is None:
            target = item
        else:
            sys.exit(usage)
    if target not in TARGETS or extend is None or after is None:
        sys.exit(usage)
    if extend < 0:
        sys.exit("--extend takes a count of cycles, which cannot be negative")
    try:
        return run(target, solution, extend, after, port)
    except ValueError as problem:
        sys.exit(str(problem))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
