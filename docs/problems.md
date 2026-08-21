# Problems register

Everything that went wrong, what it actually was, and whether the fix is
understood or only worked around.

This is kept because the failures are more transferable than the successes. A
stage document says what the pipeline does; this says what it nearly did
instead, and most entries below produced a *plausible* wrong answer rather than
an obvious one.

Verdict vocabulary:

| Verdict | Meaning |
|---|---|
| **understood** | root cause found, the fix addresses the cause |
| **worked around** | behaviour avoided, cause never diagnosed |
| **retracted** | a claim was asserted, found wrong, and withdrawn |

Dates: work started 14 August 2026; everything from stage 1 onward is 15 August.

---

## Summary

| # | Problem | Where | Verdict |
|---|---|---|---|
| 1 | Docker BuildKit could not reach the network | environment | **worked around** |
| 2 | `docker build \| tail` reported `tail`'s exit code | environment | understood |
| 3 | Piping the build hid its output; it looked frozen | environment | understood |
| 4 | Git Bash fork failures and MSYS path mangling | environment | worked around |
| 5 | Flattening the PDK's `.v` broke relative includes | environment | understood |
| 6 | `example_inputs.vcd` declared output-free | analysis | **retracted** |
| 7 | `INTERNAL_3`/`INTERNAL_7` called hierarchical blocks | analysis | retracted |
| 8 | Lesson 0's NAND2 exercise answer was wrong | analysis | retracted |
| 9 | Lesson 2's met5 answer written from plausibility | analysis | caught pre-publication |
| 10 | `gds_survey.py` undercounted reused blocks | counting | understood |
| 11 | Logic cell count given as 722, is 728 | counting | understood |
| 12 | Position alone used as a placement key | identity | understood |
| 13 | GDS origin is not the DEF lower-left corner | identity | understood |
| 14 | `subcircuit.id()` is not stable across runs | identity | understood |
| 15 | Fetched PDK revision is not the one that drew the puzzle | library | understood |
| 16 | A fingerprint matching two cells is not an identification | library | understood |
| 17 | Filtering LEF pins on `USE SIGNAL` dropped every clock | filtering | understood |
| 18 | Every simulation output stayed `x` | simulation | understood |
| 19 | The 8-bit output bus simulated as `z` | simulation | understood |
| 20 | The expected output stream was one cycle out | simulation | understood |
| 21 | Routing landed on a cell terminal the LEF does not declare | extraction | understood |
| 22 | The first repair for 21 dissolved `conb_1` into the rails | extraction | understood |
| 23 | The guard protecting 22 did not fire, twice | extraction | understood |
| 24 | Cell roles derived from the LEF and the cell name, not from liberty | normalisation | **retracted** |
| 25 | `bool("false")` is true, so every input read as a clock | normalisation | understood |
| 26 | Six circuits declared a synchronous reset and had none | answer key | understood |
| 27 | The first version of that check would have passed the broken corpus | answer key | understood |
| 28 | The structural search for a held register is a lower bound, four ways | answer key | understood, deliberately not fully fixed |
| 29 | Every test circuit was an order of magnitude below the target | scale | understood |
| 30 | The scale circuit declared sixteen clock branches and used eight | scale | understood |
| 31 | Every inverter in the library was classified as a buffer | normalisation | understood |
| 32 | The cross check compared nets by a name one side invents | identity | understood |
| 33 | A failed build overwrote the answer key it failed to produce | tooling | understood |
| 34 | The repository's best answer key went unused for five stages | process | understood |
| 35 | A score reported without its null model | process | understood |
| 36 | Two gates that printed a verdict and always exited 0 | tooling | understood |
| 37 | Ten corruptions caught, five rules never seen to fail | tooling | understood |
| 38 | The review packet's own three sections misreported | tooling | understood |
| 39 | `clock_nets` is the nets at the flop pins, not the clock tree | inversion | understood |
| 40 | An equivalence proof that proved nothing, twice over | inversion | understood |
| 41 | A bounded model checker answering from a start state nothing has | inversion | understood |
| 42 | The hold search identified a mux by its name, and one of them inverts | normalisation | understood |
| 43 | The RTL reader found no flip flops in a design that is mostly flip flops | tooling | understood |
| 44 | The corpus flow had no `flatten`, and no circuit that needed one | scale | understood |
| 45 | One design, two mappings, three different register partitions | detectors | **open** |
| 46 | The block gate compared sizes, and would have passed the wrong eight bits | verification | understood |
| 47 | The cone's weight solve printed one answer out of twenty four | verification | understood |

Two remain unresolved: **1** and **4**.

Entry **21** is the only defect so far found in a *shipped* artifact rather than
during development, and the only one a passing test did not catch.

Entries **26** to **33** were all found by tools written to check other tools,
within two days of each other. That is not a coincidence about those days: it is
what happens the first time the checks are made into programs instead of
sentences. **31** is the sharpest of them — a rule that had never reported a
non-zero value, because the code could not produce one.

---

## Environment and toolchain

### 1. Docker BuildKit could not reach the network

**Symptom.** `apt-get` inside `docker build` failed to resolve or connect. The
identical command inside `docker run` on the same machine worked.

**Cause.** Not diagnosed.

**Fix.** `DOCKER_BUILDKIT=0`. The legacy builder produces the same image. The
documented commands in `CLAUDE.md` all carry the flag, so the workaround cannot
be forgotten.

**Verdict: worked around.** A real fix would explain why the two paths differ,
probably in how BuildKit's builder container gets its network on this host. The
image is also split into `sim` (Icarus only) and `eda` (adds Yosys and z3) so a
failure while building one cannot cost the gates that depend on the other.

### 2. `docker build | tail` reported `tail`'s exit code

**Symptom.** Build reported as successful, twice, when it had failed.

**Cause.** In a pipeline the shell returns the *last* command's status. `tail`
succeeds at printing whatever it got, including a failure log.

**Fix.** Check the artifact, not the status: `docker images` shows whether the
tag exists. This became a general working rule.

**Verdict: understood.** Worth noting this was made twice before the rule was
written down, which is why it is a rule now.

### 3. Piping the build hid its output

**Symptom.** The build appeared to hang with no output. The user interrupted
twice to ask whether it was stuck.

**Cause.** `| tail` buffers everything until the command finishes, so a
long-running build shows nothing at all.

**Fix.** Run long commands in the background and let them report on completion,
rather than blocking on a silent pipe.

**Verdict: understood.**

### 4. Git Bash fork failures and MSYS path mangling

**Symptom.** Two distinct failures. `child_copy: stack write copy failed` on
some invocations, and Docker arguments silently rewritten: `-w /work` arrived as
`-w C:/Program Files/Git/work`.

**Cause.** The path rewriting is MSYS's POSIX-to-Windows path translation doing
its job on an argument that was already meant to be a container path. The fork
failure is a known Git-for-Windows/MSYS issue and was not investigated.

**Fix.** Use PowerShell for Docker invocations, and `MSYS_NO_PATHCONV=1` where
Bash is genuinely wanted.

**Verdict: worked around** for the fork failure, understood for the path
mangling. Costs nothing on this project since PowerShell is available.

### 5. Flattening the PDK's `.v` broke relative includes

**Symptom.** Cell models failed to compile after being cached.

**Cause.** `fetch_pdk.py` flattened everything into one directory, matching what
it does for `.gds` and `.lef`. But the Verilog models include each other
relatively: per-strength wrappers include their base by bare name, and the
sequential and mux models reach up for UDP primitives with `../../models/...`.
Flattening destroys those paths.

