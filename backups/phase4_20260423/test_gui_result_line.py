# tests/test_gui_result_line.py
"""Test that the GUI worker captures and uses [RESULT] line from subprocess output."""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ui.gui_process_helpers import result_line_paths_parse


class TestResultLinePathsParse:
    """Test result_line_paths_parse() handles all real-world line formats."""

    # ── Bare lines (no logger prefix) ─────────────────────────────────

    def test_bare_line_simple_paths(self):
        """Parse a [RESULT] line with no logger prefix — simple paths."""
        h, g = result_line_paths_parse("[RESULT] host=/path/host.mp4 guest=/path/guest.mp4")
        assert h == "/path/host.mp4"
        assert g == "/path/guest.mp4"

    def test_bare_line_windows_paths(self):
        h, g = result_line_paths_parse("[RESULT] host=C:\\Videos\\host.mp4 guest=C:\\Videos\\guest.mp4")
        assert h == "C:\\Videos\\host.mp4"
        assert g == "C:\\Videos\\guest.mp4"

    def test_bare_line_paths_with_spaces(self):
        h, g = result_line_paths_parse("[RESULT] host=C:\\My Videos\\host.mp4 guest=C:\\My Videos\\guest.mp4")
        assert h == "C:\\My Videos\\host.mp4"
        assert g == "C:\\My Videos\\guest.mp4"

    # ── Log-prefixed lines (real-world format from the logger) ────────

    def test_log_prefixed_line_parses_successfully(self):
        """The logger emits 'HH:MM:SS - INFO - [RESULT] ...' — must still parse."""
        line = "17:05:30 - INFO - [RESULT] host=/out/host_processed.mp4 guest=/out/guest_preflight_processed.mp4"
        h, g = result_line_paths_parse(line)
        assert h == "/out/host_processed.mp4"
        assert g == "/out/guest_preflight_processed.mp4"

    def test_log_prefixed_windows_paths(self):
        line = "09:12:45 - INFO - [RESULT] host=D:\\Projects\\host_processed.mp4 guest=D:\\Projects\\guest_preflight_processed.mp4"
        h, g = result_line_paths_parse(line)
        assert h == "D:\\Projects\\host_processed.mp4"
        assert g == "D:\\Projects\\guest_preflight_processed.mp4"

    def test_log_prefixed_paths_with_spaces(self):
        line = "17:05:30 - INFO - [RESULT] host=C:\\My Videos\\host_processed.mp4 guest=C:\\My Videos\\guest_preflight_processed.mp4"
        h, g = result_line_paths_parse(line)
        assert h == "C:\\My Videos\\host_processed.mp4"
        assert g == "C:\\My Videos\\guest_preflight_processed.mp4"

    def test_log_prefixed_with_trailing_newline(self):
        line = "17:05:30 - INFO - [RESULT] host=/out/h.mp4 guest=/out/g.mp4\n"
        h, g = result_line_paths_parse(line)
        assert h == "/out/h.mp4"
        assert g == "/out/g.mp4"

    # ── Non-matching lines ────────────────────────────────────────────

    def test_no_result_token_returns_none(self):
        h, g = result_line_paths_parse("17:05:30 - INFO - Some random log line")
        assert h is None
        assert g is None

    def test_empty_string_returns_none(self):
        h, g = result_line_paths_parse("")
        assert h is None
        assert g is None

    def test_malformed_result_missing_guest_returns_none(self):
        """[RESULT] with only host= and no guest= should return (None, None)."""
        h, g = result_line_paths_parse("[RESULT] host=only_host.mp4")
        assert h is None
        assert g is None

    def test_malformed_result_log_prefixed_missing_guest(self):
        line = "17:05:30 - INFO - [RESULT] host=only_host.mp4"
        h, g = result_line_paths_parse(line)
        assert h is None
        assert g is None


class TestGuiResultLineParsing:
    """Test [RESULT] line parsing as used in GUI _worker() flow."""

    def test_worker_uses_result_paths_when_available(self):
        """Verify GUI worker uses [RESULT] paths when captured from log-prefixed output."""
        from utils.path_helpers import make_processed_output_path

        host_path = "original_host.mp4"
        guest_path = "original_guest.mp4"

        # Simulate the log-prefixed line the GUI actually sees on stdout.
        log_line = "17:05:30 - INFO - [RESULT] host=host_processed_rerun.mp4 guest=guest_processed_rerun.mp4\n"
        _result_host, _result_guest = result_line_paths_parse(log_line)

        host_processed = _result_host or make_processed_output_path(host_path)
        guest_processed = _result_guest or make_processed_output_path(guest_path)

        assert host_processed == "host_processed_rerun.mp4"
        assert guest_processed == "guest_processed_rerun.mp4"

    def test_worker_falls_back_to_computed_paths(self):
        """Verify worker logic falls back to computed paths when no [RESULT] captured."""
        from utils.path_helpers import make_processed_output_path

        _result_host: str | None = None
        _result_guest: str | None = None

        host_path = "original_host.mp4"
        guest_path = "original_guest.mp4"

        host_processed = _result_host or make_processed_output_path(host_path)
        guest_processed = _result_guest or make_processed_output_path(guest_path)

        assert host_processed == make_processed_output_path(host_path)
        assert guest_processed == make_processed_output_path(guest_path)

    def test_preflight_path_scenario(self):
        """Reproduce the exact bug: preflight renames guest, [RESULT] carries the correct path."""
        from utils.path_helpers import make_processed_output_path

        original_guest = "guest.mp4"
        # Pipeline uses preflight path, so [RESULT] carries the preflight-based output.
        pipeline_guest_out = "guest_preflight_processed.mp4"

        log_line = f"17:05:30 - INFO - [RESULT] host=host_processed.mp4 guest={pipeline_guest_out}\n"
        _result_host, _result_guest = result_line_paths_parse(log_line)

        guest_processed = _result_guest or make_processed_output_path(original_guest)

        # With the fix, the parsed path is used — NOT the stale fallback.
        assert guest_processed == pipeline_guest_out
        assert guest_processed != make_processed_output_path(original_guest)
