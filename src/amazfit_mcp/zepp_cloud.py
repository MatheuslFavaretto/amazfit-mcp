"""EXPERIMENTAL Zepp/Huami cloud extractor -> recovery store.

Downloads the daily summaries (sleep, steps and resting HR when available) of the
user's OWN Zepp account and writes JSON in the Health Auto Export format, so that
``recovery.load_recovery()`` reads it with zero changes. Extraction stays OUTSIDE
the MCP server (project principle: decoupled ingestion) — this module is just a
personal CLI.

Authentication, in order of preference:
  1. Envs ``ZEPP_APP_TOKEN`` + ``ZEPP_USER_ID`` — RECOMMENDED path. Extract the
     values from the official app (mitmproxy/logs); password login is aggressively
     rate-limited (HTTP 429) on Huami's side.
  2. Envs ``ZEPP_EMAIL`` + ``ZEPP_PASS`` — classic Huami flow:
     POST api-user.huami.com/registrations/{email}/tokens (grant_type password)
     -> redirect with ``access=`` -> POST account.huami.com/v2/client/login
     (exchanges the access code for apptoken + userid).
     The password is NEVER persisted; apptoken/userid are cached in
     ``data/zepp_auth.json`` (gitignored) to avoid repeated logins.

Usage:
    python -m amazfit_mcp.zepp_cloud --days 14 [--out DIR] [--from YYYY-MM-DD --to YYYY-MM-DD]

All HTTP access goes through an injectable ``fetcher`` function
(``fetch(method, url, headers=None, data=None) -> dict | bytes``), so the tests run
100% offline. Auth/endpoint logic reimplemented from the behavior documented in
huami-token, hacking-mifit-api, zepp_to_influxdb and amazfit-sync.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

TOKENS_URL = "https://api-user.huami.com/registrations/{email}/tokens"
LOGIN_URL = "https://account.huami.com/v2/client/login"
BAND_DATA_URL = "https://api-mifit.huami.com/v1/data/band_data.json"
REDIRECT_URI = "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html"
DEFAULT_AUTH_CACHE = config.PROJECT_ROOT / "data" / "zepp_auth.json"

RATE_LIMIT_MSG = (
    "HTTP 429 (Huami rate limit on password login): wait a few minutes and retry, "
    "or use ZEPP_APP_TOKEN + ZEPP_USER_ID extracted from the official app."
)


class ZeppError(Exception):
    """Zepp cloud auth/network/API error, with a CLI-friendly message."""


class RateLimitError(ZeppError):
    """HTTP 429 in the password-login flow."""


# ---------------------------------------------------------------------------
# HTTP (injectable default fetcher)
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Does not follow redirects — login returns the access token in the Location."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def default_fetcher(method: str, url: str, headers: dict | None = None,
                    data: dict | bytes | None = None) -> dict | bytes:
    """Stdlib fetcher: JSON becomes a dict, a redirect becomes ``{"redirect": location}``.

    A ``data`` dict is sent as form-urlencoded. 429 becomes ``RateLimitError``.
    """
    hdrs = {"User-Agent": "MiFit/6.3.5 (Android; amazfit_mcp-experimental)"}
    hdrs.update(headers or {})
    body = None
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif data is not None:
        body = data if isinstance(data, bytes) else str(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            return {"redirect": exc.headers.get("Location", "")}
        if exc.code == 429:
            raise RateLimitError(RATE_LIMIT_MSG) from exc
        raise
    try:
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else raw
    except (ValueError, UnicodeDecodeError):
        return raw


def _call(fetcher, method: str, url: str, headers: dict | None = None,
          data: dict | bytes | None = None) -> dict | bytes:
    """Calls the fetcher, converting HTTP errors into ZeppError/RateLimitError."""
    try:
        return fetcher(method, url, headers=headers, data=data)
    except ZeppError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimitError(RATE_LIMIT_MSG) from exc
        raise ZeppError(f"HTTP {exc.code} at {url.split('?')[0]}") from exc
    except urllib.error.URLError as exc:
        raise ZeppError(f"network failure: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def login_with_password(email: str, password: str, fetcher=None) -> tuple[str, str]:
    """Classic Huami flow: password -> access code (redirect) -> apptoken + userid.

    The password only travels in the first request — it is never written to disk.
    """
    fetcher = fetcher or default_fetcher
    url = TOKENS_URL.format(email=urllib.parse.quote(email, safe=""))
    resp = _call(fetcher, "POST", url, data={
        "state": "REDIRECTION",
        "client_id": "HuaMi",
        "redirect_uri": REDIRECT_URI,
        "token": "access",
        "grant_type": "password",
        "password": password,
    })
    location = resp.get("redirect") if isinstance(resp, dict) else None
    if not location:
        raise ZeppError("login did not redirect — unexpected Huami response")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
    access = (query.get("access") or [None])[0]
    if not access:
        error = (query.get("error") or ["unknown"])[0]
        raise ZeppError(f"login redirect without 'access' (error: {error})")

    resp2 = _call(fetcher, "POST", LOGIN_URL, data={
        "app_name": "com.xiaomi.hm.health",
        "app_version": "6.3.5",
        "code": access,
        "country_code": "US",
        "device_id": "02:00:00:00:00:00",
        "device_model": "android_phone",
        "grant_type": "access_token",
        "third_name": "huami",
        "allow_registration": "false",
        "source": "com.xiaomi.hm.health",
    })
    token_info = (resp2 or {}).get("token_info") if isinstance(resp2, dict) else None
    token_info = token_info or {}
    app_token, user_id = token_info.get("app_token"), token_info.get("user_id")
    if not (app_token and user_id):
        raise ZeppError("login did not return app_token/user_id — unexpected response")
    return str(app_token), str(user_id)


def _read_auth_cache(path: Path) -> tuple[str, str] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    token, uid = doc.get("app_token"), doc.get("user_id")
    return (str(token), str(uid)) if token and uid else None


def _write_auth_cache(path: Path, app_token: str, user_id: str) -> None:
    """Caches ONLY apptoken/userid (never the password)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "app_token": app_token,
                "user_id": user_id,
                "cached_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }, fh, indent=2)
        os.chmod(path, 0o600)
    except OSError:
        pass  # the cache is a convenience; failure does not block extraction


