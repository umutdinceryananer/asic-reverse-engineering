# Stage 3, normalisation

Netlist to `out/<target>/graph.json`: the same circuit, with the structural
facts later stages need attached to it.

Stage 2 produced something correct and unreadable — 738 boxes and 723 wires
whose names mean nothing. This stage does not try to understand it. It labels
what can be established without interpretation, and refuses anything that would
need a guess.

## Reading the netlist

Yosys, in the `eda` container. It is the standard tool for this, its `check`
gives an independent opinion of the netlist, and stages 4 and 6 need the same
design in the same tool for the SMT2 and CNF exports.

Cell interfaces are supplied as a generated blackbox library rather than by
reading the PDK's behavioural models, so this stage does not depend on those
models parsing under a second tool. `hierarchy -check` then confirms every
instantiated module exists with matching ports, which is a free cross check on
stage 2's emitter.

```
warm up:  0 problems, 79 cells, 84 wires
puzzle:   0 problems, 738 cells, 716 wires
```

Blackboxes are enough here and **not enough after here**: a graph can be walked
without knowing what a cell computes, an SMT2 export cannot be written. The
`function` expression of every cell is therefore carried into `graph.json`.

## Where the roles come from

The stage has to say which net is a clock, which is a reset, which carries data.
There are three candidate sources and they are not equally good.

| Source | What it is | Verdict |
|---|---|---|
| Cell and pin names | `CLK`, `RESET_B`, `dfrtp` | **not used to decide.** Six cells in this library carry both `RESET_B` and `SET_B`; no reading of the name survives that. The pin name and the cell name are also one convention stated twice, not two opinions |
| LEF `USE CLOCK` | a routing directive | sound, as it turns out, but a statement about how to treat a pin rather than about what it does |
| **Liberty** | `clocked_on`, `next_state`, `clear`, `preset` | **the authority.** Functional statements, with polarity |

```
dfrtp_2:  clocked_on=CLK  next_state=D  clear=!RESET_B
dfstp_2:  clocked_on=CLK  next_state=D  preset=!SET_B
dfxtp_2:  clocked_on=CLK  next_state=D
```

The two weaker sources are still read, as cross checks that report rather than
decide. Both agree with liberty on both targets, and `USE CLOCK` agrees with
liberty's `clock` on all 429 cells in the library — including
`lpflow_inputisolatch_1`, which marks `SLEEP_B` and looked like a counterexample
until liberty independently gave that latch `clocked_on : SLEEP_B`.

A sequential cell whose liberty entry does not reduce to one clock, one data pin
and one output stops the run. Adding a rule is cheap; guessing is not.

## What is derived

**Clock nets**, by fanout into the pin liberty names as the clock.

**Reset and set nets**, from `clear` and `preset`, with the active level.

**A state element inventory**: clock, data source, output, reset, set per
instance.

**Signal roots**, by walking back through transparent cells. Which cells are
transparent is read from liberty's function expression and never from the cell's
name: a cell is transparent when its single output is its single input, possibly
inverted. That catches `clkbuf`, `inv`, `buf` and `clkinv` without naming any of
them, and correctly excludes `diode`, which drives no output, and `conb_1`,
whose output is a constant rather than an input. The walk carries the inversion
parity, because a clock arriving through an odd number of inverters is a falling
edge clock and a reset through one is active high.

Reading the level took a correction. This library writes a combinational output
as `function : "(!A)"`, parenthesised, and the sequential fields bare, so a test
of the expression's first character for `!` gets `clear` right on all 107
sequential fields and every one of the library's 21 inverters wrong. The walk
still found the correct root — it goes through a transparent cell either way —
and only the parity was lost, silently. `liberty.unwrap` strips enclosing
parentheses before the level is read.

This exists for one reason. **Bits of one register do not share a clock net.**
The puzzle's 92 flip flops sit on 16 `clkbuf_8` branches, so grouping them by the
net their `CLK` pin reaches splits every register into sixteen pieces. They share
a clock *root*, and the graph now carries flops grouped by root for clock, reset
and set alike.

**A hold**, where the structure shows one. No sequential cell in this library
carries an enable pin, so a held register can be built as a mux in front of `D`
with the flop's own `Q` on one leg. Where that is what stands in front of `D`, it
is recorded: which mux, which net selects it, which leg is the hold.

