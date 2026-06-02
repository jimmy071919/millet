"""Tests for the voiceprint auto-apply gate (weak_match_reason).

Regression: over-segmented backchannel clusters produce a barely-confident,
ambiguous voiceprint match (e.g. 0.69 with a 0.13 margin) that mis-names a
phantom speaker.  The gate suppresses such matches while still auto-applying
strong, well-separated ones (e.g. 0.93 with a 0.40 margin).
"""
from __future__ import annotations

from millet.cli.label import weak_match_reason
from millet.voiceprint import (
    MATCH_AUTOAPPLY_CONFIDENCE,
    MATCH_AUTOAPPLY_MARGIN,
    MATCH_MIN_SPEECH_SECONDS,
    SpeakerMatch,
)


def test_strong_well_separated_match_applies():
    """0.93 confidence / 0.40 margin (a real Lukas-style match) → applies."""
    m = SpeakerMatch("Lukas", 0.93, evidence_seconds=958.0, margin=0.40)
    assert weak_match_reason(m) is None


def test_ambiguous_low_conf_low_margin_gated():
    """0.69 / 0.13 margin (the false 'Roark' signature) → gated."""
    m = SpeakerMatch("Roark", 0.686, evidence_seconds=62.4, margin=0.128)
    reason = weak_match_reason(m)
    assert reason is not None
    assert "ambiguous" in reason


def test_strong_confidence_low_margin_still_applies():
    """High absolute confidence rescues a low margin (two similar real profiles)."""
    m = SpeakerMatch("X", 0.80, evidence_seconds=30.0, margin=0.05)
    assert m.confidence >= MATCH_AUTOAPPLY_CONFIDENCE
    assert weak_match_reason(m) is None


def test_clear_margin_rescues_modest_confidence():
    """A clear margin applies even when below the absolute auto-apply floor."""
    m = SpeakerMatch("Y", 0.70, evidence_seconds=30.0, margin=0.25)
    assert m.confidence < MATCH_AUTOAPPLY_CONFIDENCE
    assert m.margin >= MATCH_AUTOAPPLY_MARGIN
    assert weak_match_reason(m) is None


def test_thin_cluster_gated_even_if_unambiguous():
    """Too little embeddable speech → gated regardless of confidence/margin."""
    m = SpeakerMatch("Z", 0.95, evidence_seconds=2.0, margin=0.50)
    assert m.evidence_seconds < MATCH_MIN_SPEECH_SECONDS
    reason = weak_match_reason(m)
    assert reason is not None
    assert "speech" in reason


def test_positional_backcompat_not_gated():
    """Matches built positionally (no evidence/margin) use trustworthy
    sentinels and are never gated."""
    m = SpeakerMatch("W", 0.70)
    assert m.evidence_seconds == 0.0
    assert m.margin == 1.0
    assert weak_match_reason(m) is None
