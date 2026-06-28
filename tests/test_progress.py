"""Progress reporter tests."""

from __future__ import annotations

import io

from jsmerge.progress import NullProgress, TerminalProgress


def test_null_progress_is_silent():
    progress = NullProgress()
    progress.step("working")
    progress.update("still working")
    progress.finish("done")


def test_terminal_progress_non_tty_writes_step_and_finish():
    stream = io.StringIO()
    progress = TerminalProgress(stream=stream, enabled=False)
    progress.step("Loading modules")
    progress.update("Loading modules (10/100)")
    progress.finish("Loaded 100 modules")
    output = stream.getvalue()
    assert "Loading modules\n" in output
    assert "✓ Loaded 100 modules\n" in output
    assert "10/100" not in output
