# Stage 5, synthetic corpus

Circuits whose answer is already known, because we wrote them.

Stage 4 will produce detectors: algorithms that say "these eight flops are a
counter". On the puzzle there is no way to check such a claim — if it could be
checked, the detector would not be needed. So the test set has to exist first,
and `docs/solver-pipeline.md` is explicit about the order: "detectors written
without a test set cannot be validated."

Output: `synth/` with generated RTL, `out/synth/<name>/` with the netlist, the
stage 3 graph and a `truth.json` answer key, and `out/synth/index.json`.

## What it can and cannot be

It cannot be complete. A puzzle built to be reverse engineered is not obliged to
contain textbook blocks, and no list of families can be proved to cover it.
Three things are done about that, none of them "think harder about the list".

**Functional detection over structural.** The spec calls the miter check "the
more reliable of the two": synthesis rewrites structure and preserves function,
so a block that no longer looks like an adder still behaves as one. That makes
the corpus a *reference library* as well as a test set — and bounds what can
ever be named, because a miter needs something to compare against. A structure
absent here can be found unexplained; it cannot be identified.

**More than one structure per function.** The claim above was untestable while
every circuit was synthesised exactly once: a detector that had memorised one
particular mapping of an adder would have scored perfectly. Each circuit is now
mapped twice from one shared pre-mapping netlist, and 51 of 89 land on genuinely
different cell mixes.

**Negative controls.** A corpus of only positive examples measures sensitivity
and never specificity: a detector that shouts "counter" at every register scores
perfectly on a corpus of counters. So some circuits exist to *not* be detected,
and carry a `must_not_detect` list.

**Composition.** Synthesis merges logic across module boundaries, which the spec
names as a failure mode. Isolated blocks are the easy case, so the corpus also
holds blocks feeding each other.

## The catalogue

89 circuits, 19 families, five groups.

| Group | Count | Purpose |
|---|---|---|
| positive | 71 | can the detector find it |
| negative | 6 | does it fire where it should not |
| composed | 4 | does it survive blocks being merged |
| structure | 5 | shapes the target has that ordinary synthesis does not produce |
| scale | 3 | is it still true at the size of the target |

Families: register, shift register, counter, accumulator, adder, subtractor,
comparator, multiplexer, decoder, FSM, LFSR — the spec's list — plus serial
adder and CRC, because the puzzle's `I` port is one bit wide and textbook corpus
circuits take their operands in parallel; plus the negative and structure
families below.

Parameters vary within each family: width 4, 8 and 16 — and 32 and 64 in the
scale family — direction, reset style, enable, FSM encoding, LFSR taps and
style. The FSM appears in both binary and one-hot encoding on purpose: the same
machine laid out two ways, so a detector that only recognises one has learnt the
encoding rather than the machine.

**Held out.** Every third variant of each family is withheld from development:
26 circuits for scoring, 63 to work against. The split is a fixed rule rather
than a random draw, so "held out" means the same thing on every machine and
every run, and it is decided once per circuit so that both mappings of a held
out circuit stay held out together.

## Matching the target, measured rather than assumed

Each circuit goes through the same Yosys flow onto the same PDK, then through
the same `stage3_graph.build` the puzzle goes through. A corpus that stopped at
a netlist would be testing the detectors on a different kind of input than they
will meet.

Synthesis needs a liberty file and this PDK publishes liberty as per cell, per
corner JSON, so `common/liberty.write_lib` reconstructs the text: area, pin
directions, output functions and the sequential group, which is all a mapper
reads. That file also unblocks stage 4's miters and stage 6's solver export,
neither of which can work on blackboxes.

Low power cell families are excluded from what the mapper may choose. They
belong to a flow this design did not use, and the puzzle instantiates none of
them. The library is *not* narrowed to the puzzle's own 67 cell types: tuning
the test set to the target would make the detector scores meaningless.

### What the measurement found