**Fix.** Keep the library's directory structure for `.v` only, and pass a `-I`
per cell directory at compile time. `.gds` and `.lef` stay flat, since nothing
inside them refers to a sibling file.

**Verdict: understood.** The asymmetry is deliberate and is recorded in
`CLAUDE.md` so it is not "tidied up" later.

---

## Claims asserted without checking the primary source

These four share one shape and are the most expensive category in the project.

### 6. `example_inputs.vcd` declared output-free

**Symptom.** None — that is the problem. It was asserted as fact and believed.

**Cause.** The claim came from a single sentence in the puzzle's README. The
file itself, 8 KB of plain text, was never opened.

**What was actually true.** The VCD carries `O[7:0]` and `success` as well as
the inputs: two attempts of 121 bits each, both answered `TRY AGAIN`, 312 rising
edges in total. It is a complete functional test vector for the puzzle target.

**Consequences.** A three-part replacement verification strategy had been
designed on the false premise, and an argument made that Magic should be
promoted from optional to required in order to recover a check that was already
available. Both were withdrawn.

**Fix.** Open the file. It then became the stage 2 puzzle gate, which now passes
312 cycles with zero mismatches — the strongest evidence the extraction is
correct.

**Verdict: retracted.** The single most expensive error in the project, and the
cheapest one to have avoided.

### 7. `INTERNAL_3` and `INTERNAL_7` called hierarchical sub-blocks

**Symptom.** Asserted that the puzzle layout had internal hierarchy worth
exploring.

**What was actually true.** The survey tool's own output said the layout is
flat: only the top cell contains references. The two cells are marker rectangles
on layer 200/0 with no devices at all.

**Fix.** Corrected in the same turn, from the tool output that was already on
screen.

**Verdict: retracted.** Distinctive in that the contradicting evidence had
already been printed and was not read.

### 8. Lesson 0's NAND2 exercise answer was wrong

**Symptom.** The lesson claimed the series node between the two NMOS devices
"shows as a contact column with nothing landing on it."

**What was actually true.** Checking the geometry: `VGND` reaches one column via
a rail stub, `Y` reaches one, and three columns are tied together by an `li1`
shape that touches no rail and carries no pin. The shape of the answer was
right; the description was not.

**Fix.** Rewrote the exercise with the verified answer.

**Verdict: retracted.** Worse than an ordinary error because it was in teaching
material, where a reader has no way to catch it.

### 9. Lesson 2's met5 answer written from plausibility

**Symptom.** Caught before publication, so no consequence — recorded because the
pattern is identical.

**What happened.** An exercise asked what breaks if `met5` is dropped from the
connectivity stack. The answer written first was "upper metals are mostly power
distribution and long-distance routing, so the effect is limited." True in
general, unmeasured here.

**What was actually true.** Zero. `met5` carries no signal connectivity in the
warm up at all — a more interesting answer than the guess, because it says the
declared stack is wider than this layout needs, which is the safe direction to
be wrong in.

**Fix.** `tools/stack_sensitivity.py` now measures it. See problem 14 for what
went wrong on the first attempt at that measurement.

**Verdict: caught pre-publication**, by applying the rule this section exists to
enforce.

---

## Counting and classification

### 10. `gds_survey.py` undercounted reused blocks

**Symptom.** Cell totals lower than expected.

**Cause.** A recursive count guarded by a `seen` set. A block placed twice had
its contents counted once, because the guard prevented *recounting* when it was
only supposed to prevent *recomputation*.

**Fix.** Memoise per cell and multiply by the placement count
(`flatten_counts` in `tools/gds_survey.py`). The distinction is written into the
docstring, since the two guards look identical at a glance.

**Verdict: understood.**

### 11. Logic cell count given as 722, is 728

**Symptom.** A stated figure that later disagreed with an independent count.

**Cause.** Six `conb_1` cells were classified as physical. `conb_1` generates a
constant, so it looks like a support cell — but its outputs drive real nets, so
it is logic.

**Fix.** Reclassified. Independently confirmed afterwards when another solver
published their own figures: 9,875 placements, 728 logic cells, 84 D flip-flops,
21 XOR gates — all matching.

**Verdict: understood.** The correction was found by counting a second way, not
by rechecking the first.

---

## Keys and identity

Three separate bugs, one root idea: **an identifier that does not uniquely
identify.**

### 12. Position alone used as a placement key

**Symptom.** Deep in stage 2, net `B` was reported as reaching pin `A1` of a
`sky130_fd_sc_hd__dfrtp_2`. A `dfrtp_2` is a flip-flop and has no pin `A1`. The
DEF says that net reaches a `mux2_1` pin `A1`.

Everything else looked fine: net count correct, fanout distribution plausible.

**Cause.** Subcircuits were mapped back to stage 1 instances by origin. But a
GDS origin is where the cell's *own* origin landed, not its lower-left corner,
so a mirrored cell extends left and down from it. Two different cells can
therefore share an origin. Measured on the warm up:

```
instances                 230
distinct origins          178
distinct (origin, orient) 230
```

One origin, `(69.92, 38.08)`, is used three times: `nor2_2 FN`, `and2_2 S`,
`and2_2 N`.

**Fix.** Key on position **and** orientation. Additionally, assert that stage 1
and the extractor agree on the cell type at every placement — a free cross-check
over 230 and 1618 placements.

**Verdict: understood.** Note the failure mode: had the two cells' pin names
happened to overlap, this would have produced a silently wrong netlist.

### 13. GDS origin is not the DEF lower-left corner

**Symptom.** Would have broken every comparison against the DEF answer key.

**Cause.** The two formats anchor a placement differently. They agree only for
unflipped cells.

**Fix.** Transform the cell's `areaid.sc` (81/4) footprint by the placement
transform and take the minimum x and y. Caught during stage 1 rather than after.

**Verdict: understood.**

### 14. `subcircuit.id()` is not stable across runs

**Symptom.** The first version of the stack sensitivity measurement produced a
self-contradiction:

```
without met5  ->  86 nets, 19 of 86 identical (67 changed)
```

The same net count, yet 67 nets reported as changed. If nothing disappeared,
what changed?

**Cause.** Nets were compared as sets of `(subcircuit.id(), pin)`. KLayout
assigns those ids per run; they do not denote the same placement in two
extractions. The measurement was reporting harness noise.

**How it was found.** Not by theorising about met5, but by extracting the
*unmodified* stack twice. The two runs disagreed with each other, which locates
the fault in the comparison rather than in the layer.

**Fix.** Key on `(position, orientation, cell)` — the same rule problem 12
already forced on stage 2. `tools/stack_sensitivity.py` now runs the identity
extraction first and refuses to print anything if it does not come back
identical.

**Verdict: understood.** Same mistake as problem 12, in a different costume,
three weeks of project time apart.

---

## Library and PDK

### 15. The fetched PDK revision is not the one that drew the puzzle

**Symptom.** 22 of 1618 puzzle placements failed exact geometric matching —
and not marker cells, but three properly named library cells: `o211a_2` (12),
`conb_1` (6), `and4b_2` (4).

**Cause.** The files existed in the fetched PDK; the geometry genuinely
differed. Layer by layer:

| Cell | Layers that differ |
|---|---|
| `o211a_2` | `poly`, `licon1` |
| `conb_1` | `npc` |
| `and4b_2` | `poly` |

