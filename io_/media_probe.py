"""io_/media_probe.py

Media probing helpers.

This module is intentionally non-UI so it can be reused by both CLI + GUI.
"""

from __future__ import annotations

import os
import subprocess

import ffmpeg


def get_video_duration_seconds(video_path: str) -> float:
    """Return the media container duration (seconds) as reported by ffprobe.

    Notes:
    - This expects `ffprobe` to be available on PATH (typically alongside `ffmpeg`).
    - Duration is returned as a float in seconds.
    - If ffprobe cannot determine duration (or is missing), a clear exception is raised.
    """

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Use a compact, stable ffprobe output format for duration.
    # Example output: "123.456789\n"
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            "ffprobe is required to determine video duration, but was not found on PATH. "
            "Install FFmpeg (including ffprobe) and ensure it is available on PATH."
        ) from e
    except OSError as e:
        raise RuntimeError(f"Failed to run ffprobe to probe duration for: {video_path}") from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        detail = stderr or stdout or f"ffprobe returncode={proc.returncode}"
        raise RuntimeError(f"ffprobe failed to probe duration for: {video_path} ({detail})")

    raw = (proc.stdout or "").strip()
    try:
        duration = float(raw)
    except ValueError as e:
        raise RuntimeError(
            f"ffprobe returned an invalid duration for: {video_path} (stdout={raw!r})"
        ) from e

    if duration <= 0:
        raise RuntimeError(f"ffprobe returned a non-positive duration for: {video_path} ({duration})")

    return duration


def probe_video_keyframes(video_path: str) -> list[float]:
    """Return a sorted list of keyframe timestamps (in seconds) for the first video stream.

    Uses ffprobe with the following column order — do NOT reorder, as stdout parsing depends on it:
        key_frame, pts_time

    Each stdout line is parsed as "<key_frame>,<pts_time>".  Only lines where
    ``key_frame == "1"`` are collected; all other rows (non-keyframes) are
    discarded.  Malformed lines (those that do not split into exactly 2 tokens)
    are silently skipped.

    Args:
        video_path: Absolute or relative path to the video file.

    Returns:
        A sorted ``list[float]`` of keyframe PTS timestamps in seconds.

    Raises:
        RuntimeError: If ffprobe is not found on PATH (wraps FileNotFoundError
            with a clear message starting "ffprobe not found on PATH").
        RuntimeError: If ffprobe exits with a non-zero return code; the full
            stderr is included in the message.
    """

    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=key_frame,pts_time",
        "-of", "csv=p=0",
        video_path,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            "ffprobe not found on PATH — install FFmpeg (including ffprobe) "
            "and ensure it is available on PATH."
        ) from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"ffprobe failed while probing keyframes for: {video_path}\n{stderr}"
        )

    keyframe_times: list[float] = []
    for line in (proc.stdout or "").splitlines():
        tokens = line.strip().split(",")
        # Column order is key_frame, pts_time — exactly 2 tokens required.
        if len(tokens) != 2:
            continue  # skip malformed lines
        key_frame, pts_time = tokens
        if key_frame == "1":
            try:
                keyframe_times.append(float(pts_time))
            except ValueError:
                # pts_time is not a valid float — treat as malformed
                continue

    return sorted(keyframe_times)


def probe_video_stream_codec(video_path: str) -> str:
    """Return the codec name for the first video stream, e.g. ``"h264"``.

    This helper exists to determine whether an input file is already H.264 so
    that the initial two-phase render rollout can safely mix stream-copied H.264
    segments with bridge-encoded H.264 segments in the MP4 concat flow without
    introducing codec mismatches that would cause FFmpeg to error or produce
    corrupt output.

    Args:
        video_path: Absolute or relative path to the video file.

    Returns:
        The stripped codec name string reported by ffprobe for stream ``v:0``
        (e.g. ``"h264"``, ``"hevc"``, ``"vp9"``).

    Raises:
        RuntimeError: If ffprobe is not found on PATH; wraps FileNotFoundError
            with a clear message.
        RuntimeError: If ffprobe exits with a non-zero return code; includes
            ffprobe stderr in the message.
    """

    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            "ffprobe not found on PATH — install FFmpeg (including ffprobe) "
            "and ensure it is available on PATH."
        ) from e

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(
            f"ffprobe failed while probing video codec for: {video_path}\n{stderr}"
        )

    return (proc.stdout or "").strip()


