"""What the container actually carries, against the copy recorded here.

`docs/references.md` section 3 puts this plainly: we pin the PDK and nothing
else. `docker/Dockerfile` installs `yosys z3 iverilog` from a Debian suite with
no version, so stage 3's Yosys and stage 6's z3 are whatever apt served on the
day the image was built. For a deliverable whose product *is* the pipeline, an
unpinned toolchain is the one thing that cannot be afforded -- and the same
reference file supplies the counterexample, a six-year-old project whose
SHA-pinned submodules still resolve while its prose-pinned Vivado version is
unbuildable.

Two halves, and only one of them is a pin.

**Pinned.** The base image, by digest, in `docker/Dockerfile`. A clean rebuild
resolves to the same bytes rather than to whatever `debian:bookworm-slim` points
at that week.

**Recorded, not pinned.** The apt packages. Pinning them by apt version breaks
the moment Debian moves a point release out of the archive, and building them
from source is hours and a second toolchain to maintain. So each image records
its own tool versions at build time into a manifest baked into it, and this
compares that manifest against `tools/TOOL_VERSIONS.recorded`. **The gate
catching the drift is the mechanism.** The versions may move; they cannot move
silently, and a rebuild that changes one fails here until somebody re-records it
with `--record`, which is a decision rather than a side effect.

Given a target it also stamps `out/<target>/TOOL_VERSIONS` beside that run's
artifacts, so a `graph.json` or a `solution.json` can be traced to the toolchain
that produced it.

**What this does not do.** The container tools do not stamp their own artifacts;
this stamps a target on request, and the review packet runs it. A stage 6 run
performed by hand leaves a `solution.json` with no manifest beside it unless
somebody runs this too. Package 4's scope did not admit those files and Package
5's does not either, so the gap is written down rather than closed.

Usage:
    python tools/verify_toolchain.py             # gate: images against the record
    python tools/verify_toolchain.py warmup      # and stamp out/warmup/
    python tools/verify_toolchain.py --record    # re-record, deliberately
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stage1_cells import TARGETS
import fetch_pdk

# Where the manifest lives inside every image, matching docker/Dockerfile's
# GDS_TOOL_VERSIONS.
MANIFEST = "/opt/gds-teardown/TOOL_VERSIONS"
RECORDED = os.path.join("tools", "TOOL_VERSIONS.recorded")
IMAGES = ("gds-teardown-sim:latest", "gds-teardown-eda:latest")


def read_manifest(image, timeout=120):
    """The manifest an image carries, or (None, why)."""
    try:
        done = subprocess.run(["docker", "run", "--rm", image, "cat", MANIFEST],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"could not run docker: {error}"
    if done.returncode != 0:
        said = (done.stderr or done.stdout or "").strip().splitlines()
        return None, (said[0] if said else f"exit {done.returncode}")
    text = done.stdout.replace("\r\n", "\n").strip()
    if not text:
        return None, (f"{image} carries no manifest at {MANIFEST}; it predates "
                      f"the pinned Dockerfile and needs rebuilding")
    return text, ""


def collect():
    """Every image's manifest, as the recorded file's own format."""
    sections, problems = [], []
    for image in IMAGES:
        text, why = read_manifest(image)
        if text is None:
            problems.append(f"{image}: {why}")
            continue
        sections.append(f"# {image}\n{text}")
    # The PDK is the half that IS pinned, and a provenance record that omits it
    # would be recording the floating half only.
    sections.append(f"# pdk\nlibrary   {fetch_pdk.REPO}@{fetch_pdk.COMMIT}\n"
                    f"corner    {fetch_pdk.CORNER}")
    return "\n\n".join(sections) + "\n", problems


def render(text):
    for line in text.strip().splitlines():
        print(f"    {line}")


def compare(live):
    """The live manifest against the recording. Returns the differing lines."""
    if not os.path.exists(RECORDED):
        return [f"{RECORDED} does not exist; run --record once and commit it"]
    with open(RECORDED, encoding="utf-8") as handle:
        recorded = handle.read()
    if recorded.replace("\r\n", "\n") == live:
        return []
    differences = []
    want = recorded.replace("\r\n", "\n").splitlines()
    got = live.splitlines()
    for number in range(max(len(want), len(got))):
        left = want[number] if number < len(want) else "(nothing)"
        right = got[number] if number < len(got) else "(nothing)"
        if left != right:
            differences.append(f"line {number + 1}: recorded {left!r}, "
                               f"the image says {right!r}")
    return differences


def stamp(target, live):
    out_dir = os.path.join("out", target)
    if not os.path.isdir(out_dir):
        return None
    path = os.path.join(out_dir, "TOOL_VERSIONS")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(live)
    return path


def run(target=None, record=False):
    live, problems = collect()
    if problems:
        print("the toolchain manifest could not be read:")
        for problem in problems:
            print(f"  {problem}")
        print("\n  This is an environment failure, not a drift. Bring the "
              "runtime up and\n  rebuild if needed; see the Environment "
              "section of CLAUDE.md.")
        print("RESULT: fail, nothing was compared")
        return 2

    print(f"the toolchain the images carry")
    render(live)

    if record:
        with open(RECORDED, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(live)
        print(f"\n  recorded to {RECORDED.replace(os.sep, '/')}")
        print("  Commit it. A recording that is not committed records nothing.")
        return 0

    differences = compare(live)
    if target:
        written = stamp(target, live)
        print(f"\n  stamped {written.replace(os.sep, '/')}" if written else
              f"\n  out/{target}/ does not exist yet, nothing stamped")

    print(f"\nagainst {RECORDED.replace(os.sep, '/')}")
    if differences:
        for difference in differences:
            print(f"  DRIFT  {difference}")
        print(f"\n  The toolchain moved. That is not automatically wrong -- "
              f"apt is not pinned\n  and was never claimed to be -- but it is "
              f"a change to what produced every\n  result in this repository, "
              f"and it has to be a decision. Re-run the gates,\n  then "
              f"`--record` and commit.")
        print("\nRESULT: fail")
        return 1
    print("  every line matches")
    print("\nRESULT: pass, the images carry the toolchain recorded here")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--record"]:
        sys.exit(run(record=True))
    if not args:
        sys.exit(run())
    if len(args) != 1 or args[0] not in TARGETS:
        sys.exit(f"usage: python tools/verify_toolchain.py "
                 f"[{' | '.join(TARGETS)}] [--record]")
    sys.exit(run(args[0]))
