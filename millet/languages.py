"""Backward-compat shim — language constants live in `millet-record` (formerly `meetscribe-record`) since meetscribe-offline 0.5.0.

Re-exports all public names from `meet_record.languages`.
"""

from meet_record.languages import *  # noqa: F401,F403
from meet_record.languages import (  # noqa: F401  re-exported names
    LANG_NAMES,
    RTL_LANGUAGES,
    is_rtl,
    SECTION_HEADERS,
    PDF_SECTIONS,
)
