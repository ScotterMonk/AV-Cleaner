import time

import numpy as np
from pydub import AudioSegment

from utils.logger import get_logger

logger = get_logger(__name__)

nr = None
try:
    import noisereduce as nr
    HAS_NOISEREDUCE = True
except ImportError:
    HAS_NOISEREDUCE = False
    logger.warning("noisereduce not installed — denoising skipped.")


def _audio_to_float_samples(audio: AudioSegment) -> np.ndarray:
    """Convert a pydub segment into float32 samples in [-1, 1]."""
    samples = np.array(audio.get_array_of_samples())
    if audio.channels > 1:
        samples = samples.reshape((-1, audio.channels))

    scale = np.float32(2 ** (8 * audio.sample_width - 1))
    return samples.astype(np.float32) / scale


def _float_to_audio(audio: AudioSegment, reduced: np.ndarray) -> AudioSegment:
    """Convert float denoised samples back to an AudioSegment."""
    scale = float(2 ** (8 * audio.sample_width - 1) - 1)
    clipped = np.clip(reduced, -1.0, 1.0)

    if audio.sample_width == 1:
        dtype = np.int8
    elif audio.sample_width == 2:
        dtype = np.int16
    elif audio.sample_width == 4:
        dtype = np.int32
    else:
        dtype = np.int32

    pcm = np.rint(clipped * scale).astype(dtype)
    if audio.channels > 1:
        pcm = pcm.reshape(-1)

    denoised = AudioSegment(
        data=pcm.tobytes(),
        sample_width=audio.sample_width,
        frame_rate=audio.frame_rate,
        channels=audio.channels,
    )
    assert len(audio.get_array_of_samples()) == len(denoised.get_array_of_samples())
    return denoised


# Minimum number of samples noisereduce needs to form at least one STFT frame.
# The library defaults nperseg=1024; anything shorter causes noverlap >= nperseg crash.
_MIN_SAMPLES_FOR_DENOISE = 1024


def denoise_audio(audio: AudioSegment, config: dict, label: str = "Track") -> AudioSegment:
    """Apply optional noise reduction while preserving sample count.

    ``label`` is used both for log messages and to select the per-track
    aggressiveness key.  Pass "Host" for the host track and "Guest" for the
    guest track so the correct config key is read.
    """
    if not HAS_NOISEREDUCE:
        return audio

    assert nr is not None

    stationary = config.get("noise_reduction_stationary", True)
    # Select per-track prop_decrease key; fall back to legacy key then to 1.0.
    if label.lower() == "host":
        prop_decrease = config.get(
            "noise_reduct_decrease_host",
            config.get("noise_reduction_prop_decrease", 1.0),
        )
    elif label.lower() == "guest":
        prop_decrease = config.get(
            "noise_reduct_decrease_guest",
            config.get("noise_reduction_prop_decrease", 1.0),
        )
    else:
        prop_decrease = config.get("noise_reduction_prop_decrease", 1.0)
    start_time = time.time()

    samples = _audio_to_float_samples(audio)

    # Guard: skip denoising if the segment is too short for the STFT window.
    if samples.ndim == 1:
        n_samples = len(samples)
    else:
        n_samples = samples.shape[0]

    if n_samples <= _MIN_SAMPLES_FOR_DENOISE:
        logger.debug(
            f"[DENOISE] {label} segment too short ({n_samples} samples) — skipping denoising."
        )
        return audio

    # noisereduce expects (# channels, # frames) for multichannel audio.
    # Our internal helpers use (# frames, # channels), so transpose on entry
    # and transpose back after denoising.
    samples_for_noise_reduce = samples.T if audio.channels > 1 else samples

    reduced = nr.reduce_noise(
        y=samples_for_noise_reduce,
        sr=audio.frame_rate,
        stationary=stationary,
        prop_decrease=prop_decrease,
    )
    reduced = np.asarray(reduced, dtype=np.float32)
    if audio.channels > 1 and reduced.ndim == 2:
        reduced = reduced.T

    denoised_audio = _float_to_audio(audio, reduced)

    duration = time.time() - start_time
    logger.info(f"[DENOISE] {label} denoising took {duration:.1f}s")
    return denoised_audio
