import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass
class _FakeFilter:
    """Minimal AudioFilter stand-in for unit tests."""

    filter_name: str
    params: Dict[str, Any]


@dataclass
class _ManifestTP:
    """Minimal manifest stand-in for [`render_project_two_phase()`](io_/video_renderer_twophase.py:282) tests."""

    keep_segments: list
    host_filters: list
    guest_filters: list


def _apply_common_twophase_mocks(monkeypatch, source_codec="h264"):
    """Patch two-phase sub-phases with no-op stubs and capture the calls."""

    import io_.video_renderer as _vr
    from io_ import video_renderer_twophase as _tp

    captured: dict = {
        "audio_phase": [],
        "keyframe_probes": [],
        "smart_copy": [],
        "single_pass": [],
        "mux_cmds": [],
        "duration_probes": [],
    }

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
    monkeypatch.setattr(_tp, "probe_video_stream_codec", lambda p: source_codec)
    monkeypatch.setattr(_tp, "probe_video_fps", lambda p: None)
    monkeypatch.setattr(_tp, "probe_is_vfr", lambda p: False)

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

    def _fake_single_pass(src, filters, segs, out, enc_opts, cfg):
        captured["single_pass"].append({"src": src, "filters": filters, "segs": segs})

    monkeypatch.setattr(_tp, "render_video_single_pass", _fake_single_pass)

    def _fake_mux(cmd, capture_output, text):
        captured["mux_cmds"].append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_tp.subprocess, "run", _fake_mux)
    monkeypatch.setattr(_tp, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))

    return captured


def test_render_project_two_phase_host_filters_routed(monkeypatch, tmp_path):
    """[`render_audio_phase()`](io_/video_renderer_twophase.py:63) receives [`manifest.host_filters`](core/interfaces.py:18) for the host track."""

    from io_ import video_renderer_twophase as _tp

    host_f = _FakeFilter("alimiter", {"limit": 1.0})
    guest_f = _FakeFilter("loudnorm", {"I": -23})
    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[host_f], guest_filters=[guest_f])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest, str(tmp_path / "host.mp4"), None, config=None)

    assert len(captured["audio_phase"]) == 1, "Expected exactly one audio_phase call"
    assert captured["audio_phase"][0]["filters"] == [host_f], (
        "host_filters not routed correctly; got %r" % captured["audio_phase"][0]["filters"]
    )


def test_render_project_two_phase_guest_filters_routed(monkeypatch, tmp_path):
    """[`render_audio_phase()`](io_/video_renderer_twophase.py:63) receives [`manifest.guest_filters`](core/interfaces.py:18) for the guest track."""

    from io_ import video_renderer_twophase as _tp

    host_f = _FakeFilter("alimiter", {"limit": 1.0})
    guest_f = _FakeFilter("loudnorm", {"I": -23})
    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[host_f], guest_filters=[guest_f])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest, None, str(tmp_path / "guest.mp4"), config=None)

    assert len(captured["audio_phase"]) == 1, "Expected exactly one audio_phase call"
    assert captured["audio_phase"][0]["filters"] == [guest_f], (
        "guest_filters not routed correctly; got %r" % captured["audio_phase"][0]["filters"]
    )


def test_render_project_two_phase_keyframes_probed_on_correct_path(monkeypatch, tmp_path):
    """[`probe_video_keyframes()`](io_/media_probe.py:67) is called with the host source path, not the output path."""

    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase(
        "actual_host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host.mp4"),
        None,
        config={"video_phase_strategy": "smart_copy"},
    )

    assert captured["keyframe_probes"] == ["actual_host.mp4"], (
        "Expected keyframes probed on host source; got %r" % captured["keyframe_probes"]
    )


