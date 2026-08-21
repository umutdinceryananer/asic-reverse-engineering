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

### Three criteria, and no committed answer

| Criterion | exact, /133 | NMI | purity |
|---|---|---|---|
| control signature | 117 | 0.0014 | 0.5062 |
| colour refinement, to a fixed point | 97 | 0.1867 | 0.75 |
| control signature + flow split | 91 | 0.3733 | 1.0 |
| control signature + connected components | 80 | **0.5476** | **0.80** |
| + connected components + flow split | 49 | 0.3733 | 1.0 |
| *null model: one group, and do nothing* | *109* | *0.0* | *0.5* |
| *null model: every flop its own register* | *7* | *0.3733* | *1.0* |

A sixth, **placement locality**, is not in that table because the corpus cannot
score it at all — see below.

**Exact match and NMI rank these in opposite orders, and that is the most
useful thing stage 4 measures.** Exact match puts the control signature first
and connected components last. NMI, over the ten netlists whose ground truth
actually has more than one class, puts connected components at 0.5476 and the
control signature at 0.0014 — which is the one-group null model's 0.0 to three
decimal places. On the question stage 4 exists to answer, the committed
criterion *is* the null model.

The exact-match ranking was an artefact of the 109 netlists that declare one
register. `docs/references.md` §3 said so from the published literature (DANA,
TCHES 2020) before anything here measured it; this is the measurement.

The control signature is the clock root, the reset root and its level, the set
root and its level, and the hold net — what a register is written and cleared
by, which its bits share by definition.

**Exact match alone is nearly meaningless here and was reported as a result
anyway.** 109 of the corpus's 133 netlists hold exactly one register, so a
criterion that returns one group and does nothing else scores 109/133. The
control signature's real margin is eight netlists, and on the 24 where the
question is not trivial it gets **8 of 24**. `--score` prints both null models
beside the score, under all three metrics, so this cannot be read the old way
again.

The three **fail in mirror image**, which is the useful part. Connected
components shatters a *plain* register, whose bits do not depend on one another
at all. Colour refinement shatters a *shift* register, whose chain hands every
bit a distinct colour once its predecessor has one. Neither is a tuning problem:
one criterion needs the bits to interact and the other needs them not to.

The first version of this document committed the control signature on the
strength of 116/126. The warm up disproves that choice, and the disproof was
sitting in the repository the whole time — see below. Nothing is committed now.
All three are reported, and where they disagree that disagreement is the
residue: it is where a person reads, and it is not settled by picking whichever
scored best on a corpus that mostly does not ask the question.

### How it is scored, and the 0/0 convention

Exact match compares the *size multiset* — `[8, 8]` against `[8, 8]` — and is
all or nothing: an answer that gets 71 of a register's 72 bits right scores the
same as one that gets none. Every partial credit on the puzzle's R0, which is
the whole of what stage 4 has left to report, rounds to "wrong".

NMI and purity are the field's answer to that, and both need a **membership**:
which flop belongs to which declared register. The corpus declares sizes, not
memberships, so one is recovered, in two ways and never invented:

1. A declaration of one register covering every flop *is* a membership. 109 of
   the 133 netlists are that.
2. Otherwise the RTL vector name yosys leaves on each flop's Q net — `a_reg[4]`
   and `a_reg[5]` are bits of one register. **Checked against the declaration
   rather than trusted:** if the names partition the flops differently from the
   sizes the generator declared, the netlist is refused. 10 of the 24
   multi-register netlists survive.

The 14 refused are refused for two measured reasons. `two_clocks` and
`inverted_clock` declare `[4, 4]` for what the RTL writes as one vector split
across two clocks, so the names say `[8]`. The `scale_datapath` family loses one
bit of three registers to a yosys rename, so the names say
`[16, 16, 16, 15, 15, 7, 2, 1, 1, 1]` against a declared
`[16, 16, 16, 16, 16, 8, 2]`. Attaching those stragglers to whichever group
makes the sizes match would be fitting the answer key to the answer.

**NMI normalisation: arithmetic mean, `2 I(C;T) / (H(C) + H(T))`.** Named in the
tool's output as well as here, because the four normalisations in circulation
give different numbers for the same partitions — the hand-written table below
separates them: max-normalisation scores the all-singletons row 0.25 where
arithmetic scores 0.4.

**The 0/0 case is load-bearing and is not an edge case.** A ground truth with
one class has zero entropy and therefore zero mutual information with any
answer: the ratio is 0/0 and there is no value to report. 109 of 133 netlists
are in that state. The convention, stated once and counted in every aggregate:

| Ground truth | Answer | NMI |
|---|---|---|
| two or more classes | anything | as defined |
| one class | one class | **1.0** — the partitions are equal, which is all NMI ever measures |
| one class | splits | **undefined**. Excluded from the mean, counted under its own branch, left to purity and exact match, which both see it |

Averaging those 109 in as 0 would say every criterion fails on 82% of the
corpus; averaging them in as 1 would say every criterion is nearly perfect.
Both are wrong for the same reason: the netlist does not ask the question.

So **two means are reported, and the second is the one to read**: over all 119
netlists with a membership, and over the 10 whose truth has more than one class.
Measured, the first is useless — the one-group null model and the committed
criterion both score 0.9161, to four decimal places, because 109 of the 119 rows
were never able to disagree. That is what the warning above looks like when it
is ignored.

**Neither metric replaces exact match, and none of the three is sufficient.**

| | one group | every flop its own |
|---|---|---|
| exact match | 109/133 | 7/133 |
| NMI | 0.0 | 0.3733 |
| purity | 0.5 | **1.0** |

Purity does not penalise over-splitting at all — every cluster of one is pure —
so the common claim that the NMI/purity *pair* kills both degenerates is false
as stated. What kills all-singletons here is exact match. Three columns are
printed, not two.

### A hand-computed table the implementation has to reproduce

`stage4_registers.HAND_WRITTEN_METRICS`, in the style of
`verify_functions.HAND_WRITTEN` and for the same reason: the implementation is
the only thing that computes these numbers, so agreeing with itself is worth
nothing. Seven rows, each worked out on paper from the definitions with the
arithmetic in the comment beside it, and `--score` and `--compare` both run it
before they measure anything and refuse to continue if a row disagrees.

Demonstrated on three known-bad inputs, all of which the table or the recordings
catch:

| Corruption | Caught by |
|---|---|
| max-normalisation instead of arithmetic mean | 2 of 7 rows disagree; `--selftest` exits 1 |
| the 0/0 convention averaged in as 0.0 rather than excluded | the "one true class, answer splits" row; exits 1 |
| a membership fitted to the declaration instead of refused | `--score`: membership 133 where 119 is recorded, and NMI falls to 0.8801 |

### DANA's successor/predecessor split, measured rather than assumed

`docs/references.md` §3 singles out one of DANA's nine passes for our exact
symptom — *"Split by Successor/Predecessor Groupings ... becomes essential in
later iterations, where different metrics combined resulted in too large
groupings"* — and both of stage 4's failures are too-large groupings: the warm
up answers `[16]` for a true `[8, 8]`, and R0 is 72 bits under one signature.

`split_by_flow` implements it. Within a candidate group each flop is signed by
**which groups** its data reaches and which reach it, at group level rather than
flop level, with primary ports counted by port *name* — `d[0]` and `d[1]` are
the port `d`, and they have to be, or a plain register reading distinct bits of
one input bus would be split by its own inputs. A group whose members disagree
splits; groups only ever split, so the loop ends when a round adds nothing. Run
over two seeds, the control signature and control + connected components.

**It is not what the quotation predicts, and the measurement is the deliverable
here.** On the ten netlists whose ground truth has more than one class it scores
NMI 0.3733 and purity 1.0 — *identical to the all-singletons null model*,
because on those ten it is all singletons. Every one of them is a shift register
or a pair of them, and a chain hands each bit a different predecessor group as
soon as its predecessor has one. On the warm up it answers sixteen singletons,
at every round count from one to the fixpoint:

| rounds | warm up | `warmup_twin_w8` |
|---|---|---|
| 1 | `[14, 1, 1]` | `[7, 7, 1, 1]` |
| 2 | `[12, 1, 1, 1, 1]` | `[6, 6, …]` |
| 4 | `[8, 1×8]` | `[4, 4, …]` |
| fixpoint | 16 singletons | 16 singletons |

That is not DANA being wrong: DANA applies nine passes in ordered *pairs* with a
majority vote and never runs one to a fixpoint alone, which is what this
measures. This instantiation is one pass, and it is reported as one.

Two things it does that no other criterion here does:

**It does not split a plain register.** `register_w8_async_reset` stays `[8]`
under the flow split and shatters into eight singletons under connected
components. That is the pass's designed advantage over components, and
`--compare` checks it rather than describing it — a run where it stops holding
fails.

