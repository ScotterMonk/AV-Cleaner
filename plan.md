# AV-Cleaner: Sync-Centric Hardening Plan

**Goal**: eliminate the class of bugs where host/guest streams drift out of sync, or where audio/video within a stream drift, whenever features are added, removed, or refactored.

**Constraints**:
- Do not reduce output quality.
- Keep processing speed at or above current levels on the common path.
- Keep config surface unless a key truly becomes dead in code, UI, and tests.
- Favor principled, modular solutions that match the current codebase.

**Priority invariants**:
1) **I1** — cross-track sync: processed host and guest remain aligned within practical tolerance `max(10 ms, 1 frame at each output's fps)`.
2) **I2** — within-track A/V sync: each processed file keeps audio/video duration mismatch below one frame and does not accumulate drift across cuts.
3) **I3** — original-timeline correctness: manifest ranges stay on the original source timeline, and any audio filter that references `t` is applied before trim/reset steps that redefine timestamps.

---

## 1) Current state
### 1.1) Pipeline flow
1) **Preflight length alignment** — `main.py::_run_process()` calls `io_/media_preflight.py::normalize_video_lengths()` before the pipeline.
    - If `abs(delta) < 10 ms`, the original input paths are reused.
    - Otherwise only the shorter file is padded and written as one `_preflight.mp4`; the longer file path is reused unchanged.
2) **Audio extraction to RAM** — `io_/audio_extractor.py::extract_audio()` loads each source as a pydub `AudioSegment`.
3) **Optional in-memory denoise for detector inputs** — `core/pipeline.py` gates this with `noise_reduction_host` and `noise_reduction_guest`.
4) **Detectors run in fixed order** — order is derived from enabled processors and currently resolves to:
    - `AudioLevelDetector`.
    - `SpikeFixerDetector`.
    - `FillerWordDetector`.
    - `CrossTalkDetector`.
5) **Processors build one shared `EditManifest`**.
    - `SegmentRemover` appends shared removal ranges and re-derives `keep_segments` from `host_audio.duration_seconds`.
    - `WordMuter` adds original-timeline `volume=0` filters with `enable=between(t,...)` and does not change the timeline.
    - `AudioDenoiserFilter`, `AudioNormalizer`, and `SpikeFixer` append render-time audio filters.
6) **Render entry point** — `io_/video_renderer.py::render_project()` selects encoder options once and then:
    - dispatches to `io_/video_renderer_twophase.py::render_project_two_phase()` when `two_phase_render_enabled` is true.
    - otherwise uses the non-two-phase combined filter-graph path, with optional chunk-parallel rendering when `chunk_parallel_enabled` is enabled and segment count exceeds `chunk_size`.
7) **Two-phase render**.
    - Audio phase applies audio filters, trims each kept segment, concatenates audio-only output, and compensates `afftdn` warm-up.
    - Video phase currently chooses strategy per track from that track's own codec and segment count.
    - Auto routing today is: non-`h264` -> `single_pass`, `<= 5` segments -> `smart_copy`, `<= 25` -> `single_pass`, `> 25` -> `batched_gpu`.
    - Host and guest are rendered in parallel and then muxed with `-shortest`.

### 1.2) Important current semantics
- `EditManifest.keep_segments` and `EditManifest.removal_segments` live on the original source timeline.
- `CrossTalkDetector` intentionally consumes filler-word mute windows during analysis, so a muted filler word may later be absorbed by a pause cut.
- `smart_copy`, `batched_gpu`, and chunk-parallel all rely on concat-copy seams.
- The GUI still exposes `two_phase_render_enabled`, `chunk_parallel_enabled`, `video_phase_strategy`, `keyframe_snap_tolerance_s`, `cuda_decode_enabled`, `cuda_require_support`, `cpu_rate_correction`, and `nvenc` settings.

---

