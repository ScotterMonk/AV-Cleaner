# Plan: video-crossfade

**Short plan name**: video-crossfade
**Log file**: `p_20260331_video-crossfade-log.md`
**User query file**: `p_20260331_video-crossfade-user.md`
**Complexity**: One Phase (Small/Med)
**Autonomy**: High
**Testing type**: Use what is appropriate per task

---

## Problem Summary

Every cut point in the output video is currently a hard splice — the last frame of one segment is immediately followed by the first frame of the next. The user wants a true **crossfade/dissolve**: the final frames of the outgoing segment blend visually into the opening frames of the incoming segment. This must apply **simultaneously** to both the host and guest video tracks. Duration is configurable in [`config.py`](config.py) as a frame count. A second config key enables/disables the feature entirely.

---

## Solution Summary

Use FFmpeg's `xfade` video filter chained between consecutive video segments, and `acrossfade` audio filter at audio boundaries, to replace the current hard-concat approach when the feature is enabled. Two new config keys are added to `QUALITY_PRESETS`. When `smart_copy` strategy is selected and the fade is on, the strategy is automatically downgraded to `single_pass` (stream-copy segments cannot be filtered).

---

## Phase 1 — Video Crossfade/Dissolve at Cut Points

### Step 0 — Backup target files
Backup the following files to the `backups folder` before any edits:
- [`config.py`](config.py)
- [`io_/video_renderer.py`](io_/video_renderer.py)
- [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py)
- [`io_/video_renderer_strategies.py`](io_/video_renderer_strategies.py)

### Step 1 — Add config keys to `config.py`

In [`config.py`](config.py), inside `QUALITY_PRESETS['PODCAST_HIGH_QUALITY']`, add two new keys near the `cut_fade_ms` entry:

```
# Whether to apply a true crossfade/dissolve at video cut points.
# When True, consecutive video segments are blended across `video_fade_duration_frames`
# frames instead of hard-spliced. Applied to both host and guest tracks.
'video_fade_on': False,

# Number of video frames used for the crossfade dissolve at each cut point.
# At 30 fps, 4 frames = ~133 ms. At 60 fps, 4 frames = ~67 ms.
# Has no effect when video_fade_on is False.
'video_fade_duration_frames': 4,
```

### Step 2 — Add `_build_xfade_chain()` helper to `io_/video_renderer.py`

Add a new function `_build_xfade_chain(segments_v, segments_a, fade_s)` in [`io_/video_renderer.py`](io_/video_renderer.py) that:

- Takes the list of per-segment video streams, per-segment audio streams, and fade duration in seconds.
- Chains `xfade` filters between consecutive video segment pairs:
  - `transition='fade'`
  - `duration=fade_s`
  - `offset` = sum of all preceding segment durations minus the accumulated fade overlaps consumed by prior transitions. Each prior transition "eats" `fade_s` from the output timeline, so: `offset[i] = sum(durations[0..i-1]) - (i * fade_s)` for the i-th boundary (0-indexed boundaries).
- Chains `acrossfade` filters between consecutive audio segment pairs:
  - `d=fade_s` (duration)
  - `c1=tri`, `c2=tri` (triangular crossfade curve — sounds natural for speech)
- Returns `(v_out, a_out)` — the final chained output streams.

**Note on `xfade` offset math**:
- Segment 0 has duration `d0`, segment 1 has duration `d1`, etc.
- First transition starts at offset = `d0 - fade_s` (the fade begins `fade_s` before the end of segment 0).
- Second transition starts at offset = `(d0 - fade_s) + (d1 - fade_s)` = `d0 + d1 - 2*fade_s`, etc.
- General formula: `offset[i] = sum(d[0]..d[i]) - (i+1)*fade_s` for i = 0..N-2 (0-indexed).

### Step 3 — Modify `_build_filter_chain()` in `io_/video_renderer.py`

In [`_build_filter_chain()`](io_/video_renderer.py:267), add a `cut_fade_frames` (or `video_fade_s`) parameter alongside `cut_fade_s`.

After the segment loop (lines 340–353) that builds `segments_v` and `segments_a`:

