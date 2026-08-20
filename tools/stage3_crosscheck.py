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

That distinction runs through every field below and is worth stating once.
Three kinds of check live here:

    attribution     which net reached which pin, which root, which cone. The
                    two paths disagree here whenever one of them is wrong.
    transcription   what `graph.json` carries *about* a cell -- its function
                    string, its role, its reset level -- against what liberty
                    says. A copying error is caught; a misreading of liberty is
                    not, because both sides read the same liberty.
    derivation      a rule applied twice by different code. The hold search is
                    the only one: `stage3_graph.selecting_mux` decides by
                    cofactor equality, `mux_shape` below by scanning the whole
                    truth table for two columns. Same rule, no shared code.

The semantic question liberty itself raises -- does `(!A&!B) | (A&B)` actually
describe this silicon -- belongs to `verify_functions.py`, which compares 850
truth tables against the PDK's own behavioural models, and to stage 6's replay
gate, which puts a solver trace back through those models. Neither is this
file's job and neither is claimed here.

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
from common import boolexpr, liberty
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


def mux_shape(function):
    """(select pin, {leg pin: the level that passes it}) for a 2:1 mux, or None.

    The same rule `stage3_graph.selecting_mux` applies, by a different route.
    That one asks whether the cofactor at S=0 is identically some pin; this one
    builds the entire truth table and looks for a column it matches. Two
    implementations of one rule, so a slip in either shows up as a
    disagreement.

    The rule matters because `mux2i` is an inverting mux -- `(!A0&!S)|(!A1&S)`
    -- and a flop fed by one with its own Q on a leg toggles rather than holds.
    The test this replaced was `"mux2" in the cell name`, which admits it.
    """
    if not function:
        return None
    names, rows = boolexpr.table(boolexpr.parse(function))
    if len(names) != 3:
        return None
    for select in names:
        for low in names:
            for high in names:
                if len({select, low, high}) != 3:
                    continue
                if all(out == (dict(zip(names, bits))[low]
                               if dict(zip(names, bits))[select] == 0
                               else dict(zip(names, bits))[high])
                       for bits, out in rows.items()):
                    return select, {low: "low", high: "high"}
    return None


def holds_forwards(cell_of, wired, lib, pins_by_cell, driver, flops):
    """Which flops hold their value through a mux, found from stage 2's side."""
    out = {}
    for instance, record in flops.items():
        out[instance] = None
        data, q = record["data"], record["q"]
        owner = driver.get(data) if data else None
        if owner is None or q is None:
            continue
        cell = cell_of[owner]
        entry = lib.get(cell)
        if not entry:
            continue
        pin = next((p for p, net in wired[owner].items()
                    if net == data and pins_by_cell[cell].get(p) == "output"),
                   None)
        shape = mux_shape(entry["pins"].get(pin, {}).get("function")) if pin else None
        if shape is None:
            continue
        select, passed_at = shape
        legs = {p: wired[owner].get(p) for p in passed_at}
        held = [p for p, net in legs.items() if net == q]
        if len(held) != 1:
            continue
        other = next(p for p in passed_at if p != held[0])
        out[instance] = {"net": wired[owner].get(select), "mux": owner,
                         "held_when": passed_at[held[0]],
                         "data_leg": legs[other]}
    return out


def levels_forwards(cell_of, lib, flops):
    """Each flop's reset and set level, read off liberty's clear and preset.

    Transcription, not derivation: `graph.json` carries these and liberty is
    where both sides get them. What this catches is a level that arrived in
    `graph.json` wrong, including the one `docs/problems.md` 31 was about --
    liberty writes `clear : "!RESET_B"` bare and `function : "(!A)"`
    parenthesised, and reading the level off the first character is right for
    one and wrong for the other.
    """
    out = {}
    for instance in flops:
        state = lib[cell_of[instance]]["sequential"]
        _, reset_level = liberty.pin_of(state["clear"])
        _, set_level = liberty.pin_of(state["preset"])
        out[instance] = {"cell": cell_of[instance], "kind": state["kind"],
                         "reset_level": reset_level, "set_level": set_level}
    return out


