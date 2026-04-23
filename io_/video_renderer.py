# io_/video_renderer.py

import ffmpeg
import functools
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from io_.video_renderer_segments import (
    ADAPTIVE_SEGMENT_COUNT_HIGH,
    ADAPTIVE_SEGMENT_COUNT_TARGET,
    ADAPTIVE_SEGMENT_GAP_MAX_S,
    SEGMENT_GAP_MERGE_THRESHOLD_S,
    merge_close_segments,
    merge_close_segments_adaptive,
)
from io_.video_renderer_audio import (
    audio_filters_apply,
    audio_filters_partition,
    audio_segments_build,
)
from io_.video_renderer_progress import run_with_progress  # noqa: F401 — re-exported for callers
from utils.logger import get_logger

logger = get_logger(__name__)


def _path_norm_for_compare(p: str) -> str:
    """Normalize a path for equality comparisons (works even if path doesn't exist)."""
    return os.path.normcase(os.path.abspath(p))


def _render_with_safe_overwrite(input_path: str, output_path: str, render: Callable[[str], None]) -> None:
    """Render to `output_path`, safely handling the case where output==input.

    If `output_path` resolves to the same location as `input_path`, we render to a
    temp file *in the output directory* and then atomically replace the original.

    This avoids reading and writing the same path in one FFmpeg invocation.
    """
    if _path_norm_for_compare(input_path) != _path_norm_for_compare(output_path):
        render(output_path)
        return

    out_p = Path(output_path)
    out_dir = out_p.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{out_p.stem}.tmp-",
        suffix=out_p.suffix,
        dir=str(out_dir),
    )
    os.close(fd)

    try:
        logger.info("Output path equals input path; rendering to temp then replacing: %s", tmp_path)
        render(tmp_path)
        os.replace(tmp_path, output_path)
    except Exception:
        # Ensure we don't leave a temp file behind on failure.
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        finally:
            raise


def cpu_threads_from_config(config: dict) -> int:
    """Compute FFmpeg -threads value from cpu_limit_pct config setting.

    Maps cpu_limit_pct (1–100) to a per-process thread count based on the
    number of logical CPU cores. Passing the result as threads=N in enc_opts
    causes ffmpeg.output() to emit -threads N, capping encode/filter threads
    per FFmpeg process.  Default 80% keeps the machine usable during encodes.
    """
    pct = int((config or {}).get("cpu_limit_pct", 80))
    pct = max(1, min(100, pct))
    total = os.cpu_count() or 1
    return max(1, round(total * pct / 100))


def build_cpu_enc_opts(config):
    """Pure helper to build CPU encoder options for ffmpeg.output()."""
    config = config or {}
    return {
        "vcodec": config.get("video_codec", "libx264"),
        "preset": config.get("video_preset", "fast"),
        "crf": config.get("crf", 23),
        "acodec": config.get("audio_codec", "aac"),
        "audio_bitrate": config.get("audio_bitrate", "192k"),
        # Preserve original frame timestamps (passthrough) to prevent
        # progressive A/V drift when source video is VFR (variable frame
        # rate).  Without this, FFmpeg defaults to -vsync cfr which
        # duplicates/drops frames to force constant spacing, shifting
        # video timing relative to audio.  Harmless for CFR sources.
        "vsync": "passthrough",
    }


def build_nvenc_enc_opts(config):
    """
    Pure helper to build NVENC encoder options for ffmpeg.output().
    - NVENC does not support x264/libx264's CRF, so this intentionally omits "crf".
    """
    config = config or {}
    nvenc = config.get("nvenc") or {}

    opts = {
        "vcodec": nvenc.get("codec", "h264_nvenc"),
        "preset": nvenc.get("preset", "p4"),
        "rc": nvenc.get("rc", "vbr"),
        "acodec": config.get("audio_codec", "aac"),
        "audio_bitrate": config.get("audio_bitrate", "192k"),
        # Preserve original frame timestamps — see build_cpu_enc_opts comment.
        "vsync": "passthrough",
    }

    cq = nvenc.get("cq", 23)
    if cq is not None:
        opts["cq"] = cq

    return opts


