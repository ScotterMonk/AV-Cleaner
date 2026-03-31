"""tests/test_video_renderer_twophase.py

Tests for two-phase render helpers, starting with probe_video_keyframes().

Phase 1 Task 02: verify keyframe probing logic via mocked subprocess output.
Phase 1 Task 02b: verify probe_video_stream_codec() via mocked subprocess output.
Phase 1 Task 03: verify render_audio_phase() graph construction via mocked
    run_with_progress — single segment, multi-segment with filters, no segments.
Phase 2 Task 04: verify classify_segments_by_keyframe() classification logic —
    exact keyframe hit, within tolerance snap, outside tolerance bridge, empty keyframes.
"""

import subprocess
from dataclasses import dataclass
from typing import Any, Dict
from unittest.mock import patch


def test_config_two_phase_keys():
    """Two-phase config defaults are present in the high-quality preset."""
    from config import QUALITY_PRESETS

    assert QUALITY_PRESETS['PODCAST_HIGH_QUALITY']['two_phase_render_enabled'] is True
    assert QUALITY_PRESETS['PODCAST_HIGH_QUALITY']['keyframe_snap_tolerance_s'] == 0.3


def test_config_video_phase_strategy_key():
    """High-quality preset defaults the video phase strategy to auto."""
    from config import QUALITY_PRESETS

    assert QUALITY_PRESETS['PODCAST_HIGH_QUALITY']['video_phase_strategy'] == 'auto'


# ---------------------------------------------------------------------------
# probe_video_keyframes — happy path
# ---------------------------------------------------------------------------

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

    # All rows are non-keyframes
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


# ---------------------------------------------------------------------------
# probe_video_keyframes — error conditions
# ---------------------------------------------------------------------------

def test_probe_video_keyframes_raises_on_nonzero_returncode(monkeypatch):
    """RuntimeError must be raised when ffprobe exits with a non-zero return code."""
    from io_ import media_probe

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(
            args=_cmd, returncode=1, stdout="", stderr="No such file or directory"
        )

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)

    try:
        media_probe.probe_video_keyframes("fake.mp4")
        raise AssertionError("Expected RuntimeError for non-zero return code")
    except RuntimeError as e:
        assert "ffprobe failed" in str(e).lower(), f"Unexpected message: {e}"
        assert "No such file or directory" in str(e), f"stderr not included in message: {e}"


def test_probe_video_keyframes_raises_on_missing_ffprobe(monkeypatch):
    """RuntimeError must be raised when ffprobe binary is absent from PATH."""
    from io_ import media_probe

    def _raise(_cmd, capture_output, text):
        raise FileNotFoundError("ffprobe not on PATH")

    monkeypatch.setattr(media_probe.subprocess, "run", _raise)

    try:
        media_probe.probe_video_keyframes("fake.mp4")
        raise AssertionError("Expected RuntimeError for missing ffprobe")
    except RuntimeError as e:
        assert "ffprobe not found on path" in str(e).lower(), f"Unexpected message: {e}"


# ---------------------------------------------------------------------------
# probe_video_keyframes — malformed input
# ---------------------------------------------------------------------------

def test_probe_video_keyframes_skips_malformed_lines(monkeypatch):
    """Lines that do not split into exactly 2 tokens must be silently skipped."""
    from io_ import media_probe

    stdout = (
        "1,0.500000\n"          # valid keyframe
        "this_is_garbage\n"     # 1 token — malformed
        "1,bad_float\n"         # 2 tokens but pts_time is not a float — malformed
        "1,2,extra_col\n"       # 3 tokens — malformed
        "\n"                    # empty line — malformed
        "1,3.000000\n"          # valid keyframe
    )

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(args=_cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)

    result = media_probe.probe_video_keyframes("fake.mp4")

    # Only the two valid keyframe lines should survive
    assert result == [0.5, 3.0], f"Expected [0.5, 3.0], got {result}"


# ---------------------------------------------------------------------------
# probe_video_stream_codec — happy path
# ---------------------------------------------------------------------------

def test_probe_video_stream_codec_parses_codec_name(monkeypatch):
    """probe_video_stream_codec() returns the stripped codec name from ffprobe stdout."""
    from io_ import media_probe

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(args=_cmd, returncode=0, stdout="h264\n", stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)

    result = media_probe.probe_video_stream_codec("fake.mp4")

    assert result == "h264", f"Expected 'h264', got {result!r}"


# ---------------------------------------------------------------------------
# probe_video_stream_codec — error conditions
# ---------------------------------------------------------------------------

def test_probe_video_stream_codec_raises_on_nonzero_returncode(monkeypatch):
    """RuntimeError must be raised when ffprobe exits with a non-zero return code."""
    from io_ import media_probe

    def _fake_run(_cmd, capture_output, text):
        return subprocess.CompletedProcess(
            args=_cmd, returncode=1, stdout="", stderr="Invalid data found"
        )

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)

    try:
        media_probe.probe_video_stream_codec("fake.mp4")
        raise AssertionError("Expected RuntimeError for non-zero return code")
    except RuntimeError as e:
        assert "ffprobe failed" in str(e).lower(), f"Unexpected message: {e}"
        assert "Invalid data found" in str(e), f"stderr not included in message: {e}"


def test_probe_video_stream_codec_raises_on_missing_ffprobe(monkeypatch):
    """RuntimeError must be raised when ffprobe binary is absent from PATH."""
    from io_ import media_probe

    def _raise(_cmd, capture_output, text):
        raise FileNotFoundError("ffprobe not on PATH")

    monkeypatch.setattr(media_probe.subprocess, "run", _raise)

    try:
        media_probe.probe_video_stream_codec("fake.mp4")
        raise AssertionError("Expected RuntimeError for missing ffprobe")
    except RuntimeError as e:
        assert "ffprobe not found on path" in str(e).lower(), f"Unexpected message: {e}"


# ---------------------------------------------------------------------------
# Helpers for render_audio_phase tests
# ---------------------------------------------------------------------------

@dataclass
class _FakeFilter:
    """Minimal AudioFilter stand-in for unit tests."""
    filter_name: str
    params: Dict[str, Any]


def _compile_stream(stream) -> list[str]:
    """Compile an ffmpeg-python stream to a list of command-line args (no exec)."""
    import ffmpeg
    return ffmpeg.compile(stream, overwrite_output=True)


# ---------------------------------------------------------------------------
# render_audio_phase — single segment (no asplit expected)
# ---------------------------------------------------------------------------

def test_render_audio_phase_single_segment_no_asplit():
    """Single segment + no filters: atrim applied, no asplit node in command."""
    captured = {}

    def _fake_run_with_progress(stream, **kwargs):
        captured["args"] = _compile_stream(stream)

    with patch("io_.video_renderer_twophase.run_with_progress", _fake_run_with_progress):
        from io_.video_renderer_twophase import render_audio_phase

        render_audio_phase(
            input_path="fake.mp4",
            filters=[],
            keep_segments=[(0.0, 5.0)],
            out_path="fake_audio.aac",
            audio_opts={"acodec": "aac"},
        )

    assert captured, "run_with_progress was never called"
    args = " ".join(captured["args"])

    # atrim must appear — one segment should still be trimmed
    assert "atrim" in args, f"Expected 'atrim' in compiled args; got:\n{args}"
    # asplit must NOT appear — only one segment, no splitting needed
    assert "asplit" not in args, f"Unexpected 'asplit' in compiled args:\n{args}"
    # vn flag must suppress video
    assert "-vn" in captured["args"], f"Expected '-vn' flag; args={captured['args']}"


# ---------------------------------------------------------------------------
# render_audio_phase — multiple segments with filters (asplit expected)
# ---------------------------------------------------------------------------

