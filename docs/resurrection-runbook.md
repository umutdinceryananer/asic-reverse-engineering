<!-- Generated 4 September 2026 by a seven-agent read of this repository.
     Facts marked [v] were verified against the working tree that night.
     This is a resurrection aid, not a stage document. -->

Everything checked. Two argv shapes only, both mechanically substitutable. Here is the runbook.

---

# RESURRECTION RUNBOOK — gds-teardown on Linux Mint, tonight

Everything below was verified against the working tree, not just the readers' notes. Verified-tonight facts are marked **[v]**. Where the repo does not state something, it says so.

---

## 1. BLOCKERS

### B1 — Docker. Native OSS CAD Suite binaries CAN substitute. Smallest change is a PATH shim, zero repo edits. No sudo.

**The problem, exactly.** `command -v docker` returns nothing **[v]**. Nine files reference docker **[v]**; eight actually invoke it. Six of the seven pipeline call sites have no try/except, so they raise a bare `FileNotFoundError` traceback rather than a message.

**There is no escape hatch.** `grep -rn 'os.environ\|getenv' tools/` returns exactly one hit — `verify_determinism.py:70`, setting `PYTHONHASHSEED`, unrelated. No env var, no flag, no config, no native mode. All three readers who looked agree, and I confirmed it.

**Why substitution is sound.** Every call site uses one of exactly two argv shapes **[v]**:

```
A:  docker run --rm -v <abspath(cwd)>:/work -w /work <IMAGE> <command...>     (7 sites)
B:  docker run --rm <IMAGE> cat /opt/gds-teardown/TOOL_VERSIONS               (verify_toolchain only)
```

The bind mount maps the repo root to `/work` and `-w /work` makes the container cwd equal the repo root. Every path handed to yosys/iverilog/z3 is repo-relative. The only absolute paths in any command string are `/tmp/sim.vvp` (`tools/sim/run.py:110`, `tools/sim/harness.py:187`) and `/tmp/fn.vvp` (`tools/verify_functions.py:120`), both valid natively. So stripping the prefix and exec-ing the remainder from `/home/umut/Projects/gds-teardown` reproduces the invocation exactly.

The seven pipeline sites and their images **[v]**:

| File:line | Image | Runs |
|---|---|---|
| `tools/stage3_graph.py:176` | eda | `yosys -p <script>` |
| `tools/verify_equiv.py:167` | eda | `yosys -s out/<t>/equiv.ys` |
| `tools/stage5_corpus.py:1007` | eda | `yosys -p <script>` |
| `tools/stage6_invert.py:454` | eda | `z3 <path>` |
| `tools/sim/run.py:117` | sim | `bash -c "…iverilog…; vvp /tmp/sim.vvp"` |
| `tools/sim/harness.py:191` | sim | `bash -c "…iverilog…; vvp /tmp/sim.vvp"` |
| `tools/verify_functions.py:124` | sim | `bash -c "…iverilog…&& vvp /tmp/fn.vvp"` |

`tools/sim/harness.py:166` is `def icarus(netlist, bench_path, extra_sources=(), image=IMAGE)` with `IMAGE` imported from `run.py` at line 42 **[v]** — no caller passes `image`, so `replay.py`, `stage7_output.py` and `verify_output.py` all route through the sim path. All required binaries exist at `~/tools/oss-cad-suite/bin/`: `yosys`, `iverilog`, `vvp`, `z3`, `yosys-smtbmc`, `yosys-abc` **[v]**.

**Option A — the shim (recommended). No sudo. No repo edits.**

Write an executable named `docker` earliest on PATH that drops the prefix and execs the rest in the current directory. Parse generically so shape B works too: after `run`, skip `--rm`; skip `-v`/`-w`/`-e` **with their values**; the next token is the image; exec everything after it.

> **This shim is not in the repository.** Nothing in `docker/Dockerfile`, `tools/`, `docs/`, `README.md` or `CLAUDE.md` ships, mentions or contemplates one. It is authored tonight. Two readers independently converged on it as the minimal path; that is agreement between readers, not repo sanction.

**Option B — edit the seven functions.** Real source change, and it carries a self-check trap: `tools/review_packet.py:487` derives the container column as `any("docker" in text for text in code_strings(path)) or calls_the_harness(path)` **[v]**. Delete the literal `"docker"` from those code strings and `verify()` raises *"declared a container row and its source never mentions docker"* and refuses to write the packet — `docs/problems.md` 53, already lived through once. Prefer Option A.

