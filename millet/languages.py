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


# Local default language support for Chinese meetings.  The upstream
# millet-record language table only ships the languages originally targeted by
# the project, but Whisper/WhisperX accept the standard `zh` code.
LANG_NAMES.setdefault("zh", "Chinese")
SECTION_HEADERS.setdefault(
    "zh",
    {
        "overview": "會議概述",
        "topics": "討論重點",
        "actions": "待辦事項",
        "decisions": "已做決策",
        "questions": "未解問題 / 後續追蹤",
        "none_stated": "未明確提及",
    },
)
