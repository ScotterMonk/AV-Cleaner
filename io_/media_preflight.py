"""io_/media_preflight.py

Media preflight utilities.

Currently includes duration alignment for host/guest videos by padding the shorter
to match the longer.
"""

from __future__ import annotations

from dataclasses import dataclass

import time

import ffmpeg

from io_.media_probe import get_video_duration_seconds
from io_.video_renderer import run_with_progress
from utils.logger import get_logger
from utils.path_helpers import add_suffix_to_filename


logger = get_logger(__name__)


@dataclass(frozen=True)
class _NormalizePlan:
    input_path: str
    output_path: str
    input_duration_s: float
    target_duration_s: float
    pad_seconds: float


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
      and returns stable `*_preflight.mp4` intermediates (without overwriting inputs).

    Notes:
    - When a mismatch is detected, we write *both* preflight outputs so downstream
      processing always operates on an aligned pair.
    - Preflight outputs use `_preflight` suffix to reserve `_processed` for final outputs.
    """

    host_d = get_video_duration_seconds(host_path)
    guest_d = get_video_duration_seconds(guest_path)

    # Treat sub-frame probe jitter as aligned so tiny FFmpeg/container rounding differences
    # do not trigger an unnecessary preflight re-encode.
    if abs(host_d - guest_d) < 0.01:
        return host_path, guest_path

    target = max(host_d, guest_d)

    which_padded = "guest" if guest_d < host_d else "host"
    logger.info(
        f"[SUBFUNCTION START] Pad end of shorter video ({which_padded}) to fit longer video length"
    )

    out_host = add_suffix_to_filename(host_path, "_preflight", output_ext=".mp4")
    out_guest = add_suffix_to_filename(guest_path, "_preflight", output_ext=".mp4")

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

    preflight_start = time.time()
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

    preflight_duration = time.time() - preflight_start
    from utils.logger import format_duration, format_time_cut

    logger.info(
        f"[PREFLIGHT COMPLETE] Padded shorter video ({which_padded}) to fit longer video - Preflight pair written to {format_time_cut(target)} duration - Completed in {format_duration(preflight_duration)}"
    )

    logger.info(
        f"[SUBFUNCTION COMPLETE] Pad end of shorter video ({which_padded}) to fit longer video length"
    )

    return out_host, out_guest

