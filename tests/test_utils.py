"""Tests for millet.utils — shared formatting utility functions."""

from millet.utils import fmt_elapsed, fmt_size, fmt_srt_time, fmt_time, fmt_time_short

# ─── fmt_time (HH:MM:SS) ───────────────────────────────────────────────────

class TestFmtTime:
    def test_zero(self):
        assert fmt_time(0) == "00:00:00"

    def test_seconds_only(self):
        assert fmt_time(45) == "00:00:45"

    def test_minutes_and_seconds(self):
        assert fmt_time(125) == "00:02:05"

    def test_hours_minutes_seconds(self):
        assert fmt_time(3661) == "01:01:01"

    def test_fractional_truncates(self):
        # Fractional seconds should be truncated, not rounded
        assert fmt_time(59.9) == "00:00:59"


# ─── fmt_srt_time (HH:MM:SS,mmm) ──────────────────────────────────────────

class TestFmtSrtTime:
    def test_zero(self):
        assert fmt_srt_time(0) == "00:00:00,000"

    def test_with_milliseconds(self):
        assert fmt_srt_time(1.234) == "00:00:01,234"

    def test_hours(self):
        assert fmt_srt_time(3723.456) == "01:02:03,456"

    def test_rounding_ms(self):
        # 0.999 seconds -> 999 ms
        assert fmt_srt_time(0.999) == "00:00:00,999"


# ─── fmt_elapsed (same as fmt_time, aliased for clarity) ───────────────────

class TestFmtElapsed:
    def test_zero(self):
        assert fmt_elapsed(0) == "00:00:00"

    def test_typical(self):
        assert fmt_elapsed(3723.5) == "01:02:03"


# ─── fmt_size ──────────────────────────────────────────────────────────────

class TestFmtSize:
    def test_bytes(self):
        assert fmt_size(512) == "512 B"

    def test_kilobytes(self):
        assert fmt_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert fmt_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert fmt_size(2 * 1024 * 1024 * 1024) == "2.0 GB"

    def test_zero(self):
        assert fmt_size(0) == "0 B"


# ─── fmt_time_short (MM:SS or HH:MM:SS) ───────────────────────────────────

class TestFmtTimeShort:
    def test_under_one_hour(self):
        assert fmt_time_short(125) == "02:05"

    def test_zero(self):
        assert fmt_time_short(0) == "00:00"

    def test_exactly_one_hour(self):
        assert fmt_time_short(3600) == "01:00:00"

    def test_over_one_hour(self):
        assert fmt_time_short(3723) == "01:02:03"