**Sudo:** none. Installing Docker would need it and this box has no passwordless sudo — the shim is precisely how you avoid that conversation tonight.

### B2 — `verify_toolchain.py` cannot pass tonight under any option. Skip it. Do not `--record`.

Measured tonight against `tools/TOOL_VERSIONS.recorded` **[v]**:

| Recorded | This machine |
|---|---|
| `iverilog  Icarus Verilog version 11.0 (stable) ()` | `Icarus Verilog version 14.0 (devel)` |
| `yosys     Yosys 0.23 (git sha1 7ce5011c24b)` | `Yosys 0.68+58 (git sha1 edbc62a44-dirty)` |
| `z3        Z3 version 4.8.12 - 64 bit` | `Z3 version 4.15.5 - 64 bit` (oss-cad-suite) |
| `base  debian:bookworm-slim@sha256:abd67ffc…` | no native counterpart |
| `debian    12.15` | no native counterpart |

`tools/verify_toolchain.py:110` does exact line-by-line string equality and returns 1 on any difference. Without a shim it exits 2 with *"RESULT: fail, nothing was compared"* — the one site that catches the error, at lines 63-64. With a shim it will try `cat /opt/gds-teardown/TOOL_VERSIONS`, which does not exist natively, and fail the same honest way. Nothing in stages 1-3 reads the `out/<target>/TOOL_VERSIONS` stamp. **Do not run `--record` to go green** — `docs/problems.md` 36: re-recording must be a decision with a reason, not a side effect, and re-recording here silently voids the version premise behind entries 18 and 40.

**Reader disagreement, unresolved:** one reader reported `.venv-linux/bin/z3` as z3-solver **5.0.0**; I measured the oss-cad-suite z3 as **4.15.5**. Both are probably true — they are different binaries. Whichever is earlier on PATH is the one stage 6 gets. Decide deliberately; the repo does not.

### B3 — PATH ordering will silently give you the wrong Python. No sudo.

`~/tools/oss-cad-suite/environment` prepends both `bin` and `py3bin` and exports `VIRTUAL_ENV`. `py3bin` holds python3.11 with no gdstk and no klayout, and no unversioned `python` at all. Bare `python` does not exist on this box either.

Readers split on the fix: one said "source the suite, then activate the venv"; another said "never rely on bare `python` after sourcing." **Take the robust answer: source the suite for the tool binaries, then call the interpreter by absolute path.** A venv interpreter invoked absolutely resolves its own `sys.prefix` and ignores the exported `VIRTUAL_ENV`.

### B4 — `.venv/` is the dead macOS venv.

`pyvenv.cfg` reads `home = /opt/homebrew/opt/python@3.14/bin`, `version = 3.14.7`, `/Users/umut/...`. It has no interpreter binary. **Do not source it, and do not run `python -m venv .venv` from `CLAUDE.md:96`** — that line would clobber or shadow the working venv. `.venv-linux` appears nowhere in `CLAUDE.md`, `docs/endgame.md` or `docs/packages.md`; substitute it in every documented command.

Python 3.14 is **not** required. The only 3.14 construct in the tree is `from compression import zstd` at `tools/fetch_open_pdks.py:113`, function-local inside `fetch()`, behind an early return that the already-populated `pdk/open_pdks_sky130A/sky130_fd_sc_hd.gds` trips. Unreachable tonight.

### B5 — `out/puzzle/` is empty and `out/synth/` has no corpus. **[v]**

`out/puzzle/` lists nothing. `out/synth/` holds only `beh.vvp`, `gate.vvp`, `recon_selftest.gds` — no `index.json`, no per-circuit directories. Consequences: the entire puzzle chain rebuilds from stage 1, and `stage4_registers.py --score`/`--compare`, `verify_corpus.py`, `verify_output.py`, `corpus_reach.py` and `verify_figures.py`'s corpus rows cannot run until `stage5_corpus.py` regenerates it. **The puzzle path itself does not need the corpus** — stages 4/6/7 read only `out/<target>/{graph.json,netlist.v,instances.json}`.

### B6 — `out/warmup/solution_post_reset.json` is missing. **[v]**

`out/warmup/` has `solution.json` only. The documented `replay.py warmup --solution out/warmup/solution_post_reset.json` will exit before simulating. Run `stage6_invert.py warmup --post-reset` first; `docs/06` records 25.7 s over 10 solver calls, most of it docker round-trip that vanishes natively.

### B7 — `verify_blocks.py` is expected to fail. Not a regression.

