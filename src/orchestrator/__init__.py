"""
BuzzBoard Orchestrator — file watcher + pipeline runner.

Watches inbox/ for new voice memos, creates Kanban tasks, and runs
the full agent pipeline automatically.  Designed to run as a long-lived
process (daemon) or as a one-shot "process everything in inbox".

Phase 3: polling-based watcher (cross-platform, no dependencies).
Future: inotify/kqueue/FSEvents for instant detection.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from ..agents.transcriber import TranscriberAgent
from ..agents.editor import EditorAgent
from ..agents.extractor import ExtractorAgent
from ..agents.storage import StorageAgent
from ..db.kanban import KanbanBoard
from ..schema import RawTranscript


class Orchestrator:
    """
    Watches inbox/ and runs the full pipeline on new voice memos.

    Usage:
        orch = Orchestrator(
            inbox_dir="inbox",
            obsidian_vault=Path("/Users/andrey/Documents/Obsidian"),
        )
        orch.run_once()   # Process all pending files, then exit
        orch.watch()      # Run forever, polling for new files
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

    # ── Public API ──────────────────────────────────────────────────────────

    def run_once(self) -> dict:
        """
        Process all unprocessed files in inbox/, then exit.

        Returns a summary dict:
            {"processed": N, "failed": N, "skipped": N, "tasks": [...]}
        """
        files = self._find_new_files()
        if not files:
            print("📭 No new files in inbox/")
            return {"processed": 0, "failed": 0, "skipped": 0, "tasks": []}

        print(f"🐝 BuzzBoard processing {len(files)} file(s)...\n")

        results = {"processed": 0, "failed": 0, "skipped": 0, "tasks": []}
        for audio_path in files:
            try:
                task_result = self._process_one(audio_path)
                if task_result.get("status") == "done":
                    results["processed"] += 1
                else:
                    results["failed"] += 1
                results["tasks"].append(task_result)
            except Exception as e:
                print(f"  ❌ Unexpected error on {audio_path.name}: {e}")
                results["failed"] += 1
                results["tasks"].append({"file": audio_path.name, "status": "error", "error": str(e)})

        # Summary
        print(f"\n{'═' * 50}")
        print(f"📊 Run complete: {results['processed']} done, "
              f"{results['failed']} failed, {results['skipped']} skipped")
        print(self.board.print_board())
        return results

    def watch(self, poll_interval: float = 5.0):
        """
        Run forever, polling for new files every poll_interval seconds.
        Press Ctrl+C to stop.
        """
        print(f"👁️  BuzzBoard watching {self.inbox.absolute()} (polling every {poll_interval}s)")
        print("   Press Ctrl+C to stop.\n")

        try:
            while True:
                files = self._find_new_files()
                for audio_path in files:
                    self._process_one(audio_path)
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\n👋 BuzzBoard shutting down.")
            print(self.board.print_board())

    # ── Pipeline runner ─────────────────────────────────────────────────────

    def _process_one(self, audio_path: Path) -> dict:
        """Run the full pipeline on a single audio file."""
        print(f"\n{'─' * 66}")
        print(f"📥 {audio_path.name}")
        print(f"{'─' * 66}")

        # Parse filename for hive_id + date
        try:
            hive_id, insp_date = RawTranscript.parse_filename(audio_path)
        except ValueError as e:
            print(f"  ❌ Skipping — {e}")
            self._processed.add(audio_path.name)
            return {"file": audio_path.name, "status": "skipped", "error": str(e)}

        task_id = f"{hive_id}_{insp_date.isoformat()}"
        self.board.create_task(task_id, hive_id, audio_path.name)

        try:
            # Stage 1: Transcribe
            self._run_stage(task_id, "transcribing", "transcriber", lambda: (
                TranscriberAgent(
                    backend=self.whisper_backend,
                    model=self.whisper_model,
                    pipeline_dir=self.pipeline_dir,
                ).process(audio_path)
            ))

            # Find the raw transcript path
            raw_paths = sorted(self.pipeline_dir.glob("rawtranscript_*.json"),
                               key=lambda p: p.stat().st_mtime, reverse=True)
            raw_path = raw_paths[0] if raw_paths else None
            if not raw_path:
                raise FileNotFoundError("Transcriber did not produce output")

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
            self._move_to_archive(audio_path)
            self._processed.add(audio_path.name)

            print(f"  ✅ Done: {task_id}")
            return {"file": audio_path.name, "task_id": task_id, "status": "done"}

        except Exception as e:
            self.board.fail_task(task_id, str(e))
            self.board.log_event(task_id, "orchestrator", "failed", details=str(e)[:500])
            print(f"  ❌ Failed: {e}")
            return {"file": audio_path.name, "task_id": task_id, "status": "failed", "error": str(e)[:200]}

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

    def _find_new_files(self) -> list[Path]:
        """Find audio files in inbox/ that haven't been processed yet."""
        files = []
        for ext in self.AUDIO_EXTENSIONS:
            for f in self.inbox.glob(f"*{ext}"):
                if f.name not in self._processed:
                    # Also skip files that already have a task in the board
                    try:
                        hive_id, insp_date = RawTranscript.parse_filename(f)
                        task_id = f"{hive_id}_{insp_date.isoformat()}"
                        existing = self.board.get_task(task_id)
                        if existing and existing["stage"] in ("done", "failed"):
                            self._processed.add(f.name)
                            continue
                    except ValueError:
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
