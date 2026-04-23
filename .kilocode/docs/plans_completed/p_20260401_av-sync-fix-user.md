# User Query — AV Sync Fix

**Date**: 2026-04-01  
**Plan**: p_20260401_av-sync-fix  

## User Query

After processing, both guest and host processed videos have audio that starts approximately 8–9 frames behind video at 60 fps (~133–150 ms) and approximately 3.7 frames behind at 24 fps (~154 ms). The user confirmed the issue on Guest with certainty and suspects Host as well.

The user wants a **full principled fix** — no cheap partial solutions.

## Why (inferred and confirmed)

The pipeline recently added render-time `afftdn` noise reduction. This exposed two compounding delays that were previously sub-perceptual:

1. **`afftdn` FFT warm-up silence** (~85 ms at 48 kHz) — the filter pads its output with near-silence while filling its initial FFT analysis window; this silence flows through to the audio-only temp file.
2. **AAC encoder priming lost in ADTS intermediate format** (~43 ms at 48 kHz) — the temp audio file uses `.aac` (ADTS format), which cannot store encoder delay metadata; when muxed with `-c copy`, the priming samples appear as real audio offset content with no edit list to correct them.

Both delays persist uncorrected through the final mux because audio and video are rendered in separate processes (the two-phase architecture), preventing FFmpeg's internal AV sync compensation from working.

## Scope

- Fix is contained to the two-phase render pipeline.
- Touches: `io_/video_renderer_twophase.py`, `io_/media_probe.py` (sample rate probe), possibly `io_/video_renderer.py` or a new utility.
- Testing: verify output audio starts without leading silence on both Host and Guest tracks under all video_phase_strategy values.
