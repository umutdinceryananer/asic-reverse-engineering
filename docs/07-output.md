# Stage 7, output extraction

Stage 6 finds an input sequence that drives the success output high. That is not
the answer. The submission form asks for *"the string value you recovered from
the chip"*, and the announcement is explicit about how it is obtained:

> "The output generator is safe to ignore during your initial
> reverse-engineering steps, but you'll need to simulate it to get your final
> answer."

So the last stage is not another solver. It is the simulation that already
exists, asked a different question: put the trace back through the netlist and
read the output bus, cycle by cycle.

Everything here was built and gated on `warmup` and on `synth`. The puzzle run
is the author's, and no number in this document was measured on it.

## What was built

| Tool | What it does |
|---|---|
| `tools/sim/harness.py` | one Icarus driver and one cycle model, shared |
| `tools/stage7_output.py` | the trace replayed, the bus read, the bytes decoded |
| `tools/verify_output.py` | the gate: corpus strings, declared before the run |
| `streamer` corpus family | two circuits whose string is known in advance |

### One driver, not two

`tools/sim/replay.py` already put a solver trace through **stage 2's** netlist
under the PDK's own cell models. Stage 7 wants that same simulation and a
different question asked of it, so the parts that must not drift -- how a cycle
is laid out in time, and how the cell models are put in front of Icarus -- moved
into `tools/sim/harness.py`, and both tools call it. `replay.py` still writes its
own testbench, because asserting a property and printing the solver's prediction
beside every cycle is a different job from sampling a bus.

The cycle model is unchanged and is now written down in exactly one place:

    inputs move while the clock is low -> settle -> sample -> rising edge

so the sample at cycle *t* is a function of the inputs at *t* and of the state
left by *t* edges. That is what `stage6_invert.py`'s `S(t)` means, and it is what
the VCD's zero delay dump already gives, since an output change is listed
*before* the clock change at the same timestamp.

Writing the second consumer of that harness immediately found a defect in the
first, `docs/problems.md` 52: `replay.py` declared every output port as a scalar
wire. The warm up's only output is one bit, so nothing had ever disagreed; the
puzzle's `O[7:0]` would have been connected on bit 0 with seven bits floating,
at the last step of the pipeline, with no gate able to notice because no gate
runs on the puzzle. Both testbench writers now take their widths from
`harness.port_widths`, which reads the netlist's own declarations.

## The two knobs, and why they are printed rather than assumed

Neither of these can be derived from anything this repository has read. Both
change the answer. So both are arguments, and both -- **including the defaults**
-- are printed with every result and written into `output.json`.

### `--extend N`

The trace ends at the cycle the property holds. A string streaming out one byte
per cycle is not obliged to have finished by then, or to have started. Nothing in
the pipeline knows how long it is. `--extend` keeps clocking for N further
cycles; the table marks which cycles were trace and which were extension.

### `--after <policy>`

Once the trace runs out, something has to drive the inputs.

| Policy | What the extension cycles drive |
|---|---|
| `hold-last` *(default)* | the last row of the trace, repeated |
| `zeros` | every input low |
| `port=value,...` | the last row, with the named ports overridden |

**Why `hold-last` is the default.** The trace's last row is the only input
assignment known to be consistent with the property holding, and a design that
streams after success most plausibly does so while whatever got it there stays
put. That is a plausibility argument and not a derivation, which is exactly why
the policy is named in the output rather than applied quietly.

**It is not a cosmetic choice.** The same warm up trace, extended four cycles
three different ways, gives three different answers past cycle 8:

| `--after` | the row it drives | S at cycles 9..12 |
|---|---|---|
| `hold-last` | `A=0, B=0, en=0, rst_n=1` | `1 1 1 1` |
| `zeros` | `A=0, B=0, en=0, rst_n=0` | `0 0 0 0` |
| `en=1,A=1` | `A=1, B=0, en=1, rst_n=1` | `1 0 0 0` |

`zeros` drops `rst_n`, which is active low, so the asynchronous reset clears the
design one cycle later. `en=1` lets the shift registers keep loading and the sum
moves off 496. `hold-last` holds. A default that hid itself would have been a
guess wearing a result's clothes.