def build_input_kwargs(config, caps):
    """Pure helper returning kwargs for ffmpeg.input()."""
    config = config or {}
    caps = caps or {}
    hwaccels = caps.get("hwaccels") or ()

    cuda_supported = "cuda" in hwaccels
    if config.get("cuda_decode_enabled") and cuda_supported:
        return {"hwaccel": "cuda"}
    return {}


# Modified by gpt-5.2 | 2026-01-09_02
def select_enc_opts(config, caps):
    """
    Select encoder options for ffmpeg.output() based on config + probed FFmpeg caps.
    Rules:
    - If cuda_encode_enabled is False: always CPU encode.
    - If cuda_encode_enabled is True:
        - If NVENC is supported (desired codec present OR at least h264_nvenc):
            Use NVENC opts.
        - Else:
            - If cuda_require_support is True:
                Raise with a clear message.
            - Else:
                Warn (ALL CAPS) and fall back to CPU opts.
    """
    config = config or {}
    caps = caps or {}

    use_cuda_encode = bool(config.get("cuda_encode_enabled"))
    require_support = bool(config.get("cuda_require_support"))

    if not use_cuda_encode:
        return build_cpu_enc_opts(config)

    encoders = set(caps.get("encoders") or ())
    desired_codec = (config.get("nvenc") or {}).get("codec", "h264_nvenc")
    nvenc_supported = desired_codec in encoders or "h264_nvenc" in encoders

    if nvenc_supported:
        enc_opts = build_nvenc_enc_opts(config)

        # If the configured codec isn't present but h264_nvenc is, force a safe default.
        if enc_opts.get("vcodec") not in encoders and "h264_nvenc" in encoders:
            logger.info(
                "NVENC codec not detected (wanted=%s, available=%s); using h264_nvenc",
                enc_opts.get("vcodec"),
                sorted(encoders),
            )
            enc_opts["vcodec"] = "h264_nvenc"

        return enc_opts

    if require_support:
        raise RuntimeError(
            "CUDA/NVENC ENCODE REQUESTED (cuda_encode_enabled=True) BUT NVENC IS NOT AVAILABLE: "
            "FFmpeg encoder h264_nvenc was not found. "
            "Install an FFmpeg build with NVENC support or set cuda_require_support=False."
        )

    logger.warning("CUDA/NVENC REQUESTED BUT NOT AVAILABLE; FALLING BACK TO CPU ENCODE")
    return build_cpu_enc_opts(config)


def _apply_cut_fades(segments: list, cut_fade_s: float) -> list:
    """Return per-segment afade filter specs for click/pop elimination at cut boundaries.

    A 15–20 ms afade envelope is wrapped around each cut boundary — fade-out at the
    tail of the segment before the cut, fade-in at the head of the segment after it.
    The envelope is imperceptible as a volume change but eliminates the sample
    discontinuity that the AAC encoder would otherwise reproduce as a click or pop.

    Args:
        segments:    Sorted (start_s, end_s) keep-segment tuples (already merged).
        cut_fade_s:  Fade duration in seconds. 0 disables fading entirely; configs
                     without the key also default to 0 (fully backward-compatible).

    Returns:
        List of length len(segments); each element is a list of afade spec dicts
        with keys: 'type' ('in'|'out'), 'st' (float, seconds), 'd' (float, seconds).
        PTS is assumed to have been reset to 0 by asetpts before these fades run.

    Behaviour:
        - Single segment  -> no fades (nothing was cut)
        - First segment   -> fade-out only  (no cut precedes it, so no fade-in)
        - Last segment    -> fade-in only   (no cut follows it)
        - Middle segments -> fade-in then fade-out
        - Too-short (duration < required fade budget) -> skip fades + log debug
    """
    n = len(segments)

    # Fast path: fading disabled or nothing to process.
    if cut_fade_s <= 0 or n == 0:
        return [[] for _ in segments]

    # Single segment: nothing was cut; no fades needed.
    if n == 1:
        return [[]]

    result = []
    for idx, (start, end) in enumerate(segments):
        duration = end - start
        is_first = (idx == 0)
        is_last = (idx == n - 1)

        needs_fade_in = not is_first
        needs_fade_out = not is_last

        # Budget: how much fade headroom this segment must provide.
        fade_budget = (
            cut_fade_s          # first or last: one sided
            if (is_first or is_last)
            else 2 * cut_fade_s  # middle: fade-in + fade-out
        )

        if duration < fade_budget:
            logger.debug(
                "_apply_cut_fades: segment %d/%d too short (%.3fs < %.3fs); skipping fades",
                idx + 1, n, duration, fade_budget,
            )
            result.append([])
            continue

        fades = []
        if needs_fade_in:
            # PTS is reset to 0 by asetpts, so fade-in always starts at t=0.
            fades.append({"type": "in", "st": 0.0, "d": cut_fade_s})
        if needs_fade_out:
            # Fade-out starts at (duration - fade_duration) relative to reset PTS.
            fades.append({"type": "out", "st": duration - cut_fade_s, "d": cut_fade_s})
        result.append(fades)

    return result


