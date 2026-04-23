# Plan: AV Sync Fix — Start-of-File Audio Delay

**Short plan name**: av-sync-fix  
**User query file**: p_20260401_av-sync-fix-user.md  
**Log file**: p_20260401_av-sync-fix-log.md  
**Complexity**: Few Phases (Med)  
**Autonomy level**: High (rare checks)  
**Testing type**: Use what is appropriate per task  

---

## Problem Summary

After adding render-time `afftdn` noise reduction, processed videos show ~128–150 ms of audio-behind-video offset at the start. The root causes are:

**Cause A (~85 ms)** — `afftdn` FFT warm-up silence:  
The FFT-based denoiser fills its analysis window before producing valid output. During warm-up, it outputs near-silence. This silence flows through `render_audio_phase()` and ends up in the temp audio file, pushing real audio content later.

**Cause B (~43 ms)** — AAC encoder priming lost in ADTS format:  
The temp audio file uses `.aac` (ADTS format), which stores no timestamps, no encoder delay, and no edit list. The AAC encoder writes ~2048 priming samples before the first real audio frame. When the ADTS file is muxed via `-c copy`, FFmpeg cannot compensate because the priming information was discarded by ADTS. In a proper MP4/M4A container, FFmpeg writes an edit list so decoders skip the priming. With ADTS, the priming appears as real audio content.

Both affects Host and Guest equally when `noise_reduction_host` and `noise_reduction_guest` are both enabled.

## Solution Overview

- **Fix A**: After applying `afftdn` in `render_audio_phase()`, insert `atrim(start=DELAY)` + `asetpts(PTS-STARTPTS)` immediately to discard the warm-up silence before it reaches the encoder. The delay is computed mathematically from the source sample rate using FFmpeg's `afftdn` implementation formula.
- **Fix B**: Change the temp audio intermediate from `.aac` (ADTS, no metadata) to `.m4a` (MPEG-4 Audio container). The M4A file carries the AAC encoder delay as an edit list. The existing `-c copy` mux step preserves that edit list into the final MP4. Decoders then skip the priming samples correctly.

---

## Phase 1: Probe + ADTS Format Fix + Unit Tests

### Task 1: Add `probe_audio_sample_rate()` to `io_/media_probe.py`.
Mode hint: /coder-jr.  
Goal: Expose the source audio sample rate so `render_audio_phase()` can compute the `afftdn` warm-up delay.  
Acceptance criteria: `probe_audio_sample_rate("path.mp4")` returns an `int` (Hz) on success and `None` on failure, following the existing probe function pattern.  
Files involved: [`io_/media_probe.py`](io_/media_probe.py).  
Detailed actions:  
- Backup [`io_/media_probe.py`](io_/media_probe.py) to backups folder.
- Add function after the last existing `def probe_*` function (currently after `probe_is_vfr` at line 256):
```python
def probe_audio_sample_rate(path: str) -> int | None:
    """Return the sample rate (Hz) of the first audio stream, or None on failure."""
    try:
        probe = ffmpeg.probe(path)
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "audio":
                rate = stream.get("sample_rate")
                if rate:
                    return int(rate)
    except Exception:
        pass
    return None
```
- Add import of `ffmpeg` if not already present (check top of file first).
- Log progress to [`p_20260401_av-sync-fix-log.md`](.kilocode/docs/plans/p_20260401_av-sync-fix-log.md).  
Constraints: Follow domain-first naming convention. No new files — add to existing `media_probe.py`.  
Testing: Python test in `tests/test_video_renderer_twophase.py` — add `test_probe_audio_sample_rate_returns_int()` that monkeypatches `ffmpeg.probe` to return a fake JSON blob containing `{"codec_type": "audio", "sample_rate": "48000"}` and asserts the return is `48000` (int). Add `test_probe_audio_sample_rate_returns_none_on_failure()` that monkeypatches `ffmpeg.probe` to raise an exception and asserts `None` is returned.

---

### Task 2: Change temp audio intermediate from `.aac` to `.m4a` in `render_project_two_phase()`.
Mode hint: /coder-jr.  
Goal: Fix the AAC encoder priming delay (~43 ms) by using a container format that can store and propagate the encoder edit list.  
Acceptance criteria: The temp audio file created in `render_project_two_phase()` uses `.m4a` extension. The existing `-c copy` mux command is unchanged. The two existing tests related to temp file count still pass.  
Files involved: [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py), [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py).  
Detailed actions:  
- Backup [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py) to backups folder.
- At line 313, change:
  ```python
  fd, tmp_audio = tempfile.mkstemp(suffix=".aac", dir=str(out_dir))
  ```
  to:
  ```python
  fd, tmp_audio = tempfile.mkstemp(suffix=".m4a", dir=str(out_dir))
  ```
