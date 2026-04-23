# Plan: Sync-Centric Hardening
**Short plan name**: sync-hardening.
**User query**: Convert the provided [`plan.md`](plan.md) into an execution-ready sync-hardening plan for AV-Cleaner.
**User query file**: [`p_20260422_sync-hardening-user.md`](.kilocode/docs/plans/p_20260422_sync-hardening-user.md).
**Log file**: [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
**Source material**: [`plan.md`](plan.md).
**Complexity**: Multi-Phase (Large).
**Autonomy level**: Medium.
**Testing type**: Use what is appropriate per task.
**Approval status**: Original plan approved for dispatcher handoff on 2026-04-22; 2026-04-23 addendum pending approval.

---

## Problem Summary
The current renderer and pipeline preserve several important sync guarantees, but the remaining correctness still depends on implicit contracts between original-timeline filter timing, frame quantization, mux tolerance, per-track route selection, and legacy seam-join paths. The hardening objective is to make sync correctness explicit and test-enforced so future changes cannot silently reintroduce Host-versus-Guest drift or within-file A/V drift.

During execution, a follow-on issue batch surfaced around dynamic manifest typing, unit-harness isolation after post-render validation landed, narrow test metadata typing, untyped Tk variable access, and an environment-scoped warning from an unused vendored AssemblyAI SDK file.

## Constraints
- Preserve output quality.
- Preserve or improve common-path speed.
- Keep the existing config surface unless keys become fully dead in code, GUI, and tests.
- Prefer modular changes that fit the current renderer and pipeline architecture.
- Do not widen the scope into denoise unification, detector rewrites, or replacing preflight semantics in this pass.
- Do not reintroduce a runtime dependency on the AssemblyAI SDK; the live filler-word path remains REST-based unless the user explicitly approves that architectural change.

## Architect Review Notes
1) The post-render validation recommendations in sections R1 and R6 of [`plan.md`](plan.md) overlap and are merged into one validation track in this formal plan.
2) [`video_phase_strategy`](config.py) already defaults to `auto` in [`config.py`](config.py), but the GUI reload fallback still defaults to `smart_copy` in [`render_pipeline_toggles()`](ui/gui_settings_builders.py:215).
3) [`_afftdn_delay_s()`](io_/video_renderer_twophase.py:53), the `afftdn` warm-up trim in [`render_audio_phase()`](io_/video_renderer_twophase.py:63), and the `.m4a` temp audio intermediate in [`render_project_two_phase()`](io_/video_renderer_twophase.py:282) are already landed, so they are treated as baseline rather than new work.
4) [`io_/video_renderer.py`](io_/video_renderer.py) already exceeds the 600-line standard, and [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py) is far beyond it, so touched work in those areas must extract or split rather than grow the oversized files.
5) Shared auto-route selection must preserve one-output render scenarios while guaranteeing one route family for normal paired renders.
6) [`AudioNormalizer.process()`](processors/audio_normalizer.py:8) still writes normalization summary data onto [`EditManifest`](core/interfaces.py:18) as undeclared dynamic attributes.
7) [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py:84) mocks [`render_project()`](io_/video_renderer.py) but not [`assert_output_pair_sync()`](core/sync_invariants.py:229), so the new validation hook reaches real `ffprobe` during unit execution.
8) The routing assertions in [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py:144) and the GUI settings saves in [`SettingsPage._save()`](ui/gui_settings_page.py:110) are failing static analysis because of narrow dict inference and untyped Tk variable stores rather than changed runtime intent.
9) The app code does not import the AssemblyAI SDK; [`FillerWordDetector.detect()`](detectors/filler_word_detector.py:55) uses REST calls through `requests`, so the warning in [`venv/Lib/site-packages/assemblyai/transcriber.py`](venv/Lib/site-packages/assemblyai/transcriber.py:1282) should be handled as workspace or environment hygiene unless the user explicitly wants a direct vendored hotfix.

## Solution Summary
1) Add a dedicated sync-invariants module that validates both manifests and rendered outputs with tolerant, fps-aware comparisons.
2) Encode original-timeline versus post-trim audio-filter staging directly in [`AudioFilter`](core/interfaces.py:8) and in the renderer structure instead of relying on ordering comments.
3) Compute one shared auto-routing family per two-phase render call, keep per-track fps quantization, remove `smart_copy` from auto, and retain manual `smart_copy` only as an explicit override.
4) Remove the dead chunk-parallel path, keep the non-two-phase single-pass fallback, and clean only the config and GUI surface that becomes truly dead.
5) Keep preflight semantics intact, but verify the padded pair immediately after preflight completes.
6) Add targeted tests in new focused modules so the touched test surface becomes easier to maintain and moves toward the 600-line standard.
7) Add one final hardening phase for typed manifest summary fields, targeted test-harness repair, routing and GUI type hygiene, and an environment-safe AssemblyAI warning resolution.

