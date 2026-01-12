from __future__ import annotations

from dataclasses import dataclass

import tkinter as tk

import ffmpeg


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
    """Return video duration in seconds using ffprobe via ffmpeg-python."""

    probe = ffmpeg.probe(video_path)
    duration_str = probe.get("format", {}).get("duration")
    if not duration_str:
        return 0.0
    try:
        return float(duration_str)
    except (TypeError, ValueError):
        return 0.0

