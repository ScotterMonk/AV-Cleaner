"""Video-phase helper strategies for two-phase rendering.

Extracted from [`render_project_two_phase()`](io_/video_renderer_twophase.py:674)
support code to keep [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py)
under the app-standard module size limit.
"""

import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from utils.logger import get_logger
from io_.video_renderer import merge_close_segments

logger = get_logger(__name__)


# Known video encoder key -> canonical FFmpeg flag
_VIDEO_KEY_MAP = {
    "vcodec": "-c:v",
    "preset": "-preset",
    "crf": "-crf",
    "cq": "-cq",
    "rc": "-rc",
}

# Audio-only keys — must never appear in a video-phase command
_AUDIO_ONLY_KEYS = {"acodec", "audio_bitrate"}


def _build_video_enc_flags(enc_opts: dict) -> list[str]:
    """Build FFmpeg CLI flags from *enc_opts* for video-only encoding.

    Known video keys are mapped to their canonical FFmpeg flags.
    Audio-only keys (``acodec``, ``audio_bitrate``) are excluded.
    Unrecognised keys are forwarded verbatim as ``-<key> <value>``.

    Args:
        enc_opts: Encoder options dict (typically from ``QUALITY_PRESETS``).

    Returns:
        Flat list of CLI flag/value pairs for insertion into an FFmpeg command.
    """
    flags = []
    for key, value in enc_opts.items():
        if key in _AUDIO_ONLY_KEYS:
            # Exclude audio-only options — video phase always uses -an
            continue
        canonical_flag = _VIDEO_KEY_MAP.get(key)
        if canonical_flag:
            flags.extend([canonical_flag, str(value)])
        else:
            # Unrecognised key: forward as -<key> <value> (assumed video-related)
            flags.extend([f"-{key}", str(value)])
    return flags


def classify_segments_by_keyframe(
    keep_segments: list,
    keyframes: list,
    snap_tolerance_s: float = 0.1,
) -> list[dict]:
    """Classify each keep segment as 'copy' or 'bridge' based on keyframe alignment.

    For each ``(start, end)`` in *keep_segments*:

    * **empty keyframes**: ``type='bridge'``, ``kf_start=0.0``
    * **nearest keyframe within tolerance**: ``type='copy'``, ``kf_start=nearest_kf``
    * **otherwise**: ``type='bridge'``,
      ``kf_start=max(kf for kf in keyframes if kf <= start, default=0.0)``

    This classification drives Phase 2 rendering decisions: copy-eligible segments
    are stream-copied directly (fast, lossless); bridge segments require a re-encode
    from the nearest preceding keyframe to the cut point.

    Args:
        keep_segments:    Sorted list of ``(start_s, end_s)`` float tuples defining
                          regions to retain (seconds).
        keyframes:        Sorted list of keyframe timestamps in seconds, as returned
                          by :func:`io_.media_probe.probe_video_keyframes`.
        snap_tolerance_s: Maximum distance (seconds) between a segment start and a
                          keyframe for the segment to be classified as ``'copy'``.
                          Defaults to 0.1 s (one typical GOP frame interval).

    Returns:
        List of dicts, one per input segment, with keys:
        ``'type'`` (``'copy'`` | ``'bridge'``), ``'start'``, ``'end'``, ``'kf_start'``.
    """
    result = []
    copy_count = 0
    bridge_count = 0

    for start, end in keep_segments:
        if not keyframes:
            # No keyframe data available — must re-encode from the beginning.
            seg_type = "bridge"
            kf_start = 0.0
        else:
            # Only consider keyframes AT OR BEFORE the segment start.
            # Using a keyframe AFTER start as kf_start would cause the copy to
            # seek past the segment's logical start, dropping leading frames and
            # accumulating per-segment A/V de-sync drift.
            kf_before = max(
                (kf for kf in keyframes if kf <= start),
                default=None,
            )
            if kf_before is not None and (start - kf_before) <= snap_tolerance_s:
                # Segment starts within tolerance of the nearest preceding keyframe.
                # render_video_segment_copy will output-side trim to exact [start, end).
                seg_type = "copy"
                kf_start = kf_before
            else:
                # Too far from any keyframe — re-encode from the nearest preceding kf.
                seg_type = "bridge"
                kf_start = kf_before if kf_before is not None else 0.0

        if seg_type == "copy":
            copy_count += 1
        else:
            bridge_count += 1

        result.append({"type": seg_type, "start": start, "end": end, "kf_start": kf_start})

    logger.info(
        "classify_segments_by_keyframe: total=%d copy=%d bridge=%d",
        len(result),
        copy_count,
        bridge_count,
    )

    return result