- **If `video_fade_on` and `len(segments_v) > 1`**: call `_build_xfade_chain(segments_v, segments_a, video_fade_s)` to get `(v, a)` — **skip the existing `ffmpeg.concat()` call**.
- **Else**: keep the existing `ffmpeg.concat(*interleaved, v=1, a=1)` path unchanged.

The `video_fade_s` value is derived from `video_fade_duration_frames / fps`. The FPS must be probed from the input file (use existing [`probe_ffmpeg_capabilities()`](io_/video_renderer.py:373) infrastructure or a direct `ffprobe` call via [`io_/media_probe.py`](io_/media_probe.py)).

### Step 4 — Thread `video_fade_on` / `video_fade_s` through render call sites

Update all callers of `_build_filter_chain()` to pass the two new parameters:

- [`render_video_single_pass()`](io_/video_renderer_twophase.py:135) — reads from `cfg.get("video_fade_on", False)` and `cfg.get("video_fade_duration_frames", 4)`, probes FPS, computes `video_fade_s`.
- [`render_video_batched_gpu()`](io_/video_renderer_strategies.py:308) — same; passes through to per-batch `_build_filter_chain()` calls.
- [`render_project()`](io_/video_renderer.py:695) / the chunk-parallel path — reads from config, passes `video_fade_s` to each chunk's `_build_filter_chain()` call.

### Step 5 — `smart_copy` strategy gating

In the strategy-selection logic inside [`render_project()`](io_/video_renderer.py:695) (or wherever `video_phase_strategy` is resolved to `smart_copy`):

- If `cfg.get("video_fade_on", False)` is `True` and the resolved strategy is `smart_copy`:
  - Log a warning: `"video_fade_on=True is incompatible with smart_copy; downgrading to single_pass"`.
  - Override strategy to `single_pass`.

This keeps the smart_copy path clean (no filter-graph surgery needed).

### Step 6 — Add `_apply_cut_fades()` guard

When `video_fade_on=True`, the audio boundaries are already handled by `acrossfade` inside `_build_xfade_chain()`. Ensure `_apply_cut_fades()` is **not** double-applied — either skip it when `video_fade_on=True` or confirm it is called only from the non-xfade path.

### Step 7 — Tests

- Add a unit test verifying `_build_xfade_chain()` xfade offset calculations are correct for 2, 3, and N segments with known durations.
- Add a unit test verifying that when `video_fade_on=True` and `video_phase_strategy='smart_copy'`, the resolved strategy is downgraded to `single_pass`.
- Add an integration-level test (terminal command / subprocess render) to visually confirm output, OR rely on existing render tests for smoke coverage.

---

## Key Constraints

- `xfade` requires both video segment streams in the filter graph simultaneously — only possible in the filter-graph paths (`single_pass`, `batched_gpu`). `smart_copy` stream-copy segments never enter a filter graph, hence the forced downgrade.
- `xfade` changes output duration: each cut point "consumes" `fade_s` seconds from the timeline. Audio `acrossfade` must consume the exact same duration to maintain A/V sync.
- FPS must be probed per-input to convert `video_fade_duration_frames` to seconds accurately.
- Both host and guest are rendered through the same `_build_filter_chain()` call path, so the crossfade will be applied to each independently — satisfying the "both streams" requirement.
- `video_fade_on` defaults to `False` to preserve backward-compatible hard-cut behavior for existing users.

---

## Files Changed

- [`config.py`](config.py) — adds `video_fade_on`, `video_fade_duration_frames`
- [`io_/video_renderer.py`](io_/video_renderer.py) — adds `_build_xfade_chain()`, modifies `_build_filter_chain()` and `render_project()`
- [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py) — threads new params through `render_video_single_pass()`
- [`io_/video_renderer_strategies.py`](io_/video_renderer_strategies.py) — threads new params through `render_video_batched_gpu()`

---

## Issues Found by planner-b (Corrections Applied in Tasks Below)

