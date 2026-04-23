def test_render_video_smart_copy_cleanup_on_success(tmp_path, monkeypatch):
    """All temp segment files and concat list are deleted after a successful smart-copy render."""

    import subprocess as _sp
    import tempfile as _tempfile
    from pathlib import Path as _Path

    from io_ import video_renderer_twophase

    tracked_tmps: list = []
    _real_mkstemp = _tempfile.mkstemp

    def _tracking_mkstemp(suffix=None, dir=None):
        fd, path = _real_mkstemp(suffix=suffix, dir=dir)
        tracked_tmps.append(path)
        return fd, path

    def _fake_copy(input_path, kf_start, start, end, out_path):
        return None

    def _fake_subprocess_run(cmd, capture_output, text):
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_renderer_twophase, "render_video_segment_copy", _fake_copy)
    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_subprocess_run)
    monkeypatch.setattr(video_renderer_twophase.tempfile, "mkstemp", _tracking_mkstemp)

    video_renderer_twophase.render_video_smart_copy(
        input_path="source.mp4",
        keep_segments=[(0.0, 5.0), (10.0, 15.0)],
        keyframes=[0.0, 10.0],
        out_path=str(tmp_path / "output.mp4"),
        enc_opts={"vcodec": "libx264"},
    )

    assert len(tracked_tmps) == 3, f"Expected 3 temp files (2 segments + 1 concat list), got {len(tracked_tmps)}"
    for path in tracked_tmps:
        assert not _Path(path).exists(), f"Temp file was not cleaned up: {path}"


def test_render_video_smart_copy_temp_cleanup_on_failure(tmp_path, monkeypatch):
    """Temp files are cleaned up even when one segment render fails after all temps exist."""

    import tempfile as _tempfile
    from pathlib import Path as _Path

    from io_ import video_renderer_twophase

    tracked_tmps: list = []
    _real_mkstemp = _tempfile.mkstemp

    def _tracking_mkstemp(suffix=None, dir=None):
        fd, path = _real_mkstemp(suffix=suffix, dir=dir)
        tracked_tmps.append(path)
        return fd, path

    def _fake_copy_maybe_raises(input_path, kf_start, start, end, out_path):
        if end == 12.0:
            raise RuntimeError("Segment copy failed: simulated disk error")
        return None

    monkeypatch.setattr(video_renderer_twophase, "render_video_segment_copy", _fake_copy_maybe_raises)
    monkeypatch.setattr(video_renderer_twophase.tempfile, "mkstemp", _tracking_mkstemp)

    raised_exc = None
    try:
        video_renderer_twophase.render_video_smart_copy(
            input_path="source.mp4",
            keep_segments=[(0.0, 5.0), (8.0, 12.0), (16.0, 20.0)],
            keyframes=[0.0, 8.0, 16.0],
            out_path=str(tmp_path / "output.mp4"),
            enc_opts={"vcodec": "libx264"},
        )
        raise AssertionError("Expected RuntimeError but no exception was raised")
    except RuntimeError as exc:
        raised_exc = exc

    assert raised_exc is not None, "No exception was propagated"
    assert "Segment copy failed" in str(raised_exc), f"Unexpected exception message: {raised_exc}"
    assert tracked_tmps, "No temp files were created (test is invalid)"
    for path in tracked_tmps:
        assert not _Path(path).exists(), f"Temp file was not cleaned up after segment failure: {path}"
