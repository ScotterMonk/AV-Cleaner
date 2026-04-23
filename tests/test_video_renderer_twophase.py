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