**On the R0 analogue it recovers whole registers.** `scale_datapath_w16_b8` is
90 flops in seven declared registers, and the control signature answers one
group of 82 — the shape of the puzzle's R0, 72 of 92 under one signature. The
flow split answers `[16, 8]` and 66 singletons, and those two groups are
*complete RTL registers*, each one split across two names by a yosys rename.
Nothing else in the table produces a complete register on this family at all.
The check is on **bit indices** — the names on a group's Q nets must cover
`0 … n-1` once each — because the rename is also why this family has no
membership ground truth, so names would not settle it.

### Placement locality, and why n = 1

The announcement sanctions this outright: *"The circuit is physically arranged
to hint at its functionality, so look closely at the layout!"* DANA names the
same idea as its own **unexploited** one and an open research question. Stage 1
already records `lower_left` and `orient` for every placement, and
`verify_blocks.py` already keys on both, 230 of 230.

`spatial_groups` is single linkage: two flops join when they sit within
`LINK_ROWS = 3` row heights (8.16 µm) of each other, and a group is the
transitive closure. Single linkage rather than a centroid method because a
register laid out along a row is a chain of near neighbours and not a ball, and
anything measuring distance to a centre would cut it in half.

On the warm up it is **right, membership included** — NMI 1.0, purity 1.0:

```
  8 flops  x  26.22..36.34  y  59.84..76.16   DEF block sr_a
  8 flops  x  26.22..36.34  y  21.76..38.08   DEF block sr_b
```

The two clusters are 21.76 µm apart and no flop is more than 5.44 µm from its
nearest neighbour inside its own cluster. `sr_a` and `sr_b` **do** separate
spatially, measured and not assumed, and this is the only criterion that gets
the warm up right without reading a single wire.

The threshold is printed as a profile, not as a number, because that is the
difference between a reading and a knob:

| rows | µm | clusters |
|---|---|---|
| 1 | 2.72 | 16 singletons |
| 2 | 5.44 | `[7, 6, 2, 1]` |
| **3 – 8** | **8.16 – 21.76** | **`[8, 8]`** |
| 9 – 12 | 24.48 – 32.64 | `[16]` |

Six consecutive thresholds give the same answer. `LINK_ROWS = 3` is the lower
edge of that plateau, and it was chosen because it is the smallest threshold at
which this design's two registers connect — **one parameter fitted to one data
point**, which is said here rather than hidden. The profile is printed so the
author can pick differently on a design whose answer is not known.

**The synthetic corpus cannot score this.** Every circuit under `out/synth/` is
synthesised and never placed, so there is no `instances.json` for any of them
and no figure in `--score` or `--compare` covers this criterion. Its only ground
truth is the warm up — **n = 1** — and later the puzzle, read by a person.
Nothing about it is a rate, and both the tool and this document say so wherever
it appears.

### What it cannot do

It cannot see a boundary that no control signal marks. All 16 of its misses are
circuits built from several registers sharing a clock, a reset and a hold:
every `scale_datapath`, the composed shift-register-into-accumulator, both
`warmup_twin` widths, and the warm up's own RTL.

One of the terms is weaker than the others. The hold net comes from stage 3's
structural search, which is a measured lower bound — four ways of hiding a hold
are recorded in `verify_corpus.py` — so **a hold stage 3 misses is a split
missed here.** In `scale_datapath` that is exactly what happens: the held output
register would have been separated by its hold net, and the mapper factored the
mux away, so it is not.

### The warm up, where the answer is known and stage 4 gets it wrong

`puzzle/warmup/03_post_place_and_route.def` names every placed instance with the
hierarchy it came from, and `01_netlist.v` carries the same names. That is an
exact block partition of a *real* design — not a corpus we wrote, not a shape we
chose. `tools/verify_blocks.py` maps it onto the recovered instances, keyed on
position, orientation and cell together, and all 230 match.

```
the design's own block partition, from the DEF
  (top)      154 cells
  add0        41 cells
  sr_a        16 cells, 8 of them flip flops
  sr_b        16 cells, 8 of them flip flops
  cmp0         3 cells

the register partition it implies: [8, 8]

  control signature                [16]      wrong
  connected components             [8, 8]    CORRECT
  colour refinement, fixed point   [16]      wrong
  everything is one register       [16]      wrong
```

Two eight bit shift registers, feeding an adder, feeding a comparator. They
share a clock, a reset **and** an enable, so no control signature can separate
them — and the criterion the corpus score ranked *last* is the one that is
right.

