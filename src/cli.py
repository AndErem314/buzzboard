"""
BuzzBoard CLI — the single entry point for the multi-agent pipeline.

Usage:
    buzzboard process inbox/H07_2026-06-06.m4a     # Run full pipeline
    buzzboard transcribe inbox/H07_2026-06-06.m4a   # Transcribe only
    buzzboard status                                 # Show pipeline status (Phase 3)
"""

from __future__ import annotations

from pathlib import Path

import click

from .agents.transcriber import TranscriberAgent


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
@click.option("--model", default="base")
@click.option("--output-dir", default="pipeline", type=click.Path(path_type=Path))
@click.option("--editor-model", default="llama3.2:3b", help="Ollama model for text editing")
@click.option("--extractor-model", default="llama3.2:3b", help="Ollama model for data extraction")
@click.option("--obsidian-vault", default=None, type=click.Path(path_type=Path),
              help="Path to Obsidian vault (for storage agent)")
def process(
    audio_file: Path,
    backend: str,
    model: str,
    output_dir: Path,
    editor_model: str,
    extractor_model: str,
    obsidian_vault: Path | None,
):
    """Run the full BuzzBoard pipeline on a voice memo.

    Pipeline:  Transcriber → Editor → Extractor → Storage
    """
    click.echo(f"🐝 BuzzBoard processing: {audio_file.name}\n")

    # ── Stage 1: Transcribe ─────────────────────────────────────────────
    click.echo("─" * 50)
    click.echo("Stage 1/4:  Transcriber")
    click.echo("─" * 50)

    transcriber = TranscriberAgent(
        backend=backend, model=model, pipeline_dir=output_dir
    )
    try:
        raw_path = transcriber.process(audio_file)
    except (ValueError, FileNotFoundError) as e:
        click.echo(f"❌ Transcriber failed: {e}", err=True)
        raise SystemExit(1)

    # ── Stage 2-4:  Stubs (implemented in Phase 2) ─────────────────────
    click.echo("\n" + "─" * 50)
    click.echo("Stage 2/4:  Editor (Phase 2 — coming soon)")
    click.echo("─" * 50)
    click.echo(f"  ⏳ Would edit: {raw_path}")
    click.echo(f"  📋 Model: {editor_model}")

    click.echo("\n" + "─" * 50)
    click.echo("Stage 3/4:  Extractor (Phase 2 — coming soon)")
    click.echo("─" * 50)
    click.echo(f"  ⏳ Would extract structured data")
    click.echo(f"  📋 Model: {extractor_model}")

    click.echo("\n" + "─" * 50)
    click.echo("Stage 4/4:  Storage (Phase 3 — coming soon)")
    click.echo("─" * 50)
    if obsidian_vault:
        click.echo(f"  ⏳ Would write to: {obsidian_vault}/Hives/")
    else:
        click.echo(f"  ⏳ Would write to Obsidian vault")

    click.echo(f"\n✅ Pipeline complete (1/4 stages active) → {raw_path}")


@cli.command()
def status():
    """Show BuzzBoard pipeline status (Phase 3)."""
    click.echo("🐝 BuzzBoard Status")
    click.echo("=" * 40)
    click.echo("  Pipeline:  Transcriber ✅  |  Editor ⏳  |  Extractor ⏳  |  Storage ⏳")
    click.echo("  Phase 1 complete — transcription working.")
    click.echo("  Phase 2 (Editor + Extractor) coming next.")
    click.echo()
    click.echo("  Inbox:  check inbox/ for pending voice memos")
    click.echo("  Pipeline artifacts:  pipeline/")


if __name__ == "__main__":
    cli()