`CLAUDE.md`'s own capitals: "CURRENTLY FAILING". It scores stage 4's grouping against the warm-up DEF's `[8, 8]`; the committed criterion answers `[16]`. `docs/packages.md`: "That is deliberate. Committing a criterion is the author's decision." A pass here would be the surprise.

### B8 — Memory and runtime are not stated anywhere.

No document and no tool in the repository records a RAM requirement or a stage 5 wall clock. `docs/problems.md` says nothing about memory in 1689 lines. This box shows 6864 MB total, ~2774 MB available **[v]**. The largest recorded SMT2 in the repo is 8.4 MiB. Nothing clears or rules out 6.7 GiB for the puzzle BMC.

---

## 2. ORDERED COMMANDS

Preamble for every shell. Run from the repo root — every data path in `tools/` is cwd-relative (`PDK_DIR = os.path.join("pdk", "sky130_fd_sc_hd")` at `stage1_cells.py:61`; `tb_puzzle.v:43-44` does `$readmemb("out/puzzle/stimulus.txt", …)`).

```bash
cd /home/umut/Projects/gds-teardown
source ~/tools/oss-cad-suite/environment
export PATH="$HOME/bin/dockershim:$PATH"     # B1 Option A, authored tonight
PY=/home/umut/Projects/gds-teardown/.venv-linux/bin/python
```

**Gate legend:** **[GATE]** must pass before moving on. **[gate]** informative — read it, but a failure is diagnosable without stopping. **[RED]** expected to fail.

### Phase A — free checks, no shim needed

```bash
$PY -c "import sys; print(sys.version)"                                    # expect 3.12.3
$PY -c "import gdstk, klayout.db, numpy; print(gdstk.__version__)"         # expect 1.0.1  [GATE]
$PY -c "import pathlib; [compile(p.read_text(encoding='utf-8'), str(p), 'exec') for p in sorted(pathlib.Path('tools').rglob('*.py'))]; print('ok')"
$PY tools/fetch_pdk.py --verify                                            # local only; 437 gds/lef
$PY tools/fetch_open_pdks.py --verify                                      # local only
$PY tools/review_packet.py --preflight                                     # enumerates what the shim costs
```

**Never run `$PY tools/fetch_pdk.py` with no arguments** — it hits the GitHub tree API with no exception handling, and re-fetching at a different commit would reintroduce `docs/problems.md` 15 at unknown scale. `--verify` is purely local.

Under the shim, `--preflight` will get past `shutil.which("docker")` and then fail `docker image inspect gds-teardown-sim:latest`, reporting the images as unbuilt. That is honest; the packet is a deliverable, not a pipeline dependency.

### Phase B — warmup extraction, container-free (runs with or without the shim)

```bash
$PY tools/compare_libraries.py                     # 9 of 437 shared cells differ          [gate]
$PY tools/compare_libraries.py --selftest          # catches a 1 nm move                   [gate]
$PY tools/stage1_cells.py warmup                   # -> out/warmup/instances.json
$PY tools/stage2_nets.py warmup                    # -> out/warmup/netlist.{json,v}
$PY tools/compare_def.py warmup                    # 230/230 cells, 84/84 nets             [GATE]
$PY tools/stage2_unionfind.py warmup               # second extractor agrees 86/86         [GATE]
$PY tools/stage1_cells.py warmup --library pdk/open_pdks_sky130A   # exact 230, structural 0  [gate]
```

`compare_def.py` is the strongest ground truth you have; if it is not clean, stop and fix before spending anything on the shim.

### Phase C — warmup, shim-dependent. First real test of native tools.

```bash
$PY tools/sim/run.py warmup                        # 65536 pairs, 0 mismatches             [GATE]
$PY tools/stage3_graph.py warmup                   # yosys: 0 problems, 79 cells, 84 wires
$PY tools/sim/run.py warmup --netlist out/warmup/graph.v   # round trip                    [GATE]
$PY tools/stage3_crosscheck.py warmup              # 84 nets, 16 flops, 33 cone roots      [GATE]
$PY tools/stage3_crosscheck.py warmup --selftest   # all 17 corruptions caught             [GATE]
$PY tools/verify_annotations.py warmup             # against 00_source.v                   [GATE]
$PY tools/verify_equiv.py warmup                   # 153 correspondence points, all proven [GATE]
```

`sim/run.py warmup` passing is the moment the shim is proven. `verify_equiv.py warmup` is what says `graph.json` is the right circuit — stage 6 solves `graph.json`, so if this is red, stage 6 will confidently solve the wrong design.

