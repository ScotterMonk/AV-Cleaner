import os
import subprocess
import sys
from typing import Any

# Keep consistent with other tests (ex: tests/test_imports.py): allow importing repo-root modules.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main


class _DummyAudio:
    def __init__(self, *, role: str, duration_seconds: float = 3.0):
        self.role = role
        self.duration_seconds = float(duration_seconds)
        self.frame_rate = 44100
        self.channels = 2
        self.sample_width = 2

    def get_array_of_samples(self):
        # Only needed for the pre-normalization (numpy/pydub) detector path; keep tiny.
        num_frames = int(self.frame_rate * self.duration_seconds)
        return [0] * (num_frames * self.channels)


def _patch_pipeline_deps(
    monkeypatch,
    *,
    host_lufs: float,
    guest_lufs: float,
    expected_af_prefix: str,
):
    # Keep the test focused on pipeline wiring (not real media IO).
    from core import pipeline as pipeline_mod
    from detectors import audio_level_detector as audio_level_detector_mod
    from detectors import spike_fixer_detector as spike_fixer_detector_mod

    monkeypatch.setattr(
        pipeline_mod.audio_extractor,
        "extract_audio",
        lambda video_path, target_sr=44100: _DummyAudio(
            role="host" if "host" in str(video_path).lower() else "guest"
        ),
    )

    def _fake_calculate_lufs(audio):
        return float(host_lufs if getattr(audio, "role", "") == "host" else guest_lufs)

    monkeypatch.setattr(audio_level_detector_mod, "calculate_lufs", _fake_calculate_lufs)

    def _fake_run(cmd, capture_output, text, encoding="utf-8", errors="replace"):
        # Verify post-normalization analysis uses expected AF chain ordering.
        assert "-af" in cmd
        af = cmd[cmd.index("-af") + 1]
        assert af.startswith(expected_af_prefix)
        assert ",astats=metadata=1:reset=1" in af

        # Two 1s windows (reset=1). Window #2 contains a spike over threshold.
        stderr = "\n".join(
            [
                "[Parsed_astats_0 @ 0x0] Overall",
                "Peak level dB: -12.0",
                "[Parsed_astats_0 @ 0x0] Overall",
                "Peak level dB: -2.0",
            ]
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr=stderr)

    monkeypatch.setattr(spike_fixer_detector_mod.subprocess, "run", _fake_run)


def _capture_manifest(monkeypatch):
    from core import pipeline as pipeline_mod

    captured: dict[str, Any] = {"manifest": None, "config": None, "sync": None}

    def _fake_render_project(host_path, guest_path, manifest, out_host, out_guest, config):
        captured["manifest"] = manifest
        captured["config"] = config
        return {"strategy_family": "single_pass"}

    def _fake_assert_output_pair_sync(host_output, guest_output, *, strategy_family=None):
        captured["sync"] = (host_output, guest_output, strategy_family)

    monkeypatch.setattr(pipeline_mod.video_renderer, "render_project", _fake_render_project)
    monkeypatch.setattr(pipeline_mod, "assert_output_pair_sync", _fake_assert_output_pair_sync)
    return captured


def test_pipeline_match_host_normalize_then_spike_fix(monkeypatch):
    # Minimal pipeline for this test: normalize then spike fix.
    monkeypatch.setattr(
        main,
        "PIPELINE_CONFIG",
        {
            "processors": [
                {"type": "AudioNormalizer", "enabled": True},
                {"type": "SpikeFixer", "enabled": True},
                {"type": "SegmentRemover", "enabled": False},
            ]
        },
    )

    config = {
        "normalization": {"mode": "MATCH_HOST", "max_gain_db": 15.0},
        "spike_threshold_db": -6,
        "max_peak_db": -3.0,
    }

    _patch_pipeline_deps(
        monkeypatch,
        host_lufs=-18.0,
        guest_lufs=-30.0,
        expected_af_prefix="volume=",
    )
    captured = _capture_manifest(monkeypatch)

    pipeline = main._build_pipeline(config)
    pipeline.execute("host.mp4", "guest.mp4")

    manifest = captured["manifest"]
    assert manifest is not None
    assert captured["sync"] == ("host_processed.mp4", "guest_processed.mp4", "single_pass")
    assert manifest.guest_filters is not None

    # MATCH_HOST: guest gets `volume` normalization.
    guest_filters = [f for f in manifest.guest_filters if f.filter_name in {"volume", "alimiter"}]
    assert [f.filter_name for f in guest_filters][:1] == ["volume"]
    assert guest_filters[0].stage == "post_trim"
    # SpikeFixer: adds a limiter when spikes detected.
    assert [f.filter_name for f in guest_filters][-1:] == ["alimiter"]
    assert guest_filters[-1].stage == "post_trim"

    # Verify render-stage ordering: normalization before spike fix.
    names = [f.filter_name for f in guest_filters]
    assert names.index("volume") < names.index("alimiter")


def test_pipeline_standard_lufs_normalize_then_spike_fix(monkeypatch):
    monkeypatch.setattr(
        main,
        "PIPELINE_CONFIG",
        {
            "processors": [
                {"type": "AudioNormalizer", "enabled": True},
                {"type": "SpikeFixer", "enabled": True},
                {"type": "SegmentRemover", "enabled": False},
            ]
        },
    )

    config = {
        "normalization": {"mode": "STANDARD_LUFS", "standard_target": -16.0},
        "spike_threshold_db": -6,
        "max_peak_db": -3.0,
    }

    _patch_pipeline_deps(
        monkeypatch,
        host_lufs=-20.0,
        guest_lufs=-30.0,
        expected_af_prefix="loudnorm=",
    )
    captured = _capture_manifest(monkeypatch)

    pipeline = main._build_pipeline(config)
    pipeline.execute("host.mp4", "guest.mp4")

    manifest = captured["manifest"]
    assert manifest is not None
    assert captured["sync"] == ("host_processed.mp4", "guest_processed.mp4", "single_pass")
    assert manifest.host_filters is not None
    assert manifest.guest_filters is not None

    host_filters = [f for f in manifest.host_filters if f.filter_name == "loudnorm"]
    guest_filters = [f for f in manifest.guest_filters if f.filter_name in {"loudnorm", "alimiter"}]

    # STANDARD_LUFS: both tracks get `loudnorm`.
    assert [f.filter_name for f in host_filters] == ["loudnorm"]
    assert host_filters[0].stage == "post_trim"
    assert [f.filter_name for f in guest_filters][:1] == ["loudnorm"]
    assert guest_filters[0].stage == "post_trim"

    # SpikeFixer: adds limiter after loudnorm when spikes detected.
    assert [f.filter_name for f in guest_filters][-1:] == ["alimiter"]
    assert guest_filters[-1].stage == "post_trim"
    names = [f.filter_name for f in guest_filters]
    assert names.index("loudnorm") < names.index("alimiter")

