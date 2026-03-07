from __future__ import annotations

from dataclasses import dataclass

import tkinter as tk

from io_.media_probe import get_video_duration_seconds as _get_video_duration_seconds


@dataclass
class FileRowState:
    path: str | None
    file_var: tk.StringVar
    size_var: tk.StringVar
    length_var: tk.StringVar


def format_bytes(num_bytes: int) -> str:
    """Format bytes as a compact human-readable string."""

    if num_bytes < 0:
        return ""

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def get_video_duration_seconds(video_path: str) -> float:
    # Modified by gpt-5.2 | 2026-01-13_01
    """Return video duration in seconds using ffprobe via ffmpeg-python."""

    # Delegate to the shared, non-UI duration helper so CLI + GUI stay consistent.
    # Keep the GUI API stable (callers expect this function name) and preserve
    # the prior behavior of returning 0.0 on errors.
    try:
        return float(_get_video_duration_seconds(video_path))
    except Exception:
        return 0.0

