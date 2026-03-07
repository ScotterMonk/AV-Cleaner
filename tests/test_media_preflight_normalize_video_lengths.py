from __future__ import annotations

import os
import sys

import pytest

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_normalize_video_lengths_equal_returns_inputs(monkeypatch):
    from io_ import media_preflight

    monkeypatch.setattr(media_preflight, "get_video_duration_seconds", lambda _p: 10.0)

    called = []

    def _nope(_plan):
        called.append(True)

    monkeypatch.setattr(media_preflight, "_video_pad_to_duration", _nope)

    host_out, guest_out = media_preflight.normalize_video_lengths("host.mp4", "guest.mp4")
    assert (host_out, guest_out) == ("host.mp4", "guest.mp4")
    assert called == []


def test_normalize_video_lengths_returns_inputs_when_within_tolerance(monkeypatch):
    from io_ import media_preflight

    durations = {"host.mp4": 10.0, "guest.mp4": 10.005}
    monkeypatch.setattr(media_preflight, "get_video_duration_seconds", lambda p: durations[p])

    called = []

    def _nope(_plan):
        called.append(True)

    monkeypatch.setattr(media_preflight, "_video_pad_to_duration", _nope)

    host_out, guest_out = media_preflight.normalize_video_lengths("host.mp4", "guest.mp4")
    assert (host_out, guest_out) == ("host.mp4", "guest.mp4")
    assert called == []


def test_normalize_video_lengths_normalizes_when_outside_tolerance(monkeypatch):
    from io_ import media_preflight

    durations = {"host.mp4": 10.0, "guest.mp4": 10.02}
    monkeypatch.setattr(media_preflight, "get_video_duration_seconds", lambda p: durations[p])

    calls = []

    def _capture(plan):
        calls.append(plan)

    monkeypatch.setattr(media_preflight, "_video_pad_to_duration", _capture)

    host_out, guest_out = media_preflight.normalize_video_lengths("host.mp4", "guest.mp4")

    assert host_out.endswith("_preflight.mp4")
    assert guest_out.endswith("_preflight.mp4")
    assert len(calls) == 2

    by_in = {c.input_path: c for c in calls}
    assert by_in["host.mp4"].target_duration_s == 10.02
    assert by_in["host.mp4"].pad_seconds == pytest.approx(0.02)
    assert by_in["guest.mp4"].target_duration_s == 10.02
    assert by_in["guest.mp4"].pad_seconds == 0.0


def test_normalize_video_lengths_mismatch_writes_both_outputs(monkeypatch):
    from io_ import media_preflight

    logged: list[str] = []

    class _FakeLogger:
        def info(self, msg, *args, **kwargs):
            if args:
                msg = msg % args
            logged.append(str(msg))

        def warning(self, msg, *args, **kwargs):
            if args:
                msg = msg % args
            logged.append(str(msg))

    monkeypatch.setattr(media_preflight, "logger", _FakeLogger())

    durations = {"host.mp4": 10.0, "guest.mp4": 8.0}
    monkeypatch.setattr(media_preflight, "get_video_duration_seconds", lambda p: durations[p])

    calls = []

    def _capture(plan):
        calls.append(plan)

    monkeypatch.setattr(media_preflight, "_video_pad_to_duration", _capture)

    host_out, guest_out = media_preflight.normalize_video_lengths("host.mp4", "guest.mp4")
    assert host_out.endswith("_preflight.mp4")
    assert guest_out.endswith("_preflight.mp4")

    assert len(calls) == 2
    by_in = {c.input_path: c for c in calls}

    assert by_in["host.mp4"].target_duration_s == 10.0
    assert by_in["host.mp4"].pad_seconds == 0.0
    assert by_in["guest.mp4"].target_duration_s == 10.0
    assert by_in["guest.mp4"].pad_seconds == 2.0

    assert any("[PREFLIGHT COMPLETE]" in m for m in logged)
    assert any("Preflight pair written" in m for m in logged)


