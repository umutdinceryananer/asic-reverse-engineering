# Endgame — 23 August to 4 September 2026

The build is done except stage 7. From here the critical path is the author's
time, not tooling. This file replaces the stale dates in
`docs/jane-street-asic-roadmap.md`; the phase logic there still stands.

Rule carried over: submit by 2 September, not 4 — the relocation risk sits
exactly on the deadline.

## 23–24 Aug — close the build, open the puzzle

- [ ] Hand Package 6 (stage 7, output extraction) to the worker; supervisor
      validates on return. Last planned package.
- [ ] Commit the five untracked docs (lectures 04–06, references.md with the
      open_pdks revision correction, design-competition-toolchain.md).
- [ ] Author puzzle runs, in order, each cheap:
      - `stage1_cells.py puzzle --library pdk/open_pdks_sky130A` — does
        structural 22 drop to 0? Either answer goes in the writeup.
      - `stage6_invert.py puzzle --post-reset` — eyeball
        "84 cleared and 4 preset; 4 free"; start `--start 121 --depth 160`.
      - `sim/replay.py puzzle --solution out/puzzle/solution_post_reset.json`
        — believe nothing before this passes.
      - `decode_marker_row.py puzzle` — the Morse egg, for the form.

## 24–28 Aug — analysis week (author only)

Goal: an account of what the circuit computes, R0 first. Inputs already on
disk: the criteria matrix, refinement's candidate cuts, bit_order chains,
placement clusters, `stage4_cone.py puzzle` listing, `layout.png` (author may
look), and — once it exists — the string from stage 7.
- Write findings into a dated notes file as you go; the writeup is assembled
  from these, not from memory.
- 26 Aug checkpoint (kept from the old roadmap): if the whole circuit is still
  opaque, narrow to the success condition and describe the rest structurally.
- Cross-check both directions: does the solver's trace match your reading of
  R0? A mismatch is a finding about one of them.

## 29–31 Aug — answer and writeup

- [ ] Stage 7 on the puzzle: the string. Sanity gate: printable text.
- [ ] `docs/writeup.md`, the graded artifact, in the author's hand, on the
      form's four fields: approach / tools built / problems hit
      (docs/problems.md is this, curated) / how the answer was recovered.
      House style per docs/references.md §4: numbers in tables beside their
      baselines, dead ends in one sentence each, adverse results printed in
      the same table as favourable ones.
- [ ] Easter-egg field: emblem (= Jane Street logo, measured), Morse row,
      PER ARENAM AD ASTRA, repo sweep.
- [ ] Draft done by 30 Aug; one full read-through on 31 Aug.

## 1–2 Sep — submit

- [ ] Final packet regeneration; verify_blocks stays the one honest red unless
      the author commits a criterion — either way one sentence in the writeup.
- [ ] Submit the form. Publication-consent and country fields decided.
- [ ] Do not wait for the 4th.

## 4 Sep — after close

- [ ] Repository public. Writeup link mailed per the announcement's invitation.
- [ ] Lecture 07 (stage 7) once its gates have passed — the standing rule,
      lessons after gates.
- [ ] docs/design-competition-toolchain.md: revisit when the follow-up
      competition's rules are published.

## Standing boundaries, unchanged to the end

The pipeline runs on the puzzle by the author's hand only. Interpretation of
what the circuit computes, the winning input's meaning, and the writeup are
the author's. Assistant stays available for concepts, debugging and general
patterns — the same split CLAUDE.md has carried from the start.
