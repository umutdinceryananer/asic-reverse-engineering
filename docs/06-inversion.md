# Stage 6, inversion

Stages 1 to 5 answer *what is this*. Stage 6 asks *what do I type into it*, and
that is a different kind of question. The design is sequential, so it is not one
SAT call: it is bounded model checking. Unroll the transition relation to depth
K, assert the output high at cycle K, and ask a solver for the inputs.

Everything here was built and gated on `warmup`, whose answer is known. The
puzzle run is the author's, and nothing in this document was measured on it.

## What was built

| Tool | What it does |
|---|---|
| `tools/common/celllib.py` | the PDK's cells as behaviour, generated from liberty |
| `tools/verify_equiv.py` | the recovered netlist proven equal to `01_netlist.v` |
| `tools/stage6_invert.py` | the transition relation, unrolled and solved |
| `tools/sim/replay.py` | the trace put back through stage 2's netlist |

## First, prove the netlist is the right netlist

Stage 6 inverts `graph.json`. If `graph.json` is wrong, stage 6 solves the wrong
circuit and says so confidently. Three checks already stood behind it — the DEF
for placement, the simulation for behaviour, a second extractor for connectivity
— and none of them says what is needed here:

    simulation says   these two agree on the vectors I ran
    a miter says      these two agree on every input sequence, and here is a
                      proof

So `tools/verify_equiv.py` proves the recovered netlist sequentially equivalent
to `puzzle/warmup/01_netlist.v`, which is the gate level netlist the warm up was
actually built from. That file had been in the repository, unread, since the
first commit; it is `docs/problems.md` 34, and this is the first thing that
opens it.

```
$ python tools/verify_equiv.py warmup
  ports agree: A, B, S, clk, en, rst_n
  18 cell types: 16 with a liberty function, 2 physical only
yosys: 1.5s, 153 correspondence points
  every one proven, including the design's output
RESULT: pass
```

Both designs reduce to 225 cells with an identical `$and`/`$or`/`$not`/`$mux`/
`$sdff` breakdown, which is its own small finding: place and route did not
change the logic, and stage 1 to 3 recovered it exactly.

**Yosys cannot do this with blackboxes.** Two netlists of opaque boxes are
equivalent exactly when they are wired identically, which is a question about
names, and the net names here have nothing in common — `\a_reg[0]` against
`n25`. So `common/celllib.py` emits each cell's behaviour from liberty, through
the expression parser `verify_functions.py` gates against the PDK's own
behavioural models. Deliberately *not* the PDK's `.v` models, which stage 2's
simulation uses: the proof and the check on the proof must not rest on one file.

Two settings decide whether this proves anything at all, and both were found by
watching it fail:

* **`async2sync`.** The flops carry an asynchronous reset, the SAT engine has no
  model for `$adff`, and without this every proof step warns and the run fails
  for a reason with nothing to do with the netlists.
* **`proc; flatten; opt_clean` rather than `prep`.** `prep` optimises, and two
  designs optimised independently stop being structurally comparable.
  `equiv_struct` then proposes nothing, `equiv_induct` grinds through five
  induction steps, and the result is 0 of 153 proven. Measured both ways.

`equiv_struct -icells` only *proposes* correspondences from structure; every one
is then proven by SAT, and `equiv_status -assert` fails unless all of them are.
A wrong proposal is a failure, not a shortcut.

**Demonstrated failing.** One `nand2_2` in `graph.v` swapped for `nor2_2` — same
pins, different function, nothing else changed:

```
$ python tools/verify_equiv.py warmup --netlist out/warmup/graph_broken.v
  126 could not be proven
    ERROR: Found 1 unproven $equiv cells in 'equiv_status -assert'.
RESULT: fail                                                     [exit 1]
```

## Two routes to the transition relation, and why not `yosys-smtbmc`

`docs/solver-pipeline.md` suggests `yosys-smtbmc` against an SMT2 export. That
route works and was not taken. Exporting through Yosys means resolving the
sky130 cells a second time, in a second place, with a second set of assumptions
— and then believing the answer, because nothing in this repository checks a
Yosys SMT2 export.

The other route was already paid for. `graph.json` carries `cell_functions` for
every cell, which is why `docs/solver-pipeline.md` insists cells stop being
blackboxes at stage 3; `common/boolexpr` parses those expressions with the
parser `verify_functions.py` gates over 850 truth tables; and `flipflops`
carries clock, data, reset and set per flop, all of which
`stage3_crosscheck.py` derives a second time, forwards, from stage 2's netlist.
Building the relation directly out of `graph.json` rests on what already has
gates under it.

## The cycle model

    S(t)      the flops as they stand during cycle t, asynchronous reset and
              set already applied
    r(t)      reset active, read off the net at each flop's reset pin
    comb(t)   every combinational net, from the inputs at t and S(t)
    S(t+1)    the reset or set value if r(t) or r(t+1), otherwise D(t)

`r(t) or r(t+1)` is what makes an asynchronous reset asynchronous: a level held
across the edge clears the flop from either side of it. Set dominates clear,
matching how liberty orders the two on the cells carrying both.

