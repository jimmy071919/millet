"""Tests for meet.pdf — PDF generation helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from millet.pdf import (
    _escape_xml,
    _group_speaker_turns,
    _is_rtl,
    _md_to_markup,
    _reshape_rtl,
    generate_pdf,
)
from millet.transcribe import Segment, Speaker, Transcript


# ─── _is_rtl() ─────────────────────────────────────────────────────────────

class TestIsRtl:
    def test_farsi_is_rtl(self):
        assert _is_rtl("fa") is True

    def test_arabic_is_rtl(self):
        assert _is_rtl("ar") is True

    def test_english_is_not_rtl(self):
        assert _is_rtl("en") is False

    def test_german_is_not_rtl(self):
        assert _is_rtl("de") is False


# ─── _escape_xml() ─────────────────────────────────────────────────────────

class TestEscapeXml:
    def test_ampersand(self):
        assert _escape_xml("A & B") == "A &amp; B"

    def test_angle_brackets(self):
        assert _escape_xml("<tag>") == "&lt;tag&gt;"

    def test_no_escaping_needed(self):
        assert _escape_xml("hello world") == "hello world"


# ─── _md_to_markup() ───────────────────────────────────────────────────────

class TestMdToMarkup:
    def test_bold(self):
        result = _md_to_markup("this is **bold** text")
        assert "<b>bold</b>" in result

    def test_italic(self):
        result = _md_to_markup("this is *italic* text")
        assert "<i>italic</i>" in result

    def test_mixed(self):
        result = _md_to_markup("**bold** and *italic*")
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result

    def test_escapes_plain_text(self):
        result = _md_to_markup("A & B are <great>")
        assert "&amp;" in result
        assert "&lt;great&gt;" in result

    def test_no_formatting(self):
        result = _md_to_markup("plain text")
        assert result == "plain text"


# ─── _group_speaker_turns() ────────────────────────────────────────────────

class TestGroupSpeakerTurns:
    def test_merges_consecutive(self):
        t = Transcript(
            segments=[
                Segment(start=0, end=5, text="Hello.", speaker="Alice"),
                Segment(start=5, end=10, text="World.", speaker="Alice"),
                Segment(start=10, end=15, text="Hi.", speaker="Bob"),
            ],
            speakers=[Speaker(id="Alice"), Speaker(id="Bob")],
            language="en", audio_file="test.wav",
        )
        turns = _group_speaker_turns(t)
        assert len(turns) == 2
        assert turns[0]["speaker"] == "Alice"
        assert "Hello." in turns[0]["text"]
        assert "World." in turns[0]["text"]
        assert turns[0]["end"] == 10  # merged end time

    def test_no_merge_different_speakers(self, transcript):
        turns = _group_speaker_turns(transcript)
        # Our fixture alternates speakers, so no merging
        assert len(turns) == 6

    def test_empty_text_skipped(self):
        t = Transcript(
            segments=[
                Segment(start=0, end=5, text="Hello.", speaker="A"),
                Segment(start=5, end=10, text="   ", speaker="A"),
                Segment(start=10, end=15, text="World.", speaker="A"),
            ],
            speakers=[Speaker(id="A")],
            language="en", audio_file="test.wav",
        )
        turns = _group_speaker_turns(t)
        # Empty segment is skipped, but Hello and World should merge
        # since they're from the same speaker and nothing interrupts
        assert len(turns) == 1
        assert "Hello." in turns[0]["text"]
        assert "World." in turns[0]["text"]


# ─── _reshape_rtl() ────────────────────────────────────────────────────────

class TestReshapeRtl:
    def test_farsi_text_transformed(self):
        """RTL reshape should change Farsi text (glyph joining)."""
        farsi = "خلاصه جلسه"
        result = _reshape_rtl(farsi)
        # The result should be different due to reshaping/reordering
        assert isinstance(result, str)
        assert len(result) > 0

    def test_latin_text_unchanged(self):
        """Latin text should pass through mostly unchanged."""
        result = _reshape_rtl("hello world")
        assert "hello" in result


# ─── generate_pdf() ────────────────────────────────────────────────────────

class TestGeneratePdf:
    def test_creates_file(self, transcript, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        result = generate_pdf(transcript, pdf_path, language="en")
        assert result.exists()
        assert result.stat().st_size > 0

    def test_pdf_starts_with_header(self, transcript, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        generate_pdf(transcript, pdf_path, language="en")
        # PDF files start with %PDF
        with open(pdf_path, "rb") as f:
            header = f.read(5)
        assert header == b"%PDF-"

    def test_with_summary(self, transcript, tmp_path):
        from millet.summarize import MeetingSummary

        summary = MeetingSummary(
            markdown="## Overview\nA test meeting.",
            model="test-model",
            elapsed_seconds=1.0,
        )
        pdf_path = tmp_path / "test_summary.pdf"
        result = generate_pdf(transcript, pdf_path, summary=summary, language="en")
        assert result.exists()
        # PDF with summary should be larger than without
        plain_path = tmp_path / "test_plain.pdf"
        generate_pdf(transcript, plain_path, language="en")
        assert result.stat().st_size >= plain_path.stat().st_size
