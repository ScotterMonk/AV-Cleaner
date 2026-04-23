import pytest
import os
import sys

# Allow importing repo-root modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.interfaces import EditManifest
from core.sync_invariants import SyncInvariantError
import main

class _DummyAudio:
    def __init__(self, duration_seconds: float):
        self.duration_seconds = duration_seconds

def test_pipeline_manifest_validation_fails_on_invalid_manifest(monkeypatch):
    # Setup a pipeline that produces an invalid manifest (e.g., keep segment > duration)
    monkeypatch.setattr(main, "PIPELINE_CONFIG", {"processors": []})
    
    def _fake_extract_audio(path, target_sr=44100):
        return _DummyAudio(duration_seconds=5.0)
    
    monkeypatch.setattr("core.pipeline.audio_extractor.extract_audio", _fake_extract_audio)
    
    # Mock processor to return an invalid manifest
    class _BadProcessor:
        def get_name(self): return "BadProcessor"
        def process(self, manifest, host_audio, guest_audio, detection_results):
            manifest.keep_segments = [(0.0, 10.0)] # 10s > 5s duration
            return manifest
            
    pipeline = main._build_pipeline({})
    pipeline.processors = [_BadProcessor()]
    
    with pytest.raises(SyncInvariantError):
        pipeline.execute("host.mp4", "guest.mp4")

def test_pipeline_manifest_validation_passes_on_valid_manifest(monkeypatch):
    monkeypatch.setattr(main, "PIPELINE_CONFIG", {"processors": []})
    
    def _fake_extract_audio(path, target_sr=44100):
        return _DummyAudio(duration_seconds=10.0)
    
    monkeypatch.setattr("core.pipeline.audio_extractor.extract_audio", _fake_extract_audio)
    
    # Mock processor to return a valid manifest
    class _GoodProcessor:
        def get_name(self): return "GoodProcessor"
        def process(self, manifest, host_audio, guest_audio, detection_results):
            manifest.keep_segments = [(0.0, 5.0)]
            return manifest
            
    pipeline = main._build_pipeline({})
    pipeline.processors = [_GoodProcessor()]
    captured = {}
    
    # Mock render_project to avoid real FFmpeg
    def _fake_render_project(host_path, guest_path, manifest, out_host, out_guest, config):
        captured["render"] = (host_path, guest_path, out_host, out_guest)
        return {"strategy_family": "single_pass"}

    def _fake_assert_output_pair_sync(host_output, guest_output, *, strategy_family=None):
        captured["sync"] = (host_output, guest_output, strategy_family)

    monkeypatch.setattr("core.pipeline.video_renderer.render_project", _fake_render_project)
    monkeypatch.setattr("core.pipeline.assert_output_pair_sync", _fake_assert_output_pair_sync)
    
    # Should not raise
    host_out, guest_out = pipeline.execute("host.mp4", "guest.mp4")

    assert captured["render"] == ("host.mp4", "guest.mp4", host_out, guest_out)
    assert captured["sync"] == (host_out, guest_out, "single_pass")


def test_pipeline_post_render_sync_validation_fails_on_drift(monkeypatch):
    monkeypatch.setattr(main, "PIPELINE_CONFIG", {"processors": []})

    def _fake_extract_audio(path, target_sr=44100):
        return _DummyAudio(duration_seconds=10.0)

    monkeypatch.setattr("core.pipeline.audio_extractor.extract_audio", _fake_extract_audio)

    class _GoodProcessor:
        def get_name(self): return "GoodProcessor"
        def process(self, manifest, host_audio, guest_audio, detection_results):
            manifest.keep_segments = [(0.0, 5.0)]
            return manifest

    pipeline = main._build_pipeline({})
    pipeline.processors = [_GoodProcessor()]

    def _fake_render_project(host_path, guest_path, manifest, out_host, out_guest, config):
        return {"strategy_family": "chunk_parallel"}

    def _fake_assert_output_pair_sync(host_output, guest_output, *, strategy_family=None):
        raise SyncInvariantError(
            "Output pair drift exceeds tolerance: "
            "container_delta=0.060000s stream_delta=0.050000s tolerance=0.040000s "
            f"host={host_output} guest={guest_output} strategy_family={strategy_family}"
        )

    monkeypatch.setattr("core.pipeline.video_renderer.render_project", _fake_render_project)
    monkeypatch.setattr("core.pipeline.assert_output_pair_sync", _fake_assert_output_pair_sync)

    with pytest.raises(
        SyncInvariantError,
        match=r"container_delta=0\.060000s.*stream_delta=0\.050000s.*strategy_family=chunk_parallel",
    ):
        pipeline.execute("host.mp4", "guest.mp4")