def _build_filter_chain(
    input_path: str,
    filters: list,
    keep_segments: list,
    input_kwargs: dict,
    cut_fade_s: float = 0.0,
) -> tuple:
    """Build ffmpeg-python video + audio streams for one input file.

    Extracted from the `build_chain` closure in `render_project` so it can be
    reused by both the single-pass and chunk-parallel rendering paths.

    Returns:
        (v, a) — ffmpeg-python stream specs ready for ffmpeg.output().
    """
    inp = ffmpeg.input(input_path, **input_kwargs)
    v = inp.video
    a = inp.audio

    # Merge adjacent segments separated by an imperceptibly small gap to reduce
    # filter graph complexity (saves ~20-40% of trim/atrim node pairs).
    # Uses adaptive widening automatically when segment count is very high.
    if keep_segments and len(keep_segments) > 1:
        original_count = len(keep_segments)
        keep_segments = merge_close_segments_adaptive(keep_segments)
        merged_away = original_count - len(keep_segments)
        if merged_away:
            logger.info(
                "_build_filter_chain(%s): merged %d micro-gap pair(s); segments %d -> %d",
                os.path.basename(str(input_path)),
                merged_away,
                original_count,
                len(keep_segments),
            )

    try:
        filter_names = [getattr(f, "filter_name", str(f)) for f in (filters or [])]
    except Exception:
        filter_names = ["<unprintable>"]
    logger.debug(
        "_build_filter_chain(%s): keep_segments=%s audio_filters=%s",
        os.path.basename(str(input_path)),
        len(keep_segments or []),
        filter_names,
    )

    filters_original_timeline, filters_post_trim = audio_filters_partition(filters or [])
    a = audio_filters_apply(a, filters_original_timeline)

    # 2. Apply Cutting (Trimming)
    if keep_segments:
        segments_v = []

        fade_specs = _apply_cut_fades(keep_segments, cut_fade_s)
        segments_a = audio_segments_build(
            audio_stream=a,
            keep_segments=keep_segments,
            cut_fade_s=cut_fade_s,
            fade_specs=fade_specs,
            input_path=input_path,
            split_required=bool(filters_original_timeline),
        )

        for idx, (start, end) in enumerate(keep_segments):
            # Video Trim (Reset PTS to start at 0 relative to segment)
            seg_v = v.trim(start=start, end=end).setpts("PTS-STARTPTS")
            segments_v.append(seg_v)

        # Concatenate all segments using a single combined concat to guarantee A/V sync.
        # Two separate concat filters (one for video, one for audio) accumulate PTS drift
        # independently across segments: even sub-frame timing differences between a video
        # trim boundary (frame-aligned) and an audio atrim boundary (sample-exact) compound
        # over multiple cuts and produce sped-up or slowed-down playback.
        # A combined concat=n=N:v=1:a=1 with interleaved [v, a] pairs locks video and audio
        # together per-segment inside a single filter, preventing any drift from building up.
        interleaved = []
        for seg_v, seg_a in zip(segments_v, segments_a):
            interleaved.append(seg_v)
            interleaved.append(seg_a)
        concat_out = ffmpeg.concat(*interleaved, v=1, a=1)
        v = concat_out.node[0]  # video output (stream 0)
        a = concat_out.node[1]  # audio output (stream 1)

    a = audio_filters_apply(a, filters_post_trim)

    return v, a


