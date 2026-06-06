"""
Tests for Phase 3: StorageAgent, KanbanBoard, Orchestrator.
"""

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.agents.storage import StorageAgent
from src.db.kanban import KanbanBoard
from src.schema import CleanedNote, RawTranscript, StructuredRecord


# ── KanbanBoard tests ──────────────────────────────────────────────────────

class TestKanbanBoard:
    """Tests for the SQLite-backed Kanban engine."""

    @pytest.fixture
    def board(self, tmp_path: Path) -> KanbanBoard:
        db_path = tmp_path / "kanban.db"
        return KanbanBoard(db_path)

    def test_create_and_get_task(self, board):
        board.create_task("H07_2026-06-06", "H07", "H07_2026-06-06.m4a")
        task = board.get_task("H07_2026-06-06")
        assert task is not None
        assert task["hive_id"] == "H07"
        assert task["stage"] == "inbox"

    def test_move_through_pipeline(self, board):
        board.create_task("H07_2026-06-06", "H07", "test.m4a")
        stages = ["transcribing", "editing", "extracting", "storing", "done"]
        for stage in stages:
            board.move_to("H07_2026-06-06", stage)
            task = board.get_task("H07_2026-06-06")
            assert task["stage"] == stage

        task = board.get_task("H07_2026-06-06")
        assert task["completed_at"] is not None

    def test_fail_task(self, board):
        board.create_task("H07_2026-06-06", "H07", "test.m4a")
        board.fail_task("H07_2026-06-06", "Ollama connection refused")
        task = board.get_task("H07_2026-06-06")
        assert task["stage"] == "failed"
        assert "Ollama connection refused" in task["error"]

    def test_event_log(self, board):
        board.create_task("H07_2026-06-06", "H07", "test.m4a")
        board.log_event("H07_2026-06-06", "transcriber", "started")
        board.log_event("H07_2026-06-06", "transcriber", "completed",
                        input_hash="abc", output_hash="def", duration_ms=1500.0)

        events = board.get_events("H07_2026-06-06")
        assert len(events) == 2
        assert events[0]["agent"] == "transcriber"
        assert events[0]["action"] == "started"
        assert events[1]["duration_ms"] == 1500.0

    def test_stats(self, board):
        board.create_task("H07_2026-06-06", "H07", "a.m4a")
        board.create_task("H12_2026-06-06", "H12", "b.m4a")
        board.move_to("H07_2026-06-06", "done")

        stats = board.get_stats()
        assert stats["total_tasks"] == 2
        assert stats["by_stage"].get("done") == 1
        assert stats["by_stage"].get("inbox") == 1

    def test_get_tasks_by_stage(self, board):
        board.create_task("T1", "H07", "a.m4a")
        board.create_task("T2", "H12", "b.m4a")
        board.move_to("T1", "done")

        done = board.get_tasks_by_stage("done")
        inbox = board.get_tasks_by_stage("inbox")
        assert len(done) == 1
        assert len(inbox) == 1

    def test_hive_history(self, board):
        board.create_task("H07_2026-05-30", "H07", "old.m4a")
        board.create_task("H07_2026-06-06", "H07", "new.m4a")
        board.move_to("H07_2026-06-06", "done")

        history = board.get_hive_history("H07")
        assert len(history) == 2
        assert history[0]["id"] == "H07_2026-06-06"  # newest first

    def test_duplicate_task_ignored(self, board):
        board.create_task("H07_2026-06-06", "H07", "test.m4a")
        board.create_task("H07_2026-06-06", "H07", "test.m4a")  # duplicate
        assert board.get_stats()["total_tasks"] == 1


# ── StorageAgent tests ─────────────────────────────────────────────────────

