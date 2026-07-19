"""Tests for the Health Auto Export CSV dump extractor."""

import json

import pytest

from amazfit_mcp import hae_csv, recovery, workouts

DAILY_PT = """\
Data/Hora,Análise do Sono [Total] (hr),Análise do Sono [Adormecido] (hr),Análise do Sono [Profundo] (hr),Análise do Sono [REM] (hr),Análise do Sono [Núcleo] (hr),Análise do Sono [Na Cama] (hr),Frequência Cardíaca [Média] (bpm),Frequência Cardíaca em Repouso (bpm),Taxa Respiratória (contagem/min),Variabilidade da Frequência Cardíaca (ms)
2024-11-08 00:00:00,7.5,7.1,1.2,1.8,4.1,7.6,72,56,14.5,54
2024-11-09 00:00:00,,,,,,,80,,15.0,
2024-11-10 00:00:00,,,,,,,,,,
"""

WORKOUTS_PT = """\
Workout Type,Start,End,Duration,Energia Ativa (kJ),Freq. Cardíaca Máxima (bpm),Freq. Cardíaca Média (bpm),Distância (km)
Correr,2024-11-09 08:00,2024-11-09 08:33,00:33:00,1674,175,148,5.2
Caminhada,2024-11-09 09:00,2024-11-09 09:30,00:30:00,418,120,100,2.5
,,,,,,,
"""

DAILY_EN = """\
Date/Time,Sleep Analysis [Asleep] (hr),Heart Rate [Avg] (bpm),Resting Heart Rate (bpm)
2024-11-08 00:00:00,6.9,70,55
"""


@pytest.fixture
def dump(tmp_path):
    d = tmp_path / "HealthAutoExport_20241110"
    d.mkdir()
    (d / "HealthAutoExport-2024-11-08-2024-11-10.csv").write_text(DAILY_PT, encoding="utf-8")
    (d / "Workouts-20241108_000000-20241110_235959.csv").write_text(WORKOUTS_PT, encoding="utf-8")
    return d


def test_convert_dump_readable_by_the_official_readers(dump, tmp_path):
    """End-to-end contract: extractor output -> recovery.py + workouts.py."""
    store = tmp_path / "store"
    path = hae_csv.convert_dump(dump, out_dir=store)
    assert path.name == "csv-HealthAutoExport_20241110.json"

    recs = recovery.load_recovery(store)
    day = recs["2024-11-08"]
    assert day.resting_hr == 56 and day.hr_avg == 72
    assert day.hrv_sdnn == 54 and day.respiratory_rate == 14.5
    assert day.sleep["asleep_h"] == 7.1 and day.sleep["deep_h"] == 1.2
    assert recs["2024-11-09"].hr_avg == 80  # sparse row still lands
    assert "2024-11-10" not in recs  # all-empty row skipped

    wks = workouts.load_workouts(store)
    assert [w.kind for w in wks] == ["run", "walk"]
    run = wks[0]
    assert run.date == "2024-11-09" and run.duration_min == 33
    assert run.distance_km == 5.2 and run.avg_hr == 148 and run.max_hr == 175
    assert run.kcal == pytest.approx(400.1)  # 1674 kJ -> kcal
    assert run.trimp is not None


def test_localized_headers_english(tmp_path):
    d = tmp_path / "dump-en"
    d.mkdir()
    (d / "HealthAutoExport-2024-11-08-2024-11-08.csv").write_text(DAILY_EN, encoding="utf-8")
    path = hae_csv.convert_dump(d, out_dir=tmp_path / "store")
    doc = json.loads(path.read_text(encoding="utf-8"))
    names = {m["name"] for m in doc["data"]["metrics"]}
    assert names == {"resting_heart_rate", "heart_rate", "sleep_analysis"}
    assert doc["data"]["workouts"] == []  # no Workouts CSV is fine


def test_empty_dump_raises(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(FileNotFoundError):
        hae_csv.convert_dump(d)


def test_cli_prints_path_and_fails_cleanly(dump, tmp_path, capsys):
    assert hae_csv.main([str(dump), "--out", str(tmp_path / "store")]) == 0
    assert "csv-HealthAutoExport_20241110.json" in capsys.readouterr().out
    assert hae_csv.main([str(tmp_path / "missing"), "--out", str(tmp_path)]) == 1
