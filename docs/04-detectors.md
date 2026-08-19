# Stage 4, detectors

Naming the blocks a netlist is built from, and reporting honestly what is left
over.

Not started as a whole. This document grows a section per step; the first is
below.

## Step 1, registers

`tools/stage4_registers.py`. Output `out/<target>/registers.json`.

Everything later needs this. "These eight flops are a counter" cannot be said
before "these eight flops are one thing", and a flat netlist does not say which
flops belong together: the puzzle's 92 sit in no declared order, under no shared
name, on sixteen different clock nets.

### Three criteria, measured rather than argued

The answer is known for every circuit in the corpus, because the generator
declares it. `--compare` scores all three against that answer key:

| Criterion | Exact |
|---|---|
| **control signature** | **116/126** |
| colour refinement, to a fixed point | 96/126 |
| control signature + connected components | 74/126 |

The control signature is the clock root, the reset root and its level, the set
root and its level, and the hold net — what a register is written and cleared
by, which its bits share by definition.

The two alternatives **fail in mirror image**, and that is the useful part.
Connected components of the flop dependency graph shatters a *plain* register,
whose bits do not depend on one another at all. Colour refinement shatters a
*shift* register, whose chain hands every bit a distinct colour once its
predecessor has one. Neither is a tuning problem: one criterion needs the bits
to interact and the other needs them not to.

So the control signature is committed, and refinement is reported **beside** it
as candidate splits rather than applied. That is what `docs/solver-pipeline.md`
asks for — "report overlapping candidates rather than forcing a disjoint
partition" — and it is the honest shape of the result.

### What it cannot do

It cannot see a boundary that no control signal marks. All 10 of its misses are
circuits built from several registers sharing a clock, a reset and a hold:
every `scale_datapath`, and the composed shift-register-into-accumulator.

One of the terms is weaker than the others. The hold net comes from stage 3's
structural search, which is a measured lower bound — four ways of hiding a hold
are recorded in `verify_corpus.py` — so **a hold stage 3 misses is a split
missed here.** In `scale_datapath` that is exactly what happens: the held output
register would have been separated by its hold net, and the mapper factored the
mux away, so it is not.

### The warm up and the puzzle

```
warm up   16 flops -> 1 register of 16 bits
          clock clk, reset rst_n low, holds on en
          reads A, B, en; drives S
```

Which is the whole circuit: a 16-bit accumulator behind a hold.

```
puzzle    92 flops -> 4 registers

  R0  72 bits  clk, reset rst_n low          reads I, enable
                                             feeds R1 R2 R3, drives O success
  R1  12 bits  clk, reset rst_n low,         reads I, enable
               holds on n00189               feeds R0
  R2   4 bits  clk, no reset                 feeds R0 R3, drives O
  R3   4 bits  clk, set rst_n low            reads I, enable
                                             feeds R0, drives O
```

R2 and R3 are the flops stage 1 counted from geometry: 4 `dfxtp` with no
asynchronous input at all, and 4 `dfstp` that come out of reset holding one
rather than zero. Both drive `O`.

**R0 is not resolved.** 72 bits under one control signature is a blob, and three
rounds of refinement want to split it into pieces of 23, 22, 8, 4, 4, 4, 2, 2
and three singletons. Those are reported as candidates and not applied, because
refinement scores worse overall. This is the part of the puzzle a person has to
read, and saying so is the point of the residue report rather than an admission
hidden in it.

### Verification

Scored on the corpus, both mappings of every circuit, `--score`. 116 of 126
exact, of which 34 are on circuits held out from development.

The declared partition is itself checked: `verify_corpus.py` confirms the widths
a generator declares add up to the flip flops stage 3 found. A register partition
that did not account for every flop would make this score meaningless in a way
nothing else would notice.