class TestStorageAgent:
    """Tests for the Obsidian vault writer."""

    @pytest.fixture
    def mock_vault(self, tmp_path: Path) -> Path:
        vault = tmp_path / "Obsidian"
        vault.mkdir()
        (vault / "Hives").mkdir()
        return vault

    @pytest.fixture
    def sample_record(self, tmp_path: Path) -> Path:
        """Create a StructuredRecord JSON artifact."""
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
        out = tmp_path / "structuredrecord_test.json"
        out.write_text(record.model_dump_json(indent=2))
        return out

    @pytest.fixture
    def sample_cleaned_note(self, tmp_path: Path) -> Path:
        """Create a matching CleanedNote in the same dir."""
        import shutil
        note = CleanedNote(
            hive_id="H07",
            inspection_date=date(2026, 6, 6),
            observations="Queen spotted. Brood solid. Chalkbrood in frame 4.",
            issues=["Chalkbrood in frame 4"],
            actions=["Replace frame 4", "Recheck in 7 days"],
            queen_status="seen",
            brood_pattern="solid",
            honey_stores="abundant",
            pollen_stores="adequate",
            temperament="calm",
            raw_reference="abc123",
        )
        out = tmp_path / "cleanednote_test.json"
        out.write_text(note.model_dump_json(indent=2))
        return out

    def test_writes_note_file(self, mock_vault, sample_record, sample_cleaned_note):
        """StorageAgent writes a hive inspection .md file."""
        agent = StorageAgent(obsidian_vault=mock_vault)
        result = agent.process(sample_record)

        assert result.exists()
        assert result.suffix == ".md"
        content = result.read_text()
        assert "# 🐝 Hive H07" in content
        assert "2026-06-06" in content
        assert "Chalkbrood" in content
        assert "Replace frame 4" in content

    def test_creates_index_file(self, mock_vault, sample_record, sample_cleaned_note):
        """StorageAgent creates/updates the hive index."""
        agent = StorageAgent(obsidian_vault=mock_vault)
        agent.process(sample_record)

        index_path = mock_vault / "Hives" / "H07" / "H07_Index.md"
        assert index_path.exists()
        content = index_path.read_text()
        assert "# 🐝 Hive H07 — Inspection Log" in content
        assert "2026-06-06" in content

    def test_organizes_by_hive(self, mock_vault, sample_record, sample_cleaned_note):
        """Notes are placed in Hives/H{NN}/ directory."""
        agent = StorageAgent(obsidian_vault=mock_vault)
        agent.process(sample_record)

        hive_dir = mock_vault / "Hives" / "H07"
        assert hive_dir.is_dir()
        assert (hive_dir / "2026-06-06.md").exists()

    def test_frontmatter_present(self, mock_vault, sample_record, sample_cleaned_note):
        """Output .md has Dataview-compatible YAML frontmatter."""
        agent = StorageAgent(obsidian_vault=mock_vault)
        result = agent.process(sample_record)
        content = result.read_text()

        assert content.startswith("---")
        assert "hive_id:" in content
        assert "queen_seen:" in content
        assert "mite_count:" in content
        assert "tags:" in content

    def test_nonexistent_vault_raises(self):
        """StorageAgent raises FileNotFoundError for nonexistent vault."""
        with pytest.raises(FileNotFoundError):
            StorageAgent(obsidian_vault=Path("/nonexistent/vault"))


# ── RawTranscript filename parsing tests ──────────────────────────────────

class TestFilenameParsing:
    """Tests for RawTranscript.parse_filename()."""

    def test_standard_format(self):
        hive_id, insp_date = RawTranscript.parse_filename(
            Path("H07_2026-06-06.m4a")
        )
        assert hive_id == "H07"
        assert insp_date == date(2026, 6, 6)

    def test_with_timestamp(self):
        hive_id, insp_date = RawTranscript.parse_filename(
            Path("H12_2026-06-06_1430.m4a")
        )
        assert hive_id == "H12"
        assert insp_date == date(2026, 6, 6)

    def test_mp3_format(self):
        hive_id, insp_date = RawTranscript.parse_filename(
            Path("H03_2025-12-25.mp3")
        )
        assert hive_id == "H03"
        assert insp_date == date(2025, 12, 25)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Cannot parse filename"):
            RawTranscript.parse_filename(Path("bad_file.m4a"))

    def test_missing_date_raises(self):
        with pytest.raises(ValueError, match="Cannot parse filename"):
            RawTranscript.parse_filename(Path("H07_something.m4a"))
