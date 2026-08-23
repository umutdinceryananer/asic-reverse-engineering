"""Stage 5, synthetic corpus. Circuits whose answer we already know.

Stage 4 will write detectors: algorithms that say "these eight flops are a
counter". On the puzzle there is no way to check such a claim, because if we
could check it we would not need the detector. So the test set has to be built
first, out of circuits whose answer is known because we wrote them.

`docs/solver-pipeline.md` is explicit that this comes *before* the detectors:
"detectors written without a test set cannot be validated."

## What the corpus has to be, and what it cannot be

It cannot be complete. A puzzle designed to be reverse engineered is not obliged
to contain textbook blocks, and no list of families can be proven to cover it.
Three things are done about that, none of which is guessing harder.

**Functional detection over structural.** The spec calls the miter check "the
more reliable of the two": synthesis rewrites structure but preserves function,
so a block that no longer looks like an adder still behaves as one. The corpus
is therefore not only a test set, it is the *reference library* those miters
compare against. That also bounds what can ever be named: a miter needs
something to compare with, so a structure absent from this corpus can be found
unexplained but not identified.

**Negative controls.** A corpus of only positive examples measures sensitivity
and never specificity. A detector that shouts "counter" at every register scores
perfectly on a corpus of counters. So the corpus carries circuits that must
*not* trigger a given detector, and stage 4 is scored on both.

**Composition.** Synthesis merges logic across module boundaries, which the spec
names as a failure mode. Blocks standing alone are the easy case; the corpus
also holds blocks feeding each other, so a detector is tested on the case it
will actually meet.

## Matching the target's vocabulary

Each circuit is synthesised through the same Yosys flow onto the same PDK, so
the cell mix resembles what stage 2 recovers rather than a set of generic gates.
The reconstructed liberty excludes the low power cell families, which belong to
a flow this design did not use; it is not narrowed to the puzzle's own 67 cell
types, because tuning the test set to the target would make the scores
meaningless.

Usage:
    python tools/stage5_corpus.py              # generate, synthesise, graph
    python tools/stage5_corpus.py --list       # what would be generated
"""

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage3_graph
from common import liberty
from common.lef import load as load_lef
from stage1_cells import PDK_DIR

IMAGE = "gds-teardown-eda:latest"
RTL_DIR = "synth"
OUT_DIR = "out/synth"
LIB_PATH = f"{OUT_DIR}/sky130_fd_sc_hd.lib"

# Circuits are assigned to the held out split by a fixed rule rather than by a
# random draw, so that "held out" means the same thing on every machine and in
# every rerun. Every third variant of each family is withheld.
HELD_OUT_EVERY = 3


# --- generators ------------------------------------------------------------
#
# Each returns (verilog, truth). `truth` is what stage 4 has to recover: the
# family, the parameters, and which ports carry what. It is the answer key, so
# it is written from the generator's own arguments and never inferred back out
# of the result.

def register(width, enable, reset):
    body = "q <= d;" if not enable else "if (en) q <= d;"
    return _sequential("register", f"register_w{width}"
                       f"{'_en' if enable else ''}_{reset}",
                       width, enable, reset, body,
                       ports={"d": f"[{width-1}:0]", "q": f"[{width-1}:0]"},
                       truth={"family": "register", "width": width,
                              "enable": enable, "reset": reset})


def shift_register(width, direction, reset):
    if direction == "left":
        body = f"q <= {{q[{width-2}:0], si}};"
    else:
        body = f"q <= {{si, q[{width-1}:1]}};"
    return _sequential("shift_register",
                       f"shift_{direction}_w{width}_{reset}",
                       width, False, reset, body,
                       ports={"si": "", "q": f"[{width-1}:0]"},
                       truth={"family": "shift_register", "width": width,
                              "direction": direction, "reset": reset,
                              "serial_input": "si"})


def counter(width, direction, enable, reset):
    step = "+ 1'b1" if direction == "up" else "- 1'b1"
    body = f"q <= q {step};"
    if enable:
        body = f"if (en) {body}"
    return _sequential("counter",
                       f"counter_{direction}_w{width}"
                       f"{'_en' if enable else ''}_{reset}",
                       width, enable, reset, body,
                       ports={"q": f"[{width-1}:0]"},
                       truth={"family": "counter", "width": width,
                              "direction": direction, "enable": enable,
                              "reset": reset})


def lfsr(width, taps, style):
    if style == "fibonacci":
        feed = " ^ ".join(f"q[{t}]" for t in taps)
        body = f"q <= {{q[{width-2}:0], {feed}}};"
    else:
        terms = [f"q[{t}] ^ q[{width-1}]" if t in taps else f"q[{t}]"
                 for t in range(width - 1)]
        body = f"q <= {{{', '.join(reversed(terms))}, q[{width-1}]}};"
    return _sequential("lfsr", f"lfsr_{style}_w{width}",
                       width, False, "async_set", body,
                       ports={"q": f"[{width-1}:0]"},
                       truth={"family": "lfsr", "width": width,
                              "taps": taps, "style": style})


def accumulator(width):
    return _sequential("accumulator", f"accumulator_w{width}",
                       width, True, "async_reset", "if (en) q <= q + d;",
                       ports={"d": f"[{width-1}:0]", "q": f"[{width-1}:0]"},
                       truth={"family": "accumulator", "width": width,
                              "enable": True})


def serial_adder(width):
    """One bit of a sum per clock, which is what a serial input implies.

    The puzzle's `I` port is one bit wide, so whatever it does with its input
    does it a bit at a time. Textbook corpus circuits take their operands in
    parallel and would leave that whole shape untested.
    """
    name = f"serial_adder_w{width}"
    verilog = f"""module {name} (input clk, input rst_n, input a, input b,
                  output so, output reg carry);
  assign so = a ^ b ^ carry;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) carry <= 1'b0;
    else carry <= (a & b) | (a & carry) | (b & carry);
endmodule
"""
    return verilog, {"family": "serial_adder", "width": width,
                     "serial_inputs": ["a", "b"], "serial_output": "so"}