def resolve_auth(env=None, fetcher=None, cache_path: str | Path | None = None) -> tuple[str, str]:
    """Resolve (apptoken, userid): direct envs > cache > password login.

    Cache at ``ZEPP_AUTH_CACHE`` or ``data/zepp_auth.json`` (gitignored).
    """
    env = env if env is not None else os.environ
    token, uid = env.get("ZEPP_APP_TOKEN"), env.get("ZEPP_USER_ID")
    if token and uid:
        return token, uid

    cache = Path(cache_path or env.get("ZEPP_AUTH_CACHE") or DEFAULT_AUTH_CACHE)
    cached = _read_auth_cache(cache)
    if cached:
        return cached

    email, password = env.get("ZEPP_EMAIL"), env.get("ZEPP_PASS")
    if not (email and password):
        raise ZeppError(
            "missing credentials: set ZEPP_APP_TOKEN + ZEPP_USER_ID (recommended) "
            "or ZEPP_EMAIL + ZEPP_PASS"
        )
    token, uid = login_with_password(email, password, fetcher=fetcher)
    _write_auth_cache(cache, token, uid)
    return token, uid


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def fetch_band_data(app_token: str, user_id: str, from_date: str, to_date: str,
                    fetcher=None) -> list[dict]:
    """GET band_data.json (summary) — returns the raw list of daily items."""
    fetcher = fetcher or default_fetcher
    params = urllib.parse.urlencode({
        "query_type": "summary",
        "device_type": "android_phone",
        "userid": user_id,
        "from_date": from_date,
        "to_date": to_date,
    })
    resp = _call(fetcher, "GET", f"{BAND_DATA_URL}?{params}",
                 headers={"apptoken": app_token})
    if not isinstance(resp, dict):
        raise ZeppError("unexpected data-API response (non-JSON)")
    code = resp.get("code")
    if code is not None and code != 1:
        raise ZeppError(
            f"data API refused (code={code}): {resp.get('message', 'no message')}"
        )
    data = resp.get("data")
    return data if isinstance(data, list) else []


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _decode_summary(raw) -> dict:
    """summary may arrive as dict, JSON string or base64-of-JSON — or garbage."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {}
    if not isinstance(raw, str) or not raw.strip():
        return {}
    for candidate in (raw, None):
        if candidate is None:
            try:
                candidate = base64.b64decode(raw, validate=True).decode("utf-8")
            except (binascii.Error, ValueError, UnicodeDecodeError):
                return {}
        try:
            doc = json.loads(candidate)
            return doc if isinstance(doc, dict) else {}
        except (ValueError, TypeError):
            continue
    return {}


def _iso_utc(epoch) -> str | None:
    """Epoch (s or ms) -> 'YYYY-MM-DD HH:MM:SS +0000' (Health Auto Export format)."""
    val = _num(epoch)
    if not val or val <= 0:
        return None
    if val > 1e12:  # came in milliseconds
        val /= 1000.0
    try:
        return dt.datetime.fromtimestamp(val, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S %z")
    except (OverflowError, OSError, ValueError):
        return None


def build_export(items: list[dict]) -> tuple[dict, dict]:
    """Raw band_data items -> (Health Auto Export doc, statistics).

    Sleep: asleep = (dp+lt)/60, deep = dp/60, core = lt/60 (Zepp does not separate
    REM, so ``rem`` is omitted). resting_heart_rate only enters when the summary
    carries rhr.
    """
    rhr_pts, sleep_pts, step_pts = [], [], []
    skipped = 0

    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        day = item.get("date_time") or item.get("date")
        if not day:
            skipped += 1
            continue
        day = str(day)[:10]
        summary = _decode_summary(item.get("summary"))
        slp = summary.get("slp")
        if not isinstance(slp, dict):
            slp = {}
        stp = summary.get("stp")
        if not isinstance(stp, dict):
            stp = {}
        produced = False

        dp, lt = _num(slp.get("dp")), _num(slp.get("lt"))
        if dp is not None or lt is not None:
            dp, lt = dp or 0.0, lt or 0.0
            pt = {
                "date": day,
                "asleep": round((dp + lt) / 60.0, 2),
                "deep": round(dp / 60.0, 2),
                "core": round(lt / 60.0, 2),
            }
            start, end = _iso_utc(slp.get("st")), _iso_utc(slp.get("ed"))
            if start:
                pt["sleepStart"] = start
            if end:
                pt["sleepEnd"] = end
            st_s, ed_s = _num(slp.get("st")), _num(slp.get("ed"))
            if st_s and ed_s and ed_s > st_s:
                pt["inBed"] = round((ed_s - st_s) / 3600.0, 2)
            sleep_pts.append(pt)
            produced = True

        rhr = _num(slp.get("rhr"))
        if rhr is None:
            rhr = _num(summary.get("rhr"))
        if rhr is not None and rhr > 0:
            rhr_pts.append({"qty": rhr, "date": f"{day} 00:00:00 +0000"})
            produced = True

        steps = _num(stp.get("ttl"))
        if steps is not None:
            step_pts.append({"qty": steps, "date": f"{day} 00:00:00 +0000"})
            produced = True

        if not produced:
            skipped += 1

    metrics = []
    if rhr_pts:
        metrics.append({"name": "resting_heart_rate", "units": "bpm", "data": rhr_pts})
    if sleep_pts:
        metrics.append({"name": "sleep_analysis", "units": "h", "data": sleep_pts})
    if step_pts:
        metrics.append({"name": "step_count", "units": "count", "data": step_pts})

    stats = {"sleep": len(sleep_pts), "rhr": len(rhr_pts),
             "steps": len(step_pts), "skipped": skipped}
    return {"data": {"metrics": metrics}}, stats


def write_export(doc: dict, out_dir: str | Path, from_date: str, to_date: str) -> Path:
    """Writes ``zepp_export_{from}_{to}.json`` into the target folder (created if needed)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"zepp_export_{from_date}_{to_date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def compute_range(days: int, from_date: str | None, to_date: str | None,
                  today: dt.date | None = None) -> tuple[str, str]:
    """Explicit --from/--to or a --days window ending today."""
    def _parse(label: str, value: str) -> dt.date:
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            raise ZeppError(f"invalid date in {label}: {value!r} (use YYYY-MM-DD)") from None

    today = today or dt.date.today()
    end = _parse("--to", to_date) if to_date else today
    start = _parse("--from", from_date) if from_date else end - dt.timedelta(days=days)
    if start > end:
        raise ZeppError(f"invalid range: {start} > {end}")
    return start.isoformat(), end.isoformat()


