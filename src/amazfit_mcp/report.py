"""Self-contained HTML health report (cardio + form).

Renders a single-file report from data the server assembles: form time series
(CTL/ATL/TSB), latest recovery, readiness and recent workouts. Deterministic like
``obsidian.py`` — same input, same HTML — and decoupled from the producing modules:
everything arrives as plain dicts/objects.

The chart is a static inline SVG (no JS, no external assets), so the file can be
opened anywhere, attached or published as-is. Light/dark via prefers-color-scheme.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import config
from .obsidian import _fmt, _num, _pace, _wget

# chart geometry (viewBox units)
_W, _H = 680, 250
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 44, 64, 16, 28

# series key -> (label, CSS color token)
_SERIES = (
    ("ctl", "CTL · fitness", "var(--accent)"),
    ("atl", "ATL · fatigue", "var(--warn)"),
    ("tsb", "TSB · form", "var(--good)"),
)

_CSS = """
:root{--surface:#FBF7F4;--card:#FFF;--ink:#26201D;--ink-2:#6B5F58;--muted:#9A8C83;
--line:#E9DFD8;--accent:#C33D2E;--good:#2E7D4F;--warn:#B07A18;--grid:#EFE6DF}
@media (prefers-color-scheme:dark){:root{--surface:#191412;--card:#221C19;--ink:#F2ECE8;
--ink-2:#B8AAA1;--muted:#8A7C73;--line:#372E29;--accent:#DC5B46;--good:#37955F;
--warn:#B58023;--grid:#2C2420}}
body{font-family:"Avenir Next",Avenir,Seravek,"Segoe UI",system-ui,sans-serif;
background:var(--surface);color:var(--ink);margin:0;padding:2.5rem 1.25rem 3rem;line-height:1.55}
.wrap{max-width:920px;margin:0 auto;display:flex;flex-direction:column;gap:1.5rem}
.mono{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
header{display:flex;align-items:center;gap:1rem;flex-wrap:wrap}
.name{font-size:1.35rem;font-weight:600;display:flex;align-items:baseline;gap:.45rem}
.name .tag{font-family:ui-monospace,Menlo,monospace;font-size:.7rem;font-weight:600;
color:var(--accent);background:var(--grid);border-radius:99px;
padding:.15rem .55rem;letter-spacing:.06em}
.sub{font-size:.82rem;color:var(--ink-2)}
h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);
font-weight:600;margin:0 0 .75rem}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:.75rem}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:.95rem 1.05rem;display:flex;flex-direction:column;gap:.2rem}
.tile .label{font-size:.72rem;text-transform:uppercase;
letter-spacing:.09em;color:var(--muted);font-weight:600}
.tile .value{font-size:1.6rem;font-weight:600;line-height:1.15}
.tile .value small{font-size:.85rem;font-weight:500;color:var(--ink-2)}
.tile .foot{font-size:.78rem;color:var(--ink-2)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.25rem 1.3rem}
.card .note{font-size:.8rem;color:var(--muted);margin:.6rem 0 0}
.chart{overflow-x:auto}.chart svg{display:block;width:100%;height:auto;min-width:560px}
.legend{display:flex;gap:1.1rem;flex-wrap:wrap;font-size:.78rem;color:var(--ink-2);margin-top:.5rem}
.legend span{display:inline-flex;align-items:center;gap:.4rem}
.legend i{width:1rem;height:2px;border-radius:2px;display:inline-block}
.tscroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th{font-size:.7rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
font-weight:600;text-align:left;padding:.45rem .7rem .45rem 0;
border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:.5rem .7rem .5rem 0;border-bottom:1px solid var(--grid);white-space:nowrap}
tr:last-child td{border-bottom:none}
td.num{font-family:"SF Mono",ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
footer{font-size:.78rem;color:var(--muted);border-top:1px solid var(--line);
padding-top:1rem;line-height:1.6}
"""

_LOGO = """<svg width="46" height="46" viewBox="0 0 52 52" role="img" aria-label="amazfit-mcp">
<defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#D9503C"/><stop offset="1" stop-color="#A72E1F"/>
</linearGradient></defs>
<rect x="1" y="1" width="50" height="50" rx="13" fill="url(#lg)"/>
<polyline points="7,30 16,30 20,22 25,38 30,13 34,30 45,30" fill="none" stroke="#FFF6F2"
stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="45" cy="30" r="2.4" fill="#FFF6F2"/></svg>"""


def _scale(values: list[float]) -> tuple[float, float]:
    """(lo, hi) of the y domain with padding; always includes 0 so TSB reads vs zero."""
    lo, hi = min(values + [0.0]), max(values + [0.0])
    pad = max((hi - lo) * 0.08, 1.0)
    return lo - pad, hi + pad


def form_chart_svg(series: list[dict]) -> str:
    """CTL/ATL/TSB time series as a static SVG. ``series`` rows need date/ctl/atl/tsb.

    Returns "" with fewer than 2 points (a line needs a span). Points with a
    missing value break the polyline into segments rather than interpolating.
    """
    rows = [r for r in series if r.get("date")]
    if len(rows) < 2:
        return ""
    values = [
        v for r in rows for k, _, _ in _SERIES
        if (v := _num(r.get(k))) is not None
    ]
    if not values:
        return ""
    lo, hi = _scale(values)
    plot_w, plot_h = _W - _PAD_L - _PAD_R, _H - _PAD_T - _PAD_B
    step = plot_w / (len(rows) - 1)

    def x(i: int) -> float:
        return round(_PAD_L + i * step, 1)

    def y(v: float) -> float:
        return round(_PAD_T + (hi - v) / (hi - lo) * plot_h, 1)

    y0 = y(0.0)
    parts = [
        f'<svg viewBox="0 0 {_W} {_H}" aria-label="Fitness, fatigue and form over time">',
        f'<line x1="{_PAD_L}" y1="{y0}" x2="{_W - _PAD_R}" y2="{y0}" '
        'stroke="var(--line)" stroke-width="1"/>',
        f'<text x="{_PAD_L - 6}" y="{y0 + 4}" text-anchor="end" font-size="10.5" '
        'fill="var(--muted)">0</text>',
    ]
    for key, label, color in _SERIES:
        segments: list[list[str]] = [[]]
        last = None
        for i, r in enumerate(rows):
            v = _num(r.get(key))
            if v is None:
                if segments[-1]:
                    segments.append([])
                continue
            segments[-1].append(f"{x(i)},{y(v)}")
            last = v
        for seg in segments:
            if len(seg) > 1:
                parts.append(
                    f'<polyline points="{" ".join(seg)}" fill="none" stroke="{color}" '
                    'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
                )
        if last is not None:
            parts.append(
                f'<text x="{_W - _PAD_R + 6}" y="{y(last) + 4}" font-size="11" '
                f'font-weight="600" fill="{color}">{label.split(" ")[0]} {_fmt(last)}</text>'
            )
    parts.append(
        f'<text x="{_PAD_L}" y="{_H - 8}" font-size="10.5" '
        f'fill="var(--muted)">{rows[0]["date"]}</text>'
        f'<text x="{_W - _PAD_R}" y="{_H - 8}" text-anchor="end" font-size="10.5" '
        f'fill="var(--muted)">{rows[-1]["date"]}</text></svg>'
    )
    return "".join(parts)


def _tile(label: str, value: str, foot: str = "") -> str:
    foot_html = f'<span class="foot">{foot}</span>' if foot else ""
    return (
        f'<div class="tile"><span class="label">{label}</span>'
        f'<span class="value mono">{value}</span>{foot_html}</div>'
    )


def _tiles(latest_recovery, readiness: dict, form_today: dict | None) -> str:
    tiles = []
    if latest_recovery is not None and latest_recovery.resting_hr is not None:
        tiles.append(_tile(
            f"Resting HR · {latest_recovery.date}",
            f"{_fmt(latest_recovery.resting_hr)} <small>bpm</small>",
        ))
    if latest_recovery is not None and latest_recovery.hrv_sdnn is not None:
        tiles.append(_tile(
            f"HRV SDNN · {latest_recovery.date}",
            f"{_fmt(latest_recovery.hrv_sdnn)} <small>ms</small>",
        ))
    score = _num((readiness or {}).get("score"))
    if score is not None:
        tiles.append(_tile(
            "Readiness", f"{_fmt(score)}<small>/100</small>",
            foot=f'zone: {readiness.get("zone", "?")}',
        ))
    if form_today:
        vals = " · ".join(
            f"{k.upper()} {_fmt(v)}"
            for k in ("ctl", "atl", "tsb")
            if (v := _num(form_today.get(k))) is not None
        )
        if vals:
            tiles.append(_tile(f'Form · {form_today.get("date", "")}', vals))
    return f'<div class="tiles">{"".join(tiles)}</div>' if tiles else ""


def _workouts_table(workouts) -> str:
    rows = []
    for w in workouts:
        pace = _num(_wget(w, "pace_min_km"))
        cells = (
            _wget(w, "date") or "",
            _wget(w, "name") or _wget(w, "kind") or "?",
            f"{_fmt(d)} min" if (d := _num(_wget(w, "duration_min"))) is not None else "—",
            f"{_fmt(km)} km" if (km := _num(_wget(w, "distance_km"))) is not None else "—",
            f"{_pace(pace)} /km" if pace is not None else "—",
            _fmt(hr) if (hr := _num(_wget(w, "avg_hr"))) is not None else "—",
            _fmt(t) if (t := _num(_wget(w, "trimp"))) is not None else "—",
        )
        rows.append(
            f'<tr><td class="num">{cells[0]}</td><td>{cells[1]}</td>'
            + "".join(f'<td class="num">{c}</td>' for c in cells[2:])
            + "</tr>"
        )
    if not rows:
        return ""
    return (
        '<section class="card"><h2>Recent workouts</h2><div class="tscroll"><table>'
        "<thead><tr><th>Date</th><th>Workout</th><th>Duration</th><th>Distance</th>"
        "<th>Pace</th><th>Avg HR</th><th>TRIMP</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div></section>'
    )


def render_health_report(
    form_series: list[dict],
    latest_recovery=None,
    readiness: dict | None = None,
    workouts=(),
    generated: str | None = None,
) -> str:
    """Assemble the full HTML report. Deterministic: same input, same HTML.

    ``form_series`` = fitness_fatigue rows (date/ctl/atl/tsb) for the chart window;
    ``latest_recovery`` a RecoveryDay (or None); ``workouts`` recent Workout objects
    or dicts; ``generated`` the ISO date stamped in the header (defaults to the last
    form_series date so tests stay deterministic).
    """
    workouts = list(workouts or ())
    generated = generated or (form_series[-1]["date"] if form_series else "")
    form_today = form_series[-1] if form_series else None
    chart = form_chart_svg(form_series)
    chart_html = ""
    if chart:
        legend = "".join(
            f'<span><i style="background:{color}"></i>{label}</span>'
            for _, label, color in _SERIES
        )
        chart_html = (
            '<section class="card">'
            f"<h2>Fitness / fatigue / form · last {len(form_series)} days</h2>"
            f'<div class="chart">{chart}</div><div class="legend">{legend}</div>'
            '<p class="note">CTL = 42-day fitness · ATL = 7-day acute fatigue · '
            "TSB = form (negative: accumulated fatigue, positive: fresh).</p></section>"
        )
    body = (
        f'<div class="wrap"><header>{_LOGO}'
        '<div><span class="name">amazfit <span class="tag">MCP</span></span>'
        f'<div class="sub">Health report · {generated}</div></div></header>'
        + _tiles(latest_recovery, readiness or {}, form_today)
        + chart_html
        + _workouts_table(workouts)
        + "<footer>Wearable-data analysis generated by amazfit-mcp — not a medical "
        "evaluation.</footer></div>"
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Health report · amazfit-mcp</title><style>{_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def export_report(html: str, directory=None, date: str | None = None) -> str:
    """Write the report as ``report-<date>.html`` into ``directory``
    (default ``config.report_dir()``). Returns the written path."""
    directory = Path(directory) if directory is not None else config.report_dir()
    directory.mkdir(parents=True, exist_ok=True)
    day = date or dt.date.today().isoformat()
    path = directory / f"report-{day}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)