def render_video_segment_copy(
    input_path: str,
    kf_start: float,
    start: float,
    end: float,
    out_path: str,
) -> None:
    """Stream-copy a video-only segment using a keyframe-aligned start point.

    Invokes FFmpeg with ``-ss`` placed **before** ``-i`` (input seek, faster)
    and ``-c:v copy`` so no re-encode occurs.  Audio is suppressed with ``-an``
    because video-phase segments are later muxed with the pre-rendered audio
    phase output.

    When ``kf_start`` precedes ``start`` (keyframe not exactly at the segment
    boundary), an output-side ``-ss`` skip and ``-t`` duration cap are added so
    the output segment duration is **exactly** ``end - start``, matching the
    audio phase.  Without this correction, each "copy" segment would be up to
    ``snap_tolerance_s`` seconds longer than the audio segment, causing gradual
    A/V de-sync that compounds across all cut points.

    Args:
        input_path: Path to the source video file.
        kf_start:   Keyframe-aligned seek point (seconds).  Must be <= start.
        start:      Logical segment start timestamp (seconds).
        end:        Logical segment end timestamp (seconds).
        out_path:   Destination path for the video-only segment clip.

    Returns:
        None.

    Raises:
        RuntimeError: When FFmpeg exits with a non-zero return code; full
                      stderr is included in the exception message.
    """
    # extra: pre-segment frames between kf_start and logical start (always >= 0
    # because classify_segments_by_keyframe now guarantees kf_start <= start).
    extra = start - kf_start
    duration = end - start  # exact segment duration — must match audio phase

    logger.debug(
        "render_video_segment_copy: kf_start=%.3f start=%.3f end=%.3f "
        "extra=%.3f duration=%.3f out=%s",
        kf_start,
        start,
        end,
        extra,
        duration,
        out_path,
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(kf_start),   # input seek BEFORE -i (fast, keyframe-accurate)
        "-i", input_path,
        "-c:v", "copy",         # stream-copy video — no re-encode
        "-an",                  # suppress audio; muxed separately from audio phase
        "-avoid_negative_ts", "1",
    ]

    if extra > 1e-3:
        # Output-side skip: discard frames between kf_start and the logical
        # segment start.  Ensures output duration = (end - start), matching the
        # audio phase's atrim output and preventing cumulative A/V drift.
        cmd += ["-ss", str(extra)]

    cmd += ["-t", str(duration), out_path]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"render_video_segment_copy failed for {input_path!r} "
            f"(kf_start={kf_start}, start={start}, end={end})\nstderr:\n{result.stderr}"
        )


