# amazfit-mcp

MCP server that turns Claude into your personal training analyst — crossing your
**training spreadsheet** (strength) and **Amazfit watch** (running + recovery via
Apple Health). No frontend, no hosting: just data exposed as tools; Claude does
the analysis.

**15 tools:** weeks, sessions and exercise progression from the spreadsheet · runs
with pace/HR/TRIMP · resting HR, HRV and sleep · ACWR and daily CTL/ATL/TSB (form)
· a transparent 0–100 readiness score · daily notes exported to Obsidian.

## Setup

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e .

claude mcp add amazfit-mcp \
  --env PYTHONPATH="$PWD/src" \
  --env AMAZFIT_MCP_XLSX="$PWD/data/planilha.xlsx" \
  --env AMAZFIT_MCP_RECOVERY_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/HealthAutoExport" \
  -- "$PWD/.venv/bin/python" -m amazfit_mcp
```

Optional envs: `AMAZFIT_MCP_OBSIDIAN_DIR` (vault folder for the daily notes),
`AMAZFIT_MCP_HR_MAX` / `AMAZFIT_MCP_HR_REST` (your real HRs, to calibrate TRIMP).

**Watch data (one-time, on the iPhone):** Zepp app → Profile → Apple Health → enable
HR, resting HR, Sleep, HRV. Then install **Health Auto Export**, create a daily JSON
automation (those metrics + Workouts) into an iCloud folder — the MCP reads it from
there. Validate by asking Claude for `recovery_status`.

## Use

Just ask Claude:

> *"how was my Saturday of week 1?" · "am I progressing on the squat?" ·
> "how is my form?" · "am I ready to train hard today?" ·
> "export this week's notes to Obsidian"*

## Development

```bash
.venv/bin/python -m pytest        # 84 tests
```

Architecture, spreadsheet layout and design decisions: [CONTEXT.md](CONTEXT.md).
There is also an experimental Zepp cloud extractor: `python -m amazfit_mcp.zepp_cloud --help`.

## Contributing

Open source, [MIT](LICENSE). Issues and PRs welcome — keep tests green and add one
for what you change. Good first ideas: extractors for other watches that write the
Health Auto Export format into the store (zero reader changes), stress/PAI in the
Zepp extractor, more sports in `workouts.py`. If this helped you, a ⭐ helps others
find it.