def test_render_audio_phase_with_filters():
    """Multiple segments + filter path applies filters before per-segment atrim."""
    captured = {}

    def _fake_run_with_progress(stream, **kwargs):
        captured["args"] = _compile_stream(stream)

    alimiter = _FakeFilter(filter_name="alimiter", params={"limit": 1.0, "level": "disabled"})

    with patch("io_.video_renderer_twophase.run_with_progress", _fake_run_with_progress):
        from io_.video_renderer_twophase import render_audio_phase

        render_audio_phase(
            input_path="fake.mp4",
            filters=[alimiter],
            keep_segments=[(0.0, 5.0), (10.0, 15.0)],
            out_path="fake_audio.aac",
            audio_opts={"acodec": "aac"},
        )

    assert captured, "run_with_progress was never called"
    args = " ".join(captured["args"])

    # asplit must appear — multi-segment + filter path
    assert "asplit" in args, f"Expected 'asplit' in compiled args; got:\n{args}"
    # atrim must appear for each segment
    assert "atrim" in args, f"Expected 'atrim' in compiled args; got:\n{args}"
    # concat must join the two segments
    assert "concat" in args, f"Expected 'concat' in compiled args; got:\n{args}"
    # the audio filter itself must appear
    assert "alimiter" in args, f"Expected 'alimiter' in compiled args; got:\n{args}"
    assert args.index("alimiter") < args.index("atrim"), (
        f"Expected filter to be applied before atrim; got:\n{args}"
    )
    # vn flag must suppress video
    assert "-vn" in captured["args"], f"Expected '-vn' flag; args={captured['args']}"


# ---------------------------------------------------------------------------
# classify_segments_by_keyframe — exact keyframe hit => copy
# ---------------------------------------------------------------------------

def test_classify_segments_exact_keyframe_hit_is_copy():
    """Segment starting exactly on a keyframe must be classified as 'copy'."""
    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = [0.0, 2.5, 5.0, 10.0]
    keep_segments = [(5.0, 8.0)]

    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert len(result) == 1
    seg = result[0]
    assert seg["type"] == "copy", f"Expected 'copy', got {seg['type']!r}"
    assert seg["kf_start"] == 5.0, f"Expected kf_start=5.0, got {seg['kf_start']}"
    assert seg["start"] == 5.0
    assert seg["end"] == 8.0


# ---------------------------------------------------------------------------
# classify_segments_by_keyframe — within tolerance => copy snapped to keyframe
# ---------------------------------------------------------------------------

def test_classify_segments_within_tolerance_is_copy_snapped():
    """Segment starting within snap_tolerance_s of a keyframe snaps to that keyframe."""
    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = [0.0, 2.5, 5.0]
    # Start is 0.05 s away from keyframe 2.5 — within default tolerance of 0.1 s
    keep_segments = [(2.55, 4.0)]

    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert len(result) == 1
    seg = result[0]
    assert seg["type"] == "copy", f"Expected 'copy' within tolerance, got {seg['type']!r}"
    assert seg["kf_start"] == 2.5, f"Expected kf_start snapped to 2.5, got {seg['kf_start']}"
    assert seg["start"] == 2.55


# ---------------------------------------------------------------------------
# classify_segments_by_keyframe — nearest keyframe is AFTER start => bridge
# (old code incorrectly classified this as 'copy', causing A/V de-sync)
# ---------------------------------------------------------------------------

def test_classify_segments_keyframe_after_start_is_bridge():
    """Nearest keyframe AFTER start must not be used for copy — must bridge instead.

    When the only keyframe near 'start' is AFTER 'start', the old code would
    classify as 'copy' with kf_start > start.  render_video_segment_copy would
    then seek PAST the segment start, dropping leading frames.  The fix ensures
    only keyframes AT OR BEFORE start are considered for 'copy' eligibility.
    """
    from io_.video_renderer_twophase import classify_segments_by_keyframe

    # Keyframe at 3.0 is 0.05 s AFTER start=2.95 — within old tolerance of 0.1 s
    # but must NOT be used because it's after start.
    keyframes = [0.0, 3.0, 6.0]
    keep_segments = [(2.95, 5.0)]

    result = classify_segments_by_keyframe(keep_segments, keyframes, snap_tolerance_s=0.1)

    assert len(result) == 1
    seg = result[0]
    # kf_before (largest kf <= 2.95) is 0.0; distance = 2.95 > 0.1 -> bridge
    assert seg["type"] == "bridge", (
        f"Segment with nearest-kf AFTER start must be 'bridge', got {seg['type']!r}"
    )
    # kf_start must be the largest keyframe <= start (0.0), not the keyframe after start (3.0)
    assert seg["kf_start"] == 0.0, (
        f"kf_start must be largest kf <= start (0.0), not kf after start; got {seg['kf_start']}"
    )


# ---------------------------------------------------------------------------
# classify_segments_by_keyframe — outside tolerance => bridge with preceding kf
# ---------------------------------------------------------------------------

def test_classify_segments_outside_tolerance_is_bridge():
    """Segment starting further than tolerance from any keyframe is classified 'bridge'."""
    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = [0.0, 2.0, 5.0]
    # Start 3.5 is 1.5 s from 2.0 and 1.5 s from 5.0 — both beyond default 0.1 s tolerance
    # Largest keyframe <= 3.5 is 2.0
    keep_segments = [(3.5, 4.5)]

    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert len(result) == 1
    seg = result[0]
    assert seg["type"] == "bridge", f"Expected 'bridge' outside tolerance, got {seg['type']!r}"
    assert seg["kf_start"] == 2.0, f"Expected kf_start=2.0 (largest kf <= 3.5), got {seg['kf_start']}"
    assert seg["start"] == 3.5


# ---------------------------------------------------------------------------
# classify_segments_by_keyframe — empty keyframes => all bridge / kf_start=0.0
# ---------------------------------------------------------------------------

def test_classify_all_bridge():
    """When keyframes list is empty, all segments must be 'bridge' with kf_start=0.0."""
    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = []
    keep_segments = [(1.0, 3.0), (5.0, 7.0), (10.0, 12.0)]

    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert len(result) == 3, f"Expected 3 segments, got {len(result)}"
    for i, seg in enumerate(result):
        assert seg["type"] == "bridge", f"Segment {i}: expected 'bridge', got {seg['type']!r}"
        assert seg["kf_start"] == 0.0, f"Segment {i}: expected kf_start=0.0, got {seg['kf_start']}"


# ---------------------------------------------------------------------------
# render_audio_phase — no segments (full audio passthrough)
# ---------------------------------------------------------------------------

def test_render_audio_phase_no_segments():
    """Empty keep_segments: no atrim, no asplit, no concat in compiled graph."""
    captured = {}

    def _fake_run_with_progress(stream, **kwargs):
        captured["args"] = _compile_stream(stream)

    with patch("io_.video_renderer_twophase.run_with_progress", _fake_run_with_progress):
        from io_.video_renderer_twophase import render_audio_phase

        render_audio_phase(
            input_path="fake.mp4",
            filters=[],
            keep_segments=[],
            out_path="fake_audio.aac",
            audio_opts={"acodec": "aac"},
        )

    assert captured, "run_with_progress was never called"
    args = " ".join(captured["args"])

    # No trimming or splitting — full passthrough
    assert "atrim" not in args, f"Unexpected 'atrim' in no-segment args:\n{args}"
    assert "asplit" not in args, f"Unexpected 'asplit' in no-segment args:\n{args}"
    assert "concat" not in args, f"Unexpected 'concat' in no-segment args:\n{args}"
    # vn flag must suppress video
    assert "-vn" in captured["args"], f"Expected '-vn' flag; args={captured['args']}"


# ---------------------------------------------------------------------------
# render_video_single_pass — helper routing and CUDA decode input kwargs
# ---------------------------------------------------------------------------

