"""Stage 3's annotations, derived a second time by a different route.

The round trip gate proves stage 3 kept the *circuit*: `graph.json` is written
back out as Verilog and still passes stage 2's simulation. It proves nothing
whatever about the annotations, because `write_verilog` reads only cells, ports
and connections. Clock roots, cone membership and the flip flop inventory could
all be wrong and that gate would still pass -- and those are exactly what stage
4 consumes.

On the corpus, `verify_corpus.py` checks the annotations against a declared
answer key. On the warm up and the puzzle there is no answer key, so the only
thing available is a second derivation that shares as little as possible with
the first.

What is shared, and what is not:

    stage 3   netlist.v -> Yosys -> yosys.json -> graph.json, nets as integers
    here      netlist.json -> plain dicts, nets under stage 2's own names

`netlist.json` is stage 2's artifact, written from the layout before Yosys saw
anything, so the two paths meet only at the LEF and liberty -- and each
derivation below is done in the opposite direction to stage 3's:

    roots     stage 3 walks *backwards* from each flop's clock pin.
              Here every net that no transparent cell drives is flooded
              *forwards*, and a flop's root is whatever label reaches it.

    cones     stage 3 runs a depth first search backwards from each of the 189
              roots. Here one pass of memoised forward propagation computes,
              for every net at once, the set of roots it feeds.

The liberty reading of cell roles is genuinely shared and this cannot check it.
What it does check is the *attribution* -- which net reached which pin -- which
travels through Yosys in one path and not in the other.

Usage:
    python tools/stage3_crosscheck.py warmup
    python tools/stage3_crosscheck.py puzzle
    python tools/stage3_crosscheck.py warmup --selftest
"""

import copy
import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import liberty
from common.lef import functional_pins, load as load_lef
from stage1_cells import PDK_DIR, TARGETS
from stage3_graph import pass_through


def read_netlist(target, lef, lib):
    """Stage 2's netlist as instances, nets and the pins between them."""
    path = os.path.join("out", target, "netlist.json")
    if not os.path.exists(path):
        sys.exit(f"{path} missing; run tools/stage2_nets.py {target}")
    with open(path, encoding="utf-8") as handle:
        netlist = json.load(handle)

    pins_on = defaultdict(list)      # net name -> [{instance, cell, pin, dir}]
    cell_of = {}                     # instance -> cell type
    wired = defaultdict(dict)        # instance -> {pin: net name}
    for net in netlist["nets"]:
        if net["kind"] == "power":
            continue
        for connection in net["connections"]:
            cell = connection["cell"]
            direction = functional_pins(lef.get(cell, {"pins": {}})).get(
                connection["pin"])
            if direction is None:
                continue
            pins_on[net["name"]].append({**connection, "direction": direction})
            cell_of[connection["instance"]] = cell
            wired[connection["instance"]][connection["pin"]] = net["name"]

    # A named net at the top level is a port; the direction follows from whether
    # anything on it drives. Stage 2's own rule, applied to stage 2's own file.
    ports = {}
    for net in netlist["nets"]:
        if net["kind"] == "power" or not net["named"]:
            continue
        ports[net["name"]] = "output" if any(
            p["direction"] == "output" for p in pins_on[net["name"]]) else "input"

    driver = {n: p["instance"] for n, pins in pins_on.items()
              for p in pins if p["direction"] == "output"}
    return netlist, pins_on, cell_of, wired, ports, driver


def inventory(cell_of, wired, lib, pins_by_cell):
    """Flip flops and the nets on their role pins, attributed from stage 2."""
    flops = {}
    for instance, cell in sorted(cell_of.items()):
        entry = lib.get(cell)
        if not entry or not entry["sequential"]:
            continue
        state = entry["sequential"]
        clock, _ = liberty.pin_of(state["clocked_on"])
        data, _ = liberty.pin_of(state["next_state"])
        reset, _ = liberty.pin_of(state["clear"])
        preset, _ = liberty.pin_of(state["preset"])
        outputs = [p for p, d in pins_by_cell[cell].items() if d == "output"]
        flops[instance] = {
            "clock": wired[instance].get(clock),
            "data": wired[instance].get(data),
            "q": wired[instance].get(outputs[0]) if len(outputs) == 1 else None,
            "reset": wired[instance].get(reset) if reset else None,
            "set": wired[instance].get(preset) if preset else None,
        }
    return flops


