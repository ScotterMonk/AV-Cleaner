import subprocess
from dataclasses import dataclass


class _ImmediateFuture:
    def __init__(self, fn, *args, **kwargs):
        self._exc = None
        self._result = None
        try:
            self._result = fn(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - helper mirrors Future contract
            self._exc = exc

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._result


class _ImmediateExecutor:
    def __init__(self, max_workers, captured=None):
        self.max_workers = max_workers
        self.captured = captured
        if captured is not None:
            captured.setdefault("max_workers", []).append(max_workers)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args, **kwargs):
        if self.captured is not None:
            self.captured.setdefault("submitted", 0)
            self.captured["submitted"] += 1
        return _ImmediateFuture(fn, *args, **kwargs)


@dataclass
class _ManifestTP:
    keep_segments: list
    host_filters: list
    guest_filters: list


def _patch_immediate_executor(monkeypatch, module, captured):
    monkeypatch.setattr(module, "ThreadPoolExecutor", lambda max_workers: _ImmediateExecutor(max_workers, captured))
    if hasattr(module, "as_completed"):
        monkeypatch.setattr(module, "as_completed", lambda futures: list(futures))


def _patch_batched_gpu_dependencies(monkeypatch, tmp_path):
    import ffmpeg
    import io_.video_renderer as _vr
    import io_.video_renderer_progress as _vr_progress
    from io_ import video_renderer_strategies as _strategies

    captured = {"batch_segments": [], "streams": [], "concat_cmds": []}

    _patch_immediate_executor(monkeypatch, _strategies, captured)
    monkeypatch.setattr(_strategies, "merge_close_segments", lambda segs: list(segs))
    monkeypatch.setattr(
        _vr,
        "probe_ffmpeg_capabilities",
        lambda: {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset()},
    )
    monkeypatch.setattr(_vr, "build_input_kwargs", lambda cfg, caps: {})

    def _fake_build_filter_chain(input_path, filters, segs, input_kwargs, cut_fade_s=0.0):
        captured["batch_segments"].append(list(segs))
        return (f"v_{len(captured['batch_segments'])}", f"a_{len(captured['batch_segments'])}")

    monkeypatch.setattr(_vr, "_build_filter_chain", _fake_build_filter_chain)
    monkeypatch.setattr(ffmpeg, "output", lambda *args, **kwargs: {"args": args, "kwargs": kwargs})
    monkeypatch.setattr(
        _vr_progress,
        "run_with_progress",
        lambda stream, **kwargs: captured["streams"].append({"stream": stream, "kwargs": dict(kwargs)}),
    )

    def _fake_subprocess_run(cmd, **kwargs):
        captured["concat_cmds"].append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_strategies.subprocess, "run", _fake_subprocess_run)

    return _strategies, captured