Comparing the corpus's cell vocabulary against the puzzle's was worth doing, and
the first number it produced was wrong in an instructive way.

| Compared on | Overlap |
|---|---|
| Full cell name, `a21oi_2` | 3% |
| Logic function, `a21oi` | **90%** |

The difference is drive strength: the puzzle is mostly `_2` with `_4`, `_8` and
`_16` for its clock tree, and the corpus is mostly `_1` because `abc` picks the
smallest cell that does the job when no timing constraint says otherwise. Drive
strength is a physical choice and changes no function, so the second number is
the meaningful one — but the first is why **detectors must normalise the
suffix rather than match on the full name.**

With that corrected, two real gaps remained, and both were closed.

**No clock buffers.** The puzzle distributes its clock through 16 `clkbuf_8`
branches; the corpus wired every flop's `CLK` straight to the port. This is the
most dangerous of the gaps, because bits of one logical register in the puzzle
do *not* share a clock net. A detector grouping flops by the net their clock
reaches would split the puzzle's 92 flops into sixteen pieces and find nothing —
and would have scored perfectly on a corpus where that cannot happen.

**No constants.** The puzzle ties twelve nets high or low through six `conb_1`
cells. The corpus produced none — and the reason was not a broken pass but the
assumption behind it: synthesis folds a constant into whatever reads it, so
nothing survives to be mapped. A constant that reaches a *port* cannot be
folded, which is the shape that forces one.

## Closing the clock tree gap

`clkbufmap` inserts clock buffers, and did nothing twice, silently, for two
separate reasons.

Its argument is `-buf <celltype> <out>:<in>`, where the first port is the one
that connects to the sinks. Written `A:X` instead of `X:A` the pass runs,
reports success and inserts nothing.

It also finds clock inputs by the `clkbuf_sink` attribute, which cells arriving
through `dfflibmap` and `abc` do not carry. The blackbox library is now read
before synthesis with those pins marked, taken from liberty's own `clock` flag —
the same authority stage 3 uses.

That yields one buffer per clock net, not a tree; `clkbufmap` cannot split
fanout. So a `clock_tree` family writes the tree in its own RTL:

| | flops | distinct clock nets | driver |
|---|---|---|---|
| `clock_tree_w8_b4` | 8 | 4 | `clkbuf_1` |
| `clock_tree_w16_b4` | 16 | 4 | `clkbuf_1` |
| `clock_tree_w16_b8` | 16 | 8 | `clkbuf_1` |
| *puzzle* | *92* | *16* | *`clkbuf_8`* |

One logical register spread over several clock nets, which is the puzzle's shape
at a smaller size. A detector that survives these will not be grouping by clock
net.

## Size

Every family above is an order of magnitude below the target. That was easy to
miss because the corpus counts looked healthy in aggregate, and it took asking a
different question to see it:

| | flops | cells |
|---|---|---|
| largest circuit in the corpus | 32 | 125 |
| **median circuit in the corpus** | **4** | |
| the puzzle | 92 | 738 |

A detector scored on four-flop circuits says very little about ninety-two, and
two of the costs are not linear: grouping N flops into registers, and a miter
whose SAT instance grows with cone depth and width.

The `scale_datapath` family answers this by **bracketing the target rather than
approaching it** — if something breaks between 90 flops and 354, that shows up
as a trend rather than as a single pass or fail.

| | flops | cells | cone roots | clock nets |
|---|---|---|---|---|
| `scale_datapath_w16_b8` | 90 | 280 | 197 | 8 |
| *the puzzle* | *92* | *738* | *189* | *16* |
| `scale_datapath_w32_b8` | 178 | 561 | 389 | 8 |
| `scale_datapath_w64_b16` | 354 | 1136 | 773 | 16 |

What it computes is deliberately ordinary — a serially fed shift register, an
accumulator summing it, a counter, an LFSR, a held output register, a tag
register and a small state machine, all feeding each other. Nothing here is
chosen to resemble the puzzle's function, which is not known. **Only the size
and the shape are matched**, and both are things the corpus was measurably short
of.

