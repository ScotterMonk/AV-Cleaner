from datetime import datetime
from pathlib import Path

from utils.pause_removal_log import pause_removal_log_line, pause_removal_log_write


def test_pause_removal_log_line_format_no_ms() -> None:
    assert pause_removal_log_line(15 * 60, 15 * 60 + 3) == "pause rem-00:15:00-to-00:15:03"


def test_pause_removal_log_write_creates_file(tmp_path: Path) -> None:
    fixed_now = datetime(2026, 1, 12, 12, 0, 0)
    removals = [(1.0, 2.0), (3.5, 6.0)]

    out = pause_removal_log_write(tmp_path, removals, now=fixed_now)
    assert out is not None
    out_path = Path(out)
    assert out_path.name == "2026-01-12-pauses-rem-log.txt"
    assert out_path.parent == tmp_path

    text = out_path.read_text(encoding="utf-8")
    assert "pause rem-00:00:01-to-00:00:02" in text
    assert "pause rem-00:00:03-to-00:00:06" in text
    assert "2 pauses removed" in text