def test_render_video_single_pass_calls_filter_chain(monkeypatch):
    """Single-pass helper merges segments, builds the filter chain, and runs ffmpeg output."""
    from io_ import video_renderer_twophase as _tp

    calls: dict = {}
    filters = [_FakeFilter("alimiter", {"limit": 1.0})]
    keep_segments = [(0.0, 1.0), (1.02, 2.0)]
    merged_segments = [(0.0, 2.0)]
    enc_opts = {"vcodec": "libx264", "crf": 18}

    def _fake_merge_close_segments(segs):
        calls["merge_close_segments"] = list(segs)
        return list(merged_segments)

    def _fake_build_filter_chain(input_path, routed_filters, segs, input_kwargs, cut_fade_s=0.0):
        calls["build_filter_chain"] = {
            "input_path": input_path,
            "filters": routed_filters,
            "segs": list(segs),
            "input_kwargs": dict(input_kwargs),
            "cut_fade_s": cut_fade_s,
        }
        return ("fake_v", "fake_a")

    def _fake_output(v_stream, a_stream, out_path, **kwargs):
        calls["ffmpeg_output"] = {
            "v_stream": v_stream,
            "a_stream": a_stream,
            "out_path": out_path,
            "kwargs": dict(kwargs),
        }
        return "fake_stream"

    def _fake_run_with_progress(stream, **kwargs):
        calls["run_with_progress"] = {"stream": stream, "kwargs": dict(kwargs)}

    monkeypatch.setattr(_tp, "merge_close_segments", _fake_merge_close_segments)
    monkeypatch.setattr(_tp, "_build_filter_chain", _fake_build_filter_chain)
    monkeypatch.setattr(_tp.ffmpeg, "output", _fake_output)
    monkeypatch.setattr(_tp, "run_with_progress", _fake_run_with_progress)

    _tp.render_video_single_pass(
        input_path="host.mp4",
        filters=filters,
        keep_segments=keep_segments,
        out_path="host_out.mp4",
        enc_opts=enc_opts,
        config={"cut_fade_ms": 16},
    )

    assert "build_input_kwargs" not in calls, "CUDA decode kwargs should not be built unless enabled"
    assert calls["merge_close_segments"] == keep_segments
    assert calls["build_filter_chain"] == {
        "input_path": "host.mp4",
        "filters": filters,
        "segs": merged_segments,
        "input_kwargs": {},
        "cut_fade_s": 0.016,
    }
    assert calls["ffmpeg_output"] == {
        "v_stream": "fake_v",
        "a_stream": "fake_a",
        "out_path": "host_out.mp4",
        "kwargs": enc_opts,
    }
    assert calls["run_with_progress"] == {
        "stream": "fake_stream",
        "kwargs": {"overwrite_output": True},
    }


def test_render_video_single_pass_cuda_decode_routes_input_kwargs(monkeypatch):
    """Single-pass must ignore CUDA decode config and use CPU-side filter input kwargs."""
    from io_ import video_renderer_twophase as _tp

    calls: dict = {}
    config = {"cuda_decode_enabled": True, "cut_fade_ms": 24}

    def _fake_build_filter_chain(input_path, filters, segs, routed_input_kwargs, cut_fade_s=0.0):
        calls["build_filter_chain"] = {
            "input_path": input_path,
            "filters": list(filters),
            "segs": list(segs),
            "input_kwargs": dict(routed_input_kwargs),
            "cut_fade_s": cut_fade_s,
        }
        return ("gpu_v", "gpu_a")

    monkeypatch.setattr(_tp, "merge_close_segments", lambda segs: list(segs))
    monkeypatch.setattr(_tp, "_build_filter_chain", _fake_build_filter_chain)
    monkeypatch.setattr(_tp.ffmpeg, "output", lambda *args, **kwargs: "gpu_stream")
    monkeypatch.setattr(_tp, "run_with_progress", lambda stream, **kwargs: calls.__setitem__(
        "run_with_progress", {"stream": stream, "kwargs": dict(kwargs)}
    ))

    _tp.render_video_single_pass(
        input_path="guest.mp4",
        filters=[],
        keep_segments=[(0.0, 5.0)],
        out_path="guest_out.mp4",
        enc_opts={"vcodec": "h264_nvenc", "cq": 18},
        config=config,
    )

    assert calls["build_filter_chain"] == {
        "input_path": "guest.mp4",
        "filters": [],
        "segs": [(0.0, 5.0)],
        "input_kwargs": {},
        "cut_fade_s": 0.024,
    }
    assert calls["run_with_progress"] == {
        "stream": "gpu_stream",
        "kwargs": {"overwrite_output": True},
    }


def test_render_video_batched_gpu_cuda_decode_routes_input_kwargs(monkeypatch, tmp_path):
    """batched_gpu must forward CUDA decode kwargs into each batch when enabled."""
    import ffmpeg
    import io_.video_renderer as _vr
    import io_.video_renderer_progress as _vr_progress
    from io_ import video_renderer_strategies as _strategies

    calls: dict = {"filter_chain": []}
    caps = {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset({"cuda"})}
    input_kwargs = {"hwaccel": "cuda", "hwaccel_output_format": "cuda"}

    monkeypatch.setattr(_strategies, "merge_close_segments", lambda segs: list(segs))
    monkeypatch.setattr(_strategies.os, "close", lambda fd: None)
    monkeypatch.setattr(_strategies.os, "remove", lambda path: None)
    monkeypatch.setattr(_strategies, "gpu_workers_from_pct", lambda pct: 1)

    def _fake_mkstemp(prefix, suffix, dir):
        if suffix == ".txt":
            return (99, str(tmp_path / "concat_batch_00.txt"))
        return (99, str(tmp_path / ".batch00.mp4"))

    monkeypatch.setattr(_strategies.tempfile, "mkstemp", _fake_mkstemp)

    monkeypatch.setattr(_vr, "probe_ffmpeg_capabilities", lambda: caps)
    monkeypatch.setattr(_vr, "build_input_kwargs", lambda cfg, routed_caps: calls.__setitem__(
        "build_input_kwargs", {"cfg": dict(cfg), "caps": routed_caps}
    ) or dict(input_kwargs))

    def _fake_build_filter_chain(input_path, filters, segs, routed_input_kwargs, cut_fade_s=0.0):
        calls["filter_chain"].append(
            {
                "input_path": input_path,
                "filters": list(filters),
                "segs": list(segs),
                "input_kwargs": dict(routed_input_kwargs),
                "cut_fade_s": cut_fade_s,
            }
        )
        return ("batch_v", "batch_a")

    monkeypatch.setattr(_vr, "_build_filter_chain", _fake_build_filter_chain)
    monkeypatch.setattr(ffmpeg, "output", lambda *args, **kwargs: "batch_stream")
    monkeypatch.setattr(
        _vr_progress,
        "run_with_progress",
        lambda stream, **kwargs: calls.__setitem__("run_with_progress", {"stream": stream, "kwargs": dict(kwargs)}),
    )

    def _fake_subprocess_run(*args, **kwargs):
        calls["concat_run"] = {"args": list(args[0]), "kwargs": dict(kwargs)}
        return _strategies.subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_strategies.subprocess, "run", _fake_subprocess_run)

    _strategies.render_video_batched_gpu(
        input_path="guest.mp4",
        filters=["eq=contrast=1.1"],
        keep_segments=[(0.0, 2.0)],
        out_path=str(tmp_path / "guest_out.mp4"),
        enc_opts={"vcodec": "h264_nvenc", "cq": 18},
        config={"cuda_decode_enabled": True, "cut_fade_ms": 20, "gpu_limit_pct": 20},
        num_batches=1,
    )

    assert calls["build_input_kwargs"] == {"cfg": {"cuda_decode_enabled": True, "cut_fade_ms": 20, "gpu_limit_pct": 20}, "caps": caps}
    assert calls["filter_chain"] == [
        {
            "input_path": "guest.mp4",
            "filters": ["eq=contrast=1.1"],
            "segs": [(0.0, 2.0)],
            "input_kwargs": input_kwargs,
            "cut_fade_s": 0.02,
        }
    ]
    assert calls["run_with_progress"] == {
        "stream": "batch_stream",
        "kwargs": {"overwrite_output": True},
    }
    assert calls["concat_run"]["args"][-2:] == ["copy", str(tmp_path / "guest_out.mp4")]


# ---------------------------------------------------------------------------
# render_video_segment_copy -- correct command shape
# ---------------------------------------------------------------------------