def _patch_render_project_auto_dependencies(monkeypatch, batched_capture=None, source_codec="h264"):
    import io_.video_renderer as _vr
    from io_ import video_renderer_strategies as _strategies
    from io_ import video_renderer_twophase as _tp

    captured = {
        "audio_phase": [],
        "single_pass": [],
        "smart_copy": [],
        "batched_gpu": [] if batched_capture is None else batched_capture,
        "keyframe_probes": [],
        "mux_cmds": [],
    }

    _patch_immediate_executor(monkeypatch, _tp, captured)
    monkeypatch.setattr(
        _vr,
        "probe_ffmpeg_capabilities",
        lambda: {"ffmpeg_ok": True, "encoders": frozenset(), "hwaccels": frozenset()},
    )
    monkeypatch.setattr(
        _vr,
        "select_enc_opts",
        lambda cfg, caps: {"vcodec": "h264_nvenc", "acodec": "aac", "audio_bitrate": "192k"},
    )
    monkeypatch.setattr(_tp, "cpu_threads_from_config", lambda cfg: 2)
    monkeypatch.setattr("utils.cpu_override.resolve_threads", lambda cfg: 2)
    monkeypatch.setattr(_tp, "probe_video_stream_codec", lambda path: source_codec)
    monkeypatch.setattr(_tp, "probe_video_fps", lambda path: None)
    monkeypatch.setattr(_tp, "probe_is_vfr", lambda path: False)
    monkeypatch.setattr(_tp, "probe_video_keyframes", lambda path: captured["keyframe_probes"].append(path) or [0.0, 10.0])
    monkeypatch.setattr(_tp, "get_video_duration_seconds", lambda path: 10.0)
    monkeypatch.setattr(_tp, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))
    monkeypatch.setattr(
        _tp,
        "render_audio_phase",
        lambda src, filters, segs, out, audio_opts: captured["audio_phase"].append(
            {"src": src, "filters": list(filters), "segs": list(segs), "audio_opts": dict(audio_opts)}
        ),
    )
    monkeypatch.setattr(
        _tp,
        "render_video_single_pass",
        lambda src, filters, segs, out, enc_opts, cfg: captured["single_pass"].append(
            {
                "src": src,
                "filters": list(filters),
                "segs": list(segs),
                "out": out,
                "enc_opts": dict(enc_opts),
                "cfg": cfg,
            }
        ),
    )
    monkeypatch.setattr(
        _tp,
        "render_video_smart_copy",
        lambda src, segs, keyframes, out, enc_opts, snap_tol, label="", gpu_limit_pct=100: captured["smart_copy"].append(
            {
                "src": src,
                "segs": list(segs),
                "keyframes": list(keyframes),
                "out": out,
                "label": label,
                "gpu_limit_pct": gpu_limit_pct,
            }
        ),
    )
    monkeypatch.setattr(
        _strategies,
        "render_video_batched_gpu",
        lambda src, filters, segs, out, enc_opts, cfg, num_batches=3: captured["batched_gpu"].append(
            {
                "src": src,
                "filters": list(filters),
                "segs": list(segs),
                "out": out,
                "enc_opts": dict(enc_opts),
                "cfg": cfg,
                "num_batches": num_batches,
            }
        ),
    )

    def _fake_subprocess_run(cmd, **kwargs):
        captured["mux_cmds"].append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(_tp.subprocess, "run", _fake_subprocess_run)

    return _tp, captured


def test_render_video_batched_gpu_splits_segments_into_batches(monkeypatch, tmp_path):
    """batched_gpu splits merged segments into contiguous chunks across the requested batches.

    Contiguous chunking (not round-robin) is required so each batch renders a
    chronologically ordered slice of the timeline.  Round-robin would scatter
    non-adjacent segments into the same batch, producing a video whose content
    order does not match the audio phase (which renders segments sequentially),
    causing A/V de-sync.

    With 5 segments and num_batches=3:
      chunk_size = ceil(5/3) = 2
      batch 0 -> segments 0-1  [(0.0, 1.0), (1.0, 2.0)]
      batch 1 -> segments 2-3  [(2.0, 3.0), (3.0, 4.0)]
      batch 2 -> segment  4    [(4.0, 5.0)]
    """
    _strategies, captured = _patch_batched_gpu_dependencies(monkeypatch, tmp_path)

    keep_segments = [
        (0.0, 1.0),
        (1.0, 2.0),
        (2.0, 3.0),
        (3.0, 4.0),
        (4.0, 5.0),
    ]

    _strategies.render_video_batched_gpu(
        input_path="host.mp4",
        filters=["scale=1280:720"],
        keep_segments=keep_segments,
        out_path=str(tmp_path / "host_out.mp4"),
        enc_opts={"vcodec": "h264_nvenc", "cq": 18},
        config={"gpu_limit_pct": 100, "cut_fade_ms": 0},
        num_batches=3,
    )

    assert captured["batch_segments"] == [
        [(0.0, 1.0), (1.0, 2.0)],
        [(2.0, 3.0), (3.0, 4.0)],
        [(4.0, 5.0)],
    ]
    assert len(captured["streams"]) == 3


def test_render_video_batched_gpu_respects_nvenc_session_cap(monkeypatch, tmp_path):
    """NVENC batched_gpu must cap ThreadPool workers to the configured session budget."""
    _strategies, captured = _patch_batched_gpu_dependencies(monkeypatch, tmp_path)

    keep_segments = [(float(i), float(i + 1)) for i in range(5)]

    _strategies.render_video_batched_gpu(
        input_path="guest.mp4",
        filters=[],
        keep_segments=keep_segments,
        out_path=str(tmp_path / "guest_out.mp4"),
        enc_opts={"vcodec": "h264_nvenc", "cq": 18},
        config={"gpu_limit_pct": 20},
        num_batches=5,
    )

    assert captured["max_workers"] == [1]
    assert captured["submitted"] == 5


