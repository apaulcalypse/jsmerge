"""CLI progress reporting for long-running operations."""

from __future__ import annotations

import sys
import threading
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class ProgressReporter(Protocol):
    def step(self, message: str) -> None:
        """Begin a new progress step."""

    def update(self, message: str) -> None:
        """Update the current step message."""

    def finish(self, message: str | None = None) -> None:
        """Complete the current step."""


class NullProgress:
    def step(self, message: str) -> None:
        return

    def update(self, message: str) -> None:
        return

    def finish(self, message: str | None = None) -> None:
        return


_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class TerminalProgress:
    """TTY spinner on stderr; plain status lines when not interactive."""

    def __init__(self, *, stream=None, enabled: bool | None = None) -> None:
        self._stream = stream or sys.stderr
        self._enabled = self._stream.isatty() if enabled is None else enabled
        self._message = ""
        self._running = False
        self._thread: threading.Thread | None = None
        self._frame = 0

    def step(self, message: str) -> None:
        self.finish()
        self._message = message
        if self._enabled:
            self._running = True
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            self._stream.write(f"{message}\n")
            self._stream.flush()

    def update(self, message: str) -> None:
        self._message = message
        if not self._enabled:
            return

    def finish(self, message: str | None = None) -> None:
        if self._running:
            self._running = False
            if self._thread is not None:
                self._thread.join(timeout=1)
                self._thread = None
            done = message or self._message
            self._stream.write(f"\r\x1b[K✓ {done}\n")
            self._stream.flush()
        elif message:
            self._stream.write(f"✓ {message}\n")
            self._stream.flush()
        self._message = ""

    def _spin(self) -> None:
        while self._running:
            frame = _SPINNER_FRAMES[self._frame % len(_SPINNER_FRAMES)]
            self._frame += 1
            self._stream.write(f"\r\x1b[K{frame} {self._message}")
            self._stream.flush()
            time.sleep(0.08)