def test_render_video_segment_copy_command_args(monkeypatch):
    """Verify FFmpeg command args: -ss before -i, -c:v copy, -an, -avoid_negative_ts, -t duration."""
    import subprocess as _sp
    from io_ import video_renderer_twophase

    captured = {}

    def _fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_run)

    # kf_start == start: exact keyframe hit, no output-side -ss needed
    video_renderer_twophase.render_video_segment_copy(
        input_path="source.mp4",
        kf_start=2.5,
        start=2.5,
        end=8.0,
        out_path="seg_out.mp4",
    )

    assert captured, "subprocess.run was never called"
    cmd = captured["cmd"]

    # input-side -ss must appear BEFORE -i
    assert "-ss" in cmd, f"Expected '-ss' in cmd: {cmd}"
    assert "-i" in cmd, f"Expected '-i' in cmd: {cmd}"
    ss_idx = cmd.index("-ss")
    i_idx = cmd.index("-i")
    assert ss_idx < i_idx, (
        f"-ss (index {ss_idx}) must come before -i (index {i_idx}); cmd={cmd}"
    )

    # -ss value must equal kf_start
    assert cmd[ss_idx + 1] == "2.5", f"Expected -ss value '2.5', got {cmd[ss_idx + 1]!r}"

    # -to must NOT appear (replaced by -t for exact duration)
    assert "-to" not in cmd, f"'-to' must not appear; use '-t' instead; cmd={cmd}"

    # -t value must equal end - start = 5.5
    assert "-t" in cmd, f"Expected '-t' in cmd: {cmd}"
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "5.5", f"Expected -t value '5.5' (end - start), got {cmd[t_idx + 1]!r}"

    # input file follows -i
    assert cmd[i_idx + 1] == "source.mp4", (
        f"Expected input 'source.mp4' after -i, got {cmd[i_idx + 1]!r}"
    )

    # stream-copy flags
    assert "-c:v" in cmd, f"Expected '-c:v' in cmd: {cmd}"
    cv_idx = cmd.index("-c:v")
    assert cmd[cv_idx + 1] == "copy", f"Expected '-c:v copy', got {cmd[cv_idx + 1]!r}"

    # audio suppression
    assert "-an" in cmd, f"Expected '-an' in cmd: {cmd}"

    # avoid_negative_ts
    assert "-avoid_negative_ts" in cmd, f"Expected '-avoid_negative_ts' in cmd: {cmd}"
    avts_idx = cmd.index("-avoid_negative_ts")
    assert cmd[avts_idx + 1] == "1", (
        f"Expected '-avoid_negative_ts 1', got {cmd[avts_idx + 1]!r}"
    )

    # output path is last arg
    assert cmd[-1] == "seg_out.mp4", f"Expected output path last; got {cmd[-1]!r}"


# ---------------------------------------------------------------------------
# render_video_segment_copy -- output-side trim when kf_start < start
# ---------------------------------------------------------------------------

def test_render_video_segment_copy_output_side_trim_when_kf_before_start(monkeypatch):
    """When kf_start < start, output-side -ss (extra) and -t (duration) must be added."""
    import subprocess as _sp
    from io_ import video_renderer_twophase

    captured = {}

    def _fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_run)

    # kf_start=2.5, start=2.55, end=8.0 -> extra=0.05, duration=5.45
    video_renderer_twophase.render_video_segment_copy(
        input_path="source.mp4",
        kf_start=2.5,
        start=2.55,
        end=8.0,
        out_path="seg_out.mp4",
    )

    assert captured, "subprocess.run was never called"
    cmd = captured["cmd"]

    # There must be TWO -ss occurrences: input-side (kf_start=2.5) and output-side (extra≈0.05)
    ss_indices = [i for i, tok in enumerate(cmd) if tok == "-ss"]
    assert len(ss_indices) == 2, (
        f"Expected 2 '-ss' flags (input-side + output-side), got {len(ss_indices)}; cmd={cmd}"
    )
    assert abs(float(cmd[ss_indices[0] + 1]) - 2.5) < 1e-9, (
        f"First -ss must be kf_start≈2.5, got {cmd[ss_indices[0] + 1]!r}"
    )
    assert abs(float(cmd[ss_indices[1] + 1]) - 0.05) < 1e-9, (
        f"Second -ss (output-side) must be extra≈0.05, got {cmd[ss_indices[1] + 1]!r}"
    )

    # -t must equal duration = end - start ≈ 5.45
    assert "-t" in cmd, f"Expected '-t' in cmd: {cmd}"
    t_idx = cmd.index("-t")
    t_val = float(cmd[t_idx + 1])
    assert abs(t_val - 5.45) < 1e-9, f"Expected -t ~5.45, got {t_val}"

    # -to must NOT appear
    assert "-to" not in cmd, f"'-to' must not appear in output; cmd={cmd}"

    # output path is still last
    assert cmd[-1] == "seg_out.mp4", f"Expected output path last; got {cmd[-1]!r}"


# ---------------------------------------------------------------------------
# render_video_segment_copy -- RuntimeError on non-zero return code
# ---------------------------------------------------------------------------

def test_render_video_segment_copy_raises_runtime_error_on_failure(monkeypatch):
    """RuntimeError must be raised on non-zero FFmpeg exit code, including stderr."""
    import subprocess as _sp
    from io_ import video_renderer_twophase

    def _fake_run(cmd, capture_output, text):
        return _sp.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="Invalid argument: bad seek"
        )

    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_run)

    try:
        video_renderer_twophase.render_video_segment_copy(
            input_path="bad.mp4",
            kf_start=0.0,
            start=0.0,
            end=5.0,
            out_path="out.mp4",
        )
        raise AssertionError("Expected RuntimeError but no exception was raised")
    except RuntimeError as exc:
        assert "Invalid argument: bad seek" in str(exc), (
            f"Expected stderr in RuntimeError message; got: {exc}"
        )


# ---------------------------------------------------------------------------
# render_video_segment_bridge — trim offset computation
# ---------------------------------------------------------------------------

def test_render_video_segment_bridge_trim_offsets(monkeypatch):
    """trim_start and trim_end are computed as start - kf_before and end - kf_before."""
    import subprocess as _sp
    from io_ import video_renderer_twophase

    captured = {}

    def _fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_run)

    video_renderer_twophase.render_video_segment_bridge(
        input_path="source.mp4",
        kf_before=2.0,
        start=3.5,
        end=7.0,
        out_path="bridge_out.mp4",
        enc_opts={"vcodec": "libx264", "crf": 18},
    )

    assert captured, "subprocess.run was never called"
    cmd_str = " ".join(captured["cmd"])
    # trim_start = 3.5 - 2.0 = 1.5, trim_end = 7.0 - 2.0 = 5.0
    assert "trim=start=1.5:end=5.0" in cmd_str, (
        f"Expected trim offsets 1.5/5.0; got:\n{cmd_str}"
    )
    assert "setpts=PTS-STARTPTS" in cmd_str, (
        f"Expected setpts=PTS-STARTPTS in vf filter; got:\n{cmd_str}"
    )


# ---------------------------------------------------------------------------
# render_video_segment_bridge — encoder flag mapping
# ---------------------------------------------------------------------------

def test_render_video_segment_bridge_encoder_flags(monkeypatch):
    """vcodec->-c:v, preset->-preset, crf->-crf are correctly mapped in the command."""
    import subprocess as _sp
    from io_ import video_renderer_twophase

    captured = {}

    def _fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_run)

    video_renderer_twophase.render_video_segment_bridge(
        input_path="source.mp4",
        kf_before=0.0,
        start=1.0,
        end=4.0,
        out_path="bridge_out.mp4",
        enc_opts={"vcodec": "libx264", "preset": "fast", "crf": 22},
    )

    assert captured, "subprocess.run was never called"
    cmd = captured["cmd"]

    assert "-c:v" in cmd, f"Expected '-c:v' in cmd: {cmd}"
    assert cmd[cmd.index("-c:v") + 1] == "libx264", f"Expected '-c:v libx264'; cmd={cmd}"

    assert "-preset" in cmd, f"Expected '-preset' in cmd: {cmd}"
    assert cmd[cmd.index("-preset") + 1] == "fast", f"Expected '-preset fast'; cmd={cmd}"

    assert "-crf" in cmd, f"Expected '-crf' in cmd: {cmd}"
    assert cmd[cmd.index("-crf") + 1] == "22", f"Expected '-crf 22'; cmd={cmd}"

    assert "-an" in cmd, f"Expected '-an' (audio suppression) in cmd: {cmd}"


# ---------------------------------------------------------------------------
# render_video_segment_bridge — audio-only keys excluded
# ---------------------------------------------------------------------------