- No changes to `audio_opts` (already contains `acodec="aac"` which is correct for M4A).
- No changes to the mux command (line 423-425); `-c copy` from M4A to MP4 preserves the edit list.
- In [`tests/test_video_renderer_twophase.py`](tests/test_video_renderer_twophase.py) at line 1342, update the comment in the assertion from `"Expected 2 temp files (aac + mp4)"` to `"Expected 2 temp files (m4a + mp4)"`.
- Log progress to log file.  
Constraints: Do NOT change the mux command. Do NOT change `audio_opts`. Minimal change — one suffix string only.  
Testing: Run `pytest tests/test_video_renderer_twophase.py` and confirm all existing tests pass. Check specifically: temp cleanup tests still pass (they assert count == 2, not suffix).

---

## Phase 2: `afftdn` Warm-Up Delay Compensation

### Task 3: Add `_afftdn_delay_s()` helper to `io_/video_renderer_twophase.py`.
Mode hint: /coder-jr.  
Goal: Encapsulate the `afftdn` warm-up delay formula in a testable, reusable helper.  
Acceptance criteria: `_afftdn_delay_s(48000)` returns approximately `0.0854` seconds. `_afftdn_delay_s(44100)` returns approximately `0.0929` seconds. The function is a module-level private function in `io_/video_renderer_twophase.py`.  
Files involved: [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py).
Detailed actions:
- Backup for this file was already created in Task 2.
- Add `import math` to the import block at the top of the file (if not already present).
- Add this helper near the top of the module, before `render_audio_phase()` (before line 51):
```python
def _afftdn_delay_s(sample_rate: int) -> float:
    """Compute the warm-up delay (seconds) introduced by afftdn at the given sample rate.

    FFmpeg's afftdn uses overlap-add FFT processing. The number of frequency bins
    is derived from the sample rate using: nb_freq = (1 << floor(log2(sr/17))) + 1.
    The FFT frame length is 2 * nb_freq. The filter outputs near-silence for the
    first fft_length / sample_rate seconds while its analysis window fills.

    At 48000 Hz: nb_freq=2049, fft_len=4098, delay≈0.0854 s
    At 44100 Hz: nb_freq=2049, fft_len=4098, delay≈0.0929 s
    """
    safe_rate = max(int(sample_rate), 17)
    nb_freq = (1 << int(math.log2(safe_rate / 17))) + 1
    fft_length = 2 * nb_freq
    return fft_length / safe_rate
```
- Log progress to log file.  
Constraints: Module-private (underscore prefix). Pure function — no FFmpeg calls, no I/O.  
Testing: Add `test_afftdn_delay_s_48k()` and `test_afftdn_delay_s_44k()` in `tests/test_video_renderer_twophase.py`. Each imports `_afftdn_delay_s` from the module and asserts the result is within ±1ms of the expected value (use `abs(result - expected) < 0.001`).

---

### Task 4: Apply `afftdn` delay compensation in `render_audio_phase()`.
Mode hint: /coder-sr.  
Goal: Discard `afftdn` warm-up silence before it gets encoded, so the rendered audio starts at the first real audio sample (t=0 of the kept content).  
Acceptance criteria: When `filters` contains an `AudioFilter` with `filter_name == "afftdn"`, `render_audio_phase()` inserts an `atrim(start=delay_s)` + `asetpts(PTS-STARTPTS)` immediately after applying that filter, where `delay_s = _afftdn_delay_s(probed_sample_rate)`. When `filters` contains no `afftdn` filter, behavior is unchanged from current.  
Files involved: [`io_/video_renderer_twophase.py`](io_/video_renderer_twophase.py), [`io_/media_probe.py`](io_/media_probe.py).  
Detailed actions:
- Backup is already created for this file from Task 2.
- Add `probe_audio_sample_rate` to the existing file-level import block near lines 29-35:
  ```python
  from io_.media_probe import (
      get_video_duration_seconds,
      probe_audio_sample_rate,   # ← add this
      probe_is_vfr,
      probe_video_fps,
      probe_video_keyframes,
      probe_video_stream_codec,
  )
  ```
