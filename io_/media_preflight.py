"""io_/media_preflight.py

Media preflight utilities.

Currently includes duration alignment for host/guest videos by padding the shorter
to match the longer.
"""

from __future__ import annotations

from dataclasses import dataclass

import ffmpeg

from io_.media_probe import get_video_duration_seconds
from io_.video_renderer import run_with_progress
from utils.logger import get_logger
from utils.path_helpers import add_suffix_to_filename, make_processed_output_path


logger = get_logger(__name__)


@dataclass(frozen=True)
class _NormalizePlan:
    input_path: str
    output_path: str
    input_duration_s: float
    target_duration_s: float
    pad_seconds: float


def _safe_processed_output_path(input_path: str) -> str:
    """Return a stable processed output path, never equal to the input path.

    Task 04 will refine `make_processed_output_path()` to avoid `_processed_processed`.
    Until then, this helper prevents accidental overwrite if we get a pathological
    `input_path` that already equals the processed path.
    """

    outp = make_processed_output_path(input_path)
    if outp != input_path:
        return outp

    # Pathological case (e.g., input already ends in `_processed.mp4`).
    # Do NOT overwrite the input; fall back to a different suffix.
    logger.warning(
        "Processed output path equals input; using a fallback suffix to avoid overwriting: %s",
        input_path,
    )
    return add_suffix_to_filename(input_path, "_normalized", output_ext=".mp4")


def _video_pad_to_duration(plan: _NormalizePlan) -> None:
    """Pad video+audio (freeze last frame + append silence) to reach target duration."""

    if plan.target_duration_s <= 0:
        raise ValueError(f"target_duration_s must be > 0 (got {plan.target_duration_s})")
    if plan.pad_seconds < 0:
        raise ValueError(f"pad_seconds must be >= 0 (got {plan.pad_seconds})")

    inp = ffmpeg.input(plan.input_path)
    v = inp.video
    a = inp.audio

    # Video: freeze last frame for pad duration, then force exact container duration.
    if plan.pad_seconds > 0:
        v = v.filter("tpad", stop_mode="clone", stop_duration=plan.pad_seconds)
    v = v.filter("trim", duration=plan.target_duration_s).setpts("PTS-STARTPTS")

    # Audio: append silence for pad duration, then force exact container duration.
    if plan.pad_seconds > 0:
        a = a.filter("apad", pad_dur=plan.pad_seconds)
    a = a.filter_("atrim", duration=plan.target_duration_s).filter_("asetpts", "PTS-STARTPTS")

    # Preflight is config-agnostic; use safe baseline encoding settings.
    enc_opts = {
        "vcodec": "libx264",
        "preset": "fast",
        "crf": 23,
        "acodec": "aac",
        "audio_bitrate": "192k",
    }

    stream = ffmpeg.output(v, a, plan.output_path, **enc_opts)
    run_with_progress(stream, overwrite_output=True)


def normalize_video_lengths(host_path: str, guest_path: str) -> tuple[str, str]:
    """Normalize host+guest video container durations.

    - If durations are equal: returns inputs unchanged.
    - Otherwise: pads the shorter to match the longer (freeze last frame + append silence)
      and returns stable `*_processed.mp4` outputs (without overwriting inputs).

    Notes:
    - When a mismatch is detected, we write *both* processed outputs so downstream
      processing always operates on an aligned pair.
    """

    host_d = get_video_duration_seconds(host_path)
    guest_d = get_video_duration_seconds(guest_path)

    if host_d == guest_d:
        return host_path, guest_path

    target = max(host_d, guest_d)

    out_host = _safe_processed_output_path(host_path)
    out_guest = _safe_processed_output_path(guest_path)

    plans = [
        _NormalizePlan(
            input_path=host_path,
            output_path=out_host,
            input_duration_s=host_d,
            target_duration_s=target,
            pad_seconds=max(0.0, target - host_d),
        ),
        _NormalizePlan(
            input_path=guest_path,
            output_path=out_guest,
            input_duration_s=guest_d,
            target_duration_s=target,
            pad_seconds=max(0.0, target - guest_d),
        ),
    ]

    logger.info(
        "Duration mismatch detected; normalizing lengths: host=%.3fs guest=%.3fs target=%.3fs",
        host_d,
        guest_d,
        target,
    )

    for p in plans:
        logger.info(
            "Normalizing duration: in=%s out=%s pad=%.3fs target=%.3fs",
            p.input_path,
            p.output_path,
            p.pad_seconds,
            p.target_duration_s,
        )
        _video_pad_to_duration(p)

    return out_host, out_guest