def test_render_video_segment_bridge_excludes_audio_keys(monkeypatch):
    """acodec and audio_bitrate must not appear anywhere in the FFmpeg command."""
    import subprocess as _sp
    from io_ import video_renderer_twophase

    captured = {}

    def _fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_run)

    video_renderer_twophase.render_video_segment_bridge(
        input_path="source.mp4",
        kf_before=1.0,
        start=2.0,
        end=5.0,
        out_path="bridge_out.mp4",
        enc_opts={
            "vcodec": "libx264",
            "crf": 22,
            "acodec": "aac",         # must be excluded
            "audio_bitrate": "128k", # must be excluded
        },
    )

    assert captured, "subprocess.run was never called"
    cmd = captured["cmd"]

    assert "-acodec" not in cmd, f"Unexpected '-acodec' in cmd: {cmd}"
    assert "aac" not in cmd, f"Unexpected 'aac' value (audio codec) in cmd: {cmd}"
    assert "-audio_bitrate" not in cmd, f"Unexpected '-audio_bitrate' in cmd: {cmd}"
    assert "128k" not in cmd, f"Unexpected '128k' value (audio bitrate) in cmd: {cmd}"


# ---------------------------------------------------------------------------
# render_video_segment_bridge — RuntimeError on non-zero return code
# ---------------------------------------------------------------------------

def test_render_video_segment_bridge_raises_runtime_error_on_failure(monkeypatch):
    """RuntimeError must be raised on non-zero FFmpeg exit code, stderr included."""
    import subprocess as _sp
    from io_ import video_renderer_twophase

    def _fake_run(cmd, capture_output, text):
        return _sp.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="Encoder not found: libx264"
        )

    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_run)

    try:
        video_renderer_twophase.render_video_segment_bridge(
            input_path="bad.mp4",
            kf_before=0.0,
            start=1.0,
            end=3.0,
            out_path="out.mp4",
            enc_opts={"vcodec": "libx264"},
        )
        raise AssertionError("Expected RuntimeError but no exception was raised")
    except RuntimeError as exc:
        assert "Encoder not found: libx264" in str(exc), (
            f"Expected stderr in RuntimeError message; got: {exc}"
        )


# ---------------------------------------------------------------------------
# render_video_smart_copy — concat list contains correct file paths in order
# ---------------------------------------------------------------------------

def test_render_video_smart_copy_concat_list_order(tmp_path, monkeypatch):
    """Concat list must contain absolute paths + duration directives for each segment, in order."""
    import subprocess as _sp
    from io_ import video_renderer_twophase

    captured_concat = {}

    def _fake_copy(input_path, kf_start, start, end, out_path):
        # File already created by mkstemp; nothing extra needed.
        pass

    def _fake_bridge(input_path, kf_before, start, end, out_path, enc_opts):
        pass

    def _fake_subprocess_run(cmd, capture_output, text):
        # Intercept the concat command, read the list file before cleanup.
        i_idx = cmd.index("-i")
        concat_list_path = cmd[i_idx + 1]
        with open(concat_list_path, "r", encoding="utf-8") as fh:
            captured_concat["content"] = fh.read()
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_renderer_twophase, "render_video_segment_copy", _fake_copy)
    monkeypatch.setattr(video_renderer_twophase, "render_video_segment_bridge", _fake_bridge)
    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_subprocess_run)

    out_path = str(tmp_path / "output.mp4")
    # Keyframes: 0.0, 5.0, 8.0 -> segment (0.0,1.5) is copy, (3.0,4.5) is bridge, (8.0,10.0) is copy
    keyframes = [0.0, 5.0, 8.0]
    keep_segments = [(0.0, 1.5), (3.0, 4.5), (8.0, 10.0)]

    video_renderer_twophase.render_video_smart_copy(
        input_path="source.mp4",
        keep_segments=keep_segments,
        keyframes=keyframes,
        out_path=out_path,
        enc_opts={"vcodec": "libx264"},
    )

    assert "content" in captured_concat, "subprocess.run (concat) was never called"
    lines = [ln for ln in captured_concat["content"].splitlines() if ln.strip()]

    # Two lines per segment: 'file ...' followed by 'duration ...'
    assert len(lines) == 6, f"Expected 6 lines in concat list (3 file + 3 duration), got {len(lines)}: {lines}"

    # Extract file lines and duration lines
    file_lines = [ln for ln in lines if ln.startswith("file ")]
    duration_lines = [ln for ln in lines if ln.startswith("duration ")]
    assert len(file_lines) == 3, f"Expected 3 file lines, got {len(file_lines)}"
    assert len(duration_lines) == 3, f"Expected 3 duration lines, got {len(duration_lines)}"

    # File lines must alternate with duration lines: file, duration, file, duration, ...
    for i in range(3):
        assert lines[i * 2].startswith("file '"), (
            f"Line {i*2} should be a file directive; got: {lines[i*2]!r}"
        )
        assert lines[i * 2 + 1].startswith("duration "), (
            f"Line {i*2+1} should be a duration directive; got: {lines[i*2+1]!r}"
        )

    # Each file line must have the format:  file '<absolute_path>'
    for line in file_lines:
        assert line.endswith("'"), f"Expected line ending with \"'\"; got: {line!r}"
        inner_path = line[len("file '"):-1]
        from pathlib import Path as _Path
        assert _Path(inner_path).is_absolute(), (
            f"Expected absolute path in concat list, got: {inner_path!r}"
        )

    # Duration values must match expected segment durations (end - start)
    expected_durations = [1.5, 1.5, 2.0]
    for dur_line, expected in zip(duration_lines, expected_durations):
        val = float(dur_line.split()[1])
        assert abs(val - expected) < 1e-4, (
            f"Expected duration {expected}, got {val} in line: {dur_line!r}"
        )

    # Verify ordering: paths must appear in the same order as classified segments
    paths_in_list = [ln[len("file '"):-1] for ln in file_lines]
    # All paths must be distinct temp files inside tmp_path
    assert len(set(paths_in_list)) == 3, f"Expected 3 distinct paths, got: {paths_in_list}"


# ---------------------------------------------------------------------------
# render_video_smart_copy — temp files cleaned up on success
# ---------------------------------------------------------------------------

def test_render_video_smart_copy_cleanup_on_success(tmp_path, monkeypatch):
    """All temp segment files and concat list must be deleted after successful run."""
    import subprocess as _sp
    import tempfile as _tempfile
    from io_ import video_renderer_twophase

    tracked_tmps: list = []
    _real_mkstemp = _tempfile.mkstemp

    def _tracking_mkstemp(suffix=None, dir=None):
        fd, path = _real_mkstemp(suffix=suffix, dir=dir)
        tracked_tmps.append(path)
        return fd, path

    def _fake_copy(input_path, kf_start, start, end, out_path):
        pass

    def _fake_subprocess_run(cmd, capture_output, text):
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(video_renderer_twophase, "render_video_segment_copy", _fake_copy)
    monkeypatch.setattr(video_renderer_twophase.subprocess, "run", _fake_subprocess_run)
    monkeypatch.setattr(video_renderer_twophase.tempfile, "mkstemp", _tracking_mkstemp)

    out_path = str(tmp_path / "output.mp4")

    video_renderer_twophase.render_video_smart_copy(
        input_path="source.mp4",
        keep_segments=[(0.0, 5.0), (10.0, 15.0)],
        keyframes=[0.0, 10.0],   # both exact matches -> copy
        out_path=out_path,
        enc_opts={"vcodec": "libx264"},
    )

    # Expect 2 segment files + 1 concat list = 3 total tracked temp files
    assert len(tracked_tmps) == 3, (
        f"Expected 3 temp files (2 segments + 1 concat list), got {len(tracked_tmps)}"
    )

    # Every tracked temp file must have been deleted
    from pathlib import Path as _Path
    for path in tracked_tmps:
        assert not _Path(path).exists(), f"Temp file was not cleaned up: {path}"


# ---------------------------------------------------------------------------
# render_video_smart_copy — temp files cleaned up when segment render raises
# ---------------------------------------------------------------------------