- **`io_/video_renderer.py` is 704 lines** — over the 600-line limit. `_build_xfade_chain()` must be placed in a new file: [`io_/video_renderer_xfade.py`](io_/video_renderer_xfade.py).
- **Step 1 had a duplicate `video_fade_on` key** — corrected in Task 1 below.
- **`asplit` conflict** — the existing `asplit` + per-segment atrim loop in `_build_filter_chain()` must be bypassed entirely when `video_fade_on=True`, since `acrossfade` requires raw per-segment audio streams (not a shared split node). Clarified in Task 3.
- **`_render_as_chunks()` call site** — must also thread `video_fade_s` (line 633). Added explicitly in Task 4.
- **`render_project()` non-two-phase call sites** (lines 795–817) — must also pass `video_fade_s`. Added in Task 4.
- **`render_video_batched_gpu()`** — reads `cut_fade_ms` from `cfg` (line 349) but does not read `video_fade_on`. Must pass `cfg` through so `_build_filter_chain()` can act on it.

---

## Detailed Tasks

### Task 0: Backup target files
Mode hint: /coder-jr.
Goal: Create timestamped backups of all files that will be modified.
Acceptance criteria: All four files are copied to the `backups folder` with timestamp suffix.
Files involved: `config.py`, `io_/video_renderer.py`, `io_/video_renderer_twophase.py`, `io_/video_renderer_strategies.py`.
Detailed actions:
- Copy each file to `.kilocode/docs/old_versions/` with pattern `{filename}_{YYYYMMDD_HHMM}{ext}`.
Constraints: Read-only operation; no source file changes.
Testing: None.
**Log progress** to `p_20260331_video-crossfade-log.md`.

---

### Task 1: Add config keys to `config.py`
Mode hint: /coder-jr.
Goal: Add `video_fade_on` and `video_fade_duration_frames` config keys inside `QUALITY_PRESETS['PODCAST_HIGH_QUALITY']`.
Acceptance criteria: Both keys are present after `cut_fade_ms` (line 65). `video_fade_on` defaults to `False`. `video_fade_duration_frames` defaults to `4`.
Files involved: [`config.py`](config.py).
Detailed actions:
- After line 65 (`'cut_fade_ms': 12,`), insert:
```python
# When True, consecutive video segments dissolve into each other using FFmpeg
# xfade/acrossfade instead of a hard splice. Applied to both host and guest.
# Default False = preserve existing hard-cut behavior (fully backward-compatible).
'video_fade_on': False,
# Number of video frames for the crossfade dissolve at each cut boundary.
# At 30 fps, 4 frames ≈ 133 ms. At 60 fps, 4 frames ≈ 67 ms.
# Has no effect when video_fade_on is False.
'video_fade_duration_frames': 4,
```
Constraints: Do not rename or remove any existing keys.
Testing: None (config-only change).
**Log progress** to `p_20260331_video-crossfade-log.md`.

---