def test_auto_routing_non_h264_selects_single_pass(monkeypatch, tmp_path):
    """auto routing must choose single_pass immediately for non-h264 sources."""
    _tp, captured = _patch_render_project_auto_dependencies(monkeypatch, source_codec="hevc")

    manifest = _ManifestTP(
        keep_segments=[(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0), (4.0, 5.0), (5.0, 6.0)],
        host_filters=[],
        guest_filters=[],
    )

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        {"video_phase_strategy": "auto"},
    )

    assert len(captured["single_pass"]) == 1
    assert not captured["smart_copy"]
    assert not captured["batched_gpu"]
    assert not captured["keyframe_probes"]


def test_auto_routing_few_segments_selects_smart_copy(monkeypatch, tmp_path):
    """auto routing must keep small h264 workloads on smart_copy."""
    _tp, captured = _patch_render_project_auto_dependencies(monkeypatch, source_codec="h264")

    manifest = _ManifestTP(
        keep_segments=[(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0), (4.0, 5.0)],
        host_filters=[],
        guest_filters=[],
    )

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        {"video_phase_strategy": "auto", "gpu_limit_pct": 60},
    )

    assert len(captured["smart_copy"]) == 1
    assert captured["smart_copy"][0]["segs"] == manifest.keep_segments
    assert not captured["single_pass"]
    assert not captured["batched_gpu"]


def test_auto_routing_medium_segments_selects_single_pass(monkeypatch, tmp_path):
    """auto routing must choose single_pass for medium-sized h264 workloads."""
    _tp, captured = _patch_render_project_auto_dependencies(monkeypatch, source_codec="h264")

    manifest = _ManifestTP(
        keep_segments=[(float(i), float(i + 1)) for i in range(6)],
        host_filters=[],
        guest_filters=[],
    )

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        {"video_phase_strategy": "auto"},
    )

    assert len(captured["single_pass"]) == 1
    assert captured["single_pass"][0]["segs"] == manifest.keep_segments
    assert not captured["smart_copy"]
    assert not captured["batched_gpu"]


def test_auto_routing_many_segments_selects_batched_gpu(monkeypatch, tmp_path):
    """auto routing must choose batched_gpu once the segment count exceeds the medium threshold."""
    _tp, captured = _patch_render_project_auto_dependencies(monkeypatch, source_codec="h264")

    manifest = _ManifestTP(
        keep_segments=[(float(i), float(i + 1)) for i in range(26)],
        host_filters=[],
        guest_filters=[],
    )
    config = {"video_phase_strategy": "auto", "batched_gpu_num_batches": 4, "gpu_limit_pct": 20}

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        config,
    )

    assert len(captured["batched_gpu"]) == 1
    assert captured["batched_gpu"][0]["segs"] == manifest.keep_segments
    assert captured["batched_gpu"][0]["num_batches"] == 4
    assert captured["batched_gpu"][0]["cfg"] is config
    assert not captured["single_pass"]
    assert not captured["smart_copy"]


def test_batched_gpu_batch_boundaries_are_identical_for_host_and_guest(monkeypatch, tmp_path):
    """Host and guest must receive the same shared keep_segments when auto routes both tracks to batched_gpu."""
    batched_calls: list[dict] = []
    _tp, captured = _patch_render_project_auto_dependencies(
        monkeypatch,
        batched_capture=batched_calls,
        source_codec="h264",
    )

    manifest = _ManifestTP(
        keep_segments=[(float(i), float(i + 0.5)) for i in range(26)],
        host_filters=["eq=contrast=1.1"],
        guest_filters=["eq=brightness=0.02"],
    )
    config = {"video_phase_strategy": "auto", "batched_gpu_num_batches": 3}

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        str(tmp_path / "guest_out.mp4"),
        config,
    )

    assert len(batched_calls) == 2
    assert batched_calls[0]["segs"] == manifest.keep_segments
    assert batched_calls[1]["segs"] == manifest.keep_segments
    assert batched_calls[0]["segs"] == batched_calls[1]["segs"]
    assert [call["src"] for call in batched_calls] == ["host.mp4", "guest.mp4"]
    assert all(call["num_batches"] == 3 for call in batched_calls)
    assert not captured["single_pass"]
    assert not captured["smart_copy"]