def test_render_video_smart_copy_temp_cleanup_on_failure(tmp_path, monkeypatch):
    """Temp files are cleaned up even when one segment render fails after all temps exist."""
    import tempfile as _tempfile
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

    monkeypatch.setattr(video_renderer_twophase, "render_video_segment_copy", _fake_copy_maybe_raises)
    monkeypatch.setattr(video_renderer_twophase.tempfile, "mkstemp", _tracking_mkstemp)

    out_path = str(tmp_path / "output.mp4")

    raised_exc = None
    try:
        video_renderer_twophase.render_video_smart_copy(
            input_path="source.mp4",
            keep_segments=[(0.0, 5.0), (8.0, 12.0), (16.0, 20.0)],
            keyframes=[0.0, 8.0, 16.0],
            out_path=out_path,
            enc_opts={"vcodec": "libx264"},
        )
        raise AssertionError("Expected RuntimeError but no exception was raised")
    except RuntimeError as exc:
        raised_exc = exc

    assert raised_exc is not None, "No exception was propagated"
    assert "Segment copy failed" in str(raised_exc), (
        f"Unexpected exception message: {raised_exc}"
    )

    # Temp segment files must be cleaned up despite the failure.
    # This covers already-created temp files for other segments too.
    assert tracked_tmps, "No temp files were created (test is invalid)"
    from pathlib import Path as _Path
    for path in tracked_tmps:
        assert not _Path(path).exists(), (
            f"Temp file was not cleaned up after segment failure: {path}"
        )


# ===========================================================================
# Phase 3 Task 10: render_project_two_phase — sub-phase orchestration tests
# ===========================================================================

@dataclass
class _ManifestTP:
    """Minimal manifest stand-in for render_project_two_phase tests."""
    keep_segments: list
    host_filters: list
    guest_filters: list


def _apply_common_twophase_mocks(monkeypatch, source_codec="h264"):
    """Patch all two-phase sub-phases with no-op stubs; return captured-calls dict."""
    import subprocess as _sp
    import io_.video_renderer as _vr
    from io_ import video_renderer_twophase as _tp

    captured: dict = {
        "audio_phase": [],
        "keyframe_probes": [],
        "smart_copy": [],
        "mux_cmds": [],
        "duration_probes": [],
    }

    monkeypatch.setattr(_vr, "probe_ffmpeg_capabilities",
                        lambda: {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset()})
    monkeypatch.setattr(_vr, "select_enc_opts",
                        lambda cfg, caps: {"vcodec": "libx264", "acodec": "aac", "audio_bitrate": "192k"})
    monkeypatch.setattr(_tp, "probe_video_stream_codec", lambda p: source_codec)
    # Stub probe_video_fps so its ffprobe subprocess call is not captured by the
    # mux_cmds interceptor (which patches subprocess.run globally via _tp.subprocess).
    monkeypatch.setattr(_tp, "probe_video_fps", lambda p: None)

    def _fake_duration(p):
        captured["duration_probes"].append(p)
        return 10.0
    monkeypatch.setattr(_tp, "get_video_duration_seconds", _fake_duration)

    def _fake_keyframes(p):
        captured["keyframe_probes"].append(p)
        return [0.0, 5.0]
    monkeypatch.setattr(_tp, "probe_video_keyframes", _fake_keyframes)

    def _fake_audio_phase(src, filters, segs, out, audio_opts):
        captured["audio_phase"].append({"src": src, "filters": filters, "segs": segs})
    monkeypatch.setattr(_tp, "render_audio_phase", _fake_audio_phase)

    def _fake_smart_copy(src, segs, kfs, out, enc_opts, snap, label="", gpu_limit_pct=100):
        captured["smart_copy"].append({"src": src, "segs": segs, "kfs": kfs})
    monkeypatch.setattr(_tp, "render_video_smart_copy", _fake_smart_copy)

    def _fake_mux(cmd, capture_output, text):
        captured["mux_cmds"].append(list(cmd))
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    monkeypatch.setattr(_tp.subprocess, "run", _fake_mux)

    monkeypatch.setattr(_tp, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))

    return captured


def test_render_project_two_phase_host_filters_routed(monkeypatch, tmp_path):
    """render_audio_phase receives manifest.host_filters for the host track."""
    from io_ import video_renderer_twophase as _tp

    host_f = _FakeFilter("alimiter", {"limit": 1.0})
    guest_f = _FakeFilter("loudnorm", {"I": -23})
    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[host_f], guest_filters=[guest_f])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest,
                                  str(tmp_path / "host.mp4"), None, config=None)

    assert len(captured["audio_phase"]) == 1, "Expected exactly one audio_phase call"
    assert captured["audio_phase"][0]["filters"] == [host_f], (
        "host_filters not routed correctly; got %r" % captured["audio_phase"][0]["filters"]
    )


def test_render_project_two_phase_guest_filters_routed(monkeypatch, tmp_path):
    """render_audio_phase receives manifest.guest_filters for the guest track."""
    from io_ import video_renderer_twophase as _tp

    host_f = _FakeFilter("alimiter", {"limit": 1.0})
    guest_f = _FakeFilter("loudnorm", {"I": -23})
    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[host_f], guest_filters=[guest_f])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest,
                                  None, str(tmp_path / "guest.mp4"), config=None)

    assert len(captured["audio_phase"]) == 1, "Expected exactly one audio_phase call"
    assert captured["audio_phase"][0]["filters"] == [guest_f], (
        "guest_filters not routed correctly; got %r" % captured["audio_phase"][0]["filters"]
    )


def test_render_project_two_phase_keyframes_probed_on_correct_path(monkeypatch, tmp_path):
    """probe_video_keyframes is called with the host source path, not the output path."""
    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase("actual_host.mp4", "guest.mp4", manifest,
                                  str(tmp_path / "host.mp4"), None, config=None)

    assert captured["keyframe_probes"] == ["actual_host.mp4"], (
        "Expected keyframes probed on host source; got %r" % captured["keyframe_probes"]
    )


def test_render_project_two_phase_smart_copy_receives_correct_args(monkeypatch, tmp_path):
    """render_video_smart_copy receives source path, keep_segments, and probed keyframes."""
    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch)
    segs = [(0.0, 3.0), (5.0, 8.0)]
    manifest = _ManifestTP(keep_segments=segs, host_filters=[], guest_filters=[])

    _tp.render_project_two_phase("src_host.mp4", "guest.mp4", manifest,
                                  str(tmp_path / "host.mp4"), None, config=None)

    assert len(captured["smart_copy"]) == 1, f"Expected 1 smart_copy call; got {len(captured['smart_copy'])}"
    call = captured["smart_copy"][0]
    assert call["src"] == "src_host.mp4", f"Unexpected src: {call['src']!r}"
    assert call["segs"] == segs, f"Unexpected segs: {call['segs']}"
    assert call["kfs"] == [0.0, 5.0], f"Unexpected keyframes: {call['kfs']}"


def test_render_project_two_phase_mux_uses_map_flags(monkeypatch, tmp_path):
    """FFmpeg mux command contains '-map 0:v', '-map 1:a', and '-shortest'."""
    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest,
                                  str(tmp_path / "host.mp4"), None, config=None)

    assert len(captured["mux_cmds"]) == 1, f"Expected 1 mux call; got {len(captured['mux_cmds'])}"
    cmd = captured["mux_cmds"][0]
    map_indices = [i for i, x in enumerate(cmd) if x == "-map"]
    assert len(map_indices) == 2, f"Expected exactly 2 -map flags; cmd={cmd}"
    assert cmd[map_indices[0] + 1] == "0:v", (
        f"First -map must be '0:v'; got {cmd[map_indices[0]+1]!r}"
    )
    assert cmd[map_indices[1] + 1] == "1:a", (
        f"Second -map must be '1:a'; got {cmd[map_indices[1]+1]!r}"
    )
    # -shortest prevents the longer track from extending past the shorter one,
    # guarding against residual cumulative duration mismatch between audio/video phases.
    assert "-shortest" in cmd, f"Expected '-shortest' in mux command; cmd={cmd}"


