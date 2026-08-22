# EDA tools for stages 2 through 6.
#
# The Python half of the pipeline runs natively, because gdstk and klayout ship
# wheels for Windows, Linux and macOS. The tools below do not, so they live in a
# container and the repository is mounted into it.
#
# Built in two targets on purpose. Stage 2's simulation gates need only Icarus,
# which is a small package; Yosys and z3 are an order of magnitude more to
# fetch and are not needed until stage 3. Splitting them means a flaky link
# cannot cost us the gates that are ready to run:
#
#   DOCKER_BUILDKIT=0 docker build --target sim -t gds-teardown-sim -f docker/Dockerfile docker/
#   DOCKER_BUILDKIT=0 docker build --target eda -t gds-teardown-eda -f docker/Dockerfile docker/
#
# `DOCKER_BUILDKIT=0` is required on this machine: under BuildKit apt-get cannot
# reach the network while the identical command works under `docker run`. That
# is `docs/problems.md` 1, worked around and not diagnosed. Do not reopen it.
#
# Deliberately not installed: graphviz. It is only useful for eyeballing netlist
# graphs while debugging, and it drags in icon themes, fonts and X libraries.
#
# --- What is pinned here, and what is not -----------------------------------
#
# **Pinned:** the base image, by digest. `debian:bookworm-slim` is a moving tag;
# the digest below is the image this pipeline was built and gated against, and a
# clean rebuild resolves to the same bytes rather than to whatever the tag points
# at that week. To move it deliberately: `docker pull debian:bookworm-slim` then
# `docker image inspect debian:bookworm-slim --format '{{index .RepoDigests 0}}'`,
# paste the result, rebuild, and re-record `tools/TOOL_VERSIONS.recorded`.
#
# **Not pinned, and recorded instead:** the apt packages. `yosys`, `z3` and
# `iverilog` are installed unversioned, so they are whatever the pinned base's
# suite ships. Pinning them by apt version would break the moment Debian moved a
# point release out of the archive, and building them from source would be hours
# and a second toolchain to maintain. So the versions are **recorded at build
# time into a manifest baked into the image**, and `tools/verify_toolchain.py`
# fails when the image's manifest and the copy checked into the repository
# disagree. **The gate catching the drift is the mechanism** -- the versions may
# move, but they cannot move silently.

FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS base

# apt fetches a hundred small files and any one of them can drop on a poor
# link. Without this a single failed transfer fails the whole build.
RUN printf '%s\n' \
    'Acquire::Retries "10";' \
    'Acquire::http::Timeout "60";' \
    'Acquire::https::Timeout "60";' \
    > /etc/apt/apt.conf.d/99-retries

# Where the manifest lives. Read out by tools/verify_toolchain.py, which writes
# it beside the artifacts of every run it stamps.
ENV GDS_TOOL_VERSIONS=/opt/gds-teardown/TOOL_VERSIONS
RUN mkdir -p /opt/gds-teardown

WORKDIR /work
CMD ["/bin/bash"]


# --- sim: stage 2 simulation gates ------------------------------------------
FROM base AS sim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends iverilog \
    && rm -rf /var/lib/apt/lists/*

RUN iverilog -V | head -1 && command -v vvp

# One line per tool, `name` then the tool's own version string. Sorted and
# stable, because a manifest that reorders itself between builds cannot be
# diffed against a recording. The base line records what this was actually
# built from, which is the one fact a rebuild could change without anybody
# editing this file.
RUN { \
      echo "base      debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241"; \
      echo "debian    $(cat /etc/debian_version)"; \
      echo "iverilog  $(iverilog -V 2>/dev/null | head -1)"; \
    } > "$GDS_TOOL_VERSIONS"


# --- eda: stage 3 onward ----------------------------------------------------
#   yosys         normalisation, SMT2 and CNF export
#   yosys-smtbmc  bounded model checking, ships with yosys
#   z3            the solver smtbmc drives
FROM sim AS eda

RUN apt-get update \
    && apt-get install --yes --no-install-recommends yosys z3 python3 \
    && rm -rf /var/lib/apt/lists/*

RUN yosys -V && z3 --version && command -v yosys-smtbmc

RUN { \
      echo "base      debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241"; \
      echo "debian    $(cat /etc/debian_version)"; \
      echo "iverilog  $(iverilog -V 2>/dev/null | head -1)"; \
      echo "yosys     $(yosys -V 2>/dev/null | head -1)"; \
      echo "z3        $(z3 --version 2>/dev/null | head -1)"; \
    } > "$GDS_TOOL_VERSIONS"