def constants_forwards(cell_of, wired, lib, driver):
    """Nets a cell ties high or low, by liberty function rather than cell name."""
    out = {}
    for net, owner in driver.items():
        entry = lib.get(cell_of[owner])
        if not entry:
            continue
        for pin, wire in wired[owner].items():
            if wire != net:
                continue
            function = (entry["pins"].get(pin, {}).get("function") or "").strip()
            if function in ("0", "1"):
                out[net] = int(function)
    return out


def aliases_forwards(pins_on):
    """Every name this pass knows a net by. Stage 2 gives each net one."""
    return {net: {net} for net in pins_on}


def compare(graph, facts):
    """Against graph.json, keyed on the pins each net touches.

    Not on names. Stage 2 renumbers the nets when it writes the Verilog -- the
    extractor's `$371` becomes `n00076` -- so a comparison keyed on names finds
    every internal net missing and reports a disaster that is not there. A net
    is identified here by the set of (instance, pin) pairs on it, which both
    sides can compute and neither side chose. That is the same rule stage 2
    already needs for placements, for the same reason.
    """
    pins_on, flops = facts["pins_on"], facts["flops"]
    label, roots, feeds = facts["label"], facts["roots"], facts["feeds"]
    clash, loops = facts["clash"], facts["loops"]

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

    # --- what each cone root IS, not only which roots exist -----------------
    #
    # This compared `set(roots) != set(graph["cone_roots"])` and stopped: the
    # keys, never the nets they name. A root pointing at the wrong net would
    # have passed, and every cone hanging off it would have been the wrong
    # cone measured against the right name.
    wrong_roots = [name for name in set(roots) & set(graph["cone_roots"])
                   if across(roots[name]) != graph["cone_roots"][name]]
    print(f"  cone root nets    "
          f"{len(set(roots) & set(graph['cone_roots'])) - len(wrong_roots)}"
          f"/{len(set(roots) & set(graph['cone_roots']))} name the same net")
    if wrong_roots:
        problems.append(f"{len(wrong_roots)} cone root(s) name a different net")
        for name in sorted(wrong_roots)[:4]:
            print(f"    {name}: stage 3 {graph['cone_roots'][name]}, "
                  f"here {across(roots[name])}")

    # --- the hold, derived forwards -----------------------------------------
    holds = facts["holds"]
    mine_holds = {i: h for i, h in holds.items() if h}
    theirs_holds = {i: r["enable"] for i, r in graph["flipflops"].items()
                    if r.get("enable")}
    hold_wrong = []
    for instance in set(mine_holds) | set(theirs_holds):
        mine, theirs = mine_holds.get(instance), theirs_holds.get(instance)
        if (mine is None) != (theirs is None):
            hold_wrong.append((instance, mine, theirs))
        elif mine and (across(mine["net"]), mine["held_when"], mine["mux"],
                       across(mine["data_leg"])) != (
                theirs.get("net"), theirs.get("held_when"), theirs.get("mux"),
                theirs.get("data_leg")):
            hold_wrong.append((instance, mine, theirs))
    print(f"  holds             {len(mine_holds)} forwards, "
          f"{len(theirs_holds)} in stage 3, "
          f"{len(hold_wrong)} disagreement(s) on net, level, mux or data leg")
    if hold_wrong:
        problems.append(f"{len(hold_wrong)} hold annotation(s) disagree")
        for instance, mine, theirs in hold_wrong[:4]:
            print(f"    {instance}: stage 3 {theirs}")
            print(f"    {' ' * len(instance)}  here    {mine}")

    # --- reset and set level, cell and kind ---------------------------------
    levels = facts["levels"]
    level_wrong = []
    for instance, mine in levels.items():
        record = graph["flipflops"].get(instance)
        if record is None:
            continue
        for field in ("cell", "kind", "reset_level", "set_level"):
            if record.get(field) != mine[field]:
                level_wrong.append((instance, field, record.get(field),
                                    mine[field]))
    print(f"  flop cell, kind, reset and set level: {len(level_wrong)} "
          f"disagreement(s) over {len(levels)} flops")
    if level_wrong:
        problems.append(f"{len(level_wrong)} flop attribute(s) disagree")
        for entry in level_wrong[:4]:
            print(f"    {entry[0]}.{entry[1]}: stage 3 {entry[2]!r}, "
                  f"here {entry[3]!r}")

    # --- constants ----------------------------------------------------------
    mine_constants = {across(n): v for n, v in facts["constants"].items()}
    theirs_constants = {n: int(v) for n, v in
                        (graph.get("constant_nets") or {}).items()}
    print(f"  constant nets     {len(mine_constants)} forwards, "
          f"{len(theirs_constants)} in stage 3")
    if mine_constants != theirs_constants:
        problems.append(f"constant nets differ: {len(mine_constants)} here, "
                        f"{len(theirs_constants)} in stage 3")
        for net in sorted(set(mine_constants) | set(theirs_constants))[:4]:
            print(f"    {net}: stage 3 {theirs_constants.get(net)}, "
                  f"here {mine_constants.get(net)}")

    # --- net names ----------------------------------------------------------
    #
    # Not by equality, and the reason is problem 32: stage 2 *renumbers* when it
    # writes the Verilog, so the extractor's `$91` is `n00036` by the time Yosys
    # sees it. Comparing the two strings would report all 78 internal nets wrong
    # and would be measuring the renumbering, not the annotation.
    #
    # What is checkable is what the names have to satisfy whatever they are:
    # every net has one, no two nets share one, and a net this pass knows to be
    # a port carries that port's name. The third is the one that matters -- a
    # port name is the only handle a person has on the netlist, and stage 4's
    # reports and stage 6's traces are printed under them.
    names_missing = [n for m, n in translate.items()
                     if n not in graph["net_names"]]
    seen, duplicated = {}, []
    for their_id in translate.values():
        name = graph["net_names"].get(their_id)
        if name in seen:
            duplicated.append((name, seen[name], their_id))
        seen[name] = their_id
    ports_wrong = [(port, graph["net_names"].get(translate.get(port)))
                   for port in facts["ports"]
                   if port in translate
                   and graph["net_names"].get(translate[port]) != port]
    print(f"  net names         {len(translate) - len(names_missing)}"
          f"/{len(translate)} named, {len(duplicated)} shared between two nets,"
          f" {len(facts['ports']) - len(ports_wrong)}/{len(facts['ports'])} "
          f"ports named after themselves")
    if names_missing:
        problems.append(f"{len(names_missing)} net(s) carry no name")
    if duplicated:
        problems.append(f"{len(duplicated)} net name(s) shared by two nets")
        for name, first, second in duplicated[:4]:
            print(f"    {name!r} is both {first} and {second}")
    if ports_wrong:
        problems.append(f"{len(ports_wrong)} port(s) not named after themselves")
        for port, got in ports_wrong[:4]:
            print(f"    port {port} carries the name {got!r}")

    # --- transparent cell types ---------------------------------------------
    theirs_transparent = graph.get("transparent_cells") or {}
    mine_transparent = facts["transparent"]
    print(f"  transparent cells {len(mine_transparent)} forwards, "
          f"{len(theirs_transparent)} in stage 3")
    if {c: dict(i) for c, i in mine_transparent.items()} != \
            {c: dict(i) for c, i in theirs_transparent.items()}:
        problems.append(f"transparent cell types differ: "
                        f"{sorted(mine_transparent)} here, "
                        f"{sorted(theirs_transparent)} in stage 3")

    # --- the carried function strings ---------------------------------------
    #
    # Transcription. `graph.json` carries every cell's liberty function so that
    # stages 4 and 6 can compute with cells instead of blackboxing them, and a
    # string that got copied wrong on the way in would be invisible to
    # everything downstream: stage 6 would solve a circuit that does not exist,
    # confidently. That the function is *right about the silicon* is a separate
    # question and belongs to verify_functions.py.
    functions_wrong = []
    for cell, pins in (graph.get("cell_functions") or {}).items():
        entry = facts["lib"].get(cell)
        for pin, carried in pins.items():
            declared = (entry or {"pins": {}})["pins"].get(pin, {}).get("function")
            if carried != declared:
                functions_wrong.append((cell, pin, carried, declared))
    print(f"  cell functions    "
          f"{sum(len(p) for p in (graph.get('cell_functions') or {}).values())}"
          f" carried, {len(functions_wrong)} not what liberty says")
    if functions_wrong:
        problems.append(f"{len(functions_wrong)} carried cell function(s) "
                        f"differ from liberty")
        for cell, pin, carried, declared in functions_wrong[:4]:
            print(f"    {cell}.{pin}: carried {carried!r}, liberty {declared!r}")

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


