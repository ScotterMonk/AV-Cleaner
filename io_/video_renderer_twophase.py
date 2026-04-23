# io_/video_renderer_twophase.py
"""Two-phase render strategy for AV-cleaner.

Phase 1 (audio) renders a normalised/filtered audio-only stream to a
temporary AAC file.  Phase 2 (video) re-muxes the original video stream
with that pre-rendered audio, avoiding a full re-encode of video on the
common path where only audio needs processing.

This module begins with the audio-phase helper.  Video-phase and mux
helpers will be added in subsequent tasks (Phase 1 Task 04+).

Design rationale
----------------
The two-phase approach lets us apply expensive audio transformations
(normalisation, limiting, silence removal) once and then reuse the
result when iterating on video-only parameters, cutting total processing
time by 40–70 % on typical podcast files.
"""

import math
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ffmpeg

from io_.media_probe import (
    get_video_duration_seconds,
    probe_audio_sample_rate,
    probe_is_vfr,
    probe_video_fps,
    probe_video_keyframes,
    probe_video_stream_codec,
)
from io_ import video_renderer_strategies
from io_.video_renderer import (
    _build_filter_chain,
    _fmt_elapsed,
    _render_with_safe_overwrite,
    build_input_kwargs,
    cpu_threads_from_config,
    merge_close_segments,
)
from io_.video_renderer_progress import run_with_progress
from utils.logger import get_logger

logger = get_logger(__name__)


def _afftdn_delay_s(sample_rate: int | float) -> float:
    """Return the `afftdn` warm-up delay in seconds for the given sample rate.

    FFmpeg's frequency-domain denoiser buffers one 4096-sample analysis window
    before steady-state output begins.  Convert that fixed sample delay to
    seconds and round up to 4 decimals so downstream trim math is conservative.
    """
    return math.ceil((4096.0 / float(sample_rate)) * 10000.0) / 10000.0


def render_audio_phase(
    input_path: str,
    filters: list,
    keep_segments: list,
    out_path: str,
    audio_opts: dict,
) -> None:
    """Render the audio-only phase of a two-phase encode.

    Merges close segments, applies audio filters, trims to keep_segments, and
    writes an audio-only file to *out_path*.  Uses asplit when multi-segment +
    filter path requires it.  Executes via run_with_progress.

    Args:
        input_path:    Source video or audio file.
        filters:       Audio filter objects with .filter_name / .params.
        keep_segments: (start_s, end_s) tuples to retain; empty = full audio.
        out_path:      Destination audio-only file.
        audio_opts:    Extra kwargs for ffmpeg.output() (acodec, audio_bitrate).
    """
    # Step 1: merge micro-gap pairs before constructing the filter graph.
    keep_segments = merge_close_segments(keep_segments)

    # Probe sample rate for afftdn delay compensation (fallback to 48000 Hz).
    _sample_rate = probe_audio_sample_rate(input_path) or 48000

    logger.debug(
        "render_audio_phase(%s): keep_segments=%d filters=%d out=%s sample_rate=%d",
        os.path.basename(input_path),
        len(keep_segments),
        len(filters or []),
        os.path.basename(out_path),
        _sample_rate,
    )

    # Step 2: build the base audio stream from the source file.
    inp = ffmpeg.input(input_path)
    a = inp.audio

    # Step 3: apply audio filters sequentially.
    # When afftdn is encountered, immediately trim its warm-up silence so that
    # silence does not propagate to the encoder and shift audio timing.
    for f in filters or []:
        a = a.filter(f.filter_name, **f.params)
        if f.filter_name == "afftdn":
            # afftdn introduces warm-up silence of approximately fft_length samples.
            # Trim that silence immediately so it does not propagate to the encoder.
            _delay_s = _afftdn_delay_s(_sample_rate)
            logger.debug(
                "render_audio_phase(%s): afftdn delay compensation: trimming %.4f s",
                os.path.basename(input_path),
                _delay_s,
            )
            a = a.filter_("atrim", start=_delay_s)
            a = a.filter_("asetpts", "PTS-STARTPTS")

    # Step 4: initialise audio_inputs before any conditional branch.
    audio_inputs = None

    if keep_segments:
        segs_a = []

        # Step 5: insert asplit when multiple segments + at least one filter
        # exist, to prevent ffmpeg-python from wiring one filtered output node
        # into multiple atrim chains (graph construction error).
        if len(keep_segments) > 1 and (filters or []):
            logger.debug(
                "render_audio_phase(%s): inserting asplit(outputs=%d) before per-segment atrim",
                os.path.basename(input_path),
                len(keep_segments),
            )
            # NOTE: do NOT call list() on the FilterNode; iterate via .stream(i) only.
            split_node = a.filter_multi_output("asplit", outputs=len(keep_segments))
            audio_inputs = [split_node.stream(i) for i in range(len(keep_segments))]

        for idx, (start, end) in enumerate(keep_segments):
            # Step 6: trim each segment and reset PTS to 0-relative.
            a_in = audio_inputs[idx] if audio_inputs is not None else a
            seg_a = (
                a_in.filter_("atrim", start=start, end=end)
                    .filter_("asetpts", "PTS-STARTPTS")
            )
            segs_a.append(seg_a)

        # Step 7: concatenate trimmed segments (audio-only; v=0 a=1).
        if len(segs_a) == 1:
            # Single segment: skip concat node — no multi-input needed.
            audio_out = segs_a[0]
        else:
            audio_out = ffmpeg.concat(*segs_a, v=0, a=1)

    else:
        # Step 8: no segments requested — pass the full audio through unchanged.
        audio_out = a

    # Step 9: build output stream; vn=None suppresses any video track.
    stream = ffmpeg.output(audio_out, out_path, vn=None, **audio_opts)

    # Step 10: execute with progress reporting.
    run_with_progress(stream, overwrite_output=True)