`nwell`, `diff`, `li1`, `mcon`, the implants and the pin layers all matched
exactly. The puzzle was drawn with a slightly different library revision — the
difference looks like a DRC fix, electrically identical.

**Fix.** A second matching tier. Exact hash first; on a miss, a structural key
of `{nwell, diff, li1, mcon}` geometry plus the pin name set plus transistor
count. Those layers still encode which transistors are in series and which in
parallel, which is what distinguishes a gate from its dual. Measured: that key
alone separates 427 of 437 library cells, and adding pin names and transistor
count separates all of them.

**Verdict: understood.** In real reverse engineering the reference library is
routinely not the one the chip was built from, so this tier is a permanent part
of the design, not a patch.

### 16. A fingerprint matching two cells is not an identification

**Symptom.** Ten pairs of library cells produced identical structural keys.

**Cause.** The `lpflow_*` isolation cells are byte-identical in layout to their
logic equivalents (`and2_1` and `lpflow_inputiso0n_1`, for example), named
differently for a different purpose.

**Fix.** Two things. Pin names and transistor count are part of the key, which
separates these. And, as a rule: a key landing on more than one library cell is
**dropped from the index**, never resolved arbitrarily
(`fingerprint_index` in `tools/common/gds.py`).

**Verdict: understood.** Picking one of two candidates would not be an
identification, it would be a silenced error.

---

## Filters that drop more than they say

### 17. Filtering LEF pins on `USE SIGNAL` dropped every clock

**Symptom.** `dfrtp_2` came back without a `CLK` pin.

**Cause.** 69 pins across this library are declared `USE CLOCK`, not
`USE SIGNAL`. An allow-list built on `USE SIGNAL` removes every flip-flop clock
connection — silently, since the result still compiles and still simulates.

**Fix.** Invert the rule: exclude supplies (`USE POWER`, `USE GROUND`), keep
everything else. Stated as a general principle in `tools/common/lef.py`.

**Verdict: understood.** Caught before it did damage, by noticing an expected
thing was absent rather than by an error message. A flip-flop without a clock is
not a thing that exists.

---

## Simulation

### 18. Every simulation output stayed `x`

**Symptom.** The recovered netlist compiled and ran, and every output was `x`.
The obvious reading is that the extraction is broken.

**How it was found.** Instead of adjusting the extraction, the warm up's
*reference* netlist — the original, known-good `.v` — was run through the same
testbench. It failed identically. That single run separates "my extraction is
wrong" from "my harness is wrong."

**Cause.** The sky130 cell models default to the behavioural view, which carries
`specify` blocks and timing checks and holds `x` without a timing-annotated run.

**Fix.** `-DFUNCTIONAL -DUNIT_DELAY=#1`.

**Verdict: understood.** The general rule this produced: when a result is
"almost right" or "totally wrong", test the harness against known-good input
before touching the thing under test.

### 19. The 8-bit output bus simulated as `z`

**Symptom.** `O[7:0]` read `zzzzzzzz` — nothing driving it.

**Cause.** The Verilog emitter applies an escaping rule to identifiers that are
not plain names, producing `\O[0] `. But `\O[0]` is not bit 0 of the vector `O`;
it is a separate scalar whose name happens to contain brackets. The declared bus
therefore had no driver, and `z` was the correct simulation result for the
netlist as written.

**Fix.** A bit of a declared vector is emitted as a *select*, `O[0]`, bypassing
the escaping rule. The `reference()` helper in `tools/stage2_nets.py` decides
which of the two a name is.

**Verdict: understood.**

### 20. The expected output stream was one cycle out

**Symptom.** The puzzle simulation reported 20 mismatches, but the byte sequence
was already exactly right — every value correct, shifted by one cycle.

**The tempting fix.** Add one to an index until it passes. Rejected: an offset
applied without knowing why can produce the right answer for the wrong reason,
and will not survive a different input.

**How it was found.** Opening the raw VCD text:

```
#1255000
b1010100 %      <- O becomes 'T'
1!              <- clk rises
```

**Cause.** The VCD is a zero-delay dump. At a rising-edge timestamp the output
change is listed *before* the clock change, so snapshotting when the edge
arrives already captures the output that edge produced. Taking the next
snapshot — the intuitive choice — shifts the whole stream.

**Fix.** One line, `samples[:-1]` rather than `samples[1:]`. The reasoning is
written into the docstring of `tools/sim/make_puzzle_stimulus.py`, because the
line itself looks arbitrary.

**Verdict: understood.**

---

## Extraction: a defect that survived every passing test

### 21. Routing landed on a cell terminal the LEF does not declare

**Symptom.** None, for a while. All four stage 2 gates passed. It surfaced only
when the union find fallback was built and disagreed with the KLayout extraction
on the puzzle: one extractor reported a net holding `nor3_2.C`, `and2_2.X` and a
pin it had invented a name for, `a31oi_2.$7`; a separate net held `a31oi_2.A1`
and `a311o_2.A1`, **two inputs and no driver at all**.

**Cause.** A cell input is a transistor gate, and a gate can be contacted from
li1 in more than one place. `a31oi_2` has two contacts on its A1 gate. The LEF
declares one as the pin; the other is not offered as a pin, and the router
landed a via stack on it anyway. Our connectivity starts at li1 and excludes
poly, so the two contacts look like two unrelated nets, and the signal that
really drives those inputs ended up in the wrong one.

**Fix.** `tools/common/cellnodes.py` reads from the PDK which li1 shapes of a
cell are the same terminal, through gate contacts only, and matches them against
the LEF's declared PORT geometry. Both extractors use it. See
`docs/02-connectivity.md` for the rule and its guard.

**Verdict: understood.** The uncomfortable part is what did not catch it. The
puzzle simulation replays 312 cycles of the published waveform and reproduces it
byte for byte — before the repair and after. A functional test on one input
vector says nothing about whether the structure is right, and this project had
been treating that gate as its strongest evidence.

### 22. The first repair dissolved `conb_1` into the rails

**Symptom.** The obvious fix for 21 is to extend the connectivity ladder down
through licon1 to poly, so two contacts on one gate merge. Tried, and it does
repair the defect while leaving the warm up bit for bit identical.

Measured on the puzzle it also moved 16 nets to fix one. `conb_1` ties its
constant outputs to the rails through poly, so `LO` merged into `VGND` and `HI`
into `VPWR`, and the extractor began reporting pins named `LO,VGND`.

**Cause.** Extending the stack is a global change to the connectivity model, and
the model's job is to treat cells as black boxes. Reaching through poly reaches
inside every cell, not only the one with the problem.

**Fix.** Rejected the stack change. The repair is per cell and carries a guard:
two *declared* pins of one cell are never the same net, and a grouping that says
they are gets discarded.

**Verdict: understood.** Worth recording as a near miss: the rejected fix passed
the warm up gate perfectly, which is exactly how it would have got in.

### 23. The guard did not fire, twice

**Symptom.** With the guard written, `conb_1` still came back with two
"undeclared pads" to be rewritten — the guard that was supposed to protect it
reported no conflict at all.

**Cause, first time.** The grouping ran one poly shape at a time. A single li1
shape can sit on two gates and tie them together, so the real groups are the
transitive closure and taking each gate alone misses the chain that joins
`conb_1`'s output to its rail.

