"""Stage 2, connectivity extraction. Layout to netlist.

Reads the layout and the stage 1 instance list, works out which cell pins are
wired to which, and writes `out/<target>/netlist.json`.

The extractor is KLayout's `LayoutToNetlist`. It already knows how to merge
touching shapes, follow a via up a layer and resolve pins, and reimplementing
that is not a good use of the schedule.

What it does *not* know is this process's connectivity stack, and the defaults
are not a safe guess. A connectivity rule that is too permissive shorts nets
together, one that is too strict leaves pins floating, and both produce a
netlist that looks structurally plausible and is functionally wrong. So the
stack is written out explicitly below and recorded in docs/02-connectivity.md.

Cells are kept as a hierarchy rather than flattened. Each standard cell becomes
its own circuit with named pins, which means the top level netlist is a graph
over cell pins, exactly what stage 3 wants, and the extraction stays fast.

Usage:
    python tools/stage1_cells.py warmup
    python tools/stage2_nets.py warmup
"""

import json
import os
import re
import sys
from collections import Counter

import klayout.db as db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.gds import DEF_NAME
from common.lef import functional_pins, load as load_lef
from stage1_cells import PDK_DIR, TARGETS

# The conductor stack, bottom to top. Each entry is a routing layer; the entry
# after it is the via that reaches the next one up.
#
#   li1 --mcon--> met1 --via--> met2 --via2--> met3 --via3--> met4 --via4--> met5
#
# li1 is included because that is where standard cell pins live. Leaving it out
# would disconnect every cell from the routing above it.
STACK = [
    ("li1", 67, 20),
    ("mcon", 67, 44),
    ("met1", 68, 20),
    ("via", 68, 44),
    ("met2", 69, 20),
    ("via2", 69, 44),
    ("met3", 70, 20),
    ("via3", 70, 44),
    ("met4", 71, 20),
    ("via4", 71, 44),
    ("met5", 72, 20),
]

# Text layers that name a net. Cell pins are labelled on li1 and met1; the top
# level ports are labelled on met3, met4 and met5.
LABELS = [
    ("li1", 67, 5),
    ("met1", 68, 5),
    ("met3", 70, 5),
    ("met4", 71, 5),
    ("met5", 72, 5),
]

POWER = {"VPWR", "VGND", "VPB", "VNB"}

BUS_BIT = re.compile(r"^(?P<base>.+)\[(?P<index>\d+)\]$")


