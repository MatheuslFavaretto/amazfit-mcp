# amazfit-mcp

> An **Ops/SRE mindset** applied to training (codename *AmazFitOps*): monitor, measure and
> cross **training load** with **recovery**. A Python **MCP server** that turns Claude into
> a personal training analyst for strength and running.

**Open source (MIT).** If you own an Amazfit and want your AI to actually understand your
training, this is for you — [contributions are welcome](#contributing).

Claude is already the analysis layer. This project's job is to **expose the data as tools** —
no frontend, no hosting, no UI to maintain.

- **Training load** comes from a load-control spreadsheet (`.xlsx`): VTT (volume = reps × weight)
  and Load in A.U. (RPE × time, Foster's *session-RPE*), per set / session / week.
- **Recovery** comes from an **Amazfit GTR 4** via Apple Health. The spreadsheet also carries
  **subjective** recovery (sleep / stress / fatigue / soreness) per session.
- **Running** comes from the watch's workouts (distance, pace, HR, TRIMP).

## Status

**Phases 1–4 shipped** — 15 tools, 84 green tests. Phase 4 ("the best of GitHub's fitness
MCPs") brought running workouts with TRIMP, daily CTL/ATL/TSB, a readiness score, baseline
trends, Obsidian export and an experimental Zepp cloud extractor. The only missing step is
enabling the sync on the iPhone (see
[Configure the Amazfit](#configure-the-amazfit-apple-health--phase-0)).

## Tools

**Training load (spreadsheet):**

| Tool | What it does |
|---|---|
| `list_weeks()` | Lists weeks with dates, sessions done/planned, VTT, A.U. and `has_data`. |
| `get_week_summary(week)` | Week summary + per-day breakdown (VTT, A.U., readiness, trained?). |
| `get_session(week, day)` | Details one session: sets (reps/weight/speed/VTT), RPE, time, A.U., wellness. `day` takes a name ("sábado", "monday") or 1–7. |
| `get_exercise_history(exercise, weeks?)` | Progression of one exercise (max weight, volume) across weeks. Flexible name matching. |

**Recovery (Amazfit GTR 4 via Apple Health):**

| Tool | What it does |
|---|---|
| `get_recovery(date)` | Resting HR, **avg HR**, HRV, respiratory rate and sleep (hours + phases) for a day. |
| `get_recovery_range(start, end)` | Recovery time series between two dates. |
| `recovery_status()` | Diagnostics: how many days exist, range, latest data point and the folder read. |

**Cross analysis (Phase 3):**

| Tool | What it does |
|---|---|
| `get_training_load(window?)` | Load per week + **ACWR** (acute/chronic), overtraining indicator. |
| `compare_load_recovery(start, end)` | Joins training load and recovery **by date** — the central crossing. |

**Running, form & Obsidian (Phase 4 — inspired by GitHub's best fitness MCPs):**

| Tool | What it does |
|---|---|
| `get_workouts(start, end, kind?)` | Watch runs/activities: duration, distance, pace, HR and **TRIMP** (internal load). |
| `get_fitness_fatigue(ctl?, atl?)` | Daily **CTL/ATL/TSB** (fitness/fatigue/form, Garmin-style) — spreadsheet + workout TRIMP. |
| `get_trends(metric?, baseline?)` | HRV / resting HR / sleep trend against a 28-day baseline, with z-score. |
| `get_readiness(date?)` | **Transparent** 0–100 readiness (breakdown: HRV, resting HR, sleep, TSB, subjective). |
| `daily_note(date)` | Daily Markdown note (YAML frontmatter) — training + running + recovery + form. |
| `export_obsidian(start, end)` | Writes the daily notes into the vault (`AMAZFIT_MCP_OBSIDIAN_DIR`), idempotent, Dataview-ready. |

There is also an **experimental Zepp cloud extractor** (outside the MCP, SRE-style):
`PYTHONPATH=src .venv/bin/python -m amazfit_mcp.zepp_cloud --days 14` — authenticates
against the Zepp account (prefer `ZEPP_APP_TOKEN`+`ZEPP_USER_ID`; password login gets
rate-limited) and writes JSON **in the Health Auto Export format** straight into the
store, with zero reader changes. Unofficial endpoints: may break without notice — the
Apple Health route remains the primary one.

## Setup

Requires Python ≥ 3.10 (macOS's `python3` is 3.9 — use Homebrew's).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .          # installs the dependencies (mcp, openpyxl)

# point to your spreadsheet (default: data/planilha.xlsx, gitignored)
export AMAZFIT_MCP_XLSX="$PWD/data/planilha.xlsx"

# start the server (stdio)
PYTHONPATH=src .venv/bin/python -m amazfit_mcp
```

> The package lives in `src/`. We run via `PYTHONPATH=src python -m amazfit_mcp` instead of
> the console script because setuptools' editable `.pth` is not reliably honored when the
> project sits under `~/Documents` (TCC) on macOS — `PYTHONPATH` is explicit and bulletproof.

## Register in Claude Code

```bash
claude mcp add amazfit-mcp \
  --env PYTHONPATH="$PWD/src" \
  --env AMAZFIT_MCP_XLSX="$PWD/data/planilha.xlsx" \
  --env AMAZFIT_MCP_RECOVERY_DIR="$PWD/data/recovery" \
  --env AMAZFIT_MCP_OBSIDIAN_DIR="$HOME/Obsidian/Training/Daily" \
  --env AMAZFIT_MCP_HR_MAX=190 --env AMAZFIT_MCP_HR_REST=60 \
  -- "$PWD/.venv/bin/python" -m amazfit_mcp
```

`AMAZFIT_MCP_HR_MAX`/`AMAZFIT_MCP_HR_REST` calibrate TRIMP — use your real max and
resting HR. `AMAZFIT_MCP_OBSIDIAN_DIR` is optional (default `data/obsidian`).

Then, in Claude: *"how was my Saturday of week 1?"*, *"am I progressing on the squat?"*,
*"how is my form?"* (CTL/ATL/TSB), *"am I ready to train hard today?"* (readiness),
*"export this week's notes to Obsidian"*.

## Development

```bash
# generate the synthetic fixture from the template
.venv/bin/python tests/make_fixture.py

# tests
.venv/bin/python -m pytest

# inspect the tools interactively (MCP Inspector, requires Node):
AMAZFIT_MCP_XLSX="$PWD/tests/fixtures/sample.xlsx" PYTHONPATH=src \
  npx @modelcontextprotocol/inspector .venv/bin/python -m amazfit_mcp
```

### How the code is organized

- `cellmap.py` — the **only** place with cell positions. The spreadsheet uses fixed positions
  and breaks easily if the structure changes; isolating it here is the defense.
- `spreadsheet.py` — reads only the *raw inputs* and **recomputes** VTT and A.U. (Excel's
  cached formula values are unreliable in a freshly edited file).
- `recovery.py` — reads the Apple Health JSON store (Health Auto Export) and normalizes per day.
- `workouts.py` — Phase 4: watch workouts (running etc.) from the same store + Banister TRIMP.
- `analysis.py` — Phase 3: ACWR and the load × recovery join by date.
- `metrics.py` — Phase 4: CTL/ATL/TSB, baseline trends and the readiness score (pure functions).
- `obsidian.py` — Phase 4: deterministic daily Markdown notes (YAML frontmatter for Dataview).
- `zepp_cloud.py` — Phase 4: experimental Zepp cloud extractor (CLI, outside the server; writes
  in the Health Auto Export format to reuse every reader).
- `server.py` — the 15 FastMCP tools. `models.py` — return dataclasses.

Personal data (`data/*.xlsx`, `data/recovery/`) stays out of git; only the synthetic fixture
is versioned.

## Configure the Amazfit (Apple Health) — Phase 0

Flow: `GTR 4 → Zepp app → Apple Health → Health Auto Export app → JSON on iCloud → the Mac reads`.
There is no official API; this is the robust path on iPhone (no Zepp password, no reverse
engineering). Extraction stays **outside the MCP** — the app writes the JSON, the tools only
read (decoupled, SRE-style).

1. **Zepp → Apple Health:** in the Zepp app (iPhone), Profile → Apple Health, enable **HR,
   resting HR, Sleep and HRV**. (HRV started syncing in 2025; if the toggle is missing, update
   the app.)
2. **Health Auto Export:** install the app, create a **daily** automation, **JSON** format,
   metrics `resting_heart_rate`, `heart_rate_variability`, `respiratory_rate`, `sleep_analysis`
   **and Workouts** (so runs feed `get_workouts`/TRIMP), destination a folder on **iCloud
   Drive** (e.g. `HealthAutoExport/`).
3. **Point the MCP at the folder** — re-register with `AMAZFIT_MCP_RECOVERY_DIR` on the iCloud
   folder:
   ```bash
   claude mcp remove amazfit-mcp -s local
   claude mcp add amazfit-mcp \
     --env PYTHONPATH="$PWD/src" \
     --env AMAZFIT_MCP_XLSX="$PWD/data/planilha.xlsx" \
     --env AMAZFIT_MCP_RECOVERY_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/HealthAutoExport" \
     -- "$PWD/.venv/bin/python" -m amazfit_mcp
   ```
4. **Validate:** in Claude, ask for `recovery_status` — it should show yesterday's data. That
   is Phase 0's done criterion.

> Sleep assumed in hours (Health Auto Export's default — validate with the first real export).
> Stress/PAI are Zepp-proprietary and may not reach Apple Health; resting HR + sleep + HRV
> already cover the essentials of recovery (and the spreadsheet has subjective stress).

## Roadmap

- **Phase 0 (your part) — enable Apple Health** (steps above). The only step missing for real
  watch data; the reading code is ready and tested.
- **Phase 3 — cross analysis — shipped** (`get_training_load` with ACWR + `compare_load_recovery`).
- **Phase 4 — running, form & Obsidian — shipped** (workouts + TRIMP, CTL/ATL/TSB, readiness,
  trends, Obsidian export, Zepp cloud extractor). On top of the tools, Claude interprets: ask
  *"compare this week's load with my recovery"* or *"is my ACWR in a risk zone?"*. The
  subjective version (A.U./VTT × readiness) already works without the watch.

## Contributing

This project is **open source under the [MIT license](LICENSE)** — use it, fork it, break it,
improve it. Contributions of any size are welcome:

- 🐛 **Found a bug?** [Open an issue](../../issues) with the JSON/spreadsheet snippet that
  triggered it (strip your personal data).
- 💡 **Ideas that would help most right now:** other watch/source extractors that write the
  Health Auto Export format into the store (Garmin, Fitbit, Oura — zero reader changes needed),
  stress/PAI support in `zepp_cloud.py`, adapters for other spreadsheet templates, more sports
  in `workouts.py`.
- 🔧 **Sending a PR:** keep the test suite green (`.venv/bin/python -m pytest`), match the
  code style (pure functions, defensive parsing, English docstrings), and add a test for
  what you change. Architecture notes live in [CONTEXT.md](CONTEXT.md).
- ⭐ If this helped you, a star helps others find it.

Everything here was built pairing with Claude Code — issues asking "how was X built?" are
welcome too.
