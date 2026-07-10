"""Progress reporting (issue #4): long stages must never look like a hang.

One tiny seam, three implementations. The engine and governor emit through
whatever Reporter they're handed; the CLI picks rich bars on a terminal and
plain lines when piped; everything else (MCP, tests, library use) defaults to
NullReporter and stays silent. Progress goes to stderr — stdout is for data.
"""
from __future__ import annotations

import sys
from typing import Protocol


class Reporter(Protocol):
    def start(self, stage: str, total: int | None = None) -> None: ...
    def advance(self, n: int = 1) -> None: ...
    def note(self, msg: str) -> None: ...
    def finish(self) -> None: ...
    def close(self) -> None: ...


class NullReporter:
    def start(self, stage: str, total: int | None = None) -> None: pass
    def advance(self, n: int = 1) -> None: pass
    def note(self, msg: str) -> None: pass
    def finish(self) -> None: pass
    def close(self) -> None: pass


class PlainReporter:
    """Line-oriented progress for pipes, CI logs, and dumb terminals.
    Known totals print at ~decile boundaries; unknown totals every 25 items."""

    UNKNOWN_EVERY = 25

    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stderr
        self._stage = ""
        self._total: int | None = None
        self._done = 0
        self._step = 1

    def _emit(self, line: str) -> None:
        print(line, file=self.stream, flush=True)

    def start(self, stage: str, total: int | None = None) -> None:
        self.finish()
        self._stage, self._total, self._done = stage, total, 0
        if total:
            self._step = max(1, total // 10)
            self._emit(f"▸ {stage} — {total} item(s)")
        else:
            self._step = self.UNKNOWN_EVERY
            self._emit(f"▸ {stage}…")

    def advance(self, n: int = 1) -> None:
        self._done += n
        at_step = self._done % self._step == 0
        if self._total:
            if at_step or self._done >= self._total:
                self._emit(f"  {self._stage}: {self._done}/{self._total}")
        elif at_step:
            self._emit(f"  {self._stage}: {self._done}")

    def note(self, msg: str) -> None:
        self._emit(f"  ⏳ {msg}")

    def finish(self) -> None:
        # unknown-total stages report their final count once, on completion
        if self._stage and not self._total and self._done \
                and self._done % self._step != 0:
            self._emit(f"  {self._stage}: {self._done}")
        self._stage, self._total, self._done = "", None, 0

    def close(self) -> None:
        self.finish()


class RichReporter:
    """Live progress bars on a real terminal (rich ships with typer)."""

    def __init__(self):
        from rich.console import Console
        from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                                   SpinnerColumn, TextColumn,
                                   TimeElapsedColumn)
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=Console(stderr=True),
        )
        self._task = None
        self._started = False

    def start(self, stage: str, total: int | None = None) -> None:
        if not self._started:
            self._progress.start()
            self._started = True
        self._task = self._progress.add_task(stage, total=total)

    def advance(self, n: int = 1) -> None:
        if self._task is not None:
            self._progress.advance(self._task, n)

    def note(self, msg: str) -> None:
        self._progress.console.print(f"  ⏳ {msg}", style="dim", highlight=False)

    def finish(self) -> None:
        self._task = None

    def close(self) -> None:
        if self._started:
            self._progress.stop()
            self._started = False


def make_reporter(stream=None) -> Reporter:
    """Rich bars on a terminal, plain lines everywhere else."""
    stream = stream if stream is not None else sys.stderr
    try:
        if stream.isatty():
            return RichReporter()
    except Exception:
        pass
    return PlainReporter(stream)