**Cause, second time.** With transitive grouping in place it still did not fire,
and now reported the *wrong* conflict, `HI/LO`. Pin membership was being tested
against bounding boxes. `conb_1`'s ground shape is L shaped; its box reaches up
into `HI`'s rectangle while the polygon itself stays clear. The rail shapes were
being assigned to the wrong pin, or to none, and either way the conflict stayed
invisible.

**Fix.** Transitive grouping through a union find over li1 shapes, and exact
polygon intersection for pin membership with bounding boxes used only to skip
pairs that cannot meet.

**Verdict: understood.** The lesson is about safety mechanisms specifically: a
guard that has never fired has not been tested. Both faults were found by
checking that the guard fired on the one case known to need it, rather than by
observing that nothing had gone wrong.

---

## Normalisation: reaching for the wrong authority

### 24. Cell roles derived from the LEF and the cell name

**Symptom.** None. Stage 3 was written, the reasoning was written down, and it
looked sound. It surfaced because the user asked whether I was actually sure of
it, and whether it would survive a hardware engineer reading it.

**What was claimed.** That the clock could be read from the LEF's `USE CLOCK`
marker, and that reset versus set could be settled by requiring the pin name
(`RESET_B`) and the cell name (`dfrtp`) to agree, described as "two independent
sources".

**What is actually true**, once measured rather than argued:

- The pin name and the cell name are *not* independent. They are two expressions
  of one naming convention, written by the same people at the same time. And the
  convention does not decide the question: six cells in this library, `dfbbp_1`
  among them, carry **both** `RESET_B` and `SET_B`.
- `USE CLOCK` was fine. It was criticised on the strength of one cell,
  `lpflow_inputisolatch_1`, which marks `SLEEP_B` as a clock — which looked like
  a counterexample and is not: that cell is a latch and liberty independently
  gives it `clocked_on : SLEEP_B`. Compared across the whole library, LEF and
  liberty agree on the clock for all 429 cells.
- The real authority was never consulted. Liberty states all of it functionally:
  `clocked_on`, `next_state`, `clear`, `preset`, and `function` for every
  combinational output.

**The larger consequence.** Cells had been given to Yosys as blackboxes, on the
argument that stage 3 only needs connectivity. True for stage 3, and a dead end
after it: `yosys-smtbmc` cannot export a design of blackboxes to SMT2, because a
solver has to know what each cell computes. The docstring claimed this path
carried through to stages 4 and 6. It did not.

**Fix.** `tools/fetch_pdk.py` now also caches one liberty corner,
`tt_025C_1v80`, from the same pinned commit — 429 files, the corners differing
only in timing tables, none of which anything here reads.
`tools/common/liberty.py` reads the functional attributes and the cell
functions. The naming convention is still consulted, demoted to a cross check
that reports rather than decides.

**Verdict: retracted.** Recorded because the failure was not in the code, which
worked, but in stating a justification more confidently than the evidence
supported — and because no test would have caught it. A question did.

### 25. `bool("false")` is true, so every input read as a clock

**Symptom.** The new liberty reader marked `A1`, `A2`, `B1`, `C1` and `D1` of
`a2111o_1` as clock pins. Every input of every combinational cell in the library
came back as a clock.

**Cause.** This library encodes liberty booleans as JSON *strings*:
`"clock": "false"`. `bool("false")` is `True`, because the string is non-empty.

**How it was found.** Not by inspection. The reader was cross-checked against the
LEF's own clock marking on the whole library before being used, and that check
reported 414 cells disagreeing out of 429 — a number too large to be real. After
the fix it reports zero.

**Fix.** A `boolean()` helper that reads the string, with the failure mode
written into its docstring.

**Verdict: understood.** Worth keeping as the cleanest example in this document
of a cross check earning its cost: the defect was silent, produced a valid
netlist with nonsense annotations, and was caught within a minute of the
reader's first run by a comparison written for a different purpose.

---

## Answer keys: the corpus was wrong about itself

These three were found the same afternoon, by the same tool, on its first run:
`tools/verify_corpus.py`, which puts every fact a generator declared against
what stage 3 independently found in the gate level result. They are grouped
because the lesson is one lesson.

### 26. Six circuits declared a synchronous reset and had no reset at all

**Symptom.** `verify_corpus.py` reported twelve disagreements: every
`register_w*_sync` and `register_w*_en_sync`, in both mappings, declared a reset
and stage 3 found no flop with a reset pin.

**Cause.** `_sequential` branched on `async_reset` and `async_set` and let
everything else fall to an `else` that emits `always @(posedge clk)` with no
reset logic and no reset port. `sync` reached that `else`. The truth said
`reset: "sync"`, the RTL said nothing of the kind.

**Why it matters more than it looks.** These circuits are an *answer key*.
Stage 4's detectors were going to be scored against them, and six of them would
have been scoring against a fact that was not in the circuit. A detector
correctly reporting "no reset" would have been marked wrong.

**Fix.** The generator now emits what it declares: `if (!rst_n) q <= 0;` inside
a plain `posedge clk` block, which synthesises to reset logic in front of D and
a flop with no reset pin. The check distinguishes the two shapes rather than
asking whether a reset exists somewhere, because that weaker question is exactly
the one that passed for months.

**Verdict: understood.**

### 27. The first version of the check would have passed the broken corpus

**Symptom.** Not a symptom — this was caught by writing the check's own
failure test before trusting it.

**Cause.** The rule was written as "a circuit declaring any reset has flops with
a reset or set pin", which is true of asynchronous resets and false of
synchronous ones. It reported the right circuits for the wrong reason, and would
have gone on reporting them after the generator was fixed.

**Fix.** Two separate expectations: `async*` means every flop carries the pin,
`sync` means no flop does and a reset port exists instead. Both directions can
fail. `--selftest` corrupts a synchronous circuit into an asynchronous one and
confirms the rule notices.

**Verdict: understood.** The general form: a check that fires on a real defect
is not thereby a correct check.

### 28. The structural search for a held register is a lower bound, three ways

**Symptom.** Stage 3 finds a hold as a mux in front of D with the flop's own Q
on one leg. Against circuits that declare an enable, it finds 6 of 24.

**Cause.** Three distinct ones, all measured against a declared enable:

| Shape | What synthesis did |
|---|---|
| `register` | mux survives in front of D — found |
| `counter` | enable folded into the carry chain: `D[0] = q[0] ^ en`, `D[1] = q[1] ^ (q[0] & en)`. No mux exists |
| `register` + sync reset | mux survives as `mux2i`, but the reset's `nor2b` sits between it and D, and the search looks one cell back |

**Fix, and the part that is not a fix.** The check was changed from "a hold
survives as a mux", which is a claim about synthesis, to "the enable reaches the
data cone of the flops it holds", which is a claim about the circuit and holds
under every shape. The structural count is still reported, and the shapes that
defeat it are listed by name, so a *new* way of losing a hold fails the run
rather than blending into a rate.

**A fourth shape arrived within the hour, and it settles the question.** The
scale family's held register is `D = en ? (acc ^ lfsr) : outr`, and it maps to a
single `a21oi`, `Y = !B1 & (!A1 | !A2)`, with `en` on `A1` and `Q` arriving
through a `nor2` two cells back. The mux is not displaced, it does not exist.

That is not a fourth special case — it is the general one, and the three above
are the exceptions. A plain register keeps its mux only because the data leg is
a *port*. Once that leg is something the circuit computes, the mapper folds the
select into the logic that computes it, which is what a technology mapper is
for. The run failed on it, as designed, and the shape was written down with a
measurement behind it rather than a guess.