def verilog_identifier(name):
    """Verilog needs an escaped identifier for anything not [A-Za-z_][\\w$]*."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name):
        return name
    return "\\" + name + " "


def write_verilog(path, top_name, nets, ports, lef):
    """Structural Verilog from the recovered nets.

    Power pins are left off the instances. The sky130 cell models only expose
    them when compiled with USE_POWER_PINS, and the reference netlist shipped
    with the warm up omits them too, so this matches what a simulator expects.
    """
    net_of = {}
    for index, net in enumerate(nets):
        if net["kind"] == "power":
            net_of[net["name"]] = net["name"]
        else:
            net_of[net["name"]] = net["name"] if net["named"] else f"n{index:05d}"

    # Group bus bits so O[0]..O[7] is declared once as a vector.
    buses = {}
    scalars = []
    for name, direction in sorted(ports.items()):
        match = BUS_BIT.match(name)
        if match:
            base = match.group("base")
            entry = buses.setdefault(base, {"direction": direction, "bits": []})
            entry["bits"].append(int(match.group("index")))
        else:
            scalars.append((name, direction))

    lines = []
    header = sorted([n for n, _ in scalars] + list(buses))
    lines.append(f"module {top_name} ({', '.join(header)});")
    for name, direction in scalars:
        lines.append(f"  {direction} {verilog_identifier(name)};")
    for base, entry in sorted(buses.items()):
        lines.append(f"  {entry['direction']} [{max(entry['bits'])}:"
                     f"{min(entry['bits'])}] {base};")
    lines.append("")

    port_names = set(ports)
    wires = sorted(net_of[n["name"]] for n in nets
                   if n["kind"] != "power" and n["name"] not in port_names)
    for wire in wires:
        lines.append(f"  wire {verilog_identifier(wire)};")
    lines.append("")

    connections_by_instance = {}
    for net in nets:
        for connection in net["connections"]:
            connections_by_instance.setdefault(connection["instance"], {})[
                connection["pin"]] = net_of[net["name"]]

    for instance in sorted(connections_by_instance):
        pins = connections_by_instance[instance]
        cell = next(c["cell"] for n in nets for c in n["connections"]
                    if c["instance"] == instance)
        allowed = functional_pins(lef[cell]) if cell in lef else {}
        wired = [f".{pin}({verilog_identifier(pins[pin])})"
                 for pin in sorted(pins) if pin in allowed]
        if not wired:
            continue
        lines.append(f"  {cell} {instance} ({', '.join(wired)});")

    lines.append("endmodule")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return len([l for l in lines if l.startswith("  sky130")])


def extract(gds_path):
    layout = db.Layout()
    layout.read(gds_path)
    top = layout.top_cell()

    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))

    regions = {}
    for name, layer, datatype in STACK:
        regions[name] = l2n.make_polygon_layer(layout.layer(layer, datatype), name)
        l2n.connect(regions[name])

    order = [name for name, _, _ in STACK]
    for lower, upper in zip(order, order[1:]):
        l2n.connect(regions[lower], regions[upper])

    for metal, layer, datatype in LABELS:
        texts = l2n.make_text_layer(layout.layer(layer, datatype), f"{metal}_label")
        l2n.connect(regions[metal], texts)

    l2n.extract_netlist()
    return layout, l2n, top.name


def run(target):
    config = TARGETS[target]
    instances_path = os.path.join("out", target, "instances.json")
    if not os.path.exists(instances_path):
        sys.exit(f"{instances_path} missing, run tools/stage1_cells.py {target} first")
    with open(instances_path, encoding="utf-8") as handle:
        stage1 = json.load(handle)

    print(f"target   {target}")
    print(f"layout   {config['gds']}")
    print(f"stage 1  {len(stage1['instances'])} instances")

    # Key on position *and* orientation, never position alone.
    #
    # A GDS origin is where the cell's own origin landed, not its lower left
    # corner, so a flipped cell extends left and down from it. That lets two
    # placements of different cells share an origin: in the warm up, 230
    # instances occupy only 178 distinct origins. Keying on position alone
    # silently maps a subcircuit onto the wrong instance, and the damage shows
    # up much later as a pin name that the cell does not have.
    by_placement = {}
    for record in stage1["instances"]:
        key = (record["origin"][0], record["origin"][1], record["orient"])
        if key in by_placement:
            sys.exit(f"stage 1 placements are not unique at {key}, cannot map")
        by_placement[key] = record

    layout, l2n, top_name = extract(config["gds"])
    netlist = l2n.netlist()
    top = netlist.circuit_by_name(top_name)
    if top is None:
        sys.exit(f"no circuit named {top_name!r} came out of the extractor")

    # --- tie subcircuits back to stage 1 instances --------------------------
    subcircuit_instance = {}
    unlinked = Counter()
    for subcircuit in top.each_subcircuit():
        transform = subcircuit.trans
        displacement = transform.disp
        orientation = (transform.is_mirror(), round(transform.angle) % 360)
        key = (round(displacement.x, 3), round(displacement.y, 3),
               DEF_NAME[orientation])
        record = by_placement.get(key)
        if record is None:
            unlinked[subcircuit.circuit_ref().name] += 1
            continue
        if record["cell"] != subcircuit.circuit_ref().name:
            sys.exit(f"placement at {key} is {record['cell']} per stage 1 but "
                     f"{subcircuit.circuit_ref().name} per the extractor")
        subcircuit_instance[subcircuit.id()] = record

    print(f"\nsubcircuits linked to a stage 1 instance: {len(subcircuit_instance)}")
    if unlinked:
        print("  not linked, expected to be routing vias only:")
        for name, count in unlinked.most_common(8):
            print(f"    {count:6d}  {name}")

    # --- nets ---------------------------------------------------------------
    nets = []
    floating = []
    for net in top.each_net():
        connections = []
        for reference in net.each_subcircuit_pin():
            record = subcircuit_instance.get(reference.subcircuit().id())
            if record is None:
                continue
            connections.append({
                "instance": record["id"],
                "cell": record["cell"],
                "pin": reference.pin().expanded_name(),
            })
        name = net.expanded_name()
        if not connections:
            floating.append({"name": name, "shapes": net.subcircuit_pin_count()})
            continue
        nets.append({
            "name": name,
            "named": not name.startswith("$"),
            "kind": "power" if name in POWER else "signal",
            "connections": sorted(connections, key=lambda c: (c["instance"], c["pin"])),
        })

    signal = [n for n in nets if n["kind"] == "signal"]
    power = [n for n in nets if n["kind"] == "power"]

    print(f"\nnets carrying at least one cell pin: {len(nets)}")
    print(f"  signal {len(signal)}")
    print(f"  power  {len(power)}  ({', '.join(n['name'] for n in power)})")
    print(f"  named  {sum(1 for n in nets if n['named'])}")
    print(f"floating, no cell pin at all: {len(floating)}")

    fanout = Counter(len(n["connections"]) for n in signal)
    lonely = [n for n in signal if len(n["connections"]) < 2]
    print(f"\nsignal net fanout: min {min(fanout)}, max {max(fanout)}")
    if lonely:
        print(f"  {len(lonely)} signal nets touch fewer than two pins, inspect:")
        for net in lonely[:10]:
            print(f"    {net['name']}: {net['connections']}")

    # --- ports and their directions ----------------------------------------
    #
    # A named net at the top level is a port: labels inside cells stay inside
    # their own circuit, so the only labels landing on top level nets are the
    # ones on the die's own pin geometry.
    #
    # The direction follows from what the port drives. If any pin it reaches is
    # an output, the die is driving outward; otherwise every pin it reaches is
    # listening, so the die is being driven.
    lef = load_lef(PDK_DIR)
    ports = {}
    for net in nets:
        if net["kind"] == "power" or not net["named"]:
            continue
        drives = any(
            functional_pins(lef.get(c["cell"], {"pins": {}})).get(c["pin"]) == "output"
            for c in net["connections"]
        )
        ports[net["name"]] = "output" if drives else "input"

    print(f"\nports ({len(ports)}):")
    for name, direction in sorted(ports.items()):
        print(f"  {direction:<6} {name}")

    out_dir = os.path.join("out", target)
    os.makedirs(out_dir, exist_ok=True)

    verilog_path = os.path.join(out_dir, "netlist.v")
    emitted = write_verilog(verilog_path, top_name, nets, ports, lef)
    print(f"\nwrote {verilog_path} with {emitted} instances")

    out_path = os.path.join(out_dir, "netlist.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump({
            "target": target,
            "top": top_name,
            "source_gds": config["gds"],
            "connectivity": [list(entry) for entry in STACK],
            "nets": nets,
            "floating": floating,
        }, handle, indent=1)
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage2_nets.py [{' | '.join(TARGETS)}]")
    sys.exit(run(args[0]))
