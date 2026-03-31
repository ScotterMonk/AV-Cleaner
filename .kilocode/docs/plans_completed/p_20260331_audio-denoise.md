# Plan — audio-denoise

**Short plan name**: audio-denoise
**Log file**: p_20260331_audio-denoise-log.md
**User query file**: p_20260331_audio-denoise-user.md
**Complexity**: One Phase (Small/Med)
**Autonomy**: High
**Testing type**: Use what is appropriate per task

---

## Problem

`CrossTalkDetector` reads the guest's ambient noise floor as "active audio", which breaks mutual-silence detection and causes segments of host speech to be mis-cut (e.g. "palisades" gets dropped). Fix: denoise both tracks in-memory before any detector sees them, then also apply an `afftdn` render-time FFmpeg filter so the output audio is clean for listeners.

## Solution

1. Add `noisereduce` to dependencies.
2. Add per-track config flags (`noise_reduction_host`, `noise_reduction_guest`) to `QUALITY_PRESETS` alongside the existing master flag.
3. Create `analyzers/audio_denoiser.py` — a thin wrapper around `noisereduce.reduce_noise()`.
4. Call the denoiser in `core/pipeline.py` after `extract_audio()`, before the detector loop — only for whichever tracks are enabled per config.
5. Add a render-time `afftdn` FFmpeg audio filter to the `EditManifest` via a new lightweight processor (`processors/audio_denoiser_filter.py`) or by extending an existing processor — so the rendered output audio is also denoised.

---

## Phase 1: Audio Noise Reduction — Full Implementation

### Backup instruction
Backup all target files to `.kilocode/docs/old_versions/` with `_[timestamp]` suffix before modifying.

---

### Task 1: Add per-track config keys and `noisereduce` dependency.
**Mode hint**: /coder-jr
**Goal**: Wire up the two new config keys so the rest of the tasks can read them, and ensure `noisereduce` is installable.
**Acceptance criteria**:
- `requirements.txt` contains `noisereduce>=0.4.2`.
- `QUALITY_PRESETS['PODCAST_HIGH_QUALITY']` in `config.py` contains both `noise_reduction_host: True` and `noise_reduction_guest: True` (with comments matching the existing style).
- Existing keys `noise_reduction_enabled`, `noise_reduction_stationary`, `noise_reduction_prop_decrease` are unchanged.
**Files involved**:
- `requirements.txt`
- `config.py`
**Detailed actions**:
1. In `requirements.txt`, append after line 15: `noisereduce>=0.4.2`.
2. In `config.py`, after `noise_reduction_prop_decrease` (line 107), insert two new keys inside `QUALITY_PRESETS`:
   ```python
   # Per-track noise reduction toggles. Both default True.
   # Set False to skip denoising for that track (e.g. host mic is already clean).
   'noise_reduction_host': True,
   'noise_reduction_guest': True,
   ```
3. Run `pip install noisereduce` to confirm installability; do NOT commit the output — just verify exit code 0.
**Constraints**: Do not touch any logic files in this task.
**Testing**: None (config-only).
**Log progress** to `p_20260331_audio-denoise-log.md`.

---