**A cycle is an edge, so the clock is not a signal.** Clock tree cells are
dropped and the clock port is implicit. This is where the one real defect of
this stage lived: `graph.json`'s `clock_nets` names the nets *at the flop pins*,
and the warm up's tree is `clk -> n8 -> {n18, n41}`. n8 is in neither
`clock_nets` nor `clock_roots`, so the first version modelled it as ordinary
logic and made the clock a variable the solver had to choose. The tree is walked
back from the flops now. `docs/problems.md` 39.

**Two designs this model cannot describe, and it says so rather than solving
something else.** A clock net read by anything but a flop's clock pin — a gated
or sampled clock — has no value in a model where a cycle is an edge. And a reset
computed from a flop makes `r(t) or r(t+1)` a definition that refers to itself.
Both are checked before any solving happens and both exit 2. Neither occurs in
the warm up or, from what stage 3 found, in the puzzle.

## The initial state, and why it is not left free

`rst_n` is a primary input the solver controls like any other. Nothing here
asserts a reset preamble, and the measurement says why that matters: **at every
depth from 0 to 7, the warm up's solver returns a trace that works.** Each of
them is a real solution to the question asked, and each of them is useless,
because each depends on the flops starting in a state the solver picked. Nothing
powers up in a state anyone chose.

So every candidate is put to the opposite question — *is there a starting state
these same inputs fail from* — and any such state is pinned as another copy of
the design, sharing the input variables, and the search runs again. The loop
ends when no such state exists. It is counterexample-guided, it converges in one
to three rounds on everything measured, and what it produces is a trace good
from *every* power-up state.

```
  depth   7  1 start state(s)       64 KiB    1.66s  trace found
          a start state defeats it; pinning it and solving again (round 1)
  depth   7  2 start state(s)      126 KiB    1.91s  no trace
  depth   8  1 start state(s)       72 KiB    1.84s  trace found
          a start state defeats it; pinning it and solving again (round 1)
  depth   8  2 start state(s)      142 KiB    1.98s  trace found
          no start state defeats it: the trace holds from every one (1.79s)
```

Depth 8 is the first that survives, and the trace **uses no reset at all** —
`rst_n` is high in all nine cycles. It does not need one: eight shifts overwrite
both registers completely. A tool with a reset preamble baked in would have
spent a cycle on one and reported depth 9.

## The answer, which nothing told it

```
  cycle       A       B      en   rst_n
      0       1       1       1       1
      1       1       1       1       1
      2       1       1       1       1
      3       1       1       1       1
      4       1       0       1       1
      5       1       1       1       1
      6       0       0       1       1
      7       0       0       1       1
      8       0       0       0       1  <- S
```

Most significant bit first: `A = 11111100` = 252, `B = 11110100` = 244, and
252 + 244 = 496. `en` high for the eight shifts and low while `S` is read, which
is what `tb_warmup.v` does and what the solver arrived at on its own. Nothing
about the design's function, its operand width, or its comparison constant was
given to it.

## The gate on the answer

`tools/sim/replay.py` replays the trace through **stage 2's** netlist —
`out/warmup/netlist.v`, not stage 3's `graph.v` — under the PDK's own Verilog
models, and asserts the property.

The choice of netlist is the whole point. Stage 6 solves the graph. Replaying
the graph's own trace against the graph would check the solver and nothing else.

```
$ python tools/sim/replay.py warmup
cycle 0   S=x   model says S=0
cycle 1   S=x   model says S=0
cycle 2   S=0   model says S=0
...
cycle 8   S=1   model says S=1
  the property holds: S is 1 at cycle 8
RESULT: pass
```

`S` is `x` for two cycles because simulation starts every flop unknown and the
model started somewhere definite. That is why only the property cycle is
asserted; the rest are printed beside the model's prediction and reported. A
model error showing only on a cycle the property does not name would not be
caught here, and that is stated in the review packet's unverified list rather
than papered over.

### Demonstrated failing, twice

**A tampered trace.** One bit, `A` at cycle 0, which makes the operand 124
instead of 252:

```
cycle 8   S=0   model says S=1
  S is 0 at cycle 8 and the model said 1
RESULT: fail                                                     [exit 1]
```

**A tampered model, which is what this gate exists for.** One entry of
`cell_functions` in a copy of `graph.json` — `xnor2_2` written as an xor,
3 instances affected — and then the solver run on the copy:

```
$ python tools/stage6_invert.py warmup --graph out/warmup_tampered/graph.json
      8       0       0       0       1  <- S
RESULT: pass, a trace was found                                  [exit 0]

$ python tools/sim/replay.py warmup --solution out/warmup_tampered/solution.json
cycle 8   S=0   model says S=1
RESULT: fail, the trace does not reproduce.                      [exit 1]
```

The solver was confident, self-consistent and wrong. Nothing else in the
pipeline would have noticed: stage 6 reads `cell_functions` to build its model,
so a defect there is invisible to every check that reads the same field.
Simulation reads a different file by a different author, and the two only agree
when the model is right.

## Scaling