`stage3_crosscheck.py` needs no container even though it imports `stage3_graph` (`review_packet.py:454-458` records the deliberate non-transitivity) — but it needs `graph.json`, which does.

**Yosys 0.68 vs the recorded 0.23 is unmodelled by the repo.** Nothing states which Yosys versions the `write_json` parse is valid for. Treat "yosys: 0 problems, 79 cells, 84 wires" plus a clean `stage3_crosscheck` as your acceptance test — net identity is keyed on `(instance, pin)` sets, never names, so a renumbering by 0.68 is survivable and a mis-parse is catchable.

### Phase D — stage 4 warmup and the code-level gates

```bash
$PY tools/verify_functions.py                      # 850 patterns, 0 disagreements         [GATE]
$PY tools/verify_functions.py --selftest
$PY tools/stage4_registers.py --selftest           # 7 hand-computed rows, no corpus needed [GATE]
$PY tools/verify_metrics.py                        # independent implementation            [GATE]
$PY tools/verify_metrics.py --selftest
$PY tools/stage4_registers.py warmup               # -> out/warmup/registers.json
$PY tools/verify_grouping.py warmup                # single linkage vs brute force         [GATE]
$PY tools/verify_grouping.py warmup --selftest
$PY tools/verify_cone.py warmup                    # proven == (a + b == 496) over 65536   [GATE]
$PY tools/verify_blocks.py                         # exit 1, [16] vs [8,8]                 [RED]
```

`verify_functions.py` gates `common/boolexpr.py`, which both stage 4's cone composition **and** stage 6's transition relation compute with. Run it before believing either.

`verify_cone.py` cannot be pointed at the puzzle — it is exhaustive and stops at 22 support bits; `success`'s cone has 57.

### Phase E — stage 6 and 7 on the warmup

```bash
$PY tools/stage6_invert.py warmup                  # depth 8, all 2^16 starts, ~28 calls   [GATE]
$PY tools/sim/replay.py warmup                     # trace through stage 2's netlist       [GATE]
$PY tools/stage6_invert.py warmup --post-reset     # -> solution_post_reset.json (B6)      [GATE]
$PY tools/sim/replay.py warmup --solution out/warmup/solution_post_reset.json    #         [GATE]
$PY tools/stage7_output.py warmup --extend 6       # "stream NONE" is CORRECT here         [GATE]
$PY tools/stage7_output.py warmup --extend 6 --after zeros
```

`stream NONE` on the warm up is the right answer, not a failure — its only output `S` is one bit wide. The post-reset replay prints a starting-state warning; `docs/06` says that warning is correct under this mode and must not be suppressed.

`--solution` must be the **second** token — `tools/sim/replay.py:218` is `if len(args) >= 3 and args[1] == "--solution"` **[v]**. `replay.py --solution X warmup` exits with usage.

### Phase F — the puzzle path

`CLAUDE.md` assigns these to the author, not an assistant: "the assistant never opens `puzzle/puzzle.gds` or `puzzle/example_inputs.vcd`." Run them yourself.

```bash
$PY tools/stage1_cells.py puzzle          # EXITS 2 BY DESIGN — see traps. 1618 identified
$PY tools/stage2_nets.py puzzle           # expect nets 726 -> 725, "reattached 1 connection(s)"
$PY tools/stage2_unionfind.py puzzle      # 725/725                                       [GATE]
$PY tools/sim/make_puzzle_stimulus.py     # -> out/puzzle/{stimulus,expected}.txt  MUST precede next
$PY tools/sim/run.py puzzle               # 312 cycles, 0 mismatches                      [GATE]
$PY tools/stage3_graph.py puzzle          # yosys: 0 problems, 738 cells, 716 wires
$PY tools/sim/run.py puzzle --netlist out/puzzle/graph.v      # round trip                [GATE]
$PY tools/stage3_crosscheck.py puzzle     # 723/723 agree                                 [GATE]
$PY tools/stage4_registers.py puzzle      # -> registers.json; read bit_order.method
$PY tools/stage4_cone.py puzzle           # 47 cells / 57 boundary signals
$PY tools/stage4_cone.py puzzle --list
```

Then the long pole. **Start it early and let it run** — `docs/endgame.md` reversed its own plan specifically to put this first.

```bash
$PY tools/stage6_invert.py puzzle --post-reset --start 121 --depth 160
```

