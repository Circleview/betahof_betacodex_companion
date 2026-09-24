from datetime import datetime, timedelta, timezone

import pytest

from app import jsonstore, usage


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "USAGE_FILE", tmp_path / "usage_log.json")


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
    assert entry["cost_eur"] == pytest.approx(3.0 * usage.USD_TO_EUR)
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
