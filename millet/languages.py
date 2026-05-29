"""Backward-compat shim — language constants live in `millet-record` (formerly `meetscribe-record`) since meetscribe-offline 0.5.0.

Re-exports all public names from `meet_record.languages`.
"""

from millet_record.languages import *  # noqa: F403
from millet_record.languages import (  # noqa: F401  re-exported names
    LANG_NAMES,
    PDF_SECTIONS,
    RTL_LANGUAGES,
    SECTION_HEADERS,
    is_rtl,
)
