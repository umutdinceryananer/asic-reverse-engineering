"""Easter-egg hunt, domain B1 follow-up: frame perturbations of the attempt.

The output battery (tools/egg_output_battery.py) established the message space
over ENABLE-FRAMED 121-BIT attempts: TRY AGAIN, (* TWO STARS *), EMPTY SKY,
BIG BANG. This tool asks whether cheap perturbations of the FRAME itself --
never raising enable, holding it high twice as long, pulsing reset into the
middle of the streaming message, truncating or doubling the enable window --
unlock a fifth message.

It reuses the battery's exact recipe by importing it: the same generated
testbench (tools/sim/harness.py's clocked_bench, so the cycle model cannot
drift), the same native toolchain and flags (-g2012 -DFUNCTIONAL
-DUNIT_DELAY=#1), the same stage-7 escaping (proven equal to
stage7_output.escape over all 256 bytes and None by the battery's selftest,
and re-proven here). What it does NOT reuse is the battery's framing
constants: reset length, post-reset idle and attempt width are derived at
runtime from out/puzzle/stimulus.txt, the per-cycle table made from the
puzzle's own VCD.

The probes, run sequentially, each with a unique scratch path:

    control   the unmodified winning frame. POSITIVE-CONTROL GATE: it must
              reproduce (* TWO STARS *) byte for byte with success high, or
              this tool exits 1 and trusts nothing else it measured.
    1         reset toggled, then enable never raised for 300 cycles: does
              the idle machine ever drive O.
    2         the winning vector with enable held high for 121 extra cycles,
              the vector streamed a second time back to back, no reset
              between -- and enable stays high through the extension too.
    3         the winning attempt with rst_n pulsed low for exactly one
              cycle in the middle of the streaming message (the pulse cycle
              is derived from the control run's own message span).
    4a        a 60-bit enable window: the winning vector's first 60 bits.
    4b        a 242-bit enable window: the winning vector doubled, framed
              exactly like a normal attempt (enable falls after the window).

Probes 2 and 4b feed identical bits inside the window and differ only in
what enable does after it, so together they also cover both extension
conventions.

A probe's rendering is judged against the known message space by segments:
the O stream is split on idle (0x00 or undefined) runs and each segment
compared to the four known strings. A segment that is a proper prefix of a
known message is classified a TRUNCATION -- cutting a stream mid-message
reveals nothing new -- and a probe claims a NEW string only if some segment
is neither a known message nor a prefix of one.

Usage:
    .venv-linux/bin/python tools/egg_sim_probes.py --selftest
    .venv-linux/bin/python tools/egg_sim_probes.py

Writes out/eggs/sim_probes.json. No per-cycle dump is stored: decoded
segments and counts only.
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import egg_output_battery as b1                                 # noqa: E402
# Importing b1 chdirs to the repo root and puts tools/sim on sys.path, which
# is exactly the environment its simulate()/build_bench() expect.
from run import model_files                                     # noqa: E402

STIMULUS = os.path.join("out", "puzzle", "stimulus.txt")
OUT_JSON = os.path.join("out", "eggs", "sim_probes.json")
EXTEND = 64            # the battery's margin: message is 15 bytes, 64 is 4x
IDLE_PROBE_CYCLES = 300
PREFIX_BITS = 60

KNOWN_MESSAGES = ("TRY AGAIN", "(* TWO STARS *)", "EMPTY SKY", "BIG BANG")
WINNING_TEXT = "(* TWO STARS *)"
WINNING_BYTES = list(WINNING_TEXT.encode("ascii"))


def derive_framing(path=STIMULUS):
    """(reset_cycles, idle_after_reset, attempt_bits), from the VCD's table.

    Each stimulus row is three characters: rst_n, enable, I. The frame is the
    leading run of rst_n=0 rows, the rows between reset release and the first
    enable=1 row, and the length of the first enable window.
    """
    lines = [l.strip() for l in open(path, encoding="utf-8") if l.strip()]
    bad = [l for l in lines if len(l) != 3 or set(l) - {"0", "1"}]
    if bad:
        raise RuntimeError(f"{path}: rows must be 3 chars of 0/1, got "
                           f"{bad[0]!r}")
    rst = [l[0] for l in lines]
    en = [l[1] for l in lines]
    reset_cycles = 0
    while reset_cycles < len(rst) and rst[reset_cycles] == "0":
        reset_cycles += 1
    if reset_cycles == 0:
        raise RuntimeError(f"{path}: no leading reset rows -- the frame "
                           f"cannot be derived")
    if "1" not in en:
        raise RuntimeError(f"{path}: enable never rises")
    first_en = en.index("1")
    idle_after_reset = first_en - reset_cycles
    if idle_after_reset < 0:
        raise RuntimeError(f"{path}: enable rises inside the reset run")
    end = first_en
    while end < len(en) and en[end] == "1":
        end += 1
    return reset_cycles, idle_after_reset, end - first_en


def preamble(framing):
    """The derived reset toggle plus post-reset idle rows, fresh dicts."""
    reset_cycles, idle_after_reset, _ = framing
    rows = [{"rst_n": 0, "enable": 0, "I": 0} for _ in range(reset_cycles)]
    rows += [{"rst_n": 1, "enable": 0, "I": 0}
             for _ in range(idle_after_reset)]
    return rows


def frame_idle(framing, cycles):
    """Probe 1: reset toggled, then enable never raised for `cycles` rows."""
    rows = preamble(framing)
    notes = {len(rows): "<- reset released, enable never raised"}
    rows += [{"rst_n": 1, "enable": 0, "I": 0} for _ in range(cycles)]
    after = {"rst_n": 1, "enable": 0, "I": 0}
    return rows, notes, after


def frame_window(framing, bits, extend, hold_enable=False):
    """An enable window of arbitrary width, then `extend` rows.

    hold_enable=False drops to the VCD's own idle row after the window;
    hold_enable=True keeps enable high with the last bit held, so the window
    never closes from the machine's point of view.
    """
    if not bits or set(bits) - {"0", "1"}:
        raise ValueError(f"window bits must be non-empty 0/1, got {bits!r}")
    rows = preamble(framing)
    start = len(rows)
    rows += [{"rst_n": 1, "enable": 1, "I": int(b)} for b in bits]
    notes = {start: "<- enable window begins",
             len(rows) - 1: "<- last window cycle",
             len(rows): "<- extension begins"}
    if hold_enable:
        after = {"rst_n": 1, "enable": 1, "I": int(bits[-1])}
    else:
        after = {"rst_n": 1, "enable": 0, "I": 0}
    rows += [dict(after) for _ in range(extend)]
    return rows, notes, after


def pulse_reset(rows, notes, cycle):
    """The same frame with rst_n forced low for exactly one cycle."""
    if not 0 <= cycle < len(rows):
        raise ValueError(f"pulse cycle {cycle} outside 0..{len(rows) - 1}")
    rows = [dict(r) for r in rows]
    rows[cycle]["rst_n"] = 0
    notes = dict(notes)
    notes[cycle] = "<- rst_n pulsed low this cycle only"
    return rows, notes


def stream_segments(observed):
    """The O stream split on idle runs: rendered segments, plus counts.

    A segment is a maximal run of defined non-0x00 samples. Rendering uses
    the battery's escape(), which the selftest proves equal to stage 7's.
    """
    values = [b1.harness.value(s["O"]) for s in observed]
    segs, cur = [], []
    for v in values:
        if v is None or v == b1.IDLE_BYTE:
            if cur:
                segs.append(cur)
                cur = []
        else:
            cur.append(v)
    if cur:
        segs.append(cur)
    return ([b1.render(s) for s in segs],
            sum(1 for v in values if v is not None),
            sum(1 for v in values if v not in (None, b1.IDLE_BYTE)),
            sum(1 for v in values if v is None))


def classify(segment):
    """'known', 'truncation of <msg>', or 'new'. Prefix-only on purpose:
    a reset that cuts the stream can only leave a prefix, and a narrower
    excuse means less risk of dismissing a genuinely new string."""
    if segment in KNOWN_MESSAGES:
        return "known"
    for message in KNOWN_MESSAGES:
        if message.startswith(segment):
            return f"truncation of {message!r}"
    return "new"


def run_probe(probe_id, rows, notes, scratch, compile_env, extra=None):
    """One sequential simulation, analysed with the battery's own analyse()."""
    observed, _ = b1.simulate(probe_id, rows, notes, scratch, compile_env)
    record = b1.analyse(probe_id, "probe", rows, observed)
    segments, o_defined, o_live, o_undef = stream_segments(observed)
    succ_high = [s["cycle"] for s in observed if s.get("success") == "1"]
    record.pop("success_bits", None)      # per-cycle dump: counts only
    record["success_last_cycle"] = succ_high[-1] if succ_high else None
    record["o_live_cycles"] = o_live
    record["o_undefined_cycles"] = o_undef
    record["segments"] = segments
    record["segment_classes"] = [classify(s) for s in segments]
    record["new_segments"] = [s for s in segments if classify(s) == "new"]
    record["is_new_string"] = bool(record["new_segments"])
    record.update(extra or {})
    return record, observed