def render_video_single_pass(
    input_path: str,
    filters: list,
    keep_segments: list,
    out_path: str,
    enc_opts: dict,
    config: dict | None = None,
) -> None:
    """Single-pass re-encode: one FFmpeg process, all segments via concat filter graph."""
    cfg = config or {}
    cut_fade_s = float(cfg.get("cut_fade_ms", 0)) / 1000.0
    merged = merge_close_segments(keep_segments)
    # The filter graph runs CPU-side, so CUDA decode provides no practical benefit here.
    input_kwargs = {}
    v, a = _build_filter_chain(input_path, filters, merged, input_kwargs, cut_fade_s=cut_fade_s)
    logger.info("two-phase: single-pass render with %d segments", len(merged))
    run_with_progress(ffmpeg.output(v, a, out_path, **enc_opts), overwrite_output=True)


def classify_segments_by_keyframe(
    keep_segments: list,
    keyframes: list,
    snap_tolerance_s: float = 0.1,
) -> list[dict]:
    """Delegate to [`classify_segments_by_keyframe()`](io_/video_renderer_strategies.py:62)."""
    return video_renderer_strategies.classify_segments_by_keyframe(
        keep_segments,
        keyframes,
        snap_tolerance_s,
    )


def render_video_segment_copy(
    input_path: str,
    kf_start: float,
    start: float,
    end: float,
    out_path: str,
) -> None:
    """Delegate to [`render_video_segment_copy()`](io_/video_renderer_strategies.py:137)."""
    return video_renderer_strategies.render_video_segment_copy(
        input_path,
        kf_start,
        start,
        end,
        out_path,
    )


def render_video_segment_bridge(
    input_path: str,
    kf_before: float,
    start: float,
    end: float,
    out_path: str,
    enc_opts: dict,
) -> None:
    """Delegate to [`render_video_segment_bridge()`](io_/video_renderer_strategies.py:214)."""
    return video_renderer_strategies.render_video_segment_bridge(
        input_path,
        kf_before,
        start,
        end,
        out_path,
        enc_opts,
    )


