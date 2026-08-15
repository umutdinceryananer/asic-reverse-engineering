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
#   docker build --target sim -t gds-teardown-sim -f docker/Dockerfile docker/
#   docker build --target eda -t gds-teardown-eda -f docker/Dockerfile docker/
#
# Deliberately not installed: graphviz. It is only useful for eyeballing netlist
# graphs while debugging, and it drags in icon themes, fonts and X libraries.

FROM debian:bookworm-slim AS base

# apt fetches a hundred small files and any one of them can drop on a poor
# link. Without this a single failed transfer fails the whole build.
RUN printf '%s\n' \
    'Acquire::Retries "10";' \
    'Acquire::http::Timeout "60";' \
    'Acquire::https::Timeout "60";' \
    > /etc/apt/apt.conf.d/99-retries

WORKDIR /work
CMD ["/bin/bash"]


# --- sim: stage 2 simulation gates ------------------------------------------
FROM base AS sim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends iverilog \
    && rm -rf /var/lib/apt/lists/*

RUN iverilog -V | head -1 && command -v vvp


# --- eda: stage 3 onward ----------------------------------------------------
#   yosys         normalisation, SMT2 and CNF export
#   yosys-smtbmc  bounded model checking, ships with yosys
#   z3            the solver smtbmc drives
FROM sim AS eda

RUN apt-get update \
    && apt-get install --yes --no-install-recommends yosys z3 python3 \
    && rm -rf /var/lib/apt/lists/*

RUN yosys -V && z3 --version && command -v yosys-smtbmc