def main(argv):
    scratch_arg, extend = None, EXTEND
    rest = list(argv)
    if rest and rest[0] == "--selftest":
        return selftest()
    while rest:
        item = rest.pop(0)
        if item == "--scratch":
            scratch_arg = rest.pop(0)
        elif item == "--extend":
            extend = int(rest.pop(0))
        else:
            sys.exit("usage: egg_sim_probes.py [--selftest] [--scratch DIR] "
                     "[--extend N]")
    scratch = scratch_arg or tempfile.mkdtemp(prefix="egg_sim_probes_")
    os.makedirs(scratch, exist_ok=True)
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)

    framing = derive_framing()
    reset_cycles, idle_after_reset, attempt_bits = framing
    _, _, win = b1.vectors_from_artifacts()
    if len(win) != attempt_bits:
        sys.exit(f"framing derived {attempt_bits} attempt bits but the "
                 f"winning vector is {len(win)} -- refusing to continue")

    print(f"netlist    {b1.NETLIST}")
    print(f"toolchain  {b1.IVERILOG} (native, no container)")
    print(f"framing    derived from {STIMULUS}: {reset_cycles} reset rows, "
          f"{idle_after_reset} idle row(s), {attempt_bits}-bit window")
    print(f"scratch    {scratch}")
    print(f"--extend   {extend}\n")

    compile_env = model_files(b1.NETLIST)
    cells, files, includes, missing = compile_env
    if missing:
        sys.exit("no model in the PDK cache for: " + ", ".join(missing))
    print(f"models     {len(files)} files for {len(cells)} cell types\n")

    records = []

    # --- Positive control, first and gating -------------------------------
    rows, notes, after = frame_window(framing, win, extend)
    control, _ = run_probe("control-winning", rows, notes, scratch,
                           compile_env,
                           {"fed": "the unmodified winning frame",
                            "after_row_used": after})
    records.append(control)
    print(f"[1/6] control-winning        success="
          f"{'YES' if control['success_ever'] else 'no '} "
          f"msg={control['trimmed_text']!r}")
    if (not control["success_ever"]
            or control["trimmed_bytes"] != WINNING_BYTES):
        print(f"\nPOSITIVE CONTROL FAILED: expected {WINNING_TEXT!r} byte "
              f"for byte with success high, got "
              f"{control['trimmed_text']!r}. Nothing else is trustworthy.")
        return 1
    span = (control["trimmed_first_cycle"], control["trimmed_last_cycle"])

    # --- Probe 1: idle machine --------------------------------------------
    rows, notes, after = frame_idle(framing, IDLE_PROBE_CYCLES)
    rec, _ = run_probe("probe1-idle-300", rows, notes, scratch, compile_env,
                       {"fed": f"reset toggled, then {IDLE_PROBE_CYCLES} "
                               f"cycles with enable never raised",
                        "after_row_used": after})
    records.append(rec)
    print(f"[2/6] probe1-idle-300        success="
          f"{'YES' if rec['success_ever'] else 'no '} "
          f"msg={rec['trimmed_text']!r}")

    # --- Probe 2: enable held, vector streamed twice back to back ---------
    rows, notes, after = frame_window(framing, win + win, extend,
                                      hold_enable=True)
    rec, _ = run_probe("probe2-double-enable-held", rows, notes, scratch,
                       compile_env,
                       {"fed": "winning vector twice back to back, enable "
                               "high 242 cycles and held through extension, "
                               "no reset between",
                        "after_row_used": after})
    records.append(rec)
    print(f"[3/6] probe2-double-held     success="
          f"{'YES' if rec['success_ever'] else 'no '} "
          f"msg={rec['trimmed_text']!r}")

    # --- Probe 3: rst_n pulsed low mid-message ----------------------------
    pulse_at = (span[0] + span[1]) // 2
    rows, notes, after = frame_window(framing, win, extend)
    rows, notes = pulse_reset(rows, notes, pulse_at)
    rec, _ = run_probe("probe3-midmessage-reset", rows, notes, scratch,
                       compile_env,
                       {"fed": f"the winning frame with rst_n low for one "
                               f"cycle at cycle {pulse_at}, mid-message "
                               f"(control streamed cycles "
                               f"{span[0]}..{span[1]})",
                        "after_row_used": after,
                        "pulse_cycle": pulse_at})
    records.append(rec)
    print(f"[4/6] probe3-midmsg-reset    success="
          f"{'YES' if rec['success_ever'] else 'no '} "
          f"msg={rec['trimmed_text']!r}")

    # --- Probe 4a: 60-bit window ------------------------------------------
    rows, notes, after = frame_window(framing, win[:PREFIX_BITS], extend)
    rec, _ = run_probe("probe4a-60bit-window", rows, notes, scratch,
                       compile_env,
                       {"fed": f"a {PREFIX_BITS}-bit enable window carrying "
                               f"the winning vector's prefix",
                        "after_row_used": after})
    records.append(rec)
    print(f"[5/6] probe4a-60bit          success="
          f"{'YES' if rec['success_ever'] else 'no '} "
          f"msg={rec['trimmed_text']!r}")

    # --- Probe 4b: 242-bit window, normally framed -------------------------
    rows, notes, after = frame_window(framing, win + win, extend)
    rec, _ = run_probe("probe4b-242bit-window", rows, notes, scratch,
                       compile_env,
                       {"fed": "a 242-bit enable window carrying the "
                               "winning vector doubled, enable falling "
                               "after the window as in a normal attempt",
                        "after_row_used": after})
    records.append(rec)
    print(f"[6/6] probe4b-242bit         success="
          f"{'YES' if rec['success_ever'] else 'no '} "
          f"msg={rec['trimmed_text']!r}")

    # --- Verdict ------------------------------------------------------------
    new_claims = [r for r in records if r["is_new_string"]]
    result = {
        "netlist": b1.NETLIST,
        "toolchain": {"iverilog": b1.IVERILOG, "vvp": b1.VVP,
                      "flags": "-g2012 -DFUNCTIONAL -DUNIT_DELAY=#1",
                      "container": None},
        "framing_derived_from": STIMULUS,
        "framing": {"reset_cycles": reset_cycles,
                    "idle_after_reset": idle_after_reset,
                    "attempt_bits": attempt_bits,
                    "extend": extend,
                    "cycle_model": "tools/sim/harness.py clocked_bench: "
                                   "inputs move while clk low, outputs "
                                   "sampled before the rising edge"},
        "winning_vector": win,
        "known_messages": list(KNOWN_MESSAGES),
        "positive_control": {"expected": WINNING_TEXT, "passed": True},
        "fifth_message_found": bool(new_claims),
        "probes": records,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=1)

    print(f"\npositive control: PASS ({WINNING_TEXT!r} byte for byte, "
          f"success high)")
    for r in records:
        shown = (list(zip(r["segments"], r["segment_classes"]))
                 or [("<silence>", "-")])
        print(f"  {r['id']:<26} {shown!r} "
              f"new={'YES' if r['is_new_string'] else 'no'}")
    print(f"\nfifth message: "
          f"{'FOUND -- see new_segments' if new_claims else 'none'}")
    print(f"wrote {OUT_JSON}")
    return 0


