"""Authoritative sync invariant helpers for manifests and rendered outputs."""

from __future__ import annotations

import re
from typing import Any, Mapping

import ffmpeg

from core.interfaces import EditManifest
from io_.media_probe import probe_video_fps


_BETWEEN_ENABLE_RE = re.compile(
    r"^\s*between\s*\(\s*t\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)\s*$"
)


class SyncInvariantError(RuntimeError):
    """Raised when manifest or rendered-output sync invariants are violated."""


def _duration_tolerance_s(fps: float | None) -> float:
    """Return the fps-aware duration tolerance for output checks."""
    if fps is None or fps <= 0:
        return 0.01
    return max(0.01, 1.0 / fps)


def _parse_float(value: Any, *, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SyncInvariantError(f"Invalid {label}: {value!r}") from exc
    return parsed


def _parse_probe_duration(value: Any, *, label: str, path: str) -> float:
    if value in (None, ""):
        raise SyncInvariantError(f"Missing {label} duration in probe data for {path}")
    parsed = _parse_float(value, label=f"{label} duration")
    if parsed <= 0:
        raise SyncInvariantError(f"Non-positive {label} duration in probe data for {path}: {parsed}")
    return parsed


def _range_validate(
    ranges: list[tuple[float, float]], *, label: str, max_duration_s: float
) -> None:
    previous_end: float | None = None
    previous_start: float | None = None
    for index, (start_raw, end_raw) in enumerate(ranges):
        start_s = _parse_float(start_raw, label=f"{label}[{index}] start")
        end_s = _parse_float(end_raw, label=f"{label}[{index}] end")
        if start_s < 0:
            raise SyncInvariantError(f"{label}[{index}] starts before zero: {start_s:.6f}")
        if end_s <= start_s:
            raise SyncInvariantError(
                f"{label}[{index}] must have end > start, got ({start_s:.6f}, {end_s:.6f})"
            )
        if end_s > max_duration_s:
            raise SyncInvariantError(
                f"{label}[{index}] exceeds shared duration {max_duration_s:.6f}s: "
                f"({start_s:.6f}, {end_s:.6f})"
            )
        if previous_start is not None and start_s < previous_start:
            raise SyncInvariantError(f"{label} must be sorted by start time")
        if previous_end is not None and start_s < previous_end:
            raise SyncInvariantError(
                f"{label} contains overlapping ranges: "
                f"previous_end={previous_end:.6f}s current_start={start_s:.6f}s"
            )
        previous_start = start_s
        previous_end = end_s


def _ranges_assert_disjoint(
    keep_segments: list[tuple[float, float]], removal_segments: list[tuple[float, float]]
) -> None:
    removal_index = 0
    for keep_start, keep_end in keep_segments:
        while removal_index < len(removal_segments) and removal_segments[removal_index][1] <= keep_start:
            removal_index += 1
        if removal_index >= len(removal_segments):
            break
        removal_start, removal_end = removal_segments[removal_index]
        if removal_start < keep_end and keep_start < removal_end:
            raise SyncInvariantError(
                "keep_segments and removal_segments must be disjoint: "
                f"keep=({keep_start:.6f}, {keep_end:.6f}) removal=({removal_start:.6f}, {removal_end:.6f})"
            )


def _filter_window_parse(enable_expr: str) -> tuple[float, float]:
    match = _BETWEEN_ENABLE_RE.match(enable_expr)
    if not match:
        raise SyncInvariantError(
            "Expected enable expression in the form between(t,start,end), "
            f"got {enable_expr!r}"
        )
    start_s = _parse_float(match.group(1), label="enable start")
    end_s = _parse_float(match.group(2), label="enable end")
    if start_s < 0:
        raise SyncInvariantError(f"enable window starts before zero: {start_s:.6f}")
    if end_s <= start_s:
        raise SyncInvariantError(
            f"enable window must have end > start, got ({start_s:.6f}, {end_s:.6f})"
        )
    return start_s, end_s


def _filter_windows_assert_valid(filters: list[Any], *, track_label: str, track_duration_s: float) -> None:
    tolerance_s = 0.01
    for index, filter_spec in enumerate(filters):
        params = getattr(filter_spec, "params", None)
        if not isinstance(params, Mapping):
            raise SyncInvariantError(f"{track_label}_filters[{index}] params must be a mapping")
        enable_expr = params.get("enable")
        if enable_expr is None:
            continue
        start_s, _end_s = _filter_window_parse(str(enable_expr))
        if start_s > track_duration_s + tolerance_s:
            raise SyncInvariantError(
                f"{track_label}_filters[{index}] starts after {track_label} duration "
                f"{track_duration_s:.6f}s: {start_s:.6f}s"
            )


def _probe_primary_stream(probe_data: Mapping[str, Any]) -> Mapping[str, Any] | None:
    streams = probe_data.get("streams", [])
    if not isinstance(streams, list):
        return None
    for stream in streams:
        if isinstance(stream, Mapping) and stream.get("codec_type") == "video":
            return stream
    for stream in streams:
        if isinstance(stream, Mapping):
            return stream
    return None


def _probe_coerce(output_or_probe: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(output_or_probe, str):
        return probe_output_sync(output_or_probe)
    required_keys = {"path", "container_duration_s", "stream_duration_s", "fps"}
    missing_keys = required_keys.difference(output_or_probe.keys())
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise SyncInvariantError(f"Probe data is missing required keys: {missing}")
    probe = dict(output_or_probe)
    probe["container_duration_s"] = _parse_float(
        probe["container_duration_s"], label="container duration"
    )
    probe["stream_duration_s"] = _parse_float(probe["stream_duration_s"], label="stream duration")
    fps = probe.get("fps")
    probe["fps"] = None if fps is None else _parse_float(fps, label="fps")
    probe["duration_tolerance_s"] = _duration_tolerance_s(probe["fps"])
    return probe


def assert_manifest_consistency(
    manifest: EditManifest, host_duration_s: float, guest_duration_s: float
) -> None:
    """Fail fast when a manifest violates sync-safe timeline invariants."""
    shared_duration_s = min(
        _parse_float(host_duration_s, label="host duration"),
        _parse_float(guest_duration_s, label="guest duration"),
    )
    if shared_duration_s <= 0:
        raise SyncInvariantError(f"Shared duration must be positive, got {shared_duration_s!r}")

    keep_segments = list(manifest.keep_segments)
    removal_segments = list(manifest.removal_segments)

    _range_validate(keep_segments, label="keep_segments", max_duration_s=shared_duration_s)
    _range_validate(removal_segments, label="removal_segments", max_duration_s=shared_duration_s)
    if keep_segments and removal_segments:
        _ranges_assert_disjoint(keep_segments, removal_segments)

    _filter_windows_assert_valid(
        list(manifest.host_filters),
        track_label="host",
        track_duration_s=_parse_float(host_duration_s, label="host duration"),
    )
    _filter_windows_assert_valid(
        list(manifest.guest_filters),
        track_label="guest",
        track_duration_s=_parse_float(guest_duration_s, label="guest duration"),
    )


def probe_output_sync(output_path: str) -> dict[str, Any]:
    """Probe one rendered output for later sync assertions."""
    try:
        probe_data = ffmpeg.probe(output_path)
    except Exception as exc:  # pragma: no cover - exact exception depends on ffmpeg-python
        raise SyncInvariantError(f"ffmpeg.probe failed for {output_path}: {exc}") from exc

    format_data = probe_data.get("format", {})
    if not isinstance(format_data, Mapping):
        raise SyncInvariantError(f"Probe data for {output_path} is missing format metadata")

    container_duration_s = _parse_probe_duration(
        format_data.get("duration"), label="container", path=output_path
    )
    primary_stream = _probe_primary_stream(probe_data)
    if primary_stream is None:
        raise SyncInvariantError(f"Probe data for {output_path} has no streams")

    stream_duration_raw = primary_stream.get("duration")
    if stream_duration_raw in (None, ""):
        stream_duration_s = container_duration_s
    else:
        stream_duration_s = _parse_probe_duration(
            stream_duration_raw, label="stream", path=output_path
        )

    fps = probe_video_fps(output_path)

    return {
        "path": output_path,
        "container_duration_s": container_duration_s,
        "stream_duration_s": stream_duration_s,
        "fps": fps,
        "duration_tolerance_s": _duration_tolerance_s(fps),
    }


def assert_output_pair_sync(
    host_output: str | Mapping[str, Any],
    guest_output: str | Mapping[str, Any],
    *,
    strategy_family: str | None = None,
) -> None:
    """Assert per-file and cross-file output duration sync within fps-aware tolerances."""
    host_probe = _probe_coerce(host_output)
    guest_probe = _probe_coerce(guest_output)
    valid_strategy_families = {"auto", "smart_copy", "single_pass", "batched_gpu", "chunk_parallel"}
    if strategy_family is not None and strategy_family not in valid_strategy_families:
        raise SyncInvariantError(
            "Unknown strategy_family for sync validation: "
            f"{strategy_family!r}. Expected one of {sorted(valid_strategy_families)!r}"
        )
    strategy_suffix = f" strategy_family={strategy_family}" if strategy_family else ""

    for label, probe in (("host", host_probe), ("guest", guest_probe)):
        internal_delta_s = abs(probe["container_duration_s"] - probe["stream_duration_s"])
        if internal_delta_s > probe["duration_tolerance_s"]:
            raise SyncInvariantError(
                f"{label} output drift exceeds tolerance: container={probe['container_duration_s']:.6f}s "
                f"stream={probe['stream_duration_s']:.6f}s delta={internal_delta_s:.6f}s "
                f"tolerance={probe['duration_tolerance_s']:.6f}s path={probe['path']}"
                f"{strategy_suffix}"
            )

    pair_tolerance_s = max(host_probe["duration_tolerance_s"], guest_probe["duration_tolerance_s"])
    container_delta_s = abs(host_probe["container_duration_s"] - guest_probe["container_duration_s"])
    stream_delta_s = abs(host_probe["stream_duration_s"] - guest_probe["stream_duration_s"])

    if container_delta_s > pair_tolerance_s or stream_delta_s > pair_tolerance_s:
        raise SyncInvariantError(
            "Output pair drift exceeds tolerance: "
            f"container_delta={container_delta_s:.6f}s stream_delta={stream_delta_s:.6f}s "
            f"tolerance={pair_tolerance_s:.6f}s host={host_probe['path']} guest={guest_probe['path']}"
            f"{strategy_suffix}"
        )
