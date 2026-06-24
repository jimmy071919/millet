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

from pathlib import Path

from millet.paths import recordings_dir
from millet_record.capture import *  # noqa: F403
from millet_record.capture import (  # noqa: F401  re-exported names
    DRAIN_SECONDS,
    RecordingSession,
    check_prerequisites,
    create_session as _record_create_session,
    get_default_sink,
    get_default_source,
    list_sources,
)


def create_session(
    output_dir: str | Path | None = None,
    filename: str | None = None,
    mic: str | None = None,
    monitor: str | None = None,
    virtual_sink: bool = False,
) -> RecordingSession:
    """Create a recording session using millet's project-local default.

    ``millet-record`` defaults to ``~/meet-recordings``.  The pipeline keeps
    generated artefacts inside this checkout by default so recordings,
    transcripts, summaries, and PDFs stay together.
    """
    return _record_create_session(
        output_dir=recordings_dir() if output_dir is None else output_dir,
        filename=filename,
        mic=mic,
        monitor=monitor,
        virtual_sink=virtual_sink,
    )