---

## Phase 1 — Sync Invariant Foundation
### Step 0 — Backup target files.
Backup target files to backups folder.
- [`core/pipeline.py`](core/pipeline.py).
- [`core/interfaces.py`](core/interfaces.py).
- New file [`core/sync_invariants.py`](core/sync_invariants.py).
- New file [`tests/test_sync_invariants.py`](tests/test_sync_invariants.py).

Task 1: Create the sync-invariant module.
Mode hint: /coder-sr.
Goal: Add one authoritative place for manifest validation, output probing, and output-pair sync assertions.
Acceptance criteria: A new module [`core/sync_invariants.py`](core/sync_invariants.py) exposes `SyncInvariantError`, `assert_manifest_consistency()`, `probe_output_sync()`, and `assert_output_pair_sync()` with tolerant bounds based on `max(0.01, 1 / fps)` behavior.
Files involved: [`core/sync_invariants.py`](core/sync_invariants.py).
Detailed actions: Action: Create [`core/sync_invariants.py`](core/sync_invariants.py) with tolerant validation helpers that parse `enable=between(t,...)`, assert sorted non-overlapping manifest ranges, allow self-healing mute windows to extend beyond final keep ranges, and probe rendered outputs for container duration, stream duration, and fps so later pipeline checks can fail with measured deltas. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Reuse existing probing patterns where practical instead of introducing a second media-probe abstraction tree.
Testing: Use what is appropriate per task — create focused pytest coverage for the new module.

Task 2: Wire manifest validation into the pipeline.
Mode hint: /coder-jr.
Goal: Fail fast when processors produce an invalid shared manifest.
Acceptance criteria: [`ProcessingPipeline.execute()`](core/pipeline.py:104) imports and calls `assert_manifest_consistency()` immediately after Phase 2 manifest construction and before Phase 3 rendering starts.
Files involved: [`core/pipeline.py`](core/pipeline.py), [`core/sync_invariants.py`](core/sync_invariants.py).
Detailed actions: Action: Update [`ProcessingPipeline.execute()`](core/pipeline.py:104) so the end of the manifest-building section validates the manifest against Host and Guest extracted durations before [`render_project()`](io_/video_renderer.py:702) is invoked, and log a success detail when the manifest passes. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Keep the pipeline behavior unchanged for valid manifests and do not alter detector or processor registration order.
Testing: Use what is appropriate per task — cover the pipeline wiring with lightweight mocked tests rather than real media renders.

Task 3: Add invariant unit tests.
Mode hint: /coder-jr.
Goal: Lock down the manifest and output validation contract before renderer changes land.
Acceptance criteria: New tests cover overlapping keep or removal ranges, invalid `between(t,...)` bounds, tolerated self-healing mute plus pause-cut manifests, valid within-file output tolerances, and failing cross-track mismatches.
Files involved: [`tests/test_sync_invariants.py`](tests/test_sync_invariants.py).
Detailed actions: Action: Create [`tests/test_sync_invariants.py`](tests/test_sync_invariants.py) with pytest cases that mock output-probe data and assert the new invariant helpers accept valid self-healing cases and reject invalid overlap, bounds, and duration-drift cases with useful error messages. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Keep the tests independent of real FFmpeg binaries and real media fixtures.
Testing: Use what is appropriate per task — run the new invariant test module directly during implementation.

---

## Phase 2 — Explicit Audio-Filter Staging
### Step 0 — Backup target files.
Backup target files to backups folder.
- [`core/interfaces.py`](core/interfaces.py).
- [`processors/word_muter.py`](processors/word_muter.py).
- [`processors/audio_denoiser_filter.py`](processors/audio_denoiser_filter.py).
- [`processors/audio_normalizer.py`](processors/audio_normalizer.py).
- [`processors/spike_fixer.py`](processors/spike_fixer.py).
- [`io_/video_renderer.py`](io_/video_renderer.py).
- New file [`io_/video_renderer_audio.py`](io_/video_renderer_audio.py).
- New file [`tests/test_video_renderer_audio_staging.py`](tests/test_video_renderer_audio_staging.py).