> **Genuine repo disagreement, do not smooth over.** `README.md:230` is `python tools/stage6_invert.py puzzle --post-reset` with no bounds, and `DEFAULT_DEPTH = 16` (`stage6_invert.py:96`) **[v]** — that searches depths 0..16 only. `docs/06-inversion.md:403-406` **[v]**: *"`example_inputs.vcd` holds two attempts of 121 bits each, 312 rising edges. Start above 121 rather than iterating from 0… `--start 121 --depth 160` is the shape of it."* The README line will burn time searching far below the answer. **Follow docs/06.**

Recovery if it exits 1 saying "looked to depth N": `--start N --depth 160`, resume rather than restart.

Then, and only then:

```bash
$PY tools/sim/replay.py puzzle --solution out/puzzle/solution_post_reset.json          # [GATE]
$PY tools/stage7_output.py puzzle --solution out/puzzle/solution_post_reset.json --extend 64
$PY tools/stage7_output.py puzzle --solution out/puzzle/solution_post_reset.json --extend 64 --after zeros
```

`README.md:235-236`: *"Run the replay before the extraction. Stage 7 will read a bus faithfully and report the wrong design's bytes if the trace does not reproduce."* If replay fails, the trace is not a solution — it is a modelling error in `graph.json`. Do not proceed to stage 7 to "see what it says."

Raise `--extend` until the tail goes idle: the trimmed span must **end before** the last simulated cycle, or you are reading a prefix.

### Phase G — the corpus. Optional tonight; skip if time is short.

```bash
$PY tools/stage5_corpus.py --list        # catalogue, no yosys, safe
$PY tools/stage5_corpus.py               # 98 yosys runs + 197 in-process graph builds
$PY tools/verify_corpus.py               # 12 rules, 762 uses                            [gate]
$PY tools/verify_corpus.py --selftest
$PY tools/verify_output.py               # the ONLY gate on stage 7's byte decoder       [gate]
$PY tools/stage4_registers.py --score    # EXPECT FAILURE on toolchain drift
$PY tools/stage4_registers.py --compare  # EXPECT FAILURE on toolchain drift
```

`--score`/`--compare` fail on movement in **either** direction against recordings measured under Yosys 0.23. A different abc will very likely move them. That is drift, not regression — do not re-record to go green. `verify_corpus.py` and `verify_output.py` carry no recordings and check declared-vs-found, so they are the corpus gates most likely to survive.

---

## 3. THE HUMAN DECISION

Stage 4 hands you a question it has deliberately refused to answer.

The chip holds 92 flip-flops — one-bit memory cells. Some belong together as a single multi-bit number (eight of them forming a byte, say); others are unrelated. Nothing in the layout labels these groups. Recovering them is the difference between "92 loose bits" and "a 72-bit value, a 12-bit counter, and two small fields."

The tool tries six different ways of guessing the grouping and **commits to none**:

1. **Control signature** — group flops sharing a clock, reset, set and hold-enable signal.
2. **Connected components** — group flops that talk to each other.
3. **Colour refinement** — repeatedly split groups whose members have different neighbours.
4. **Control + flow split**, 5. **all three combined** — hybrids.
6. **Placement locality** — group flops that sit near each other physically, the only criterion that reads no wire at all. The puzzle announcement says *"The circuit is physically arranged to hint at its functionality, so look closely at the layout!"*

On the puzzle these produce: R1 (12 bits), R2 (4 bits), R3 (4 bits) — clean — and **R0, a 72-bit blob**. `docs/04`, verbatim: *"**R0 is not resolved.** 72 bits under one control signature is a blob, and three rounds of refinement want to split it into pieces of 23, 22, 8, 4, 4, 4, 2, 2 and three singletons. Those are reported as candidates and not applied, because refinement scores worse overall. This is the part of the puzzle a person has to read."* Those eleven pieces sum to exactly 72.

**The decision: are R0's 72 bits one register, or eleven, or something between?**

**Why no score settles it.** The two scoring metrics rank the criteria in *opposite orders*. Exact-match puts the control signature first — but that ranking is an artefact: 109 of 137 corpus netlists declare a single register, so a criterion that returns "one group" and does nothing else scores 109 (`docs/problems.md` 35). On NMI, the control signature scores 0.001, which to three decimals *is* that do-nothing null model. And on the one real design whose true partition is known — the warm-up DEF, `[8, 8]` — the corpus's top-ranked criterion is **wrong** and its fourth-ranked is right. The criteria fail in mirror image: connected components shatters a plain register and merges a chained pair; refinement and the flow split shatter a shift register.

