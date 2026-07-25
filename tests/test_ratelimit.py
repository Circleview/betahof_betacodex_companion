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