The real answer is stage 4's: whether a register holds is a question about
behaviour — is there an input assignment under which D equals Q — and no
enumeration of patterns closes it.

**Verdict: understood, and deliberately not fully fixed.** Making the structural
search cleverer would buy a fifth shape and hide the sixth.

---

## Scale, and a number that flattered us

### 29. Every test circuit was an order of magnitude below the target

**Symptom.** None. The corpus reported 4493 cells and 1074 state elements, which
sounds like plenty, and passed every gate.

**Cause.** The aggregate hid the distribution. Asked circuit by circuit rather
than in total:

| | flops | cells |
|---|---|---|
| largest corpus circuit | 32 | 125 |
| **median corpus circuit** | **4** | |
| the puzzle | 92 | 738 |

A detector scored on four-flop circuits says very little about ninety-two, and
two of the costs are not linear: grouping N flops into registers, and a miter
whose SAT instance grows with cone depth and width.

**How it was found.** By deliberately attacking our own numbers rather than
reporting them. Nothing failed; a question was asked that had not been asked.

**Fix.** A `scale_datapath` family that **brackets** the target rather than
approaching it — 90, 178 and 354 flops against the puzzle's 92, and 280, 561 and
1136 cells against its 738 — so a scaling problem shows up as a trend rather
than as one pass or fail. Stage 3 turns out to scale flat: 1.1 s at 280 cells,
1.4 s at 1136. Stage 4 is the open question.

**Verdict: understood.** The general form: a total is not a distribution, and
the statistic that matters for a test set is the size of its *hardest* member.

### 30. The scale circuit declared sixteen clock branches and used eight

**Symptom.** `verify_corpus.py` reported the largest scale circuit declaring 16
distinct clock nets and stage 3 finding 8.

**Cause.** The generator instantiated `branches` clock buffers but had only
eight independent `always` blocks to drive from them. The other eight buffers
fanned out to nothing and `opt_clean` removed them, correctly.

**Fix.** The shift register is cut into one segment per spare branch, so the
tree is used by construction: six fixed blocks plus ten shift segments at the
largest size. That also buys something the corpus wanted anyway — a single
logical register spanning ten of sixteen branches, which is the puzzle's shape
rather than a two-way split in a toy.

**Verdict: understood.** Worth recording because the check was written the day
before and caught a defect in the circuit written to exercise it.

### 31. Every inverter in the library was classified as a buffer

**Symptom.** None visible. Stage 3's clock root walk reported that no flip flop
in either target sat on an inverting clock path, and no corpus circuit could
contradict it.

**Cause.** `liberty.pin_of` read the active level off the first character of the
expression. This library writes a combinational output as
`function : "(!A)"` — parenthesised — while it writes the sequential fields
`clear`, `clocked_on` and `preset` bare. So the same function got `clear`
exactly right on all 107 sequential fields, and all 21 of the library's
inverters exactly wrong.

The consequence was narrow and completely silent. The walk still traced to the
correct root, because it walks *through* a transparent cell either way; only the
inversion parity was lost. Nothing that shipped before this session depended on
it — measured across the whole library, the fix changes 30 combinational
`function` results and no sequential field at all.

**How it was found.** Not by a failing test. By asking, of a rule that always
reported zero, whether it *could* report anything else — and finding that the
producer could not. The rule was passing because nothing was able to fail it,
which is the shape problem 23 is about, one level further down: there the check
could not see the case, here the check could not be given the case.

**Fix.** `liberty.unwrap` strips *enclosing* parentheses only, so `(A)&(B)` is
left alone rather than becoming `A)&(B`, and the level is read after unwrapping.
An `inverted_clock` family now puts half a register behind a real `clkinv`, so
the rule has a non-zero answer to be checked against.

**Verdict: understood.** The general form is worth stating: **a constant a check
always confirms is a check on nothing until something can make it vary.** Both
halves matter — a corpus that can produce the other answer, and a producer that
can report it.

### 32. The cross check compared nets by a name one side invents

**Symptom.** `stage3_crosscheck.py`, on its first run, reported all 16 of the
warm up's flip flops wired differently — and every role net as a mismatch of the
form `n00076` against `$371`.

**Cause.** Stage 2 renumbers the nets when it writes the Verilog. `netlist.json`
carries the extractor's own names, `netlist.v` carries `n000NN`, and comparing
the two by name finds every internal net missing.

**Fix.** Key a net on the set of `(instance, pin)` pairs on it — something both
sides compute and neither side chose. This is problem 12 and problem 14 for the
third time: **a name assigned by one of the two things being compared is not a
key.**

**Verdict: understood.** Notable only for how quickly the same shape came back
in a tool written specifically to be independent.

### 33. A failed build overwrote the answer key it failed to produce

**Symptom.** `verify_corpus.py` reported `0 circuits as 0 netlists, 0 rules, 0
uses` and `RESULT: pass`.

**Cause.** Docker Desktop was not running, so all 93 syntheses failed. The
builder reported every failure, then wrote `index.json` from the empty result,
replacing a good index. The verifier iterated over nothing and passed, because
zero disagreements out of zero checks is a pass.

**Fix.** The builder refuses to rewrite the index if any circuit failed, leaves
the existing one alone, and exits non-zero — and says so, naming Docker when
every failure mentions it.

**Verdict: understood.** Two shapes at once, both already in this document.
A green result read as evidence when it was silence, and a step whose *report*
was checked instead of its *product*. Worth the entry because the loss was
silent: nothing said the answer key had been destroyed, and stage 4's score
would have been measured against it.

### 34. The repository's best answer key went unused for five stages

**Symptom.** Stage 4's register grouping scored 116/126 on a synthetic corpus
and was declared done. Asked afterwards what ground truth existed and had not
been used, the answer was `puzzle/warmup/00_source.v` and
`puzzle/warmup/01_netlist.v` — the warm up's RTL and its reference gate netlist.

**What they contain.** `01_netlist.v` and `03_post_place_and_route.def` both
name every instance with the hierarchy it came from: `sr_a/_16_`, `add0/_31_`,
`cmp0/_02_`. That is an exact block partition of a real design — 16 cells in
`sr_a`, 16 in `sr_b`, 41 in `add0`, 3 in `cmp0`. The flops divide 8 and 8.

**What it says about stage 4.** The committed criterion answers "one register of
sixteen". It is wrong, and the criterion the corpus score ranked *last* is the
one that is right. Two shift registers sharing a clock, a reset and an enable
cannot be separated by any control signature, and no corpus circuit has that
shape — `two_clocks` differs in clock, `inverted_clock` in edge,
`composed_shift_accumulate` in structure.

**Cause.** Days were spent building a synthetic corpus to test detectors against,
while the real answer sat in the repository unopened. The stage documents were
written from the corpus score.

**Fix.** `tools/verify_blocks.py` maps the DEF's hierarchy onto the recovered
instances — keyed on position, orientation and cell, all 230 matching — and
scores stage 4 against it. It fails, and is recorded as failing.

**Verdict: understood.** This is problem 6 again at the scale of a whole stage:
*open the primary artifact before reasoning from a secondary one*. Problem 6 was
one file unread; this was the most authoritative file in the repository unread
while a substitute for it was constructed.

### 35. A score reported without its null model

**Symptom.** "116/126 netlists partitioned exactly" was written into `CLAUDE.md`
as a gate.

