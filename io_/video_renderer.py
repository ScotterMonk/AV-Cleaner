# io/video_renderer.py

import ffmpeg
import functools
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable
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


def build_cpu_enc_opts(config):
    """Pure helper to build CPU encoder options for ffmpeg.output()."""
    config = config or {}
    return {
        "vcodec": config.get("video_codec", "libx264"),
        "preset": config.get("video_preset", "fast"),
        "crf": config.get("crf", 23),
        "acodec": config.get("audio_codec", "aac"),
        "audio_bitrate": config.get("audio_bitrate", "192k"),
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


# Modified by gpt-5.2 | 2026-01-12_01
def run_with_progress(stream_spec, **kwargs):
    """
    Runs ffmpeg with a custom progress parser that displays a table.
    Columns: Frame, FPS, Q, Size, Progress (time), Bitrate, Speed, Elapsed.
    
    Uses -progress pipe:1 for machine-readable output with proper newlines,
    and flush=True on all prints for immediate GUI display.
    """
    cmd_args = ffmpeg.compile(stream_spec, **kwargs)
    # Add -progress for machine-readable newline-delimited output
    # Add -nostats to suppress the normal stderr progress line
    cmd_args = cmd_args + ["-progress", "pipe:1", "-nostats"]
    logger.info(f"Running FFmpeg: {' '.join(cmd_args)}")

    start_time = time.time()

    # Table Header - pinned at top
    headers = ["Frame", "FPS", "Q", "Size", "Progress", "Bitrate", "Speed", "Elapsed"]
    row_fmt = "{:<8} {:<8} {:<6} {:<10} {:<12} {:<12} {:<8} {:<10}"
    
    print("-" * 80, flush=True)
    print(row_fmt.format(*headers), flush=True)
    print("-" * 80, flush=True)

    # NOTE:
    # - We merge stderr into stdout to avoid deadlocks if FFmpeg writes enough to fill the stderr pipe.
    # - This also matches how the GUI reads output (stdout only) in [`AVCleanerGUI.run_processing()`](ui/gui_app.py:262).
    process = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1  # Line-buffered
    )

    assert process.stdout is not None

    # -progress outputs key=value pairs, one per line.
    # We collect them and print a row when we see "progress=continue" or "progress=end".
    stats = {}
    last_print_time = 0.0
    UPDATE_INTERVAL = 0.25  # Throttle to ~4 updates/sec for GUI smoothness

    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        
        if "=" in line:
            key, _, value = line.partition("=")
            stats[key] = value
            
            # When we see progress=continue or progress=end, we have a full update
            if key == "progress":
                current_time = time.time()
                # Throttle output for GUI performance
                if current_time - last_print_time >= UPDATE_INTERVAL or value == "end":
                    elapsed = current_time - start_time
                    elapsed_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))
                    
                    # Format size from bytes to kB
                    try:
                        size_bytes = int(stats.get("total_size", 0))
                        size_str = f"{size_bytes // 1024}kB"
                    except (ValueError, TypeError):
                        size_str = stats.get("total_size", "N/A")
                    
                    # Find Q value (stream_0_0_q or similar)
                    q_val = "-"
                    for k, v in stats.items():
                        if k.endswith("_q"):
                            q_val = v
                            break
                    
                    # out_time is in format HH:MM:SS.microseconds
                    progress_time = stats.get("out_time", "00:00:00")
                    # Truncate microseconds for cleaner display
                    if "." in progress_time:
                        progress_time = progress_time.split(".")[0]
                    
                    print(row_fmt.format(
                        stats.get("frame", "0"),
                        stats.get("fps", "0"),
                        q_val,
                        size_str,
                        progress_time,
                        stats.get("bitrate", "N/A"),
                        stats.get("speed", "N/A"),
                        elapsed_str
                    ), flush=True)
                    last_print_time = current_time
        else:
            # Non key=value line - likely FFmpeg banner/warnings.
            # Keep the table clean; only print likely-fatal messages.
            lowered = line.lower()
            if "error" in lowered or "invalid" in lowered or "failed" in lowered:
                print(line, flush=True)

    returncode = process.wait()
    if returncode != 0:
        logger.error(f"FFmpeg failed with return code {returncode}")
        raise ffmpeg.Error("ffmpeg", returncode, cmd=cmd_args)

    # Provide an explicit end/summary message (the old FFmpeg stderr stats line effectively did this).
    total_elapsed = time.time() - start_time
    total_elapsed_str = time.strftime("%H:%M:%S", time.gmtime(total_elapsed))

    # Created by gpt-5.2 | 2026-01-12_01
    def _format_bytes(n: int) -> str:
        if n < 0:
            return "N/A"
        if n < 1024:
            return f"{n}B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f}kB"
        if n < 1024 * 1024 * 1024:
            return f"{n / (1024 * 1024):.1f}MB"
        return f"{n / (1024 * 1024 * 1024):.2f}GB"

    try:
        final_size_bytes = int(stats.get("total_size", 0))
        final_size_str = _format_bytes(final_size_bytes)
    except (ValueError, TypeError):
        final_size_str = "N/A"

    print("-" * 80, flush=True)
    print(
        f"FFmpeg complete | elapsed={total_elapsed_str} | final_size={final_size_str} | avg_bitrate={stats.get('bitrate', 'N/A')}",
        flush=True,
    )