**The evidence a person reads instead.** (a) `bit_order` — on the warm up, 16 flops under one control signature come out as two chains of eight, which is `sr_a` and `sr_b` exactly: the boundary the control signature cannot see, said in a second language. A guessed order is worse than none, so 95 of 137 corpus netlists get `method: null` with a stated reason. (b) The placement clustering with its printed threshold profile at 1..12 rows — right on the warm up including membership, but n = 1, and its single parameter (`LINK_ROWS = 3`) is *"one parameter fitted to one data point, which is said here rather than hidden."* Two caveats specific to the puzzle: it measures corner-to-corner, and the puzzle mixes 9.66 µm and 7.36 µm flops, so corner and centre differ by up to 1.15 µm — 14% of the threshold; and the plateau that justified the threshold was measured on a two-register design, so a denser one may have no plateau. (c) The register dependency graph. (d) `stage4_cone.py puzzle`: `success`'s cone is 47 cells over 57 boundary signals, **every one a bit of R0** — so whatever R0 is, it is what the chip checks to decide you have won.

**One upstream hazard.** The hold-enable net is a term in the control signature and comes from a *structural search* that `docs/problems.md` 28 admits is a lower bound — 12 of 46 declared enables found in the corpus. A hold missed on only *some* bits of one register invents a boundary that is not there (`docs/problems.md` 45, verdict **open**), and *"a false boundary is worse than a missed one, because a missed boundary leaves a group a person still has to read and a false one looks like an answer."*

---

## 4. TRAPS

- `tools/stage1_cells.py puzzle` **exits 2 on a good run** (`:288-289` **[v]**, the 36 non-`VIA_` marker rectangles); `instances.json` is written first — do not wrap the puzzle path in `set -e`.
- `sim/make_puzzle_stimulus.py` MUST run before `sim/run.py puzzle`; `tb_puzzle.v:43-44` `$readmemb`s `out/puzzle/{stimulus,expected}.txt` by hardcoded path and `out/puzzle/` is empty, so the run would compile and compare against garbage.
- `--post-reset` writes `solution_post_reset.json`, **not** `solution.json` — stage 7 without an explicit `--solution` will look for the wrong file.
- `replay.py`'s parser accepts `--solution` **only as the second token** (`:218` **[v]**).
- `README.md:230` omits `--start/--depth` and `DEFAULT_DEPTH = 16`; `docs/06:406` says `--start 121 --depth 160`. The repo contradicts itself; follow docs/06.
- Run the replay **before** stage 7 — a solver result is a claim about the model, not about the circuit.
- `docs/problems.md` 21: the puzzle simulation replays 312 cycles byte for byte **both before and after** a real structural defect — a passing `sim/run.py puzzle` does **not** certify a rebuilt extraction.
- `docs/problems.md` 22: the obvious repair for that defect left the warm up bit-identical while silently moving 16 puzzle nets — the rejected fix passed the warm-up gate perfectly.
- `docs/problems.md` 52: the replay bench once declared every output a scalar; `wire O;` would drive bit 0 and leave seven bits floating, with no gate able to notice because no gate runs on the puzzle. Every place the puzzle is wider than the warm up is a place an assumption can survive the whole project.
- `docs/problems.md` 20: if a rebuilt `out/puzzle` shows mismatches with plausible-looking bytes, do **not** nudge the index — the fix is `samples[:-1]`, and an offset applied without knowing why gives the right answer for the wrong reason.
- `docs/problems.md` 18: `-DFUNCTIONAL -DUNIT_DELAY=#1` are not optional; without them every output stays `x` and the netlist looks broken when it is not. Version-independent, recurs identically under Icarus 14.0.
- `docs/problems.md` 5: keep `pdk/sky130_fd_sc_hd/cells/<cell>/*.v` structure intact — per-strength wrappers include their base by bare name and reach `../../models/...` for UDP primitives. Do not flatten or "tidy" `pdk/`.
- `docs/problems.md` 40: Yosys pass order is load-bearing (`async2sync` before SAT; `proc; flatten; opt_clean` not `prep -flatten`; `-icells` on equiv_struct) — all tuned against 0.23, behaviour under 0.68 not stated.
- `docs/problems.md` 33: a failed corpus build once overwrote a good `index.json` and the verifier passed 0/0. The builder now refuses to rewrite on any failure — but no index exists at all right now, so one failure leaves you with nothing.
- `docs/problems.md` 2: *"Verify what a step produced, not its exit code"* — `docker build | tail` reported tail's status and a failed build looked successful twice. Applies to any piped step tonight.
- `tools/common/liberty.py:107-118`: the first `stage3_graph` run may re-parse 17 MB of liberty JSON (~30 s) and **write a cache into `pdk/`** — expect the first run to be much slower and to touch the PDK directory.
- Native `iverilog` writes fixed absolute `/tmp/sim.vvp` and `/tmp/fn.vvp` — in containers these were private, natively they are shared. **Run sim-backed stages sequentially**, never two in parallel.
- `compare_def.py puzzle` does not exist as a check — `TARGETS['puzzle']['def']` is `None`.
- `stage2_nets.py` always returns 0 (`:464`); its driver check prints but does not set exit status. **Read** the "0 undriven with a load, 0 with two drivers" line.
- `stage2_unionfind.py` returns 0 with a green message if `netlist.json` is absent — a clean exit that checked nothing. Run stage 2 first.
- On the puzzle, union-find legitimately lists 15 single-pin `clkbuf_4` X terminals the KLayout path does not; that still prints agreement and exit 0.
- `docs/03` is stale: it says the cross-check selftest has six corruptions; the code has 17 and `CLAUDE.md` is correct.
- `docs/problems.md` 6, the most expensive error in the project: a claim taken from a README sentence about an 8 KB file nobody opened. The fix was *"Open the file."* Tonight's form: `puzzle/warmup/{00_source.v,01_netlist.v,03_post_place_and_route.def}` are present and are the strongest ground truth in the repo; `out/synth` is not.

