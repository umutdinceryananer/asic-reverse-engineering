"""Run a stage 2 simulation gate inside the EDA container.

The Python half of the pipeline runs natively; Icarus does not ship a wheel, so
it lives in the container built from `docker/Dockerfile` and the repository is
mounted into it.

Cell models are resolved with Icarus's library search rather than by listing
files. Every model in the PDK cache is named exactly after the module it
defines, so `-y` finds `sky130_fd_sc_hd__nand2_2.v` when the netlist
instantiates `sky130_fd_sc_hd__nand2_2`, and `-I` resolves the `include` each
of those wrappers makes to its base model.

Usage:
    python tools/sim/run.py warmup
"""

import glob
import os
import re
import subprocess
import sys

# Simulation needs only Icarus, which is the small target of docker/Dockerfile.
# Stage 3 onward uses gds-teardown-eda, which adds Yosys and z3 on top.
IMAGE = "gds-teardown-sim:latest"
PDK = "pdk/sky130_fd_sc_hd"

GATES = {
    "warmup": {
        "testbench": "tools/sim/tb_warmup.v",
        "netlist": "out/warmup/netlist.v",
        "asks": "success exactly when the two operands sum to 496, "
                "checked over all 65536 pairs",
    },
    "puzzle": {
        "testbench": "tools/sim/tb_puzzle.v",
        "netlist": "out/puzzle/netlist.v",
        "asks": "the inputs from example_inputs.vcd reproduce TRY AGAIN "
                "with success low",
    },
}


INSTANCE = re.compile(r"^\s*(sky130_fd_sc_hd__\w+)\s+\S+\s*\(", re.M)


def model_files(netlist_path):
    """The cell model for every distinct cell the netlist instantiates.

    Listed explicitly rather than found with Icarus's `-y` library search,
    because the models keep the PDK's directory layout. They have to: each
    per-strength wrapper includes its base model from the same directory, and
    the sequential and mux models reach further up for their UDP primitives
    with `../../models/...`. Those relative includes only resolve if the files
    sit where the library put them, and `-y` does not search subdirectories.
    """
    cells = sorted(set(INSTANCE.findall(open(netlist_path, encoding="utf-8").read())))
    files, includes, missing = [], set(), []
    for cell in cells:
        found = glob.glob(os.path.join(PDK, "cells", "*", f"{cell}.v"))
        if not found:
            missing.append(cell)
            continue
        path = found[0].replace("\\", "/")
        files.append(path)
        # Two includes have to resolve from here, and Icarus searches -I paths
        # rather than the including file's own directory:
        #   "sky130_fd_sc_hd__nand2.v"        the base model, same directory
        #   "../../models/udp_x/...v"         UDP primitives, two levels up
        # Adding the cell's directory satisfies both at once.
        includes.add(os.path.dirname(path))
    return cells, files, sorted(includes), missing


def run(target):
    gate = GATES[target]
    for path in (gate["testbench"], gate["netlist"]):
        if not os.path.exists(path):
            sys.exit(f"{path} missing")
    if not os.path.isdir(PDK):
        sys.exit(f"{PDK} missing, run tools/fetch_pdk.py first")

    print(f"target {target}")
    print(f"gate   {gate['asks']}")

    cells, files, includes, missing = model_files(gate["netlist"])
    print(f"cell types instantiated: {len(cells)}, models found: {len(files)}")
    if missing:
        print("no model in the PDK cache for:")
        for cell in missing:
            print(f"  {cell}")
        return 2
    print()

    # FUNCTIONAL selects the plain logic models over the behavioural ones,
    # which carry specify blocks and timing checks and hold x without a
    # timing-annotated run. UNIT_DELAY is the delay macro those models expect.
    # Without both, every cell output stays x and the netlist looks broken when
    # it is not.
    build = (
        "iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY=#1 -o /tmp/sim.vvp "
        + " ".join(f"-I {d}" for d in includes) + " "
        + f"{gate['testbench']} {gate['netlist']} " + " ".join(files)
    )
    command = f"set -e; {build}; vvp /tmp/sim.vvp"

    result = subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{os.path.abspath('.')}:/work",
         "-w", "/work", IMAGE, "bash", "-c", command],
        capture_output=True, text=True,
    )

    output = result.stdout + result.stderr
    print(output.strip())

    if result.returncode != 0:
        print("\nRESULT: simulation did not run")
        return 2
    if "RESULT: pass" in output:
        return 0
    return 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in GATES:
        sys.exit(f"usage: python tools/sim/run.py [{' | '.join(GATES)}]")
    sys.exit(run(args[0]))