A per-port policy starts from `hold-last` and overrides only what it names, so
naming one port says nothing accidental about the others, and the exact resulting
row is printed underneath.

## What it does on the warm up

```
$ python tools/stage7_output.py warmup --extend 4
target warmup
  solution   out/warmup/solution.json   depth 8, 9 cycles
  under test out/warmup/netlist.v   module adder_demo
  property   S is 1 at cycle 8
  extend     4 cycle(s) past the trace, 13 simulated in total
  after      hold-last: the last row of the trace, repeated
             A=0, B=0, en=0, rst_n=1
  stream     NONE   (this design has no multi-bit output port)
```

**`NONE` is the correct answer here, not a failure.** The warm up's only output
is `S`, one bit. The stream port is chosen by *width from the netlist* rather
than by the name `O`, because the name is a fact about the puzzle and this tool
has to run on a target that does not have it. Where several outputs tie for
widest, it refuses and asks for `--port`.

So the warm up exercises everything about stage 7 except the decoding: the
replay, the extension, the policy, the per cycle table, `output.json`. The
decoding is gated somewhere else, and had to be.

## The gate: strings that were known before the simulation ran

On the puzzle there is no way to check what stage 7 read -- if there were, the
puzzle would be solved. So the check is made where the answer is already written
down. The corpus gained a `streamer` family: circuits that emit a declared ASCII
string one byte per cycle after a one cycle trigger, then go quiet.

| Circuit | String | Bytes | Registers |
|---|---|---|---|
| `streamer_hello` | `HELLO WORLD` | 11 | `[7, 4]` |
| `streamer_escape` | `OK\a 42\n` | 7 | `[7, 3]` |

Two, not one, because a decoder that hard-wired a length would pass on a single
instance. Different lengths, so the index register is a different width. And one
carrying two non-printable bytes -- `0x07` and `0x0a` -- because the escape path
is the part a printable-only string would leave untested.

The machine is an index and a ROM, which is the smallest thing with the property
stage 7 needs: **the stream starts at a cycle nothing outside the circuit
announces, runs for a length nothing outside the circuit announces, and goes
quiet afterwards.**

### Two declared numbers that are derived from the string, not from the netlist

An answer key read back out of the result is not an answer key. Both of these are
computed by the generator, from its own arguments, before Yosys runs:

    live bits   a bit position that is 0 in every byte and 0 at idle is a flop
                whose D is constant, and `opt` removes it. Every byte of an
                ASCII string has bit 7 clear, so the output register is seven
                flops and O[7] arrives from a `conb_1`. Both circuits declare
                seven, and stage 3 finds seven.
    index bits  the index counts 0 .. len, so `len.bit_length()`.

The cycle numbers are declared the same way, from the machine's own shape rather
than from a run. `go` is taken while the index is 0, one edge moves it to 1, the
next edge loads the ROM, and the harness samples a cycle before its own edge --
so the first byte is at cycle 3 and the last at `3 + len - 1`. The busy flag
**leads the data by one cycle**, because it reads the index while the byte is
still an edge away from the output register. That offset is declared rather than
smoothed over: a flag that happened to align with the stream would let a check
pass that had the offset wrong.

### What is compared

Four things, and the second and third are the ones that matter:

1. **The bytes, element by element**, against the declaration. Not the rendered
   text -- comparing text against text would be comparing the decoder with
   itself.
2. **Where the stream is.** Found the way stage 7 finds it on a target: from the
   first byte that is not the idle byte to the last. A stream that landed in the
   right place by arriving early and being padded passes (1) and fails this.
3. **The rendering round trips.** `verify_output.unescape` is a second, small
   implementation that turns the rendered text back into bytes and shares no code
   with `stage7_output.escape`. It refuses anything it does not recognise rather
   than guessing. A decoder that dropped a control byte, or rendered two
   different bytes the same way, fails here and would pass a comparison of text
   against text.
4. **The busy flag**, against the declared cycles.