## 2) Actual sync risks
1) The two-phase path still renders audio and video in separate FFmpeg processes, so correctness depends on consistent quantization, muxing, and tolerance handling.
2) Auto strategy is currently chosen per track inside `_render_track()`, so host and guest can take different route families in the same render call.
3) `smart_copy` is the highest-risk auto-selected path because it combines keyframe snapping, per-segment subprocesses, and concat-copy joins.
4) `batched_gpu` still joins independently encoded batches with concat-copy, so batch seams remain a real risk.
5) The legacy chunk-parallel path has the same seam class as `batched_gpu` and is still user-reachable through config and GUI.
6) Original-timeline mute filters are correct today only because `_build_filter_chain()` happens to apply all audio filters before any `atrim`; that contract is not encoded in data or validation.
7) The pipeline logs durations but does not fail fast when processed outputs drift.
8) Preflight may contribute seam risk, but replacing it inside this plan would also change manifest semantics and widen the refactor.
9) Detector-side denoise and render-side denoise can diverge, but fixing that safely requires parameter parity that the current render-time filter path does not yet have.

---

## 3) Corrected recommendations
### R1) Add tolerant sync validation.
**New file**: `core/sync_invariants.py`.
**Functions**:
- `assert_manifest_consistency(manifest, host_duration_s, guest_duration_s, tolerance_s=0.01) -> None`.
    - Assert `removal_segments` and `keep_segments` are sorted, non-overlapping, and bounded by the shared aligned source window within tolerance.
    - Parse any `enable=between(t,a,b)` expression and assert `0 <= a < b` and `b` stays within source duration tolerance.
    - Do not require mute windows to be contained inside final `keep_segments`; that would reject current self-healing behaviour.
- `probe_output_sync(path) -> dict`.
    - Return container duration, stream durations, and fps when available.
- `assert_output_pair_sync(host_out, guest_out, tolerance_s=None) -> None`.
    - Compare processed host vs guest duration using `max(0.01, 1 / fps)` style tolerance.
    - Compare within-file audio vs video duration using the same tolerance model.
    - Raise `SyncInvariantError` with measured deltas on failure.
**Wiring**:
- Call `assert_manifest_consistency()` at the end of Phase 2 in `core/pipeline.py`.
- Call `assert_output_pair_sync()` immediately after render completes in `core/pipeline.py`.

### R2) Encode original-timeline audio-filter staging.
**Scope**: `core/interfaces.py`, `processors/word_muter.py`, `processors/audio_denoiser_filter.py`, `processors/audio_normalizer.py`, `processors/spike_fixer.py`, `io_/video_renderer.py`.
- Extend `AudioFilter` with an explicit stage marker such as `original_timeline` vs `post_trim`.
- `WordMuter` must mark `volume` filters that use `enable=between(t,...)` as `original_timeline`.
- `AudioDenoiserFilter`, `AudioNormalizer`, and `SpikeFixer` should mark their filters as `post_trim`.
- Split `_build_filter_chain()` into:
    - one helper that applies original-timeline filters before any `atrim` or `asetpts`.
    - one helper that applies post-trim filters after each segment has been trimmed/reset.
- Add a render-time guard that validates the tag against the actual filter params and raises on mismatch.
**Result**:
- Word-mute timing stops depending on an implicit comment-level contract.

### R3) Choose one shared auto route for both tracks, but keep per-track FPS quantization.
**Scope**: `io_/video_renderer_twophase.py`.
- Compute one render decision at the top of `render_project_two_phase()` from the shared worst case:
    - If either source codec is not `h264`, route both tracks to `single_pass`.
    - Else if segment count is greater than 25, route both tracks to `batched_gpu`.
    - Else route both tracks to `single_pass`.
- Keep `probe_video_fps()` and `quantize_segments_to_frames()` inside `_render_track()` so each file quantizes to its own real frame grid.
- Do not introduce canonical `max(fps)` or `max(sample_rate)` quantization. That does not create a structural guarantee and can put one file on the wrong grid.
**Result**:
- Host and guest stop taking different auto-selected strategy families, while per-track frame math remains correct.

### R4) Remove `smart_copy` from auto, but do not pretend it is solved.
**Scope**: `io_/video_renderer_twophase.py`, `io_/video_renderer_strategies.py`, GUI settings.
- `auto` must never choose `smart_copy`.
- Keep `smart_copy` reachable only through an explicit manual override while the path remains in the codebase.
- Keep `keyframe_snap_tolerance_s` only while that explicit override exists.
- If the team wants to delete `smart_copy` later, do it in a follow-up cleanup after usage and test data confirm nothing relies on it.
**Result**:
- The highest-risk path is removed from normal operation without claiming the implementation problem has already vanished.

