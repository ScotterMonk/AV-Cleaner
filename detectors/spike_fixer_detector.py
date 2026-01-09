# detectors/spike_fixer_detector.py

from .base_detector import BaseDetector
from typing import List, Tuple

import numpy as np

class SpikeFixerDetector(BaseDetector):
    """
    Detects audio spikes (peaks) above threshold.
    Used to identify segments that need limiting/compression.
    """
    
    # Modified by gpt-5.2 | 2026-01-09_02
    def detect(self, host_audio, guest_audio) -> List[Tuple[float, float]]:
        """Detect audio spikes in guest audio only."""

        # Only analyze guest audio for spikes.
        audio = guest_audio

        threshold_db = self.config.get("spike_threshold_db", -6)
        window_ms = self.config.get("spike_window_ms", 50)

        # IMPORTANT: frame-accurate windowing for mono/stereo.
        # - Convert window_ms -> window_frames using frame_rate.
        # - Window over frames (not samples).
        # - Peak across ALL channels.
        sample_rate = int(audio.frame_rate)
        window_frames = int(sample_rate * window_ms / 1000)
        window_frames = max(1, window_frames)

        samples = np.asarray(audio.get_array_of_samples())
        peaks_db, _num_frames = self._window_peaks_db(
            samples,
            channels=int(audio.channels),
            window_frames=window_frames,
            sample_width=int(audio.sample_width),
        )

        duration_seconds = float(audio.duration_seconds)
        spike_window_idxs = np.nonzero(peaks_db > threshold_db)[0]
        spike_regions = [
            (
                (int(window_idx) * window_frames) / sample_rate,
                min(((int(window_idx) + 1) * window_frames) / sample_rate, duration_seconds),
            )
            for window_idx in spike_window_idxs
        ]

        # Merge adjacent spikes
        merged = self._merge_adjacent_regions(spike_regions, gap_threshold=0.1)

        return merged

    # Created-or-Modified by gpt-5.2 | 2026-01-09_01
    @staticmethod
    def _window_peaks_db(
        samples: np.ndarray,
        *,
        channels: int,
        window_frames: int,
        sample_width: int,
        min_ratio: float = 1e-10,
    ) -> Tuple[np.ndarray, int]:
        """Compute peak dBFS per frame-window (vectorized).

        Important: `samples` must be interleaved PCM samples as returned by
        `audio.get_array_of_samples()`.

        Returns:
            (peaks_db, num_frames)
        Where:
            peaks_db is shape (num_windows,) and computed across ALL channels.
            num_frames is the number of source frames (before padding).
        """

        if channels <= 0:
            raise ValueError("channels must be >= 1")

        # Clamp to at least 1 to avoid divide-by-zero and reshape issues.
        window_frames = max(1, int(window_frames))

        if sample_width <= 0:
            raise ValueError("sample_width must be >= 1")

        # NOTE: The project usually operates on extracted WAV audio; common PCM
        # widths are 1/2/3/4 bytes. We keep this generic, but sanity-check
        # absurd widths so shifts don't explode.
        if sample_width > 8:
            raise ValueError("sample_width must be <= 8")

        # Ensure integer type before abs() to avoid int16 overflow at -32768.
        # (np.abs(np.int16(-32768)) == -32768)
        samples_i32 = np.asarray(samples)
        if not np.issubdtype(samples_i32.dtype, np.signedinteger):
            samples_i32 = samples_i32.astype(np.int32, copy=False)
        else:
            samples_i32 = samples_i32.astype(np.int32, copy=False)

        # Frame-accurate windowing for mono/stereo: reshape interleaved samples
        # into (num_frames, channels) and window over frames.
        num_frames = int(samples_i32.size // channels)
        if num_frames <= 0:
            return np.asarray([], dtype=np.float64), 0

        usable = samples_i32[: num_frames * channels]
        frames = usable.reshape((num_frames, channels))

        # Pad trailing frames to a multiple of window_frames so we can reshape
        # into (num_windows, window_frames, channels) in one go.
        pad_frames = (-num_frames) % window_frames
        if pad_frames:
            frames = np.pad(frames, ((0, pad_frames), (0, 0)), mode="constant")

        num_windows = frames.shape[0] // window_frames
        windows = frames.reshape((num_windows, window_frames, channels))

        # Peak across all samples in the window across channels.
        peaks = np.max(np.abs(windows), axis=(1, 2)).astype(np.float64, copy=False)

        # Convert to dBFS where 0 dBFS == full scale. Derive full scale from
        # sample_width (bytes) rather than hardcoding 32768.
        full_scale = float(1 << ((8 * sample_width) - 1))
        ratio = peaks / full_scale
        peaks_db = 20.0 * np.log10(np.maximum(ratio, min_ratio))

        return peaks_db, num_frames
    
    def _merge_adjacent_regions(self, regions, gap_threshold=0.1):
        """Merge regions that are close together"""
        if not regions:
            return []
        
        merged = [regions[0]]
        
        for start, end in regions[1:]:
            last_start, last_end = merged[-1]
            
            if start - last_end <= gap_threshold:
                # Merge with previous region
                merged[-1] = (last_start, end)
            else:
                merged.append((start, end))
        
        return merged
    
    def get_name(self) -> str:
        return "spike_fixer_detector"
