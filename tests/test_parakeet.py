"""Tests for the Parakeet ASR backend (millet.parakeet) and its wiring into
millet.transcribe.

These tests mock onnx-asr entirely so they run with no model download and no
onnxruntime session — they verify the *contract* (WhisperX-shaped dict),
config B/C alignment behavior, backend validation, and dispatch.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from millet.transcribe import TranscriptionConfig, _transcribe_asr

# ─── Config validation + B/C alignment wiring ───────────────────────────────

class TestParakeetConfig:
    def test_parakeet_is_valid_backend(self):
        c = TranscriptionConfig(asr_backend="parakeet", device="cpu")
        assert c.asr_backend == "parakeet"

    def test_invalid_backend_rejected(self):
        with pytest.raises(ValueError, match="Invalid ASR backend"):
            TranscriptionConfig(asr_backend="bogus", device="cpu")

    def test_config_b_skips_alignment_by_default(self):
        # B = trust native Parakeet timestamps.
        c = TranscriptionConfig(asr_backend="parakeet", device="cpu")
        assert c.parakeet_skip_alignment is True
        assert c.skip_alignment is True

    def test_config_c_keeps_alignment(self):
        # C = Parakeet text + WhisperX alignment.
        c = TranscriptionConfig(
            asr_backend="parakeet",
            parakeet_skip_alignment=False,
            device="cpu",
        )
        assert c.skip_alignment is False

    def test_parakeet_does_not_resolve_whisper_alias(self):
        # Parakeet model names are onnx-asr identifiers; self.model must be
        # left untouched (no CTranslate2 alias resolution).
        c = TranscriptionConfig(
            asr_backend="parakeet", model="some-onnx-name", device="cpu"
        )
        assert c.model == "some-onnx-name"

    def test_whisperx_alignment_unaffected(self):
        c = TranscriptionConfig(asr_backend="whisperx", device="cpu")
        assert c.skip_alignment is False

    def test_auto_never_selects_parakeet(self):
        # Parakeet is opt-in only; auto must resolve to whisperx/mlx.
        c = TranscriptionConfig(asr_backend="auto", device="cpu")
        assert c.asr_backend in ("whisperx", "mlx")


# ─── Backend contract: WhisperX-shaped dict ─────────────────────────────────

def _fake_onnx_asr_module():
    """Build a fake onnx_asr module whose VAD pipeline yields 3 segments."""
    seg_results = [
        SimpleNamespace(start=0.0, end=2.0, text="Hello there."),
        SimpleNamespace(start=2.5, end=4.0, text="  General Kenobi.  "),
        SimpleNamespace(start=4.0, end=5.0, text=""),  # empty -> dropped
    ]
    vad_adapter = MagicMock()
    vad_adapter.recognize.return_value = iter(seg_results)
    model = MagicMock()
    model.with_vad.return_value = vad_adapter

    fake = MagicMock()
    fake.load_model.return_value = model
    fake.load_vad.return_value = MagicMock()
    return fake, model, vad_adapter


@pytest.fixture
def fake_onnx(monkeypatch):
    """Inject a fake onnx_asr module + mark the backend available."""
    import millet.parakeet as pk

    fake, model, vad_adapter = _fake_onnx_asr_module()
    pk._MODEL_CACHE.clear()
    pk._VAD_CACHE.clear()
    monkeypatch.setattr(pk, "parakeet_available", lambda: True)
    monkeypatch.setitem(__import__("sys").modules, "onnx_asr", fake)
    yield SimpleNamespace(module=fake, model=model, vad_adapter=vad_adapter)
    pk._MODEL_CACHE.clear()
    pk._VAD_CACHE.clear()


class TestParakeetContract:
    def test_returns_whisperx_shape(self, fake_onnx):
        import millet.parakeet as pk

        audio = np.zeros(16000, dtype=np.float32)
        out = pk.transcribe_parakeet(audio, device="cpu", language="en")

        assert set(out) == {"segments", "language", "text"}
        assert out["language"] == "en"
        # Empty segment dropped -> 2 segments.
        assert len(out["segments"]) == 2
        for s in out["segments"]:
            assert set(s) == {"start", "end", "text"}
            assert isinstance(s["start"], float)
            assert isinstance(s["end"], float)
        # Text is stripped + joined.
        assert out["segments"][1]["text"] == "General Kenobi."
        assert out["text"] == "Hello there. General Kenobi."

    def test_global_timestamps_preserved(self, fake_onnx):
        import millet.parakeet as pk

        audio = np.zeros(16000, dtype=np.float32)
        out = pk.transcribe_parakeet(audio, device="cpu")
        # VAD adapter returns global timestamps; we pass them straight through.
        assert out["segments"][0]["start"] == 0.0
        assert out["segments"][1]["start"] == 2.5

    def test_non_float32_audio_coerced(self, fake_onnx):
        import millet.parakeet as pk

        audio = np.zeros(16000, dtype=np.int16)  # wrong dtype on purpose
        out = pk.transcribe_parakeet(audio, device="cpu")
        assert len(out["segments"]) == 2  # still works after coercion

    def test_dispatch_through_transcribe_asr(self, fake_onnx):
        """_transcribe_asr must route asr_backend='parakeet' to the module."""
        config = TranscriptionConfig(asr_backend="parakeet", device="cpu")
        audio = np.zeros(16000, dtype=np.float32)
        out = _transcribe_asr(audio, config, language="en")
        assert out["language"] == "en"
        assert len(out["segments"]) == 2


# ─── Availability + error guidance ──────────────────────────────────────────

class TestParakeetAvailability:
    def test_missing_onnx_asr_raises_actionable(self):
        import millet.parakeet as pk

        pk._MODEL_CACHE.clear()
        with patch("millet.parakeet.parakeet_available", return_value=False):
            with pytest.raises(RuntimeError, match="millet-pipeline\\[parakeet\\]"):
                pk.load_parakeet(device="cpu")
