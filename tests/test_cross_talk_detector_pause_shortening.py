# tests/test_cross_talk_detector_pause_shortening.py

import numpy as np


def test_cross_talk_detector_removes_beyond_new_pause_duration(monkeypatch):
    """Mid-recording pause: keep new_pause_duration, remove the rest."""
    from detectors.cross_talk_detector import CrossTalkDetector

    # 120 windows @ 100ms = 12.0s total audio.
    # Windows 0-19  (0.0-2.0s): loud (host/guest speaking)
    # Windows 20-69 (2.0-7.0s): silence (5.0s pause in the middle)
    # Windows 70-119 (7.0-12.0s): loud (speaking resumes)
    db = np.full((120,), -10.0)        # loud by default
    db[20:70] = -100.0                 # silence from 2.0s to 7.0s

    def fake_envelope(_audio, window_ms: int):
        assert window_ms == 100
        return db.copy()

    monkeypatch.setattr("detectors.cross_talk_detector.calculate_db_envelope", fake_envelope)
    monkeypatch.setattr(CrossTalkDetector, "_verify_mutual_silence", lambda *a, **k: True)

    detector = CrossTalkDetector(
        config={
            "silence_threshold_db": -20,
            "max_pause_duration": 1.2,
            "new_pause_duration": 0.5,
            "silence_window_ms": 100,
        }
    )

    host_audio = type("A", (), {"frame_rate": 44100})()
    guest_audio = type("A", (), {"frame_rate": 44100})()

    regions = detector.detect(host_audio, guest_audio)
    # Pause detected at (2.0, 7.0). Keep 0.5s -> remove (2.5, 7.0).
    assert regions == [(2.5, 7.0)]


def test_cross_talk_detector_removes_nothing_when_new_pause_longer_than_detected_pause(monkeypatch):
    """When new_pause_duration exceeds the detected pause, nothing is removed."""
    from detectors.cross_talk_detector import CrossTalkDetector

    # 40 windows @ 100ms = 4.0s total audio.
    # Windows 0-9   (0.0-1.0s): loud
    # Windows 10-22 (1.0-2.3s): silence (1.3s pause)
    # Windows 23-39 (2.3-4.0s): loud
    db = np.full((40,), -10.0)
    db[10:23] = -100.0

    def fake_envelope(_audio, window_ms: int):
        assert window_ms == 100
        return db.copy()

    monkeypatch.setattr("detectors.cross_talk_detector.calculate_db_envelope", fake_envelope)
    monkeypatch.setattr(CrossTalkDetector, "_verify_mutual_silence", lambda *a, **k: True)

    detector = CrossTalkDetector(
        config={
            "silence_threshold_db": -20,
            "max_pause_duration": 1.0,
            "new_pause_duration": 2.0,
            "silence_window_ms": 100,
        }
    )

    host_audio = type("A", (), {"frame_rate": 44100})()
    guest_audio = type("A", (), {"frame_rate": 44100})()

    regions = detector.detect(host_audio, guest_audio)
    assert regions == []


def test_cross_talk_detector_boundary_guard_skips_leading_silence(monkeypatch):
    """Silence at the very beginning of the recording must not be removed."""
    from detectors.cross_talk_detector import CrossTalkDetector

    # 120 windows @ 100ms = 12.0s total audio.
    # Windows 0-99  (0.0-10.0s): silence (leading intro / countdown)
    # Windows 100-119 (10.0-12.0s): loud (speaking starts)
    db = np.full((120,), -100.0)       # silence by default
    db[100:120] = -10.0                # speaking starts at 10.0s

    def fake_envelope(_audio, window_ms: int):
        assert window_ms == 100
        return db.copy()

    monkeypatch.setattr("detectors.cross_talk_detector.calculate_db_envelope", fake_envelope)
    monkeypatch.setattr(CrossTalkDetector, "_verify_mutual_silence", lambda *a, **k: True)

    detector = CrossTalkDetector(
        config={
            "silence_threshold_db": -20,
            "max_pause_duration": 1.0,
            "new_pause_duration": 0.8,
            "silence_window_ms": 100,
        }
    )

    host_audio = type("A", (), {"frame_rate": 44100})()
    guest_audio = type("A", (), {"frame_rate": 44100})()

    regions = detector.detect(host_audio, guest_audio)
    # The leading silence (0.0-10.0s) must be skipped by boundary guard.
    assert regions == []


def test_cross_talk_detector_boundary_guard_skips_trailing_silence(monkeypatch):
    """Silence at the very end of the recording must not be removed."""
    from detectors.cross_talk_detector import CrossTalkDetector

    # 120 windows @ 100ms = 12.0s total audio.
    # Windows 0-19  (0.0-2.0s): loud
    # Windows 20-119 (2.0-12.0s): silence (trailing outro)
    db = np.full((120,), -100.0)
    db[0:20] = -10.0

    def fake_envelope(_audio, window_ms: int):
        assert window_ms == 100
        return db.copy()

    monkeypatch.setattr("detectors.cross_talk_detector.calculate_db_envelope", fake_envelope)
    monkeypatch.setattr(CrossTalkDetector, "_verify_mutual_silence", lambda *a, **k: True)

    detector = CrossTalkDetector(
        config={
            "silence_threshold_db": -20,
            "max_pause_duration": 1.0,
            "new_pause_duration": 0.8,
            "silence_window_ms": 100,
        }
    )

    host_audio = type("A", (), {"frame_rate": 44100})()
    guest_audio = type("A", (), {"frame_rate": 44100})()

    regions = detector.detect(host_audio, guest_audio)
    # The trailing silence (2.0-12.0s) must be skipped by boundary guard.
    assert regions == []


def test_cross_talk_detector_boundary_guard_keeps_middle_pauses(monkeypatch):
    """Mid-recording pauses are still detected even when head/tail silence exists."""
    from detectors.cross_talk_detector import CrossTalkDetector

    # 200 windows @ 100ms = 20.0s total audio.
    # Windows 0-29   (0.0-3.0s):  silence (leading — guarded)
    # Windows 30-59  (3.0-6.0s):  loud
    # Windows 60-109 (6.0-11.0s): silence (mid-conversation pause — NOT guarded)
    # Windows 110-169 (11.0-17.0s): loud
    # Windows 170-199 (17.0-20.0s): silence (trailing — guarded)
    db = np.full((200,), -10.0)        # loud by default
    db[0:30] = -100.0                  # leading silence
    db[60:110] = -100.0                # mid-conversation pause
    db[170:200] = -100.0               # trailing silence

    def fake_envelope(_audio, window_ms: int):
        assert window_ms == 100
        return db.copy()

    monkeypatch.setattr("detectors.cross_talk_detector.calculate_db_envelope", fake_envelope)
    monkeypatch.setattr(CrossTalkDetector, "_verify_mutual_silence", lambda *a, **k: True)

    detector = CrossTalkDetector(
        config={
            "silence_threshold_db": -20,
            "max_pause_duration": 1.0,
            "new_pause_duration": 0.5,
            "silence_window_ms": 100,
        }
    )

    host_audio = type("A", (), {"frame_rate": 44100})()
    guest_audio = type("A", (), {"frame_rate": 44100})()

    regions = detector.detect(host_audio, guest_audio)
    # Only the middle pause should be detected: (6.0, 11.0) → keep 0.5s → (6.5, 11.0)
    # Leading (0.0-3.0) and trailing (17.0-20.0) are guarded.
    assert regions == [(6.5, 11.0)]