def render_video_segment_bridge(
    input_path: str,
    kf_before: float,
    start: float,
    end: float,
    out_path: str,
    enc_opts: dict,
) -> None:
    """Re-encode a bridge video segment from a preceding keyframe.

    When a segment start does not align with a keyframe, stream-copy is
    inaccurate.  This function seeks to the keyframe *before* the desired
    start (``kf_before``), then uses a ``trim`` video filter to extract
    exactly ``[start, end)`` relative to that seek point, followed by
    ``setpts=PTS-STARTPTS`` to reset timestamps to 0.

    Trim offsets (relative to the seek point):
    - ``trim_start = start - kf_before``
    - ``trim_end   = end   - kf_before``

    Audio is suppressed (``-an``) because video-phase segments are muxed
    with the pre-rendered audio-phase output downstream.

    NOTE: CPU decode is used intentionally here (no -hwaccel cuda), even
    when the encoder is NVENC.  Bridge segments are short (sub-second to a
    few seconds), so per-process CUDA context initialisation overhead
    dominates any decode speedup.  Additionally, the trim/setpts filter is
    CPU-side, which would force a GPU→CPU download then CPU→GPU re-upload
    (two PCIe round-trips per frame) — slower than CPU decode + one upload.

    Args:
        input_path: Path to the source video file.
        kf_before:  Keyframe timestamp (seconds) that precedes *start*;
                    used as the FFmpeg input seek point (``-ss`` before ``-i``).
        start:      Logical segment start timestamp (seconds).
        end:        Logical segment end timestamp (seconds).
        out_path:   Destination path for the re-encoded video-only segment.
        enc_opts:   Encoder options dict mapping option name -> value.
                    Video-related keys are forwarded as FFmpeg flags;
                    audio-only keys (``acodec``, ``audio_bitrate``) are
                    always excluded.

    Returns:
        None.

    Raises:
        RuntimeError: When FFmpeg exits with a non-zero return code; full
                      stderr is included in the exception message.
    """
    trim_start = start - kf_before
    trim_end = end - kf_before

    logger.debug(
        "render_video_segment_bridge: kf_before=%.3f start=%.3f end=%.3f "
        "trim_start=%.3f trim_end=%.3f encoder=%s out=%s",
        kf_before,
        start,
        end,
        trim_start,
        trim_end,
        enc_opts.get("vcodec", "unknown"),
        out_path,
    )

    vf_filter = f"trim=start={trim_start}:end={trim_end},setpts=PTS-STARTPTS"
    enc_flags = _build_video_enc_flags(enc_opts)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(kf_before),   # input seek BEFORE -i (fast, keyframe-accurate)
        "-i", input_path,
        "-vf", vf_filter,        # trim to [trim_start, trim_end) + PTS reset
        "-an",                   # suppress audio; muxed separately from audio phase
        *enc_flags,
        out_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"render_video_segment_bridge failed for {input_path!r} "
            f"(kf_before={kf_before}, start={start}, end={end})\n"
            f"stderr:\n{result.stderr}"
        )


def gpu_workers_from_pct(gpu_limit_pct: int) -> int:
    """Map gpu_limit_pct (100/60/20) to a maximum NVENC worker count."""
    mapping = {100: 5, 60: 3, 20: 1}
    return mapping.get(int(gpu_limit_pct), 5)