---

## 5. TIME

The repo records **no** wall-clock for stage 5 and **nothing at all** on memory. Figures below are either repo-recorded (marked) or my derivation from stated parts — say so if you quote them.

| Phase | Estimate | Confidence |
|---|---|---|
| B1 shim + PATH/venv setup | 20–40 min | Medium. Straightforward; budget for one round of "the shim ate an argument." |
| A — free checks | 5 min | High |
| B — warmup extraction | 10–15 min | Medium-high. `stage2_unionfind warmup` slices 10318 polygons into 13970 rectangles. |
| C — warmup stage 3 + sim | 15–30 min | **Low.** First native run of everything; add ~30 s for the liberty cache rebuild. This is where the shim actually gets tested. |
| D — stage 4 gates | 15–25 min | Medium. `verify_cone warmup` is exhaustive over 65536; `verify_functions` is 850 patterns. |
| E — stage 6/7 warmup | 5–10 min | High. Repo-recorded: 72.4 s and 25.7 s under docker, mostly round-trip that vanishes natively. |
| F — puzzle stages 1-3 | 30–60 min | **Low.** Union-find flattens 73683 polygons into 103450 rectangles — the heaviest step in the repo, on a box with ~2.8 GB available. |
| F — puzzle stage 6 BMC | **Unknown** | **None. The overrun risk.** |
| F — puzzle stage 7 | 10–20 min | Medium, plus iteration on `--extend`. |
| G — corpus | 20–90 min | **Low.** No recorded figure exists. |

**What will overrun, in order:**

1. **Puzzle stage 6.** `docs/06` closes with *"Nothing here has run on the puzzle."* The closest analogue is `scale16` — 90 flops (vs 92) but 280 cells (vs 738) — at depth 121: 13.9 s, 3.8 MiB, 1 round. That is encouraging, not predictive: the puzzle has 2.6× the cells. What is stated: *"Solve time is close to flat in depth"* and *"what actually drives the wall clock is the number of robustness rounds, and each round is one more whole copy of the unrolled design"* — `MAX_ROUNDS = 8` bounds it. **Start this the moment `stage3_graph.py puzzle` and `stage3_crosscheck.py puzzle` are green, and do Phase D/G while it runs.** That reordering is `docs/endgame.md`'s own correction to itself. If it runs for hours, `docs/endgame.md` calls that a signal, not a hang: bound it in another terminal with a small `--depth` and see what the scale costs.
2. **The corpus (Phase G).** 98 yosys invocations plus 197 in-process graph builds. Arithmetic from stated parts (docker round-trip 1.1–1.5 s eliminated natively; stage 3 measured at 1.1 s for 280 cells and 1.4 s for 1136) puts it in minutes rather than hours — **my derivation, not a recorded figure**. It is all-or-nothing on the index and its scoring gates will probably fail on drift anyway. **Cut it first.**
3. **Memory.** ~2774 MB available right now on a 6864 MB box **[v]**. Stage 4's miter and stage 6's BMC are the two costs `docs/problems.md` 29 explicitly names as non-linear. Nothing anywhere in the repo says whether they fit. Close other applications before the puzzle BMC.