### Task 2: Create `analyzers/audio_denoiser.py`.
**Mode hint**: /coder-jr
**Goal**: Provide a reusable, well-tested function that denoises a pydub `AudioSegment` and returns an `AudioSegment` with identical duration/sample-count.
**Acceptance criteria**:
- File exists at `analyzers/audio_denoiser.py`.
- Exported function: `denoise_audio(audio: AudioSegment, config: dict) -> AudioSegment`.
- Function reads `noise_reduction_stationary` and `noise_reduction_prop_decrease` from `config`.
- Input sample count == output sample count (verified by an assert / logged check inside the function).
- Timing is logged: `[DENOISE] Host/Guest denoising took X.Xs`.
- Graceful degradation: if `noisereduce` import fails, log a warning and return `audio` unchanged.
- File is ≤ 120 lines.
**Files involved**:
- `analyzers/audio_denoiser.py` (new)
**Detailed actions**:
```python
# analyzers/audio_denoiser.py

import time
import numpy as np
from pydub import AudioSegment
from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import noisereduce as nr
    HAS_NOISEREDUCE = True
except ImportError:
    HAS_NOISEREDUCE = False
    logger.warning("noisereduce not installed — denoising skipped. pip install noisereduce")


def denoise_audio(audio: AudioSegment, config: dict, label: str = "Track") -> AudioSegment:
    """
    Denoise a pydub AudioSegment in-memory using noisereduce spectral gating.
    Returns an AudioSegment with identical sample count and duration.
    If noisereduce is unavailable, returns audio unchanged.
    """
    if not HAS_NOISEREDUCE:
        return audio

    stationary = config.get("noise_reduction_stationary", True)
    prop_decrease = config.get("noise_reduction_prop_decrease", 1.0)

    sample_rate = audio.frame_rate
    channels = audio.channels
    sample_width = audio.sample_width
    original_samples = len(audio.get_array_of_samples()) // channels

    # Convert pydub -> numpy float32 shape (samples, channels)
    raw = np.array(audio.get_array_of_samples(), dtype=np.float32)
    max_val = float(2 ** (8 * sample_width - 1))
    raw /= max_val
    if channels > 1:
        raw = raw.reshape((-1, channels))  # (samples, channels)

    t0 = time.time()
    if channels > 1:
        # noisereduce accepts (channels, samples) or (samples,); use per-channel loop
        denoised_channels = []
        for ch in range(channels):
            ch_data = raw[:, ch]
            ch_denoised = nr.reduce_noise(
                y=ch_data,
                sr=sample_rate,
                stationary=stationary,
                prop_decrease=prop_decrease,
            )
            denoised_channels.append(ch_denoised)
        denoised = np.stack(denoised_channels, axis=1)  # (samples, channels)
    else:
        denoised = nr.reduce_noise(
            y=raw.flatten(),
            sr=sample_rate,
            stationary=stationary,
            prop_decrease=prop_decrease,
        ).reshape(-1, 1)

    elapsed = time.time() - t0
    logger.info("[DENOISE] %s denoising took %.1fs", label, elapsed)

    # Verify sample count preserved (critical for A/V sync)
    output_samples = denoised.shape[0]
    if output_samples != original_samples:
        logger.error(
            "[DENOISE] Sample count mismatch: in=%d out=%d — returning original audio",
            original_samples, output_samples,
        )
        return audio

    # Convert back: float32 -> int16 interleaved -> pydub AudioSegment
    denoised = (denoised * max_val).clip(-max_val, max_val - 1).astype(np.int16)
    interleaved = denoised.reshape(-1).tobytes()
    return AudioSegment(
        data=interleaved,
        sample_width=sample_width,
        frame_rate=sample_rate,
        channels=channels,
    )
```
**Constraints**: No external calls. Pure in-memory. File must stay ≤ 120 lines (it's ~90 lines as written).
**Testing**: Write `tests/test_audio_denoiser.py`:
- Test 1: Pass a synthetic 1-second stereo silence `AudioSegment` — output sample count == input sample count.
- Test 2: Pass a synthetic noisy mono segment — output sample count == input sample count.
- Test 3: When `HAS_NOISEREDUCE=False` (mock the import), function returns input unchanged.
**Log progress** to `p_20260331_audio-denoise-log.md`.

---

### Task 3: Integrate denoiser into `core/pipeline.py` (analysis phase).
**Mode hint**: /coder-jr
**Goal**: After `extract_audio()` in `ProcessingPipeline.execute()`, call `denoise_audio()` on each track if its per-track flag is enabled, and pass the denoised audio to all detectors.
**Acceptance criteria**:
- Denoising happens at lines 115-116 of `core/pipeline.py` (after extraction, before detector loop).
- Per-track flags `noise_reduction_host` and `noise_reduction_guest` gate the call independently.
- Master flag `noise_reduction_enabled` also gates both (if False, skip entirely regardless of per-track flags).
- Original `host_audio` / `guest_audio` variables are replaced by the denoised versions (or remain unchanged if disabled).
- Log line emitted: `[DENOISE] Noise reduction: host=True/False, guest=True/False`.
**Files involved**:
- `core/pipeline.py`
**Detailed actions**:
After line 116 (`guest_audio = audio_extractor.extract_audio(guest_video_path)`), insert:
```python
# Denoise tracks in-memory before detectors (preserves sample count for A/V sync)
preset = self.config.get("quality_preset", {})
nr_enabled = preset.get("noise_reduction_enabled", True)
nr_host = preset.get("noise_reduction_host", True)
nr_guest = preset.get("noise_reduction_guest", True)
logger.info("[DENOISE] Noise reduction: enabled=%s host=%s guest=%s", nr_enabled, nr_host, nr_guest)
if nr_enabled:
    from analyzers.audio_denoiser import denoise_audio
    if nr_host:
        host_audio = denoise_audio(host_audio, preset, label="Host")
    if nr_guest:
        guest_audio = denoise_audio(guest_audio, preset, label="Guest")
```
Note: Verify how `self.config` exposes the quality preset dict. In `main.py` check what key is used when `ProcessingPipeline(config)` is called and adjust the key `"quality_preset"` accordingly. The actual key may differ — search `main.py` for `ProcessingPipeline(` to confirm.
**Constraints**: Do NOT reorder or remove existing detector/processor calls. Do not break the `detection_results` dict.
**Testing**: Integration — run `pytest tests/test_pipeline_normalize_spike.py` to confirm no regression. No new test required for this task (covered by denoiser unit tests + existing pipeline tests).
**Log progress** to `p_20260331_audio-denoise-log.md`.

---

### Task 4: Add render-time `afftdn` FFmpeg filter via a new processor.
**Mode hint**: /coder-jr
**Goal**: Create `processors/audio_denoiser_filter.py` — a minimal processor that appends `afftdn` to `manifest.host_filters` and/or `manifest.guest_filters` based on the per-track config flags, so rendered output is also denoised.
**Acceptance criteria**:
- File `processors/audio_denoiser_filter.py` exists.
- Class `AudioDenoiserFilter(BaseProcessor)` with `get_name()` returning `"AudioDenoiserFilter"`.
- `process()` reads `noise_reduction_enabled`, `noise_reduction_host`, `noise_reduction_guest` from config.
- Adds `afftdn` with `nr=10:nf=-25` defaults to the appropriate track filters in `manifest` when enabled.
- Processor is registered in `main.py` alongside the other processors (only when `noise_reduction_enabled` is True).
- `pipeline.py` Phase 2 log shows `"[FUNCTION START] Denoise render filter"` / `"[FUNCTION COMPLETE] ..."`.
**Files involved**:
- `processors/audio_denoiser_filter.py` (new)
- `main.py` (register processor)
- `core/pipeline.py` (add friendly name label for this processor)
**Detailed actions**:
```python
# processors/audio_denoiser_filter.py

from processors.base_processor import BaseProcessor
from utils.logger import get_logger

logger = get_logger(__name__)


class AudioDenoiserFilter(BaseProcessor):
    """
    Appends FFmpeg afftdn (adaptive noise reduction) filter to host/guest
    audio filter chains in the EditManifest for render-time denoising.
    """

    def get_name(self) -> str:
        return "AudioDenoiserFilter"

    def process(self, manifest, host_audio, guest_audio, detection_results):
        preset = self.config.get("quality_preset", {})  # adjust key as in Task 3
        if not preset.get("noise_reduction_enabled", True):
            return manifest

        nr_host = preset.get("noise_reduction_host", True)
        nr_guest = preset.get("noise_reduction_guest", True)

        # afftdn params: nr=noise reduction amount (0-97, default 12)
        #                nf=noise floor in dBFS (default -50)
        # Tune to taste; these defaults match gentle denoising.
        afftdn_params = {"nr": 10, "nf": -25}

        if nr_host:
            manifest.add_host_filter("afftdn", **afftdn_params)
            logger.info("[DENOISE] Added afftdn render filter to Host track")
        if nr_guest:
            manifest.add_guest_filter("afftdn", **afftdn_params)
            logger.info("[DENOISE] Added afftdn render filter to Guest track")

        return manifest
```
In `main.py`, locate where processors are added to the pipeline (search for `.add_processor(`). Add `AudioDenoiserFilter` FIRST in the processor chain (before `WordMuter`, `SegmentRemover`, etc.) so its filter is prepended — applied before volume/mute filters at render time.
In `core/pipeline.py`, add an `elif processor_name == "AudioDenoiserFilter":` branch in the `friendly` assignment block (around line 184) setting `friendly = "Denoise render filter"`.
**Constraints**: `AudioDenoiserFilter` must NOT modify `host_audio`/`guest_audio` in-memory (that's Task 3's job). It only appends to the manifest filter lists.
**Testing**: Write `tests/test_audio_denoiser_filter.py`:
- Test 1: When `noise_reduction_enabled=True`, `noise_reduction_host=True`, `noise_reduction_guest=True` — manifest has `afftdn` in both `host_filters` and `guest_filters`.
- Test 2: When `noise_reduction_enabled=False` — neither filter list is modified.
- Test 3: When `noise_reduction_host=False, noise_reduction_guest=True` — only `guest_filters` gets `afftdn`.
**Log progress** to `p_20260331_audio-denoise-log.md`.

---

### Task 5: Verify `main.py` config key path and register processor.
**Mode hint**: /coder-jr
**Goal**: Confirm the actual key used to pass `QUALITY_PRESETS['PODCAST_HIGH_QUALITY']` into `ProcessingPipeline`, fix the `"quality_preset"` key references in Tasks 3 & 4 if needed, and ensure `AudioDenoiserFilter` is registered in the pipeline.
**Acceptance criteria**:
- `denoise_audio()` and `AudioDenoiserFilter.process()` both correctly resolve the preset dict from `self.config` / the pipeline's `config` argument.
- Running `python main.py process --host <any_mp4> --guest <any_mp4>` shows `[DENOISE]` log lines for both analysis-phase and render-phase denoising.
- All existing tests pass: `pytest` exits 0.
**Files involved**:
- `main.py`
- `core/pipeline.py` (if key name correction needed)
- `processors/audio_denoiser_filter.py` (if key name correction needed)
**Detailed actions**:
1. Read `main.py` lines around `ProcessingPipeline(` — identify what dict/object is passed as `config`.
2. Trace the key name for the quality preset dict inside that config object.
3. Update every `self.config.get("quality_preset", {})` reference in `audio_denoiser_filter.py` and the pipeline insertion in Task 3 to use the correct key.
4. Confirm `AudioDenoiserFilter` is imported and `.add_processor(AudioDenoiserFilter(config))` is called in `main.py`.
5. Run `pytest` and confirm 0 failures.
**Constraints**: Minimal changes only — fix key path and registration, nothing else.
**Testing**: Full `pytest` suite must pass. Terminal smoke-test with real or mock video files if available.
**Log progress** to `p_20260331_audio-denoise-log.md`.