def main(argv=None, fetcher=None, env=None) -> int:
    fetcher = fetcher or default_fetcher
    env = env if env is not None else os.environ

    parser = argparse.ArgumentParser(
        prog="python -m amazfit_mcp.zepp_cloud",
        description="EXPERIMENTAL: extracts sleep/RHR/steps from the Zepp cloud into "
                    "the recovery store (Health Auto Export format).",
    )
    parser.add_argument("--days", type=int, default=14,
                        help="window of days ending today (default: 14)")
    parser.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD",
                        help="explicit start date")
    parser.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD",
                        help="explicit end date")
    parser.add_argument("--out", default=None,
                        help="target folder (default: config.recovery_dir())")
    args = parser.parse_args(argv)

    try:
        from_date, to_date = compute_range(args.days, args.from_date, args.to_date)
        app_token, user_id = resolve_auth(env=env, fetcher=fetcher)
        items = fetch_band_data(app_token, user_id, from_date, to_date, fetcher=fetcher)
    except ZeppError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    doc, stats = build_export(items)
    out_dir = Path(args.out).expanduser() if args.out else config.recovery_dir()
    path = write_export(doc, out_dir, from_date, to_date)

    print(f"{len(items)} item(s) received from the Zepp cloud ({from_date} -> {to_date})")
    print(f"  sleep: {stats['sleep']} day(s) | resting HR: {stats['rhr']} day(s) "
          f"| steps: {stats['steps']} day(s)")
    if stats["skipped"]:
        print(f"  warning: {stats['skipped']} item(s) without a usable summary (skipped)")
    if not (stats["sleep"] or stats["rhr"] or stats["steps"]):
        print("  warning: no usable data in the range — file written empty")
    print(f"file written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
