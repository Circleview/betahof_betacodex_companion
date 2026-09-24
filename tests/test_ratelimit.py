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