def render_video_batched_gpu(
    input_path: str,
    filters: list,
    keep_segments: list,
    out_path: str,
    enc_opts: dict,
    config: dict | None = None,
    num_batches: int = 3,
) -> None:
    """Render video in parallel batches, then concat-copy the batch outputs."""
    import ffmpeg
    from io_.video_renderer import _build_filter_chain, build_input_kwargs, probe_ffmpeg_capabilities
    from io_.video_renderer_progress import run_with_progress

    t_start = time.monotonic()
    out_dir = Path(out_path).parent
    tmp_paths: list[str] = []
    concat_list_path: str | None = None

    # 1. cfg = config or {}
    cfg = config or {}
    # 2. merged = merge_close_segments(keep_segments)
    merged = merge_close_segments(keep_segments)
    # 3. n = min(num_batches, len(merged))
    n = min(num_batches, len(merged))
    # 4. batches: split merged into n contiguous chunks (preserve chronological order).
    # CRITICAL: round-robin (merged[i::n]) scrambles segment order across batches,
    # producing video that is chronologically misaligned with the audio phase.
    # Contiguous chunking keeps each batch's segments in order; the final concat
    # joins batch-0..batch-(n-1) in the correct temporal sequence.
    chunk_size = max(1, (len(merged) + n - 1) // n)  # ceiling division
    batches = [merged[i * chunk_size:(i + 1) * chunk_size] for i in range(n)]
    batches = [b for b in batches if b]  # drop empty tail batches if len(merged) < n
    # 5. is_nvenc = any("nvenc" in str(v).lower() for v in (enc_opts or {}).values())
    is_nvenc = any("nvenc" in str(v).lower() for v in (enc_opts or {}).values())
    # 6. _nvenc_cap = gpu_workers_from_pct(int(cfg.get("gpu_limit_pct", 100)))
    _nvenc_cap = gpu_workers_from_pct(int(cfg.get("gpu_limit_pct", 100)))
    # 7. max_workers = _nvenc_cap if is_nvenc else 8
    max_workers = _nvenc_cap if is_nvenc else 8
    caps = probe_ffmpeg_capabilities()

    cut_fade_s = float(cfg.get("cut_fade_ms", 0)) / 1000.0
    logger.info(
        "[DETAIL] batched_gpu: %d merged segments -> %d batch(es), max_workers=%d (%s)",
        len(merged), len(batches), max_workers, "nvenc" if is_nvenc else "cpu",
    )

    try:
        # 8. Allocate one temp .mp4 per batch.
        for idx in range(len(batches)):
            fd, tmp_path = tempfile.mkstemp(prefix=f".batch{idx:02d}.", suffix=".mp4", dir=str(out_dir))
            os.close(fd)
            tmp_paths.append(tmp_path)

        def _render_batch(idx: int, batch_segments: list, tmp_path: str) -> None:
            logger.info("[DETAIL] batched_gpu batch %d of %d start", idx + 1, len(batches))
            use_cuda_decode = bool(cfg.get("cuda_decode_enabled"))
            input_kwargs = build_input_kwargs(cfg, caps) if use_cuda_decode else {}
            v, a = _build_filter_chain(
                input_path,
                filters,
                batch_segments,
                input_kwargs,
                cut_fade_s=cut_fade_s,
            )
            run_with_progress(ffmpeg.output(v, a, tmp_path, **(enc_opts or {})), overwrite_output=True)
            logger.info("[DETAIL] batched_gpu batch %d of %d complete", idx + 1, len(batches))

        # 9. Use ThreadPoolExecutor(max_workers=max_workers) to submit encodes: use _build_filter_chain, run_with_progress for each batch.
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_render_batch, idx, batch_segments, tmp_paths[idx])
                for idx, batch_segments in enumerate(batches)
            ]
            # 10. Collect futures, re-raise exceptions.
            for future in as_completed(futures):
                future.result()

        # 11. Write concat list .txt with file and duration lines.
        fd, concat_list_path = tempfile.mkstemp(prefix="concat_batch_", suffix=".txt", dir=str(out_dir))
        os.close(fd)
        with open(concat_list_path, "w", encoding="utf-8") as fh:
            for tmp_path, batch_segments in zip(tmp_paths, batches):
                fh.write(f"file '{str(Path(tmp_path).resolve()).replace('\\', '/')}'\n")
                fh.write(f"duration {sum(end - start for start, end in batch_segments):.6f}\n")

        # 12. Run ffmpeg concat copy to out_path.
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", out_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise RuntimeError(f"render_video_batched_gpu concat failed for {out_path!r}\nstderr:\n{result.stderr}")
    finally:
        # 13. finally: cleanup temps.
        for tmp_path in tmp_paths:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        if concat_list_path is not None:
            try:
                os.remove(concat_list_path)
            except OSError:
                pass

    # 14. Log elapsed time.
    logger.info("render_video_batched_gpu: done in %.2fs out=%s", time.monotonic() - t_start, os.path.basename(out_path))