def test_render_project_two_phase_temp_cleanup_on_audio_raise(monkeypatch, tmp_path):
    """Temp audio and video files are removed even when render_audio_phase raises."""
    import tempfile as _tf
    import io_.video_renderer as _vr
    from io_ import video_renderer_twophase as _tp
    from pathlib import Path as _Path

    tracked_tmps: list = []
    _real_mkstemp = _tf.mkstemp

    def _tracking_mkstemp(suffix=None, dir=None):
        fd, path = _real_mkstemp(suffix=suffix, dir=dir)
        tracked_tmps.append(path)
        return fd, path

    monkeypatch.setattr(_vr, "probe_ffmpeg_capabilities",
                        lambda: {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset()})
    monkeypatch.setattr(_vr, "select_enc_opts",
                        lambda cfg, caps: {"vcodec": "libx264", "acodec": "aac", "audio_bitrate": "192k"})
    monkeypatch.setattr(_tp, "probe_video_stream_codec", lambda p: "h264")
    monkeypatch.setattr(_tp.tempfile, "mkstemp", _tracking_mkstemp)

    def _raise_audio(*a, **kw):
        raise RuntimeError("audio phase boom")
    monkeypatch.setattr(_tp, "render_audio_phase", _raise_audio)
    monkeypatch.setattr(_tp, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])
    raised = None
    try:
        _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest,
                                      str(tmp_path / "host.mp4"), None, config=None)
    except RuntimeError as exc:
        raised = exc

    assert raised is not None, "Expected RuntimeError to propagate"
    assert "audio phase boom" in str(raised)
    assert len(tracked_tmps) == 2, f"Expected 2 temp files (aac + mp4); got {tracked_tmps}"
    for p in tracked_tmps:
        assert not _Path(p).exists(), f"Temp file not cleaned up after audio raise: {p}"


def test_render_project_two_phase_empty_segments_use_full_duration(monkeypatch, tmp_path):
    """Empty manifest.keep_segments triggers get_video_duration_seconds to build full span."""
    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest,
                                  str(tmp_path / "host.mp4"), None, config=None)

    assert captured["duration_probes"], "Expected get_video_duration_seconds called for empty segments"
    assert len(captured["audio_phase"]) == 1
    assert captured["audio_phase"][0]["segs"] == [(0.0, 10.0)], (
        "Expected normalized full-span [(0.0, 10.0)]; got %r" % captured["audio_phase"][0]["segs"]
    )


def test_render_project_two_phase_falls_back_for_non_h264_source(monkeypatch, tmp_path):
    """Non-h264 codec uses single-pass video phase, then muxes with audio phase."""
    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch, source_codec="hevc")

    single_pass_calls: list = []

    def _fake_single_pass(src, filters, segs, out, enc_opts, cfg):
        single_pass_calls.append(
            {
                "src": src,
                "filters": filters,
                "segs": segs,
                "out": out,
                "enc_opts": dict(enc_opts),
                "cfg": cfg,
            }
        )

    monkeypatch.setattr(_tp, "render_video_single_pass", _fake_single_pass)

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest,
                                  str(tmp_path / "host.mp4"), None, config=None)

    assert len(single_pass_calls) == 1, "Expected single-pass video phase called for non-h264"
    assert len(captured["audio_phase"]) == 1, "render_audio_phase should still run for non-h264"
    assert not captured["keyframe_probes"], "probe_video_keyframes must NOT be called for non-h264"
    assert not captured["smart_copy"], "render_video_smart_copy must NOT be called for non-h264"
    assert len(captured["mux_cmds"]) == 1, "Mux should still run after single-pass video phase"


def test_render_track_routes_single_pass_strategy(monkeypatch, tmp_path):
    """Configured single-pass strategy routes the track through single-pass video rendering."""
    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch, source_codec="h264")

    single_pass_calls: list = []

    def _fake_single_pass(src, filters, segs, out, enc_opts, cfg):
        single_pass_calls.append(
            {
                "src": src,
                "filters": filters,
                "segs": segs,
                "out": out,
                "enc_opts": dict(enc_opts),
                "cfg": cfg,
            }
        )

    monkeypatch.setattr(_tp, "render_video_single_pass", _fake_single_pass)

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])
    config = {"video_phase_strategy": "single_pass"}

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest,
                                  str(tmp_path / "host.mp4"), None, config=config)

    assert len(single_pass_calls) == 1, "Expected single-pass video phase called once"
    assert single_pass_calls[0]["cfg"] is config, "Expected original config routed to single-pass helper"
    assert len(captured["audio_phase"]) == 1, "Audio phase should still run for single_pass strategy"
    assert not captured["keyframe_probes"], "probe_video_keyframes must NOT be called for single_pass strategy"
    assert not captured["smart_copy"], "render_video_smart_copy must NOT be called for single_pass strategy"
    assert len(captured["mux_cmds"]) == 1, "Mux should still run after single-pass video phase"


def test_render_track_routes_smart_copy_default(monkeypatch, tmp_path):
    """Default routing for h264 sources stays on the smart-copy branch."""
    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch, source_codec="h264")

    single_pass_calls: list = []

    def _fake_single_pass(*args, **kwargs):
        single_pass_calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(_tp, "render_video_single_pass", _fake_single_pass)

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host.mp4"),
        None,
        config={},
    )

    assert len(captured["audio_phase"]) == 1, "Audio phase should still run on the default smart-copy route"
    assert captured["keyframe_probes"] == ["host.mp4"], "Expected keyframe probing on the rendered track"
    assert len(captured["smart_copy"]) == 1, "Expected smart-copy video render on the default route"
    assert not single_pass_calls, "Single-pass helper must not be called on the default smart-copy route"
    assert len(captured["mux_cmds"]) == 1, "Mux should still run after smart-copy video phase"


def test_render_project_two_phase_dispatches_when_enabled(monkeypatch, tmp_path):
    """Enabled flag triggers the two-phase dispatcher and skips the single-pass path."""
    import io_.video_renderer as _vr
    from io_ import video_renderer_twophase as _tp

    calls = {"two_phase": []}

    monkeypatch.setattr(
        _vr,
        "probe_ffmpeg_capabilities",
        lambda: {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset()},
    )
    monkeypatch.setattr(
        _vr,
        "select_enc_opts",
        lambda cfg, caps: {"vcodec": "libx264", "acodec": "aac", "audio_bitrate": "192k"},
    )
    monkeypatch.setattr(
        _tp,
        "render_project_two_phase",
        lambda host, guest, manifest, out_host, out_guest, config: calls["two_phase"].append(
            (host, guest, manifest, out_host, out_guest, config)
        ),
    )
    monkeypatch.setattr(
        _vr,
        "_build_filter_chain",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("single-pass path must not run")),
    )

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])
    config = {"two_phase_render_enabled": True}

    _vr.render_project(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        config,
    )

    assert len(calls["two_phase"]) == 1, "Expected render_project_two_phase to be called once"
    assert calls["two_phase"][0][0] == "host.mp4"
    assert calls["two_phase"][0][1] == "guest.mp4"
    assert calls["two_phase"][0][2] is manifest
    assert calls["two_phase"][0][3] == str(tmp_path / "host_out.mp4")
    assert calls["two_phase"][0][4] is None
    assert calls["two_phase"][0][5] is config


def test_render_project_falls_back_without_flag(monkeypatch, tmp_path):
    """Missing flag keeps the existing single-pass path and does not dispatch."""
    import io_.video_renderer as _vr
    from io_ import video_renderer_twophase as _tp

    calls = {"two_phase": 0, "single_pass": [], "run": []}

    monkeypatch.setattr(
        _vr,
        "probe_ffmpeg_capabilities",
        lambda: {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset()},
    )
    monkeypatch.setattr(
        _vr,
        "select_enc_opts",
        lambda cfg, caps: {"vcodec": "libx264", "acodec": "aac", "audio_bitrate": "192k"},
    )
    monkeypatch.setattr(
        _tp,
        "render_project_two_phase",
        lambda *args, **kwargs: calls.__setitem__("two_phase", calls["two_phase"] + 1),
    )
    monkeypatch.setattr(_vr, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))
    monkeypatch.setattr(
        _vr,
        "_build_filter_chain",
        lambda src, filters, keep_segments, input_kwargs, **kwargs: calls["single_pass"].append(
            {
                "src": src,
                "filters": filters,
                "keep_segments": keep_segments,
                "input_kwargs": input_kwargs,
            }
        ) or ("fake_v", "fake_a"),
    )
    monkeypatch.setattr(_vr.ffmpeg, "output", lambda *args, **kwargs: "fake_stream")
    monkeypatch.setattr(
        _vr,
        "run_with_progress",
        lambda stream, **kwargs: calls["run"].append({"stream": stream, "kwargs": kwargs}),
    )

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    _vr.render_project(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        {},
    )

    assert calls["two_phase"] == 0, "Two-phase dispatcher must not be called"
    assert len(calls["single_pass"]) == 1, "Expected the existing single-pass path to run"
    assert calls["single_pass"][0]["src"] == "host.mp4"
    assert len(calls["run"]) == 1, "Expected single-pass run_with_progress to be called once"
