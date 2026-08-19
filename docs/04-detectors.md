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

## Step 2, one cone, composed

`tools/stage4_cone.py`. Output `out/<target>/cone.json`.

The roadmap's instruction for the analysis week is *"read `success` backwards to
find what gates the success condition"*. Backwards from `success` the netlist is
738 anonymous cells. This turns the part that matters into a listing over
register bits and ports, in dependency order, each line showing what the cell
computes rather than what it is called.

Nothing here interprets. It substitutes names and composes liberty functions,
both mechanical, and stops at the boundary stage 3 already defines: a flip flop's
output, a primary input, a constant.

### `success` is a registered output

The port is driven straight off a `dfrtp`, so its own cone holds one signal and
says nothing. The cone that matters is the one feeding that flop's `D`, and it
is one of the two widest in the design — the same 57-input cone
`corpus_reach.py` found sitting closest to the edge of what the corpus can name.

```
target puzzle, cone root i00228.data
  47 cells, 57 boundary signals
  it depends on   R0  57 bits, and nothing else

  i00228.data = t46
  t0  = !R0[41]                                  # inv_2
  t2  = (R0[48] | R0[45] | R0[49])               # or3_2
  t3  = (!R0[50] & !R0[52] & !t2)                # nor3_2
  t4  = (R0[47] & R0[46] & R0[51] & t3)          # and4_2
  ...
  t44 = (!R0[0] & R0[36] & t24 & t43)            # and4b_2
  t45 = (R0[0] | !R0[36])                        # nand2b_2
  t46 = ((t0 & t5 & t44) | (R0[2] & t45))        # a32o_2
```

Every boundary signal is a bit of R0. No primary input reaches it directly and
no constant does, so the success condition is a function of stored state alone —
which is what makes stage 6 a bounded model checking problem rather than a
single SAT query.

Reading what that condition *means* is the author's work and deliberately not
the pipeline's. What the pipeline owes is the listing above and the guarantee
that it is faithful.

### What guarantees the listing

Composing cells means evaluating liberty's `function` expressions, and from here
on the pipeline computes with them rather than carrying them: stage 6's SMT2
export inherits the same parser. So the parser is checked twice.

`tools/common/boolexpr.py` parses the expressions. `tools/verify_functions.py`
puts every combinational cell through **both** liberty and the PDK's own
behavioural Verilog model, under Icarus, and compares complete truth tables.

```
67 cell types, 62 combinational with a parseable function
850 (cell, output, pattern) comparisons -- every one agrees
```

`--selftest` asks the harder question: *which mistakes would that comparison
notice?* It builds three deliberately wrong parsers and measures how many of the
library's 448 functions expose each.

| Mistake | Functions that expose it |
|---|---|
| `and` and `or` exchanged | 257 / 448 |
| negation binds greedily, `!A&B` read as `!(A&B)` | 137 / 448 |
| **one precedence level**, `A\|B&C` read as `(A\|B)&C` | **0 / 448** |

That last row is the finding. **This library parenthesises every conjunction** —
`(A1&B1) | (A2&B1)` — so precedence never decides anything in it, and 850
agreeing comparisons are no evidence at all about precedence. Eight hand written
truth tables cover it instead, and they are the only thing that does.

Three of those eight were wrong when first written, in the bit order of the
pattern rather than in the logic. The parser was right and the test was wrong,
which is the ordinary way round for a test nobody has exercised.
