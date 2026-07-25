# Bennu — handoff plan (session of 2026-07-24 / 2026-07-25)

This document is deliberately outside the repo. It is self-contained: another
engineer should be able to pick up from here with no access to the original
Claude Code conversation.

---

## 0. Pointers

| What | Where |
|---|---|
| Repo | https://github.com/jeffshrager/bennu |
| Branch `main` at handoff | `5cc6cbe` "Major Directrory reorg" |
| My merged work | `a792be9`, `5f9b942`, `e03a2b7`, `564b29d` — all in `main` |
| Local branch `o3-stuck-recovery` | https://github.com/jeffshrager/bennu/tree/o3-stuck-recovery (pushed, fully merged into main) |
| Session transcript | `~/.claude/projects/-Users-leo-Desktop-Projects-bennu--claude-worktrees-o3-target-column/e79b52fd-be8c-4568-95be-6b88657dba59.jsonl` |

**There is no session URL.** Claude Code conversations are local JSONL files,
not web-hosted, and they are *not* recoverable from the API key — the key
authenticates API calls and carries no history. To move the conversation to
another machine you must copy that `.jsonl` into the equivalent directory on
the target box: `~/.claude/projects/<absolute-cwd-with-slashes-as-dashes>/`,
then `claude --resume` from that directory. Caveat: the transcript is full of
absolute `/Users/leo/...` paths and was recorded inside a git worktree that
won't exist elsewhere, so it will load but its file references will be stale.

---

## 1. Context — why any of this

Bennu is an automated laboratory testing **methane oxidation** under varying
ozone level, flow rate, illumination shape, and methane level.

The repo was organised as a ship's-log of SSH recipes and dated one-off bash
loops, which actively fought that goal:

- **Experiment data lived in git.** Committed and purged three separate times,
  ~110,000 lines total, all still in `.git`. There was no `.gitignore`.
- **The factorial design existed in exactly one place** — a 628-byte
  undocumented `results/expmodel.txt` whose rows looked like
  `a+1  105000  105500  on,1.5v,lowfan`. Hand-typed after the fact, readable
  only by `axanal.py`, mentioned in no README.
- **Flow rate had zero representation in code.** The word appeared nowhere; it
  was a fan knob turned by hand and recorded as the string `lowfan`/`medfan`.
- **A two-variable bench run meant two terminals.** Start `o3.py` in one and
  `exprun.py` in the other, by hand, then reconcile their clocks *after* the
  run with `annotate_tsv.py --timedelta <a number you work out yourself>`.
- **The two live bench scripts collided over GPIO pin 6.** `run_example.sh`
  drives pin 6 with `exprun.py` while `o3test.sh` drives pin 6 with `o3.py` —
  the ozone generator. A since-deleted protocol script shows this was hit in
  practice and worked around by commenting the line out.

During this session the user did a **major cleanup themselves** (`5cc6cbe`):
146 files / 23 MB → 56 files / 3.1 MB, all experiment data purged, a
`.gitignore` added, and ship vs lab split into `Lab/` and `Remoa/`.

---

## 2. Decisions locked in this session

These were settled with the user explicitly. Treat as requirements.

| # | Decision |
|---|---|
| 1 | `Lab/` and `Remora/` are top-level sibling subprojects in **one** repo. No submodules, no separate repos. (Follows the pattern the removed `ubermodel/` used.) |
| 2 | `Remoa/` is a **typo** → rename to `Remora/`. |
| 3 | Axetris ("ax") is **ship-only**; LI-COR is **lab-only**. There is therefore **no shared instrument driver** and no `common/` needed. |
| 4 | Experiment design and results live **outside the repo**. They must never re-enter it. |
| 5 | Each dated experiment folder carries an `experiment.json` that **describes and controls** the run. |
| 6 | A lab experiment is a **repeating on/off lamp duty cycle** on **GPIO pin 5** — not authored phase blocks. |
| 7 | Ozone is **GPIO pin 6**, closed-loop via `o3.py`, with **one fixed setpoint for the whole run**. |
| 8 | Flow rate and methane level are **fixed per experiment** — metadata to record, not variables to drive. Flow-control hardware comes later; design for it, don't build it. |
| 9 | The manifest records **which methane sensor** was used (`licor` / `ax`). |
| 10 | The lab needs **no methane-reading code at all** — the LI-COR writes its own files into the experiment folder. Do not "helpfully" add a reader. |
| 11 | The experiment path becomes a **shell variable later**. Not now — a single positional argument for today. |