def gpu_workers_from_pct(gpu_limit_pct: int) -> int:
    """Delegate to [`gpu_workers_from_pct()`](io_/video_renderer_strategies.py:301)."""
    return video_renderer_strategies.gpu_workers_from_pct(gpu_limit_pct)


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
    """Delegate to [`_render_video_smart_copy_impl()`](io_/video_renderer_strategies.py:316).

    The wrapper preserves existing monkeypatch points on
    [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py) so tests and
    callers that patch public symbols keep working after the split.
    """
    return video_renderer_strategies._render_video_smart_copy_impl(
        input_path,
        keep_segments,
        keyframes,
        out_path,
        enc_opts,
        snap_tolerance_s=snap_tolerance_s,
        label=label,
        gpu_limit_pct=gpu_limit_pct,
        copy_fn=render_video_segment_copy,
        bridge_fn=render_video_segment_bridge,
        mkstemp_fn=tempfile.mkstemp,
        subprocess_run_fn=subprocess.run,
    )


# Modified by gpt-5.4 | 2026-03-31
def quantize_segments_to_frames(
    keep_segments: list,
    fps: float | None,
) -> list:
    """Delegate to [`quantize_segments_to_frames()`](io_/video_renderer_strategies.py:524)."""
    if not fps:
        return keep_segments
    return video_renderer_strategies.quantize_segments_to_frames(keep_segments, fps)


def _shared_segment_count(keep_segments: list) -> int:
    """Return the shared segment count used for route-family selection."""
    return len(keep_segments) if keep_segments else 1


def _store_render_metadata(cfg: dict, metadata: dict) -> dict:
    """Persist lightweight render metadata for later logging or validation."""
    cfg["_two_phase_render_metadata"] = metadata
    return metadata


