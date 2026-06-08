"""
BuzzBoard Orchestrator — file watcher + pipeline runner.

Watches inbox/ for new voice memos, creates Kanban tasks, and runs
the full agent pipeline automatically.  Designed to run as a long-lived
process (daemon) or as a one-shot "process everything in inbox".

Phase 3: polling-based watcher (cross-platform, no dependencies).
Phase 8: multi-hive support via HiveSplitterAgent.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..agents.transcriber import TranscriberAgent
from ..agents.splitter import HiveSplitterAgent
from ..agents.editor import EditorAgent
from ..agents.extractor import ExtractorAgent
from ..agents.storage import StorageAgent
from ..db.kanban import KanbanBoard
from ..schema import RawTranscript


class Orchestrator:
    """
    Watches inbox/ and runs the full pipeline on new voice memos.

    Supports both single-hive (H07_YYYY-MM-DD.m4a) and multi-hive
    (any filename) voice memos. Multi-hive files are split into
    per-hive transcripts before processing.

    Usage:
        orch = Orchestrator(
            inbox_dir="inbox",
            obsidian_vault=Path("/Users/andrey/Documents/Obsidian"),
        )
        orch.run_once()                  # Process all pending files
        orch.run_once(recent_only=True)  # Only files from last 24h
        orch.watch()                     # Run forever, polling for new files
    """

    AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".webm", ".aac"}

    def __init__(
        self,
        inbox_dir: Path | str = "inbox",
        obsidian_vault: Optional[Path] = None,
        ollama_model: str = "llama3.1:8b",
        ollama_host: str = "http://localhost:11434",
        whisper_backend: str = "whisper",
        whisper_model: str = "base",
        pipeline_dir: Path | str = "pipeline",
        kanban_db: Path | str = "pipeline/kanban.db",
    ):
        self.inbox = Path(inbox_dir)
        self.obsidian_vault = Path(obsidian_vault) if obsidian_vault else None
        self.ollama_model = ollama_model
        self.ollama_host = ollama_host
        self.whisper_backend = whisper_backend
        self.whisper_model = whisper_model
        self.pipeline_dir = Path(pipeline_dir)
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)

        self.board = KanbanBoard(kanban_db)
        self._processed: set[str] = set()
        self._last_run: Optional[datetime] = None

    # ── Public API ──────────────────────────────────────────────────────────

    def run_once(self, recent_only: bool = False,
                 recent_hours: float = 24.0) -> dict:
        """
        Process all unprocessed files in inbox/, then exit.

        Args:
            recent_only: Only process files modified within recent_hours.
            recent_hours: Time window in hours for recent_only mode.

        Returns a summary dict:
            {"processed": N, "failed": N, "skipped": N, "tasks": [...]}
        """
        self._last_run = datetime.now()
        files = self._find_new_files(recent_only=recent_only,
                                     recent_hours=recent_hours)
        if not files:
            print("📭 No new files in inbox/")
            return {"processed": 0, "failed": 0, "skipped": 0, "tasks": []}

        print(f"🐝 BuzzBoard processing {len(files)} file(s)...\n")

        results = {"processed": 0, "failed": 0, "skipped": 0, "tasks": []}
        for audio_path in files:
            try:
                task_results = self._process_one(audio_path)
                # _process_one returns a list of per-hive results for multi-hive
                for tr in task_results:
                    if tr.get("status") == "done":
                        results["processed"] += 1
                    else:
                        results["failed"] += 1
                    results["tasks"].append(tr)
            except Exception as e:
                print(f"  ❌ Unexpected error on {audio_path.name}: {e}")
                results["failed"] += 1
                results["tasks"].append({
                    "file": audio_path.name, "status": "error", "error": str(e)
                })

        # Summary
        print(f"\n{'═' * 50}")
        print(f"📊 Run complete: {results['processed']} done, "
              f"{results['failed']} failed, {results['skipped']} skipped")
        print(self.board.print_board())
        return results

    def watch(self, poll_interval: float = 5.0, recent_only: bool = True):
        """
        Run forever, polling for new files every poll_interval seconds.
        With recent_only=True, only processes files added since last poll
        (avoids re-processing old files on restart).

        Press Ctrl+C to stop.
        """
        mode = "recent-only" if recent_only else "all pending"
        print(f"👁️  BuzzBoard watching {self.inbox.absolute()} "
              f"(polling every {poll_interval}s, {mode})")
        print("   Press Ctrl+C to stop.\n")

        self._last_run = datetime.now()

        try:
            while True:
                files = self._find_new_files(recent_only=recent_only)
                for audio_path in files:
                    self._process_one(audio_path)
                self._last_run = datetime.now()
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\n👋 BuzzBoard shutting down.")
            print(self.board.print_board())

    # ── Pipeline runner ─────────────────────────────────────────────────────

    def _process_one(self, audio_path: Path) -> list[dict]:
        """
        Run the full pipeline on a single audio file.

        For multi-hive files: Transcriber → Splitter → (Editor → Extractor → Storage) × N
        For single-hive files: Transcriber → Editor → Extractor → Storage

        Returns a list of per-hive result dicts.
        """
        print(f"\n{'─' * 66}")
        print(f"📥 {audio_path.name}")
        print(f"{'─' * 66}")

        # ── Stage 1: Transcribe (always) ────────────────────────────────
        try:
            transcriber = TranscriberAgent(
                backend=self.whisper_backend,
                model=self.whisper_model,
                pipeline_dir=self.pipeline_dir,
            )
            raw_path, is_multi_hive = transcriber.process(audio_path)
        except FileNotFoundError as e:
            print(f"  ❌ Transcriber failed: {e}")
            self._processed.add(audio_path.name)
            return [{"file": audio_path.name, "status": "skipped", "error": str(e)}]

        # ── Branch: multi-hive or single-hive? ──────────────────────────
        if is_multi_hive:
            return self._process_multi_hive(audio_path, raw_path)
        else:
            result = self._process_single_hive(audio_path, raw_path)
            return [result]

    def _process_multi_hive(self, audio_path: Path, raw_path: Path) -> list[dict]:
        """Split a multi-hive transcript, then process each hive independently."""
        print(f"\n  🔀 Multi-hive detected — running HiveSplitter...")

        # Stage 2: Split into per-hive transcripts
        try:
            splitter = HiveSplitterAgent(
                ollama_model=self.ollama_model,
                ollama_host=self.ollama_host,
                pipeline_dir=self.pipeline_dir,
            )
            hive_paths = splitter.process(raw_path)
        except (RuntimeError, ValueError) as e:
            print(f"  ❌ HiveSplitter failed: {e}")
            return [{"file": audio_path.name, "status": "failed", "error": str(e)}]

        # Process each hive through Editor → Extractor → Storage
        results = []
        for hive_path in hive_paths:
            result = self._process_single_hive(audio_path, hive_path,
                                                parent_task=True)
            results.append(result)

        # Archive the original multi-hive audio
        self._move_to_archive(audio_path)
        self._processed.add(audio_path.name)

        return results

    def _process_single_hive(self, audio_path: Path, raw_path: Path,
                             parent_task: bool = False) -> dict:
        """
        Run Editor → Extractor → Storage on a single-hive RawTranscript.

        Args:
            audio_path: Original audio file (for Kanban tracking)
            raw_path: Path to RawTranscript JSON artifact
            parent_task: If True, this is a sub-task of a multi-hive split
        """
        # Parse hive_id and date from the artifact for task tracking
        raw_data = BuzzAgentShim.load_json(raw_path)
        hive_id = raw_data.get("hive_id", "unknown")
        insp_date = raw_data.get("inspection_date", "unknown")

        task_id = f"{hive_id}_{insp_date}"

        # For multi-hive sub-tasks, don't create duplicate tasks
        existing = self.board.get_task(task_id)
        if existing and existing["stage"] in ("done",):
            print(f"  ⏭️  {task_id} already processed — skipping")
            return {"file": audio_path.name, "task_id": task_id, "status": "skipped"}

        if not existing:
            self.board.create_task(task_id, hive_id, audio_path.name)

        prefix = "     " if parent_task else "  "
        print(f"\n{prefix}🐝 Processing {task_id}...")

        try:
            # Stage 2: Editor
            cleaned_path = self._run_stage(task_id, "editing", "editor", lambda: (
                EditorAgent(
                    ollama_model=self.ollama_model,
                    ollama_host=self.ollama_host,
                    pipeline_dir=self.pipeline_dir,
                ).process(raw_path)
            ))

            # Stage 3: Extractor
            record_paths = sorted(self.pipeline_dir.glob("cleanednote_*.json"),
                                  key=lambda p: p.stat().st_mtime, reverse=True)
            cleaned_path = record_paths[0] if record_paths else cleaned_path

            record_path = self._run_stage(task_id, "extracting", "extractor", lambda: (
                ExtractorAgent(
                    ollama_model=self.ollama_model,
                    ollama_host=self.ollama_host,
                    pipeline_dir=self.pipeline_dir,
                ).process(cleaned_path)
            ))

            # Stage 4: Storage
            if self.obsidian_vault:
                record_paths2 = sorted(self.pipeline_dir.glob("structuredrecord_*.json"),
                                       key=lambda p: p.stat().st_mtime, reverse=True)
                record_path = record_paths2[0] if record_paths2 else record_path

                self._run_stage(task_id, "storing", "storage", lambda: (
                    StorageAgent(
                        obsidian_vault=self.obsidian_vault,
                        pipeline_dir=self.pipeline_dir,
                    ).process(record_path)
                ))

            # Mark done
            self.board.move_to(task_id, "done")

            # Only archive the audio if this is NOT a sub-task
            # (multi-hive audio is archived by the parent)
            if not parent_task:
                self._move_to_archive(audio_path)
                self._processed.add(audio_path.name)

            print(f"{prefix}  ✅ Done: {task_id}")
            return {"file": audio_path.name, "task_id": task_id, "status": "done"}

        except Exception as e:
            self.board.fail_task(task_id, str(e))
            self.board.log_event(task_id, "orchestrator", "failed", details=str(e)[:500])
            print(f"{prefix}  ❌ Failed: {e}")
            return {"file": audio_path.name, "task_id": task_id, "status": "failed",
                    "error": str(e)[:200]}

    def _run_stage(self, task_id: str, stage: str, agent_name: str, fn) -> Path:
        """Run one pipeline stage with Kanban tracking."""
        self.board.move_to(task_id, stage)

        start = time.perf_counter()
        self.board.log_event(task_id, agent_name, "started")

        try:
            result = fn()
            elapsed = (time.perf_counter() - start) * 1000
            self.board.log_event(task_id, agent_name, "completed", duration_ms=elapsed)
            return result
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            self.board.log_event(
                task_id, agent_name, "failed",
                duration_ms=elapsed, details=str(e)[:500],
            )
            raise

    # ── File management ─────────────────────────────────────────────────────

    def _find_new_files(self, recent_only: bool = False,
                        recent_hours: float = 24.0) -> list[Path]:
        """
        Find audio files in inbox/ that haven't been processed yet.

        Args:
            recent_only: Only return files modified since last poll
                         (or within recent_hours on first run).
            recent_hours: Time window for "recent" files.
        """
        cutoff = None
        if recent_only:
            if self._last_run:
                cutoff = self._last_run - timedelta(seconds=10)  # small buffer
            else:
                cutoff = datetime.now() - timedelta(hours=recent_hours)

        files = []
        for ext in self.AUDIO_EXTENSIONS:
            for f in self.inbox.glob(f"*{ext}"):
                if f.name in self._processed:
                    continue

                # Timestamp filtering: skip old files in recent_only mode
                if cutoff:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        continue

                # Check if already in Kanban as done/failed
                try:
                    hive_id, insp_date = RawTranscript.parse_filename(f)
                    task_id = f"{hive_id}_{insp_date.isoformat()}"
                    existing = self.board.get_task(task_id)
                    if existing and existing["stage"] in ("done", "failed"):
                        self._processed.add(f.name)
                        continue
                except ValueError:
                    # Generic filename — can't check Kanban by hive,
                    # but if already processed, it's in _processed
                    pass

                files.append(f)

        return sorted(files, key=lambda p: p.stat().st_mtime)

    def _move_to_archive(self, audio_path: Path):
        """Move processed audio to archive/."""
        archive_dir = Path("archive")
        archive_dir.mkdir(exist_ok=True)
        dest = archive_dir / audio_path.name
        # Avoid overwriting
        if dest.exists():
            dest = archive_dir / f"{audio_path.stem}_{int(time.time())}{audio_path.suffix}"
        audio_path.rename(dest)


class BuzzAgentShim:
    """Minimal shim so _process_single_hive can read JSON without importing BuzzAgent."""
    @staticmethod
    def load_json(path: Path) -> dict:
        import json as _json
        return _json.loads(path.read_text())
