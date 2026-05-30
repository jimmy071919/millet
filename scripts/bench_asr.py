#!/usr/bin/env python3
"""ASR backend benchmark harness for millet.

Runs the same audio through up to three configurations and reports speed
(RTFx = audio_seconds / wall_seconds), segment counts, and dumps each
transcript so a human can compare quality side-by-side.  WER against the
stored .json transcripts is intentionally NOT computed: those transcripts are
themselves WhisperX output, so comparing to them measures "closeness to
Whisper", not correctness — and in particular cannot reveal Whisper's
overlapping-speech speaker-attribution errors (the thing we care about).

Configs:
  A = whisperx (current default)
  B = parakeet, native VAD-segment timestamps (skip alignment)  [fast]
  C = parakeet + WhisperX wav2vec2 alignment                    [accurate ts]

Usage:
  python scripts/bench_asr.py AUDIO.wav [--configs A,B,C] [--out DIR]
      [--mixdown mono|dual] [--device cuda|cpu] [--hf-token TOKEN]

Notes:
  * For the overlap-attribution comparison, run with --mixdown dual on a
    stereo recording: channel identity becomes speaker identity, so cleaner
    per-channel ASR directly improves attribution.
  * Diarization (config A, mono) needs an HF token; pass --hf-token or set
    HF_TOKEN.  B/C skip diarization unless alignment/labeling applies.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path


def _build_config(letter: str, *, device, hf_token, mixdown):
    from millet.transcribe import TranscriptionConfig

    if letter == "A":
        return TranscriptionConfig(
            asr_backend="whisperx",
            device=device,
            hf_token=hf_token,
            mixdown=mixdown,
        )
    if letter == "B":
        return TranscriptionConfig(
            asr_backend="parakeet",
            parakeet_skip_alignment=True,  # native timestamps
            device=device,
            hf_token=hf_token,
            mixdown=mixdown,
        )
    if letter == "C":
        return TranscriptionConfig(
            asr_backend="parakeet",
            parakeet_skip_alignment=False,  # keep WhisperX alignment
            device=device,
            hf_token=hf_token,
            mixdown=mixdown,
        )
    raise ValueError(f"Unknown config '{letter}' (expected A, B, or C)")


def _run_one(letter: str, audio_path: Path, out_dir: Path, *, device, hf_token, mixdown):
    from millet.transcribe import get_audio_duration
    from millet.transcribe import transcribe as do_transcribe

    config = _build_config(letter, device=device, hf_token=hf_token, mixdown=mixdown)
    audio_sec = get_audio_duration(audio_path)

    print(f"\n=== Config {letter}: backend={config.asr_backend} "
          f"skip_align={config.skip_alignment} mixdown={config.mixdown} ===")
    t0 = time.monotonic()
    transcript = do_transcribe(audio_path, config)
    wall = time.monotonic() - t0
    rtfx = (audio_sec / wall) if wall > 0 else 0.0

    stem = f"{audio_path.stem}.config{letter}"
    txt_path = out_dir / f"{stem}.txt"
    json_path = out_dir / f"{stem}.json"
    txt_path.write_text(transcript.to_text(), encoding="utf-8")
    json_path.write_text(transcript.to_json(), encoding="utf-8")

    n_speakers = len(transcript.speakers)
    n_segs = len(transcript.segments)
    result = {
        "config": letter,
        "backend": config.asr_backend,
        "skip_alignment": config.skip_alignment,
        "mixdown": config.mixdown,
        "audio_sec": round(audio_sec, 1),
        "wall_sec": round(wall, 1),
        "rtfx": round(rtfx, 2),
        "n_speakers": n_speakers,
        "n_segments": n_segs,
        "txt": str(txt_path),
        "json": str(json_path),
    }
    print(f"  audio={audio_sec:.0f}s wall={wall:.1f}s RTFx={rtfx:.2f} "
          f"speakers={n_speakers} segments={n_segs}")
    print(f"  -> {txt_path}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="millet ASR backend benchmark")
    ap.add_argument("audio", type=Path, help="Audio file (wav/ogg) or session dir")
    ap.add_argument("--configs", default="A,B,C", help="Comma list of A,B,C")
    ap.add_argument("--out", type=Path, default=None, help="Output dir (default: ./asr_bench)")
    ap.add_argument("--mixdown", choices=["mono", "dual"], default="mono")
    ap.add_argument("--device", default=None, help="cuda|cpu (default: auto)")
    ap.add_argument("--hf-token", default=None, help="HF token for diarization (config A mono)")
    args = ap.parse_args()

    audio_path = args.audio
    if audio_path.is_dir():
        cands = sorted(audio_path.glob("*.wav")) or sorted(audio_path.glob("*.ogg"))
        if not cands:
            raise SystemExit(f"No .wav/.ogg in {audio_path}")
        audio_path = cands[0]

    out_dir = args.out or Path("asr_bench")
    out_dir.mkdir(parents=True, exist_ok=True)

    letters = [c.strip().upper() for c in args.configs.split(",") if c.strip()]
    results = []
    for letter in letters:
        try:
            results.append(
                _run_one(
                    letter, audio_path, out_dir,
                    device=args.device, hf_token=args.hf_token, mixdown=args.mixdown,
                )
            )
        except Exception as exc:
            print(f"  Config {letter} FAILED: {exc}")
            results.append({"config": letter, "error": str(exc)})

    summary_path = out_dir / f"{audio_path.stem}.bench_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(f"{'cfg':>3} {'backend':>9} {'RTFx':>6} {'wall_s':>7} {'segs':>5} {'spk':>3}")
    for r in results:
        if "error" in r:
            print(f"{r['config']:>3} {'ERROR':>9}  {r['error'][:50]}")
        else:
            print(f"{r['config']:>3} {r['backend']:>9} {r['rtfx']:>6} "
                  f"{r['wall_sec']:>7} {r['n_segments']:>5} {r['n_speakers']:>3}")
    print(f"\nSummary: {summary_path}")
    print("Compare transcripts side-by-side; for overlap attribution use --mixdown dual.")
    _ = asdict  # keep import used if config dumping is added later


if __name__ == "__main__":
    main()