Measured on this machine, one `docker run` per solver query. The docker round
trip is **1.1 to 1.5 s** and dominates the small cases, so the numbers below are
mostly transport, not solving. Every figure is the tool's own recorded timing,
in each `solution.json` under `solver.calls`.

The corpus circuit is `scale_datapath`, which exists precisely to bracket the
target's size, and its property is `result[0]` high.

| Design | flops | cells | depth | wall | rounds | largest SMT2 |
|---|---|---|---|---|---|---|
| warmup | 16 | 79 | 8 (the answer) | 8.5 s | 2 | 142 KiB |
| warmup | 16 | 79 | 10 | 11.8 s | 3 | 261 KiB |
| warmup | 16 | 79 | 12 | 9.4 s | 2 | 208 KiB |
| warmup | 16 | 79 | 16 | 4.7 s | 1 | 138 KiB |
| warmup | 16 | 79 | 20 | 4.8 s | 1 | 172 KiB |
| warmup | 16 | 79 | 40 | 5.2 s | 1 | 339 KiB |
| warmup | 16 | 79 | 80 | 5.2 s | 1 | 674 KiB |
| warmup | 16 | 79 | **121** | **5.1 s** | 1 | 1.0 MiB |
| scale16 | 90 | 280 | 4 | 12.3 s | 3 | 448 KiB |
| scale16 | 90 | 280 | 16 | 8.3 s | 2 | 1.0 MiB |
| scale16 | 90 | 280 | 32 | 5.8 s | 1 | 1.0 MiB |
| scale16 | 90 | 280 | **121** | **13.9 s** | 1 | 3.8 MiB |
| scale32 | 178 | 561 | 4 | 5.3 s | 1 | 305 KiB |
| scale64 | 354 | 1136 | 4 | 14.1 s | 3 | 1.8 MiB |
| scale64 | 354 | 1136 | 8 | 23.4 s | 4 | 4.4 MiB |
| scale64 | 354 | 1136 | 32 | 17.9 s | 2 | 8.4 MiB |

**Solve time is close to flat in depth.** The warm up at depth 121 costs what it
costs at depth 16. The SMT2 grows linearly — it is one copy of the netlist per
cycle — but z3 does not appear to care within this range. What actually drives
the wall clock is the number of robustness rounds, and each round is one more
whole copy of the unrolled design.

`scale16` is the row to read for the puzzle: 90 flops against the puzzle's 92,
one serial input like the puzzle's `I`, and 121 cycles is the length of an
attempt in `example_inputs.vcd`. It solves in **14 seconds**. The puzzle has
2.6× the cells, so on this evidence the unrolling itself is not the problem.

### The expensive case, which is the honest negative

The interesting number is not the one where a trace exists. `scale_datapath`'s
`done` output is `(state == 3) && (tag != 0)`, and state reaches 3 only after a
free-running counter expires — 256 cycles at w16, and 2^56 at w64. It is not
reachable by bounded model checking at any depth anyone will run.

```
$ python tools/stage6_invert.py scale16 --property done --start 32 --depth 32
  depth  32  2 start state(s)     2044 KiB    5.80s  no trace
  no input sequence drives done high within 33 cycles
  DEPTH REACHED: 32. A negative without its depth is not a result; this one
  has been searched to 32 and no further.
RESULT: fail                                                     [exit 1]
```

That is the failure mode `docs/solver-pipeline.md` warns about, and the reason
every negative here carries its depth. An unreachable property and a property
that needs one more cycle are the same output otherwise.

## What remains, for the run the author performs

1. **A property.** `success` is a registered output whose condition is a
   function of 57 bits of R0 and no primary input (`docs/04-detectors.md`).
   `--property success` is the default when the port exists, so this needs no
   change.
2. **A depth.** `example_inputs.vcd` holds two attempts of 121 bits each, 312
   rising edges. Start above 121 rather than iterating from 0: iterative
   deepening costs one round trip per depth and the answer is not shallow.
   `--start 121 --depth 160` is the shape of it.
3. **The two refusals.** Stage 3 found the puzzle's clock tree to be sixteen
   `clkbuf_8` branches from one root, and `rst_n` to be both reset and set root.
   Neither should trip the checks, but if one does the message says which flop
   and why, and that is a finding rather than an obstacle.
4. **`sim/replay.py puzzle` before believing anything.** The 4 `dfstp` cells
   mean part of the design leaves reset holding a non-zero value; the model
   handles set the same way it handles reset, and the replay is what confirms
   that on the real target.
5. **Stage 7.** Not started. Turning a trace into the string the puzzle wants is
   its own step.

## What this stage does not establish

* The reproduction gate asserts the property cycle only. See above.
* The transition relation and `common/celllib.py` read liberty separately, but
  both are *this repository's* reading of the same JSON. `verify_functions.py`
  checking that reading against the PDK's behavioural models is what keeps
  either honest, and its own limits are in `docs/04-detectors.md`.
* The robustness loop stops after 8 rounds and moves to a deeper unrolling. On
  everything measured it converged in 1 to 4, but a design needing more would be
  reported as "no trace at this depth", which is true and incomplete.
* Nothing here has run on the puzzle.
