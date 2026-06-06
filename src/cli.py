"""
BuzzBoard CLI — the single entry point for the multi-agent pipeline.

Usage:
    buzzboard transcribe inbox/H07_2026-06-06.m4a    # Voice → text only
    buzzboard process inbox/H07_2026-06-06.m4a        # Full pipeline
    buzzboard watch                                     # Auto-process inbox/
    buzzboard status                                    # Show Kanban board
    buzzboard board                                     # Kanban board detail
"""

from __future__ import annotations

from pathlib import Path

import click

from .agents.transcriber import TranscriberAgent
from .agents.editor import EditorAgent
from .agents.extractor import ExtractorAgent
from .agents.storage import StorageAgent
from .orchestrator import Orchestrator
from .db.kanban import KanbanBoard
from . import config as cfg


@click.group()
@click.version_option(package_name="buzzboard", message="BuzzBoard %(version)s 🐝")
def cli():
    """BuzzBoard — multi-agent beehive inspection assistant.

    Drop voice memos in inbox/, let the agents do the rest.
    Structured Obsidian notes appear in your vault, organized by hive.
    """
    pass


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--backend", default="whisper", type=click.Choice(["whisper", "whisper-cpp"]),
    help="Speech-to-text backend (default: whisper)"
)
@click.option(
    "--model", default="base",
    help="Whisper model size: tiny, base, small, medium, large"
)
@click.option(
    "--output-dir", default="pipeline", type=click.Path(path_type=Path),
    help="Directory for pipeline artifacts"
)
def transcribe(
    audio_file: Path,
    backend: str,
    model: str,
    output_dir: Path,
):
    """Transcribe a single voice memo to raw text."""
    agent = TranscriberAgent(
        backend=backend,
        model=model,
        pipeline_dir=output_dir,
    )
    try:
        output_path = agent.process(audio_file)
        click.echo(f"\n✅ Done: {output_path}")
    except ValueError as e:
        click.echo(f"❌ Filename error: {e}", err=True)
        raise SystemExit(1)
    except FileNotFoundError as e:
        click.echo(f"❌ {e}", err=True)
        raise SystemExit(1)


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option("--backend", default="whisper", type=click.Choice(["whisper", "whisper-cpp"]))
@click.option("--whisper-model", default="base", help="Whisper model size")
@click.option("--output-dir", default="pipeline", type=click.Path(path_type=Path))
@click.option(
    "--ollama-model", default="llama3.1:8b",
    help="Ollama model for Editor + Extractor agents"
)
@click.option(
    "--ollama-host", default="http://localhost:11434",
    help="Ollama API host"
)
@click.option("--skip-transcribe", is_flag=True, help="Skip transcription (use existing raw JSON)")
@click.option(
    "--obsidian-vault", default=None, type=click.Path(path_type=Path),
    help="Path to Obsidian vault for Storage agent (default: $BUZZBOARD_OBSIDIAN_VAULT)"
)
def process(
    audio_file: Path,
    backend: str,
    whisper_model: str,
    output_dir: Path,
    ollama_model: str,
    ollama_host: str,
    skip_transcribe: bool,
    obsidian_vault: Path | None,
):
    """Run the full BuzzBoard pipeline on a voice memo.

    Pipeline:  Transcriber → Editor → Extractor → Storage
    """
    # Resolve Obsidian vault: CLI arg > env var
    if obsidian_vault is None:
        obsidian_vault = cfg.OBSIDIAN_VAULT

    click.echo(f"🐝 BuzzBoard processing: {audio_file.name}\n")

    # ── Stage 1: Transcribe ─────────────────────────────────────────────
    click.echo("─" * 50)
    click.echo("Stage 1/4:  Transcriber (Whisper)")
    click.echo("─" * 50)
    click.echo()

    if skip_transcribe:
        raw_path = audio_file
        click.echo(f"  ⏭️  Skipping — using existing artifact: {raw_path}")
    else:
        transcriber = TranscriberAgent(
            backend=backend, model=whisper_model, pipeline_dir=output_dir
        )
        try:
            raw_path = transcriber.process(audio_file)
        except (ValueError, FileNotFoundError) as e:
            click.echo(f"❌ Transcriber failed: {e}", err=True)
            raise SystemExit(1)

    # ── Stage 2: Editor ─────────────────────────────────────────────────
    click.echo(f"\n{'─' * 50}")
    click.echo("Stage 2/4:  Editor (LLM)")
    click.echo("─" * 50)
    click.echo()

    try:
        editor = EditorAgent(
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            pipeline_dir=output_dir,
        )
        cleaned_path = editor.process(raw_path)
    except RuntimeError as e:
        click.echo(f"❌ Editor failed: {e}", err=True)
        raise SystemExit(1)

    # ── Stage 3: Extractor ──────────────────────────────────────────────
    click.echo(f"\n{'─' * 50}")
    click.echo("Stage 3/4:  Extractor (LLM)")
    click.echo("─" * 50)
    click.echo()

    try:
        extractor = ExtractorAgent(
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            pipeline_dir=output_dir,
        )
        record_path = extractor.process(cleaned_path)
    except RuntimeError as e:
        click.echo(f"❌ Extractor failed: {e}", err=True)
        raise SystemExit(1)

    # ── Stage 4: Storage ────────────────────────────────────────────────
    click.echo(f"\n{'─' * 50}")
    click.echo("Stage 4/4:  Storage (Obsidian)")
    click.echo("─" * 50)
    click.echo()

    if obsidian_vault:
        try:
            storage = StorageAgent(
                obsidian_vault=obsidian_vault,
                pipeline_dir=output_dir,
            )
            note_path = storage.process(record_path)
            click.echo(f"  ✅ Wrote to Obsidian: {note_path}")
        except (FileNotFoundError, RuntimeError) as e:
            click.echo(f"❌ Storage failed: {e}", err=True)
            raise SystemExit(1)
    else:
        click.echo("  ⏭️  Skipping — no Obsidian vault specified (use --obsidian-vault)")

    # ── Summary ─────────────────────────────────────────────────────────
    click.echo(f"\n{'═' * 50}")
    click.echo(f"✅ Pipeline complete ({4 if obsidian_vault else 3}/4 stages)")
    click.echo(f"{'═' * 50}")
    click.echo(f"  Raw transcript:  {raw_path}")
    click.echo(f"  Cleaned note:    {cleaned_path}")
    click.echo(f"  Structured data: {record_path}")
    if obsidian_vault:
        click.echo(f"  Obsidian note:   {note_path}")
    click.echo()


