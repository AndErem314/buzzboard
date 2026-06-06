"""
Tests for EditorAgent and ExtractorAgent (Phase 2).

Mocks OllamaClient at the import level so agents work naturally.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.editor import EditorAgent
from src.agents.extractor import ExtractorAgent
from src.schema import CleanedNote, RawTranscript, StructuredRecord


# ── Test fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def sample_raw_transcript(tmp_path: Path) -> Path:
    """Create a RawTranscript JSON artifact for testing."""
    raw = RawTranscript(
        audio_file="H07_2026-06-06.m4a",
        hive_id="H07",
        inspection_date=date(2026, 6, 6),
        raw_text="Checked hive seven today. Queen was spotted, laying well. "
                 "Brood pattern looked solid across six frames. "
                 "Saw about three mites on the bottom board. "
                 "Honey stores are good, maybe eight frames full. "
                 "Bees were calm. Need to replace frame four — "
                 "some chalkbrood showing. Should recheck in seven days.",
        duration_seconds=45.0,
    )
    out_path = tmp_path / "raw_transcript.json"
    out_path.write_text(raw.model_dump_json(indent=2))
    return out_path


@pytest.fixture
def editor_llm_json() -> str:
    """Valid JSON the Editor LLM would return."""
    return json.dumps({
        "hive_id": "H07",
        "inspection_date": "2026-06-06",
        "observations": "Queen spotted and laying well. Brood pattern solid across "
                        "six frames. Approximately three mites observed on bottom board. "
                        "Honey stores good with eight frames full. Colony temperament calm.",
        "issues": ["Chalkbrood in frame 4", "Mite count elevated (3 on bottom board)"],
        "actions": ["Replace frame 4", "Recheck in 7 days", "Consider mite treatment"],
        "queen_status": "seen",
        "brood_pattern": "solid",
        "honey_stores": "abundant",
        "pollen_stores": "adequate",
        "temperament": "calm",
        "swarm_indicators": [],
    })


@pytest.fixture
def extractor_llm_json() -> str:
    """Valid JSON the Extractor LLM would return."""
    return json.dumps({
        "hive_id": "H07",
        "inspection_date": "2026-06-06",
        "queen_seen": True,
        "brood_health": "chalkbrood",
        "mite_count": 3,
        "honey_frames": 8,
        "issues": ["Chalkbrood in frame 4", "Mite count: 3"],
        "actions_required": ["Replace frame 4", "Recheck in 7 days", "Monitor mites"],
        "next_inspection_days": 7,
        "severity": "attention",
    })


@pytest.fixture
def clean_note_json(tmp_path: Path) -> Path:
    """A CleanedNote JSON artifact (simulating editor output)."""
    note = CleanedNote(
        hive_id="H07",
        inspection_date=date(2026, 6, 6),
        observations="Queen spotted, brood solid, 8 honey frames, calm.",
        issues=["Chalkbrood in frame 4"],
        actions=["Replace frame 4", "Recheck in 7 days"],
        queen_status="seen",
        brood_pattern="solid",
        honey_stores="abundant",
        temperament="calm",
        raw_reference="abc123",
    )
    out_path = tmp_path / "cleaned_note.json"
    out_path.write_text(note.model_dump_json(indent=2))
    return out_path


# ── EditorAgent tests ──────────────────────────────────────────────────────

class TestEditorAgent:
    """Tests for EditorAgent (raw transcript → cleaned note)."""

    def test_process_success(self, sample_raw_transcript, editor_llm_json, tmp_path):
        """Full EditorAgent.process() with mocked Ollama."""
        with patch("src.agents.editor.OllamaClient") as mock_client:
            mock_client.return_value.chat.return_value = editor_llm_json

            agent = EditorAgent(pipeline_dir=tmp_path / "pipeline")
            output_path = agent.process(sample_raw_transcript)

            assert output_path.exists()
            result = CleanedNote.model_validate_json(output_path.read_text())
            assert result.hive_id == "H07"
            assert result.queen_status == "seen"
            assert result.brood_pattern == "solid"
            assert "Chalkbrood" in result.issues[0]
            assert "Replace frame 4" in result.actions

    def test_process_with_bad_json(self, sample_raw_transcript, tmp_path):
        """Graceful degradation when LLM returns invalid JSON."""
        with patch("src.agents.editor.OllamaClient") as mock_client:
            mock_client.return_value.chat.return_value = "this is not json at all!!!"

            agent = EditorAgent(pipeline_dir=tmp_path / "pipeline")
            output_path = agent.process(sample_raw_transcript)

            result = CleanedNote.model_validate_json(output_path.read_text())
            assert result.hive_id == "H07"
            assert "not json" in result.observations  # fallback: raw text as observations

    def test_ollama_unavailable(self, sample_raw_transcript, tmp_path):
        """EditorAgent raises RuntimeError when Ollama is down."""
        with patch("src.agents.editor.OllamaClient") as mock_client:
            mock_client.return_value.chat.side_effect = ConnectionError("No route to host")

            agent = EditorAgent(pipeline_dir=tmp_path / "pipeline")
            with pytest.raises(RuntimeError, match="EditorAgent needs Ollama"):
                agent.process(sample_raw_transcript)


# ── ExtractorAgent tests ────────────────────────────────────────────────────

class TestExtractorAgent:
    """Tests for ExtractorAgent (cleaned note → structured record)."""

    def test_process_success(self, clean_note_json, extractor_llm_json, tmp_path):
        """Full ExtractorAgent.process() with mocked Ollama."""
        with patch("src.agents.extractor.OllamaClient") as mock_client:
            mock_client.return_value.chat.return_value = extractor_llm_json

            agent = ExtractorAgent(pipeline_dir=tmp_path / "pipeline")
            output_path = agent.process(clean_note_json)

            assert output_path.exists()
            result = StructuredRecord.model_validate_json(output_path.read_text())
            assert result.hive_id == "H07"
            assert result.queen_seen is True
            assert result.mite_count == 3
            assert result.honey_frames == 8
            assert result.severity == "attention"
            assert result.next_inspection_days == 7
            assert "Replace frame 4" in result.actions_required

    def test_process_with_bad_json(self, clean_note_json, tmp_path):
        """Graceful degradation when LLM returns invalid JSON."""
        with patch("src.agents.extractor.OllamaClient") as mock_client:
            mock_client.return_value.chat.return_value = "garbage response"

            agent = ExtractorAgent(pipeline_dir=tmp_path / "pipeline")
            output_path = agent.process(clean_note_json)

            result = StructuredRecord.model_validate_json(output_path.read_text())
            assert result.hive_id == "H07"
            assert "LLM extraction failed" in result.issues[0]

    def test_ollama_unavailable(self, clean_note_json, tmp_path):
        """ExtractorAgent raises RuntimeError when Ollama is down."""
        with patch("src.agents.extractor.OllamaClient") as mock_client:
            mock_client.return_value.chat.side_effect = ConnectionError("No route to host")

            agent = ExtractorAgent(pipeline_dir=tmp_path / "pipeline")
            with pytest.raises(RuntimeError, match="ExtractorAgent needs Ollama"):
                agent.process(clean_note_json)