- At the top of `render_audio_phase()` (after the `merge_close_segments` call at line 72, before the ffmpeg input is built at line 83), probe the sample rate:
  ```python
  # Probe sample rate for afftdn delay compensation (fallback to 48000 Hz).
  _sample_rate = probe_audio_sample_rate(input_path) or 48000
  ```
- In the filter application loop (currently at lines 87-88):
  ```python
  for f in filters or []:
      a = a.filter(f.filter_name, **f.params)
  ```
  Change to:
  ```python
  for f in filters or []:
      a = a.filter(f.filter_name, **f.params)
      if f.filter_name == "afftdn":
          # afftdn introduces warm-up silence of approximately fft_length samples.
          # Trim that silence immediately so it does not propagate to the encoder.
          _delay_s = _afftdn_delay_s(_sample_rate)
          logger.debug(
              "render_audio_phase(%s): afftdn delay compensation: trimming %.4f s",
              os.path.basename(input_path),
              _delay_s,
          )
          a = a.filter_("atrim", start=_delay_s)
          a = a.filter_("asetpts", "PTS-STARTPTS")
  ```
- Log progress to log file.  
Constraints: Only trigger compensation for `filter_name == "afftdn"`. Do not modify the subsequent `atrim`/`asetpts` logic for `keep_segments`. The probe call must use the `probe_audio_sample_rate` function from Task 1 (not inline ffprobe).  
Testing: Add `test_render_audio_phase_afftdn_inserts_compensation()` in `tests/test_video_renderer_twophase.py`:
- Create a fake `afftdn` `AudioFilter`.
- Call `render_audio_phase` with that filter (mocking `run_with_progress` and `probe_audio_sample_rate` to return `48000`).
- Inspect the captured ffmpeg-python graph (via its compile output or string representation) and assert that an `atrim` node appears immediately after `afftdn` in the filter chain, before the keep-segments `atrim`.
- Also add `test_render_audio_phase_non_afftdn_filter_no_compensation()` to confirm a non-afftdn filter (e.g., `volume`) does NOT insert the extra atrim.

---

## Phase 3: Integration Validation

### Task 5: Regression + integration test sweep.
Mode hint: /coder-jr.  
Goal: Confirm no existing tests break, and the pipeline compiles cleanly.  
Acceptance criteria: `pytest` passes with zero failures. No new Python import errors.  
Files involved: All test files.  
Detailed actions:  
- Run `pytest` from the project root.
- Fix any test failures caused by the new `atrim`/`asetpts` nodes in `render_audio_phase` filter graph (if any existing test inspects the ffmpeg-python compiled node list and asserts node order, update it to accommodate the new nodes).
- Check that `test_render_audio_phase_with_filters` still passes (that test uses a non-afftdn filter so should be unaffected).
- Check that `test_render_project_two_phase_mux_uses_map_flags` still passes (mux command unchanged).
- Run `python -c "from io_.video_renderer_twophase import render_audio_phase, _afftdn_delay_s; from io_.media_probe import probe_audio_sample_rate; print('ok')"` to confirm imports work.
- Log progress to log file.  
Constraints: Do not remove existing passing tests. Do not skip tests.  
Testing: `pytest` — all tests must pass.

---

### Task 6: Update log file and mark plan complete.
Mode hint: /tasky.  
Goal: Housekeeping — mark all tasks complete, update log, move plan files to completed folder.  
Acceptance criteria: Log file updated with completion status of all tasks. Plan file, log file, and user query file moved to `.kilocode/docs/plans_completed/`.  
Files involved: [`p_20260401_av-sync-fix-log.md`](.kilocode/docs/plans/p_20260401_av-sync-fix-log.md), [`p_20260401_av-sync-fix.md`](.kilocode/docs/plans/p_20260401_av-sync-fix.md), [`p_20260401_av-sync-fix-user.md`](.kilocode/docs/plans/p_20260401_av-sync-fix-user.md).  
Detailed actions:  
- Mark all tasks [x] complete in the log file.  
- Move the three plan files to `.kilocode/docs/plans_completed/`.  
- Log progress: "Plan complete. All tasks executed."  
Constraints: Do not delete files — move only.  
Testing: Verify files exist in `.kilocode/docs/plans_completed/`.