### Task 2: Create `io_/video_renderer_xfade.py` with `_build_xfade_chain()`
Mode hint: /coder-sr.
Goal: Add a new module containing `_build_xfade_chain()` — the FFmpeg filter-graph builder for xfade + acrossfade between consecutive video/audio segments.
Acceptance criteria:
- New file `io_/video_renderer_xfade.py` exists and is under 600 lines.
- `_compute_xfade_offsets(segment_durations, fade_s)` is a pure Python helper (no FFmpeg) and is importable.
- `_build_xfade_chain(segments_v, segments_a, segment_durations, fade_s)` is importable.
- Returns `(v_out, a_out)` — final chained ffmpeg-python stream specs.
- Offset formula is correct per plan notes.
Files involved: [`io_/video_renderer_xfade.py`](io_/video_renderer_xfade.py) (new file).
Detailed actions:
```python
# io_/video_renderer_xfade.py
import ffmpeg
from utils.logger import get_logger

logger = get_logger(__name__)


def _compute_xfade_offsets(segment_durations: list[float], fade_s: float) -> list[float]:
    """Return xfade offset values for each inter-segment boundary.

    Pure helper with no FFmpeg dependency — extracted for testability.

    Offset formula (0-indexed boundary i):
        offset[i] = sum(segment_durations[0..i]) - (i+1) * fade_s
    Running accumulation: offset[i] = offset[i-1] + (segment_durations[i-1] - fade_s)
    """
    offsets = []
    running = 0.0
    for i in range(1, len(segment_durations)):
        running += segment_durations[i - 1] - fade_s
        offsets.append(running)
    return offsets


def _build_xfade_chain(
    segments_v: list,
    segments_a: list,
    segment_durations: list[float],
    fade_s: float,
) -> tuple:
    """Chain FFmpeg xfade (video) + acrossfade (audio) between consecutive segments.

    Args:
        segments_v:         List of per-segment ffmpeg-python video streams.
        segments_a:         List of per-segment ffmpeg-python audio streams.
        segment_durations:  Duration in seconds for each segment (len == len(segments_v)).
        fade_s:             Crossfade duration in seconds (same for all boundaries).

    Returns:
        (v_out, a_out) — final ffmpeg-python stream specs ready for ffmpeg.output().

    Offset formula (0-indexed):
        offset[i] = sum(segment_durations[0..i]) - (i+1) * fade_s
        i.e. sum of all preceding durations minus the timeline consumed by prior fades.
    """
    assert len(segments_v) == len(segments_a) == len(segment_durations) >= 2

    v = segments_v[0]
    a = segments_a[0]
    offsets = _compute_xfade_offsets(segment_durations, fade_s)

    for i in range(1, len(segments_v)):
        running_offset = offsets[i - 1]
        logger.debug(
            "_build_xfade_chain: boundary %d/%d offset=%.4fs fade_s=%.4fs",
            i, len(segments_v) - 1, running_offset, fade_s,
        )

        # Video crossfade (dissolve).
        v = ffmpeg.filter([v, segments_v[i]], "xfade",
                          transition="fade",
                          duration=fade_s,
                          offset=running_offset)

        # Audio crossfade (triangular curve — natural for speech).
        a = ffmpeg.filter([a, segments_a[i]], "acrossfade",
                          d=fade_s, c1="tri", c2="tri")

    return v, a
```
Constraints: No circular imports. This module imports only `ffmpeg` and `utils.logger`.
Testing: None here — covered by Task 6 tests.
**Log progress** to `p_20260331_video-crossfade-log.md`.

---

### Task 3: Modify `_build_filter_chain()` in `io_/video_renderer.py`
Mode hint: /coder-sr.
Goal: Add `video_fade_on` and `video_fade_s` parameters to `_build_filter_chain()`. When enabled and segment count > 1, bypass the existing `concat` path and call `_build_xfade_chain()` instead.
Acceptance criteria:
- Signature of `_build_filter_chain()` gains two new optional params: `video_fade_on=False`, `video_fade_s=0.0`.
- When `video_fade_on=True` and `len(keep_segments) > 1`: calls `_build_xfade_chain()`.
- When `video_fade_on=False`: existing `ffmpeg.concat()` path runs unchanged.
- `_apply_cut_fades()` is skipped (not called) when `video_fade_on=True` (acrossfade handles audio boundaries).
- The `asplit` insertion (line 327–335) is also skipped when `video_fade_on=True` since xfade path handles per-segment audio differently.
Files involved: [`io_/video_renderer.py`](io_/video_renderer.py:267).
Detailed actions:
1. Update signature at line 267:
   ```python
   def _build_filter_chain(
       input_path: str,
       filters: list,
       keep_segments: list,
       input_kwargs: dict,
       cut_fade_s: float = 0.0,
       video_fade_on: bool = False,
       video_fade_s: float = 0.0,
   ) -> tuple:
   ```
2. Add import near top of file: `from io_.video_renderer_xfade import _build_xfade_chain`.
3. Inside the `if keep_segments:` block (line 318), modify the segment loop to support xfade.
   In the loop building `segments_v` and `segments_a` (lines 340–353):
   - When `video_fade_on=True`: do NOT call `_apply_cut_fades()` (skip line 338) and do NOT insert `asplit` (skip lines 327–335).
   - Build `segment_durations = [end - start for start, end in keep_segments]`.
