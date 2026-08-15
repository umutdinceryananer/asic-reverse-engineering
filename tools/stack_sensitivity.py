"""Does every layer in the connectivity stack actually earn its place?

stage2_nets.py declares the conductor stack explicitly rather than trusting a
default, on the argument that a wrong connectivity rule yields a netlist that is
structurally plausible and functionally wrong. That argument is only worth
anything if the declared stack is right, and "it looks right" is not evidence.

So: drop one layer at a time, re-extract, and count how many nets change. A
layer that carries connectivity will break nets when removed. A layer that
carries none will not, and that is worth knowing too -- it says the stack is
wider than this layout needs, which is the safe direction to be wrong in.

Nets are compared as sets of (placement, pin), never by name and never by the
extractor's own subcircuit ids. Those ids are assigned per run and are not
stable across two runs of the same stack, so keying on them reports differences
that are an artifact of the harness. The identity run below exists to catch
exactly that: if the same stack twice does not give the same answer, the
comparison is broken and nothing after it means anything.

Usage:
    python tools/stack_sensitivity.py warmup
"""

import os
import sys

import klayout.db as db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.gds import DEF_NAME
from stage1_cells import TARGETS
from stage2_nets import LABELS, STACK


def extract(gds_path, stack):
    """Extract with the given stack, returning nets as sets of (placement, pin)."""
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()

    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))
    regions = {}
    for name, layer, datatype in stack:
        regions[name] = l2n.make_polygon_layer(layout.layer(layer, datatype), name)
        l2n.connect(regions[name])

    order = [name for name, _, _ in stack]
    for lower, upper in zip(order, order[1:]):
        l2n.connect(regions[lower], regions[upper])

    for metal, layer, datatype in LABELS:
        if metal not in regions:
            continue
        texts = l2n.make_text_layer(layout.layer(layer, datatype), f"{metal}_label")
        l2n.connect(regions[metal], texts)

    l2n.extract_netlist()
    circuit = l2n.netlist().circuit_by_name(top.name)

    placement = {}
    for subcircuit in circuit.each_subcircuit():
        transform = subcircuit.trans
        placement[subcircuit.id()] = (
            round(transform.disp.x, 3), round(transform.disp.y, 3),
            DEF_NAME[(transform.is_mirror(), round(transform.angle) % 360)],
            subcircuit.circuit_ref().name,
        )

    nets = set()
    for net in circuit.each_net():
        pins = frozenset((placement[r.subcircuit().id()], r.pin().expanded_name())
                         for r in net.each_subcircuit_pin())
        if pins:
            nets.add(pins)
    return nets


def run(target):
    gds = TARGETS[target]["gds"]
    print(f"target {target}\nlayout {gds}\n")

    baseline = extract(gds, STACK)
    print(f"full stack: {len(baseline)} nets carrying a cell pin")

    control = extract(gds, STACK)
    if control != baseline:
        sys.exit("the same stack extracted twice gave different nets; the "
                 "comparison key is wrong, fix it before reading anything below")
    print("same stack extracted twice: identical, so the key is stable\n")

    routing = [name for name, _, _ in STACK if not name.startswith(("mcon", "via"))]
    print(f"{'dropped':<8} {'nets':>6} {'unchanged':>10} {'broken':>8}")
    for dropped in reversed(routing):
        stack = [entry for entry in STACK if entry[0] != dropped]
        nets = extract(gds, stack)
        unchanged = len(nets & baseline)
        print(f"{dropped:<8} {len(nets):>6} {unchanged:>10} "
              f"{len(baseline) - unchanged:>8}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stack_sensitivity.py [{' | '.join(TARGETS)}]")
    sys.exit(run(args[0]))