Task 4: Extend the audio-filter data model with stage metadata.
Mode hint: /coder-sr.
Goal: Represent original-timeline versus post-trim filter intent directly in the manifest.
Acceptance criteria: [`AudioFilter`](core/interfaces.py:8) carries a stage field, and [`add_host_filter()`](core/interfaces.py:63) plus [`add_guest_filter()`](core/interfaces.py:66) accept a backward-compatible stage argument.
Files involved: [`core/interfaces.py`](core/interfaces.py).
Detailed actions: Action: Update [`AudioFilter`](core/interfaces.py:8), [`add_host_filter()`](core/interfaces.py:63), and [`add_guest_filter()`](core/interfaces.py:66) so filters can declare `original_timeline` or `post_trim` without breaking untouched callers that rely on the existing helper API. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Preserve current manifest serialization expectations in existing tests by choosing a safe default and by updating helper construction rather than requiring direct dataclass calls everywhere.
Testing: Use what is appropriate per task — update the existing filter-producing unit tests that inspect manifest filter objects.

Task 5: Mark original-timeline word-mute filters explicitly.
Mode hint: /coder-jr.
Goal: Make filler-word mute timing independent of implicit renderer ordering.
Acceptance criteria: [`_word_mute_add()`](processors/word_muter.py:101) emits `volume` filters tagged as `original_timeline`, and word-muter tests assert the stage.
Files involved: [`processors/word_muter.py`](processors/word_muter.py), [`tests/test_word_removal.py`](tests/test_word_removal.py).
Detailed actions: Action: Update [`_word_mute_add()`](processors/word_muter.py:101) to pass `stage="original_timeline"` through [`add_host_filter()`](core/interfaces.py:63) and [`add_guest_filter()`](core/interfaces.py:66), then extend the word-muter tests that already inspect `volume` filter params so they also assert the stage contract. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not change mute-window math or the self-healing pause-cut behavior.
Testing: Use what is appropriate per task — keep tests unit-level and deterministic.

Task 6: Mark full-track render filters as post-trim.
Mode hint: /coder-jr.
Goal: Distinguish denoise, normalization, and limiter filters from original-timeline mute filters.
Acceptance criteria: [`AudioDenoiserFilter.process()`](processors/audio_denoiser_filter.py:9), [`AudioNormalizer.process()`](processors/audio_normalizer.py:8), and [`SpikeFixer.process()`](processors/spike_fixer.py:18) emit filters tagged `post_trim`, and the related processor tests assert the new metadata where they inspect manifest filters.
Files involved: [`processors/audio_denoiser_filter.py`](processors/audio_denoiser_filter.py), [`processors/audio_normalizer.py`](processors/audio_normalizer.py), [`processors/spike_fixer.py`](processors/spike_fixer.py), [`tests/test_audio_normalizer_detection.py`](tests/test_audio_normalizer_detection.py), [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py).
Detailed actions: Action: Update the three processor `process()` methods that append render-time filters so they emit `stage="post_trim"` through the manifest helper API, then refresh the existing processor tests that inspect filter objects to assert the new stage metadata. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not change detector-driven normalization or spike logic in this task.
Testing: Use what is appropriate per task — run the directly affected processor unit tests.

Task 7: Extract staged audio-chain helpers and guard renderer ordering.
Mode hint: /coder-sr.
Goal: Enforce filter staging in the renderer while reducing the size of the touched renderer file.
Acceptance criteria: [`_build_filter_chain()`](io_/video_renderer.py:275) delegates staged audio work to a new helper module, applies `original_timeline` filters before any `atrim` or `asetpts`, applies `post_trim` filters after segment reset, and raises on stage-versus-parameter mismatches.
Files involved: [`io_/video_renderer.py`](io_/video_renderer.py), [`io_/video_renderer_audio.py`](io_/video_renderer_audio.py).
Detailed actions: Action: Extract the audio-side logic from [`_build_filter_chain()`](io_/video_renderer.py:275) into a new helper module such as [`io_/video_renderer_audio.py`](io_/video_renderer_audio.py), then have [`_build_filter_chain()`](io_/video_renderer.py:275) call those helpers so `enable=between(t,...)` filters run pre-trim, full-track filters run post-trim, and mis-staged filters fail before FFmpeg execution. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Keep the combined concat behavior intact for A/V lockstep, and use the extraction to move the touched renderer surface toward the 600-line limit instead of adding more inline branching.
Testing: Use what is appropriate per task — compile mocked ffmpeg graphs and assert filter order in focused pytest cases.

Task 8: Add focused staging tests in a new renderer test module.
Mode hint: /coder-jr.
Goal: Cover staging order and guard behavior without growing the oversized two-phase test file.
Acceptance criteria: New tests assert original-timeline mute filters land before trim, post-trim filters land after reset, and mis-staged filters raise.
Files involved: [`tests/test_video_renderer_audio_staging.py`](tests/test_video_renderer_audio_staging.py), [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py).
Detailed actions: Action: Create [`tests/test_video_renderer_audio_staging.py`](tests/test_video_renderer_audio_staging.py) for the new staging-order cases and move or trim any overlapping touched cases out of [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py) so the active renderer test surface stops growing in the oversized legacy file. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Prefer migrating touched cases into new files over adding more assertions into the legacy mega-test module.
Testing: Use what is appropriate per task — run the new staging test module directly.

