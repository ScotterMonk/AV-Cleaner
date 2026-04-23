# User Query — Sync Hardening

**Date**: 2026-04-22.
**Plan**: p_20260422_sync-hardening.

## User Query
Convert the provided [`plan.md`](plan.md) into an execution-ready architect plan for AV-Cleaner's sync-centric hardening work.

## Why (inferred from the provided plan content)
The intent is to prevent regressions where Host and Guest drift apart, or audio and video inside either processed file drift apart, as rendering and pipeline behavior continue to change. The user wants a principled hardening pass rather than another one-off fix, while preserving output quality, preserving or improving common-path speed, and avoiding premature config-surface churn.

## Scope
- In scope: sync invariant validation, original-timeline audio-filter staging, shared two-phase auto-routing, removal of chunk-parallel rendering, preflight verification hardening, targeted config and GUI cleanup, and sync-focused tests.
- Out of scope: replacing preflight with renderer-level `apad` or `tpad`, denoise-path unification, removing the two-phase kill switch, removing active CUDA or NVENC or CPU-throttle controls, cross-track canonical quantization, and detector-pipeline rewrites.

## Current-Code Adjustments Captured During Planning
- [`_afftdn_delay_s()`](io_/video_renderer_twophase.py:53) and the warm-up trim inside [`render_audio_phase()`](io_/video_renderer_twophase.py:63) are already landed.
- The temp audio intermediate in [`render_project_two_phase()`](io_/video_renderer_twophase.py:282) already uses `.m4a`.
- `video_phase_strategy` already defaults to `auto` in [`config.py`](config.py), but the GUI reload fallback still points to `smart_copy` in [`render_pipeline_toggles()`](ui/gui_settings_builders.py:215).
- The post-render validation recommendations in sections R1 and R6 of [`plan.md`](plan.md) overlap and are merged into one execution phase in the formal plan.

## Addendum Request — 2026-04-23
Make a plan to fix the currently surfaced issue list covering [`AudioNormalizer.process()`](processors/audio_normalizer.py:8), [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py:84), [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py:144), [`SettingsPage._save()`](ui/gui_settings_page.py:110), and the vendored AssemblyAI SDK annotation in [`venv/Lib/site-packages/assemblyai/transcriber.py`](venv/Lib/site-packages/assemblyai/transcriber.py:1282).

## Why (inferred from the addendum issue list)
The intent is to finish the in-flight sync-hardening work with a clean targeted analysis and regression surface, without weakening the new sync validation and without baking a brittle unmanaged site-packages patch into the default long-term solution.

## Scope Update
- In scope: typed manifest summary fields for normalization, pipeline unit-harness repair for post-render validation, routing-test metadata typing, Tk-variable typing in the settings UI, and an environment-safe resolution path for the unused AssemblyAI SDK warning.
- Out of scope: rewriting the REST-based filler-word detector around the SDK, broad renderer behavior changes beyond what the cited tests require, and unrelated GUI layout refactors.