# Modified by gpt-5.4 | 2026-03-31
def render_project_two_phase(
    host_path: str,
    guest_path: str | None,
    manifest,
    out_host: str | None,
    out_guest: str | None,
    config: dict | None,
) -> dict:
    """Orchestrate two-phase (audio-first) rendering for host and guest tracks."""
    from io_.video_renderer import probe_ffmpeg_capabilities, select_enc_opts
    caps = probe_ffmpeg_capabilities()
    enc_opts = select_enc_opts(config, caps)
    cfg = config or {}
    use_cuda_decode = bool(cfg.get("cuda_decode_enabled"))
    input_kwargs = build_input_kwargs(config, caps) if use_cuda_decode else {}
    audio_opts = {k: enc_opts[k] for k in ("acodec", "audio_bitrate") if k in enc_opts}
    # Throttle per-process FFmpeg thread count to honour cpu_limit_pct.
    thread_count = cpu_threads_from_config(cfg)
    enc_opts["threads"] = thread_count
    audio_opts["threads"] = thread_count
    snap_tol = float(cfg.get("keyframe_snap_tolerance_s", 0.1))
    render_tasks: list[tuple[str, str, str, list]] = []
    if out_host:
        render_tasks.append(("Host", host_path, out_host, manifest.host_filters))
    if out_guest and guest_path is not None:
        render_tasks.append(("Guest", guest_path, out_guest, manifest.guest_filters))

    requested_strategy = cfg.get("video_phase_strategy", "auto")
    shared_segment_count = _shared_segment_count(manifest.keep_segments)
    source_codecs: dict[str, str] = {}
    shared_strategy = requested_strategy

    if requested_strategy == "auto":
        source_codecs = {
            label.lower(): probe_video_stream_codec(src_path)
            for label, src_path, _dst_path, _filters in render_tasks
        }
        if any(codec != "h264" for codec in source_codecs.values()):
            shared_strategy = "single_pass"
        elif shared_segment_count > 25:
            shared_strategy = "batched_gpu"
        else:
            # Removed 'smart_copy' from auto-selection path.
            shared_strategy = "single_pass"
        logger.info(
            "two-phase: shared auto strategy selected=%r (codecs=%r segments=%d tracks=%d)",
            shared_strategy,
            source_codecs,
            shared_segment_count,
            len(render_tasks),
        )

    render_metadata = _store_render_metadata(
        cfg,
        {
            "route_mode": "auto" if requested_strategy == "auto" else "manual",
            "strategy_family": shared_strategy,
            "requested_strategy": requested_strategy,
            "shared_segment_count": shared_segment_count,
            "source_codecs": dict(source_codecs),
            "tracks": {},
        },
    )

    def _render_track(src_path: str, filters: list, to_path: str, label: str = "") -> None:
        # Normalize empty keep_segments to full-duration span.
        segs = manifest.keep_segments or [(0.0, get_video_duration_seconds(src_path))]
        track_key = label.lower() if label else os.path.basename(src_path)
        source_codec = render_metadata["source_codecs"].get(track_key)
        if source_codec is None:
            source_codec = probe_video_stream_codec(src_path)
            render_metadata["source_codecs"][track_key] = source_codec
        strategy = shared_strategy
        if source_codec != "h264" and strategy not in ("single_pass", "batched_gpu"):
            logger.info(
                "two-phase: non-h264 codec=%r; overriding strategy to single_pass",
                source_codec,
            )
            strategy = "single_pass"
        render_metadata["tracks"][track_key] = {
            "source_codec": source_codec,
            "strategy_family": strategy,
            "output_path": to_path,
            "segment_count": len(segs),
        }

        # VFR diagnostic: log whether the source appears to be variable frame rate.
        # The vsync=passthrough enc_opt protects against VFR drift regardless, but
        # the log helps diagnose sync issues if they recur.
        pfx_vfr = f"{label} " if label else ""
        is_vfr = probe_is_vfr(src_path)
        if is_vfr:
            logger.warning(
                "%sSource %s appears to be VFR (variable frame rate); "
                "vsync=passthrough is active to preserve A/V sync.",
                pfx_vfr, os.path.basename(src_path),
            )
        else:
            logger.info(
                "[DETAIL] %sSource %s appears to be CFR (constant frame rate).",
                pfx_vfr, os.path.basename(src_path),
            )

        # Quantize segment boundaries to video frame boundaries so audio (atrim,
        # sample-precise) and video (frame-quantized) phases use identical timestamps.
        # Without this, each segment can drift by up to ½ frame (~8.3 ms at 60 fps),
        # compounding into noticeable A/V de-sync over hundreds of cuts.
        vid_fps = probe_video_fps(src_path)
        if vid_fps:
            segs = quantize_segments_to_frames(segs, vid_fps)
            render_metadata["tracks"][track_key]["fps"] = vid_fps
            render_metadata["tracks"][track_key]["segment_count_quantized"] = len(segs)
            logger.info(
                "[DETAIL] %sframe quantization: %d segments snapped to %.4f fps grid",
                f"{label} " if label else "", len(segs), vid_fps,
            )
        else:
            render_metadata["tracks"][track_key]["fps"] = None
            render_metadata["tracks"][track_key]["segment_count_quantized"] = len(segs)
            logger.warning(
                "two-phase: could not probe FPS for %s; skipping frame quantization",
                os.path.basename(src_path),
            )

        out_dir = Path(to_path).parent
        fd, tmp_audio = tempfile.mkstemp(suffix=".m4a", dir=str(out_dir))
        os.close(fd)
        fd, tmp_video = tempfile.mkstemp(suffix=".mp4", dir=str(out_dir))
        os.close(fd)
        pfx = f"{label} " if label else ""
        try:
            t0 = time.monotonic()
            logger.info("[DETAIL] %saudio render: started (%d segments)", pfx, len(segs))
            render_audio_phase(src_path, filters, segs, tmp_audio, audio_opts)
            logger.info("[DETAIL] %saudio render: complete | Took %s", pfx, _fmt_elapsed(time.monotonic() - t0))

            # Re-read the live CPU override at the audio/video-phase seam so that
            # any in-flight user adjustment takes effect for the video phase.
            # Build a *new* local dict — shared enc_opts must never be mutated.
            from utils.cpu_override import resolve_threads
            fresh_threads = resolve_threads(cfg)
            video_enc_opts = {**enc_opts, "threads": fresh_threads}
            if fresh_threads != enc_opts.get("threads"):
                logger.info(
                    "[DETAIL] %sCPU override applied at video-phase seam: threads %s -> %d",
                    pfx, enc_opts.get("threads"), fresh_threads,
                )

            if strategy == "single_pass":
                logger.info("two-phase: video_phase_strategy=single_pass; single-pass render")
                t0 = time.monotonic()
                logger.info("[DETAIL] %ssingle-pass video render: started (%d segments)", pfx, len(segs))
                render_video_single_pass(src_path, filters, segs, tmp_video, video_enc_opts, cfg)
                logger.info(
                    "[DETAIL] %ssingle-pass video render: complete | Took %s",
                    pfx,
                    _fmt_elapsed(time.monotonic() - t0),
                )
            elif strategy == "batched_gpu":
                from io_.video_renderer_strategies import render_video_batched_gpu

                num_batches = int(cfg.get("batched_gpu_num_batches", 3))
                t0 = time.monotonic()
                logger.info(
                    "[DETAIL] %sbatched-gpu video render: started (%d segments, %d batches)",
                    pfx,
                    len(segs),
                    num_batches,
                )
                render_video_batched_gpu(
                    src_path,
                    filters,
                    segs,
                    tmp_video,
                    video_enc_opts,
                    cfg,
                    num_batches=num_batches,
                )
                logger.info(
                    "[DETAIL] %sbatched-gpu video render: complete | Took %s",
                    pfx,
                    _fmt_elapsed(time.monotonic() - t0),
                )
            else:
                t0 = time.monotonic()
                logger.info("[DETAIL] %skeyframe scan: started", pfx)
                keyframes = probe_video_keyframes(src_path)
                logger.info(
                    "[DETAIL] %skeyframe scan: complete | %d keyframes | Took %s",
                    pfx,
                    len(keyframes),
                    _fmt_elapsed(time.monotonic() - t0),
                )

                t0 = time.monotonic()
                logger.info("[DETAIL] %svideo copy: started (%d segments)", pfx, len(segs))
                render_video_smart_copy(
                    src_path, segs, keyframes, tmp_video, video_enc_opts, snap_tol,
                    label=label,
                    gpu_limit_pct=int(cfg.get("gpu_limit_pct", 100)),
                )
                logger.info("[DETAIL] %svideo copy: complete | Took %s", pfx, _fmt_elapsed(time.monotonic() - t0))

            t0 = time.monotonic()
            logger.info("[DETAIL] %smux: started", pfx)
            # -shortest: stop output when the shorter track ends, preventing
            # the longer track from extending unsynchronised.  Guards against
            # any residual cumulative duration mismatch between the separately
            # rendered audio and video phases.
            cmd = ["ffmpeg", "-y", "-i", tmp_video, "-i", tmp_audio,
                   "-c", "copy", "-map", "0:v", "-map", "1:a",
                   "-shortest", to_path]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            logger.info("[DETAIL] %smux: complete | Took %s", pfx, _fmt_elapsed(time.monotonic() - t0))
            if proc.returncode != 0:
                raise RuntimeError(f"Mux failed: {proc.stderr}")
        finally:
            for _p in (tmp_audio, tmp_video):
                try:
                    os.remove(_p)
                except OSError:
                    pass

    def _run(task: tuple[str, str, str, list]) -> None:
        label, src, dst, filters = task
        logger.info("Rendering %s Video (two-phase)...", label)
        _render_with_safe_overwrite(
            src,
            dst,
            lambda to_path, _s=src, _f=filters, _label=label: _render_track(_s, _f, to_path, label=_label),
        )

    if len(render_tasks) == 1:
        _run(render_tasks[0])
    else:
        logger.info("Rendering Host + Guest in parallel (two-phase, max_workers=2)...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_run, t) for t in render_tasks]
        for future in futures:
            future.result()

    return render_metadata