def _render_video_smart_copy_impl(
    input_path: str,
    keep_segments: list,
    keyframes: list,
    out_path: str,
    enc_opts: dict,
    snap_tolerance_s: float = 0.1,
    label: str = "",
    gpu_limit_pct: int = 100,
    copy_fn: Callable[[str, float, float, float, str], None] = render_video_segment_copy,
    bridge_fn: Callable[[str, float, float, float, str, dict], None] = render_video_segment_bridge,
    mkstemp_fn: Callable[..., tuple[int, str]] = tempfile.mkstemp,
    subprocess_run_fn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Render smart-copy video: classify segments, render in parallel, concat."""
    t_start = time.monotonic()
    out_dir = Path(out_path).parent

    # Step 1: merge micro-gap pairs before classification.
    keep_segments = merge_close_segments(keep_segments)

    # Step 2: classify each segment as copy or bridge.
    classified = classify_segments_by_keyframe(keep_segments, keyframes, snap_tolerance_s)

    # Step 2b: drop zero-duration segments — these occur when a "copy" segment's
    # nearest keyframe lands exactly on the segment end (kf_start == end).
    # FFmpeg rejects "-to value smaller than -ss" in that case.
    valid = []
    for seg in classified:
        if seg["kf_start"] >= seg["end"]:
            logger.warning(
                "render_video_smart_copy: skipping zero-duration segment "
                "kf_start=%.3f end=%.3f type=%s — would crash FFmpeg",
                seg["kf_start"],
                seg["end"],
                seg["type"],
            )
        else:
            valid.append(seg)
    classified = valid

    # Step 3: log stats (classify_segments_by_keyframe also logs; repeat here for context).
    copy_count = sum(1 for s in classified if s["type"] == "copy")
    bridge_count = len(classified) - copy_count
    logger.info(
        "render_video_smart_copy: total=%d copy=%d bridge=%d input=%s",
        len(classified),
        copy_count,
        bridge_count,
        os.path.basename(input_path),
    )

    tmp_paths: list[str] = []
    concat_list_path: str | None = None

    try:
        # Step 4: create one temp segment file per classified segment; close fds.
        for _ in classified:
            fd, tmp_path = mkstemp_fn(suffix=".mp4", dir=str(out_dir))
            os.close(fd)
            tmp_paths.append(tmp_path)

        # Step 5: render segments in parallel.
        # NVENC (GPU) encode sessions are a limited hardware resource: consumer
        # NVIDIA GPUs cap concurrent sessions at 3–5 (RTX 3080 supports 5).
        # With two tracks (host + guest) each spawning workers, we can exceed
        # that limit and get "incompatible client key" failures mid-encode.
        # CPU encoders have no such hard limit, so they can safely use 8.
        # gpu_limit_pct controls the NVENC worker cap: 100%→5, 60%→3, 20%→1.
        is_nvenc = any("nvenc" in str(v).lower() for v in (enc_opts or {}).values())
        _nvenc_cap = gpu_workers_from_pct(gpu_limit_pct)
        _worker_cap = _nvenc_cap if is_nvenc else 8
        max_workers = min(len(classified), _worker_cap)
        logger.info(
            "render_video_smart_copy: %d segments -> max_workers=%d (%s encoder, gpu_limit_pct=%d%%)",
            len(classified), max_workers, "nvenc" if is_nvenc else "cpu", gpu_limit_pct,
        )

        # Inform the user what's happening during the silent parallel-encode phase.
        pfx = f"{label} " if label else ""
        label_lower = label.lower() if label else "video"
        logger.info(
            "[DETAIL] %svideo render: encoding %d segments in parallel (%s encoder)"
            " — this part may take awhile...",
            pfx, len(classified), "nvenc" if is_nvenc else "cpu",
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for seg, tmp_path in zip(classified, tmp_paths):
                if seg["type"] == "copy":
                    fut = executor.submit(
                        copy_fn,
                        input_path,
                        seg["kf_start"],
                        seg["start"],   # logical start — ensures output duration = end - start
                        seg["end"],
                        tmp_path,
                    )
                else:
                    fut = executor.submit(
                        bridge_fn,
                        input_path,
                        seg["kf_start"],
                        seg["start"],
                        seg["end"],
                        tmp_path,
                        enc_opts,
                    )
                futures.append(fut)

            # Step 6: surface any worker failure immediately; log per-segment progress.
            total = len(futures)
            completed = 0
            for fut in as_completed(futures):
                fut.result()  # re-raise any exception from the worker
                completed += 1
                logger.info(
                    "%d of %d %s segments rendered.",
                    completed, total, label_lower,
                )

        # Step 7: write concat list file — one absolute path per segment in order.
        # Include explicit `duration` directives so the concat demuxer uses the
        # exact expected segment duration instead of container metadata.  Without
        # this, stream-copied segments may report slightly different container
        # durations (B-frame DTS/PTS mismatch, MP4 mdat rounding) causing the
        # concat demuxer to place subsequent segments at wrong timestamps.  Over
        # many segments, these tiny errors accumulate into visible A/V de-sync
        # against the audio phase (which uses the concat filter with precise atrim).
        fd, concat_list_path = mkstemp_fn(suffix=".txt", dir=str(out_dir))
        os.close(fd)
        with open(concat_list_path, "w", encoding="utf-8") as fh:
            for tmp_path, seg in zip(tmp_paths, classified):
                abs_path = str(Path(tmp_path).resolve())
                seg_duration = seg["end"] - seg["start"]
                fh.write(f"file '{abs_path}'\n")
                fh.write(f"duration {seg_duration:.6f}\n")

        # Step 8: concatenate all segments via FFmpeg concat demuxer (lossless).
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            out_path,
        ]
        result = subprocess_run_fn(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"render_video_smart_copy concat failed for {out_path!r}\n"
                f"stderr:\n{result.stderr}"
            )

    finally:
        # Step 9: clean up all temp segment files regardless of success or failure.
        for tmp_path in tmp_paths:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        if concat_list_path is not None:
            try:
                os.remove(concat_list_path)
            except OSError:
                pass

    elapsed = time.monotonic() - t_start
    logger.info(
        "render_video_smart_copy: done in %.2fs out=%s",
        elapsed,
        os.path.basename(out_path),
    )


def render_video_smart_copy(
    input_path: str,
    keep_segments: list,
    keyframes: list,
    out_path: str,
    enc_opts: dict,
    snap_tolerance_s: float = 0.1,
    label: str = "",
    gpu_limit_pct: int = 100,
) -> None:
    """Render smart-copy video: classify segments by keyframe, render in parallel, concat."""
    _render_video_smart_copy_impl(
        input_path,
        keep_segments,
        keyframes,
        out_path,
        enc_opts,
        snap_tolerance_s=snap_tolerance_s,
        label=label,
        gpu_limit_pct=gpu_limit_pct,
    )


def quantize_segments_to_frames(
    keep_segments: list,
    fps: float,
) -> list:
    """Round each segment boundary to the nearest video frame boundary.

    Video is frame-quantized (each segment's duration snaps to a multiple of
    1/fps), while audio ``atrim`` is sample-precise.  When audio and video
    segments are concatenated independently in the two-phase render, each
    segment can drift by up to ½ frame (e.g. ±8.3 ms at 60 fps), compounding
    into seconds of A/V de-sync over hundreds of cuts.

    Rounding BOTH audio and video boundaries to the same frame grid before
    rendering ensures both phases operate on identical timestamps, eliminating
    cumulative drift.  The rounding adjustment is at most 0.5/fps per boundary
    — imperceptible in practice.

    Args:
        keep_segments: Sorted list of ``(start_s, end_s)`` float tuples.
        fps:           Video frame rate in frames per second (e.g. 60.0).

    Returns:
        New list of ``(start_s, end_s)`` tuples with boundaries snapped to the
        nearest frame boundary.  Input is never mutated.
    """
    if not fps or fps <= 0:
        return list(keep_segments)

    result = []
    for start, end in keep_segments:
        q_start = round(start * fps) / fps
        q_end = round(end * fps) / fps
        # Guard against zero-duration segments after rounding (ensure ≥ 1 frame).
        if q_end <= q_start:
            q_end = q_start + 1.0 / fps
        result.append((q_start, q_end))
    return result
