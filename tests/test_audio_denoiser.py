import types

import numpy as np
from pydub import AudioSegment

from analyzers.audio_denoiser import denoise_audio


def _audio_stereo(duration_ms: int = 100, frame_rate: int = 44100) -> AudioSegment:
    """Create a small stereo clip with enough frames for the denoiser path."""
    samples_per_channel = int(frame_rate * duration_ms / 1000)
    t = np.arange(samples_per_channel, dtype=np.float32)
    left = 0.3 * np.sin(2 * np.pi * 220 * t / float(frame_rate))
    right = 0.3 * np.sin(2 * np.pi * 330 * t / float(frame_rate))
    interleaved = np.column_stack((left, right)).reshape(-1)
    pcm = np.rint(interleaved * 32767.0).astype(np.int16)
    return AudioSegment(
        data=pcm.tobytes(),
        sample_width=2,
        frame_rate=frame_rate,
        channels=2,
    )


def _audio_mono_short(duration_ms: int = 1, frame_rate: int = 44100) -> AudioSegment:
    """Create a very short mono clip that should skip denoising."""
    return AudioSegment.silent(duration=duration_ms, frame_rate=frame_rate).set_channels(1)


def test_denoise_audio_stereo_uses_channel_first_for_noisereduce(monkeypatch) -> None:
    calls = {}

    def fake_reduce_noise(*, y, sr, stationary, prop_decrease):
        calls["shape"] = y.shape
        calls["sr"] = sr
        calls["stationary"] = stationary
        calls["prop_decrease"] = prop_decrease
        return y

    monkeypatch.setattr("analyzers.audio_denoiser.HAS_NOISEREDUCE", True)
    monkeypatch.setattr(
        "analyzers.audio_denoiser.nr",
        types.SimpleNamespace(reduce_noise=fake_reduce_noise),
    )

    audio = _audio_stereo(duration_ms=100)
    result = denoise_audio(
        audio,
        {
            "noise_reduction_stationary": True,
            "noise_reduction_prop_decrease": 0.75,
        },
        "Host",
    )

    assert calls["shape"][0] == 2
    assert calls["shape"][1] > 1024
    assert calls["sr"] == 44100
    assert calls["stationary"] is True
    assert calls["prop_decrease"] == 0.75
    assert result.channels == audio.channels
    assert result.frame_rate == audio.frame_rate
    assert result.sample_width == audio.sample_width
    assert len(result.get_array_of_samples()) == len(audio.get_array_of_samples())


def test_denoise_audio_skips_short_segments(monkeypatch) -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("reduce_noise should not be called for short audio")

    monkeypatch.setattr("analyzers.audio_denoiser.HAS_NOISEREDUCE", True)
    monkeypatch.setattr(
        "analyzers.audio_denoiser.nr",
        types.SimpleNamespace(reduce_noise=fail_if_called),
    )

    audio = _audio_mono_short(duration_ms=1)
    result = denoise_audio(audio, {}, "Host")

    assert result.raw_data == audio.raw_data
    assert result.channels == audio.channels
    assert result.frame_rate == audio.frame_rate