4. After the loop, replace the `interleaved / ffmpeg.concat()` block (lines 362–368) with:
   ```python
   if video_fade_on and len(segments_v) > 1:
       v, a = _build_xfade_chain(segments_v, segments_a, segment_durations, video_fade_s)
   else:
       interleaved = []
       for seg_v, seg_a in zip(segments_v, segments_a):
           interleaved.append(seg_v)
           interleaved.append(seg_a)
       concat_out = ffmpeg.concat(*interleaved, v=1, a=1)
       v = concat_out.node[0]
       a = concat_out.node[1]
   ```
Constraints: Do not break any existing tests. Only the section inside `if keep_segments:` changes.
Testing: Existing tests continue to pass (video_fade_on defaults to False = old behavior).
**Log progress** to `p_20260331_video-crossfade-log.md`.

---

### Task 4: Thread `video_fade_on` / `video_fade_s` through all `_build_filter_chain()` call sites
Mode hint: /coder-jr.
Goal: All callers of `_build_filter_chain()` must pass the two new params derived from config.
Acceptance criteria: All 4 call sites pass `video_fade_on` and `video_fade_s`.
Files involved:
- [`io_/video_renderer.py`](io_/video_renderer.py) — lines 795–798 (host non-chunk), 812–814 (guest non-chunk), 633 inside `_render_as_chunks()`.
- [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py:149) — `render_video_single_pass()`.
- [`io_/video_renderer_strategies.py`](io_/video_renderer_strategies.py:366) — `render_video_batched_gpu()` → `_render_batch()`.
Detailed actions:
For each call site, compute:
```python
video_fade_on = bool(cfg.get("video_fade_on", False))
video_fade_duration_frames = int(cfg.get("video_fade_duration_frames", 4))
video_fade_s = (video_fade_duration_frames / fps) if fps and video_fade_on else 0.0
```
Where `fps` comes from calling `probe_video_fps(input_path)` (already imported in `video_renderer_twophase.py` from `io_.media_probe`). For the `io_/video_renderer.py` non-two-phase path and `_render_as_chunks()`, import `probe_video_fps` from `io_.media_probe`.

Call site changes:
1. `render_video_single_pass()` in `io_/video_renderer_twophase.py` (line 135):
   - After `cut_fade_s = ...` (line 145), add:
     ```python
     video_fade_on = bool(cfg.get("video_fade_on", False))
     vid_fps = probe_video_fps(input_path) if video_fade_on else None
     video_fade_s = (int(cfg.get("video_fade_duration_frames", 4)) / vid_fps) if vid_fps else 0.0
     ```
   - Add `video_fade_on=video_fade_on, video_fade_s=video_fade_s` to the `_build_filter_chain()` call at line 149.
2. `_render_batch()` inside `render_video_batched_gpu()` in `io_/video_renderer_strategies.py` (line 362):
   - After `cut_fade_s = float(cfg.get(...))` (line 349), add:
     ```python
     video_fade_on = bool(cfg.get("video_fade_on", False))
     # FPS probed once per batch call (not per segment inside _render_batch).
     ```
   - Import `probe_video_fps` at top of file from `io_.media_probe`.
   - Pass `video_fade_on=video_fade_on, video_fade_s=video_fade_s` to `_build_filter_chain()` at line 366.
3. Non-two-phase call sites in `render_project()` in `io_/video_renderer.py` (lines 786–818):
   - After `cut_fade_s = cut_fade_ms / 1000.0` (line 739), add:
     ```python
     video_fade_on = bool(cfg.get("video_fade_on", False))
     ```
   - In closures `_render_host` and `_render_guest`, compute `video_fade_s` by calling `probe_video_fps(host_path)` / `probe_video_fps(guest_path)`.
   - Pass `video_fade_on=video_fade_on, video_fade_s=video_fade_s` to all `_build_filter_chain()` calls and `_render_as_chunks()` via new `video_fade_on` / `video_fade_s` params for `_render_as_chunks()`.