def roots_forwards(pins_on, cell_of, wired, driver, transparent):
    """Flood forwards through transparent cells; stage 3 walks backwards.

    A net nothing transparent drives is a source. Its label is pushed along
    every chain of buffers and inverters leaving it, carrying parity. Any net
    that ends up with two different labels would mean two sources reaching one
    net, which cannot happen in a netlist with one driver per net and is
    reported rather than resolved.
    """
    def transparent_output(net):
        instance = driver.get(net)
        if instance is None:
            return None
        info = transparent.get(cell_of[instance])
        if info is None or wired[instance].get(info["output"]) != net:
            return None
        return instance, info

    label, clash = {}, []
    sources = [n for n in pins_on if transparent_output(n) is None]
    for source in sources:
        frontier = [(source, False)]
        while frontier:
            net, inverted = frontier.pop()
            if net in label:
                if label[net] != (source, inverted):
                    clash.append((net, label[net], (source, inverted)))
                continue
            label[net] = (source, inverted)
            for instance, cell in cell_of.items():
                info = transparent.get(cell)
                if info is None or wired[instance].get(info["input"]) != net:
                    continue
                out = wired[instance].get(info["output"])
                if out is not None:
                    frontier.append((out, inverted ^ info["inverting"]))
    return label, clash


def cones_forwards(pins_on, cell_of, wired, driver, lib, pins_by_cell,
                   flops, ports, constants):
    """One memoised forward pass giving every net the roots it feeds.

    Stage 3 runs a depth first search backwards from each of the roots, once
    per root. This computes the same relation in the other direction and in one
    pass, so an error in either traversal shows up as a disagreement rather than
    as the same mistake made twice.
    """
    roots = {}
    for instance, record in flops.items():
        for role in ("data", "reset", "set"):
            if record[role]:
                roots[f"{instance}.{role}"] = record[role]
    for name, direction in ports.items():
        if direction == "output":
            roots[f"port.{name}"] = name

    starts_at = defaultdict(set)
    for name, net in roots.items():
        starts_at[net].add(name)

    sequential = {c for c in set(cell_of.values())
                  if lib.get(c) and lib[c]["sequential"]}
    readers = defaultdict(list)
    for instance, cell in cell_of.items():
        if cell in sequential:
            continue
        for pin, net in wired[instance].items():
            if pins_by_cell[cell].get(pin) == "input":
                readers[net].append(instance)

    feeds, state, loops = {}, {}, []

    def resolve(net):
        if net in feeds:
            return feeds[net]
        if state.get(net) == "open":
            loops.append(net)
            return set()
        state[net] = "open"
        result = set(starts_at.get(net, ()))
        for instance in readers.get(net, ()):
            cell = cell_of[instance]
            for pin, direction in pins_by_cell[cell].items():
                if direction != "output":
                    continue
                downstream = wired[instance].get(pin)
                if downstream is not None:
                    result |= resolve(downstream)
        state[net] = "done"
        feeds[net] = result
        return result

    sys.setrecursionlimit(20000)
    for net in pins_on:
        resolve(net)
    return roots, feeds, loops


