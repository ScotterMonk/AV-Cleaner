# AGENTS.md

## Environment & Shell
- **Context**: Windows 11, VS Code, PowerShell Core (`pwsh`).
- **Compute resources**: Optimized for AMD Ryzen 7 5800X, 64GB DDR4 RAM, nVidia RTX 3080 12GB.
- **Base folder**: `d:/Dropbox/Projects/AV-cleaner/app/`.
    - **Rule**: Always use forward slashes `/` in paths to avoid escaping errors.
- **Terminal**: **STRICTLY PowerShell**. Do not use `cmd.exe`, `bash`, or `wsl`.
- **Syntax Rules**:
  - **Chaining**: Use `;` (sequential) or `&&` (conditional).
  - **Variables**: Use `$env:VAR = 'val'` (not `export` or `set`).
  - **Replacements**: Use `Select-String` (not `grep`), `Get-Content` (not `cat`), `New-Item` (not `touch`), `Remove-Item` (not `rm`).
   - **NO terminal line feeds**: 
      - **No:**:
         ```
         python -c "
         print('stuff')
         print('more')
         "
         ```
      - **Yes:**:
         ```
         python -c "print('stuff'); print('more')"
         ```
- **Prohibited**: `tail`, `sed`, `awk`, `sudo`, and `cmd.exe` flags (like `/d`).


## Run Commands
- Start app: `python app.py` # launches the GUI. Do not test to see if it worked.
- **ONLY if venv not activated**: Activate venv with `.\activate.ps1`.
- Run processing: `python main.py process --host <path> --guest <path>`.
- Override normalization: `python main.py process --host ... --guest ... --norm-mode MATCH_HOST|STANDARD_LUFS`.
- Run tests: `pytest` (from project root).
- Run single test: `pytest tests/test_filename.py`.

## Critical Non-Obvious Gotchas
- **`io_/` trailing underscore is intentional** — do NOT write `io/`; that shadows Python's built-in `io` namespace.
- **`config.py` is the behavioral control surface** — `PIPELINE_CONFIG`, `QUALITY_PRESETS`, and `WORDS_TO_REMOVE` control which processors run, thresholds, codec settings, and filler word detection. Start there for any behavioral change.
- **Only one active quality preset**: `QUALITY_PRESETS['PODCAST_HIGH_QUALITY']` is deep-copied into the per-run config in `_run_process()` (`main.py`). Add new presets only if you also update the selection site.
- **`--action` is deprecated**; it accepts only `None` or `ALL` (any other value raises `click.ClickException`). Never generate `--action ALL` in new scripts or tests (`main.py`).
- **Top-level CLI form is legacy** — `python main.py --host ... --guest ...` still routes via `cli()` but always prefer the `process` subcommand.
- **Sync invariants** (must all hold after any edit):
    - Keep guest's video in sync with guest's audio.
    - Keep host's video in sync with host's audio.
    - Keep guest and host in sync with each other: any removal of a pause in either track means you must mirror the removal on the other track.
