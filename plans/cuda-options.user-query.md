# User query — cuda-options

## Request

Modify application to include OPTIONs for CUDA use.

### Add options to config

- CUDA video encoding
- CUDA video decoding

### Where CUDA can help in this codebase

#### Video encoding

Rendering happens in [`render_project()`](../io_/video_renderer.py:8) via `ffmpeg.output(..., **enc_opts).run()`.
With an NVIDIA GPU (CUDA enabled in config) + an FFmpeg build with NVENC enabled, switch the video encoder from CPU (`libx264`) to GPU (`h264_nvenc` / `hevc_nvenc`).

#### Video decoding

**If CUDA disabled (mimics/uses current implementation)**:
- Filter graph in [`render_project()`](../io_/video_renderer.py:8) uses CPU-side trim/concat.

**If CUDA enabled in config**:
- Get FFmpeg to decode with CUDA (`-hwaccel cuda`, `h264_cuvid`).
- Make graph GPU-native (e.g., `hwupload_cuda` + CUDA filters + NVENC).
- Do not use for audio extraction + analysis.

### Practical “CUDA enablement” options

**Option A (recommended): NVENC for output encoding**
- Set `config['video_codec']` (used in [`render_project()`](../io_/video_renderer.py:8)) to an NVENC codec (e.g., `h264_nvenc`).
- Adjust rate-control options: current `crf` in `enc_opts` is for x264; NVENC uses `cq`/`qp`/`rc` style controls.
- Expect slightly different quality/bitrate tradeoffs vs `libx264`.

**Option B: Hardware decode (only if profiling shows decode-bound)**
- Add FFmpeg input args (conceptually) to request CUDA decode.
- Only worthwhile if frames stay on-GPU for most of the graph; otherwise pay upload/download costs.