**Cause.** 108 of the corpus's 126 netlists hold exactly one register, so a
criterion that returns one group and does nothing else scores 108/126. The real
margin was eight netlists, and on the 18 where the question is not trivial the
criterion gets 8.

**Fix.** `--score` prints the null model beside the score, so it cannot be read
the old way again. The same principle belongs beside every score this project
produces.

**Verdict: understood.** A sibling of the rule this project already had — *a
passing test that was never able to fail is not evidence* — one step further
out: **a score a trivial implementation also achieves is not evidence either.**

### 36. Two gates that printed a verdict and always exited 0

**Symptom.** `stage4_registers.py --score` and `--compare` were listed as gates
in `CLAUDE.md`, were run by `review_packet.py` as gates, and both ended in an
unconditional `return 0`.

**How it was shown.** Replacing `control_groups` with "every flop is its own
register" -- a criterion that is wrong on 120 of the corpus's 126 netlists --
took the score from 116/126 to 6/126. The run printed the 6, printed a line
reading `of those 18, this criterion gets -102`, printed a paragraph explaining
that every miss was a circuit whose registers share their control signals, and
exited 0. The review packet rendered it **pass**.

**Cause.** Three separate things, all the same shape. The exit status was never
connected to the measurement. The non-trivial-subset figure was computed as
`18 - len(wrong)`, subtracting the single-register misses too, so it could go
negative. And the explanatory paragraph was printed unconditionally rather than
when the run supported it.

**Fix.** What each entry point is expected to measure is recorded in `RECORDED`
and `RECORDED_CRITERIA`, and a figure that moves in either direction fails --
below its recording as a regression, above it because an unexplained
improvement is a change to something and re-recording has to be a decision. The
subset figure is counted directly as hits among the multi-register netlists and
cannot go negative. The paragraph is said only when the misses support it, and
the over-splitting case says so instead. A fourth number went with them: the
per-target report quoted "48/63 against the control signature's 56/63", from a
corpus two sizes ago, which no run reproduced.

**Verdict: understood.** This is the project's own rule -- *a passing test that
was never able to fail is not evidence* -- applied to the thing doing the
passing rather than to the thing being tested. Every printed figure was
truthful. None of them was a gate.

### 37. Ten corruptions caught, five rules never seen to fail

**Symptom.** `verify_corpus.py --selftest` reported `RESULT: pass, every
corruption was caught`, over ten corruptions, and had done for several
sessions.

**Cause.** True, and read as something stronger. Between them the ten
corruptions tripped seven of the twelve rules; the other five had never been
seen to fail at all. The selftest asked the question from the corruptions' side
-- *was each one noticed* -- and never from the rules' side -- *was each rule
ever the one doing the noticing*. Two of the five are the rules the report
itself labels `always True` and `always 0`, which is the easiest place for a
rule to rot, because a constant that is always confirmed looks like a rule that
works. A third is `flops accounted for by the declared registers`, the rule
stage 4's entire corpus score rests on: a declared partition that does not add
up to the flop count would make `--score` a comparison against a wrong answer
key, and a neutered version of that rule passed every gate in the repository.

**Fix.** `--selftest` now counts coverage from the rules' side as well and names
any rule no corruption reaches. Five corruptions close the gap. For the two
constant rules the corruption makes the *found* value vary, since the declared
one cannot: a synchronous reset whose port has vanished, and a circuit declared
combinational whose graph has grown a flop.

**Verdict: understood.** Problem 23's shape at one remove. There the guard could
not see the case it existed for; here the selftest could not see which rules it
was not exercising, and the number it printed was large enough to look like
coverage.

### 38. The review packet's own three sections misreported

**Symptom.** `out/review.md` is the artifact an outside reviewer reads, and it
is generated, which makes every line in it look measured. Three sections were
reporting something other than what they said.

**The defect register showed zero of its rows.** The slice ended at
`register.index("---", start)`, which finds the `|---|---|---|---|` separator of
the summary table's own header, not the horizontal rule after it. Every packet
ever generated showed the heading, the header row, and none of the thirty five
rows underneath, above a sentence claiming 36 entries -- itself wrong, because
`count("\n### ")` counts one heading that is a discussion and not an entry.

**"Read by" was a substring search over basename stems**, and every row it
produced was wrong in one direction or the other. It credited `review_packet.py`
with reading all seven answer keys, because that file names them. It credited
twenty three tools with reading `puzzle.gds`, because the stem is `puzzle`. It
credited `verify_blocks.py` with `01_netlist.v`, which that tool mentions in its
opening paragraph and never opens. And it missed `stage2_nets.py`,
`stage2_unionfind.py` and `stack_sensitivity.py`, which reach the layouts
through `stage1_cells.TARGETS` and never name a path at all. This is the section
that exists *because* an answer key went unused for five stages, so a wrong
answer in it is worse than no section.

**A report was rendered as a passing gate.** `corpus_reach.py` is labelled "not
a gate" in `CLAUDE.md` and got the same **pass** cell as `compare_def.py`.

**stderr was captured and dropped**, so a tool dying through
`sys.exit("message")` produced a **FAIL** row above an empty output block.

**Fix.** The register slice ends at the horizontal rule, counts numbered
entries, and fails if the entry count and the summary row count disagree; the
`except` no longer swallows a slicing failure. "Read by" is an explicit
registry, and `verify()` re-derives every claim from the named tool's parsed
source -- docstrings excluded, which is what separates opening a file from
mentioning it, and TARGETS use requiring a subscript, because five tools import
it only to validate an argument. Rows declare gate or report and `verify()`
derives which from whether the tool's source holds any literal non-zero exit.
stderr is emitted in a marked block. If any claim does not hold, the packet is
not written.

**Verdict: understood.** Problem 6 in the tool that exists to prevent problem 6.
The packet was built so a reviewer would not have to trust the author's summary,
and then its own tables were not checked against anything -- because generated
output reads as measured, and three of those sections were prose with a
`for` loop in front of it.

### 39. `clock_nets` is the nets at the flop pins, not the clock tree

**Symptom.** Stage 6's first run stopped with `KeyError: 'clk'` while building
the transition relation: something was asking for the value of the clock port,
in a model where a cycle *is* a clock edge and the clock has no value.

**Cause.** The model drops clock tree cells, and it identified them as the cells
driving a net in `graph.json`'s `clock_nets`. That field holds the nets **at the
flop clock pins** and nothing else. The warm up's tree is
`clk -> n8 -> {n18, n41}` through three `clkbuf_16`; `clock_nets` is
`['n18', 'n41']` and `clock_roots` is `{'n5': 16}`, so the middle net n8 appears
in neither. The buffer driving it was modelled as ordinary logic, which made the
clock port a free variable the solver had to choose a value for.

**Fix.** The tree is walked backwards from each flop's clock pin to its root,
through the cells that drive it, rather than read off a field that answers a
different question. A clock net read by anything other than a flop's clock pin
is now reported and refused: that is a gated or sampled clock, which this cycle
model cannot represent at all.

**Verdict: understood.** The field is not wrong; it was read as though it named
the tree, and it names the leaves. Nothing before stage 6 needed the difference,
which is why five stages went by without it surfacing.

### 40. An equivalence proof that proved nothing, twice over

**Symptom.** The first miter between `01_netlist.v` and `graph.v` failed. So did
the second. The two designs are the same design.

