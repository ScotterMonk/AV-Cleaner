"""Test GUI subprocess command construction for processing runs."""

import sys
from pathlib import Path
from types import SimpleNamespace

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ui.gui_app import AVCleanerGUI


class _FakeStdout:
    # Modified by gpt-5.4 | 2026-03-07
    def __init__(self, lines=None):
        self._lines = lines or ()

    # Modified by gpt-5.4 | 2026-03-07
    def __iter__(self):
        return iter(self._lines)


class _FakeProcess:
    # Modified by gpt-5.4 | 2026-03-07
    def __init__(self, cmd, *, lines=None):
        self.cmd = cmd
        self.stdout = _FakeStdout(lines)

    def poll(self):
        return 0

    def wait(self):
        return 0


class _FakeThread:
    def __init__(self, *, target, daemon):
        self._target = target
        self.daemon = daemon

    def start(self):
        self._target()


# Modified by gpt-5.4 | 2026-03-07
def test_run_processing_uses_process_subcommand(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def _fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return _FakeProcess(cmd)

    monkeypatch.setattr("ui.gui_app.subprocess.Popen", _fake_popen)
    monkeypatch.setattr("ui.gui_app.threading.Thread", _FakeThread)

    app = object.__new__(AVCleanerGUI)
    app._proc = None
    app._project_dir = tmp_path
    app.clear_logs = lambda: None
    app.clear_progress = lambda: None
    app.set_status = lambda _status: None
    app.append_log = lambda _line: None
    app.append_progress = lambda _line: None
    app.after = lambda _delay, callback, *args: callback(*args)
    app._set_row_for_path = lambda *_args: None
    app._set_modded_row_for_path = lambda *_args: None
    app._clear_modded_rows = lambda: None

    app.run_processing("host.mp4", "guest.mp4")

    cmd = captured["cmd"]
    assert cmd[0] == sys.executable
    assert cmd[1] == "main.py"
    assert cmd[2] == "process"
    assert "--host" in cmd
    assert "host.mp4" in cmd
    assert "--guest" in cmd
    assert "guest.mp4" in cmd
    assert "--action" not in cmd
    assert captured["cwd"] == str(tmp_path)


# Created by gpt-5.4 | 2026-03-07
def test_run_processing_updates_modded_rows_from_result_line(monkeypatch, tmp_path):
    captured_updates: list[tuple[str, str]] = []

    result_lines = [
        "[RESULT] host=C:\\Videos\\host_processed.mp4 guest=C:\\Videos\\guest_processed.mp4\n",
    ]

    def _fake_popen(cmd, **kwargs):
        return _FakeProcess(cmd, lines=result_lines)

    monkeypatch.setattr("ui.gui_app.subprocess.Popen", _fake_popen)
    monkeypatch.setattr("ui.gui_app.threading.Thread", _FakeThread)
    monkeypatch.setattr("ui.gui_app.os.path.exists", lambda _path: True)

    app = object.__new__(AVCleanerGUI)
    app._proc = None
    app._project_dir = tmp_path
    app.clear_logs = lambda: None
    app.clear_progress = lambda: None
    app._clear_modded_rows = lambda: None
    app.set_status = lambda _status: None
    app.append_log = lambda _line: None
    app.append_progress = lambda _line: None
    app.after = lambda _delay, callback, *args: callback(*args)
    app._set_row_for_path = lambda *_args: None
    app._set_modded_row_for_path = lambda role, path: captured_updates.append((role, path))

    app.run_processing("host.mp4", "guest.mp4")

    assert captured_updates == [
        ("host", "C:\\Videos\\host_processed.mp4"),
        ("guest", "C:\\Videos\\guest_processed.mp4"),
    ]