---

## Phase 3 — Shared Auto-Routing and Post-Render Validation
### Step 0 — Backup target files.
Backup target files to backups folder.
- [`core/pipeline.py`](core/pipeline.py).
- [`io_/video_renderer.py`](io_/video_renderer.py).
- [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py).
- [`tests/test_video_renderer_batched_gpu.py`](tests/test_video_renderer_batched_gpu.py).
- New file [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py).

Task 9: Add shared auto-route selection for the whole two-phase render call.
Mode hint: /coder-sr.
Goal: Ensure both tracks take the same auto-selected strategy family for a paired render.
Acceptance criteria: Under `auto`, non-`h264` inputs force both tracks to `single_pass`, segment counts above 25 force both tracks to `batched_gpu`, smaller `h264` cases use `single_pass`, and one-output calls still render successfully.
Files involved: [`render_project_two_phase()`](io_/video_renderer_twophase.py:282), [`quantize_segments_to_frames()`](io_/video_renderer_twophase.py:271).
Detailed actions: Action: Move the `auto` route decision to the top of [`render_project_two_phase()`](io_/video_renderer_twophase.py:282), compute one shared strategy family from both source codecs and shared segment count, store lightweight render metadata for later logging or validation, and keep per-track fps probing plus [`quantize_segments_to_frames()`](io_/video_renderer_twophase.py:271) inside each rendered track so each file still snaps to its own frame grid. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not introduce cross-track canonical fps or sample-rate quantization.
Testing: Use what is appropriate per task — update routing tests for paired and one-output scenarios.

Task 10: Remove `smart_copy` from auto but keep manual override.
Mode hint: /coder-jr.
Goal: Keep the riskiest seam path out of normal operation without deleting the explicit override path yet.
Acceptance criteria: `auto` never chooses `smart_copy`, manual `video_phase_strategy="smart_copy"` still reaches [`render_video_smart_copy()`](io_/video_renderer_twophase.py:238), and logs distinguish auto routing from manual override.
Files involved: [`render_project_two_phase()`](io_/video_renderer_twophase.py:282), [`render_video_smart_copy()`](io_/video_renderer_twophase.py:238).
Detailed actions: Action: Update the strategy-selection branch inside [`render_project_two_phase()`](io_/video_renderer_twophase.py:282) so `smart_copy` is no longer emitted by `auto`, while preserving the explicit `smart_copy` branch and the continued use of `keyframe_snap_tolerance_s` only when that override path is chosen. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not delete the `smart_copy` implementation in this plan.
Testing: Use what is appropriate per task — add explicit auto-versus-manual override assertions.

Task 11: Wire hard post-render sync validation using renderer metadata.
Mode hint: /coder-sr.
Goal: Convert rendered-output drift into a hard pipeline failure with actionable diagnostics.
Acceptance criteria: [`ProcessingPipeline.execute()`](core/pipeline.py:104) calls `assert_output_pair_sync()` after [`render_project()`](io_/video_renderer.py:702) returns, and failure messages include measured deltas plus the chosen strategy family.
Files involved: [`core/pipeline.py`](core/pipeline.py), [`io_/video_renderer.py`](io_/video_renderer.py), [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py), [`core/sync_invariants.py`](core/sync_invariants.py).
Detailed actions: Action: Thread a minimal render-metadata result back from [`render_project()`](io_/video_renderer.py:702) and [`render_project_two_phase()`](io_/video_renderer_twophase.py:282) so [`ProcessingPipeline.execute()`](core/pipeline.py:104) can call `assert_output_pair_sync()` immediately after rendering and raise `SyncInvariantError` with both the measured drift values and the route family that produced them. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Keep the public behavior of the full pipeline intact apart from the new failure path when outputs drift beyond tolerance.
Testing: Use what is appropriate per task — add mocked pass and fail cases for the new post-render validation path.

