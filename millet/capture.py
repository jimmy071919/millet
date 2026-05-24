"""Backward-compat shim — capture lives in `millet-record` (formerly
`meetscribe-record`) since meetscribe-offline 0.5.0.

This module re-exports everything from `millet_record.capture` so that
existing code (and any third-party importers) continue to work with
both `from meet.capture import ...` (now an import-alias of millet) and
`from millet.capture import ...`.  All real implementation lives
upstream in the millet-record package.

To install just the capture primitives without millet-pipeline's heavy
deps:

    pip install millet-record

To get the full pipeline:

    pip install millet-pipeline
"""

from meet_record.capture import *  # noqa: F401,F403
from meet_record.capture import (  # noqa: F401  re-exported names
    DRAIN_SECONDS,
    RecordingSession,
    create_session,
    check_prerequisites,
    list_sources,
    get_default_sink,
    get_default_source,
)