def probe_video_fps(video_path: str) -> float | None:
    """Return the frame rate (fps) for the first video stream, or None on failure.

    Uses ffprobe's ``r_frame_rate`` field, which is the exact frame rate as a
    rational ``"num/den"`` string (e.g. ``"60/1"``, ``"30000/1001"``).

    Returns ``None`` rather than raising so callers can gracefully skip
    frame-quantization when the FPS cannot be determined.

    Args:
        video_path: Absolute or relative path to the video file.

    Returns:
        Frame rate in frames per second as a float, or None if unavailable.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        return None

    if proc.returncode != 0:
        return None

    raw = (proc.stdout or "").strip()
    if not raw:
        return None

    # r_frame_rate is returned as a rational "num/den" string (e.g. "60/1").
    if "/" in raw:
        try:
            num_s, den_s = raw.split("/", 1)
            den_f = float(den_s)
            if den_f == 0:
                return None
            return float(num_s) / den_f
        except (ValueError, ZeroDivisionError):
            return None

    try:
        return float(raw)
    except ValueError:
        return None


def _parse_frame_rate(raw: str) -> float | None:
    """Parse an ffprobe rational frame rate string (e.g. ``"60/1"``) to float."""
    raw = raw.strip()
    if not raw:
        return None
    if "/" in raw:
        try:
            num_s, den_s = raw.split("/", 1)
            den_f = float(den_s)
            if den_f == 0:
                return None
            return float(num_s) / den_f
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(raw)
    except ValueError:
        return None


def probe_is_vfr(video_path: str) -> bool:
    """Detect whether the first video stream is variable frame rate (VFR).

    Compares ``r_frame_rate`` (container-declared base rate) with
    ``avg_frame_rate`` (actual average over all frames).  A significant
    discrepancy (> 1 %) between the two is a strong indicator of VFR
    content — common with webcam, OBS, and Zoom recordings.

    Returns ``True`` if VFR is detected, ``False`` otherwise (including
    when the probe fails or data is unavailable).

    Args:
        video_path: Absolute or relative path to the video file.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,avg_frame_rate",
        "-of", "default=noprint_wrappers=1",
        video_path,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        return False

    if proc.returncode != 0:
        return False

    r_fps: float | None = None
    avg_fps: float | None = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("r_frame_rate="):
            r_fps = _parse_frame_rate(line.split("=", 1)[1])
        elif line.startswith("avg_frame_rate="):
            avg_fps = _parse_frame_rate(line.split("=", 1)[1])

    if r_fps is None or avg_fps is None or r_fps <= 0 or avg_fps <= 0:
        return False

    # If avg and declared rates differ by more than 1 %, treat as VFR.
    return abs(r_fps - avg_fps) / max(r_fps, avg_fps) > 0.01


def probe_audio_sample_rate(path: str) -> int | None:
    """Return the first audio stream sample rate in Hz, or ``None`` on failure.

    Uses ``ffmpeg.probe`` so callers can cheaply inspect source audio parameters
    without invoking a separate subprocess wrapper. This is intentionally lenient:
    probe failures, missing audio streams, and invalid sample-rate values all
    return ``None`` so higher-level logic can fall back to safe defaults.
    """
    try:
        probe = ffmpeg.probe(path)
    except Exception:
        return None

    for stream in probe.get("streams", []):
        if stream.get("codec_type") != "audio":
            continue
        try:
            return int(stream.get("sample_rate"))
        except (TypeError, ValueError):
            return None

    return None