Task 12: Add focused routing and sync-validation tests.
Mode hint: /coder-jr.
Goal: Lock in the new auto-routing rules and the new hard validation behavior.
Acceptance criteria: New tests cover mixed-codec `single_pass`, small `h264` `single_pass`, large `h264` `batched_gpu`, manual `smart_copy` override, and output validation pass or fail behavior.
Files involved: [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py), [`tests/test_video_renderer_batched_gpu.py`](tests/test_video_renderer_batched_gpu.py), [`tests/test_sync_invariants.py`](tests/test_sync_invariants.py), [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py).
Detailed actions: Action: Create [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py) for the shared-route expectations, update [`tests/test_video_renderer_batched_gpu.py`](tests/test_video_renderer_batched_gpu.py) for paired-route coverage, and remove or relocate the old default-`smart_copy` expectations currently living in [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py). **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Prefer moving touched cases out of the oversized legacy test file instead of adding more routing assertions there.
Testing: Use what is appropriate per task — run the focused routing modules before the full suite.

---

## Phase 4 — Chunk-Parallel Removal, Preflight Hardening, and Surface Cleanup
### Step 0 — Backup target files.
Backup target files to backups folder.
- [`io_/video_renderer.py`](io_/video_renderer.py).
- [`config.py`](config.py).
- [`ui/gui_settings_builders.py`](ui/gui_settings_builders.py).
- [`ui/gui_settings_page.py`](ui/gui_settings_page.py).
- [`io_/media_preflight.py`](io_/media_preflight.py).
- [`tests/test_chunk_rendering.py`](tests/test_chunk_rendering.py).
- [`tests/test_media_preflight_normalize_video_lengths.py`](tests/test_media_preflight_normalize_video_lengths.py).
- [`tests/test_main_preflight_normalize_lengths.py`](tests/test_main_preflight_normalize_lengths.py).
- [`tests/test_gui_result_line.py`](tests/test_gui_result_line.py).
- [`tests/test_gui_settings_page.py`](tests/test_gui_settings_page.py).

Task 13: Remove the chunk-parallel renderer path and keep the non-two-phase fallback.
Mode hint: /coder-sr.
Goal: Eliminate one known concat-seam path while preserving the explicit single-pass fallback.
Acceptance criteria: [`render_project()`](io_/video_renderer.py:702) no longer branches on `chunk_parallel_enabled`, the dead chunk helpers are removed, the non-two-phase combined-filter path still works, and the touched renderer surface complies with the 600-line rule.
Files involved: [`io_/video_renderer.py`](io_/video_renderer.py).
Detailed actions: Action: Delete the chunk-activation logic and the dead helper code rooted in [`render_project()`](io_/video_renderer.py:702), remove or extract [`partition_segments()`](io_/video_renderer.py:552) plus [`_render_as_chunks()`](io_/video_renderer.py:589), and use the deletion or extraction to bring the actively edited renderer file back under the line-count ceiling while preserving the current non-two-phase single-pass path. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not remove [`two_phase_render_enabled`](config.py) in this plan.
Testing: Use what is appropriate per task — update renderer dispatch tests to prove the single-pass fallback still executes.

Task 14: Remove only dead chunk-parallel config and GUI surface.
Mode hint: /coder-jr.
Goal: Clean up the config surface without disturbing still-live sync controls.
Acceptance criteria: `chunk_parallel_enabled` and `chunk_size` are removed from [`config.py`](config.py), [`build_pipeline_form()`](ui/gui_settings_builders.py:117) and [`render_pipeline_toggles()`](ui/gui_settings_builders.py:215) stop exposing them, [`SettingsPage._save()`](ui/gui_settings_page.py:110) stops persisting them, and the GUI fallback for `video_phase_strategy` defaults to `auto` instead of `smart_copy`.
Files involved: [`config.py`](config.py), [`ui/gui_settings_builders.py`](ui/gui_settings_builders.py), [`ui/gui_settings_page.py`](ui/gui_settings_page.py), [`tests/test_gui_settings_page.py`](tests/test_gui_settings_page.py), [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py).
Detailed actions: Action: Delete the dead chunk-parallel settings from config and GUI builders, change the reload fallback inside [`render_pipeline_toggles()`](ui/gui_settings_builders.py:215) from `smart_copy` to `auto`, and update the affected GUI settings tests so only truly dead keys disappear. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Keep `two_phase_render_enabled`, `video_phase_strategy`, `keyframe_snap_tolerance_s`, CUDA, NVENC, and CPU-throttle settings active.
Testing: Use what is appropriate per task — run the GUI settings tests touched by the removed fields.

Task 15: Add post-preflight pair verification.
Mode hint: /coder-jr.
Goal: Keep the current preflight semantics but assert that the padded pair actually aligns.
Acceptance criteria: [`normalize_video_lengths()`](io_/media_preflight.py:209) probes the returned host and guest paths after padding and raises if the pair still exceeds the existing 10 ms tolerance.
Files involved: [`io_/media_preflight.py`](io_/media_preflight.py), [`core/sync_invariants.py`](core/sync_invariants.py).
Detailed actions: Action: Update [`normalize_video_lengths()`](io_/media_preflight.py:209) to probe the returned pair after `_video_pad_efficient` completes, verify the durations are aligned within the existing preflight tolerance, and emit a detail log that the verification passed. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Preserve `_preflight.mp4` naming and the current shorter-file-only write behavior.
Testing: Use what is appropriate per task — extend the existing preflight tests instead of introducing redundant coverage.

