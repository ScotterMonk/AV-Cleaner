class _FakeFilter:
    def __init__(self, filter_name, params):
        self.filter_name = filter_name
        self.params = params


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
    """Single-pass helper keeps CPU-side filter input kwargs even when CUDA decode is enabled."""

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
    monkeypatch.setattr(
        _tp,
        "run_with_progress",
        lambda stream, **kwargs: calls.__setitem__("run_with_progress", {"stream": stream, "kwargs": dict(kwargs)}),
    )

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
