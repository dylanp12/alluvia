"""CLI boundary for attributed sources and isolated regression verification."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from alluvia.distill.scrub import redact

app = typer.Typer(help="Turn corrected Python behavior into a verified regression check.")


def _fail(message: str) -> None:
    typer.echo(json.dumps({"error": redact(message)}, ensure_ascii=False))
    raise typer.Exit(2)


@app.command("source")
def source_command(
    note_id: str,
    project: Path = typer.Option(Path("."), "--project", help="Project containing this correction."),
):
    """Read a note's attributed, project-scoped source as JSON; no model call."""
    from alluvia import config
    from alluvia.cli import _repo
    from alluvia.checks_sources import SourceError, note_source

    try:
        result = note_source(_repo(), config.DEFAULT_USER, note_id, project)
    except SourceError as exc:
        _fail(str(exc))
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("verify")
def verify_command(
    selector: str = typer.Argument(..., help="One pytest node: tests/test_guard.py::test_behavior."),
    before: str = typer.Option(..., "--before", help="Commit or ref containing the old behavior."),
    after: str = typer.Option("HEAD", "--after", help="Commit or ref containing the corrected behavior."),
    project: Path = typer.Option(Path("."), "--project", help="Python project directory within a Git checkout."),
    requirement: str = typer.Option(..., "--requirement", help="The concrete behavior this check protects."),
    source_file: Path = typer.Option(..., "--source-file", help="JSON source receipt with nonempty kind and text."),
    python: str | None = typer.Option(None, "--python", help="Python interpreter with this project's pytest dependencies."),
    timeout: int = typer.Option(60, "--timeout", min=1, max=600, help="Maximum seconds for each revision."),
    output: Path = typer.Option(..., "--output", help="New directory for the unchanged test and evidence bundle."),
):
    """Run identical test bytes against two committed revisions and export proof.

    Executes trusted project tests with your permissions. JSON output; exit 0
    means verified, 1 means not verified/inconclusive, 2 means invalid request.
    """
    try:
        if source_file.stat().st_size > 65536:
            _fail("Source receipt exceeds 64 KiB.")
        source = json.loads(source_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        _fail(f"Cannot read source receipt: {exc}")
    if not isinstance(source, dict) or any(
        not isinstance(source.get(key), str) or not source[key].strip()
        for key in ("kind", "text")
    ):
        _fail("Source receipt must contain nonempty string kind and text fields.")
    if not requirement.strip():
        _fail("Requirement must describe the behavior being checked.")
    from alluvia.checks import CheckError, verify_check

    try:
        result = verify_check(project, selector, before, after, requirement=requirement,
                              source=source, python=python, timeout=timeout, output=output)
    except (CheckError, OSError) as exc:
        _fail(str(exc))
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "verified":
        raise typer.Exit(1)