An earlier version of this document read stage 4's `[16]` and wrote "which is
the whole circuit: a 16-bit accumulator behind a hold". `00_source.v` says it is
two shift registers, an adder and a comparison against 496. The count was wrong,
the name was wrong, and interpreting the circuit was not the pipeline's job in
the first place.

This gate **currently fails**, and it should: stage 4 cannot yet partition the
one real design whose partition is known.

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

Two scores, and they disagree, which is the finding.

`--score` runs the corpus: 117 of 133 exact, 34 of them held out — beside a null
model that gets 109, and beside NMI and purity on the ten netlists where the
question is real, where it scores the null model's numbers.
`verify_blocks.py` runs the warm up against its own DEF hierarchy: **fail**.

`verify_blocks.py` scores **membership** beside sizes. It did not, and would
have called an interleaved answer correct — `[8, 8]` with eight bits of `sr_a`
and eight of `sr_b` in each group, from no information at all. That answer is
now a permanent row in its table, labelled `RIGHT SIZES, WRONG MEMBERS` at NMI
0.000, because the column needs a known-bad input standing in it or it is only
silence. `docs/problems.md` 46.

The declared corpus partitions are themselves checked: `verify_corpus.py`
confirms the widths a generator declares add up to the flip flops stage 3 found.
A partition that did not account for every flop would make the corpus score
meaningless in a way nothing else would notice.

What neither score covers is the shape the warm up actually has: **two
structurally identical registers sharing every control signal.** No corpus
circuit has it. `two_clocks` differs in clock, `inverted_clock` in edge,
`composed_shift_accumulate` in structure. The corpus missed exactly the case the
real target contains.

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

### Bit order, and two derivations meeting

Stage 4 emitted registers as *sets* from the day it was written. Stage 7 needs
words: `O[7:0]` is not the same eight flops in some other order, and an
operand's bits carry different arithmetic weight. `bit_order` derives one where
the structure gives one, following WordRev (`docs/references.md` §3):

| Shape | Rule | Corpus |
|---|---|---|
| shift chain | drop self edges — a flop whose Q returns to its own D is *holding*, not shifting — and if every bit then has at most one predecessor and one successor inside the group, the group is a set of simple paths, head first | 19 |
| carry chain | otherwise, if the induced graph is acyclic and the longest path to each bit is distinct, order by ripple depth | 34 |
| none | otherwise, emit `"method": null` and the reason | 95 |

The third row is the point. A plain register's bits do not depend on one
another at all, so there is nothing to order and the tool says so; an LFSR's
bits depend on one another cyclically, so there is no first bit and the tool
says that. **A guessed bit order is worse than none** — it is exactly the kind
of answer stage 7 would build a string out of.

On the warm up, the sixteen flops under one control signature come out as **two
chains of eight**, which is `sr_a` and `sr_b` exactly: the boundary the control
signature cannot see, said in a second language.

#### The cross-check, and what it caught

`verify_cone.py` now checks that order against the arithmetic, and the two
derivations share nothing:

- stage 4 orders bits by following `D <- Q` through the netlist — a walk over
  wires that knows nothing about arithmetic;
- `verify_cone` solves for the weight assignments that make the cone equivalent
  to `a + b == 496` over all 65536 assignments — a search over functions that
  knows nothing about wires.

In a shift register the two must run together. The check is in two parts:

1. the two bits of each operand pair sit in **different chains at the same
   position**. All eight do, at positions 0–7 once each — and stage 4 found the
   two chains without knowing an adder pairs bit *i* with bit *i*.
2. the weights that order implies, `2^position` or `2^(width-1-position)`, are
   **among** the assignments that make the cone equivalent. `2^position` is,
   so the chain head is the least significant bit: the first bit shifted in
   ends up as bit 0.

**Running it found a defect in the more rigorous-looking half.** The two
derivations disagreed, and the fault was in the weight solve: it stopped at its
first hit and printed one assignment as though the search had determined it,
when **24 of the 40320 are equivalent** — `a + b == 496` with both operands
below 256 does not tell the four most significant pairs apart at all.
`docs/problems.md` 47. Asking whether the structural order is *among* the 24 is
a stronger question than comparing it to one arbitrary member: 24 chances in
40320 of passing by luck.

Demonstrated failing, on two scrambles of `registers.json` passed with
`--registers`:

| Scramble | Caught by |
|---|---|
| swap two bits in one chain | part 1: two pairs land at positions 2 and 5 |
| swap the same two positions in **both** chains | part 2: the pairs still align, and neither `2^position` nor `2^(7-position)` is among the 24 |

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