def compare(graph, pins_on, flops, label, roots, feeds, clash, loops):
    """Against graph.json, keyed on the pins each net touches.

    Not on names. Stage 2 renumbers the nets when it writes the Verilog -- the
    extractor's `$371` becomes `n00076` -- so a comparison keyed on names finds
    every internal net missing and reports a disaster that is not there. A net
    is identified here by the set of (instance, pin) pairs on it, which both
    sides can compute and neither side chose. That is the same rule stage 2
    already needs for placements, for the same reason.
    """
    key = lambda pins: frozenset((p["instance"], p["pin"]) for p in pins)
    mine_by_key = {key(pins): name for name, pins in pins_on.items()}
    theirs_by_key = {key(entry["pins"]): net
                     for net, entry in graph["nets"].items()}

    problems = []
    if clash:
        problems.append(f"{len(clash)} net(s) reached by two different sources")
    if loops:
        problems.append(f"{len(loops)} combinational loop(s): "
                        f"{sorted(set(loops))[:4]}")

    only_mine = set(mine_by_key) - set(theirs_by_key)
    only_theirs = set(theirs_by_key) - set(mine_by_key)
    print(f"  nets              {len(mine_by_key)} here, {len(theirs_by_key)} "
          f"in stage 3, {len(set(mine_by_key) & set(theirs_by_key))} matched "
          f"on the pins they touch")
    if only_mine or only_theirs:
        problems.append(f"{len(only_mine)} net(s) only here, "
                        f"{len(only_theirs)} only in stage 3")
        for k in list(only_mine)[:3]:
            print(f"    only here:  {mine_by_key[k]} on {sorted(k)[:4]}")
        for k in list(only_theirs)[:3]:
            print(f"    only there: {theirs_by_key[k]} on {sorted(k)[:4]}")

    # my net name -> stage 3's net id, through the pin set
    translate = {mine_by_key[k]: theirs_by_key[k]
                 for k in set(mine_by_key) & set(theirs_by_key)}
    across = lambda net: translate.get(net) if net else None

    # --- the flip flop inventory --------------------------------------------
    theirs = {i: {role: r[role] for role in
                  ("clock", "data", "q", "reset", "set")}
              for i, r in graph["flipflops"].items()}
    mine = {i: {role: across(r[role]) for role in
                ("clock", "data", "q", "reset", "set")}
            for i, r in flops.items()}
    if set(theirs) != set(mine):
        problems.append(f"flip flop sets differ: stage 3 has {len(theirs)}, "
                        f"this pass has {len(mine)}")
    shared = set(theirs) & set(mine)
    wrong = [i for i in shared if theirs[i] != mine[i]]
    print(f"  flip flops        {len(shared)} in both, "
          f"{len(shared) - len(wrong)} with every role net agreeing")
    if wrong:
        problems.append(f"{len(wrong)} flip flop(s) wired differently")
        for instance in sorted(wrong)[:4]:
            print(f"    {instance}: stage 3 {theirs[instance]}")
            print(f"    {' ' * len(instance)}  here    {mine[instance]}")

    # --- roots, found forwards against stage 3's backwards walk -------------
    disagree = []
    for instance in sorted(shared):
        for role in ("clock", "reset", "set"):
            net = flops[instance][role]
            if net is None:
                continue
            source, inverted = label.get(net, (net, False))
            record = graph["flipflops"][instance]
            if (across(source), inverted) != (record.get(f"{role}_root"),
                                              bool(record.get(f"{role}_inverted"))):
                disagree.append((instance, role, (source, inverted),
                                 (record.get(f"{role}_root"),
                                  record.get(f"{role}_inverted"))))
    roots_here = {label.get(flops[i]["clock"], (flops[i]["clock"], False))[0]
                  for i in shared if flops[i]["clock"]}
    print(f"  clock roots       {len(roots_here)} forwards {sorted(roots_here)}, "
          f"{len(graph['clock_roots'])} backwards")
    print(f"  role nets rooted  {len(disagree)} disagreement(s) on root or parity")
    if disagree:
        problems.append(f"{len(disagree)} root or parity disagreement(s)")
        for entry in disagree[:4]:
            print(f"    {entry}")

    # --- cones ---------------------------------------------------------------
    if set(roots) != set(graph["cone_roots"]):
        only_here = set(roots) - set(graph["cone_roots"])
        only_there = set(graph["cone_roots"]) - set(roots)
        problems.append(f"cone root sets differ: {len(only_here)} only here, "
                        f"{len(only_there)} only in stage 3")
        print(f"    only here:  {sorted(only_here)[:4]}")
        print(f"    only there: {sorted(only_there)[:4]}")
    print(f"  cone roots        {len(roots)} forwards, "
          f"{len(graph['cone_roots'])} backwards")

    checked, differ = 0, []
    for net, reached in feeds.items():
        other = across(net)
        if other is None:
            continue
        checked += 1
        theirs_cone = set(graph["nets"][other]["cones"])
        if reached != theirs_cone:
            differ.append((net, sorted(reached - theirs_cone)[:3],
                           sorted(theirs_cone - reached)[:3]))
    print(f"  cone membership   {checked} nets compared, "
          f"{checked - len(differ)} identical")
    if differ:
        problems.append(f"{len(differ)} net(s) in different cones")
        for net, extra, missing in differ[:6]:
            print(f"    {net}: only here {extra}, only in stage 3 {missing}")
    return problems


def a_flop_rewired(graph):
    record = next(iter(graph["flipflops"].values()))
    record["data"], record["q"] = record["q"], record["data"]


def a_root_left_at_the_buffer(graph):
    """Stage 3 stopping at the clock net instead of walking back to `clk`."""
    for record in graph["flipflops"].values():
        record["clock_root"] = record["clock"]


def a_parity_flipped(graph):
    next(iter(graph["flipflops"].values()))["clock_inverted"] = True


def a_net_dropped_from_a_cone(graph):
    for entry in graph["nets"].values():
        if entry["cones"]:
            entry["cones"] = entry["cones"][1:]
            return


def an_extra_cone_root(graph):
    graph["cone_roots"]["port.invented"] = next(iter(graph["nets"]))