### R5) Delete chunk-parallel rendering, but keep the non-two-phase single-pass fallback.
**Scope**: `io_/video_renderer.py`, `config.py`, `ui/gui_settings_builders.py`, `ui/gui_settings_page.py`, tests.
- Remove `_render_as_chunks()` and the `chunk_parallel_enabled` / `chunk_size` branch from `render_project()`.
- Keep the non-two-phase single-pass combined filter-graph path as an explicit fallback while two-phase hardening lands.
- Keep `two_phase_render_enabled` for now. It is still a useful kill switch until post-render assertions prove the primary path is trustworthy.
**Config impact**:
- Remove `chunk_parallel_enabled`.
- Remove `chunk_size`.
- Do not remove `two_phase_render_enabled` in this plan.
**Result**:
- One known concat-seam path is eliminated without throwing away the safest fallback.

### R6) Add hard post-render sync validation.
**Scope**: `core/pipeline.py`.
- After `render_project()` returns, call `assert_output_pair_sync()`.
- Include the chosen render strategy family in the error message and logs.
- Add tests for:
    - a known out-of-sync pair.
    - a valid pair that passes within tolerance.
**Result**:
- Sync regressions fail in development and tests instead of reaching users first.

### R7) Keep preflight in this plan; harden it instead of replacing it.
**Scope**: `io_/media_preflight.py`, `tests/test_media_preflight_normalize_video_lengths.py`, `tests/test_main_preflight_normalize_lengths.py`, `tests/test_gui_result_line.py`.
- Keep `normalize_video_lengths()` as the current front-door alignment step.
- After padding, probe the returned outputs and assert that host/guest durations are aligned within the existing 10 ms tolerance.
- Preserve `_preflight.mp4` behaviour and the tests that intentionally cover preflight result paths.
- Move any renderer-level `apad` / `tpad` replacement experiment to a separate plan after measurement proves it is safer and not slower.
**Result**:
- The plan reduces sync risk without changing manifest semantics or widening the refactor unnecessarily.

### R8) Do not unify denoise paths in this plan.
**Scope**: none for this pass.
- Keep detector-side denoise and render-side `afftdn` as-is for now.
- If future unification is desired, first make `AudioDenoiserFilter` express the same stationary/aggressiveness controls as the analysis path, then compare detector outputs before removing `analyzers/audio_denoiser.py`.
**Result**:
- This plan stays focused on sync hardening instead of mixing in a larger signal-processing change.

### R9) Do only targeted config cleanup.
**Scope**: `config.py`, `ui/gui_settings_builders.py`, `ui/gui_settings_page.py`, tests.
- Remove only keys whose code truly disappears in this plan.
- Keep these active keys because the current code, GUI, or runtime still use them:
    - `two_phase_render_enabled`.
    - `video_phase_strategy`.
    - `keyframe_snap_tolerance_s` while manual `smart_copy` still exists.
    - `cuda_decode_enabled`.
    - `cuda_require_support`.
    - `cpu_rate_correction`.
    - `nvenc.codec`, `nvenc.preset`, `nvenc.rc`, `nvenc.cq`.
- Update GUI defaults so any fallback value for `video_phase_strategy` is `auto`, not `smart_copy`.
**Result**:
- The plan avoids breaking runtime and GUI behaviour with premature config deletion.

---

## 4) Implementation sequence
1) **Step 1 — `R1`**.
    - Add `core/sync_invariants.py`.
    - Wire `assert_manifest_consistency()` and `assert_output_pair_sync()` into `core/pipeline.py`.
    - Tests:
        - invalid overlapping keep/removal ranges fail.
        - invalid `between(t,...)` bounds fail.
        - valid self-healing mute plus pause-cut manifests still pass.
2) **Step 2 — `R2`**.
    - Add filter-stage metadata to `AudioFilter`.
    - Update processors to emit the correct stage.
    - Split `_build_filter_chain()` into original-timeline and post-trim audio phases.
    - Tests:
        - a `WordMuter` filter is applied before trim.
        - a mis-staged filter raises.
3) **Step 3 — `R3` plus `R4`**.
    - Move auto route selection to the top of `render_project_two_phase()`.
    - Remove `smart_copy` from auto.
    - Keep per-track FPS quantization where it already belongs.
    - Tests:
        - mixed-codec inputs force both tracks to `single_pass`.
        - small `h264` inputs use `single_pass` for both tracks under auto.
        - large `h264` inputs use `batched_gpu` for both tracks under auto.
        - `smart_copy` is only reachable via explicit override.