**First cause.** The flops carry an asynchronous reset, and Yosys's SAT engine
has no model for `$adff`. Every proof step emitted
`No SAT model available for async FF cell ... Consider running async2sync`, and
the run failed for a reason with nothing to do with the netlists. `async2sync`
fixes it.

**Second cause.** With that fixed, `equiv_struct` proposed no correspondences at
all and `equiv_induct` ground through five induction steps and gave up: 0 of 153
points proven. The script used `prep -flatten`, and `prep` optimises. Two
designs optimised independently stop being structurally comparable, which is the
one thing `equiv_struct` needs. `proc; flatten; opt_clean` instead, and 153 of
153 prove in 1.5 seconds. A third cause sat under it: `equiv_struct` ignores
internal cell types by default, and after flattening every cell here is one, so
`-icells` is required for it to look at anything.

**Fix.** Both settings, with the measurement that chose them recorded in the
tool. Demonstrated able to fail: one `nand2_2` swapped for `nor2_2`, exit 1.

**Verdict: understood.** Worth its own entry because a failing equivalence check
looks exactly like a real inequivalence, and the temptation is to go looking for
the defect in the netlist rather than in the script.

### 41. A bounded model checker answering from a start state nothing has

**Symptom.** None, which is the problem. Stage 6 found a trace driving the warm
up's output high at depth 0 -- before any clock edge -- and would have written
it down.

**Cause.** The initial state was left free, which is the honest statement of a
chip whose power-up state is unknown, and asking `exists inputs, exists start
state: output high` is not the question. It lets the solver choose the state as
well as the inputs. Measured on the warm up, *every* depth from 0 to 7 returns a
trace of this kind. Each is a correct answer to what was asked and useless as an
answer to what was meant, and simulation from `x` would have rejected all of
them without saying why.

**Fix.** After each candidate, the opposite question: is there a start state
these same inputs fail from? Any such state is pinned as another copy of the
design sharing the input variables, and the search runs again. The loop ends
when no state defeats the trace, which makes it good from every power-up state.
Depth 8 is the first the warm up survives, and it uses no reset at all, because
eight shifts overwrite the registers -- which is also why baking in a reset
preamble would have been wrong rather than merely unnecessary.

**Verdict: understood.** The same shape as *a passing test that was never able
to fail*: a query that can be satisfied the easy way will be, and the fix is to
ask the harder question rather than to constrain the answer by hand.

### 42. The hold search identified a mux by its name, and one of them inverts

**Symptom.** None. This one had never fired, which is why it is worth an entry.

**Cause.** Stage 3 decides a register holds by looking for a mux in front of D
with the flop's own Q on a leg, and it found the mux with
`if "mux2" not in source["cell"]: continue`. That substring also matches
`mux2i`, and `mux2i` is an *inverting* mux:

    mux2   X = (A0&!S) | (A1&S)          passes A0, then A1
    mux2i  Y = (!A0&!S) | (!A1&S)        passes !A0, then !A1

A flop fed by a `mux2i` with its own Q on a leg does not hold. It toggles. The
annotation would have said "this register can keep its value" about a register
that inverts every cycle, and every later stage reads it that way.

**Why it never fired.** All 56 structurally found holds across the warm up and
the corpus are `mux2_1`. The corpus's one `mux2i` sits behind a synchronous
reset's `nor2b`, more than one cell back from D, so the search never reaches it.
Nothing in the repository could produce the wrong answer, which is why nothing
noticed the wrong rule.

**Fix.** The test is functional: for some pin S, the function with S=0 must be
identically some other pin, positively. Across the library's 429 cells exactly
four outputs pass it -- the four `mux2_*` -- and the three `mux2i_*` are
rejected. `stage3_crosscheck.py` applies the same rule by a different route,
scanning the whole truth table rather than testing cofactors.

**Demonstrated.** The corpus now holds `mux2i_witness`, a pre-mapped netlist
whose only purpose is to be rejected. Running the detector as it stood before
the fix -- checked out of git, not reimplemented -- against the same file:

    OLD, name based      1 hold(s): _02_ holds when low, through a mux2i_1
    NEW, function based  no holds

**Verdict: understood.** The circuit is not one anyone would write, which is
why no synthesised corpus entry could produce it and why the rule went eight
months unable to be wrong out loud. This is the repository's own standard --
*exercise a check against a known-bad input once, or it is only silence* --
applied to a rule rather than to a check.

### 43. The RTL reader found no flip flops in a design that is mostly flip flops

**Symptom.** `verify_annotations.py`, on its first run, reported
`16 found, 0 declared` and failed.

**Cause.** It read `reg` declarations out of each module's *body*, and
`00_source.v` declares its state in the port list:
`output reg [7:0] parallel_out`. Both shift registers were therefore empty and
the design declared no state at all.

**Fix.** The port list is searched as well as the body. A second one went with
it: the per-instance count was accumulated into a `set`, so `sr_a` and `sr_b` --
the same module twice -- collapsed into one entry and the tool declared 8 holds
in a design with 16.

**Verdict: understood.** Worth recording because of how it surfaced. The tool's
whole purpose is to disagree with stage 3 when stage 3 is wrong, and the first
thing it did was disagree with stage 3 when *it* was wrong -- loudly, with both
numbers printed side by side. A reader that had silently returned a plausible
count would have been believed.

### 44. The corpus flow had no `flatten`, and no circuit that needed one

**Symptom.** Adding `puzzle/warmup/00_source.v` to the corpus stopped stage 3
dead: `KeyError: 'shift_register'` from `functional_pins(lef[cell_type])`.

**Cause.** `stage5_corpus.synthesise` runs
`hierarchy -check -top NAME; proc; opt; fsm; opt; memory; opt; techmap; opt`
and never flattened. It never had to: every one of the 96 circuits this corpus
generates is a single module, so the mapped netlist held nothing but sky130
cells. `00_source.v` is three modules under `adder_demo`, the sub-modules
survived mapping as hierarchy, and stage 3 went looking for `shift_register` in
the PDK's LEF.

**Fix.** `flatten` after `proc`. A no-op on the other 96, and the corpus's
numbers moved only by what the new entry contributes.

**Verdict: understood.** Worth an entry for which circuit found it. The review
packet has carried a line for months saying the corpus is the answer key most
of stage 4 is scored against and the same author wrote both. This is that
sentence in miniature: a synthesis flow written alongside the circuits it
synthesises quietly inherits their shape, and the *only* entry whose Verilog
this author did not write is the one that broke it. One outside circuit found a
gap 96 inside ones could not.

### 45. One design, two mappings, three different register partitions

**Symptom.** `adder_demo` and `adder_demo__fast` are `puzzle/warmup/00_source.v`
put through the same synthesis and mapped two ways. The declared partition is
`[8, 8]` for both. Measured:

    base mapping                     fast mapping
      control signature  [16]          [11, 5]
      connected comps    [8, 8]        [3,2,2,2,2,1,1,1,1,1]
      colour refinement  [16]          sixteen singletons

**Cause.** The base mapping keeps all 16 of the design's holds as a `mux2` in
front of D and stage 3 finds every one. The fast mapping keeps 11. The five it
folds away are not distinguishable from the eleven by anything in the design --
`abc -fast` simply made a different choice on five bits -- but the control
signature includes the hold net, so five flops get a different signature from
their eleven neighbours and the criterion reports a register boundary that does
not exist.