def test_render_project_two_phase_smart_copy_receives_correct_args(monkeypatch, tmp_path):
    """[`render_video_smart_copy()`](io_/video_renderer_twophase.py:112) receives source path, keep segments, and probed keyframes."""

    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch)
    segs = [(0.0, 3.0), (5.0, 8.0)]
    manifest = _ManifestTP(keep_segments=segs, host_filters=[], guest_filters=[])

    _tp.render_project_two_phase(
        "src_host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host.mp4"),
        None,
        config={"video_phase_strategy": "smart_copy"},
    )

    assert len(captured["smart_copy"]) == 1, f"Expected 1 smart_copy call; got {len(captured['smart_copy'])}"
    call = captured["smart_copy"][0]
    assert call["src"] == "src_host.mp4", f"Unexpected src: {call['src']!r}"
    assert call["segs"] == segs, f"Unexpected segs: {call['segs']}"
    assert call["kfs"] == [0.0, 5.0], f"Unexpected keyframes: {call['kfs']}"


def test_render_project_two_phase_mux_uses_map_flags(monkeypatch, tmp_path):
    """Mux command contains `-map 0:v`, `-map 1:a`, and `-shortest`."""

    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest, str(tmp_path / "host.mp4"), None, config=None)

    assert len(captured["mux_cmds"]) == 1, f"Expected 1 mux call; got {len(captured['mux_cmds'])}"
    cmd = captured["mux_cmds"][0]
    map_indices = [i for i, x in enumerate(cmd) if x == "-map"]
    assert len(map_indices) == 2, f"Expected exactly 2 -map flags; cmd={cmd}"
    assert cmd[map_indices[0] + 1] == "0:v", f"First -map must be '0:v'; got {cmd[map_indices[0]+1]!r}"
    assert cmd[map_indices[1] + 1] == "1:a", f"Second -map must be '1:a'; got {cmd[map_indices[1]+1]!r}"
    assert "-shortest" in cmd, f"Expected '-shortest' in mux command; cmd={cmd}"


def test_render_project_two_phase_temp_cleanup_on_audio_raise(monkeypatch, tmp_path):
    """Temp audio and video files are removed even when [`render_audio_phase()`](io_/video_renderer_twophase.py:63) raises."""

    import io_.video_renderer as _vr
    import tempfile as _tf
    from io_ import video_renderer_twophase as _tp

    tracked_tmps: list = []
    _real_mkstemp = _tf.mkstemp

    def _tracking_mkstemp(suffix=None, dir=None):
        fd, path = _real_mkstemp(suffix=suffix, dir=dir)
        tracked_tmps.append(path)
        return fd, path

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
    monkeypatch.setattr(_tp, "probe_video_stream_codec", lambda p: "h264")
    monkeypatch.setattr(_tp.tempfile, "mkstemp", _tracking_mkstemp)

    def _raise_audio(*a, **kw):
        raise RuntimeError("audio phase boom")

    monkeypatch.setattr(_tp, "render_audio_phase", _raise_audio)
    monkeypatch.setattr(_tp, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])
    raised = None
    try:
        _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest, str(tmp_path / "host.mp4"), None, config=None)
    except RuntimeError as exc:
        raised = exc

    assert raised is not None, "Expected RuntimeError to propagate"
    assert "audio phase boom" in str(raised)
    assert len(tracked_tmps) == 2, f"Expected 2 temp files (m4a + mp4); got {tracked_tmps}"
    for temp_path in tracked_tmps:
        assert not Path(temp_path).exists(), f"Temp file not cleaned up after audio raise: {temp_path}"


def test_render_project_two_phase_empty_segments_use_full_duration(monkeypatch, tmp_path):
    """Empty [`manifest.keep_segments`](core/interfaces.py:18) triggers [`get_video_duration_seconds()`](io_/media_probe.py:10) to build a full-span segment."""

    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch)
    manifest = _ManifestTP(keep_segments=[], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest, str(tmp_path / "host.mp4"), None, config=None)

    assert captured["duration_probes"], "Expected get_video_duration_seconds called for empty segments"
    assert len(captured["audio_phase"]) == 1
    assert captured["audio_phase"][0]["segs"] == [(0.0, 10.0)], (
        "Expected normalized full-span [(0.0, 10.0)]; got %r" % captured["audio_phase"][0]["segs"]
    )


