import subprocess
from dataclasses import dataclass
from typing import NotRequired, TypedDict, cast


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
    def __init__(self, max_workers):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args, **kwargs):
        return _ImmediateFuture(fn, *args, **kwargs)


@dataclass
class _ManifestTP:
    keep_segments: list
    host_filters: list
    guest_filters: list


class _TrackRoutingMetadata(TypedDict):
    fps: float
    strategy_family: str


class _RoutingMetadata(TypedDict):
    strategy_family: str
    source_codecs: dict[str, str]
    route_mode: NotRequired[str]
    requested_strategy: NotRequired[str]
    shared_segment_count: NotRequired[int]
    tracks: NotRequired[dict[str, _TrackRoutingMetadata]]


def _two_phase_render_metadata(config: dict) -> _RoutingMetadata:
    metadata = config.get("_two_phase_render_metadata")
    assert isinstance(metadata, dict)
    return cast(_RoutingMetadata, metadata)


def _metadata_shared_segment_count(metadata: _RoutingMetadata) -> int:
    shared_segment_count = metadata.get("shared_segment_count")
    assert isinstance(shared_segment_count, int)
    return shared_segment_count


def _metadata_route_mode(metadata: _RoutingMetadata) -> str:
    route_mode = metadata.get("route_mode")
    assert isinstance(route_mode, str)
    return route_mode


def _metadata_requested_strategy(metadata: _RoutingMetadata) -> str:
    requested_strategy = metadata.get("requested_strategy")
    assert isinstance(requested_strategy, str)
    return requested_strategy


def _metadata_tracks(metadata: _RoutingMetadata) -> dict[str, _TrackRoutingMetadata]:
    tracks = metadata.get("tracks")
    assert isinstance(tracks, dict)
    return cast(dict[str, _TrackRoutingMetadata], tracks)


def _patch_twophase_routing_dependencies(
    monkeypatch,
    codec_map=None,
    fps_map=None,
):
    import io_.video_renderer as _vr
    from io_ import video_renderer_strategies as _strategies
    from io_ import video_renderer_twophase as _tp

    codec_map = codec_map or {"host.mp4": "h264", "guest.mp4": "h264"}
    fps_map = fps_map or {}
    captured = {
        "audio_phase": [],
        "single_pass": [],
        "smart_copy": [],
        "batched_gpu": [],
        "keyframe_probes": [],
        "quantize": [],
        "mux_cmds": [],
    }

    monkeypatch.setattr(_tp, "ThreadPoolExecutor", lambda max_workers: _ImmediateExecutor(max_workers))
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
    monkeypatch.setattr(_tp, "probe_video_stream_codec", lambda path: codec_map[path])
    monkeypatch.setattr(_tp, "probe_video_fps", lambda path: fps_map.get(path))
    monkeypatch.setattr(_tp, "probe_is_vfr", lambda path: False)
    monkeypatch.setattr(_tp, "probe_video_keyframes", lambda path: captured["keyframe_probes"].append(path) or [0.0, 10.0])
    monkeypatch.setattr(_tp, "get_video_duration_seconds", lambda path: 10.0)
    monkeypatch.setattr(_tp, "_render_with_safe_overwrite", lambda src, dst, fn: fn(dst))
    monkeypatch.setattr(
        _tp,
        "quantize_segments_to_frames",
        lambda segs, fps: captured["quantize"].append({"segs": list(segs), "fps": fps}) or list(segs),
    )
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


def test_shared_auto_routing_mixed_codecs_forces_single_pass_for_both_tracks(monkeypatch, tmp_path):
    """Any non-h264 source in an auto-routed pair forces both outputs onto single_pass."""
    _tp, captured = _patch_twophase_routing_dependencies(
        monkeypatch,
        codec_map={"host.mp4": "h264", "guest.mp4": "hevc"},
        fps_map={"host.mp4": 30.0, "guest.mp4": 60.0},
    )
    manifest = _ManifestTP(
        keep_segments=[(float(i), float(i + 1)) for i in range(26)],
        host_filters=[],
        guest_filters=[],
    )
    config = {"video_phase_strategy": "auto"}

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        str(tmp_path / "guest_out.mp4"),
        config,
    )
    metadata = _two_phase_render_metadata(config)

    assert [call["src"] for call in captured["single_pass"]] == ["host.mp4", "guest.mp4"]
    assert not captured["batched_gpu"]
    assert not captured["smart_copy"]
    assert not captured["keyframe_probes"]
    assert captured["quantize"] == [
        {"segs": manifest.keep_segments, "fps": 30.0},
        {"segs": manifest.keep_segments, "fps": 60.0},
    ]
    assert metadata["strategy_family"] == "single_pass"
    assert metadata["source_codecs"] == {
        "host": "h264",
        "guest": "hevc",
    }