def a_cone_root_moved(graph):
    """The right root names, pointing at the wrong net."""
    name = next(iter(graph["cone_roots"]))
    other = next(n for n in graph["nets"] if n != graph["cone_roots"][name])
    graph["cone_roots"][name] = other


def a_hold_deleted(graph):
    for record in graph["flipflops"].values():
        if record.get("enable"):
            record["enable"] = None
            return


def a_hold_polarity_flipped(graph):
    """What reading `mux2i` as `mux2` produces: the right mux, the wrong sense."""
    for record in graph["flipflops"].values():
        if record.get("enable"):
            record["enable"]["held_when"] = (
                "high" if record["enable"]["held_when"] == "low" else "low")
            return


def a_hold_on_the_wrong_mux(graph):
    """The right flop holding, attributed to a cell that is not driving its D."""
    for record in graph["flipflops"].values():
        if record.get("enable"):
            record["enable"]["mux"] = "not_the_cell_in_front_of_d"
            return


def a_reset_level_flipped(graph):
    record = next(iter(graph["flipflops"].values()))
    record["reset_level"] = "high" if record["reset_level"] == "low" else "low"


def a_set_level_invented(graph):
    """A set level on a flop with no set pin.

    The warm up has no set nets at all, so this is the direction in which it
    can be made to disagree: stage 3 claiming a level where liberty gives none.
    The other direction -- a real set flop whose level is wrong -- needs a
    subject the warm up does not contain, and the tool says so.
    """
    next(iter(graph["flipflops"].values()))["set_level"] = "low"