Task 16: Update and prune the affected tests for chunk removal and preflight hardening.
Mode hint: /coder-jr.
Goal: Remove dead chunk tests and refresh preflight and GUI expectations around the surviving behavior.
Acceptance criteria: [`tests/test_chunk_rendering.py`](tests/test_chunk_rendering.py) is deleted, the preflight tests assert verification behavior, and GUI or result-line tests still cover `_preflight` output-path semantics.
Files involved: [`tests/test_chunk_rendering.py`](tests/test_chunk_rendering.py), [`tests/test_media_preflight_normalize_video_lengths.py`](tests/test_media_preflight_normalize_video_lengths.py), [`tests/test_main_preflight_normalize_lengths.py`](tests/test_main_preflight_normalize_lengths.py), [`tests/test_gui_result_line.py`](tests/test_gui_result_line.py).
Detailed actions: Action: Delete [`tests/test_chunk_rendering.py`](tests/test_chunk_rendering.py), update the preflight-focused tests to assert the new verification path, and preserve the `_preflight` result-path expectations already covered by the GUI-facing tests. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not remove `_preflight` path coverage from the test suite.
Testing: Use what is appropriate per task — run the touched preflight and GUI-related test modules.

---

## Phase 5 — Type-Safety, Harness Repair, and Environment Hygiene
### Step 0 — Backup target files.
Backup target files to backups folder.
- [`core/interfaces.py`](core/interfaces.py).
- [`processors/audio_normalizer.py`](processors/audio_normalizer.py).
- [`tests/test_audio_normalizer_detection.py`](tests/test_audio_normalizer_detection.py).
- [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py).
- [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py).
- [`ui/gui_settings_page.py`](ui/gui_settings_page.py).
- [`ui/gui_settings_builders.py`](ui/gui_settings_builders.py).
- [`pyrightconfig.json`](pyrightconfig.json).

Task 17: Promote audio-normalizer summary fields into typed manifest state.
Mode hint: /coder-jr.
Goal: Remove dynamic manifest attributes so summary logging and tests share one typed contract.
Acceptance criteria: [`EditManifest`](core/interfaces.py:18) declares optional normalization summary fields, [`AudioNormalizer.process()`](processors/audio_normalizer.py:8) writes them without creating undeclared attributes, and [`tests/test_audio_normalizer_detection.py`](tests/test_audio_normalizer_detection.py:11) asserts `None` or a float value instead of relying on `hasattr`.
Files involved: [`core/interfaces.py`](core/interfaces.py), [`processors/audio_normalizer.py`](processors/audio_normalizer.py), [`tests/test_audio_normalizer_detection.py`](tests/test_audio_normalizer_detection.py).
Detailed actions: Action: Extend the [`EditManifest`](core/interfaces.py:18) dataclass with typed optional `guest_audio_gain_db_applied` and `guest_audio_gain_db_estimate` fields, keep the writes in [`AudioNormalizer.process()`](processors/audio_normalizer.py:52) and [`AudioNormalizer.process()`](processors/audio_normalizer.py:72) aligned to those fields, and update the normalization tests so the inactive field is asserted as `None` instead of absent. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not change MATCH_HOST or STANDARD_LUFS math, filter parameters, or stage tags.
Testing: Use what is appropriate per task — run the normalization pytest module and verify the cited issue lines clear.

Task 18: Repair normalize-plus-spike pipeline tests for post-render validation.
Mode hint: /coder-jr.
Goal: Keep the targeted pipeline tests isolated from real `ffprobe` while preserving the new sync-validation production behavior.
Acceptance criteria: [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py:84) stubs post-render sync validation the same way [`tests/test_pipeline_manifest_validation.py`](tests/test_pipeline_manifest_validation.py:62) does, the captured manifest is narrowed before filter assertions, and the normalize-plus-spike tests pass again.
Files involved: [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py), [`tests/test_pipeline_manifest_validation.py`](tests/test_pipeline_manifest_validation.py).
Detailed actions: Action: Update the capture helper and/or test bodies in [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py:71) so [`ProcessingPipeline.execute()`](core/pipeline.py:105) no longer reaches real [`assert_output_pair_sync()`](core/sync_invariants.py:229) during this unit harness, while preserving the existing filter-order assertions at [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py:119) through [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py:172). **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not weaken the production sync-validation call in [`ProcessingPipeline.execute()`](core/pipeline.py:264).
Testing: Use what is appropriate per task — rerun the normalize-plus-spike pytest module after the harness fix.

