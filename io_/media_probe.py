"""io_/media_probe.py

Media probing helpers.

This module is intentionally non-UI so it can be reused by both CLI + GUI.
"""

from __future__ import annotations

import os
import subprocess


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

