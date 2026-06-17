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


# ─── many-to-one matching (0.12.11) ──────────────────────────────────────────
# Regression: diarization over-segments ONE person into several clusters
# (volume/mic changes, cross-channel bleed).  Greedy 1:1 matching used to name
# only the first cluster and leave the rest raw → needs_labeling + "Destiny ×3".
# identify_speakers now lets an already-claimed profile ALSO claim additional
# clusters when each is confident on its own.

import numpy as np  # noqa: E402

from millet import voiceprint as _vp  # noqa: E402
from millet.transcribe import Segment, Speaker  # noqa: E402
from millet.voiceprint import (  # noqa: E402
    SpeakerProfile,
    identify_speakers,
)


def _unit(*vals: float) -> np.ndarray:
    v = np.array(vals, dtype=np.float32)
    return v / np.linalg.norm(v)


def _run_identify(monkeypatch, *, cluster_embeddings, profiles):
    """Drive identify_speakers with mocked embedding extraction.

    ``cluster_embeddings``: {speaker_id -> unit vector}.  Each cluster gets one
    long (well over the 4s evidence floor) segment so the auto-apply gate never
    trips for confident matches.
    """
    speakers = [Speaker(id=sid, label=sid) for sid in cluster_embeddings]
    segments = [
        Segment(start=float(i * 100), end=float(i * 100 + 60), text="x", speaker=sid)
        for i, sid in enumerate(cluster_embeddings)
    ]
    channel_map = {sid: "system" for sid in cluster_embeddings}

    monkeypatch.setattr(_vp, "load_profiles", lambda profiles_path=None: profiles)
    monkeypatch.setattr(_vp, "_get_inference", lambda: object())
    monkeypatch.setattr(
        _vp, "_extract_channel_audio",
        lambda audio_path, channel: (np.ones(16000, dtype=np.float32), 16000),
    )

    # _embed_segments is called once per cluster, in the loop order of all_ids.
    # Map by the (sorted-by-duration) selected segments isn't needed: we key off
    # which speaker's audio is being embedded.  Use a counter over speaker ids.
    order = list(cluster_embeddings)
    state = {"i": 0}

    def fake_embed(samples, sr, selected, inference):
        sid = order[state["i"]]
        state["i"] += 1
        return cluster_embeddings[sid]

    monkeypatch.setattr(_vp, "_embed_segments", fake_embed)

    from pathlib import Path
    return identify_speakers(
        Path("/tmp/fake.ogg"), segments, speakers, channel_map,
        profiles_path=Path("/tmp/profiles.json"),
    )


def test_two_clusters_same_person_both_matched(monkeypatch):
    """Two near-identical Destiny clusters → BOTH named Destiny (many-to-one)."""
    destiny = _unit(1.0, 0.0, 0.0)
    andrej = _unit(0.0, 1.0, 0.0)
    matches = _run_identify(
        monkeypatch,
        cluster_embeddings={
            "SPEAKER_00": _unit(1.0, 0.02, 0.0),   # Destiny (best)
            "SPEAKER_01": andrej,                   # Andrej
            "SPEAKER_02": _unit(0.98, 0.05, 0.0),  # Destiny again (high conf)
        },
        profiles={
            "Destiny": SpeakerProfile("Destiny", destiny, 3),
            "Andrej": SpeakerProfile("Andrej", andrej, 3),
        },
    )
    assert matches["SPEAKER_00"].name == "Destiny"
    assert matches["SPEAKER_02"].name == "Destiny"  # would be raw under 1:1
    assert matches["SPEAKER_01"].name == "Andrej"


def test_secondary_cluster_below_autoapply_stays_unmatched(monkeypatch):
    """A 2nd cluster that only weakly resembles the claimed profile is NOT
    folded on (stays raw → human review), guarding against over-merge."""
    destiny = _unit(1.0, 0.0, 0.0)
    # Second 'Destiny-ish' cluster at ~0.66 cosine: above MATCH_THRESHOLD (0.65)
    # but below MATCH_AUTOAPPLY_CONFIDENCE (0.72) → not auto-folded.
    weak = _unit(0.66, 0.751, 0.0)
    assert float(np.dot(weak, destiny)) < MATCH_AUTOAPPLY_CONFIDENCE
    matches = _run_identify(
        monkeypatch,
        cluster_embeddings={
            "SPEAKER_00": destiny,        # strong Destiny
            "SPEAKER_01": weak,           # weak resemblance
        },
        profiles={"Destiny": SpeakerProfile("Destiny", destiny, 3)},
    )
    assert matches["SPEAKER_00"].name == "Destiny"
    assert "SPEAKER_01" not in matches


def test_single_cluster_per_profile_unchanged(monkeypatch):
    """Baseline: distinct people still map 1:1."""
    destiny = _unit(1.0, 0.0, 0.0)
    andrej = _unit(0.0, 1.0, 0.0)
    matches = _run_identify(
        monkeypatch,
        cluster_embeddings={"SPEAKER_00": destiny, "SPEAKER_01": andrej},
        profiles={
            "Destiny": SpeakerProfile("Destiny", destiny, 3),
            "Andrej": SpeakerProfile("Andrej", andrej, 3),
        },
    )
    assert matches["SPEAKER_00"].name == "Destiny"
    assert matches["SPEAKER_01"].name == "Andrej"