@cli.command()
@click.option(
    "--obsidian-vault", default=None, type=click.Path(path_type=Path),
    help="Path to Obsidian vault for Storage agent"
)
@click.option(
    "--ollama-model", default=None, help="Ollama model"
)
@click.option(
    "--interval", default=5.0, help="Polling interval in seconds (for watch mode)"
)
@click.option("--once", is_flag=True, help="Process all pending files, then exit (default: watch forever)")
def watch(
    obsidian_vault: Path | None,
    ollama_model: str | None,
    interval: float,
    once: bool,
):
    """Watch inbox/ and auto-process new voice memos.

    Without --once: runs forever, polling every N seconds.
    With --once: processes all pending files, reports results, exits.
    """
    # Resolve from config if not specified
    if obsidian_vault is None:
        obsidian_vault = cfg.OBSIDIAN_VAULT
    if ollama_model is None:
        ollama_model = cfg.OLLAMA_MODEL

    orch = Orchestrator(
        inbox_dir=str(cfg.INBOX_DIR),
        obsidian_vault=obsidian_vault,
        ollama_model=ollama_model,
        pipeline_dir=str(cfg.PIPELINE_DIR),
    )

    if once:
        orch.run_once()
    else:
        orch.watch(poll_interval=interval)


@cli.command()
@click.option("--db", default=None, help="Path to Kanban database")
def board(db: str | None):
    """Show the Kanban board with all tasks and events."""
    if db is None:
        db = str(cfg.KANBAN_DB)
    board_obj = KanbanBoard(db)
    print(board_obj.print_board())

    # Show recent tasks with details
    tasks = board_obj.get_all_tasks()
    if tasks:
        print(f"\n{'─' * 70}")
        print(f"Recent tasks:")
        print(f"{'─' * 70}")
        for t in tasks[:10]:
            status_icon = {"done": "✅", "failed": "❌", "inbox": "📥"}.get(t["stage"], "🔄")
            print(f"  {status_icon} {t['id']:<20}  {t['stage']:<14}  "
                  f"created: {t['created_at'][:19]}  "
                  f"{'done: ' + t['completed_at'][:19] if t['completed_at'] else ''}")
            if t.get("error"):
                print(f"     ⚠️  {t['error'][:100]}")


@cli.command()
@click.argument("task_id")
@click.option("--db", default=None, help="Path to Kanban database")
def events(task_id: str, db: str | None):
    """Show the event log for a specific task."""
    if db is None:
        db = str(cfg.KANBAN_DB)
    board_obj = KanbanBoard(db)
    task = board_obj.get_task(task_id)
    if not task:
        click.echo(f"❌ Task not found: {task_id}")
        raise SystemExit(1)

    click.echo(f"Task: {task['id']}")
    click.echo(f"  Hive: {task['hive_id']}  |  File: {task['audio_file']}")
    click.echo(f"  Stage: {task['stage']}  |  Created: {task['created_at'][:19]}")
    if task.get("error"):
        click.echo(f"  Error: {task['error'][:200]}")
    click.echo()

    events_list = board_obj.get_events(task_id)
    if not events_list:
        click.echo("  No events logged.")
        return

    click.echo(f"{'Agent':<14} {'Action':<12} {'Duration':>8}  {'Time':<20}")
    click.echo("-" * 60)
    for ev in events_list:
        dur = f"{ev['duration_ms']:.0f}ms" if ev.get("duration_ms") else "—"
        click.echo(f"{ev['agent']:<14} {ev['action']:<12} {dur:>8}  {ev['created_at'][:19]}")


@cli.command()
def status():
    """Show BuzzBoard pipeline status."""
    click.echo("🐝 BuzzBoard Status")
    click.echo("=" * 40)
    click.echo("  Pipeline:  Transcriber ✅  |  Editor ✅  |  Extractor ✅  |  Storage ✅")
    click.echo("  Phase 3 complete — full pipeline + Kanban + file watcher.")
    click.echo()
    click.echo("  Quick start:")
    click.echo("    buzzboard process inbox/H07_2026-06-06.m4a")
    click.echo("    buzzboard watch --once")
    click.echo("    buzzboard board")
    click.echo("    buzzboard config")
    click.echo()


@cli.command(name="config")
def config_cmd():
    """Show current BuzzBoard configuration."""
    click.echo(cfg.print_config())
    click.echo()
    env_file = Path(".env")
    if env_file.exists():
        click.echo(f"  📄 .env file: {env_file.absolute()}")
    else:
        click.echo(f"  💡 Create a .env file to customize (see .env.example)")


if __name__ == "__main__":
    cli()
