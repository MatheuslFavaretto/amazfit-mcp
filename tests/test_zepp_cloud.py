"""Testes offline do extractor experimental da nuvem Zepp (zepp_cloud)."""

import base64
import datetime as dt
import json
import urllib.error

import pytest

from amazfit_mcp import recovery
from amazfit_mcp import zepp_cloud as zc

# noite de 2024-11-02 23:30 UTC até 2024-11-03 07:00 UTC (7h30 na cama)
ST = 1730590200
ED = 1730617200


def _summary_com_rhr() -> dict:
    # dp=72min deep, lt=372min light -> asleep 7.4h, deep 1.2h, core 6.2h
    return {"v": 6,
            "slp": {"st": ST, "ed": ED, "dp": 72, "lt": 372, "rhr": 58},
            "stp": {"ttl": 8042, "dis": 5600}}


def _summary_sem_rhr() -> dict:
    return {"v": 6, "slp": {"st": ST + 86400, "ed": ED + 86400, "dp": 60, "lt": 360},
            "stp": {"ttl": 4200}}


def _band_items() -> list[dict]:
    return [
        # summary base64-encodado (variante comum da API)
        {"date_time": "2024-11-03",
         "summary": base64.b64encode(json.dumps(_summary_com_rhr()).encode()).decode()},
        # summary como string JSON direta
        {"date_time": "2024-11-04", "summary": json.dumps(_summary_sem_rhr())},
        # summary lixo -> ignorado com aviso, sem quebrar
        {"date_time": "2024-11-05", "summary": "@@@ nada a ver @@@"},
    ]


def _band_fetcher(items):
    """Fetcher fake da API de dados; grava as chamadas para inspeção."""
    calls = []

    def fetch(method, url, headers=None, data=None):
        calls.append({"method": method, "url": url, "headers": headers or {}, "data": data})
        assert "band_data.json" in url
        return {"code": 1, "message": "success", "data": items}

    fetch.calls = calls
    return fetch


# ---------------------------------------------------------------------------
# decode do summary
# ---------------------------------------------------------------------------

def test_decode_summary_variantes():
    doc = {"slp": {"dp": 10}}
    s = json.dumps(doc)
    b64 = base64.b64encode(s.encode()).decode()
    assert zc._decode_summary(doc) == doc
    assert zc._decode_summary(s) == doc
    assert zc._decode_summary(b64) == doc
    assert zc._decode_summary(None) == {}
    assert zc._decode_summary("") == {}
    assert zc._decode_summary("lixo total") == {}
    assert zc._decode_summary(123) == {}
    assert zc._decode_summary("[1,2,3]") == {}


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def _login_fetcher():
    def fetch(method, url, headers=None, data=None):
        if "api-user.huami.com/registrations" in url:
            assert method == "POST"
            assert data["password"] == "s3cret" and data["grant_type"] == "password"
            return {"redirect": zc.REDIRECT_URI + "?access=ACC123&country_code=US"}
        if url == zc.LOGIN_URL:
            assert data["code"] == "ACC123" and data["grant_type"] == "access_token"
            return {"token_info": {"app_token": "APPT", "user_id": 4242,
                                   "login_token": "LT"}}
        raise AssertionError(f"URL inesperada: {url}")

    return fetch


def test_login_por_senha_fluxo_completo():
    token, uid = zc.login_with_password("a@b.com", "s3cret", fetcher=_login_fetcher())
    assert (token, uid) == ("APPT", "4242")


def test_login_429_vira_mensagem_clara():
    def fetch(method, url, headers=None, data=None):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

    with pytest.raises(zc.RateLimitError) as exc:
        zc.login_with_password("a@b.com", "x", fetcher=fetch)
    msg = str(exc.value)
    assert "429" in msg and "ZEPP_APP_TOKEN" in msg


def test_login_redirect_sem_access():
    def fetch(method, url, headers=None, data=None):
        return {"redirect": zc.REDIRECT_URI + "?error=0106"}

    with pytest.raises(zc.ZeppError, match="access"):
        zc.login_with_password("a@b.com", "errada", fetcher=fetch)


def test_resolve_auth_prefere_envs_diretas():
    def bomba(method, url, headers=None, data=None):
        raise AssertionError("não deveria chamar a rede")

    env = {"ZEPP_APP_TOKEN": "tok", "ZEPP_USER_ID": "99"}
    assert zc.resolve_auth(env=env, fetcher=bomba) == ("tok", "99")


def test_resolve_auth_cacheia_sem_persistir_senha(tmp_path):
    cache = tmp_path / "zepp_auth.json"
    env = {"ZEPP_EMAIL": "a@b.com", "ZEPP_PASS": "s3cret"}
    token, uid = zc.resolve_auth(env=env, fetcher=_login_fetcher(), cache_path=cache)
    assert (token, uid) == ("APPT", "4242")
    text = cache.read_text()
    assert "s3cret" not in text and "APPT" in text

    # segunda chamada usa o cache — nenhuma requisição
    def bomba(method, url, headers=None, data=None):
        raise AssertionError("cache deveria ter evitado a rede")

    assert zc.resolve_auth(env=env, fetcher=bomba, cache_path=cache) == ("APPT", "4242")


