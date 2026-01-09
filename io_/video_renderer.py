# io/video_renderer.py

import ffmpeg
import functools
import re
import subprocess
from utils.logger import get_logger

logger = get_logger(__name__)


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
    """Pure helper to build NVENC encoder options for ffmpeg.output().

    Notes:
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
    """Select encoder options for ffmpeg.output() based on config + probed FFmpeg caps.

    Rules:
      - If cuda_encode_enabled is False: always CPU encode.
      - If cuda_encode_enabled is True:
          - If NVENC is supported (desired codec present OR at least h264_nvenc): use NVENC opts.
          - Else:
              - If cuda_require_support is True: raise with a clear message.
              - Else: warn (ALL CAPS) and fall back to CPU opts.
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
        ffmpeg.output(h_v, h_a, out_host, **enc_opts).run(overwrite_output=True)

    if out_guest:
        logger.info("Rendering Guest Video...")
        ffmpeg.output(g_v, g_a, out_guest, **enc_opts).run(overwrite_output=True)