def crc(width, poly):
    """An LFSR with the input mixed in, which is what a stream checker is."""
    name = f"crc_w{width}"
    terms = []
    for bit in range(width):
        if bit == 0:
            terms.append("feedback")
        elif (poly >> bit) & 1:
            terms.append(f"q[{bit-1}] ^ feedback")
        else:
            terms.append(f"q[{bit-1}]")
    assign = ", ".join(reversed(terms))
    verilog = f"""module {name} (input clk, input rst_n, input si,
                  output reg [{width-1}:0] q);
  wire feedback = q[{width-1}] ^ si;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= {width}'d0;
    else q <= {{{assign}}};
endmodule
"""
    return verilog, {"family": "crc", "width": width, "polynomial": poly,
                     "serial_input": "si"}


def adder(width, carry):
    name = f"adder_w{width}{'_cio' if carry else ''}"
    if carry:
        verilog = f"""module {name} (input [{width-1}:0] a, input [{width-1}:0] b,
                  input ci, output [{width-1}:0] s, output co);
  assign {{co, s}} = a + b + ci;
endmodule
"""
    else:
        verilog = f"""module {name} (input [{width-1}:0] a, input [{width-1}:0] b,
                  output [{width-1}:0] s);
  assign s = a + b;
endmodule
"""
    return verilog, {"family": "adder", "width": width, "carry": carry}


def subtractor(width):
    name = f"subtractor_w{width}"
    return f"""module {name} (input [{width-1}:0] a, input [{width-1}:0] b,
                  output [{width-1}:0] d, output borrow);
  assign {{borrow, d}} = a - b;
endmodule
""", {"family": "subtractor", "width": width}


def comparator(width, kind):
    op = {"eq": "==", "lt": "<", "gt": ">"}[kind]
    name = f"comparator_{kind}_w{width}"
    return f"""module {name} (input [{width-1}:0] a, input [{width-1}:0] b,
                  output r);
  assign r = (a {op} b);
endmodule
""", {"family": "comparator", "width": width, "kind": kind}


def multiplexer(width, inputs):
    select = max(1, (inputs - 1).bit_length())
    name = f"mux_w{width}_n{inputs}"
    lines = [f"module {name} (input [{select-1}:0] s,"]
    lines += [f"  input [{width-1}:0] d{i}," for i in range(inputs)]
    lines.append(f"  output reg [{width-1}:0] y);")
    lines.append("  always @(*) case (s)")
    for i in range(inputs):
        lines.append(f"    {select}'d{i}: y = d{i};")
    lines.append(f"    default: y = {width}'d0;")
    lines.append("  endcase")
    lines.append("endmodule")
    return "\n".join(lines) + "\n", {"family": "multiplexer", "width": width,
                                     "inputs": inputs}


def decoder(bits):
    name = f"decoder_b{bits}"
    return f"""module {name} (input [{bits-1}:0] a, input en,
                  output [{2**bits-1}:0] y);
  assign y = en ? ({2**bits}'d1 << a) : {2**bits}'d0;
endmodule
""", {"family": "decoder", "input_bits": bits, "outputs": 2 ** bits}


def fsm(states, encoding):
    """A ring of states that advances on `go` and flags the last one.

    The encoding is passed to Yosys as an attribute rather than written by hand,
    because the point of having both variants is to see the same behaviour laid
    out two different ways: binary packs the state into log2(N) flops, one-hot
    spends one flop per state. A detector that only recognises one of them has
    learnt the encoding rather than the machine.
    """
    identifier = encoding.replace("-", "")
    name = f"fsm_s{states}_{identifier}"
    bits = max(1, (states - 1).bit_length())
    lines = [f'(* fsm_encoding = "{encoding}" *)',
             f"module {name} (input clk, input rst_n, input go, "
             "output reg done);",
             f"  reg [{bits-1}:0] state;",
             "  always @(posedge clk or negedge rst_n)",
             f"    if (!rst_n) begin",
             f"      state <= {bits}'d0;",
             "      done  <= 1'b0;",
             "    end else begin",
             "      case (state)"]
    for current in range(states):
        following = (current + 1) % states
        if current == 0:
            step = f"go ? {bits}'d{following} : {bits}'d0"
        else:
            step = f"{bits}'d{following}"
        lines.append(f"        {bits}'d{current}: state <= {step};")
    lines += [f"        default: state <= {bits}'d0;",
              "      endcase",
              f"      done <= (state == {bits}'d{states - 1});",
              "    end",
              "endmodule"]
    return "\n".join(lines) + "\n", {"family": "fsm", "states": states,
                                     "encoding": encoding}


def streamer(label, text):
    """A block that emits a declared string one byte per cycle, then idles.

    Stage 7 turns a winning input sequence into the string the chip prints, and
    the announcement says the output generator has to be *simulated* to get the
    final answer. Every other circuit here exists so a stage 4 detector can be
    scored; this one exists so stage 7 can be, and it is the only family whose
    answer key is a string rather than a shape.

    The machine is an index and a ROM, which is the smallest thing that has the
    property stage 7 needs: the byte stream starts at a cycle nothing outside
    the circuit announces, runs for a length nothing outside the circuit
    announces, and goes quiet afterwards. `idx` doubles as the state -- 0 is
    idle, k emits byte k-1 -- so there is no separate run bit to be re-encoded
    by the `fsm` pass.

    **Two declared numbers here are derived from the string rather than from the
    netlist**, which is what keeps this an answer key:

      live bits   a bit position that is 0 in every byte *and* 0 at idle is a
                  flop whose D is constant, and `opt` removes it. Every byte of
                  an ASCII string has bit 7 clear, so the output register is
                  seven flops and O[7] arrives from a `conb_1`. Computed from
                  the bytes, before synthesis, not read back out of the result.
      index bits  the index counts 0 .. len, so `len.bit_length()`.

    The cycle the first byte appears on is `first_byte_cycle` below and is fixed
    by the machine, not by the string: `go` is taken while idx is 0, one edge
    moves idx to 1, the next edge loads the ROM, and `tools/sim/harness.py`
    samples a cycle before its own edge. Three.
    """
    data = list(text.encode("ascii"))
    last = len(data)
    bits = max(1, last.bit_length())
    live = sum(1 for bit in range(8) if any(b >> bit & 1 for b in data))
    name = f"streamer_{label}"

    lines = [f"module {name} (input clk, input rst_n, input go,",
             "  output [7:0] O, output busy);",
             f"  reg [{bits-1}:0] idx;",
             "  reg [7:0] outr;",
             "  reg [7:0] rom;",
             "",
             "  always @* case (idx)"]
    for offset, byte in enumerate(data):
        lines.append(f"      {bits}'d{offset + 1}: rom = 8'd{byte};")
    lines += ["      default: rom = 8'd0;",
              "    endcase",
              "",
              "  always @(posedge clk or negedge rst_n)",
              f"    if (!rst_n) begin idx <= {bits}'d0; outr <= 8'd0; end",
              "    else begin",
              "      outr <= rom;",
              f"      if (idx == {bits}'d{last}) idx <= {bits}'d0;",
              f"      else if (idx != {bits}'d0 || go) idx <= idx + 1'b1;",
              "    end",
              "",
              "  assign O = outr;",
              f"  assign busy = (idx != {bits}'d0);",
              "endmodule"]
    return "\n".join(lines) + "\n", {
        "family": "streamer", "label": label,
        # The answer key. `bytes` is authoritative and `string` is the same
        # thing rendered, because a string is the field a person reads and a
        # byte list is the field a comparison can be exact about.
        "string": text, "bytes": data, "length": len(data),
        "trigger": "go", "output": "O", "busy": "busy",
        "idle_byte": 0, "first_byte_cycle": 3,
        # The busy flag leads the data by a cycle, because it reads the index
        # while the byte is still one edge away from the output register. Said
        # here rather than smoothed over: a flag that happened to align with the
        # stream would let a check pass that had the offset wrong.
        "busy_first_cycle": 2, "busy_last_cycle": 1 + len(data),
        "registers": [live, bits], "flops": live + bits,
        "reset": "async_reset", "clock_roots": 1,
        "note": "stage 7's ground truth: a string that is known before the "
                "simulation runs"}


