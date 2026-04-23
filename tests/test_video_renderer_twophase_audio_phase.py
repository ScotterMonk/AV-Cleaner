from dataclasses import dataclass
from typing import Any, Dict
from unittest.mock import patch


@dataclass
class _FakeFilter:
    """Minimal AudioFilter stand-in for unit tests."""

    filter_name: str
    params: Dict[str, Any]


def _compile_stream(stream) -> list[str]:
    """Compile an ffmpeg-python stream to a list of command-line args without execution."""

    import ffmpeg

    return ffmpeg.compile(stream, overwrite_output=True)


def test_afftdn_delay_s_48k():
    """48 kHz maps the 4096-sample warm-up window to about 85.4 ms."""

    from io_.video_renderer_twophase import _afftdn_delay_s

    assert _afftdn_delay_s(48000) == 0.0854


def test_afftdn_delay_s_44k():
    """44.1 kHz maps the 4096-sample warm-up window to about 92.9 ms."""

    from io_.video_renderer_twophase import _afftdn_delay_s

    assert _afftdn_delay_s(44100) == 0.0929


def test_render_audio_phase_single_segment_no_asplit():
    """Single segment plus no filters applies `atrim` without `asplit`."""

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
    assert "atrim" in args, f"Expected 'atrim' in compiled args; got:\n{args}"
    assert "asplit" not in args, f"Unexpected 'asplit' in compiled args:\n{args}"
    assert "-vn" in captured["args"], f"Expected '-vn' flag; args={captured['args']}"


def test_render_audio_phase_with_filters():
    """Multiple segments plus filters apply filters before per-segment `atrim`."""

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
    assert "asplit" in args, f"Expected 'asplit' in compiled args; got:\n{args}"
    assert "atrim" in args, f"Expected 'atrim' in compiled args; got:\n{args}"
    assert "concat" in args, f"Expected 'concat' in compiled args; got:\n{args}"
    assert "alimiter" in args, f"Expected 'alimiter' in compiled args; got:\n{args}"
    assert args.index("alimiter") < args.index("atrim"), f"Expected filter before atrim; got:\n{args}"
    assert "-vn" in captured["args"], f"Expected '-vn' flag; args={captured['args']}"


def test_render_audio_phase_no_segments():
    """Empty keep-segments leave full audio passthrough without trim or concat nodes."""

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
    assert "atrim" not in args, f"Unexpected 'atrim' in no-segment args:\n{args}"
    assert "asplit" not in args, f"Unexpected 'asplit' in no-segment args:\n{args}"
    assert "concat" not in args, f"Unexpected 'concat' in no-segment args:\n{args}"
    assert "-vn" in captured["args"], f"Expected '-vn' flag; args={captured['args']}"


def test_render_audio_phase_afftdn_inserts_compensation():
    """`afftdn` adds compensation `atrim` plus `asetpts` after the denoiser stage."""

    captured = {}

    def _fake_run_with_progress(stream, **kwargs):
        captured["args"] = _compile_stream(stream)

    afftdn_filter = _FakeFilter(filter_name="afftdn", params={"nr": 10})

    with (
        patch("io_.video_renderer_twophase.run_with_progress", _fake_run_with_progress),
        patch("io_.video_renderer_twophase.probe_audio_sample_rate", return_value=48000),
    ):
        from io_.video_renderer_twophase import render_audio_phase

        render_audio_phase(
            input_path="fake.mp4",
            filters=[afftdn_filter],
            keep_segments=[(0.0, 5.0)],
            out_path="fake_audio.m4a",
            audio_opts={"acodec": "aac"},
        )

    assert captured, "run_with_progress was never called"
    args_joined = " ".join(captured["args"])
    assert "afftdn" in args_joined, f"Expected 'afftdn' in compiled args; got:\n{args_joined}"
    afftdn_pos = args_joined.index("afftdn")
    first_atrim = args_joined.index("atrim")
    second_atrim = args_joined.index("atrim", first_atrim + 1)
    assert second_atrim > first_atrim, f"Expected 2 atrim occurrences; got:\n{args_joined}"
    assert afftdn_pos < first_atrim, f"Expected afftdn before first atrim; got:\n{args_joined}"
    assert "asetpts" in args_joined, f"Expected 'asetpts' in compiled args; got:\n{args_joined}"


def test_render_audio_phase_non_afftdn_filter_no_compensation():
    """Non-`afftdn` filters do not insert extra compensation trim nodes."""

    captured = {}

    def _fake_run_with_progress(stream, **kwargs):
        captured["args"] = _compile_stream(stream)

    volume_filter = _FakeFilter(filter_name="volume", params={"volume": 1.5})

    with (
        patch("io_.video_renderer_twophase.run_with_progress", _fake_run_with_progress),
        patch("io_.video_renderer_twophase.probe_audio_sample_rate", return_value=48000),
    ):
        from io_.video_renderer_twophase import render_audio_phase

        render_audio_phase(
            input_path="fake.mp4",
            filters=[volume_filter],
            keep_segments=[(0.0, 5.0)],
            out_path="fake_audio.m4a",
            audio_opts={"acodec": "aac"},
        )

    assert captured, "run_with_progress was never called"
    args_joined = " ".join(captured["args"])
    assert "volume" in args_joined, f"Expected 'volume' in compiled args; got:\n{args_joined}"
    first_atrim = args_joined.find("atrim")
    assert first_atrim != -1, f"Expected exactly 1 atrim in args; got none:\n{args_joined}"
    second_atrim = args_joined.find("atrim", first_atrim + 1)
    assert second_atrim == -1, f"Expected exactly 1 atrim; got:\n{args_joined}"
    assert "afftdn" not in args_joined, f"Unexpected 'afftdn' in args:\n{args_joined}"


def test_config_two_phase_keys():
    """Two-phase config defaults are present in the high-quality preset."""

    from config import QUALITY_PRESETS

    assert QUALITY_PRESETS["PODCAST_HIGH_QUALITY"]["two_phase_render_enabled"] is True
    assert QUALITY_PRESETS["PODCAST_HIGH_QUALITY"]["keyframe_snap_tolerance_s"] == 0.1


def test_config_video_phase_strategy_key():
    """High-quality preset defaults the video phase strategy to auto."""

    from config import QUALITY_PRESETS

    assert QUALITY_PRESETS["PODCAST_HIGH_QUALITY"]["video_phase_strategy"] == "auto"