def test_render_project_two_phase_falls_back_for_non_h264_source(monkeypatch, tmp_path):
    """Non-H264 codec uses [`render_video_single_pass()`](io_/video_renderer_twophase.py:33), then muxes with the audio phase."""

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

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest, str(tmp_path / "host.mp4"), None, config=None)

    assert len(single_pass_calls) == 1, "Expected single-pass video phase called for non-h264"
    assert len(captured["audio_phase"]) == 1, "render_audio_phase should still run for non-h264"
    assert not captured["keyframe_probes"], "probe_video_keyframes must NOT be called for non-h264"
    assert not captured["smart_copy"], "render_video_smart_copy must NOT be called for non-h264"
    assert len(captured["mux_cmds"]) == 1, "Mux should still run after single-pass video phase"


def test_render_track_routes_single_pass_strategy(monkeypatch, tmp_path):
    """Configured `single_pass` strategy routes the track through [`render_video_single_pass()`](io_/video_renderer_twophase.py:33)."""

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

    _tp.render_project_two_phase("host.mp4", "guest.mp4", manifest, str(tmp_path / "host.mp4"), None, config=config)

    assert len(single_pass_calls) == 1, "Expected single-pass video phase called once"
    assert single_pass_calls[0]["cfg"] is config, "Expected original config routed to single-pass helper"
    assert len(captured["audio_phase"]) == 1, "Audio phase should still run for single_pass strategy"
    assert not captured["keyframe_probes"], "probe_video_keyframes must NOT be called for single_pass strategy"
    assert not captured["smart_copy"], "render_video_smart_copy must NOT be called for single_pass strategy"
    assert len(captured["mux_cmds"]) == 1, "Mux should still run after single-pass video phase"


def test_render_track_routes_single_pass_auto_default(monkeypatch, tmp_path):
    """Default auto routing for H.264 sources stays on the single-pass branch."""

    from io_ import video_renderer_twophase as _tp

    captured = _apply_common_twophase_mocks(monkeypatch, source_codec="h264")
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host.mp4"),
        None,
        config={},
    )

    assert len(captured["audio_phase"]) == 1, "Audio phase should still run on the default auto route"
    assert not captured["keyframe_probes"], "Default auto route must not probe keyframes"
    assert not captured["smart_copy"], "Default auto route must not use smart-copy"
    assert len(captured["single_pass"]) == 1, "Single-pass helper must be called on the default auto route"
    assert len(captured["mux_cmds"]) == 1, "Mux should still run after single-pass video phase"


