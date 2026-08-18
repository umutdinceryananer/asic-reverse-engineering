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

**Negative controls.** A corpus of only positive examples measures sensitivity
and never specificity: a detector that shouts "counter" at every register scores
perfectly on a corpus of counters. So some circuits exist to *not* be detected,
and carry a `must_not_detect` list.

**Composition.** Synthesis merges logic across module boundaries, which the spec
names as a failure mode. Isolated blocks are the easy case, so the corpus also
holds blocks feeding each other.

## The catalogue

86 circuits, 18 families, four groups.

| Group | Count | Purpose |
|---|---|---|
| positive | 71 | can the detector find it |
| negative | 6 | does it fire where it should not |
| composed | 4 | does it survive blocks being merged |
| structure | 5 | shapes the target has that ordinary synthesis does not produce |

Families: register, shift register, counter, accumulator, adder, subtractor,
comparator, multiplexer, decoder, FSM, LFSR — the spec's list — plus serial
adder and CRC, because the puzzle's `I` port is one bit wide and textbook corpus
circuits take their operands in parallel; plus the negative and structure
families below.

Parameters vary within each family: width 4, 8 and 16, direction, reset style,
enable, FSM encoding, LFSR taps and style. The FSM appears in both binary and
one-hot encoding on purpose — the same machine laid out two ways, so a detector
that only recognises one has learnt the encoding rather than the machine.

**Held out.** Every third variant of each family is withheld from development:
25 for scoring, 61 to work against. The split is a fixed rule rather than a
random draw, so "held out" means the same thing on every machine and every run.

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
| Full cell name, `a21oi_2` | 5% |
| Logic function, `a21oi` | **87%** |

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

## Results

```
86 circuits, 0 synthesis failures
1999 cells, 537 state elements
85 clock buffers across 56 circuits
4 conb_1 cells across 2 circuits
held out for scoring 25, available for development 61
vocabulary by function: 87% of corpus instances are of a kind the puzzle uses
```

**A consistency check that needs no detector.** The generator declares a width;
stage 3 independently reports how many flip flops it found. For every sequential
circuit the two agree, and every combinational circuit reports zero. That is 86
out of 86, and it exercises the generators and stage 3 at once.

## Known gaps

**No general buffering.** 17 of the puzzle's cell functions still never appear,
and `buf` and `inv` are among them: with no timing constraint the mapper never
inserts a plain buffer. Lower risk than the clock tree was, since a buffer in a
data path is a one input one output cell a detector can walk through, but it is
untested.

**`diode`** never appears and never will. Antenna diodes are a manufacturing
construct with no function; stage 3 already carries them as cells attached to a
net and stage 4 should filter them by role.

**Fewer constants than the target.** Four `conb_1` cells against the puzzle's
six. The shape exists; the density does not.

**The corpus cannot prove its own completeness.** This is not fixable and should
not be papered over. The answer is stage 4's coverage report: after the
detectors run, how much of the netlist remains unexplained. That residue is the
honest signal, and it is where a person has to read.
