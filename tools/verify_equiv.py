"""The recovered netlist against the reference netlist, proven rather than tested.

`puzzle/warmup/01_netlist.v` is the gate level netlist the warm up was actually
built from. It has sat in this repository unread since the first commit --
`docs/problems.md` 34 -- while stages 1 to 3 were checked against a DEF for
placement, a simulation for behaviour, and a second extractor for connectivity.
All three are strong. None of them is this one.

    simulation says   these two agree on the vectors I ran
    this says         these two agree on every input sequence, and here is a
                      proof

That distinction is the whole reason stage 6 exists as a solver stage rather
than a simulation stage, and it is worth making once on a netlist whose answer
is known before making it on one whose answer is not. The netlist proven here is
also, exactly, the netlist stage 6 inverts.

**How.** Both netlists instantiate sky130 cells, which Yosys cannot reason about
as blackboxes, so `common/celllib.py` emits each cell's behaviour from the PDK's
liberty -- through the expression parser `verify_functions.py` gates. Yosys then
builds a miter with `equiv_make`, seeds candidate correspondences structurally
with `equiv_struct -icells`, and proves each one with `equiv_simple` and
`equiv_induct`. `equiv_status -assert` fails unless every one is proven.

`equiv_struct` only *proposes*; a proposal that is wrong fails to prove and the
run fails with it. The net names have nothing in common between the two files --
`\a_reg[0]` against `n25` -- so nothing here matches by name except the six
ports, which are checked to be the same six.

**What it does not cover.** Both sides read the same cell library, so an error in
this repository's reading of liberty would cancel out. That reading is what
`verify_functions.py` checks, against the PDK's own behavioural Verilog, which
is a different file from the one used here on purpose.

Usage:
    python tools/verify_equiv.py warmup
    python tools/verify_equiv.py warmup --netlist out/warmup/broken.v
"""

import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import celllib, liberty
from stage1_cells import PDK_DIR, TARGETS

IMAGE = "gds-teardown-eda:latest"

# The reference netlist per target. The puzzle has none, which is the whole
# situation this pipeline exists to address, and saying so is better than
# offering a gate that silently checks nothing there.
REFERENCE = {
    "warmup": "puzzle/warmup/01_netlist.v",
    "puzzle": None,
}

CELL = re.compile(r"sky130_fd_sc_hd__\w+")
MODULE = re.compile(r"^\s*module\s+(\w+)\s*\(", re.M)
DIRECTION = re.compile(r"^\s*(input|output|inout)\s+([\w\\\[\]]+)\s*;", re.M)


def ports_of(path):
    """The declared port names of a netlist's single module, and its name."""
    text = open(path, encoding="utf-8").read()
    modules = MODULE.findall(text)
    if len(modules) != 1:
        sys.exit(f"{path} declares {len(modules)} modules; this gate compares "
                 f"one against one")
    ports = {name.strip("\\").strip()
             for _, name in DIRECTION.findall(text)}
    return modules[0], ports


def script(gold, gate, library, top):
    """The Yosys equivalence script.

    `proc; flatten; opt_clean` rather than `prep`: `prep` optimises, and two
    designs optimised independently stop being structurally comparable, which
    is what `equiv_struct` needs. Measured -- with `prep -flatten` this same
    check proves nothing at all and `equiv_induct` grinds through five
    induction steps before giving up.

    `async2sync` because the flops carry an asynchronous reset and the SAT
    engine has no model for `$adff`. Without it every proof step warns and the
    run fails for a reason that has nothing to do with the netlists.
    """
    common = f"proc; flatten; opt_clean; async2sync; opt_clean"
    return "\n".join([
        f"read_verilog {library} {gold}",
        f"hierarchy -check -top {top}",
        common,
        "stat",
        "design -stash gold",
        f"read_verilog {library} {gate}",
        f"hierarchy -check -top {top}",
        common,
        "stat",
        "design -stash gate",
        f"design -copy-from gold -as gold {top}",
        f"design -copy-from gate -as gate {top}",
        "equiv_make gold gate equiv",
        "hierarchy -top equiv",
        # Proposes correspondences by structure. Every one still has to be
        # proven below; a wrong proposal is a failure, not a shortcut.
        "equiv_struct -icells -maxiter 40",
        "equiv_simple -seq 5",
        "equiv_induct -seq 5",
        "equiv_status -assert",
    ])