def test_shared_auto_routing_large_h264_pair_uses_batched_gpu(monkeypatch, tmp_path):
    """Large all-h264 auto-routed pairs must keep both tracks on batched_gpu."""
    _tp, captured = _patch_twophase_routing_dependencies(
        monkeypatch,
        fps_map={"host.mp4": 24.0, "guest.mp4": 30.0},
    )
    manifest = _ManifestTP(
        keep_segments=[(float(i), float(i + 0.5)) for i in range(26)],
        host_filters=["host-filter"],
        guest_filters=["guest-filter"],
    )
    config = {"video_phase_strategy": "auto", "batched_gpu_num_batches": 4}

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        str(tmp_path / "guest_out.mp4"),
        config,
    )
    metadata = _two_phase_render_metadata(config)

    assert [call["src"] for call in captured["batched_gpu"]] == ["host.mp4", "guest.mp4"]
    assert all(call["segs"] == manifest.keep_segments for call in captured["batched_gpu"])
    assert all(call["num_batches"] == 4 for call in captured["batched_gpu"])
    assert not captured["single_pass"]
    assert not captured["smart_copy"]
    assert metadata["strategy_family"] == "batched_gpu"
    assert _metadata_shared_segment_count(metadata) == 26


def test_shared_auto_routing_small_h264_pair_uses_single_pass(monkeypatch, tmp_path):
    """Small all-h264 auto-routed pairs must now use single_pass for both tracks."""
    _tp, captured = _patch_twophase_routing_dependencies(
        monkeypatch,
        fps_map={"host.mp4": 29.97, "guest.mp4": 25.0},
    )
    manifest = _ManifestTP(
        keep_segments=[(0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 4.0), (4.0, 5.0)],
        host_filters=[],
        guest_filters=[],
    )
    config = {"video_phase_strategy": "auto"}

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        str(tmp_path / "guest_out.mp4"),
        config,
    )
    metadata = _two_phase_render_metadata(config)

    assert [call["src"] for call in captured["single_pass"]] == ["host.mp4", "guest.mp4"]
    assert not captured["batched_gpu"]
    assert not captured["smart_copy"]
    assert not captured["keyframe_probes"]
    tracks = _metadata_tracks(metadata)

    assert metadata["strategy_family"] == "single_pass"
    assert tracks["host"]["fps"] == 29.97
    assert tracks["guest"]["fps"] == 25.0


def test_manual_override_smart_copy_still_works(monkeypatch, tmp_path):
    """Manual override to smart_copy must still reach the smart_copy implementation."""
    _tp, captured = _patch_twophase_routing_dependencies(
        monkeypatch,
        fps_map={"host.mp4": 30.0},
    )
    manifest = _ManifestTP(
        keep_segments=[(0.0, 1.0)],
        host_filters=[],
        guest_filters=[],
    )
    config = {"video_phase_strategy": "smart_copy"}

    _tp.render_project_two_phase(
        "host.mp4",
        None,
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        config,
    )
    metadata = _two_phase_render_metadata(config)

    assert captured["smart_copy"]
    assert captured["smart_copy"][0]["src"] == "host.mp4"
    assert _metadata_route_mode(metadata) == "manual"
    assert _metadata_requested_strategy(metadata) == "smart_copy"


def test_shared_auto_routing_one_output_still_renders(monkeypatch, tmp_path):
    """A single-output auto-routed render still succeeds and stores lightweight metadata."""
    _tp, captured = _patch_twophase_routing_dependencies(
        monkeypatch,
        codec_map={"host.mp4": "h264"},
        fps_map={"host.mp4": 30.0},
    )
    manifest = _ManifestTP(keep_segments=[(0.0, 5.0)], host_filters=[], guest_filters=[])
    config = {"video_phase_strategy": "auto"}

    _tp.render_project_two_phase(
        "host.mp4",
        None,
        manifest,
        str(tmp_path / "host_out.mp4"),
        None,
        config,
    )
    metadata = _two_phase_render_metadata(config)

    assert len(captured["audio_phase"]) == 1
    assert len(captured["single_pass"]) == 1
    assert captured["single_pass"][0]["src"] == "host.mp4"
    assert not captured["batched_gpu"]
    assert not captured["smart_copy"]
    assert len(captured["mux_cmds"]) == 1
    tracks = _metadata_tracks(metadata)

    assert metadata["source_codecs"] == {"host": "h264"}
    assert tracks["host"]["strategy_family"] == "single_pass"


def test_shared_auto_routing_mixed_codec_single_pass_validation(monkeypatch, tmp_path):
    """Verify that mixed-codec single_pass routing correctly triggers validation."""
    _tp, captured = _patch_twophase_routing_dependencies(
        monkeypatch,
        codec_map={"host.mp4": "h264", "guest.mp4": "hevc"},
    )
    manifest = _ManifestTP(keep_segments=[(0.0, 1.0)], host_filters=[], guest_filters=[])
    config = {"video_phase_strategy": "auto"}

    _tp.render_project_two_phase(
        "host.mp4",
        "guest.mp4",
        manifest,
        str(tmp_path / "host_out.mp4"),
        str(tmp_path / "guest_out.mp4"),
        config,
    )
    metadata = _two_phase_render_metadata(config)

    assert metadata["strategy_family"] == "single_pass"
    assert "source_codecs" in metadata
