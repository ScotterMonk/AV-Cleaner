# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Application overview
Automate "Cleaning" of synchronized dual-video recordings (host + guest):
- All relevant settings in config file.
- Users only control which PROCESSORS run; DETECTORS are enabled automatically behind the scenes based on processor requirements.
- Find average audio level (db) of both files. Normalize avg audio levels of guest video to fit host video audio level.
- Find spikes above y db in guest video and reduce them to y.
- Trimming silent pauses.
- Maintaining perfect sync and audio quality.
- Built with a plugin-based architecture for easy extension (e.g., later features such as AI-based filler word removal).

## Commands
1) Run GUI: `py app.py`
2) Run CLI (Click): `python main.py --host path/to/host.mp4 --guest path/to/guest.mp4`
3) Override normalization mode: `python main.py --host ... --guest ... --norm-mode MATCH_HOST|STANDARD_LUFS`

## Environment & Shell
1) **Prefer PowerShell**: This project is developed on Windows. Agents should assume a PowerShell environment (`pwsh`) for terminal commands.
2) **Avoid cmd.exe pitfalls**: Be aware that `cmd.exe` does not treat `;` as a command separator (use `&` or `&&` instead). If a command fails with "shell is treating ; as an argument", it likely ran in `cmd.exe`.
3) **VS Code Settings**: The workspace is configured to default to PowerShell (`.vscode/settings.json`).

## Project-specific gotchas
1) `ProcessingPipeline.execute()` always extracts audio to a temp stereo 44.1kHz WAV, then loads it fully into RAM via pydub; long videos can require hundreds of MB (`io/audio_extractor.py`).
2) Output filenames are derived via `path.replace(".mp4", "_processed.mp4")`; non-`.mp4` inputs won’t produce correct output names (`core/pipeline.py`).
3) Frame-accurate cutting assumes H.264/AAC output (config comment: libx264/aac allows cutting at non-keyframes); keep config consistent when changing codecs (`config.py`, `io/video_renderer.py`).
4) LUFS uses `pyloudnorm` if installed; otherwise it falls back to pydub RMS and logs a warning (`analyzers/audio_level_analyzer.py`).

## Architecture map (how edits are expressed)
1) Detectors produce results keyed by `detector.get_name()`; processors consume `detection_results` and build an `EditManifest` (no direct media mutation) (`core/pipeline.py`, `processors/base_processor.py`).
2) Rendering applies `EditManifest.host_filters`/`guest_filters` then trims BOTH audio and video using the SAME `keep_segments` to preserve sync (`io/video_renderer.py`, `core/interfaces.py`).
3) The CLI builds the pipeline from enabled processors, then auto-adds the required detectors (detectors are not user-configurable) (`main.py`, `config.py`).

## Code style conventions observed in-repo
1) Module logging uses `logger = get_logger(__name__)`; the CLI should call `setup_logger()` once to configure handlers (`utils/logger.py`, `main.py`).

## Folder/file structure
```
app/
    app.py
    main.py
    config.py
    AGENTS.md
    activate.ps1
    .gitignore
    .roomodes
    tests/
        test_imports.py
    core/
        __init__.py
        interfaces.py
        pipeline.py
    analyzers/
        audio_envelope.py
        audio_level_analyzer.py
    detectors/
        __init__.py
        base_detector.py
        cross_talk_detector.py
        filler_word_detector.py
        silence_detector.py
        spike_fixer_detector.py
    processors/
        __init__.py
        base_processor.py
        audio_fader.py
        spike_fixer.py
        audio_normalizer.py
        segment_remover.py
    io_/
        __init__.py
        audio_extractor.py
        video_renderer.py
    utils/
        logger.py
        time_helpers.py
    # build/diagnostic artifacts (generated)
    ._gui_compile_output.txt
    ._gui_import_output.txt
    ._gui_run_output.txt
    ._main_help.txt
    ._pip_ffmpeg_show.txt
    ._pip_install.txt
    ._pyaudioop_install.txt
    ._pyprocs.txt
    ._venv_diag.txt
```