@functools.lru_cache(maxsize=1)
def probe_ffmpeg_capabilities():
    # Created by gpt-5.2 | 2026-01-09_01
    """Best-effort probe for local FFmpeg capabilities.

    Returns a small dict suitable for unit tests and memoization.

    Shape:
        {
            "ffmpeg_ok": bool,
            "encoders": frozenset[str],   # subset of {"h264_nvenc", "hevc_nvenc"}
            "hwaccels": frozenset[str],   # subset of {"cuda"}
        }
    """

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

    # [Modified] by gpt-5.2 | 2026-01-09_03
    def build_chain(input_path, filters, keep_segments):
        inp = ffmpeg.input(input_path, **input_kwargs)
        v = inp.video
        a = inp.audio
        
        # 1. Apply Audio Filters (Normalization, etc.)
        for f in filters:
            a = a.filter(f.filter_name, **f.params)
            
        # 2. Apply Cutting (Trimming)
        if keep_segments:
            segments_v = []
            segments_a = []
            for start, end in keep_segments:
                # Video Trim (Reset PTS to start at 0 relative to segment)
                seg_v = v.trim(start=start, end=end).setpts("PTS-STARTPTS")
                segments_v.append(seg_v)
                
                # Audio Trim (Must match exactly)
                seg_a = a.filter_("atrim", start=start, end=end).filter_("asetpts", "PTS-STARTPTS")
                segments_a.append(seg_a)
                
            # Concatenate all segments
            v = ffmpeg.concat(*segments_v, v=1, a=0).node[0]
            a = ffmpeg.concat(*segments_a, v=0, a=1).node[0]
            
        return v, a

    if not out_host and not out_guest:
        raise ValueError("render_project() requires at least one output (out_host or out_guest)")

    # Build graphs (only for requested outputs)
    h_v = h_a = None
    g_v = g_a = None
    if out_host:
        h_v, h_a = build_chain(host_path, manifest.host_filters, manifest.keep_segments)
    if out_guest:
        g_v, g_a = build_chain(guest_path, manifest.guest_filters, manifest.keep_segments)
    
    # Common Output Settings
    enc_opts = select_enc_opts(config, caps)

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
    
    # Define Outputs
    # Note: Running sequentially is safer for memory, though parallel is possible
    if out_host:
        logger.info("Rendering Host Video...")
        def _render_host(to_path: str) -> None:
            stream = ffmpeg.output(h_v, h_a, to_path, **enc_opts)
            run_with_progress(stream, overwrite_output=True)

        _render_with_safe_overwrite(host_path, out_host, _render_host)

    if out_guest:
        logger.info("Rendering Guest Video...")
        def _render_guest(to_path: str) -> None:
            stream = ffmpeg.output(g_v, g_a, to_path, **enc_opts)
            run_with_progress(stream, overwrite_output=True)

        _render_with_safe_overwrite(guest_path, out_guest, _render_guest)