---

## 3. Misplacements in `5cc6cbe`, confirmed but NOT yet fixed

All verified by reading `git show origin/main:<path>`.

**`Lab/run.py` is the ship controller, and it is broken where it sits.**
It drives the four ship lamp quads (`QUAD_GPIO_PINS`, line 22), polls
`lamp.config` (line 36), writes `lamp_controller.log` (line 40) — and does
`from adc_sensors import ...` (line 12) and `from methane_sensor import ...`
(line 44). Both of those modules, plus `lamp.config`, plus its systemd unit,
are in `Remoa/`. As committed, `python3 Lab/run.py` fails at import.
→ move to `Remora/`.

**The ship's cycle-analysis chain is also in `Lab/`.**
`extract_cycles.py` reads `lamp_controller.log*` and writes `cycles.tsv`;
`analyze_cycles.R`, `plot_cycles.R` and `run_analysis.R` all read that
`cycles.tsv`; `anal1.r` is a template with a placeholder filename. That is the
ship pipeline end to end, while `Remoa/log2tsv.py`, `logcat.py` and
`logplot.py` parse the same log from the other directory.
→ move all five to `Remora/`.

**Axetris is split, against decision 3.**
`Lab/` holds `axa.py`, `axb.py`, `axanal.py` and
`AX_LGD_Compact_OI_Rev F.pdf` (2.98 MB — 96% of `Lab/`'s total size), while
`Remoa/` holds `ax.py` and `methane_sensor.py`.
→ move all four to `Remora/`.

**After the moves, `Lab/` should contain exactly:** `o3.py`, `o3test.sh`,
`exprun.py`, `run_example.sh`, `annotate_tsv.py`, `region_corr.r`,
`how_to_corr_in_r.md`, `gpio-pulse.sh`.

---

## 4. The JSON manifest

One `experiment.json` per dated experiment folder, outside the repo.

```json
{
  "experiment": "20260801a_o3_30ppm_1min",
  "date": "2026-08-01",
  "rig": "lab",
  "operator": "jeff",
  "notes": "Baseline replication at 30 ppm O3, symmetric 1-minute lamp cycling.",

  "duration_min": 240,

  "conditions": {
    "methane_sensor": "licor",
    "methane_ppm": 2.0,
    "flow_lpm": 1.5,
    "flow_control": "manual"
  },

  "lamp": {
    "pin": 5,
    "on_ms": 60000,
    "off_ms": 60000,
    "initial": "off"
  },

  "ozone": {
    "setpoint": 30.0,
    "tickle_low_threshold": 29.0,
    "pin": 6,
    "gpio_ms": 500,
    "tickle_delay_ms": 5000,
    "max_delta": 1.5,
    "forced_reset_count": "never",
    "vidpos": [50, 70, 110, 95]
  }
}
```

Notes on the schema:

- The `lamp` block mirrors `exprun.py`'s `[pin,on_ms,off_ms,on|off]` grammar
  1:1, so a human reading the manifest can predict the child's command line.
- `o3.py` defaults `--target` to the positional grounding value and refuses
  `target < tickle_low_threshold`. So one `setpoint` field legitimately drives
  both — that is the whole of decision 7.
- `flow_control: "manual"` is the forward hook for decision 8.
- Recovery knobs (`-sac -rcc -rtdms -rmp`) are deliberately omitted; `o3.py`'s
  defaults are good. An `extra_args` escape hatch avoids schema churn.
- **Unknown keys should be a hard error** with a "did you mean" list. Silently
  ignoring a typo'd `duraton_min` and running 240 default minutes instead of
  30 is worse than failing at startup.

This resolves to exactly two child command lines:

```
ozone: python3 <repo>/Lab/o3.py 30.0 --target 30.0 -tlt 29.0 --gpiopin 6 \
         --gpio-ms 500 -tdms 5000 -md 1.5 -frc never --vidpos 50,70,110,95 \
         --log-dir <exp>/o3logs
lamp:  python3 <repo>/Lab/exprun.py '[5,60000,60000,off]'      (cwd=<exp>)
```

---

## 5. The runner — `Lab/labrun.py`

### Spawn subprocesses; do NOT import

`o3.py` is 710 lines. Module level has only the docstring, imports, OCR
geometry constants, `parse_vidpos`, `default_vidpos`, `run_calibration`, and
`class HeuristicFilter`. **Everything else — argparse, all validation, GPIO
setup, log-file lifetime, camera init, `log()`, `enter_recovery()`,
`on_reground()`, `do_pulse()`, and the ~90-line control loop — lives inside
`main()` as closures.** There is no seam. Importing means a ~350-line refactor
of the one file that is the scientific instrument.

Three more reasons:

1. **`GPIO.cleanup()` collision.** `o3.py`'s `finally` calls bare
   `GPIO.cleanup()`, which resets every channel that process registered.
   In-process, o3's exit would tear down the lamp pin too.
2. **`o3.py` is a GUI program.** It calls `cv2.imshow` + `cv2.waitKey(1)` every
   frame, unconditionally, and `'q'` is its only clean exit. cv2's event loop
   wants the main thread.
3. **Failure isolation is the runner's whole job.** In-process, an OCR/camera
   crash kills the lamp cycle too.

Cost of subprocesses: three surgical edits (~20 lines) instead of a ~350-line
refactor, and both tools stay usable standalone for hand debugging.

Spawn `exprun.py` as a subprocess too, for one supervision mechanism and one
signal discipline. Use `sys.executable`, never a literal `"python3"` — the
working environment is a conda env named `test`.

### Three upstream edits to `o3.py`

1. **Add `--log-dir PATH`.** Mandatory and unavoidable under any architecture:
   `LOG_DIR = os.path.join(os.path.dirname(__file__), 'o3logs')`, so changing
   cwd does *not* move o3's logs out of the repo. ~4 lines.
2. **`GPIO.cleanup(args.gpiopin)`** instead of bare. 1 line.
3. **Wrap the loop in `except KeyboardInterrupt: pass`.** Cosmetic — the
   `finally` already runs on SIGINT so the pin already drops; this just keeps
   real tracebacks visible. 2 lines.

Optional: make `exprun.py` refuse pin 6 unless `--allow-ozone-pin`. Makes the
collision structurally impossible rather than merely discouraged.

### Output layout (all outside the repo)

```
20260801a_o3_30ppm_1min/
├── experiment.json        # operator-authored; runner opens read-only
├── run_manifest.json      # resolved manifest + exact child argv + t0 + git rev + host
├── runlog.tsv             # run-level supervisor log, one clock
├── explog/exp_*.log       # written by the exprun child (cwd = exp dir)
├── o3logs/o3_*.log        # written by the o3 child (--log-dir)
├── stdout_ozone.log
├── stdout_lamp.log
└── <LI-COR writes its own files here>
```

**`explog/` and `o3logs/` are not arbitrary names** — `annotate_tsv.py`
hardcodes exactly those two cwd-relative directories. Keeping them means the
analysis step is unchanged and `--timedelta 0` becomes correct. Do not put
`runlog.tsv` inside `explog/`; it would be picked up by `annotate_tsv.py`'s
glob and double-annotate every second.

### One clock

Capture `t0_unix`, `t0_iso`, `t0_mono` once before spawning anything. Compute
the deadline from **`time.monotonic()`**, not wall clock — immune to NTP steps,
which matters because the Pi may step its clock after boot.

**Be honest about the limit.** This unifies the clocks of the two GPIO programs
only, which does eliminate the hand-computed `--timedelta` between them. It
does **not** unify the LI-COR's clock or the Presentation TSV's clock — those
are other machines. What it does is record t0 to the millisecond so the
remaining offset is *computable from a written-down number*.

### Shutdown

**Send SIGINT, never SIGTERM first.** Neither child installs a SIGTERM handler;
their only teardown is a `finally:` block, which SIGINT reaches via
`KeyboardInterrupt` and default-disposition SIGTERM skips. `exprun.py`
explicitly drives every pin low in its handler. SIGTERM would leave pin 6 HIGH
with the ozone generator running unattended.

Escalate SIGINT → 10 s → SIGTERM → 5 s → SIGKILL. Then, in a `finally`,
unconditionally: `pinctrl set 5 dl; pinctrl set 6 dl` plus a readback, logged.
`pinctrl` specifically, because `gpio-pulse.sh`'s header comment establishes it
as the mechanism that works on this hardware and `gpioset` as the one that
doesn't.

### Ozone failure — three distinct cases

- **(a) Process dies.** Detect with `proc.poll()` on a 1 Hz tick.
- **(b) Alive but not controlling** — the silent one. `o3.py` logs
  `RECOVERY abandoned  pulses=N  best=X  target=Y` when it spends its pulse
  budget with no new high. Process fine, chemistry not. Tail the o3 log for it.
- **(c) Alive but wedged** — no new `READ` line for >30 s.

Default policy **abort**. **Do not auto-restart** — `o3.py` needs a grounding
value seeded from the live display; restarting it against the manifest setpoint
while the true level has fallen recreates precisely the stale-grounding
declining spiral that its `check_for_confirmed_reground` / RECOVER machinery
exists to escape. It would look like recovery while controlling to a fiction.

**The runner must never reimplement any of `o3.py`'s control logic and must
never pulse pin 6 itself.** It touches pin 6 exactly once, at teardown.

### Pin ownership

```python
PIN_ROLES = {5: "lamp", 6: "ozone"}
```

Validated at startup: pins differ, and each block's declared pin matches its
role. A manifest putting the lamp on 6 becomes representable but rejected,
instead of invisible the way `o3test.sh` vs `run_example.sh` is today.

### Repo-containment check

Compare `os.path.realpath(exp_dir)` against the repo root derived from
`__file__`; abort if the experiment dir is at or under it. **This, not
`.gitignore`, is the real enforcement of decision 4** — an ignore file only
helps after data has already landed in the tree.

### `--dry-run`

Validate everything, print both resolved child command lines and the planned
output layout, spawn nothing, touch no pins. For a two-person lab this is the
highest-value flag in the runner: it turns "did I write the manifest right?"
from a four-hour question into a one-second one.

---

## 6. Ordered commit sequence

| # | Commit | Risk |
|---|---|---|
| 1 | `.gitignore` hardening + optional `.githooks/pre-commit` — do first, it protects every later step | none |
| 2 | `git mv` moves + `Remoa`→`Remora`, **bundled with** the `install_bennu_pi.sh` / `lamp-controller.service` / `logbkup.sh` path fixes | **HIGH — ship deploy** |
| 3 | `Remora/quadmap.py` — single source of truth for the quad→GPIO map | low, high value |
| 4 | Delete dead ship code | low |
| 5 | Split the 645-line README across root / `Lab/` / `Remora/` | none |
| 6 | The three `o3.py` edits | medium — touches the instrument |
| 7 | `exprun.py` pin-6 guard + `run_example.sh` fix | low |
| 8 | `Lab/labrun.py` + `Lab/example_experiment.json` | medium |

Bundle 2 so that no pullable commit leaves the ship broken:
`install_bennu_pi.sh` looks for `run.py` and the service file at the repo root
(already broken by `5cc6cbe`), and `lamp-controller.service` hardcodes
`/home/pi/lamp-controller` and `User=pi` while the real deploy path is
`/home/bennu/software/bennu` under user `bennu`.

### Dead code in `Remora/` (step 4)

Delete, and move the *rationale* into `Remora/README.md` as "removed in `<sha>`,
and why":

- **`lamps.py`** — highest priority. It drives real hardware **at import time**
  (module-level `DigitalOutputDevice`, then `LampsAllOff`, `board_on(1)`,
  `sleep(8)` at the bottom) and it claims **GPIO 6**, the lab's ozone pin.
- **`remora_config.csv`** — the address map for `lamps.py`; dies with it.
- **`gpio-hold-{on,off,status}.sh`** — built on `gpioset`, documented as not
  working on this hardware; author states untested and believed broken.
- **`bigmove.py`** — zero references anywhere; competes for the camera.
- **`windandcurrent.sh`** — line-for-line superseded by `adc_sensors.py`.
- **`minitest.py`** — judgement call, easy to reverse; it's the simplest
  "is the current sensor responding to lamps" check that exists.

**Keep `multiais2json.py`.** It is not dead, it is *undocumented* — a hand-run
tool for the marinetraffic screenshot step the README says happens every ship
experiment.

### `test.py` — the one item that can corrupt a result

Do not just delete it. Its quad→GPIO map **contradicts `run.py`'s**:

- `run.py` / `minitest.py`: bowport=16, bowstar=23, sternport=24, sternstar=25
- `test.py`: bowport=24, bowstar=25, sternport=16, sternstar=23

Every committed log agrees with `test.py`'s version, and the README admits the
mapping was never verified against the physical wiring. A mislabelled quad is a
mislabelled experimental condition — **a wrong scientific conclusion that looks
completely clean.** Fix by adding `Remora/quadmap.py` as the single source of
truth (with a prominent UNVERIFIED caveat and how to check it), having both
`run.py` and `test.py` import it, and adding a `--pins` override to `test.py`
so the map can be *discovered* without editing code.

---

## 7. Still open

- Whether the manifest should name the LI-COR data file or leave discovery to
  convention. Deferred as an analysis-side concern.
- Whether to scrub the ~12 MB of purged data from git history. Needs a
  coordinated force-push and jeffshrager re-cloning; not urgent.
- **`SIGTERM` leaving pin 6 HIGH is inferred, not tested.** The whole shutdown
  design rests on it. Verify on the bench: start `o3.py`, `kill -TERM`,
  `pinctrl get 6`. This is the single most worthwhile 30-second check.
- **`o3.py` has no headless path** — `cv2.imshow` is unconditional, so bench
  runs need a display (VNC or a monitor). Un-runnable over plain ssh. A real
  `o3.py` change (`--no-preview`) if unattended running ever matters.
- The root `README.md` still says `labexps/` throughout — stale since `5cc6cbe`.

---

## 8. What was actually done to the code this session

Four commits, all merged into `main`:

- `a792be9` — Add TARGET column to `o3.py` output and log.
- `5f9b942` — Detect stuck grounding in `o3.py` and recover to the normal
  target. Fixes a real declining-spiral bug: when OCR failed for a long stretch
  the grounding went stale, correct low reads were then rejected as anomalies,
  and the loop stopped tickling while the level kept falling. Detection is a
  run of ≥25 rejections ending in ≥10 mutually-agreeing reads; recovery ignores
  the min tickle point and climbs to `--target` with wider pulse spacing and a
  no-progress pulse cap.
- `e03a2b7` — Correct two inaccurate claims in those docs.
- `564b29d` — Document `o3.py` with block comments and docstrings; also fixed
  unreachable docstring/dead code stranded after the `return` in
  `default_vidpos`.

Testing note: `o3.py` can't run off-Pi (`picamera2`, `RPi.GPIO`). It was
verified with a harness that stubs `cv2`/`pytesseract`/`picamera2`/`RPi.GPIO`
and drives the real `main()` loop with scripted OCR sequences — four scenarios
(spiral, no-rise, scattered, normal). That harness lives in a job tmp dir and
was not committed; it is worth rebuilding if the recovery logic is touched
again.