# --- negative controls ------------------------------------------------------
#
# These exist to be *not* detected. Without them a detector that fires on
# everything scores perfectly.

def parallel_register(width):
    """A register whose input comes from outside. Not a counter, not a shift."""
    verilog, truth = register(width, False, "async_reset")
    truth = {"family": "register", "width": width, "enable": False,
             "reset": "async_reset",
             "must_not_detect": ["counter", "shift_register", "lfsr"]}
    return verilog.replace("module register_", "module negctl_register_"), truth


def xor_tree(width):
    """Dense XOR logic that is not an LFSR, because it holds no state."""
    name = f"negctl_xor_tree_w{width}"
    return f"""module {name} (input [{width-1}:0] a, output y);
  assign y = ^a;
endmodule
""", {"family": "xor_tree", "width": width,
      "must_not_detect": ["lfsr", "counter", "adder"]}


def scrambled_logic(width):
    """Arbitrary combinational logic with an adder-like cell mix and no meaning."""
    name = f"negctl_scrambled_w{width}"
    terms = " | ".join(f"(a[{i}] & ~b[{(i * 3) % width}])" for i in range(width))
    return f"""module {name} (input [{width-1}:0] a, input [{width-1}:0] b,
                  output [{width-1}:0] y);
  assign y = {{a[{width-1}:1] ^ b[{width-2}:0], {terms}}};
endmodule
""", {"family": "scrambled_logic", "width": width,
      "must_not_detect": ["adder", "subtractor", "comparator", "counter"]}


# --- composed ---------------------------------------------------------------
#
# Synthesis merges logic across module boundaries, so a detector that only ever
# saw isolated blocks has not been tested on the case it will meet.