4) **Step 4 — `R6`**.
    - Add post-render sync assertion tests around representative fixture outputs.
    - Promote assertion failure to a hard pipeline error.
5) **Step 5 — `R5`**.
    - Remove chunk-parallel code and related tests.
    - Remove `chunk_parallel_enabled` and `chunk_size` from config and GUI.
    - Keep non-two-phase single-pass fallback and `two_phase_render_enabled`.
6) **Step 6 — `R7`**.
    - Add post-preflight verification and keep existing `_preflight` path semantics.
    - Update preflight tests to assert verification and logging.
7) **Step 7 — `R9`**.
    - Clean up only the config, UI, and test entries tied to code that was actually removed.
    - Update GUI strategy defaults from `smart_copy` to `auto`.

---

## 5) File-level impact summary
**New**:
- `core/sync_invariants.py` — `R1`.

**Modified**:
- `core/pipeline.py` — invariant wiring and post-render validation.
- `core/interfaces.py` — filter-stage metadata.
- `io_/video_renderer.py` — staged audio-filter application and chunk-parallel removal.
- `io_/video_renderer_twophase.py` — shared auto-route decision and `smart_copy` removal from auto.
- `io_/video_renderer_strategies.py` — retain `smart_copy` only as an explicit override path.
- `processors/word_muter.py` — mark original-timeline filters.
- `processors/audio_denoiser_filter.py` — mark post-trim filters.
- `processors/audio_normalizer.py` — mark post-trim filters.
- `processors/spike_fixer.py` — mark post-trim filters.
- `io_/media_preflight.py` — post-preflight verification.
- `config.py` — remove chunk-parallel keys only.
- `ui/gui_settings_builders.py` — remove chunk-parallel controls and fix strategy fallback default.
- `ui/gui_settings_page.py` — stop saving removed chunk-parallel keys and keep remaining active settings accurate.
- `tests/test_video_renderer_twophase.py` — auto-route expectations and sync assertions.
- `tests/test_video_renderer_batched_gpu.py` — shared-route expectations.
- `tests/test_media_preflight_normalize_video_lengths.py` — verification coverage.
- `tests/test_main_preflight_normalize_lengths.py` — preflight behaviour remains covered.
- `tests/test_gui_result_line.py` — keep preflight-path behaviour covered.

**Deleted**:
- `tests/test_chunk_rendering.py` — chunk-parallel path removed.
- Chunk-parallel helper code inside `io_/video_renderer.py` — chunk-parallel path removed.

---

## 6) Acceptance criteria
1) Running the full pipeline on representative fixtures produces outputs where `assert_output_pair_sync()` passes.
2) Under auto routing, both tracks always choose the same strategy family for a given render call.
3) Under auto routing, `smart_copy` is never selected.
4) If either source is non-`h264`, both tracks use `single_pass`.
5) If both sources are `h264` and segment count is greater than 25, both tracks use `batched_gpu` and still pass sync validation.
6) A manifest that contains valid filler-word mute windows later absorbed by pause cuts still passes manifest validation.
7) A mis-staged original-timeline filter raises before render.
8) No GUI control, config key, or code path for chunk-parallel rendering remains.
9) Preflight mismatched-duration fixtures still work, and any produced `_preflight.mp4` output passes post-preflight verification.
10) `pytest` is green after the refactor.

---

## 7) Risks and open questions
1) `batched_gpu` still ends with concat-copy seams. If post-render assertions fail on large-cut fixtures, the next move should be to fall back to `single_pass` for those cases rather than add speculative tail padding.
2) Preflight may still contribute small seam risk, but keeping it is safer than changing manifest semantics during this pass.
3) Manual `smart_copy` override remains risky until the path is either deleted or separately proven.
4) VFR inputs should remain supported, but each track must keep its own FPS probe and quantization.
5) Denoise-path divergence remains a correctness risk, but it is intentionally out of scope for this sync-hardening pass.

---

## 8) Non-goals
- Replacing preflight with renderer-level `apad` / `tpad` in this plan.
- Deleting `analyzers/audio_denoiser.py` in this plan.
- Removing `two_phase_render_enabled` in this plan.
- Hard-coding away active CUDA, NVENC, or CPU-throttle settings.
- Using canonical `max(fps)` or `max(sample_rate)` quantization across both tracks.
- Rewriting the detector pipeline.