def a_flop_cell_retyped(graph):
    record = next(iter(graph["flipflops"].values()))
    record["cell"] = "sky130_fd_sc_hd__dfxtp_1"


def a_constant_invented(graph):
    graph["constant_nets"][next(iter(graph["nets"]))] = 1


def a_net_renamed(graph):
    """A port whose net stopped carrying the port's name.

    Renaming an internal net would not be caught and is not claimed to be:
    stage 2 renumbers those on the way into the Verilog, so there is no name
    for this pass to hold stage 3 to. A port's name is different -- it is the
    one handle a person has on the design, and every stage 4 report and stage 6
    trace is printed under it.
    """
    for net, name in graph["net_names"].items():
        if name in graph["ports"]:
            graph["net_names"][net] = "renamed_by_nobody"
            return


def a_transparent_type_lost(graph):
    graph["transparent_cells"] = {}


def a_function_mistranscribed(graph):
    """One carried liberty string altered.

    Stage 6 builds its transition relation out of these, so a string that got
    copied wrong makes it solve a circuit that does not exist. Nothing
    downstream of stage 3 reads liberty again to notice.
    """
    cell = next(iter(graph["cell_functions"]))
    pin = next(iter(graph["cell_functions"][cell]))
    graph["cell_functions"][cell][pin] = "(A)"


