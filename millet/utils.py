"""Backward-compat shim — formatting helpers live in `millet-record` (formerly `meetscribe-record`) since meetscribe-offline 0.5.0.

Re-exports all public names from `meet_record.utils`.
"""

from millet_record.utils import *  # noqa: F403
from millet_record.utils import (  # noqa: F401  re-exported names
    fmt_elapsed,
    fmt_size,
    fmt_srt_time,
    fmt_time,
    fmt_time_short,
)