- **Audio extraction writes to a temp WAV then loads into RAM** as stereo 44.1kHz via pydub/FFmpeg; the temp file is deleted after load, but the in-memory AudioSegment remains (a 1-hour stereo 16-bit WAV is ~600 MB) (`io_/audio_extractor.py`).
- **All outputs are MP4** even when input is `.avi`, `.mkv`, etc. (`utils/path_helpers.py`).
- **`make_processed_output_path()` prevents `_processed_processed` chains**; if input already ends in `_processed`, it strips that suffix and returns `{stem}_processed_rerun.mp4` (unless `output_ext` overridden) (`utils/path_helpers.py`, `tests/test_output_paths.py`).
- **Detectors are NEVER user-configurable**; they're auto-added based on enabled processors (`main.py`).
- **Detector registration order is fixed**: `AudioLevelDetector → SpikeFixerDetector → FillerWordDetector → CrossTalkDetector` — order matters for dependency resolution (`main.py`).
- **Pipeline always renders BOTH outputs** (host + guest) even for guest-only workflows to maintain paired alignment (`main.py`).
- **Host + Guest renders run in parallel** via `ThreadPoolExecutor(max_workers=2)` inside `render_project()`; each is an independent FFmpeg subprocess so there is zero sync risk. Falls back to sequential when only one output is requested (`io_/video_renderer.py`, `io_/video_renderer_twophase.py`).
- **`normalize_video_lengths()` pads only the SHORTER video** using stream-copy + tiny-tail; the longer video is returned as its ORIGINAL path (no re-encode, no intermediate file). Only one preflight output is written, and it uses the `_preflight` suffix (reserved separately from `_processed`) (`io_/media_preflight.py`).
- **Preflight tolerance is 10 ms**: duration deltas `< 0.01s` are treated as aligned and skip preflight entirely (`io_/media_preflight.py`).
- **Rendering with output==input uses temp file + atomic replace** via `os.replace()`; otherwise FFmpeg would read/write the same path (`io_/video_renderer.py`).
- **Two-phase render is enabled by default** (`two_phase_render_enabled: True` in `QUALITY_PRESETS`); it renders audio-first to a temp AAC file then smart-copies the video stream, bypassing a full video re-encode on the common path (`io_/video_renderer_twophase.py`).
- **`video_phase_strategy`** controls the fallback (non-two-phase) render path: `'auto'` (default), `'smart_copy'`, `'single_pass'`, or `'batched_gpu'`. `'batched_gpu'` auto-selects when segment count exceeds ~25. Strategies live in `io_/video_renderer_strategies.py`.
- **Chunked parallel rendering** is gated by `chunk_parallel_enabled`/`chunk_size` in `QUALITY_PRESETS`; when active, one FFmpeg process is spawned per chunk and results are concat-demuxed (`io_/video_renderer.py`).
- **Keyframe snap tolerance** (`keyframe_snap_tolerance_s`, default 0.1s) applies ONLY to `smart_copy`; cuts snap to the nearest keyframe within that window. Switch `video_phase_strategy` to `'single_pass'` to eliminate snapping entirely (`config.py`).
- **Cut fade** (`cut_fade_ms`, default 8ms) is an audio-only afade at every cut point to avoid clicks. `video_fade_on` (default False) toggles a separate xfade/acrossfade dissolve (`config.py`, `io_/video_renderer.py`).
- **Noise reduction is enabled by default** (`noise_reduction_enabled: True`); applied in-memory before detectors (analysis phase) AND as an `afftdn` render-time filter (output phase). Stationary mode by default (`noise_reduction_stationary: True`). Per-track strength via `noise_reduct_decrease_host` / `noise_reduct_decrease_guest`.
- **CPU cap uses a downward correction factor**: the effective cap sent to the Windows kernel is `cpu_limit_pct * cpu_rate_correction` (default 0.8) to compensate for FFmpeg burst overshoot. This is a SUBTRACTION, not an addition (`config.py`, `utils/cpu_job_object.py`).
- **FFmpeg subprocess stdout+stderr are merged** (`stderr=subprocess.STDOUT`) to avoid pipe-fill deadlocks on long runs; FFmpeg progress is throttled to 0.25s (`UPDATE_INTERVAL`) for GUI smoothness (`io_/video_renderer_progress.py`).
- **Large filter graphs are offloaded to a temp file** via `-filter_complex_script` to avoid WinError 206 ("command line too long") (`io_/video_renderer_progress.py`).
- **Frame-accurate cutting requires H.264/AAC**; changing codecs breaks non-keyframe cuts (`config.py`, `io_/video_renderer.py`).
- **LUFS uses `pyloudnorm` if installed**; missing triggers RMS fallback with warning (`analyzers/audio_level_analyzer.py`).
- **`STANDARD_LUFS` normalization applies loudnorm to BOTH host and guest** (identical params); `MATCH_HOST` applies a volume gain to guest only (host is the reference and gets no filter) (`processors/audio_normalizer.py`).
- **AssemblyAI normalizes spoken "uhm"/"uhh" to "uh"/"um"** in transcripts — matching both forms in `words_to_remove` is redundant but harmless (`config.py`).

## Architecture (Edit Flow)
- Detectors → results keyed by `detector.get_name()` → processors consume and build `EditManifest` (no media mutation) (`core/pipeline.py`, `processors/base_processor.py`).
- Pipeline passes accumulated `detection_results` to detectors that accept it; `SpikeFixerDetector` can run an extra FFmpeg analysis pass post-normalization for accuracy and depends on `AudioLevelDetector` results. Falls back to pre-normalization analysis with a warning if results or guest path are missing.
- `AudioNormalizer` consumes `detection_results['audio_level_detector']` (it no longer computes LUFS internally) — raises `ValueError` if the key is absent.
- `WordMuter` is the sole owner of per-track audio mute filters. `SegmentRemover` is the sole owner of `removal_segments` / `keep_segments`.
- **Processors registry** (`_PROCESSOR_REGISTRY` in `main.py`): `SegmentRemover`, `WordMuter`, `AudioDenoiserFilter`, `AudioNormalizer`, `SpikeFixer`. Adding a new processor requires both a registry entry AND a `PIPELINE_CONFIG['processors']` entry.
- **`processors/word_remover.py` was removed**; replaced by `processors/word_muter.py`. Do not recreate or reference `word_remover.py`.
- Rendering applies `host_filters`/`guest_filters`, then trims video AND audio using the SAME `keep_segments` to preserve sync (`io_/video_renderer.py`, `core/interfaces.py`).
- **Renderer module split** (each under the 600-line limit): `io_/video_renderer.py` is the main entry point; strategy logic in `io_/video_renderer_strategies.py`; two-phase render in `io_/video_renderer_twophase.py`; FFmpeg progress + filter-graph offloading in `io_/video_renderer_progress.py`.
- **`WORDS_TO_REMOVE`** in `config.py` controls filler-word targets (`words_to_remove`), per-speaker confidence thresholds (`confidence_required_host`, `confidence_required_guest`), per-word bonus (`confidence_bonus_per_word`), slur-gap inset (`filler_mute_inset_ms` + `filler_mute_gap_threshold_ms`), and mute window expansion (`filler_mute_offset_left_ms`, `filler_mute_offset_right_ms`).
- **Confidence formula** (key insight): a phrase is muted when `actual_confidence >= confidence_required - (word_count * confidence_bonus_per_word)`. Setting the threshold `> 1.0` is intentional — single-word fillers need near-perfect confidence, multi-word phrases earn bonus subtractions that let them through.
