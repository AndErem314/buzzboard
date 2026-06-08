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
from src.agents.trend import TrendAgent
from src.schema import CleanedNote, RawTranscript, StructuredRecord, TrendReport


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


# ── TrendAgent tests ────────────────────────────────────────────────────────

@pytest.fixture
def single_record_dir(tmp_path: Path) -> Path:
    """Create a directory with one StructuredRecord JSON artifact."""
    records_dir = tmp_path / "records"
    records_dir.mkdir()
    record = StructuredRecord(
        hive_id="H07",
        inspection_date=date(2026, 6, 6),
        queen_seen=True,
        brood_health="chalkbrood",
        mite_count=3,
        honey_frames=8,
        issues=["Chalkbrood in frame 4"],
        actions_required=["Replace frame 4", "Recheck in 7 days"],
        next_inspection_days=7,
        severity="attention",
    )
    out_path = records_dir / "record_2026-06-06.json"
    out_path.write_text(record.model_dump_json(indent=2))
    return records_dir


@pytest.fixture
def multi_record_dir(tmp_path: Path) -> Path:
    """Create a directory with 3 StructuredRecord JSON artifacts."""
    records_dir = tmp_path / "records"
    records_dir.mkdir()

    inspections = [
        StructuredRecord(
            hive_id="H07",
            inspection_date=date(2026, 5, 15),
            queen_seen=True,
            brood_health="healthy",
            mite_count=1,
            honey_frames=10,
            issues=[],
            actions_required=[],
            severity="normal",
        ),
        StructuredRecord(
            hive_id="H07",
            inspection_date=date(2026, 5, 22),
            queen_seen=True,
            brood_health="healthy",
            mite_count=2,
            honey_frames=9,
            issues=["Few varroa on bottom board"],
            actions_required=["Monitor mites"],
            severity="normal",
        ),
        StructuredRecord(
            hive_id="H07",
            inspection_date=date(2026, 6, 6),
            queen_seen=True,
            brood_health="chalkbrood",
            mite_count=5,
            honey_frames=6,
            issues=["Chalkbrood in frame 4", "Mite count elevated"],
            actions_required=["Replace frame 4", "Consider mite treatment", "Recheck in 7 days"],
            next_inspection_days=7,
            severity="attention",
        ),
    ]
    for insp in inspections:
        fname = f"record_{insp.inspection_date.isoformat()}.json"
        (records_dir / fname).write_text(insp.model_dump_json(indent=2))
    return records_dir


@pytest.fixture
def trend_llm_json() -> str:
    """Valid JSON the TrendAgent LLM would return."""
    return json.dumps({
        "hive_id": "H07",
        "inspections_analyzed": 3,
        "date_range_first": "2026-05-15",
        "date_range_last": "2026-06-06",
        "summary": "H07 is generally healthy but showing concerning trends. "
                   "Mite counts have risen from 1 to 5 across three inspections, "
                   "and chalkbrood appeared in the most recent check. "
                   "Honey stores dropped from 10 to 6 frames.",
        "queen_performance": "Queen consistently seen across all 3 inspections. "
                            "Brood pattern solid in first two inspections. "
                            "Laying pattern appears stable.",
        "mite_trajectory": "Rising: 1 → 2 → 5 across 3 inspections. "
                          "Rate of increase is accelerating — from +1/week to +3 in two weeks. "
                          "Currently above treatment threshold.",
        "honey_trend": "Declining: 10 → 9 → 6 frames. A 40% drop over 3 weeks. "
                      "May reflect seasonal flow ending or colony stress from mites.",
        "recurring_issues": ["Mite presence increasing across all inspections"],
        "swarm_risk": "low — no queen cells, no congestion indicators. "
                     "Temperament calm throughout.",
        "recommendations": [
            "Apply mite treatment immediately (count exceeds threshold of 3)",
            "Replace frame 4 permanently to eliminate chalkbrood reservoir",
            "Supplement feed if honey continues to decline",
            "Re-inspect in 5 days to verify treatment efficacy",
        ],
        "overall_severity": "attention",
    })


class TestTrendAgent:
    """Tests for TrendAgent (multiple records → trend analysis)."""

    def test_single_inspection(self, single_record_dir, trend_llm_json, tmp_path):
        """TrendAgent works with a single record (limited but valid)."""
        with patch("src.agents.trend.OllamaClient") as mock_client:
            mock_client.return_value.chat.return_value = trend_llm_json

            agent = TrendAgent(pipeline_dir=tmp_path / "pipeline")
            output_path = agent.process(single_record_dir)

            assert output_path.exists()
            result = TrendReport.model_validate_json(output_path.read_text())
            assert result.hive_id == "H07"
            assert result.inspections_analyzed > 0
            assert result.overall_severity in ("normal", "attention", "urgent")

    def test_multiple_inspections(self, multi_record_dir, trend_llm_json, tmp_path):
        """TrendAgent identifies patterns across multiple records."""
        with patch("src.agents.trend.OllamaClient") as mock_client:
            mock_client.return_value.chat.return_value = trend_llm_json

            agent = TrendAgent(pipeline_dir=tmp_path / "pipeline")
            output_path = agent.process(multi_record_dir)

            assert output_path.exists()
            result = TrendReport.model_validate_json(output_path.read_text())
            assert result.hive_id == "H07"
            assert result.inspections_analyzed == 3
            assert "rising" in result.mite_trajectory.lower() or "rising" in result.summary.lower()
            assert len(result.recommendations) > 0

    def test_bad_json_fallback(self, multi_record_dir, tmp_path):
        """TrendAgent falls back to data-driven report when LLM returns garbage."""
        with patch("src.agents.trend.OllamaClient") as mock_client:
            mock_client.return_value.chat.return_value = "not valid json at all!!!"

            agent = TrendAgent(pipeline_dir=tmp_path / "pipeline")
            output_path = agent.process(multi_record_dir)

            assert output_path.exists()
            result = TrendReport.model_validate_json(output_path.read_text())
            assert result.hive_id == "H07"
            assert result.inspections_analyzed == 3
            # Fallback should still compute basic trends
            assert result.mite_trajectory != ""
            assert result.overall_severity == "attention"

    def test_fallback_recurring_issues(self, multi_record_dir, tmp_path):
        """Fallback report detects recurring issues from raw data."""
        with patch("src.agents.trend.OllamaClient") as mock_client:
            mock_client.return_value.chat.return_value = "garbage"

            agent = TrendAgent(pipeline_dir=tmp_path / "pipeline")
            output_path = agent.process(multi_record_dir)

            result = TrendReport.model_validate_json(output_path.read_text())
            assert result.inspections_analyzed == 3
            # Mite count 1→2→5 = rising
            assert "rising" in result.mite_trajectory
            assert result.overall_severity == "attention"

    def test_ollama_unavailable(self, multi_record_dir, tmp_path):
        """TrendAgent raises RuntimeError when Ollama is down."""
        with patch("src.agents.trend.OllamaClient") as mock_client:
            mock_client.return_value.chat.side_effect = ConnectionError("No route to host")

            agent = TrendAgent(pipeline_dir=tmp_path / "pipeline")
            with pytest.raises(RuntimeError, match="TrendAgent needs Ollama"):
                agent.process(multi_record_dir)

    def test_no_records_found(self, tmp_path):
        """TrendAgent raises FileNotFoundError when no records exist."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch("src.agents.trend.OllamaClient"):  # shouldn't be reached
            agent = TrendAgent(pipeline_dir=tmp_path / "pipeline")
            with pytest.raises(FileNotFoundError, match="No record_.*"):
                agent.process(empty_dir)
