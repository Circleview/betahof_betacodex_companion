from datetime import datetime, timedelta, timezone

import pytest

from app import jsonstore, usage


FX_CALLS = []


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "USAGE_FILE", tmp_path / "usage_log.json")
    monkeypatch.setattr(usage, "FX_FILE", tmp_path / "fx_rate.json")
    FX_CALLS.clear()

    def fake_fetch():
        FX_CALLS.append(1)
        return 0.9, "2026-09-23"

    monkeypatch.setattr(usage, "_fetch_ecb_rate", fake_fetch)


def _usage(model="claude-sonnet-5", **overrides):
    base = {
        "model": model,
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "web_search_requests": 0,
    }
    base.update(overrides)
    return base


def test_cost_usd_combines_tokens_cache_and_web_search():
    # Sonnet 5: 2 USD/Mio. Eingabe, 10 USD/Mio. Ausgabe
    assert usage.cost_usd(_usage()) == pytest.approx(2.0 + 1.0)
    assert usage.cost_usd(_usage(web_search_requests=3)) == pytest.approx(3.0 + 0.03)
    cached = _usage(input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000, cache_read_input_tokens=1_000_000)
    assert usage.cost_usd(cached) == pytest.approx(2.0 * 1.25 + 2.0 * 0.1)
    assert usage.cost_usd(_usage(model="claude-haiku-4-5-20251001")) == pytest.approx(1.0 + 0.5)


def test_record_stores_usd_and_eur():
    entry = usage.record(_usage(), channel="mcp", web_search=True, key_id="k1", email="a@test.local")

    assert entry["cost_usd"] == pytest.approx(3.0)
    assert entry["cost_eur"] == pytest.approx(3.0 * 0.9)
    assert (entry["usd_to_eur"], entry["fx_date"], entry["fx_source"]) == (0.9, "2026-09-23", "ecb")
    assert usage.list_entries()[0]["key_id"] == "k1"


def test_record_prunes_entries_older_than_retention():
    old = (datetime.now(timezone.utc) - timedelta(days=usage.RETENTION_DAYS + 1)).isoformat()
    jsonstore.save(usage.USAGE_FILE, [{"ts": old, "key_id": None}])

    usage.record(_usage(), channel="ui", web_search=True)

    assert len(usage.list_entries()) == 1


def test_key_stats_counts_today_and_sums_month():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    jsonstore.save(
        usage.USAGE_FILE,
        [
            {"ts": "2026-09-24T08:00:00+00:00", "key_id": "k1", "cost_eur": 1.0, "cost_usd": 1.2},
            {"ts": "2026-09-02T08:00:00+00:00", "key_id": "k1", "cost_eur": 2.0, "cost_usd": 2.4},
            {"ts": "2026-08-31T08:00:00+00:00", "key_id": "k1", "cost_eur": 9.0, "cost_usd": 9.9},
            {"ts": "2026-09-24T09:00:00+00:00", "key_id": "k2", "cost_eur": 5.0, "cost_usd": 6.0},
        ],
    )

    assert usage.key_stats("k1", now) == {"calls_today": 1, "month_eur": 3.0, "month_usd": 3.6}


def test_monthly_summary_and_csv_group_by_channel_email_and_key():
    usage.record(_usage(), channel="ui", web_search=True)
    usage.record(_usage(), channel="mcp", web_search=False, key_id="k1", email="a@test.local")
    usage.record(_usage(), channel="mcp", web_search=True, key_id="k2", email="a@test.local")
    month = datetime.now(timezone.utc).strftime("%Y-%m")

    summary = usage.monthly_summary(month)

    assert summary["total"]["calls"] == 3
    assert summary["by_channel"]["mcp"]["calls"] == 2
    assert summary["by_email"]["a@test.local"]["cost_usd"] == pytest.approx(6.0)
    assert set(summary["by_key"]) == {"k1", "k2"}
    csv_text = usage.export_csv(month)
    assert csv_text.splitlines()[0].startswith("ts,channel,email,key_id")
    assert len(csv_text.strip().splitlines()) == 4


def test_current_fx_fetches_at_most_once_per_day():
    assert usage.current_fx() == {"rate": 0.9, "date": "2026-09-23", "source": "ecb"}
    usage.current_fx()
    assert len(FX_CALLS) == 1


def test_current_fx_keeps_last_known_rate_when_service_fails(monkeypatch):
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    jsonstore.save(usage.FX_FILE, {"rate": 0.88, "date": "2026-09-22", "source": "ecb", "fetched_at": yesterday})

    def boom():
        FX_CALLS.append(1)
        raise OSError("offline")

    monkeypatch.setattr(usage, "_fetch_ecb_rate", boom)

    assert usage.current_fx() == {"rate": 0.88, "date": "2026-09-22", "source": "ecb"}
    usage.current_fx()  # innerhalb einer Stunde kein zweiter Versuch
    assert len(FX_CALLS) == 1


def test_current_fx_retries_after_an_hour_and_falls_back_if_never_fetched(monkeypatch):
    def boom():
        FX_CALLS.append(1)
        raise OSError("offline")

    monkeypatch.setattr(usage, "_fetch_ecb_rate", boom)
    assert usage.current_fx() == {"rate": usage.FALLBACK_USD_TO_EUR, "date": None, "source": "fallback"}

    cache = jsonstore.load(usage.FX_FILE, {})
    cache["last_attempt_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    jsonstore.save(usage.FX_FILE, cache)
    usage.current_fx()
    assert len(FX_CALLS) == 2


def test_monthly_summary_and_csv_carry_the_rate():
    usage.record(_usage(), channel="ui", web_search=True)
    month = datetime.now(timezone.utc).strftime("%Y-%m")

    assert usage.monthly_summary(month)["fx"] == {"rate": 0.9, "date": "2026-09-23", "source": "ecb"}
    header, row = usage.export_csv(month).strip().splitlines()
    assert header.endswith("usd_to_eur,fx_date,fx_source") and row.endswith("0.9,2026-09-23,ecb")