4. `_render_as_chunks()` signature at line 581: add `video_fade_on=False, video_fade_s=0.0` params and thread down to its `_build_filter_chain()` call at line 633.
Constraints: `probe_video_fps()` may return `None` — guard with `if vid_fps else 0.0`. If `video_fade_s` resolves to 0, `video_fade_on` must also be treated as False to avoid a zero-duration fade.
Testing: No new tests in this task, existing tests still pass.
**Log progress** to `p_20260331_video-crossfade-log.md`.

---

### Task 5: Smart-copy strategy downgrade when `video_fade_on=True`
Mode hint: /coder-jr.
Goal: When `video_fade_on=True` and the resolved strategy is `smart_copy`, log a warning and downgrade to `single_pass`.
Acceptance criteria:
- The downgrade is logged as a warning.
- The `smart_copy` path is never reached when `video_fade_on=True`.
Files involved: [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py:315) — `render_project_two_phase()` → `_render_track()`.
Detailed actions:
- In `_render_track()`, after the `strategy` variable is resolved (after line 338, the non-h264 override block), add:
  ```python
  if strategy == "smart_copy" and bool(cfg.get("video_fade_on", False)):
      logger.warning(
          "video_fade_on=True is incompatible with smart_copy; downgrading to single_pass"
      )
      strategy = "single_pass"
  ```
- This must come AFTER both the `auto` resolution block (lines 317–331) and the non-h264 override block (lines 333–338).
Constraints: Do not change the `auto` resolution logic. Downgrade only applies when `video_fade_on=True`.
Testing: Covered by Task 6 test.
**Log progress** to `p_20260331_video-crossfade-log.md`.

---

### Task 6: Write tests for xfade offset math and strategy downgrade
Mode hint: /coder-sr.
Goal: Add unit tests for `_build_xfade_chain()` offset formula and the `smart_copy` downgrade.
Acceptance criteria:
- New test file `tests/test_video_crossfade.py`.
- Test 1: xfade offset correctness for N=2, N=3, N=4 segments with known durations.
- Test 2: When `video_fade_on=True` + `video_phase_strategy='smart_copy'` → strategy resolves to `single_pass`.
Files involved: [`tests/test_video_crossfade.py`](tests/test_video_crossfade.py) (new).
Detailed actions:
Test 1 — offset math (pure Python, no FFmpeg):
```python
def test_xfade_offset_two_segments():
    # Segments: [5.0s, 3.0s], fade_s=0.133
    # offset[0] = 5.0 - 0.133 = 4.867
    durations = [5.0, 3.0]
    fade_s = 0.133
    offsets = _compute_xfade_offsets(durations, fade_s)
    assert len(offsets) == 1
    assert abs(offsets[0] - (5.0 - 0.133)) < 1e-6

def test_xfade_offset_three_segments():
    # Segments: [4.0, 3.0, 2.0], fade_s=0.1
    # offset[0] = 4.0 - 0.1 = 3.9
    # offset[1] = (4.0 - 0.1) + (3.0 - 0.1) = 6.8
    durations = [4.0, 3.0, 2.0]
    fade_s = 0.1
    offsets = _compute_xfade_offsets(durations, fade_s)
    assert abs(offsets[0] - 3.9) < 1e-6
    assert abs(offsets[1] - 6.8) < 1e-6
```
`_compute_xfade_offsets()` is already defined in `io_/video_renderer_xfade.py` (Task 2). Import it directly for testing.

Test 2 — strategy downgrade (mock `probe_video_fps`, `probe_video_stream_codec`, and rendering):
```python
def test_strategy_downgrade_when_video_fade_on(monkeypatch):
    # Confirm resolved strategy = 'single_pass' when video_fade_on=True and
    # video_phase_strategy='smart_copy'
    resolved = []
    # ... monkeypatch render_video_single_pass to capture strategy
    cfg = {**DEFAULT_CFG, "video_fade_on": True, "video_phase_strategy": "smart_copy"}
    # call _render_track(...) or render_project_two_phase with mock inputs
    assert "single_pass" in resolved
```
Constraints: All tests are pure-Python / monkeypatched — no real FFmpeg calls.
Testing: `pytest tests/test_video_crossfade.py`.
**Log progress** to `p_20260331_video-crossfade-log.md`.

