"""Backward-compat shim — formatting helpers live in `millet-record` (formerly `meetscribe-record`) since meetscribe-offline 0.5.0.

Re-exports all public names from `meet_record.utils`.
"""

from meet_record.utils import *  # noqa: F401,F403
from meet_record.utils import (  # noqa: F401  re-exported names
    fmt_elapsed,
    fmt_size,
    fmt_time,
    fmt_time_short,
    fmt_srt_time,
)