**Shortest path to a real answer tonight:** shim → Phase B → Phase C (stop if `verify_equiv warmup` is red) → puzzle stages 1-3 → **launch stage 6 puzzle** → Phases D/E while it runs → replay → stage 7. Skip Phase G entirely.

---

# APPENDIX — measured on the Linux box, 4-5 September 2026

The runbook above was written before anything ran. This is what actually
happened, kept here because the reproducibility result is the part that
transfers.

## Docker was installed rather than shimmed

B1's shim was never needed. `docker.io` 29.1.3 is in Ubuntu noble's own
repositories, which Linux Mint 22.3 tracks, so the images were built from
`docker/Dockerfile` unchanged. That also dissolved B2: the `eda` image's
manifest matches `tools/TOOL_VERSIONS.recorded` **byte for byte** -- iverilog
11.0, Yosys 0.23, z3 4.8.12 -- and `verify_toolchain.py warmup` passes rather
than needing a re-record. Installing the packaged Docker was cheaper than
working around its absence, and it kept the toolchain premise behind problems
18 and 40 intact.

B3 and B4 stood: `.venv/` is the retired Mac's, and the interpreter is called
by absolute path as `.venv-linux/bin/python`.

## Artifacts reproduce across macOS and Linux

Every `out/warmup/` artifact from the archive commit was compared against the
same artifact regenerated here. **Byte identical:** `instances.json`,
`netlist.v`, `netlist_unionfind.json`, `graph.json`, `graph.v`, `cone.json`,
`registers.json`, `output.json`, `yosys.json`, `celllib.v`, `blackbox.v`,
`equiv.ys`, `tb_output.v`, `TOOL_VERSIONS`. That is the whole extraction spine,
across two operating systems and two Python versions.

Three things differ, and none of them is a defect:

**`netlist.json`, anonymous net names.** `$88` and `$100` here are `$87` and
`$101` there. These are the names stage 2 gives nets nothing else names, and
they are the trace of a host-Python difference -- 3.14 on the Mac, 3.12 here.
The reason it is harmless is visible one file over: `netlist.v` is byte
identical, because stage 2 renumbers on the way into the Verilog (problem 32).
Everything downstream is byte identical too. **Nothing may key on a `$` name.**
They are not identifiers, they are filler, and this is the neighbour of problem
14: a name that looks stable because it has not moved yet.

**`solution.json`, wall clock only.** `seconds` per solver call and
`solver.total_seconds`. The trace, the property, the predicted outputs and the
depth are identical. Compared with timings stripped, the two files are equal.

**`bmc_k*.smt2`, and the cause is not the machine.** These looked like a
cross-platform difference and are not. `stage6_invert.py:546` writes
`bmc_k{k}.smt2` for the main query, and **both modes write that same name**:
the default run and `--post-reset` overwrite each other's files. The archive's
copies carry `q0_` and `q1_` prefixes -- two copies of the unrolled design,
which is the default mode pinning a counterexample start state as a second
copy. The files here carried only `q0_`, because `--post-reset` pins the start
state directly and never needs a second.

Measured directly: from a clean checkout, running only
`stage6_invert.py warmup` leaves **every** `bmc_k*.smt2` byte identical to the
archive and touches only `solution.json`. Running `--post-reset` afterwards is
what rewrites all nine. So a diff of these files reports which mode ran last,
not which machine ran it, and the CEGAR path did not vary across hosts at all.

## Corpus and gate results

`stage5_corpus.py` full run: **99 circuits, 197 netlists, 0 failed, 2m57s** --
far under the 20-90 minutes estimated above, because the estimate assumed
Docker round-trip costs that a local daemon does not have.

Then, all green and all matching their recordings: `verify_corpus.py` and its
selftest (15 corruptions caught, 12/12 rules tripped), `verify_determinism.py`
(3 of 3 byte identical under both seeds -- it had been red only because the
corpus was missing), `stage4_registers.py --score` and `--compare` (**all 5
criteria match their recording**, which is the check that Yosys 0.23 in the
container really is the toolchain the scores were measured under),
`verify_metrics.py`, `verify_output.py` and its selftest.

## What this machine still cannot tell you

The puzzle path was run only as far as stage 4. Stage 6 has met the puzzle once
and found problems 54 and 55 there; whether the double-driver guard added for
55 stays quiet across the puzzle's 738 cells is **not measured**.