def test_classify_all_copy():
    """All segments on keyframes must classify as copy segments."""
    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keep_segments = [(0.0, 1.0), (2.0, 3.5), (4.0, 6.0)]
    keyframes = [0.0, 2.0, 4.0, 8.0]

    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert [seg["type"] for seg in result] == ["copy", "copy", "copy"]
    assert [seg["kf_start"] for seg in result] == [0.0, 2.0, 4.0]


# ===========================================================================
# probe_video_fps — happy path
# ===========================================================================

def test_probe_video_fps_parses_rational_string(monkeypatch):
    """probe_video_fps must parse '60/1' format and return 60.0."""
    import subprocess as _sp
    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="60/1\n", stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("fake.mp4")
    assert result == 60.0, f"Expected 60.0, got {result}"


def test_probe_video_fps_parses_ntsc_rational(monkeypatch):
    """probe_video_fps must parse '30000/1001' (NTSC 29.97) correctly."""
    import subprocess as _sp
    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="30000/1001\n", stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("fake.mp4")
    assert result is not None
    assert abs(result - 29.97) < 0.01, f"Expected ~29.97, got {result}"


def test_probe_video_fps_returns_none_on_nonzero_returncode(monkeypatch):
    """probe_video_fps must return None (not raise) on ffprobe failure."""
    import subprocess as _sp
    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        return _sp.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="error")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("bad.mp4")
    assert result is None, f"Expected None on failure, got {result}"


def test_probe_video_fps_returns_none_on_zero_denominator(monkeypatch):
    """probe_video_fps must return None when denominator is 0."""
    import subprocess as _sp
    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        return _sp.CompletedProcess(args=cmd, returncode=0, stdout="60/0\n", stderr="")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("fake.mp4")
    assert result is None, f"Expected None for 60/0, got {result}"


def test_probe_video_fps_returns_none_on_missing_ffprobe(monkeypatch):
    """probe_video_fps must return None (not raise) when ffprobe is missing."""
    from io_ import media_probe

    def _fake_run(cmd, capture_output, text):
        raise FileNotFoundError("ffprobe not found")

    monkeypatch.setattr(media_probe.subprocess, "run", _fake_run)
    result = media_probe.probe_video_fps("fake.mp4")
    assert result is None, f"Expected None when ffprobe missing, got {result}"


# ===========================================================================
# quantize_segments_to_frames — rounding logic
# ===========================================================================

def test_quantize_segments_to_frames_exact_boundaries():
    """Segments already on frame boundaries must be unchanged."""
    from io_.video_renderer_twophase import quantize_segments_to_frames

    fps = 60.0
    segs = [(0.0, 1.0), (2.0, 3.5)]  # 0/60, 60/60, 120/60, 210/60 — all exact
    result = quantize_segments_to_frames(segs, fps)
    assert len(result) == 2
    assert abs(result[0][0] - 0.0) < 1e-9
    assert abs(result[0][1] - 1.0) < 1e-9
    assert abs(result[1][0] - 2.0) < 1e-9
    assert abs(result[1][1] - 3.5) < 1e-9


def test_quantize_segments_to_frames_rounds_to_nearest_frame():
    """Mid-frame boundaries must be rounded to the nearest frame."""
    from io_.video_renderer_twophase import quantize_segments_to_frames

    fps = 60.0

    # start=0.005 -> round(0.005 × 60) = round(0.30) = 0 -> 0/60 = 0.0
    # end=1.008   -> round(1.008 × 60) = round(60.48) = 60 -> 60/60 = 1.0
    segs = [(0.005, 1.008)]
    result = quantize_segments_to_frames(segs, fps)
    assert len(result) == 1
    assert abs(result[0][0] - 0.0) < 1e-9, f"start should round to 0.0, got {result[0][0]}"
    assert abs(result[0][1] - 1.0) < 1e-9, f"end should round to 1.0, got {result[0][1]}"


def test_quantize_segments_to_frames_zero_fps_passthrough():
    """Zero or None fps must return the original segments unchanged."""
    from io_.video_renderer_twophase import quantize_segments_to_frames

    segs = [(1.5, 3.7), (5.1, 7.9)]
    assert quantize_segments_to_frames(segs, 0.0) == segs
    assert quantize_segments_to_frames(segs, None) == segs


def test_quantize_segments_to_frames_degenerate_segment_gets_one_frame():
    """If rounding collapses a segment to zero duration, ensure ≥ 1 frame output."""
    from io_.video_renderer_twophase import quantize_segments_to_frames

    fps = 60.0
    frame = 1.0 / 60.0
    # start and end both round to the same frame boundary
    # e.g. start=0.008, end=0.009 both round to 0.0 at 60fps (nearest frame)
    segs = [(0.008, 0.009)]
    result = quantize_segments_to_frames(segs, fps)
    assert len(result) == 1
    q_s, q_e = result[0]
    assert q_e > q_s, f"Degenerate segment must have q_end > q_start; got [{q_s}, {q_e}]"
    assert abs((q_e - q_s) - frame) < 1e-9, (
        f"Degenerate segment duration must be exactly 1 frame ({frame:.6f}s), got {q_e - q_s:.6f}s"
    )


def test_seam_reads_live_cpu_override(monkeypatch, tmp_path):
    """video-copy phase picks up live thread-count override while preserving original audio-phase setup."""
    from io_ import video_renderer_twophase as mod
    import io_.video_renderer as vr
    from pathlib import Path

    captured = {}

    sentinel = 3
    original = 99

    # Patch live override resolver (used at seam)
    def fake_resolve_threads(cfg):
        return sentinel
    monkeypatch.setattr("utils.cpu_override.resolve_threads", fake_resolve_threads)
    monkeypatch.setattr(
        mod, "resolve_threads", fake_resolve_threads, raising=False
    )

    def fake_audio_phase(src, filters, segs, out, audio_opts):
        captured["audio_threads"] = audio_opts.get("threads")
    monkeypatch.setattr(mod, "render_audio_phase", fake_audio_phase)

    def fake_video_smart_copy(src, segs, kf, dst, enc_opts, snap, **kw):
        captured["video_threads"] = enc_opts.get("threads")
    monkeypatch.setattr(mod, "render_video_smart_copy", fake_video_smart_copy)

    monkeypatch.setattr(mod, "probe_video_stream_codec", lambda p: "h264")
    monkeypatch.setattr(mod, "probe_video_keyframes", lambda p: [0.0])
    monkeypatch.setattr(mod, "probe_video_fps", lambda p: 30.0)
    monkeypatch.setattr(mod, "get_video_duration_seconds", lambda p: 10.0)
    monkeypatch.setattr(mod, "quantize_segments_to_frames", lambda segs, fps: list(segs))
    monkeypatch.setattr(mod, "run_with_progress", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))

    # Mux is inline
    import subprocess as sp
    def fake_mux_run(cmd, **kwargs):
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    monkeypatch.setattr(mod.subprocess, "run", fake_mux_run)

    # Initial config setup uses these
    monkeypatch.setattr(
        vr, "probe_ffmpeg_capabilities",
        lambda: {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset()}
    )
    monkeypatch.setattr(
        vr,
        "select_enc_opts",
        lambda cfg, caps: {
            "threads": original,
            "acodec": "aac",
            "audio_bitrate": "192k",
            "vcodec": "libx264",
        },
    )
    monkeypatch.setattr(mod, "cpu_threads_from_config", lambda cfg: original)

    manifest = _ManifestTP(
        keep_segments=[(0.0, 10.0)], host_filters=[], guest_filters=[]
    )

    in_path = str(tmp_path / "seam_test_in.mp4")
    out_path = str(tmp_path / "seam_test_out.mp4")
    Path(in_path).touch()

    config = {"two_phase_render_enabled": True, "cpu_limit_pct": 25}

    mod.render_project_two_phase(
        in_path, None, manifest, out_path, None, config
    )

    assert captured.get("video_threads") == sentinel, (
        f"Expected video-copy to receive live sentinel {sentinel}, got {captured.get('video_threads')}"
    )
    assert captured.get("audio_threads") == original, (
        f"Audio phase must preserve original threads {original}, got {captured.get('audio_threads')}"
    )
