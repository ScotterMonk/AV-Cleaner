# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Commands (non-standard flags)
- Run tests from project root: `pytest` (NOT from tests/ subdirectory; imports require root context)
- Override normalization: `python main.py --host ... --guest ... --norm-mode MATCH_HOST|STANDARD_LUFS`

--- do not remove this ---
## Shell & Environment (Windows-specific)
- **Base folder**: `D:/Dropbox/Projects/AV-cleaner/app/`. Convert between "\" and "/" as necessary.
- **Prefer PowerShell** for commands; if `;` is treated as an argument, you likely ran in `cmd.exe` (use `&` or `&&` instead)
- **Videos for testing**: `{base folder}/test_videos`
--- do not remove this ---

## Critical Non-Obvious Gotchas
- **Sync**
    - **Keep guest's video in sync with guest's audio**.
    - **Keep host's video in sync with host's audio**.
    - **Keep guest and host in sync with each other**: any removal of a pause in either video means you must modify both videos so they stay in sync.
- **Audio extraction loads entire video into RAM** as stereo 44.1kHz WAV via pydub; long videos require hundreds of MB (`io_/audio_extractor.py`)
- **All outputs are MP4** even when input is `.avi`, `.mkv`, etc. (`utils/path_helpers.py`, line 6)
- **`make_processed_output_path()` prevents "_processed_processed" chains**; if input already ends in `_processed.ext`, returns input unchanged—BUT preserves original extension (doesn't force `.mp4`) (`utils/path_helpers.py:36`, `tests/test_output_paths.py:35`)
- **Detectors are NEVER user-configurable**; they're auto-added based on enabled processors (`main.py:56-64`)
- **Pipeline always renders BOTH outputs** (host + guest) even for guest-only workflows to maintain paired alignment (`main.py:121`)
- **`normalize_video_lengths()` writes BOTH processed files** when duration mismatch detected, even if only one needs padding (`io_/media_preflight.py:99`)
- **Rendering with output==input uses temp file + atomic replace**; otherwise FFmpeg would read/write same path (`io_/video_renderer.py:24`)
- **GUI subprocess stdout/stderr are merged** (`io_/video_renderer.py:189`); FFmpeg progress throttled to 0.25s for GUI smoothness (`io_/video_renderer.py:206`)
- **Frame-accurate cutting requires H.264/AAC**; changing codecs breaks non-keyframe cuts (`config.py`, `io_/video_renderer.py`)
- **LUFS uses `pyloudnorm` if installed**; missing triggers RMS fallback with warning (`analyzers/audio_level_analyzer.py`)

## Architecture (Edit Flow)
- Detectors → results keyed by `detector.get_name()` → processors consume and build `EditManifest` (no media mutation) (`core/pipeline.py`, `processors/base_processor.py`)
- Rendering applies `host_filters`/`guest_filters`, then trims video AND audio using SAME `keep_segments` to preserve sync (`io_/video_renderer.py`, `core/interfaces.py`)
