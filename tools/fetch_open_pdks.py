"""The same standard cells, as open_pdks builds them, into a separate cache.

Stage 1 fingerprints cell geometry against `pdk/sky130_fd_sc_hd/`, which
`fetch_pdk.py` pulls from the upstream *library* repository. 22 of the puzzle's
1618 placements do not match by exact geometry there and fall back to a
structural key; three cell types differ on poly, licon1 or npc while the metal
is intact (`docs/01-cell-recognition.md`).

`docs/references.md` section 3 names the candidate cause. Every manufactured
sky130 flow consumes **`sky130A` as built by open_pdks**, which re-renders cell
layouts through Magic on the way through, and that is exactly the class of
difference that shows on poly, licon1 and npc while leaving metal alone. The
hypothesis is testable without opening a single puzzle file: fetch the cells as
open_pdks builds them and compare the two libraries to each other.

**This never writes into `pdk/sky130_fd_sc_hd/`.** Stage 1's current results are
gated at 230/230 against the warm up's DEF, and a fetch that overwrote the
library those numbers came from would make them unreproducible. The alternate
library lands in `pdk/open_pdks_sky130A/` -- a sibling directory, invisible to
`load_library`'s glob -- and is passed to stage 1 explicitly with `--library`.

**Where it comes from.** open_pdks is a build system, not a distribution; running
it needs Magic and hours. The built PDKs are published as release assets by
`ciel` (formerly `volare`), keyed by the open_pdks commit they were built from,
and served without authentication:

    https://fossi-foundation.github.io/ciel-releases/sky130/manifest.json
    https://fossi-foundation.github.io/ciel-releases/sky130/<commit>/manifest.json
    https://github.com/fossi-foundation/ciel-releases/releases/download/
        sky130-<commit>/sky130_fd_sc_hd.tar.zst

The asset holds one merged `sky130_fd_sc_hd.gds` of about 4 MB, and 458 MB of
liberty this pipeline does not want. A `.tar.zst` is not randomly seekable, so
the archive is **streamed and abandoned** at the member wanted -- roughly 60 MB
crosses the wire for the 4 MB kept, and nothing is written to disk but the GDS.
The liberty stays where it is: `fetch_pdk.py`'s per cell JSON is the functional
statement this pipeline reads, and nothing here touches it.

Usage:
    python tools/fetch_open_pdks.py
    python tools/fetch_open_pdks.py --verify
    python tools/fetch_open_pdks.py --versions      # what revisions are published
"""

import io
import json
import os
import sys
import tarfile
import urllib.error
import urllib.request

# The open_pdks revision this is pinned to, and why this one. `ciel` does not
# publish every open_pdks commit, so a pin has to name a published release.
# 8afc8346 is the release used to establish the difference; the previous
# published release, 823ec23c (2025-05-24), does not carry it, so the change
# entered open_pdks in that window.
#
# Pinned rather than "latest" for the same reason `fetch_pdk.py` pins: a clean
# clone has to reproduce the same fingerprints, and an unpinned fetch would
# silently change what the pipeline recognises.
OPEN_PDKS = "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"
LIBRARY = "sky130_fd_sc_hd"

INDEX = "https://fossi-foundation.github.io/ciel-releases/sky130/manifest.json"
RELEASE = ("https://github.com/fossi-foundation/ciel-releases/releases/"
           f"download/sky130-{OPEN_PDKS}/{LIBRARY}.tar.zst")
MEMBER = f"sky130A/libs.ref/{LIBRARY}/gds/{LIBRARY}.gds"

# A sibling of the standard cache, never the same directory. `pdk/` as a whole
# is already gitignored, and a new top level directory would leave the working
# tree dirty for a generated artifact; stage 1's `load_library` globs
# `pdk/sky130_fd_sc_hd/*.gds` specifically, so nothing here is visible to it
# unless it is asked for by `--library`.
DEST = os.path.join("pdk", "open_pdks_sky130A")
GDS = os.path.join(DEST, f"{LIBRARY}.gds")
STAMP = os.path.join(DEST, "PROVENANCE")


def get(url, timeout=120):
    request = urllib.request.Request(url,
                                     headers={"User-Agent": "gds-teardown"})
    return urllib.request.urlopen(request, timeout=timeout)


