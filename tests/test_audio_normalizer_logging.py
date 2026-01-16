import logging


def test_audio_normalizer_logs_match_host(monkeypatch, caplog):
    from core.interfaces import EditManifest
    from processors.audio_normalizer import AudioNormalizer

    # Deterministic loudness values (avoid dependence on pyloudnorm/pydub internals)
    values = iter([-16.2, -22.5])
    monkeypatch.setattr(
        "processors.audio_normalizer.calculate_lufs",
        lambda _audio: next(values),
    )

    processor = AudioNormalizer(
        {
            "normalization": {
                "mode": "MATCH_HOST",
                "max_gain_db": 15.0,
            }
        }
    )

    caplog.set_level(logging.INFO)
    processor.process(EditManifest(), object(), object(), {})

    assert "[PROCESSOR] Audio analysis - Host: -16.2 LUFS, Guest: -22.5 LUFS" in caplog.text
    assert "[PROCESSOR] Normalized guest audio - Applied +6.3 dB gain to match host" in caplog.text


def test_audio_normalizer_logs_standard_lufs(monkeypatch, caplog):
    from core.interfaces import EditManifest
    from processors.audio_normalizer import AudioNormalizer

    values = iter([-18.0, -24.0])
    monkeypatch.setattr(
        "processors.audio_normalizer.calculate_lufs",
        lambda _audio: next(values),
    )

    processor = AudioNormalizer(
        {
            "normalization": {
                "mode": "STANDARD_LUFS",
                "standard_target": -16.0,
            }
        }
    )

    caplog.set_level(logging.INFO)
    processor.process(EditManifest(), object(), object(), {})

    assert "[PROCESSOR] Audio analysis - Host: -18.0 LUFS, Guest: -24.0 LUFS" in caplog.text
    assert "[PROCESSOR] Normalized both tracks - Target: -16.0 LUFS (STANDARD_LUFS mode)" in caplog.text