@functools.lru_cache(maxsize=1)
def probe_ffmpeg_capabilities():
    # Created by gpt-5.2 | 2026-01-09_01
    """Best-effort probe for local FFmpeg capabilities."""
    desired_encoders = {"h264_nvenc", "hevc_nvenc"}
    desired_hwaccels = {"cuda"}

    def _run_ffmpeg_cmd(args):
        return subprocess.run(args, capture_output=True, text=True)

    def _combined_output(proc):
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        return f"{stdout}\n{stderr}".strip()

    def _contains_token(haystack, token):
        return re.search(rf"\b{re.escape(token)}\b", haystack) is not None

    ffmpeg_ok = False
    found_encoders = set()
    found_hwaccels = set()

    try:
        enc_proc = _run_ffmpeg_cmd(["ffmpeg", "-hide_banner", "-encoders"])
        ffmpeg_ok = True
        enc_output = _combined_output(enc_proc)
        for enc in desired_encoders:
            if _contains_token(enc_output, enc):
                found_encoders.add(enc)

        hw_proc = _run_ffmpeg_cmd(["ffmpeg", "-hide_banner", "-hwaccels"])
        hw_output = _combined_output(hw_proc)
        for accel in desired_hwaccels:
            if _contains_token(hw_output, accel):
                found_hwaccels.add(accel)
    except (FileNotFoundError, OSError) as e:
        logger.info("FFmpeg not available for probing (%s); treating GPU capabilities as absent", e)
        return {"ffmpeg_ok": False, "encoders": frozenset(), "hwaccels": frozenset()}

    logger.debug(
        "FFmpeg probe result: ffmpeg_ok=%s encoders=%s hwaccels=%s",
        ffmpeg_ok,
        sorted(found_encoders),
        sorted(found_hwaccels),
    )

    if "cuda" in found_hwaccels or found_encoders:
        logger.info(
            "Detected FFmpeg GPU capabilities: encoders=%s hwaccels=%s",
            sorted(found_encoders),
            sorted(found_hwaccels),
        )
    else:
        logger.info("No FFmpeg CUDA/NVENC capabilities detected")

    return {
        "ffmpeg_ok": ffmpeg_ok,
        "encoders": frozenset(found_encoders),
        "hwaccels": frozenset(found_hwaccels),
    }


