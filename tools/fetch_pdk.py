"""Fetch the sky130 standard cell library, pinned to one commit.

Stage 1 identifies cells by geometry, which needs a reference library to match
against; that library is the PDK's own per cell GDS files. Stage 2 needs pin
directions to emit Verilog, and those come from the LEF abstract views rather
than from guessing at pin names.

Stage 3 needs more than directions. It has to say which net is a clock, which is
a reset and which carries data, and the LEF cannot answer that: `USE CLOCK` is a
statement about how the router should treat a pin, not about what the pin does.
The library proves the difference itself -- `lpflow_inputisolatch_1` marks
`SLEEP_B` as `USE CLOCK`, and `SLEEP_B` is a power gating control.

Liberty is where the functional statements live, per cell:

    dfrtp_2:  clocked_on=CLK  next_state=D  clear=!RESET_B
    dfstp_2:  clocked_on=CLK  next_state=D  preset=!SET_B
    nand2_2:  Y function=(!A) | (!B)
    conb_1:   HI function=1   LO function=0

This library publishes liberty as per cell, per corner JSON rather than as `.lib`
files, so one corner is taken: `tt_025C_1v80`, typical process at 25C and 1.80V.
The corner only changes timing numbers, and no stage here reads timing -- the
functional attributes are identical across corners.

Those `function=` expressions are also what stages 4 and 6 need. A netlist of
blackboxes can be walked as a graph but cannot be exported to SMT2 or CNF,
because a solver has to know what each cell computes.

The commit is pinned rather than tracked so that a clean clone reproduces the
same fingerprints. If the upstream library ever changes a cell, an unpinned
fetch would silently change what the pipeline recognises.

Downloads about 9 MB of cell GDS, LEF and Verilog models into
`pdk/sky130_fd_sc_hd/`,
which is gitignored. Re-running skips whatever is already present.

Usage:
    python tools/fetch_pdk.py
    python tools/fetch_pdk.py --verify
"""

import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = "google/skywater-pdk-libs-sky130_fd_sc_hd"
COMMIT = "ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1"
TREE_URL = f"https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/"
DEST = os.path.join("pdk", "sky130_fd_sc_hd")


def get(url, binary=False):
    request = urllib.request.Request(url, headers={"User-Agent": "gds-teardown"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    return data if binary else data.decode("utf-8")


CORNER = "tt_025C_1v80"


def wanted(path):
    """Cell geometry for stage 1, the abstract views for pin directions, and
    one liberty corner for what the cells actually compute.

    The `.magic.lef` variants are skipped: they are the same cells written for
    Magic, and taking both would put two macros of the same name in the index.

    Only one liberty corner is taken. The library ships 6865 of them across
    process, temperature and voltage; they differ in timing tables and agree on
    every functional attribute, and nothing in this pipeline reads timing.
    """
    if path.endswith(".gds"):
        return True
    if path.endswith(".magic.lef"):
        return False
    if path.endswith(".lef"):
        return True
    if path.endswith(".lib.json"):
        return path.endswith(f"__{CORNER}.lib.json")
    # UDP primitives that the sequential and mux cell models depend on.
    if path.startswith("models/") and path.endswith(".v"):
        return not path.endswith(".tb.v")
    # Verilog cell models for the stage 2 simulation gate. The per-strength
    # wrappers `include their base model by bare filename, so flattening every
    # .v into one directory and pointing the simulator at it with -I resolves
    # them; the files carry include guards, so duplicates are harmless.
    return path.endswith(".v") and not path.endswith(".tb.v")


def cell_paths():
    tree = json.loads(get(TREE_URL))
    if tree.get("truncated"):
        sys.exit("the tree listing came back truncated, fetch needs paging")
    return sorted(entry["path"] for entry in tree["tree"] if wanted(entry["path"]))


def local_path(path):
    """Where a repository path lands under DEST.

    GDS and LEF are flattened, because stage 1 and the LEF reader glob one
    directory. Verilog keeps its repository layout: the cell models `include
    their UDP primitives by relative path, `../../models/...`, which only
    resolves if cells stay two levels deep with models beside them.
    """
    if path.endswith(".v"):
        return os.path.join(DEST, *path.split("/"))
    return os.path.join(DEST, os.path.basename(path))


def fetch_one(path):
    target = local_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return "skipped"
    try:
        data = get(RAW + path, binary=True)
    except urllib.error.URLError as error:
        return f"failed {path}: {error}"
    with open(target, "wb") as handle:
        handle.write(data)
    return "fetched"


def main(verify_only=False):
    os.makedirs(DEST, exist_ok=True)

    if verify_only:
        have = []
        for root, _, files in os.walk(DEST):
            have.extend(os.path.join(root, f) for f in files)
        gds = [f for f in have if f.endswith(".gds")]
        lef = [f for f in have if f.endswith(".lef")]
        ver = [f for f in have if f.endswith(".v")]
        lib = [f for f in have if f.endswith(".lib.json")]
        total = sum(os.path.getsize(f) for f in have)
        print(f"{len(gds)} GDS, {len(lef)} LEF, {len(lib)} liberty and "
              f"{len(ver)} Verilog in {DEST}, {total / 1e6:.2f} MB")
        print(f"pinned to {REPO}@{COMMIT[:12]}")
        return 0

    print(f"listing {REPO}@{COMMIT[:12]}")
    paths = cell_paths()
    print(f"{len(paths)} cell files to reconcile")

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(fetch_one, paths))

    fetched = results.count("fetched")
    skipped = results.count("skipped")
    failures = [r for r in results if r.startswith("failed")]

    print(f"fetched {fetched}, already present {skipped}, failed {len(failures)}")
    for failure in failures[:10]:
        print(f"  {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main("--verify" in sys.argv[1:]))