def clock_tree(width, branches):
    """A register whose bits are clocked from different branches of a tree.

    The puzzle distributes its clock through sixteen `clkbuf_8` branches, so
    bits of one logical register do not share a clock *net*. A detector that
    groups flops by the net their CLK reaches would split that register into
    sixteen pieces and find nothing.

    `clkbufmap` inserts one buffer per clock net and cannot split fanout, so the
    tree is written here in the RTL, which is the only place this pipeline can
    put it without a real clock tree synthesis tool. It is a one level tree
    rather than the puzzle's, which is enough to make the failure visible: a
    detector that survives this will not group by clock net.
    """
    name = f"clock_tree_w{width}_b{branches}"
    per = max(1, width // branches)
    lines = [f"module {name} (input clk, input rst_n, input [{width-1}:0] d,",
             f"  output [{width-1}:0] q);"]
    for branch in range(branches):
        lines.append(f"  wire clk_b{branch};")
        lines.append(f"  {CLOCK_BUFFER} cb{branch} (.A(clk), .X(clk_b{branch}));")
    for branch in range(branches):
        low = branch * per
        high = min(width, low + per) - 1
        if low > high:
            continue
        lines.append(f"  reg [{high}:{low}] r{branch};")
        lines.append(f"  always @(posedge clk_b{branch} or negedge rst_n)")
        lines.append(f"    if (!rst_n) r{branch} <= 0; "
                     f"else r{branch} <= d[{high}:{low}];")
        lines.append(f"  assign q[{high}:{low}] = r{branch};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n", {
        "family": "clock_tree", "width": width, "branches": branches,
        "note": "one logical register spread over several clock nets"}


CLOCK_INVERTER = "sky130_fd_sc_hd__clkinv_1"


def two_clocks(width):
    """Two independent clock domains, so "one clock root" is not a tautology.

    Every other circuit in the corpus is single clock, which means the rule
    `verify_corpus.py` uses to catch a broken root walk -- exactly one clock
    root -- had only ever been asked to confirm the number 1. That tests
    under-merging and never over-merging: a walk that collapsed every clock in
    the design into one root would have passed on all 86 circuits.

    Here it must find two, and the two are genuinely independent ports rather
    than branches of one tree.
    """
    name = f"two_clocks_w{width}"
    half = width // 2
    lines = [f"module {name} (input clk_a, input clk_b, input rst_n,",
             f"  input [{width-1}:0] d, output [{width-1}:0] q);",
             "  wire ca, cb;",
             f"  {CLOCK_BUFFER} cba (.A(clk_a), .X(ca));",
             f"  {CLOCK_BUFFER} cbb (.A(clk_b), .X(cb));",
             f"  reg [{half-1}:0] ra, rb;",
             "  always @(posedge ca or negedge rst_n)",
             f"    if (!rst_n) ra <= 0; else ra <= d[{half-1}:0];",
             "  always @(posedge cb or negedge rst_n)",
             f"    if (!rst_n) rb <= 0; else rb <= d[{width-1}:{half}];",
             "  assign q = {rb, ra};",
             "endmodule"]
    return "\n".join(lines) + "\n", {
        "family": "two_clocks", "width": width, "reset": "async_reset",
        "flops": width, "clock_roots": 2,
        # Two registers, not one: they are written by different clocks, so no
        # assignment of bits to a single register survives.
        "registers": [half, width - half],
        "note": "two independent clock domains, so one root would be wrong"}


def inverted_clock(width):
    """Half the register clocked from an inverted branch of the same tree.

    The other reason "no flop is on an inverting clock path" was a constant:
    nothing could produce one. That turned out to be true of the *code* as well
    as of the corpus -- this library writes a combinational output as
    `function : "(!A)"`, parenthesised, and stage 3 read the level off the raw
    first character, so all 21 of its inverters were classified as buffers and
    the walk reported every path straight. Silent, because the root was still
    correct and only the parity was wrong.

    A circuit that puts a flop behind a real `clkinv` is what makes that rule
    able to fail. It is also a shape worth handling: those bits sample on the
    falling edge of the root clock, and a detector that groups them with the
    rest without noticing has merged two different sampling instants.
    """
    name = f"inverted_clock_w{width}"
    half = width // 2
    lines = [f"module {name} (input clk, input rst_n,",
             f"  input [{width-1}:0] d, output [{width-1}:0] q);",
             "  wire cp, cn;",
             f"  {CLOCK_BUFFER} cbp (.A(clk), .X(cp));",
             f"  {CLOCK_INVERTER} cbn (.A(clk), .Y(cn));",
             f"  reg [{half-1}:0] rp, rn;",
             "  always @(posedge cp or negedge rst_n)",
             f"    if (!rst_n) rp <= 0; else rp <= d[{half-1}:0];",
             "  always @(posedge cn or negedge rst_n)",
             f"    if (!rst_n) rn <= 0; else rn <= d[{width-1}:{half}];",
             "  assign q = {rn, rp};",
             "endmodule"]
    return "\n".join(lines) + "\n", {
        "family": "inverted_clock", "width": width, "reset": "async_reset",
        "flops": width, "clock_roots": 1, "clock_inverted": half,
        # One clock root, two registers: half sample on the rising edge and
        # half on the falling, which is two different instants.
        "registers": [half, width - half],
        "note": "half the flops sample on the falling edge of the root clock"}


def tied_outputs(width, constants):
    """Outputs held at a constant, which is how `conb_1` cells come to exist.

    The puzzle carries six `conb_1` cells driving twelve constant nets. The
    corpus produced none at all -- synthesis folds a constant into whatever
    reads it, so nothing survives for `hilomap` to map. A constant that reaches
    a port cannot be folded away, so this is the shape that forces one.

    `constants` varies between the two members so that the rule checking the
    count has more than one answer to give. A rule only ever asked to confirm
    the same number is one an implementation returning that number
    unconditionally would pass.
    """
    name = f"tied_outputs_w{width}_c{constants}"
    ties = "".join(
        f"  assign tie{index} = 1'b{index % 2};\n" for index in range(constants))
    ports = "".join(f", output tie{index}" for index in range(constants))
    return f"""module {name} (input [{width-1}:0] d, output [{width-1}:0] q{ports});
  assign q = d;
{ties}endmodule
""", {"family": "tied_outputs", "width": width, "constants": constants}


def counter_compare(width, limit):
    name = f"composed_counter_compare_w{width}"
    return f"""module {name} (input clk, input rst_n, input en, output hit,
                  output [{width-1}:0] q);
  reg [{width-1}:0] count;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) count <= {width}'d0;
    else if (en) count <= count + 1'b1;
  assign hit = (count == {width}'d{limit});
  assign q = count;
endmodule
""", {"family": "composed", "parts": ["counter", "comparator"],
      "width": width, "limit": limit, "enable": True}


def shift_accumulate(width):
    name = f"composed_shift_accumulate_w{width}"
    return f"""module {name} (input clk, input rst_n, input si,
                  output [{width-1}:0] total);
  reg [{width-1}:0] sr, acc;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin sr <= {width}'d0; acc <= {width}'d0; end
    else begin sr <= {{sr[{width-2}:0], si}}; acc <= acc + sr; end
  assign total = acc;
endmodule
""", {"family": "composed", "parts": ["shift_register", "accumulator"],
      "width": width, "registers": [width, width]}


def scale_datapath(width, branches):
    """Several interacting blocks, at the size the target actually is.

    Every other circuit here is small: the largest holds 32 flip flops and 125
    cells against the puzzle's 92 and 738, and the median holds four. Scoring a
    detector on circuits an order of magnitude below the thing it has to work on
    says very little, and two of the costs are not linear -- grouping N flops
    into registers, and a miter whose SAT instance grows with cone depth and
    width. This family exists so the scores mean something, and its three sizes
    bracket the target rather than approach it.

    What it computes is deliberately ordinary: a shift register fed one bit at a
    time, an accumulator summing it, a free running counter, an LFSR, a held
    output register, a narrow tag register and a small state machine. Nothing
    here is chosen to resemble the puzzle's function, which is not known. Only
    the *size* and the *shape* are matched, and both are things the corpus was
    measurably short of.

    Two properties carry over from the smaller families on purpose:

      the shift register is cut into one segment per spare clock branch, so a
      single logical register genuinely spans the tree -- ten of the sixteen
      branches at the largest size -- rather than spanning two in a toy;

      the LFSR resets to a non-zero seed, which forces set flops beside the
      reset flops. An LFSR started at zero stays there, so this is the circuit's
      own requirement and not a shape borrowed from the target.

    The number of clock domains is bounded by the number of independent always
    blocks, so `branches` is not a free parameter: six blocks are fixed and the
    rest of the tree has to come from segmenting the shift register. Asking for
    more branches than the RTL can use leaves dead buffers, `opt_clean` removes
    them, and the declared count then disagrees with the netlist -- which is how
    the first version of this was caught.
    """
    if branches < 8:
        raise ValueError("scale_datapath needs at least 8 clock branches")
    name = f"scale_datapath_w{width}_b{branches}"
    half, top = width // 2, width - 1
    seed = ("1010110011100001" * 8)[:width]
    taps = f"lfsr[{top}] ^ lfsr[{top-2}] ^ lfsr[{top-3}] ^ lfsr[{top-5}]"
    limit = (1 << (width - 8)) - 1

    # The shift register takes every branch the six fixed blocks do not.
    segments = branches - 6
    base, spare = divmod(width, segments)
    sizes = [base + (1 if i < spare else 0) for i in range(segments)]

    lines = [f"module {name} (input clk, input rst_n, input si, input en,",
             f"  output [{top}:0] result, output done);"]
    for branch in range(branches):
        lines.append(f"  wire clk_b{branch};")
        lines.append(f"  {CLOCK_BUFFER} cb{branch} (.A(clk), .X(clk_b{branch}));")

    for index, size in enumerate(sizes):
        lines.append(f"  reg [{size-1}:0] sr{index};")
    lines += [f"  reg [{top}:0] acc, cnt, lfsr, outr;",
              f"  reg [{half-1}:0] tag;",
              "  reg [1:0] state;"]
    joined = ", ".join(f"sr{i}" for i in reversed(range(segments)))
    lines.append(f"  wire [{top}:0] sr = {{{joined}}};")
    lines.append("")
    lines.append(f"  // one logical shift register over {segments} branches")
    for index, size in enumerate(sizes):
        feed = "si" if index == 0 else f"sr{index-1}[{sizes[index-1]-1}]"
        lines.append(f"  always @(posedge clk_b{index} or negedge rst_n)")
        lines.append(f"    if (!rst_n) sr{index} <= 0;"
                     f" else sr{index} <= {{sr{index}[{size-2}:0], {feed}}};")

    fixed = segments
    lines += [
        "",
        f"  always @(posedge clk_b{fixed} or negedge rst_n)",
        "    if (!rst_n) acc <= 0; else acc <= acc + sr;",
        f"  always @(posedge clk_b{fixed + 1} or negedge rst_n)",
        "    if (!rst_n) cnt <= 0; else cnt <= cnt + 1'b1;",
        "",
        "  // a non-zero seed, because an LFSR started at zero never leaves it",
        f"  always @(posedge clk_b{fixed + 2} or negedge rst_n)",
        f"    if (!rst_n) lfsr <= {width}'b{seed};",
        f"    else lfsr <= {{lfsr[{top-1}:0], {taps}}};",
        "",
        f"  always @(posedge clk_b{fixed + 3} or negedge rst_n)",
        "    if (!rst_n) outr <= 0; else if (en) outr <= acc ^ lfsr;",
        f"  always @(posedge clk_b{fixed + 4} or negedge rst_n)",
        f"    if (!rst_n) tag <= 0; else tag <= tag + {{{half-1}'d0, si}};",
        "",
        f"  always @(posedge clk_b{fixed + 5} or negedge rst_n)",
        "    if (!rst_n) state <= 2'd0;",
        "    else case (state)",
        "      2'd0: state <= si ? 2'd1 : 2'd0;",
        f"      2'd1: state <= (cnt == {width}'d{limit}) ? 2'd2 : 2'd1;",
        "      2'd2: state <= 2'd3;",
        "      default: state <= 2'd0;",
        "    endcase",
        "",
        "  assign result = outr;",
        "  assign done = (state == 2'd3) && (tag != 0);",
        "endmodule"]
    return "\n".join(lines) + "\n", {
        "family": "scale_datapath", "width": width, "branches": branches,
        # Declared rather than derived, so verify_corpus.py has something to
        # disagree with. Five registers of `width`, a half width tag and a two
        # bit state; and the enable gates only the output register, unlike the
        # smaller families where it holds all of them.
        "flops": 5 * width + half + 2,
        # The shift register counts once, not once per segment: the segments
        # are one logical register spread over the clock tree, which is the
        # shape the clock_tree family exists to make visible.
        "registers": [width, width, width, width, width, half, 2],
        "enable": True, "enable_holds": width, "reset": "async_reset",
        "segments": segments,
        "parts": ["shift_register", "accumulator", "counter", "lfsr",
                  "register", "fsm"],
        "note": "the corpus at the size of the target, blocks interacting"}


def warmup_source():
    """The warm up's own RTL, unmodified, as a corpus entry.

    The only circuit here whose Verilog this pipeline's author did not write,
    and that is worth more than one entry usually would be. The corpus is the
    answer key most of stage 4 is scored against and the same person wrote both
    -- `docs/05-synthetic-corpus.md` says so and the review packet lists it
    under what is unverified. This entry is outside that: it is the design the
    warm up target *is*, and the partition declared for it, `[8, 8]`, is what
    `03_post_place_and_route.def` states the hierarchy to be rather than what
    anybody here decided it should be.

    It is also the same function reaching stage 3 by a second route. The warm up
    target arrives as a *layout*, through stages 1 and 2 and a GDS; this arrives
    as RTL, through Yosys. Anything stage 3 concludes about one and not the
    other would be worth knowing, and nothing else in the repository would show
    it.
    """
    path = os.path.join("puzzle", "warmup", "00_source.v")
    if not os.path.exists(path):
        sys.exit(f"{path} missing; run git submodule update --init")
    with open(path, encoding="utf-8") as handle:
        verilog = handle.read()
    return verilog, {"family": "warmup", "top": "adder_demo", "width": 8,
                     "flops": 16, "registers": [8, 8], "enable": True,
                     "reset": "async_reset", "clock_roots": 1,
                     "source": path}


def warmup_twin(width):
    """Two structurally identical registers sharing every control signal.

    The one shape the corpus did not have, and the shape the warm up actually
    is. Every other multi-register circuit here differs from this in a way a
    control signature can see: `two_clocks` differs in clock, `inverted_clock`
    in edge, `composed_shift_accumulate` in structure, `scale_datapath` in all
    of them. Here `a_reg` and `b_reg` are the same bits twice, on one clock, one
    reset and one enable, and *nothing in a control signature can separate
    them*.

    Which means adding this makes `stage4_registers.py --score` worse, on
    purpose. It was 117/127 against a corpus that mostly did not ask the
    question. The number drops because the corpus now contains the failure mode
    the real target has -- `tools/verify_blocks.py` has been failing on exactly
    this since it was written, and until now nothing in the corpus agreed with
    it. A score that only ever rose when the corpus grew would be measuring the
    corpus.
    """
    name = f"warmup_twin_w{width}"
    top = width - 1
    return f"""module {name} (input clk, input rst_n, input en,
                  input a_in, input b_in,
                  output [{top}:0] a_out, output [{top}:0] b_out);
  reg [{top}:0] a_reg, b_reg;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) a_reg <= 0;
    else if (en) a_reg <= {{a_reg[{width - 2}:0], a_in}};
  always @(posedge clk or negedge rst_n)
    if (!rst_n) b_reg <= 0;
    else if (en) b_reg <= {{b_reg[{width - 2}:0], b_in}};
  assign a_out = a_reg;
  assign b_out = b_reg;
endmodule
""", {"family": "warmup_twin", "width": width, "flops": 2 * width,
      "registers": [width, width], "enable": True, "reset": "async_reset",
      "clock_roots": 1}


def mux2i_witness():
    """A flop fed by an *inverting* mux with its own Q on a leg. Pre-mapped.

    Every other circuit here is RTL that Yosys maps. This one is written at the
    gate level and handed to stage 3 as it stands, because no RTL produces it:
    `mux2i` in front of a D with Q on a leg is not a hold, it is a toggle, and a
    synthesiser asked for a hold emits `mux2`.

    Which is exactly why the corpus needed it. Stage 3 used to find the mux in
    front of D with `"mux2" in the cell name`, and that substring matches
    `mux2i` too:

        mux2   X = (A0&!S) | (A1&S)          passes A0, then A1
        mux2i  Y = (!A0&!S) | (!A1&S)        passes !A0, then !A1

    Under the old rule this circuit records a hold on `en`. It does not hold. It
    inverts every cycle that `en` is low. Problem 42 records the defect, and its
    verdict was `understood and incomplete` precisely because nothing in the
    repository could produce the wrong answer -- all 56 holds found anywhere are
    `mux2_1`, so the rule was fixed by argument and never seen to reject
    anything. This is the known-bad input that argument was missing.

    No enable is declared, because there is none.
    """
    name = "mux2i_witness"
    netlist = f"""module {name}(clk, rst_n, en, d, q);
  input clk;
  input rst_n;
  input en;
  input d;
  output q;
  wire clk_b;
  wire nd;
  sky130_fd_sc_hd__clkbuf_1 _00_ (
    .A(clk),
    .X(clk_b)
  );
  sky130_fd_sc_hd__mux2i_1 _01_ (
    .A0(q),
    .A1(d),
    .S(en),
    .Y(nd)
  );
  sky130_fd_sc_hd__dfrtp_1 _02_ (
    .CLK(clk_b),
    .D(nd),
    .Q(q),
    .RESET_B(rst_n)
  );
endmodule
"""
    return netlist, {"family": "mux2i_witness", "premapped": True,
                     "flops": 1, "clock_roots": 1, "reset": "async_reset",
                     "registers": [1]}


def _sequential(family, name, width, enable, reset, body, ports, truth):
    """Shared skeleton for the clocked generators."""
    declared = ", ".join(
        f"input {size} {port}" if port in ("d", "si") else f"output reg {size} {port}"
        for port, size in ports.items())
    enable_port = ", input en" if enable else ""
    # An asynchronous reset becomes a pin on the flop; a synchronous one becomes
    # logic in front of D and leaves the flop with no reset pin at all. Two
    # genuinely different shapes, and the corpus used to declare `sync` while
    # emitting neither -- caught by tools/verify_corpus.py comparing the
    # declaration against the flops stage 3 found.
    if reset == "async_reset":
        head = "always @(posedge clk or negedge rst_n)\n    if (!rst_n) q <= 0;\n    else "
        reset_port = ", input rst_n"
    elif reset == "async_set":
        head = ("always @(posedge clk or negedge rst_n)\n"
                f"    if (!rst_n) q <= {{{width}{{1'b1}}}};\n    else ")
        reset_port = ", input rst_n"
    elif reset == "sync":
        head = "always @(posedge clk)\n    if (!rst_n) q <= 0;\n    else "
        reset_port = ", input rst_n"
    else:
        head = "always @(posedge clk)\n    "
        reset_port = ""
    verilog = (f"module {name} (input clk{reset_port}{enable_port}, "
               f"{declared});\n  {head}{body}\nendmodule\n")
    return verilog, truth


def catalogue():
    """Every circuit the corpus holds, as (generator result, group)."""
    items = []

    def add(result, group):
        items.append((result[0], result[1], group))

    for width in (4, 8, 16):
        for reset in ("async_reset", "sync"):
            add(register(width, False, reset), "positive")
            add(register(width, True, reset), "positive")
        for direction in ("left", "right"):
            add(shift_register(width, direction, "async_reset"), "positive")
        for direction in ("up", "down"):
            add(counter(width, direction, False, "async_reset"), "positive")
            add(counter(width, direction, True, "async_reset"), "positive")
        add(accumulator(width), "positive")
        add(adder(width, False), "positive")
        add(adder(width, True), "positive")
        add(subtractor(width), "positive")
        for kind in ("eq", "lt", "gt"):
            add(comparator(width, kind), "positive")
        add(multiplexer(width, 4), "positive")
        add(serial_adder(width), "positive")
        add(crc(width, {4: 0b10011, 8: 0b100011101, 16: 0b11000000000000101}[width]),
            "positive")

    for width, taps in ((8, (7, 5, 4, 3)), (16, (15, 13, 12, 10))):
        for style in ("fibonacci", "galois"):
            add(lfsr(width, taps, style), "positive")

    for bits in (2, 3, 4):
        add(decoder(bits), "positive")
    # Stage 7's ground truth. Two strings rather than one, because a decoder
    # that hard-wired a length would pass on a single instance; different
    # lengths so the index register is a different width; and one carrying two
    # non-printable bytes, because the escape path in the decoding is the part
    # a printable-only string would leave untested.
    add(streamer("hello", "HELLO WORLD"), "positive")
    add(streamer("escape", "OK\x07 42\n"), "positive")
    for states in (4, 8):
        for encoding in ("binary", "one-hot"):
            add(fsm(states, encoding), "positive")

    for width in (8, 16):
        add(parallel_register(width), "negative")
        add(xor_tree(width), "negative")
        add(scrambled_logic(width), "negative")
        add(counter_compare(width, width * 3), "composed")
        add(shift_accumulate(width), "composed")

    # Shapes the puzzle has that ordinary synthesis of ordinary RTL does not
    # produce. Both were added after measuring the corpus against the target,
    # not from a list drawn up in advance.
    for width, branches in ((8, 4), (16, 4), (16, 8)):
        add(clock_tree(width, branches), "structure")
    for width, constants in ((8, 2), (16, 5)):
        add(tied_outputs(width, constants), "structure")
    # Circuits that exist so a rule has something other than its usual answer to
    # give. Without these, "one clock root" and "no inverting clock path" are
    # constants that no circuit here could contradict -- and the second was a
    # constant the *code* could not contradict either.
    for width in (8, 16):
        add(two_clocks(width), "structure")
        add(inverted_clock(width), "structure")
    # Not a circuit anyone would write. It exists so that stage 3's rule for
    # "is there a mux holding this register" has something it must say no to,
    # and so that saying yes to it is a failure something notices.
    add(mux2i_witness(), "structure")
    # The shape verify_blocks.py fails the warm up on, which the corpus lacked.
    for width in (8, 16):
        add(warmup_twin(width), "structure")
    add(warmup_source(), "structure")

    # Size. Everything above is an order of magnitude below the target: the
    # largest holds 32 flops and 125 cells against the puzzle's 92 and 738, and
    # the median holds four. Two of these bracket the target rather than
    # approach it, because a detector that works at 90 flops and fails at 180
    # has a scaling problem worth knowing about before the real run.
    for width, branches in ((16, 8), (32, 8), (64, 16)):
        add(scale_datapath(width, branches), "scale")

    return items


def module_name(verilog):
    for line in verilog.splitlines():
        stripped = line.strip()
        if stripped.startswith("module "):
            return stripped.split()[1].split("(")[0]
    raise ValueError("no module in generated source")


# Structures the puzzle has that a plain `abc` mapping does not produce. Both
# were found by measuring the corpus's cell vocabulary against the puzzle's
# rather than assuming the two matched.
#
# `clkbufmap` inserts one buffer per clock net. Two things had to be right
# before it inserted anything at all, and neither announced itself:
#
#   port order    `-buf <cell> <out>:<in>`, so `X:A` and not `A:X`. Written the
#                 wrong way round the pass runs, reports nothing and does
#                 nothing.
#   sink marking  it finds clock inputs by the `clkbuf_sink` attribute, which
#                 cells arriving through `dfflibmap` and `abc` do not carry.
#                 The blackbox library is read first with those pins marked,
#                 from liberty's own `clock` flag.
#
# It gives one buffer, not the puzzle's sixteen branches. Circuits that need a
# real tree write it in their RTL instead, in the `clock_tree` family below.
CLOCK_BUFFER = "sky130_fd_sc_hd__clkbuf_1"
CONSTANT_CELL = "sky130_fd_sc_hd__conb_1"
SINKS_PATH = f"{OUT_DIR}/clock_sinks.v"


# The same circuit mapped more than one way.
#
# `docs/solver-pipeline.md` calls the miter check "the more reliable of the two"
# because synthesis rewrites structure and preserves function, so a block that
# no longer looks like an adder still behaves as one. Every circuit here being
# synthesised exactly once left that claim untestable: a detector that memorised
# one particular mapping of an adder would have scored perfectly.
#
# Which knob to turn was measured rather than picked. `abc -D 250`, a delay
# target, was the obvious candidate and changes nothing at all: identical cell
# mix on every circuit tried. `-fast` stops abc short of its full optimisation
# and genuinely rewrites -- on `adder_w8`, 24 cells over 6 types becomes 31 over
# 10, only 10 instances survive unchanged, and the `maj3` carry chain is
# replaced by `a31o` and `a21oi`, which are cells the puzzle uses and the base
# flow never produced.
#
# Drive strength stays at `_1` under both, and is left alone on purpose. It is a
# physical choice that changes no function; the corpus differing from the puzzle
# there is what makes the case that detectors must normalise the suffix.
VARIANTS = {"base": "", "fast": "-fast"}


def synthesise(name, rtl_path, out_dirs):
    """Map one circuit several ways, from one shared pre-mapping netlist.

    `design -save` before the mapper and `design -load` before each variant is
    what makes these variants of one function rather than two separately
    compiled circuits: everything up to technology mapping is shared, and only
    the mapping differs.
    """
    steps = [f"read_verilog -lib {SINKS_PATH}",
             f"read_verilog {rtl_path}",
             f"hierarchy -check -top {name}",
             # `flatten` because one entry has hierarchy. Every circuit this
             # corpus generates is a single module, so the step was never
             # needed and never noticed missing -- until `00_source.v` arrived,
             # which is three modules under `adder_demo`, and stage 3 met a
             # netlist still instantiating `shift_register`. A no-op on the
             # other 96.
             "proc; flatten; opt; fsm; opt; memory; opt",
             "techmap; opt",
             "design -save premap"]
    for variant, extra in VARIANTS.items():
        steps += ["design -load premap",
                  f"dfflibmap -liberty {LIB_PATH}",
                  f"abc -liberty {LIB_PATH} {extra}".strip(),
                  f"clkbufmap -buf {CLOCK_BUFFER} X:A",
                  f"hilomap -hicell {CONSTANT_CELL} HI -locell {CONSTANT_CELL} LO",
                  "opt_clean",
                  "stat",
                  f"write_verilog -noattr {out_dirs[variant]}/netlist.v"]
    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{os.path.abspath('.')}:/work",
         "-w", "/work", IMAGE, "yosys", "-p", "; ".join(steps)],
        capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def main(list_only=False):
    items = catalogue()
    groups = Counter(group for _, _, group in items)
    print(f"corpus: {len(items)} circuits  {dict(groups)}")
    families = Counter(truth["family"] for _, truth, _ in items)
    print(f"families: {dict(families)}")
    if list_only:
        for verilog, truth, group in items:
            print(f"  {group:<9} {module_name(verilog):<34} {truth}")
        return 0

    os.makedirs(RTL_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    lib = liberty.load(PDK_DIR)
    lef_views = load_lef(PDK_DIR)
    written = liberty.write_lib(lib, LIB_PATH)
    print(f"\nwrote {LIB_PATH}, {written} mappable cells "
          f"(low power families excluded)")

    # Read before synthesis so `clkbufmap` can find the clock inputs. Every cell
    # the mapper might pick is included, since which ones it picks is not known
    # until it has picked them.
    mappable = sorted(n for n in lib if n in lef_views)
    stage3_graph.blackbox_library(mappable, lef_views, SINKS_PATH, lib)
    marked = open(SINKS_PATH, encoding="utf-8").read().count("clkbuf_sink")
    print(f"wrote {SINKS_PATH}, {len(mappable)} cells, {marked} clock pins marked")

    index = []
    seen = Counter()
    failures = []
    for verilog, truth, group in items:
        # `top` where a file holds several modules and the first is not the one
        # wanted: 00_source.v opens with `shift_register` and the design is
        # `adder_demo`.
        name = truth.get("top") or module_name(verilog)
        seen[truth["family"]] += 1
        truth = dict(truth, name=name, group=group,
                     held_out=seen[truth["family"]] % HELD_OUT_EVERY == 0)

        rtl_path = f"{RTL_DIR}/{name}.v"
        with open(rtl_path, "w", encoding="utf-8") as handle:
            handle.write(verilog)
        premapped = truth.get("premapped", False)

        # Held out is decided once per circuit and inherited by every variant of
        # it. Splitting variants across the boundary would let a held out
        # circuit reach development work through its other mapping.
        # A pre-mapped entry has exactly one mapping, because it was not
        # mapped: the two variants would be the same file twice and would
        # report a structural invariance the circuit does not have.
        out_dirs = {variant: f"{OUT_DIR}/{name}" if variant == "base"
                    else f"{OUT_DIR}/{name}__{variant}"
                    for variant in (["base"] if premapped else VARIANTS)}
        for path in out_dirs.values():
            os.makedirs(path, exist_ok=True)

        if premapped:
            with open(f"{out_dirs['base']}/netlist.v", "w",
                      encoding="utf-8") as handle:
                handle.write(verilog)
        else:
            code, log = synthesise(name, rtl_path, out_dirs)
            if code != 0:
                failures.append((name,
                                 log.strip().splitlines()[-1] if log else "?"))
                continue

        for variant, out_dir in out_dirs.items():
            entry = dict(truth, variant=variant, dir=out_dir)
            netlist = f"{out_dir}/netlist.v"
            cells = Counter(line.strip().split()[0]
                            for line in open(netlist, encoding="utf-8")
                            if line.strip().startswith("sky130"))
            entry["cells"] = sum(cells.values())
            entry["cell_mix"] = dict(cells.most_common())

            # Through the same stage 3 the puzzle goes through. Stage 4 consumes
            # graph.json, so a corpus that stopped at a netlist would be testing
            # the detectors on a different kind of input than they will meet.
            graph = stage3_graph.build(out_dir, name, lef_views, lib, quiet=True)
            entry["graph"] = {
                "cells": len(graph["cells"]),
                "nets": len(graph["nets"]),
                "flipflops": len(graph["flipflops"]),
                "clock_nets": len(graph["clock_nets"]),
                "cone_roots": len(graph["cone_roots"]),
            }
            with open(f"{out_dir}/truth.json", "w", encoding="utf-8") as handle:
                json.dump(entry, handle, indent=1)
            index.append(entry)

    circuits = len({t["name"] for t in index})
    print(f"\nsynthesised {circuits} circuits as {len(index)} netlists "
          f"({', '.join(VARIANTS)}), failed {len(failures)}")
    for name, why in failures[:10]:
        print(f"  FAILED {name}: {why}")

    # An index written from a failed build is worse than no index: it is the
    # answer key stage 4 is scored against, and a shorter one still looks like a
    # valid corpus. This was not hypothetical -- Docker Desktop being stopped
    # made all 93 circuits fail and the previous version wrote an index of zero
    # over a good one, which the verifier then reported as passing 0/0.
    if failures:
        print(f"\n{len(failures)} circuit(s) failed, so {OUT_DIR}/index.json is "
              f"NOT being rewritten; the existing one is left alone.")
        if any("docker" in why.lower() for _, why in failures):
            print("  Every failure mentions Docker. Start Docker Desktop and "
                  "run this again.")
        print("\nRESULT: fail")
        return 1

    with open(f"{OUT_DIR}/index.json", "w", encoding="utf-8") as handle:
        json.dump({"circuits": index, "held_out_every": HELD_OUT_EVERY,
                   "variants": list(VARIANTS)}, handle, indent=1)
    print(f"wrote {OUT_DIR}/index.json")

    held = len({t["name"] for t in index if t["held_out"]})
    print(f"  held out for scoring: {held} circuits, available for "
          f"development: {circuits - held}")
    total = sum(t["cells"] for t in index)
    flops = sum(t["graph"]["flipflops"] for t in index)
    print(f"  {total} cells and {flops} state elements across the corpus")

    # A variant that mapped to the same cells as the base tests nothing about
    # structural invariance. How many actually differ is the honest measure of
    # what this doubling bought, and it is not a number to assume.
    by_name = defaultdict(dict)
    for entry in index:
        by_name[entry["name"]][entry["variant"]] = entry
    for variant in VARIANTS:
        if variant == "base":
            continue
        pairs = [(v["base"], v[variant]) for v in by_name.values()
                 if "base" in v and variant in v]
        differ = [(b, o) for b, o in pairs
                  if Counter(b["cell_mix"]) != Counter(o["cell_mix"])]
        moved = sum(sum((Counter(b["cell_mix"]) - Counter(o["cell_mix"])).values())
                    for b, o in differ)
        print(f"  variant {variant!r}: {len(differ)}/{len(pairs)} circuits mapped "
              f"to a different cell mix, {moved} instances changed")

    # How far this corpus reaches against a target -- the size bound on what
    # can ever be named, and the cell vocabulary comparison -- is
    # tools/corpus_reach.py. It lives there rather than here because the
    # vocabulary number needs its limits stated beside it every time it is
    # printed: it reads like a coverage figure and is not one.
    print(f"\nreach against a target: python tools/corpus_reach.py puzzle")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main("--list" in sys.argv[1:]))