def _fmt_elapsed(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS for progress display."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# [Modified] by gpt-5.2 | 2026-01-09_03
def render_project(host_path, guest_path, manifest, out_host, out_guest, config):
    """
    Constructs and executes the FFmpeg graph.
    Cuts video and audio simultaneously to guarantee sync.
    """
    caps = probe_ffmpeg_capabilities()

    # [Modified] by gpt-5.2 | 2026-01-09_03
    # Best-effort CUDA decode is applied ONLY at ffmpeg.input(...) time.
    # NOTE: The rest of the filter graph remains CPU-side.
    use_cuda_decode = bool((config or {}).get("cuda_decode_enabled"))
    input_kwargs = build_input_kwargs(config, caps) if use_cuda_decode else {}
    if use_cuda_decode and input_kwargs:
        logger.warning(
            "CUDA HWACCEL DECODE ENABLED; FILTER GRAPH IS CPU-SIDE SO DECODE SPEEDUPS MAY BE LIMITED"
        )

    if not out_host and not out_guest:
        raise ValueError("render_project() requires at least one output (out_host or out_guest)")

    # Common Output Settings
    enc_opts = select_enc_opts(config, caps)
    # Throttle per-process FFmpeg thread count to honour cpu_limit_pct.
    enc_opts["threads"] = cpu_threads_from_config(config or {})

    logger.info(
        "Selected encoder options: vcodec=%s preset=%s crf=%s cq=%s rc=%s acodec=%s audio_bitrate=%s",
        enc_opts.get("vcodec"),
        enc_opts.get("preset"),
        enc_opts.get("crf"),
        enc_opts.get("cq"),
        enc_opts.get("rc"),
        enc_opts.get("acodec"),
        enc_opts.get("audio_bitrate"),
    )

    cfg = config or {}

    # Cut-boundary fade: eliminates clicks/pops at sample-level splice discontinuities.
    # Default 0 -> disabled; old configs without the key are safe (backward-compatible).
    cut_fade_ms = float(cfg.get("cut_fade_ms", 0))
    cut_fade_s = cut_fade_ms / 1000.0

    # Two-phase render dispatch (audio-first + smart video copy).
    # NOTE: probe_ffmpeg_capabilities() is LRU-cached; select_enc_opts() above is
    # redundant when two-phase is active, but cost is negligible.
    if cfg.get("two_phase_render_enabled"):
        from io_.video_renderer_twophase import render_project_two_phase

        logger.info("Two-phase render ACTIVE (audio-first + smart video copy)")
        out_count = sum(1 for o in (out_host, out_guest) if o)
        logger.info(
            "[DETAIL] Encoding strategy: two-phase (audio-first + smart copy) × %d video(s)",
            out_count,
        )
        return render_project_two_phase(
            host_path, guest_path, manifest, out_host, out_guest, config
        )

    n_segs = len(manifest.keep_segments or [])
    out_count = sum(1 for o in (out_host, out_guest) if o)
    logger.info(
        "[DETAIL] Encoding strategy: single-pass | %d segments × %d video(s)",
        n_segs, out_count,
    )

    # Collect render tasks so we can run host+guest in parallel (existing behaviour).
    # Each task is a completely independent FFmpeg subprocess writing to a different
    # file, so there is zero sync risk.
    render_tasks: list[tuple[str, str, str, Callable[[str], None]]] = []

    if out_host:
        def _render_host(to_path: str) -> None:
            h_v, h_a = _build_filter_chain(
                host_path, manifest.host_filters, manifest.keep_segments, input_kwargs,
                cut_fade_s=cut_fade_s,
            )
            stream = ffmpeg.output(h_v, h_a, to_path, **enc_opts)
            run_with_progress(stream, overwrite_output=True)
        render_tasks.append(("Host", host_path, out_host, _render_host))

    if out_guest:
        def _render_guest(to_path: str) -> None:
            g_v, g_a = _build_filter_chain(
                guest_path, manifest.guest_filters, manifest.keep_segments, input_kwargs,
                cut_fade_s=cut_fade_s,
            )
            stream = ffmpeg.output(g_v, g_a, to_path, **enc_opts)
            run_with_progress(stream, overwrite_output=True)
        render_tasks.append(("Guest", guest_path, out_guest, _render_guest))

    def _run_render_task(task: tuple[str, str, str, Callable[[str], None]]) -> None:
        """Execute a single (label, src, dst, render_fn) render task."""
        label, src, dst, fn = task
        logger.info("Rendering %s Video...", label)
        logger.info("[DETAIL] %s video: encoding started", label)
        task_start = time.time()
        _render_with_safe_overwrite(src, dst, fn)
        elapsed = _fmt_elapsed(time.time() - task_start)
        logger.info("[DETAIL] %s video: encoding complete | Took %s", label, elapsed)

    if len(render_tasks) == 1:
        # Only one output requested — skip threading overhead.
        _run_render_task(render_tasks[0])
    else:
        # Both outputs requested — run in parallel for ~2× wall-clock speedup.
        logger.info("Rendering Host + Guest Videos in parallel (ThreadPoolExecutor max_workers=2)...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_run_render_task, t) for t in render_tasks]
        # executor.__exit__ blocks until both threads finish; now surface any exceptions.
        for future in futures:
            future.result()

    return {
        "strategy_family": "single_pass",
    }