def test_resolve_auth_sem_credenciais(tmp_path):
    env = {"ZEPP_AUTH_CACHE": str(tmp_path / "auth.json")}
    with pytest.raises(zc.ZeppError, match="ZEPP_APP_TOKEN"):
        zc.resolve_auth(env=env, fetcher=None)


# ---------------------------------------------------------------------------
# datas
# ---------------------------------------------------------------------------

def test_range_calculado_de_days():
    hoje = dt.date(2024, 11, 15)
    assert zc.compute_range(14, None, None, today=hoje) == ("2024-11-01", "2024-11-15")


def test_range_explicito_vence():
    assert zc.compute_range(14, "2024-10-01", "2024-10-07") == ("2024-10-01", "2024-10-07")


def test_range_invalido():
    with pytest.raises(zc.ZeppError):
        zc.compute_range(14, "2024-12-01", "2024-11-01")
    with pytest.raises(zc.ZeppError):
        zc.compute_range(14, "01/11/2024", "2024-11-15")


# ---------------------------------------------------------------------------
# dados / export
# ---------------------------------------------------------------------------

def test_band_data_erro_de_api():
    def fetch(method, url, headers=None, data=None):
        return {"code": 0, "message": "invalid apptoken"}

    with pytest.raises(zc.ZeppError, match="invalid apptoken"):
        zc.fetch_band_data("tok", "99", "2024-11-01", "2024-11-14", fetcher=fetch)


def test_build_export_campos_faltando():
    doc, stats = zc.build_export([
        {"date_time": "2024-11-06", "summary": json.dumps({"stp": {"ttl": 100}})},
        {"date_time": "2024-11-07"},          # sem summary
        {"summary": json.dumps({"slp": {}})},  # sem data
        "nem é dict",
    ])
    names = {m["name"] for m in doc["data"]["metrics"]}
    assert names == {"step_count"}
    assert stats == {"sleep": 0, "rhr": 0, "steps": 1, "skipped": 3}


def test_main_gera_export_e_recovery_le(tmp_path, capsys):
    fetch = _band_fetcher(_band_items())
    env = {"ZEPP_APP_TOKEN": "tok123", "ZEPP_USER_ID": "9999"}
    rc = zc.main(["--from", "2024-11-01", "--to", "2024-11-14", "--out", str(tmp_path)],
                 fetcher=fetch, env=env)
    assert rc == 0

    # requisição correta: header apptoken + querystring
    call = fetch.calls[0]
    assert call["method"] == "GET"
    assert call["headers"].get("apptoken") == "tok123"
    assert "userid=9999" in call["url"]
    assert "from_date=2024-11-01" in call["url"] and "to_date=2024-11-14" in call["url"]
    assert "query_type=summary" in call["url"]

    out_file = tmp_path / "zepp_export_2024-11-01_2024-11-14.json"
    assert out_file.exists()
    doc = json.loads(out_file.read_text())
    names = [m["name"] for m in doc["data"]["metrics"]]
    assert "resting_heart_rate" in names and "sleep_analysis" in names

    saida = capsys.readouterr().out
    assert "3 item(s)" in saida and str(out_file) in saida and "warning" in saida

    # integração chave: recovery.load_recovery lê o arquivo gerado
    recs = recovery.load_recovery(tmp_path)
    assert set(recs) == {"2024-11-03", "2024-11-04"}
    r = recs["2024-11-03"]
    assert r.resting_hr == 58.0
    assert r.sleep["asleep_h"] == 7.4
    assert r.sleep["deep_h"] == 1.2 and r.sleep["core_h"] == 6.2
    assert r.sleep["rem_h"] is None          # Zepp não separa REM
    assert r.sleep["in_bed_h"] == 7.5
    assert str(r.sleep["start"]).startswith("2024-11-02 23:30:00")
    assert str(r.sleep["end"]).startswith("2024-11-03 07:00:00")

    r4 = recs["2024-11-04"]
    assert r4.resting_hr is None             # rhr ausente -> métrica omitida no dia
    assert r4.sleep["asleep_h"] == 7.0


def test_main_days_default_calcula_janela(tmp_path):
    fetch = _band_fetcher([])
    env = {"ZEPP_APP_TOKEN": "t", "ZEPP_USER_ID": "1"}
    rc = zc.main(["--days", "7", "--out", str(tmp_path)], fetcher=fetch, env=env)
    assert rc == 0
    hoje = dt.date.today()
    inicio = hoje - dt.timedelta(days=7)
    assert (tmp_path / f"zepp_export_{inicio.isoformat()}_{hoje.isoformat()}.json").exists()
    assert f"from_date={inicio.isoformat()}" in fetch.calls[0]["url"]


def test_main_429_retorna_erro_amigavel(tmp_path, capsys):
    def fetch(method, url, headers=None, data=None):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

    env = {"ZEPP_EMAIL": "a@b.com", "ZEPP_PASS": "x",
           "ZEPP_AUTH_CACHE": str(tmp_path / "auth.json")}
    rc = zc.main(["--days", "7", "--out", str(tmp_path)], fetcher=fetch, env=env)
    assert rc == 1
    err = capsys.readouterr().err
    assert "429" in err and "ZEPP_APP_TOKEN" in err
