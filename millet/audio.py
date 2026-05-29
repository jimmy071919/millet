"""Backward-compat shim — audio helpers live in `millet-record` (formerly `meetscribe-record`) since meetscribe-offline 0.5.0.

Re-exports all public names from `meet_record.audio`.
"""

from millet_record.audio import *  # noqa: F403
from millet_record.audio import (  # noqa: F401  re-exported names
    StereoChannels,
    compress_audio,
    compute_speaker_channel_energy,
    read_stereo_channels,
)
