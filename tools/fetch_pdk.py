"""Fetch the sky130 standard cell GDS library, pinned to one commit.

Stage 1 identifies cells by geometry, which needs a reference library to match
against. That library is the PDK's own per cell GDS files.

The commit is pinned rather than tracked so that a clean clone reproduces the
same fingerprints. If the upstream library ever changes a cell, an unpinned
fetch would silently change what the pipeline recognises.

Downloads about 4 MB across roughly 440 files into `pdk/sky130_fd_sc_hd/`,
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


def gds_paths():
    tree = json.loads(get(TREE_URL))
    if tree.get("truncated"):
        sys.exit("the tree listing came back truncated, fetch needs paging")
    return sorted(entry["path"] for entry in tree["tree"]
                  if entry["path"].endswith(".gds"))


def fetch_one(path):
    target = os.path.join(DEST, os.path.basename(path))
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
        have = [f for f in os.listdir(DEST) if f.endswith(".gds")]
        total = sum(os.path.getsize(os.path.join(DEST, f)) for f in have)
        print(f"{len(have)} cell GDS files in {DEST}, {total / 1e6:.2f} MB")
        print(f"pinned to {REPO}@{COMMIT[:12]}")
        return 0

    print(f"listing {REPO}@{COMMIT[:12]}")
    paths = gds_paths()
    print(f"{len(paths)} cell GDS files to reconcile")

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