Task 19: Type the two-phase routing metadata assertions.
Mode hint: /coder-jr.
Goal: Make the routing tests reflect the actual metadata shape without narrow-literal dict typing failures.
Acceptance criteria: [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py:144) reads `_two_phase_render_metadata` through a typed helper or explicit narrowing so the assertions at [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py:175), [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py:239), [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py:268), [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py:297), and [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py:319) remain behaviorally identical but are static-analysis clean.
Files involved: [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py).
Detailed actions: Action: Introduce a local typed metadata extractor beside [`_patch_twophase_routing_dependencies()`](tests/test_video_renderer_twophase_routing.py:41) and route the affected assertions through it instead of indexing directly into a narrowly inferred config literal. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not relax the metadata contract or remove the current routing expectations.
Testing: Use what is appropriate per task — run the focused routing pytest module and the matching targeted analysis check.

Task 20: Add explicit Tk variable typing to settings save and reload paths.
Mode hint: /coder-sr.
Goal: Stop GUI settings code from leaking unknown or union Tk variable types into `.get().strip()` and checkbox iteration.
Acceptance criteria: [`SettingsPage`](ui/gui_settings_page.py:17) declares concrete types for `_vars`, `_pipe_vars`, `_word_vars`, `_qual_vars`, `_bool_vars`, `_norm_mode`, `_enc_mode`, and `_enc_quality`; [`SettingsPage._scan_default_video_player()`](ui/gui_settings_page.py:67) and [`SettingsPage._save()`](ui/gui_settings_page.py:110) use typed string-coercion helpers so the cited GUI issues clear without changing saved config data.
Files involved: [`ui/gui_settings_page.py`](ui/gui_settings_page.py), [`ui/gui_settings_builders.py`](ui/gui_settings_builders.py), [`tests/test_gui_settings_page.py`](tests/test_gui_settings_page.py).
Detailed actions: Action: Add shared type aliases and string-coercion helpers around the Tk variable dictionaries built in [`build_gui_form()`](ui/gui_settings_builders.py:21) and [`build_pipeline_form()`](ui/gui_settings_builders.py:117), then use them in [`SettingsPage._scan_default_video_player()`](ui/gui_settings_page.py:67) and [`SettingsPage._save()`](ui/gui_settings_page.py:110) instead of repeated untyped `.get().strip()` calls. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not change config key names, default fallback values, or widget layout behavior.
Testing: Use what is appropriate per task — run the GUI settings pytest module and the matching targeted analysis check.

Task 21: Resolve the vendored AssemblyAI SDK warning at the environment boundary.
Mode hint: /coder-sr.
Goal: Remove the stale `assemblyai` site-packages warning without committing the project to an unmanaged in-venv patch if a repo-level fix is sufficient.
Acceptance criteria: One durable path is implemented and documented — prefer tightening the workspace or analysis surface around the unused SDK while keeping the live filler-word flow in [`FillerWordDetector.detect()`](detectors/filler_word_detector.py:55) REST-based, and only patch [`venv/Lib/site-packages/assemblyai/transcriber.py`](venv/Lib/site-packages/assemblyai/transcriber.py:1282) directly if the user explicitly approves that environment-specific hotfix.
Files involved: Likely [`pyrightconfig.json`](pyrightconfig.json), relevant workspace-analysis configuration, and only if explicitly approved the vendored AssemblyAI file.
Detailed actions: Action: First verify the repo has no live `assemblyai` imports beyond the vendored environment surface, then implement the least brittle fix that prevents the warning at [`venv/Lib/site-packages/assemblyai/transcriber.py`](venv/Lib/site-packages/assemblyai/transcriber.py:1282) from blocking project work, documenting any environment-specific step if a direct site-packages patch is truly required. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not add a new runtime dependency on the AssemblyAI SDK or rewrite the REST detector around it.
Testing: Use what is appropriate per task — rerun the touched analysis check on the cited file list and confirm the warning is cleared or intentionally excluded by configuration.

---

## Phase 6 — Final Regression, Refactor Pass, and Completion
### Step 0 — Backup target files.
Backup target files to backups folder.
- Any markdown or test file touched during the final cleanup pass.

