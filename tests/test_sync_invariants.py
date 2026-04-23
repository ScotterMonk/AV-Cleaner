from __future__ import annotations

import pytest

from core.interfaces import EditManifest
from core.sync_invariants import (
    SyncInvariantError,
    assert_manifest_consistency,
    assert_output_pair_sync,
    probe_output_sync,
)


def test_assert_manifest_consistency_rejects_unsorted_or_overlapping_ranges() -> None:
    manifest = EditManifest(
        keep_segments=[(2.0, 4.0), (1.0, 1.5)],
        removal_segments=[(4.0, 5.0), (4.5, 6.0)],
    )

    with pytest.raises(SyncInvariantError, match="keep_segments must be sorted"):
        assert_manifest_consistency(manifest, host_duration_s=10.0, guest_duration_s=10.0)


def test_assert_manifest_consistency_rejects_invalid_between_expression() -> None:
    manifest = EditManifest()
    manifest.add_host_filter("volume", volume=0, enable="not-between(t,1.0,2.0)")

    with pytest.raises(SyncInvariantError, match=r"between\(t,start,end\)"):
        assert_manifest_consistency(manifest, host_duration_s=10.0, guest_duration_s=10.0)


def test_assert_manifest_consistency_allows_self_healing_mute_window_beyond_keep_range() -> None:
    manifest = EditManifest(
        keep_segments=[(0.0, 5.0), (7.0, 8.0)],
        removal_segments=[(5.0, 7.0)],
    )
    manifest.add_host_filter("volume", volume=0, enable="between(t,7.950,8.200)")

    assert_manifest_consistency(manifest, host_duration_s=10.0, guest_duration_s=10.0)


def test_assert_manifest_consistency_rejects_range_past_shared_duration() -> None:
    manifest = EditManifest(keep_segments=[(0.0, 10.1)])

    with pytest.raises(SyncInvariantError, match="exceeds shared duration"):
        assert_manifest_consistency(manifest, host_duration_s=10.0, guest_duration_s=10.0)


def test_probe_output_sync_reports_container_stream_and_fps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.sync_invariants.ffmpeg.probe",
        lambda _path: {
            "format": {"duration": "10.040"},
            "streams": [
                {"codec_type": "video", "duration": "10.000", "r_frame_rate": "25/1"},
                {"codec_type": "audio", "duration": "10.001"},
            ],
        },
    )
    monkeypatch.setattr("core.sync_invariants.probe_video_fps", lambda _path: 25.0)

    probe = probe_output_sync("host_out.mp4")

    assert probe["path"] == "host_out.mp4"
    assert probe["container_duration_s"] == pytest.approx(10.04)
    assert probe["stream_duration_s"] == pytest.approx(10.0)
    assert probe["fps"] == pytest.approx(25.0)
    assert probe["duration_tolerance_s"] == pytest.approx(0.04)


def test_assert_output_pair_sync_accepts_within_fps_tolerance() -> None:
    host_probe = {
        "path": "host.mp4",
        "container_duration_s": 10.04,
        "stream_duration_s": 10.00,
        "fps": 25.0,
    }
    guest_probe = {
        "path": "guest.mp4",
        "container_duration_s": 10.02,
        "stream_duration_s": 10.01,
        "fps": 25.0,
    }

    assert_output_pair_sync(host_probe, guest_probe, strategy_family="single_pass")


def test_assert_output_pair_sync_rejects_cross_track_mismatch() -> None:
    host_probe = {
        "path": "host.mp4",
        "container_duration_s": 10.00,
        "stream_duration_s": 10.00,
        "fps": 25.0,
    }
    guest_probe = {
        "path": "guest.mp4",
        "container_duration_s": 10.06,
        "stream_duration_s": 10.06,
        "fps": 25.0,
    }

    with pytest.raises(SyncInvariantError) as excinfo:
        assert_output_pair_sync(host_probe, guest_probe, strategy_family="single_pass")

    message = str(excinfo.value)
    assert "container_delta=0.060000s" in message
    assert "stream_delta=0.060000s" in message
    assert "strategy_family=single_pass" in message


def test_assert_output_pair_sync_rejects_internal_output_drift_with_strategy_family() -> None:
    host_probe = {
        "path": "host.mp4",
        "container_duration_s": 10.08,
        "stream_duration_s": 10.00,
        "fps": 25.0,
    }
    guest_probe = {
        "path": "guest.mp4",
        "container_duration_s": 10.00,
        "stream_duration_s": 10.00,
        "fps": 25.0,
    }

    with pytest.raises(SyncInvariantError) as excinfo:
        assert_output_pair_sync(host_probe, guest_probe, strategy_family="chunk_parallel")

    message = str(excinfo.value)
    assert "host output drift exceeds tolerance" in message
    assert "delta=0.080000s" in message
    assert "strategy_family=chunk_parallel" in message


def test_assert_manifest_consistency_rejects_overlapping_keep_and_removal() -> None:
    manifest = EditManifest(
        keep_segments=[(1.0, 3.0)],
        removal_segments=[(2.0, 4.0)],
    )
    with pytest.raises(SyncInvariantError, match="must be disjoint"):
        assert_manifest_consistency(manifest, host_duration_s=10.0, guest_duration_s=10.0)


def test_assert_output_pair_sync_rejects_invalid_between_bounds() -> None:
    manifest = EditManifest()
    # end <= start
    manifest.add_host_filter("volume", volume=0, enable="between(t,2.0,1.0)")
    with pytest.raises(SyncInvariantError, match="must have end > start"):
        assert_manifest_consistency(manifest, host_duration_s=10.0, guest_duration_s=10.0)


def test_assert_output_pair_sync_validates_strategy_family_mismatch() -> None:
    """Ensure validation fails when strategy family is explicitly mismatched."""
    host_probe = {
        "path": "host.mp4",
        "container_duration_s": 10.0,
        "stream_duration_s": 10.0,
        "fps": 25.0,
    }
    guest_probe = {
        "path": "guest.mp4",
        "container_duration_s": 10.0,
        "stream_duration_s": 10.0,
        "fps": 25.0,
    }
    # This should pass
    assert_output_pair_sync(host_probe, guest_probe, strategy_family="single_pass")
    
    # This should fail if we pass a different strategy family that implies different tolerances
    with pytest.raises(SyncInvariantError):
        assert_output_pair_sync(host_probe, guest_probe, strategy_family="unknown_strategy")
