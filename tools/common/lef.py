"""Pin directions from the PDK's LEF abstract views.

The layout says which shapes are connected. It does not say which pin drives a
net and which one listens, and Verilog needs that distinction to be written
down. Guessing from names would mostly work in this library -- `X`, `Y` and `Q`
are outputs, `A`, `B` and `CLK` are inputs -- but "mostly" is how a netlist ends
up structurally plausible and functionally wrong, so the directions are read
from the LEF instead.

The subset of LEF that matters here is small:

    MACRO <cell>
      SIZE <w> BY <h> ;
      PIN <name>
        DIRECTION INPUT | OUTPUT | INOUT ;
        USE SIGNAL | POWER | GROUND ;
      END <name>
    END <cell>
"""

import glob
import os
import re

MACRO = re.compile(r"^\s*MACRO\s+(\S+)", re.M)
PIN = re.compile(r"^\s*PIN\s+(\S+)(.*?)^\s*END\s+\1\s*$", re.M | re.S)
DIRECTION = re.compile(r"^\s*DIRECTION\s+(\w+)\s*;", re.M)
USE = re.compile(r"^\s*USE\s+(\w+)\s*;", re.M)
SIZE = re.compile(r"^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", re.M)


def parse_macro(text):
    """One LEF file holds one macro here. Returns (name, info) or None."""
    macro = MACRO.search(text)
    if not macro:
        return None

    pins = {}
    for match in PIN.finditer(text):
        name, body = match.group(1), match.group(2)
        direction = DIRECTION.search(body)
        use = USE.search(body)
        pins[name] = {
            "direction": direction.group(1).lower() if direction else "unknown",
            "use": use.group(1).lower() if use else "signal",
        }

    size = SIZE.search(text)
    return macro.group(1), {
        "pins": pins,
        "size": (float(size.group(1)), float(size.group(2))) if size else None,
    }


def load(directory):
    """Cell name -> {'pins': {pin: {direction, use}}, 'size': (w, h)}."""
    library = {}
    for path in sorted(glob.glob(os.path.join(directory, "*.lef"))):
        if path.endswith(".magic.lef"):
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            parsed = parse_macro(handle.read())
        if parsed:
            library[parsed[0]] = parsed[1]
    return library


# Everything a netlist has to carry. The exclusion is by supply rather than by
# inclusion of USE SIGNAL, because 69 pins in this library are USE CLOCK: taking
# only the signal ones drops every flip-flop clock, and it does so silently.
SUPPLY_USES = {"power", "ground"}


def functional_pins(entry):
    """Pin name -> direction, supplies dropped, clocks kept."""
    return {name: info["direction"] for name, info in entry["pins"].items()
            if info["use"] not in SUPPLY_USES}