Task 22: Perform the explicit refactor pass on touched oversized files.
Mode hint: /coder-sr.
Goal: Ensure the implementation finishes cleaner than it started instead of leaving new logic embedded in oversized files.
Acceptance criteria: Any touched logic file is at or below 600 lines, and any touched oversized test logic moved during this plan lives in smaller focused modules.
Files involved: Likely [`io_/video_renderer.py`](io_/video_renderer.py), [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py), plus any new focused helper or test files created earlier.
Detailed actions: Action: Before final verification, review the touched renderer and test files, extract any remaining newly added logic that still lives in oversized files into focused modules, and update imports plus tests so the final state complies with the project modularity rule. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not perform opportunistic unrelated refactors outside the sync-hardening footprint.
Testing: Use what is appropriate per task — rerun the directly affected focused tests after each extraction.

**Continue here**

Task 23: Run the targeted sync-hardening regression and analysis sweep.
Mode hint: /tasky.
Goal: Verify the newly added invariant, routing, staging, preflight, GUI, and type-hygiene fixes before the full suite.
Acceptance criteria: All newly added or modified focused tests pass, and the touched issue-bearing files return a clean targeted analysis pass before the final full-suite run begins.
Files involved: [`tests/test_sync_invariants.py`](tests/test_sync_invariants.py), [`tests/test_video_renderer_audio_staging.py`](tests/test_video_renderer_audio_staging.py), [`tests/test_video_renderer_twophase_routing.py`](tests/test_video_renderer_twophase_routing.py), [`tests/test_audio_normalizer_detection.py`](tests/test_audio_normalizer_detection.py), [`tests/test_pipeline_normalize_spike.py`](tests/test_pipeline_normalize_spike.py), [`tests/test_gui_settings_page.py`](tests/test_gui_settings_page.py), plus the touched analysis-config files.
Detailed actions: Action: Run the focused pytest modules added or changed by this plan first, rerun the targeted analysis or type-check pass against the cited issue files, fix any failures caused by the sync-hardening refactor, and keep the fixes inside the approved scope. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not skip failing focused tests and do not mask failures by weakening assertions without architectural justification.
Testing: Use what is appropriate per task — focused pytest plus the matching targeted analysis check.

Task 24: Run the full regression suite and close out the plan execution.
Mode hint: /tasky.
Goal: Confirm the refactor is globally green and finalize execution logging.
Acceptance criteria: `pytest` passes, the targeted issue list is resolved, sync-hardening acceptance criteria are satisfied, and the log records the final completion state with no open blockers.
Files involved: Whole project test suite and [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Detailed actions: Action: Run the full pytest suite from the project root, resolve any remaining regressions introduced by the sync-hardening work, and update the plan log with the final execution summary once all phases are complete. **Log progress** to [`p_20260422_sync-hardening-log.md`](.kilocode/docs/plans/p_20260422_sync-hardening-log.md).
Constraints: Do not mark the plan complete while any failing test remains.
Testing: Use what is appropriate per task — full pytest.

---

## Acceptance Criteria
1) Representative outputs pass [`assert_output_pair_sync()`](core/sync_invariants.py:1) within the plan tolerance model.
2) Under `auto`, Host and Guest always take the same strategy family for a paired render.
3) Under `auto`, `smart_copy` is never selected.
4) Under manual override, `smart_copy` remains reachable and continues using [`keyframe_snap_tolerance_s`](config.py).
5) Invalid manifests fail before rendering, and invalid output pairs fail immediately after rendering.
6) Original-timeline mute filters no longer rely on implicit ordering inside [`_build_filter_chain()`](io_/video_renderer.py:275).
7) No code path, config key, or GUI control for chunk-parallel rendering remains.
8) Preflight mismatched-duration cases still produce correct `_preflight` behavior and now verify the returned pair.
9) The touched implementation moves toward the 600-line standard instead of pushing oversized files further out of bounds.
10) [`EditManifest`](core/interfaces.py:18) owns the normalization summary fields instead of relying on dynamic attribute writes from [`AudioNormalizer.process()`](processors/audio_normalizer.py:8).
11) The normalize-plus-spike, routing, and GUI-settings issue files are clean in the targeted analysis pass that originally surfaced the cited problems.
12) The AssemblyAI SDK warning is resolved through config or environment hygiene unless the user explicitly approves a direct vendored hotfix path.
13) The full pytest suite is green at the end of execution.

## Risks and Follow-up Boundaries
1) [`render_video_batched_gpu()`](io_/video_renderer_strategies.py:310) still ends in concat-copy seams, so if post-render assertions fail on large-cut fixtures the next move should be to route those cases down `single_pass`, not to add speculative padding tricks.
2) Manual `smart_copy` remains risky until it is separately proven or deleted.
3) Preflight may still contribute small seam risk, but preserving its semantics is safer than widening this refactor.
4) Denoise-path divergence remains out of scope for this pass and should not be mixed into execution unless a blocker proves otherwise.