def run(target, netlist=None):
    gold = REFERENCE.get(target)
    if gold is None:
        sys.exit(f"target {target!r} has no reference netlist to prove against. "
                 f"That is the point of the pipeline, not a defect in this gate.")
    if not os.path.exists(gold):
        sys.exit(f"{gold} missing; run git submodule update --init")
    # Forward slashes throughout: these paths are handed to Yosys inside the
    # container, where `out\warmup\graph.v` is one filename that does not exist.
    gate = (netlist or os.path.join("out", target, "graph.v")).replace("\\", "/")
    if not os.path.exists(gate):
        sys.exit(f"{gate} missing; run tools/stage3_graph.py {target}")

    gold_top, gold_ports = ports_of(gold)
    gate_top, gate_ports = ports_of(gate)
    print(f"target {target}")
    print(f"  reference   {gold}   module {gold_top}")
    print(f"  recovered   {gate}   module {gate_top}")

    # Names inside the two files have nothing in common, but the ports must:
    # they are the design's interface and both files describe the same design.
    # A mismatch here would make everything below compare the wrong things.
    if gold_top != gate_top:
        print(f"\nRESULT: fail, module names differ: {gold_top} vs {gate_top}")
        return 1
    if gold_ports != gate_ports:
        print(f"  reference ports  {sorted(gold_ports)}")
        print(f"  recovered ports  {sorted(gate_ports)}")
        print(f"\nRESULT: fail, the two do not agree on the design's interface")
        return 1
    print(f"  ports agree: {', '.join(sorted(gold_ports))}")

    cells = set()
    for path in (gold, gate):
        cells |= set(CELL.findall(open(path, encoding="utf-8").read()))
    library = liberty.load(PDK_DIR)
    out_dir = os.path.join("out", target)
    os.makedirs(out_dir, exist_ok=True)
    lib_path = os.path.join(out_dir, "celllib.v").replace("\\", "/")
    behaviour, empty = celllib.write(library, lib_path, cells)
    print(f"  {len(cells)} cell types: {behaviour} with a liberty function, "
          f"{len(empty)} physical only")
    if empty:
        print(f"    physical only, emitted as empty modules: "
              f"{', '.join(c.split('__')[-1] for c in empty)}")

    script_path = os.path.join(out_dir, "equiv.ys").replace("\\", "/")
    with open(script_path, "w", encoding="utf-8") as handle:
        handle.write(script(gold, gate, lib_path, gold_top) + "\n")

    started = time.time()
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{os.path.abspath('.')}:/work",
         "-w", "/work", IMAGE, "yosys", "-s", script_path],
        capture_output=True, text=True,
    )
    seconds = time.time() - started
    output = result.stdout + result.stderr

    for label in ("gold", "gate"):
        block = re.search(rf"=== {label} ===(.*?)(?=\n\n|\Z)", output, re.S)
        if block:
            counts = dict(re.findall(r"^\s+(\$\w+)\s+(\d+)$", block.group(1), re.M))
            total = re.search(r"Number of cells:\s+(\d+)", block.group(1))
            print(f"  {label}: {total.group(1) if total else '?'} cells "
                  f"{counts}")

    proven = re.search(r"Found (\d+) \$equiv cells in equiv", output)
    unproven = re.search(r"Found (\d+) unproven \$equiv cells", output)
    print(f"\nyosys: {seconds:.1f}s, "
          f"{proven.group(1) if proven else '?'} correspondence points")

    if "Equivalence successfully proven!" in output and result.returncode == 0:
        print(f"  every one proven, including the design's output")
        print("\nRESULT: pass, the recovered netlist and the reference netlist "
              "are\nsequentially equivalent")
        return 0

    print(f"  {unproven.group(1) if unproven else 'some'} could not be proven")
    for line in output.splitlines():
        if "failed" in line or "not equivalent" in line or "ERROR" in line:
            print(f"    {line.strip()}")
    print("\nRESULT: fail")
    return 1


if __name__ == "__main__":
    args = sys.argv[1:]
    override = None
    if len(args) >= 3 and args[1] == "--netlist":
        override, args = args[2], args[:1]
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/verify_equiv.py "
                 f"[{' | '.join(TARGETS)}] [--netlist <path>]")
    sys.exit(run(args[0], override))