def selftest():
    """No simulation. The frame machinery and the rendering convention."""
    failures = []

    def check(name, ok):
        print(f"  {'pass' if ok else 'FAIL'}  {name}")
        if not ok:
            failures.append(name)

    print("selftest (no simulation is run)")

    # 1. Framing really is derived, and from this repository's artifact it
    #    matches what the battery's constants hardcode.
    framing = derive_framing()
    reset_cycles, idle_after_reset, attempt_bits = framing
    check("derived reset run is positive", reset_cycles >= 1)
    check("derived framing matches the battery's constants",
          (reset_cycles, idle_after_reset, attempt_bits)
          == (b1.RESET_CYCLES, b1.IDLE_AFTER_RESET, b1.BITS))
    _, _, win = b1.vectors_from_artifacts()
    check("winning vector fits the derived window",
          len(win) == attempt_bits)

    # 2. Frame builders: shape, vector carriage, fresh rows.
    rows, _, _ = frame_idle(framing, 10)
    check("idle frame never raises enable",
          all(r["enable"] == 0 for r in rows))
    check("idle frame is reset + idle + N",
          len(rows) == reset_cycles + idle_after_reset + 10)
    rows, _, _ = frame_window(framing, win, 8)
    check("window frame carries the vector",
          "".join(str(r["I"]) for r in rows if r["enable"] == 1) == win)
    check("window frame equals the battery's frame for the same vector",
          rows == b1.frame_single(win, 8, "idle")[0])
    held, _, after = frame_window(framing, "10", 4, hold_enable=True)
    check("hold_enable keeps enable high with the last bit",
          after == {"rst_n": 1, "enable": 1, "I": 0}
          and all(r["enable"] == 1 for r in held[-4:]))
    dbl, _, _ = frame_window(framing, win + win, 8)
    check("doubled window carries the vector twice",
          "".join(str(r["I"]) for r in dbl if r["enable"] == 1) == win * 2)

    # 3. The reset pulse touches exactly one row, and only rst_n on it.
    rows, notes, _ = frame_window(framing, win, 8)
    pulsed, _ = pulse_reset(rows, notes, 100)
    diffs = [i for i, (a, b) in enumerate(zip(rows, pulsed)) if a != b]
    check("pulse changes exactly one row", diffs == [100])
    check("pulse changes only rst_n",
          pulsed[100] == {**rows[100], "rst_n": 0})
    check("original frame is not mutated", rows[100]["rst_n"] == 1)

    # 4. Rendering: the battery's escape, itself proven equal to stage 7's.
    import stage7_output
    check("escape() equals stage7_output.escape() on 0..255 and None",
          all(b1.escape(v) == stage7_output.escape(v)
              for v in list(range(256)) + [None]))

    # 5. Segmenting: splits on idle and on undefined, in order.
    segs, _, live, undef = stream_segments(
        [{"O": "00000000"},
         {"O": "01001000"}, {"O": "01001001"},   # HI
         {"O": "xxxxxxxx"},                       # undefined splits too
         {"O": "01001111"}, {"O": "01001011"},   # OK
         {"O": "00000000"}])
    check("segments split on idle and undefined",
          segs == ["HI", "OK"] and live == 4 and undef == 1)
    check("known-message set is the four strings",
          set(KNOWN_MESSAGES)
          == {"TRY AGAIN", "(* TWO STARS *)", "EMPTY SKY", "BIG BANG"})
    check("a known segment classifies as known",
          classify("TRY AGAIN") == "known")
    check("a mid-message cut classifies as a truncation",
          classify("(* TWO ") == "truncation of '(* TWO STARS *)'")
    check("a truncation is prefix-only, not substring",
          classify("TWO STARS") == "new")
    check("a novel segment classifies as new",
          classify("HELLO") == "new")
    check("segments are never empty, so classify never sees ''",
          stream_segments([{"O": "0"}, {"O": "0"}])[0] == [])

    print(f"\nselftest: {'PASS' if not failures else 'FAIL'} "
          f"({len(failures)} failure(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