Two properties are carried over deliberately. The shift register is cut into one
segment per spare clock branch, so a single logical register spans ten of the
sixteen branches at the largest size rather than spanning two in a toy. And the
LFSR resets to a non-zero seed, which puts set flops beside reset flops — an
LFSR started at zero stays there, so that is the circuit's own requirement and
not a shape borrowed from the target.

The first version declared sixteen branches and used eight. The other eight
buffers drove nothing, `opt_clean` removed them, and `verify_corpus.py` caught
the declared count disagreeing with the netlist. The number of clock domains is
bounded by the number of independent `always` blocks, so `branches` was never a
free parameter.

**Stage 3 scales flat.** Building the graph takes 1.1 s at 280 cells and 1.4 s at
1136. Whether stage 4 does is the open question, and now there is something to
ask it on.

## The same function, mapped more than one way

Which knob to turn was measured rather than picked. `abc -D 250`, a delay
target, was the obvious candidate and changes **nothing at all**: identical cell
mix on every circuit tried. `-fast` stops `abc` short of its full optimisation
and genuinely rewrites. On `adder_w8`, 24 cells over 6 types becomes 31 over 10,
only 10 instances survive unchanged, and the `maj3` carry chain is replaced by
`a31o` and `a21oi` — cells the puzzle uses and the base flow never produced.

`design -save` before the mapper and `design -load` before each variant is what
makes these variants of one *function*: everything up to technology mapping is
shared and only the mapping differs. Held out is decided once per circuit and
inherited by every variant, or a held out circuit would reach development work
through its other mapping.

Drive strength stays at `_1` under both, deliberately. It is a physical choice
that changes no function; the corpus differing from the puzzle there is what
makes the case that detectors must normalise the suffix.

## Results

```
89 circuits as 178 netlists (base, fast), 0 synthesis failures
8593 cells, 2318 state elements
51/89 circuits map to a different cell mix under the second flow
held out for scoring 26 circuits, available for development 63
vocabulary by function: 90% of corpus instances are of a kind the puzzle uses
```

How far apart the two mappings really are is worth stating separately, because
"differs at all" is a weak claim. Among the circuits that differ, the median has
**78% of its cell slots changed**; corpus wide the figure is 63%. Two of the
comparators are more than completely rewritten.

## The answer key, checked

`tools/verify_corpus.py` puts every fact a generator declared against what stage
3 independently found in the synthesised result. The two are independent: one is
what was asked for, the other is what a tool read out of the gate level netlist,
and where they disagree it is not knowable in advance which is wrong.

This existed once as a sentence in this document — "the declared width equals
the flip flops stage 3 finds, 86 out of 86". It was true when written and had no
way of staying true. **A measurement that is not a program is a measurement that
happened once.**

```
89 circuits as 178 netlists, 622 declared facts checked
   12  a reset port, with the reset in the logic    118  clock roots
    4  constant nets                                118  flops on an inverting clock path
    6  declared flip flop count                     118  flops under the clock root
   12  distinct clock nets                           70  flops whose reset is a pin
   30  flops whose data cone the enable reaches      78  width in flip flops
   56  stateless
RESULT: pass
```

**That headline number deserves less credit than it looks like.** There are ten
rules here, applied across 178 netlists. Four of the ten assert a constant no
circuit in this corpus could violate — `clock roots` is always 1, `stateless`
always 0, `flops on an inverting clock path` always 0 because no generator
writes `negedge clk`. And `clock roots == 1` implies `flops under the clock
root == all of them`, so those 118 pairs are one fact counted twice. The honest
summary is **ten rules, four of them constant**, not 622 independent facts.

Every declared fact is checked against **every** mapping of the circuit that
declared it. That is the structural invariance test, made at the stage 3 level
and for free: a fact that only survives one particular mapping was a property of
that mapping and not of the circuit.

