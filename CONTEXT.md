# amazfit-mcp — architecture notes

> Technical documentation: spreadsheet structure, recovery store, decisions and roadmap.
> Renamed from *AmazFitOps* to **amazfit-mcp** in Jul/2026 (discoverability; `garmin_mcp`
> naming pattern). English is the project's default language since then.

## What it is

An **MCP server** (FastMCP, Python) that turns Claude into a training analyst for strength
and running. An **Ops/SRE mindset** applied to training: monitor, measure, alert — crossing
**training load** (spreadsheet + watch workouts) with **recovery** (watch + subjective).
First MCP project; serves as tool + learning + portfolio piece.

**Guiding principle:** Claude is already the analysis layer (for free). The project only
**exposes the data as tools**. No frontend, no hosting, no UI.

## Stack

- Python ≥ 3.10 (macOS's `python3` is 3.9 — use Homebrew `python3.12`).
- FastMCP (official `mcp` SDK); `openpyxl` (read-only).
- No `uv` in the environment; `venv` + `pip install -e .`. Usage = **Claude Code CLI**
  (not Desktop): registered via `claude mcp add amazfit-mcp` / `.mcp.json`.
- Package `amazfit_mcp` under `src/`; runs via `PYTHONPATH=src python -m amazfit_mcp`
  (the editable `.pth` gets a macOS *hidden* flag under `~/Documents` and Python ≥3.12
  skips hidden .pth files — `PYTHONPATH` is immune).

## Current state

- **Phase 1 (spreadsheet MCP) — shipped.** 4 tools: `list_weeks`, `get_week_summary`,
  `get_session`, `get_exercise_history`.
- **Phase 2 (recovery) — shipped (read).** 3 tools: `get_recovery`, `get_recovery_range`,
  `recovery_status`, reading the Apple Health JSON store (`recovery.py`).
- **Phase 3 (cross analysis) — shipped.** 2 tools: `get_training_load` (ACWR) and
  `compare_load_recovery` (join by date), in `analysis.py`.
- **Phase 4 (Jul/2026, "the best of GitHub's fitness MCPs") — shipped.** Inspirations mapped
  by GitHub research: Taxuspt/garmin_mcp (CTL/ATL/TSB, trends, readiness),
  dimonier/amazfit-sync (day-centric Obsidian notes), huami-token + m4ary/zepp-health-cli
  (Zepp cloud extractor). New modules: `workouts.py` (watch workouts via Health Auto Export
  + Banister TRIMP, HR via `AMAZFIT_MCP_HR_MAX`/`HR_REST` envs), `metrics.py` (CTL/ATL/TSB
  with EWMA, 28d-baseline trends + z-score, transparent 0–100 readiness with renormalized
  weights), `obsidian.py` (deterministic daily notes, YAML frontmatter,
  `AMAZFIT_MCP_OBSIDIAN_DIR`), `zepp_cloud.py` (experimental CLI, stdlib-only, writes **in
  the Health Auto Export format** so `recovery.py` needs zero changes; preferred auth via
  `ZEPP_APP_TOKEN`+`ZEPP_USER_ID`, password login gets 429s).
- **15 tools, 84 green tests** against synthetic fixtures (spreadsheet + recovery + workouts,
  dates aligned in Nov/2024).
- **Phase 0 (enable the iPhone sync) — pending (manual iPhone configuration).** The only step
  missing for real data. Include **Workouts** in the Health Auto Export automation.

## The spreadsheet (REAL structure, verified)

Quarterly spreadsheet: sheets `SEM 1`..`SEM 12` (detected via regex `^SEM \d+$`, so it works
with 4 or 12). Source of truth: `data/planilha.xlsx` (env `AMAZFIT_MCP_XLSX`).

Each `SEM N` sheet has **7 vertical blocks of 18 rows** (one per day). Day ``d``'s block
(0 = MON … 6 = SUN) starts at `base = 1 + 18*d` → `[1, 19, 37, 55, 73, 91, 109]`.
The full map lives in `src/amazfit_mcp/cellmap.py`:

| Item | Cell (relative to `base`) |
|---|---|
| Day name / Date | `A(base+1)` / `E(base+1)` |
| Sleep / Stress / Fatigue / Soreness | `L / M / N / O (base+1)` |
| Exercises (up to 12) | `A(base+4)` … `A(base+15)` |
| Sets 1–5 (reps/weight/speed) | `B C D` · `G H I` · `L M N` · `Q R S` · `V W X` |
| Session RPE (PSE) | `AE(base+4)` |
| Time (min) | `AG(base+6)` |

**Derived values are recomputed in Python**, not read from the spreadsheet: VTT = reps×weight;
session VTT = Σ; A.U. load = RPE×time; readiness = mean(sleep,stress,fatigue,soreness).
Reason: `openpyxl(data_only=True)` only returns Excel's cached value, which comes back
`None`/`#DIV/0!` in a freshly edited file. The parser treats `None` and error strings as absent.

**"Logged session"** = some `weight > 0` on the day (distinguishes from a merely *planned*
day, whose reps are pre-filled in the template).

There are aggregation sheets (`C.I DIÁRIA`, ` C.I SEMANAL` — note the leading space!,
`C.E DIÁRIA E SEMANAL`) whose formulas were the source for deriving the map. We do **not**
use them as a data source (they have a bug — session 6 reads `S92` instead of `L92` — and
the A.U. sheet only covers MON–FRI). Everything is computed from the `SEM` blocks, covering
all 7 days.

Domain vocabulary kept as-is in field names / dict keys (part of the tool API): `carga_ua`
(load in A.U.), `vtt`, `pse` (session RPE), wellness keys `sono/estresse/fadiga/dor`.

## Decisions made

- Name: **amazfit-mcp** (born *AmazFitOps*; renamed Jul/2026). Custom MCP (not an app).
  FastMCP, no exotic framework. Read-only first.
- Source spreadsheet: 12-week quarterly version; weeks detected dynamically.
- Validation via versioned **synthetic fixture** (`tests/fixtures/sample.xlsx`); real data out
  of git.
- **Recovery on iPhone — DECIDED: via Apple Health.** Setup: **iPhone + GTR 4**, which rules
  out Health Connect and reading the app DB (both Android). Chosen path (Jun/2026):
  `GTR 4 → Zepp → Apple Health → Health Auto Export app (JSON on iCloud) → the Mac reads`.
  Robust, no Zepp password, no reverse engineering (Zepp started syncing HRV to Apple Health
  in 2025). Fallback implemented in Phase 4 as a **second source**: `zepp_cloud.py` (cloud
  API, more data but fragile / ToS gray area). Do NOT install third-party Zepp MCPs.
- **Phase 4 model choices:** TRIMP = Banister (`dur_min · HRr · 0.64 · e^{1.92·HRr}`);
  CTL/ATL = Coggan EWMA (42d/7d) with rest days as load 0; TSB = yesterday's CTL−ATL;
  readiness = weighted mean of HRV z (30), inverted RHR z (25), sleep vs baseline (20),
  TSB mapped [−30,+15] (15), subjective (10), weights renormalized on missing data — always
  returned WITH the per-component breakdown (transparency requirement: Claude explains the
  score, never a black box). Readiness zones: ready/ok/caution/rest; ACWR zones: no data /
  low load (detraining) / optimal / caution / high risk.

## Recovery — store and format (Phase 2, shipped)

`recovery.py` reads every `*.json` in `AMAZFIT_MCP_RECOVERY_DIR` (default `data/recovery`;
in production, the iCloud folder where Health Auto Export drops the exports) and normalizes
per day. Health Auto Export format: `{"data":{"metrics":[{"name","units","data":[...]}]}}` —
quantity points carry `qty`+`date`; `sleep_analysis` carries
`asleep/deep/rem/core/inBed/sleepStart/sleepEnd`. Mapping: `resting_heart_rate`→resting HR,
`heart_rate`→avg HR (`Avg` field), `heart_rate_variability`→HRV SDNN, `respiratory_rate`,
and sleep. Dates as `yyyy-MM-dd HH:mm:ss Z` (quantities) and `yyyy-MM-dd` (sleep).
`workouts.py` reads `{"data":{"workouts":[...]}}` from the same folder (defensive parsing,
multiple key candidates; mi→km; duration >1000 = seconds heuristic).

The store is **format-coupled, source-decoupled**: anything that writes Health Auto
Export-shaped JSON into the folder becomes a source (that is how `zepp_cloud.py` plugs in
with zero reader changes).

## Roadmap

- **Phase 0 (pending, manual configuration)** — enable Zepp → Apple Health (incl. HRV) and
  configure Health Auto Export to write JSON (metrics + **Workouts**) to iCloud; point
  `AMAZFIT_MCP_RECOVERY_DIR` there. Done criterion: `recovery_status` shows yesterday's data.
  Step-by-step in the README.
- **Possible next steps** — real-data validation of Phase 4 (TRIMP calibration with real
  HR max/rest; sleep-units check on the first real export); stress/PAI via `zepp_cloud.py`
  if the summary carries them; publish to PyPI as `amazfit-mcp`.

## Reference repos (researched Jun–Jul/2026)

Study the **extraction method** (the hard part), don't copy blindly.
- `argrento/huami-token` (Python, mature) — Huami/Zepp cloud auth token. **Auth baseline.**
- `m4ary/zepp-health-cli` — current Zepp mobile-API endpoints (HRV, body battery, training
  load); requires app-token capture via HTTPS proxy.
- `bentasker/zepp_to_influxdb`, `dimonier/amazfit-sync` — cloud-API data flows; the latter
  inspired the Obsidian day-notes.
- `Taxuspt/garmin_mcp` (801⭐), `Nicolasvegam/garmin-connect-mcp` — feature north star
  (CTL/ATL/TSB, trends, readiness).
- `davidepalleschi/zepp2hass` + `MrCodeEU/zepp2hass-watch` — Zepp OS watch-app → webhook
  architecture (validated alternative; no HRV in the public watch API).
- ~~`ndesgranges/zepp-health-ha`~~ (reads the Android DB) — **not applicable (iPhone)**.