def versions():
    """Which open_pdks revisions have a published build."""
    with get(INDEX) as response:
        listing = json.loads(response.read().decode("utf-8"))
    rows = listing if isinstance(listing, list) else listing.get("versions", [])
    print(f"{len(rows)} published sky130 builds, newest first")
    for row in rows[:12]:
        commit = row.get("version", "?")
        mark = "   <- pinned here" if commit == OPEN_PDKS else ""
        print(f"  {commit}  {row.get('date', '')}{mark}")
    if not any(row.get("version") == OPEN_PDKS for row in rows):
        print(f"\n  {OPEN_PDKS[:12]} is NOT in this listing, which means the "
              f"pin no longer\n  resolves. Pick one above and re-pin "
              f"deliberately.")
        return 1
    return 0


def fetch():
    """Stream the asset and stop at the one member wanted."""
    os.makedirs(DEST, exist_ok=True)
    if os.path.exists(GDS) and os.path.getsize(GDS) > 0:
        print(f"{GDS} is already present, {os.path.getsize(GDS) / 1e6:.2f} MB")
        return 0

    # 3.14's stdlib zstd. Nothing here needs a third party package, which
    # matters for a tool whose whole point is a reproducible environment -- but
    # it does mean this one tool needs 3.14, where the rest of the pipeline runs
    # on 3.12 as well. Said plainly rather than left as a bare ImportError
    # three frames down.
    try:
        from compression import zstd                         # noqa: PLC0415
    except ImportError:
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        sys.exit(
            f"this tool needs Python 3.14 or later for the stdlib zstd "
            f"decoder, and this is {version}.\n"
            f"  Nothing else in the pipeline does -- only the open_pdks "
            f"comparison, which is optional.\n"
            f"  Either run it under 3.14, or skip it: tools/fetch_pdk.py "
            f"alone is enough for every stage.")

    print(f"streaming {RELEASE}")
    print(f"  for {MEMBER}")
    read = 0
    try:
        with get(RELEASE) as response:
            counted = _Counted(response)
            with zstd.ZstdFile(counted) as raw:
                # `r|` is the streaming mode: no seeking, members in order,
                # and we abandon the connection at the one we want.
                with tarfile.open(fileobj=raw, mode="r|") as archive:
                    for member in archive:
                        if member.name != MEMBER:
                            continue
                        handle = archive.extractfile(member)
                        if handle is None:
                            sys.exit(f"{MEMBER} is not a regular file")
                        with open(GDS, "wb") as out:
                            out.write(handle.read())
                        read = counted.total
                        break
                    else:
                        sys.exit(f"{MEMBER} was not in the archive; the layout "
                                 f"of this release differs and the member path "
                                 f"needs re-checking")
    except urllib.error.URLError as error:
        sys.exit(f"could not fetch: {error}")

    with open(STAMP, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"open_pdks {OPEN_PDKS}\n"
                     f"library   {LIBRARY}\n"
                     f"source    {RELEASE}\n"
                     f"member    {MEMBER}\n")
    print(f"  wrote {GDS}, {os.path.getsize(GDS) / 1e6:.2f} MB "
          f"after {read / 1e6:.0f} MB over the wire")
    print(f"  wrote {STAMP}")
    print(f"\n  pdk/ is untouched. Stage 1 reads this with "
          f"--library {DEST.replace(os.sep, '/')}")
    return 0


class _Counted:
    """A read-only wrapper that counts bytes, so the report is measured."""

    def __init__(self, stream):
        self.stream = stream
        self.total = 0

    def read(self, size=-1):
        chunk = self.stream.read(size)
        self.total += len(chunk)
        return chunk

    def readable(self):
        return True


def verify():
    if not os.path.exists(GDS):
        print(f"{GDS} is missing; run tools/fetch_open_pdks.py")
        return 1
    import gdstk                                             # noqa: PLC0415
    cells = gdstk.read_gds(GDS).cells
    flat = [c for c in cells if not c.references]
    print(f"{GDS.replace(os.sep, '/')}, "
          f"{os.path.getsize(GDS) / 1e6:.2f} MB")
    print(f"  {len(cells)} cells, {len(flat)} of them flat")
    print(f"  pinned to open_pdks {OPEN_PDKS[:12]}")
    if os.path.exists(STAMP):
        with open(STAMP, encoding="utf-8") as handle:
            for line in handle:
                print(f"  {line.rstrip()}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--verify"]:
        sys.exit(verify())
    if args == ["--versions"]:
        sys.exit(versions())
    if args:
        sys.exit("usage: python tools/fetch_open_pdks.py "
                 "[--verify | --versions]")
    sys.exit(fetch())
