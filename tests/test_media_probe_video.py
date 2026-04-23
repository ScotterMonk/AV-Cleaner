import subprocess


def test_probe_video_keyframes_returns_sorted_floats(monkeypatch):
    """Keyframe rows (key_frame==1) are parsed and returned as a sorted list of floats."""

    from io_ import media_probe

    stdout = (
        "1,0.000000\n"
        "0,0.033367\n"
        "1,2.500000\n"
        "1,1.250000\n"
    )

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(args=_cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_keyframes("fake.mp4")

    assert result == [0.0, 1.25, 2.5], f"Expected [0.0, 1.25, 2.5], got {result}"


def test_probe_video_keyframes_filters_non_keyframes(monkeypatch):
    """Rows where key_frame == 0 must be excluded from the result."""

    from io_ import media_probe

    stdout = (
        "0,0.033367\n"
        "0,0.066733\n"
        "0,0.100100\n"
    )

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(args=_cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_keyframes("fake.mp4")

    assert result == [], f"Expected empty list for all non-keyframes, got {result}"


def test_probe_video_keyframes_raises_on_nonzero_returncode(monkeypatch):
    """RuntimeError must be raised when ffprobe exits with a non-zero return code."""

    from io_ import media_probe

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(
            args=_cmd,
            returncode=1,
            stdout="",
            stderr="No such file or directory",
        )

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)

    try:
        media_probe.probe_video_keyframes("fake.mp4")
        raise AssertionError("Expected RuntimeError for non-zero return code")
    except RuntimeError as exc:
        assert "ffprobe failed" in str(exc).lower(), f"Unexpected message: {exc}"
        assert "No such file or directory" in str(exc), f"stderr not included in message: {exc}"


def test_probe_video_keyframes_raises_on_missing_ffprobe(monkeypatch):
    """RuntimeError must be raised when ffprobe binary is absent from PATH."""

    from io_ import media_probe

    def _raise(_cmd, capture_output, text):
        raise FileNotFoundError("ffprobe not on PATH")

    monkeypatch.setattr(media_probe.subprocess, "run", _raise)

    try:
        media_probe.probe_video_keyframes("fake.mp4")
        raise AssertionError("Expected RuntimeError for missing ffprobe")
    except RuntimeError as exc:
        assert "ffprobe not found on path" in str(exc).lower(), f"Unexpected message: {exc}"


def test_probe_video_keyframes_skips_malformed_lines(monkeypatch):
    """Lines that do not split into exactly 2 tokens must be silently skipped."""

    from io_ import media_probe

    stdout = (
        "1,0.500000\n"
        "this_is_garbage\n"
        "1,bad_float\n"
        "1,2,extra_col\n"
        "\n"
        "1,3.000000\n"
    )

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(args=_cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_keyframes("fake.mp4")

    assert result == [0.5, 3.0], f"Expected [0.5, 3.0], got {result}"


def test_probe_video_stream_codec_parses_codec_name(monkeypatch):
    """[`probe_video_stream_codec()`](io_/media_probe.py:117) returns the stripped codec name from ffprobe stdout."""

    from io_ import media_probe

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(args=_cmd, returncode=0, stdout="h264\n", stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_stream_codec("fake.mp4")

    assert result == "h264", f"Expected 'h264', got {result!r}"


def test_probe_video_stream_codec_raises_on_nonzero_returncode(monkeypatch):
    """RuntimeError must be raised when ffprobe exits with a non-zero return code."""

    from io_ import media_probe

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(args=_cmd, returncode=1, stdout="", stderr="Invalid data found")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)

    try:
        media_probe.probe_video_stream_codec("fake.mp4")
        raise AssertionError("Expected RuntimeError for non-zero return code")
    except RuntimeError as exc:
        assert "ffprobe failed" in str(exc).lower(), f"Unexpected message: {exc}"
        assert "Invalid data found" in str(exc), f"stderr not included in message: {exc}"


def test_probe_video_stream_codec_raises_on_missing_ffprobe(monkeypatch):
    """RuntimeError must be raised when ffprobe binary is absent from PATH."""

    from io_ import media_probe

    def _raise(_cmd, capture_output, text):
        raise FileNotFoundError("ffprobe not on PATH")

    monkeypatch.setattr(media_probe.subprocess, "run", _raise)

    try:
        media_probe.probe_video_stream_codec("fake.mp4")
        raise AssertionError("Expected RuntimeError for missing ffprobe")
    except RuntimeError as exc:
        assert "ffprobe not found on path" in str(exc).lower(), f"Unexpected message: {exc}"


def test_probe_video_fps_parses_rational_string(monkeypatch):
    """[`probe_video_fps()`](io_/media_probe.py:154) must parse `60/1` and return `60.0`."""

    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="60/1\n", stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("fake.mp4")
    assert result == 60.0, f"Expected 60.0, got {result}"


def test_probe_video_fps_parses_ntsc_rational(monkeypatch):
    """[`probe_video_fps()`](io_/media_probe.py:154) must parse `30000/1001` close to 29.97."""

    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="30000/1001\n", stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("fake.mp4")
    assert result is not None
    assert abs(result - 29.97) < 0.01, f"Expected ~29.97, got {result}"


def test_probe_video_fps_returns_none_on_nonzero_returncode(monkeypatch):
    """[`probe_video_fps()`](io_/media_probe.py:154) must return `None` on ffprobe failure."""

    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="error")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("bad.mp4")
    assert result is None, f"Expected None on failure, got {result}"


def test_probe_video_fps_returns_none_on_zero_denominator(monkeypatch):
    """[`probe_video_fps()`](io_/media_probe.py:154) must return `None` when denominator is zero."""

    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="60/0\n", stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("fake.mp4")
    assert result is None, f"Expected None for 60/0, got {result}"


def test_probe_video_fps_returns_none_on_missing_ffprobe(monkeypatch):
    """[`probe_video_fps()`](io_/media_probe.py:154) must return `None` when ffprobe is missing."""

    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        raise FileNotFoundError("ffprobe not found")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("fake.mp4")
    assert result is None, f"Expected None when ffprobe missing, got {result}"