**`--selftest` feeds each rule the corruption it exists to catch** — the root
walk removed, reset pins lost, a synchronous reset made asynchronous, a clock
inverted, an extra flip flop, an enable reaching no cone, constants folded away
— on a circuit that rule applies to and that passes cleanly beforehand. The
first version ran all seven against one circuit and one went unnoticed for the
uninteresting reason that its rule was never in play.

### What it found on its first run

**Six circuits declared a synchronous reset and had no reset at all.** The
generator branched on `async_reset` and `async_set` and let `sync` fall through
to an `else` emitting no reset and no reset port. These are an answer key:
stage 4's detectors were going to be scored against them, and a detector
correctly reporting "no reset" would have been marked wrong. The generator now
emits what it declares, and the check distinguishes the two shapes rather than
asking whether a reset exists somewhere — which is the weaker question that had
been passing.

**The structural search for a held register finds 6 of 30 declared enables**, in
four distinct ways, all measured against ground truth we wrote:

| Shape | What synthesis did |
|---|---|
| `register` | mux survives in front of `D` — found |
| `counter` | enable folded into the carry chain, `D[0] = q[0] ^ en`. No mux exists |
| `register` + sync reset | mux survives as `mux2i`, but the reset's `nor2b` sits between it and `D` |
| `scale_datapath` | the mux is factored away entirely |

The fourth came in with the scale family and it is the one that settles the
question. `D = en ? (acc ^ lfsr) : outr` maps to a single `a21oi`, `Y = !B1 &
(!A1 | !A2)`, with `en` on `A1` and `Q` arriving through a `nor2` two cells back.

That is not a special case — **it is the general one, and the other three are
the exceptions.** A plain register keeps its mux only because the data leg is a
port. Once that leg is something the circuit computes, the mapper folds the
select into the logic that computes it, which is what a technology mapper is
for. Any enumeration of hold patterns loses to this.

The rule was changed from "a hold survives as a mux", which is a claim about
synthesis, to "the enable reaches the data cone of the flops it holds", which is
a claim about the circuit and holds under all four. The structural count is
still reported and the shapes that defeat it are listed by name, so a *new* way
of losing a hold fails the run rather than blending into a rate — which is
exactly what happened when the scale family arrived, and is why the fourth shape
above is written down with a measurement behind it instead of a guess.

## Known gaps

**12 of the puzzle's cell functions never appear**, down from 17 once the second
mapping and the scale family were added. Three of those twelve do not need
naming:

| | | |
|---|---|---|
| `inv`, `buf` | 26 cells | transparent; stage 3 walks through them by function, and the corpus's 102 `clkinv` exercise the same code |
| `diode` | 10 cells | an antenna diode is a manufacturing construct with no function at all |

That leaves roughly 9% of the puzzle's cells of a function the corpus cannot
name — the largest being `and2b` at 30. Halved from 18%.

**This number should not be read as a coverage estimate, and it was presented as
one for a while.** It measures cell *vocabulary* overlap. The corpus can only
name a puzzle block if some corpus circuit computes the same function, and
vocabulary overlap says nothing whatever about that: a block built entirely from
`nand2` scores 100% here and may still compute something no corpus circuit
computes. **Functional coverage measured so far is zero — no miter has been
run.** The real figure comes out of stage 4's residue report, and until then
this is a lower bound on the problem dressed up as an estimate of it.

**Fewer constants than the target.** Four `conb_1` cells against the puzzle's
six. The shape exists; the density does not.

**Drive strength.** The corpus is `_1` throughout and the puzzle is mostly `_2`.
Left alone on purpose — see above.

**The corpus cannot prove its own completeness.** This is not fixable and should
not be papered over. The answer is stage 4's coverage report: after the
detectors run, how much of the netlist remains unexplained. That residue is the
honest signal, and it is where a person has to read.
