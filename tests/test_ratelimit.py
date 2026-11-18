from unittest.mock import patch

from app import ratelimit


def test_is_rate_limited_allows_requests_within_limit():
    ratelimit._request_log.clear()
    for _ in range(5):
        assert ratelimit.is_rate_limited("1.2.3.4", max_requests=5, window_seconds=60) is False


def test_is_rate_limited_blocks_requests_beyond_limit():
    ratelimit._request_log.clear()
    for _ in range(5):
        ratelimit.is_rate_limited("1.2.3.4", max_requests=5, window_seconds=60)

    assert ratelimit.is_rate_limited("1.2.3.4", max_requests=5, window_seconds=60) is True


def test_is_rate_limited_tracks_keys_independently():
    ratelimit._request_log.clear()
    for _ in range(5):
        ratelimit.is_rate_limited("1.2.3.4", max_requests=5, window_seconds=60)

    assert ratelimit.is_rate_limited("5.6.7.8", max_requests=5, window_seconds=60) is False


def test_is_rate_limited_resets_after_window_passes():
    ratelimit._request_log.clear()
    with patch("app.ratelimit.time.monotonic", return_value=1000.0):
        for _ in range(5):
            ratelimit.is_rate_limited("1.2.3.4", max_requests=5, window_seconds=60)

    with patch("app.ratelimit.time.monotonic", return_value=1061.0):
        assert ratelimit.is_rate_limited("1.2.3.4", max_requests=5, window_seconds=60) is False


def test_retry_after_seconds_counts_down_to_when_oldest_request_leaves_window():
    ratelimit._request_log.clear()
    with patch("app.ratelimit.time.monotonic", return_value=1000.0):
        for _ in range(2):
            ratelimit.is_rate_limited("k", max_requests=2, window_seconds=600)
    with patch("app.ratelimit.time.monotonic", return_value=1100.4):
        assert ratelimit.is_rate_limited("k", max_requests=2, window_seconds=600) is True
        assert ratelimit.retry_after_seconds("k", 600) == 500


def test_retry_after_seconds_is_zero_for_unknown_key():
    ratelimit._request_log.clear()
    assert ratelimit.retry_after_seconds("unbekannt", 600) == 0


def test_char_budget_allows_exact_sum_then_blocks_and_isolates_keys():
    ratelimit._char_log.clear()
    assert ratelimit.is_char_budget_exceeded("a", 600, 1000, 3600) is False
    assert ratelimit.is_char_budget_exceeded("a", 400, 1000, 3600) is False
    assert ratelimit.is_char_budget_exceeded("a", 1, 1000, 3600) is True
    assert ratelimit.is_char_budget_exceeded("b", 1000, 1000, 3600) is False


def test_char_budget_frees_after_window():
    ratelimit._char_log.clear()
    with patch("app.ratelimit.time.monotonic", return_value=1000.0):
        assert ratelimit.is_char_budget_exceeded("a", 1000, 1000, 3600) is False
    with patch("app.ratelimit.time.monotonic", return_value=4601.0):
        assert ratelimit.is_char_budget_exceeded("a", 1000, 1000, 3600) is False


def test_ip_key_truncates_ipv6_to_64_and_keeps_ipv4_and_unknown():
    assert ratelimit.ip_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd") == ratelimit.ip_key(
        "2001:db8:1:2:1111:2222:3333:4444"
    )
    assert ratelimit.ip_key("2001:db8:1:2::1") != ratelimit.ip_key("2001:db8:1:3::1")
    assert ratelimit.ip_key("1.2.3.4") == "1.2.3.4"
    assert ratelimit.ip_key("unknown") == "unknown"


def test_expired_keys_are_removed_from_memory():
    ratelimit._request_log.clear()
    ratelimit._char_log.clear()
    ratelimit._last_sweep = 0.0
    with patch("app.ratelimit.time.monotonic", return_value=1000.0):
        ratelimit.is_rate_limited("old", max_requests=5, window_seconds=60)
        ratelimit.is_char_budget_exceeded("oldc", 5, 100, 60)
    with patch("app.ratelimit.time.monotonic", return_value=2000.0):
        ratelimit.is_rate_limited("new", max_requests=5, window_seconds=60)
    assert "old" not in ratelimit._request_log
    assert "oldc" not in ratelimit._char_log
    assert "new" in ratelimit._request_log