CORRUPTIONS = [
    ("a flop rewired", a_flop_rewired),
    ("a root left at the buffer", a_root_left_at_the_buffer),
    ("a clock parity flipped", a_parity_flipped),
    ("a net dropped from a cone", a_net_dropped_from_a_cone),
    ("an extra cone root", an_extra_cone_root),
    ("a net rewired", a_net_rewired),
    # One per field group the comparison did not read until now.
    ("a cone root moved", a_cone_root_moved),
    ("a hold deleted", a_hold_deleted),
    ("a hold polarity flipped", a_hold_polarity_flipped),
    ("a hold on the wrong mux", a_hold_on_the_wrong_mux),
    ("a reset level flipped", a_reset_level_flipped),
    ("a set level invented", a_set_level_invented),
    ("a flop cell retyped", a_flop_cell_retyped),
    ("a constant invented", a_constant_invented),
    ("a net renamed", a_net_renamed),
    ("a transparent type lost", a_transparent_type_lost),
    ("a function mistranscribed", a_function_mistranscribed),
]

# What the warm up cannot exercise from the positive side, and why. A
# corruption above makes each of these disagree, so the comparison is shown
# able to speak; what is not shown is that it says the right thing about a
# circuit that really has one. Those subjects are in the corpus, which has no
# `netlist.json` -- it is synthesised, never laid out -- so this pass cannot
# read it without a second netlist reader. Recorded rather than implied.
NOT_EXERCISED_POSITIVELY = {
    "warmup": [
        ("set level", "no flop in the warm up has a set pin; "
                      "out/synth/lfsr_fibonacci_w8 does"),
        ("constant nets", "the warm up ties nothing; "
                          "out/synth/tied_outputs_w8_c2 does"),
        ("a hold where there is none", "every one of the warm up's 16 flops "
                                       "holds, so the false positive the mux2i "
                                       "rule exists to prevent has no subject "
                                       "here; the corpus witness circuit is "
                                       "where that direction is shown"),
        ("internal net names", "stage 2 renumbers on the way into the Verilog "
                               "(problem 32), so only the port names are held "
                               "to their value"),
    ],
}


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
            "roots": roots, "feeds": feeds, "clash": clash, "loops": loops,
            "lib": lib,
            "holds": holds_forwards(cell_of, wired, lib, pins_by_cell, driver,
                                    flops),
            "levels": levels_forwards(cell_of, lib, flops),
            "constants": constants_forwards(cell_of, wired, lib, driver),
            "aliases": aliases_forwards(pins_on)}


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
    print(f"selftest on {target}")

    def quietly(graph):
        buffer = io.StringIO()
        stdout, sys.stdout = sys.stdout, buffer
        try:
            return compare(graph, facts)
        finally:
            sys.stdout = stdout

    # The uncorrupted graph first. A corruption test on a subject that already
    # disagrees proves nothing, and every corruption would look caught.
    clean = quietly(copy.deepcopy(good))
    print(f"  {'the graph as it stands':<28} "
          f"{'agrees' if not clean else 'ALREADY DISAGREES: ' + clean[0]}")
    if clean:
        print(f"\nRESULT: fail, the subject does not pass before it is broken")
        return 1

    silent = []
    for name, corrupt in CORRUPTIONS:
        graph = copy.deepcopy(good)
        corrupt(graph)
        problems = quietly(graph)
        print(f"  {name:<28} "
              f"{'caught: ' + problems[0] if problems else 'NOT CAUGHT'}")
        if not problems:
            silent.append(name)

    gaps = NOT_EXERCISED_POSITIVELY.get(target, [])
    if gaps:
        print(f"\n  {len(gaps)} field(s) this target can only disagree about, "
              f"never confirm:")
        for field, why in gaps:
            print(f"    {field:<18} {why}")

    if silent:
        print(f"\nRESULT: fail, {len(silent)} corruption(s) went unnoticed")
        return 1
    print(f"\nRESULT: pass, all {len(CORRUPTIONS)} corruptions were caught")
    return 0


def run(target):
    print(f"target {target}: stage 3's annotations, derived again from "
          f"out/{target}/netlist.json")
    facts = derive(target)
    print(f"  {len(facts['cell_of'])} instances, {len(facts['pins_on'])} "
          f"signal nets, {len(facts['ports'])} ports, "
          f"{len(facts['transparent'])} transparent cell types")
    problems = compare(load_graph(target), facts)
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
