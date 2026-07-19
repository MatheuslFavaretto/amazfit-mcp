"""Tests for the HTML health report renderer/exporter."""

from amazfit_mcp import report as rp
from amazfit_mcp.models import RecoveryDay

FORM_SERIES = [
    {"date": "2024-11-01", "ctl": 40.0, "atl": 50.0, "tsb": -8.0},
    {"date": "2024-11-02", "ctl": 40.5, "atl": 48.0, "tsb": -10.0},
    {"date": "2024-11-03", "ctl": 41.0, "atl": 46.0, "tsb": -7.5},
]

WORKOUT = {
    "date": "2024-11-03", "name": "Corrida leve", "kind": "run",
    "duration_min": 33.8, "distance_km": 5.2, "pace_min_km": 6.5,
    "avg_hr": 148, "trimp": 85.0,
}

RECOVERY = RecoveryDay(
    date="2024-11-03", resting_hr=56.0, hr_avg=72.0, hrv_sdnn=54.0,
    respiratory_rate=14.5, sleep=None,
)

READINESS = {"score": 61, "zone": "ok"}


def render():
    return rp.render_health_report(
        FORM_SERIES, latest_recovery=RECOVERY, readiness=READINESS,
        workouts=[WORKOUT], generated="2024-11-03",
    )


def test_report_has_all_sections():
    html = render()
    assert "<title>Health report" in html
    assert "Health report · 2024-11-03" in html
    assert "Resting HR · 2024-11-03" in html and "56" in html
    assert "HRV SDNN" in html and "54" in html
    assert "Readiness" in html and "61" in html
    assert "zone: ok" in html
    assert "Fitness / fatigue / form · last 3 days" in html
    assert "Recent workouts" in html and "Corrida leve" in html
    assert "6:30 /km" in html  # pace formatted M:SS


def test_report_is_deterministic():
    assert render() == render()


def test_chart_has_three_series_and_end_labels():
    svg = rp.form_chart_svg(FORM_SERIES)
    assert svg.count("<polyline") == 3
    assert "CTL 41" in svg and "ATL 46" in svg and "TSB -7.5" in svg
    assert "2024-11-01" in svg and "2024-11-03" in svg


def test_chart_breaks_segments_on_missing_values():
    series = FORM_SERIES + [
        {"date": "2024-11-04", "ctl": None, "atl": None, "tsb": None},
        {"date": "2024-11-05", "ctl": 42.0, "atl": 44.0, "tsb": -5.0},
    ]
    svg = rp.form_chart_svg(series)
    # a single trailing point after the gap cannot form a segment, so still 3 lines
    assert svg.count("<polyline") == 3
    assert "2024-11-05" in svg  # but the x range covers the full window


def test_chart_empty_when_insufficient():
    assert rp.form_chart_svg([]) == ""
    assert rp.form_chart_svg(FORM_SERIES[:1]) == ""


def test_export_writes_file(tmp_path):
    path = rp.export_report("<html></html>", directory=tmp_path, date="2024-11-03")
    assert path.endswith("report-2024-11-03.html")
    assert (tmp_path / "report-2024-11-03.html").read_text() == "<html></html>"