def a_net_rewired(graph):
    for entry in graph["nets"].values():
        if len(entry["pins"]) > 1:
            entry["pins"] = entry["pins"][1:]
            return


CORRUPTIONS = [
    ("a flop rewired", a_flop_rewired),
    ("a root left at the buffer", a_root_left_at_the_buffer),
    ("a clock parity flipped", a_parity_flipped),
    ("a net dropped from a cone", a_net_dropped_from_a_cone),
    ("an extra cone root", an_extra_cone_root),
    ("a net rewired", a_net_rewired),
]


def derive(target):
    """Everything this pass computes for itself, from stage 2's netlist."""
    lef = load_lef(PDK_DIR)
    lib = liberty.load(PDK_DIR)
    netlist, pins_on, cell_of, wired, ports, driver = read_netlist(target, lef, lib)
    pins_by_cell = {c: functional_pins(lef[c]) for c in set(cell_of.values())}
    transparent = {c: info for c in set(cell_of.values())
                   if (info := pass_through(c, lib, pins_by_cell[c]))}
    flops = inventory(cell_of, wired, lib, pins_by_cell)
    label, clash = roots_forwards(pins_on, cell_of, wired, driver, transparent)
    roots, feeds, loops = cones_forwards(pins_on, cell_of, wired, driver, lib,
                                         pins_by_cell, flops, ports, None)
    return {"pins_on": pins_on, "cell_of": cell_of, "ports": ports,
            "transparent": transparent, "flops": flops, "label": label,
            "roots": roots, "feeds": feeds, "clash": clash, "loops": loops}


def load_graph(target):
    with open(os.path.join("out", target, "graph.json"), encoding="utf-8") as h:
        return json.load(h)


def selftest(target):
    """Corrupt stage 3's answer and confirm this pass notices.

    Two implementations agreeing is only evidence if disagreeing was possible,
    and the first version of this compared nets by name -- which stage 2
    renumbers -- so it reported all 84 as wrong and nothing as right. A check
    that cannot be silenced is worth as little as one that cannot speak.
    """
    facts = derive(target)
    good = load_graph(target)
    quiet = {**facts}
    print(f"selftest on {target}")
    silent = []
    for name, corrupt in CORRUPTIONS:
        graph = copy.deepcopy(good)
        corrupt(graph)
        buffer = io.StringIO()
        stdout, sys.stdout = sys.stdout, buffer
        try:
            problems = compare(graph, quiet["pins_on"], quiet["flops"],
                               quiet["label"], quiet["roots"], quiet["feeds"],
                               quiet["clash"], quiet["loops"])
        finally:
            sys.stdout = stdout
        print(f"  {name:<28} "
              f"{'caught: ' + problems[0] if problems else 'NOT CAUGHT'}")
        if not problems:
            silent.append(name)
    if silent:
        print(f"\nRESULT: fail, {len(silent)} corruption(s) went unnoticed")
        return 1
    print("\nRESULT: pass, every corruption was caught")
    return 0


def run(target):
    lef = load_lef(PDK_DIR)
    lib = liberty.load(PDK_DIR)
    print(f"target {target}: stage 3's annotations, derived again from "
          f"out/{target}/netlist.json")

    netlist, pins_on, cell_of, wired, ports, driver = read_netlist(target, lef, lib)
    pins_by_cell = {c: functional_pins(lef[c]) for c in set(cell_of.values())}
    transparent = {c: info for c in set(cell_of.values())
                   if (info := pass_through(c, lib, pins_by_cell[c]))}
    constants = {n for n, instance in driver.items()
                 if (lib.get(cell_of[instance], {}).get("pins") or {})}
    print(f"  {len(cell_of)} instances, {len(pins_on)} signal nets, "
          f"{len(ports)} ports, {len(transparent)} transparent cell types")

    flops = inventory(cell_of, wired, lib, pins_by_cell)
    label, clash = roots_forwards(pins_on, cell_of, wired, driver, transparent)
    roots, feeds, loops = cones_forwards(pins_on, cell_of, wired, driver, lib,
                                         pins_by_cell, flops, ports, constants)

    problems = compare(load_graph(target), pins_on, flops, label,
                       roots, feeds, clash, loops)
    if problems:
        print(f"\nDISAGREEMENTS")
        for problem in problems:
            print(f"  {problem}")
        print("\nRESULT: the two derivations do not agree")
        return 1
    print("\nRESULT: the two derivations agree exactly")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--selftest"]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/stage3_crosscheck.py "
                 f"[{' | '.join(TARGETS)}] [--selftest]")
    sys.exit(selftest(args[0]) if "--selftest" in sys.argv[1:] else run(args[0]))