Every mapping of every streamer must pass: a stream that survived only one
particular `abc` run was a property of that run.

```
$ python tools/verify_output.py
  ok    streamer_hello[base]         11 bytes at cycles 3..13   'HELLO WORLD'
  ok    streamer_hello[fast]         11 bytes at cycles 3..13   'HELLO WORLD'
  ok    streamer_escape[base]         7 bytes at cycles 3..9   'OK\a 42\n'
  ok    streamer_escape[fast]         7 bytes at cycles 3..9   'OK\a 42\n'

RESULT: pass, 2 circuit(s) as 4 netlist(s), every byte exact and every escape read back.

$ python tools/verify_output.py --selftest
  all 4 netlist(s) decode exactly

  caught  one byte of the decoded stream changed, at cycle 8, on streamer_hello[base]
  caught  one byte of the declared string changed, at index 5, on streamer_hello[base]
  caught  a raw control byte left in the rendering
  3/3 caught
```

The third corruption is the round trip's own known-bad input, and it is the one
that would not exist without `unescape`: a renderer that passed a control byte
through raw produces text that *looks* like the string and cannot be read back.

## The author's run

After stage 6 has written a solution, the whole of stage 7 is one line:

```
python tools/stage7_output.py puzzle --extend 64
```

and, once the shape of the stream is visible, the same line with the policy made
explicit:

```
python tools/stage7_output.py puzzle --extend 64 --after zeros
python tools/stage7_output.py puzzle --solution out/puzzle/solution_post_reset.json --extend 64
```

`docs/06-inversion.md` says which solution file the puzzle run should use and
why; stage 7 takes whichever one is named.

### What to look at first, in this order

1. **The `stream` line.** It should say `O`, chosen as the widest output at 8
   bits. If it says `NONE`, the netlist has no bus and something is wrong
   upstream, not here.
2. **The cycle the property holds**, printed in the header, against the cycle the
   table shows `success` going high. They must agree -- and if they do not, that
   is `sim/replay.py`'s job to report, not this tool's. Run the replay first.
3. **Where the byte stream starts.** Before the success cycle, at it, or after
   it. All three are possible and they mean different things: a stream that
   starts *before* success was already running and the property cycle is not the
   beginning of the answer.
4. **Whether `--extend` was needed, and how far.** If the last non-idle byte is
   the last simulated cycle, the stream was cut off -- raise `--extend` and run
   again until the tail is idle. **The trimmed span must end before the last
   simulated cycle**, or the answer is a prefix.
5. **Whether the policy changed it.** Run it twice, `hold-last` and `zeros`. If
   the two agree, the stream does not depend on what happens after the trace and
   there is nothing to decide. If they disagree, the disagreement is the
   interesting thing and belongs in the writeup.
6. **`\?` in the rendering.** That is a cycle the simulation left at `x` or `z`,
   which is not a byte. It means the trace has not flushed the design's state at
   that point, and it must not be read as a character.

### What stage 7 does not do

**It never interprets the string.** It reports the bytes the bus carried, cycle
by cycle, and renders them with everything unprintable escaped. Which of those
bytes are the answer, and what the answer means, is the author's reading.
`CLAUDE.md`'s working split puts *"identify what the circuit computes"* on the
other side of the line, and this is the last tool before it.

Two smaller limits, stated because they look like results:

- **The idle byte is a convention, not a derivation.** Trimming runs from the
  first byte that is not `0x00` to the last. The untrimmed per cycle list is what
  `output.json` carries first, and the rule is printed under the trimmed
  rendering every time.
- **The gate says stage 7 reads a stream correctly where a stream was put there
  on purpose.** It does not say the puzzle emits one. Nothing in this repository
  can say that before the author runs it.

## `output.json`

Written to `out/<target>/output.json`. It carries the policy and the exact row it
produced, the per cycle inputs and outputs, the raw byte list with `null` where
the simulation held `x`, the rendering, and the trimmed span with the rule that
produced it. Everything the printed table shows, and the inputs that produced it,
so a reading can be re-derived without re-running the simulation.