def test_render_project_two_phase_dispatches_when_enabled(monkeypatch, tmp_path):
    """Enabled flag triggers the two-phase dispatcher and skips the single-pass path in [`render_project()`](io_/video_renderer.py:426)."""

    import io_.video_renderer as _vr
    from io_ import video_renderer_twophase as _tp

    calls = {"two_phase": []}
    expected_metadata = {"strategy_family": "single_pass", "route_mode": "auto"}

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
        lambda host, guest, manifest, out_host, out_guest, config: (
            calls["two_phase"].append((host, guest, manifest, out_host, out_guest, config)) or expected_metadata
        ),
    )
    monkeypatch.setattr(
        _vr,
        "_build_filter_chain",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("single-pass path must not run")),
    )

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])
    config = {"two_phase_render_enabled": True}

    metadata = _vr.render_project(
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
    assert metadata == expected_metadata


def test_render_project_falls_back_without_flag(monkeypatch, tmp_path):
    """Missing two-phase flag keeps the existing single-pass path and does not dispatch."""

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
        )
        or ("fake_v", "fake_a"),
    )
    monkeypatch.setattr(_vr.ffmpeg, "output", lambda *args, **kwargs: "fake_stream")
    monkeypatch.setattr(
        _vr,
        "run_with_progress",
        lambda stream, **kwargs: calls["run"].append({"stream": stream, "kwargs": kwargs}),
    )

    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])

    metadata = _vr.render_project(
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
    assert metadata == {"strategy_family": "single_pass"}


def test_render_project_ignores_chunk_parallel_config_and_stays_single_pass(monkeypatch, tmp_path):
    """Legacy chunk config no longer affects the non-two-phase renderer dispatch."""

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
                "keep_segments": list(keep_segments),
                "input_kwargs": input_kwargs,
            }
        )
        or ("fake_v", "fake_a"),
    )
    monkeypatch.setattr(_vr.ffmpeg, "output", lambda *args, **kwargs: "fake_stream")
    monkeypatch.setattr(
        _vr,
        "run_with_progress",
        lambda stream, **kwargs: calls["run"].append({"stream": stream, "kwargs": kwargs}),
    )

    manifest = _ManifestTP(
        keep_segments=[(float(i), float(i + 1)) for i in range(60)],
        host_filters=[],
        guest_filters=[],
    )

    metadata = _vr.render_project(
        "host.mp4",
        None,
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        {"chunk_parallel_enabled": True, "chunk_size": 1},
    )

    assert calls["two_phase"] == 0, "Two-phase dispatcher must not be called"
    assert len(calls["single_pass"]) == 1, "Expected the single-pass renderer path to run"
    assert len(calls["single_pass"][0]["keep_segments"]) == 60
    assert len(calls["run"]) == 1, "Expected single-pass run_with_progress to be called once"
    assert metadata == {"strategy_family": "single_pass"}


def test_seam_reads_live_cpu_override(monkeypatch, tmp_path):
    """Video-copy phase picks up the live thread override while preserving original audio-phase setup."""

    import io_.video_renderer as vr
    from io_ import video_renderer_twophase as mod

    captured = {}
    sentinel = 3
    original = 99

    def fake_resolve_threads(cfg):
        return sentinel

    monkeypatch.setattr("utils.cpu_override.resolve_threads", fake_resolve_threads)
    monkeypatch.setattr(mod, "resolve_threads", fake_resolve_threads, raising=False)

    def fake_audio_phase(src, filters, segs, out, audio_opts):
        captured["audio_threads"] = audio_opts.get("threads")

    monkeypatch.setattr(mod, "render_audio_phase", fake_audio_phase)

    def fake_video_single_pass(src, filters, segs, dst, enc_opts, cfg):
        captured["video_threads"] = enc_opts.get("threads")

    monkeypatch.setattr(mod, "render_video_single_pass", fake_video_single_pass)
    monkeypatch.setattr(mod, "probe_video_stream_codec", lambda p: "h264")
    monkeypatch.setattr(mod, "probe_video_keyframes", lambda p: [0.0])
    monkeypatch.setattr(mod, "probe_video_fps", lambda p: 30.0)
    monkeypatch.setattr(mod, "get_video_duration_seconds", lambda p: 10.0)
    monkeypatch.setattr(mod, "quantize_segments_to_frames", lambda segs, fps: list(segs))
    monkeypatch.setattr(mod, "run_with_progress", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))

    def fake_mux_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_mux_run)
    monkeypatch.setattr(
        vr,
        "probe_ffmpeg_capabilities",
        lambda: {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset()},
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

    manifest = _ManifestTP(keep_segments=[(0.0, 10.0)], host_filters=[], guest_filters=[])
    in_path = str(tmp_path / "seam_test_in.mp4")
    out_path = str(tmp_path / "seam_test_out.mp4")
    Path(in_path).touch()
    config = {"two_phase_render_enabled": True, "cpu_limit_pct": 25}

    mod.render_project_two_phase(in_path, None, manifest, out_path, None, config)

    assert captured.get("video_threads") == sentinel, (
        f"Expected video-copy to receive live sentinel {sentinel}, got {captured.get('video_threads')}"
    )
    assert captured.get("audio_threads") == original, (
        f"Audio phase must preserve original threads {original}, got {captured.get('audio_threads')}"
    )