This is a **lower bound and is labelled as one**, because the corpus contains
circuits whose enable we declared ourselves and four separate things happen to
it. In a plain register the mux survives. In a counter, `if (en) q <= q + 1` is
folded into the carry chain — `D[0] = q[0] ^ en`, `D[1] = q[1] ^ (q[0] & en)` —
and no mux exists anywhere. In a register with a *synchronous* reset the mux
survives but the reset's `nor2b` sits between it and `D`, and this search looks
one cell back. And in the scale family the mux is factored away entirely: `D =
en ? (acc ^ lfsr) : outr` becomes one `a21oi` with `Q` arriving two cells back.
Six of thirty declared enables are found.

That fourth case is the general one and the first three are the exceptions. A
plain register keeps its mux only because the data leg is a *port*; once that
leg is computed, the mapper folds the select into the logic that computes it.
Making the search cleverer is the wrong move: it buys a fifth shape and hides
the sixth. Whether a register holds is a question about behaviour — is there an
input assignment under which `D` equals `Q` — and it belongs to stage 4, which
has a solver.

**Constant nets**, from cell outputs whose liberty function is the literal `1` or
`0`. Read from the function rather than from the cell's name, so a differently
named constant generator is still caught.

**Primary inputs and outputs**, from the module ports.

**Combinational cone membership per net.** A cone root is where combinational
logic ends: a flop's data or asynchronous input, or a primary output. Walking
back from each root until a flop output, a primary input or a constant stops it
gives the nets that root depends on within one cycle.

## Results

| | warm up | puzzle |
|---|---|---|
| Cells | 79 | 738 |
| Nets | 84 | 723 |
| Ports (names) | 6 | 6 |
| Clock nets | 2 | 16 |
| Clock net drivers | `clkbuf_16` x2 | `clkbuf_8` x16 |
| Flops per clock branch | 8, 8 | twelve of 6, four of 5 |
| **Clock roots** | **1, `clk`, 16 flops** | **1, `clk`, 92 flops** |
| Flops on an inverting clock path | 0 | 0 |
| Transparent cells | 3 | 58: 32 `clkbuf`, 25 `inv`, 1 `buf` |
| State elements | 16 `dfrtp_2` | 84 `dfrtp_2`, 4 `dfstp_2`, 4 `dfxtp_2` |
| Holds found structurally | 16, all on `en` | 12, all on one net |
| Reset nets | 1, `rst_n`, 16 pins | 1, `rst_n`, 88 pins |
| Set nets | 0 | 1, `rst_n`, 88 pins |
| Constant nets | 0 | 12, six 1 and six 0 |
| Cone roots | 33 | 189 |
| `graph.json` | 0.1 MB | 0.7 MB |

Two of those rows are worth reading twice.

The clock branches account for every state element exactly: 8 + 8 = 16, and
twelve branches of six plus four of five = 92. Nothing is on an unclocked
element and nothing is clocked twice. And every one of those branches resolves
to the same root, two buffer hops back, named `clk` — which is the fact stage 4
needs and the clock *net* count actively obscures.

`rst_n` appears as **both** the reset net and the set net, because it clears 84
flops and presets 4. Stage 1 counted those 4 `dfstp_2` from geometry; stage 3
reaches the same number from liberty's `preset` attribute, by an unrelated route.
The consequence — that the design does not leave reset holding all zeros — is
now a derived property of the graph rather than a note someone made by hand.

The 189 cone roots decompose as 92 data inputs, 88 asynchronous inputs and 9
primary outputs, which is the whole boundary and nothing else.

## Verification

The round trip the spec asks for. `graph.json` is written back out as Verilog —
from the graph alone, never from stage 2's file, or the test would only prove
that a copy is a copy — and has to pass stage 2's own simulation unchanged.

```
warm up: 65536 operand pairs, 15 successes, 0 mismatches   RESULT: pass
puzzle:  312 cycles of the VCD, 0 mismatches               RESULT: pass
```

Both gates pass on the regenerated netlist.

## Not done, and worth knowing

The `eda` image is heavy for what it delivers. Debian's `yosys` depends on
`xdot`, which pulls in GTK, Pango and systemd: 170 packages and 93 MB to obtain
Yosys, z3 and yosys-smtbmc. On a poor link that is a repeated risk — the build
here failed once outright on DNS and later retried five individual packages. A
single static distribution of the tools would be one download instead of 170.
Not changed, because the image now exists and works; recorded because the next
person to build it on a bad connection will care.