**Why this is worse than the known weakness.** `CLAUDE.md` already says *a hold
stage 3 misses is a split missed here*, which describes under-splitting. This is
the other direction: a hold missed on *some* bits of one register **invents** a
split. A false boundary is worse than a missed one, because a missed boundary
leaves a group a person still has to read and a false one looks like an answer.

**Verdict: open.** Nothing here is fixed. The finding is that the structural
hold search is not merely a lower bound on holds but a source of spurious
register boundaries, and that the corpus's two-mapping design is what exposed
it -- one circuit, mapped twice, disagreeing with itself. `docs/04-detectors.md`
says the answer to "does this register hold" is functional and belongs to a
solver; this is the measurement that says it is not optional.

---

### 46. The block gate compared sizes, and would have passed the wrong eight bits

**Symptom.** None, for as long as it existed. `verify_blocks.py` compared
`sorted((len(m) for m in criterion(graph).values()), reverse=True)` against
`[8, 8]` and printed CORRECT when they matched. Adding a null model that deals
the sixteen flops alternately into two groups — eight bits of `sr_a` and eight
of `sr_b` in each, from no information whatsoever — produced `[8, 8]`, and the
tool printed it in the list of criteria that *get the warm up right*, inside its
own summary sentence.

**Cause.** A partition is a membership and the gate was reading a histogram of
it. `[8, 8]` says two groups of eight and says nothing about which eight. There
are 6435 ways to split sixteen flops into two eights and exactly one of them is
the answer; the gate accepted all of them.

**Fix.** Membership is compared as sets of frozensets, and NMI and purity are
printed beside the sizes. A right-sized wrong-membered answer is now labelled
`RIGHT SIZES, WRONG MEMBERS` and scores NMI 0.000, and the winners list filters
on membership rather than on sizes. The interleaved model **stays in the
criteria table permanently**, because a check whose failing column is never
exercised is the repository's own recorded mistake — *a passing test that was
never able to fail is not evidence* — and this is the column's known-bad input.

**Verdict: understood.** Worth its entry for how long it survived rather than
for its depth. This gate was written specifically because the corpus score was
being read as evidence when a null model achieved it, and it then made the same
class of mistake one level down: the corpus score could not fail because most
circuits do not ask the question, and this could not fail on membership because
it never looked. **The remedy for a measurement that cannot fail is not a
better measurement, it is a known-bad input standing beside it in the same
table.**

---

### 47. The cone's weight solve printed one answer out of twenty four

**Symptom.** Stage 4's structurally derived bit order disagreed with the
arithmetic weights `verify_cone.py` reports — position mapped onto significance
as `[0, 1, 2, 3, 5, 6, 4, 7]`, monotone in five places out of eight. Both
derivations looked right and one of them had to be wrong.

**Cause.** Neither was. `weigh()` iterated `permutations(powers)`, returned the
first assignment that made the cone equivalent to `a + b == 496`, and stopped.
**24 of the 40320 assignments are equivalent.** `a + b == 496` with both
operands below 256 forces the four low pairs and says nothing whatsoever about
which of the four high pairs carries which of 16, 32, 64 and 128 — 4! = 24 — so
the printed weights were an artefact of the order `permutations` emits.

The equivalence claim was never wrong: the cone *is* equivalent to `a + b ==
496` under an assignment of bit weights, which is what the file's docstring
says. What was wrong was reading the weights beside it as a derivation. A
search that stops at its first hit has determined that a solution exists, not
what it is.

**Fix.** `weigh` returns the whole solution set, the report says "24 of the
40320 possible ... one of them, and it is one and not the one", and the bit
order cross check asks whether stage 4's order is **among** them rather than
equal to one of them.

**Verdict: understood.** And the fix made the check stronger than it would have
been. Comparing a structural order to one arbitrary member of a 24-element set
would have been comparing it to an artefact of iteration order; comparing it to
the set is a real question, with 24 chances in 40320 of passing by luck. **The
disagreement between two independent derivations found a defect in the one that
looked more rigorous** — which is the entire argument for deriving anything
twice.

---

## The shapes these fall into

Forty seven problems, six recurring shapes.

**Reasoning from a secondary source while the primary sits there.** Problems 6,
7, 8, 9, and 24 — which is the same shape enlarged: not a secondary source
misread, but the primary source never fetched. The liberty data had been sitting
at the pinned commit the whole time.

**A key that does not identify.** Problems 12, 13, 14, 32. Position without
orientation; one format's anchor read as another's; a per-run id treated as
stable. All three produce a *plausible* result, which is why they survive.

**A filter that drops more than it says.** Problem 17, and problem 16 is the
same instinct pointed at a different risk. An allow-list is a claim about the
complete set of things you want, and that claim is usually not checked.

**Verifying the report instead of the artifact.** Problems 2 and 3. A pipeline's
exit code, a buffered log. Look at what exists, not at what claims to have
happened.

**Treating a symptom as its own cause.** Problems 18, 20, and the first attempt
at 14. Each looked like a defect in the thing being measured and was a defect in
the measuring.

A sixth shape appears once problems 21 to 23 are in, and 31 belongs to it too:
**a check that passes without having been exercised.** The puzzle simulation passed with a defect in
the netlist, and the guard in 23 reported no conflict because it could not see
the case it existed for. In both, a green result was read as evidence when it
was only silence. The remedy is the same in both: make the check fail on
purpose, once, against a case known to be bad.

### What actually caught these

Not care, and not review. Every real defect surfaced through one of three
mechanisms, all of which are cheap and mechanical:

1. **An independent second route to the same fact.** Transistor count versus
   layer absence; the reference netlist through the same testbench; the reset
   net's fanout confirming stage 1's flip-flop census; another solver's
   published counts confirming 728.
2. **A report of what did *not* match**, rather than dropping it. The 22
   unmatched puzzle placements were the PDK revision drift. Silently discarded,
   they would have been 22 logic cells missing from the netlist with no
   indication why.
3. **An expected thing being absent.** A flip-flop with no clock. A bus with no
   driver. Knowing what must be there is what makes absence visible.

The corollary was the argument for building stage 2's union find fallback even
though the existing extractor had never misbehaved: a second implementation
written against different assumptions is mechanism 1, applied to the stage that
carries the most risk.

It was built, and it found problem 21 within minutes of first running on the
puzzle — a defect four passing gates had not. That is the strongest evidence in
this document for the whole approach, so it is worth stating plainly: **the
fallback was not redundant work, and the reasoning that nearly skipped it was
"the primary path has never misbehaved."**

Problems 26 to 28 are mechanism 1 again, pointed at the corpus. The generator's
declaration and stage 3's reading of the synthesised result are two routes to
the same fact, and the corpus had been sitting there for a session with the two
never compared — because the comparison had been *made once, by hand, and
written into prose*: "the declared width equals the flip flops stage 3 finds, 86
out of 86." That sentence was true when written and had no way of staying true.
A measurement that is not a program is a measurement that happened once.

---

## Still open

**Problem 1**, the BuildKit network failure — worked around with
`DOCKER_BUILDKIT=0`, cause unknown.

**Problem 4**, Git Bash fork failures — avoided by using PowerShell, cause
unknown.

Neither blocks anything. Both are listed so that "we build with
`DOCKER_BUILDKIT=0`" reads as an unexplained workaround rather than a
preference.

The union find fallback that `docs/solver-pipeline.md` specifies for stage 2,
previously listed here as a skipped requirement, is now implemented:
`tools/stage2_unionfind.py`.
