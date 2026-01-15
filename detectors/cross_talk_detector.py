# detectors/cross_talk_detector.py

from .base_detector import BaseDetector
from analyzers.audio_envelope import calculate_db_envelope
import numpy as np
from typing import List, Tuple

class CrossTalkDetector(BaseDetector):
    """
    Detects pauses where BOTH speakers are silent simultaneously.
    This prevents cutting when one person speaks while the other listens.
    
    Critical for quality: Only removes awkward pauses, not natural turn-taking.
    """
    
    def detect(self, host_audio, guest_audio) -> List[Tuple[float, float]]:
        """
        Detect mutual silence regions (both speakers silent) that exceed max_pause_duration.
        
        Returns only the EXCESS portion to remove (keeps max_pause_duration as natural pause).
        
        Example: 5-second pause with max_pause_duration=1.2s
          - Detected: 0.0 to 5.0 (5s total)
          - Returned: 1.2 to 5.0 (3.8s to remove, keeps 1.2s natural pause)
        
        Handles edge cases:
        - Cross-talk: One speaks while other listens → KEEP
        - Turn-taking: Natural back-and-forth → KEEP
        - True pause: Both silent > max_pause_duration → REMOVE EXCESS
        """
        from utils.logger import get_logger
        logger = get_logger(__name__)
        
        threshold_db = self.config.get('silence_threshold_db', -45)
        min_duration = self.config.get('max_pause_duration', 2.5)
        window_ms = self.config.get('silence_window_ms', 100)
        
        logger.info(f"CrossTalkDetector config: threshold={threshold_db}dB, max_pause_duration={min_duration}s, window={window_ms}ms")
        
        # Step 1: Calculate dB envelopes for both tracks
        host_db = calculate_db_envelope(host_audio, window_ms)
        guest_db = calculate_db_envelope(guest_audio, window_ms)

        # Step 1b: Align envelope lengths.
        #
        # Real-world extractions can differ by a few samples/windows due to container
        # timestamps or rounding (even when the videos are meant to be synced).
        # For mutual-silence detection, we prefer padding the *shorter* envelope with
        # silence so the logical AND remains time-aligned with the longer track.
        host_db, guest_db = self._pad_envelopes_to_equal_length(
            host_db,
            guest_db,
            silence_db_floor=-200.0,
        )
        
        # Step 2: Identify silent frames in each track
        host_silent = host_db < threshold_db
        guest_silent = guest_db < threshold_db
        
        # Step 3: CRITICAL - Mutual silence detection
        # A frame is "truly silent" ONLY when BOTH speakers are silent
        mutual_silence = host_silent & guest_silent
        
        # Step 4: Find continuous mutual silence regions
        mutual_silence_regions = self._find_continuous_regions(
            mutual_silence,
            min_duration,
            host_audio.frame_rate,
            window_ms
        )
        
        # Step 5: Verify each region and trim to keep only max_pause_duration
        verified_regions = []
        for start, end in mutual_silence_regions:
            if self._verify_mutual_silence(
                host_audio, guest_audio, start, end, threshold_db
            ):
                # Only remove the EXCESS beyond max_pause_duration
                # Example: 5s pause with max_duration=1.2s → remove 1.2s to 5.0s (keep first 1.2s)
                trimmed_start = start + min_duration
                if trimmed_start < end:
                    verified_regions.append((trimmed_start, end))
                    logger.debug(f"Detected pause {start:.2f}s to {end:.2f}s (duration={(end-start):.2f}s) → removing {trimmed_start:.2f}s to {end:.2f}s (excess={(end-trimmed_start):.2f}s)")
        
        logger.info(f"Found {len(verified_regions)} pauses to remove (total excess time)")
        return verified_regions

    @staticmethod
    def _pad_envelopes_to_equal_length(
        host_db: np.ndarray,
        guest_db: np.ndarray,
        silence_db_floor: float = -200.0,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Pad the shorter dB envelope with silence so both arrays have equal length."""

        host_len = int(host_db.shape[0])
        guest_len = int(guest_db.shape[0])

        if host_len == guest_len:
            return host_db, guest_db

        target_len = max(host_len, guest_len)

        if host_len < target_len:
            host_db = np.pad(
                host_db,
                (0, target_len - host_len),
                mode="constant",
                constant_values=silence_db_floor,
            )

        if guest_len < target_len:
            guest_db = np.pad(
                guest_db,
                (0, target_len - guest_len),
                mode="constant",
                constant_values=silence_db_floor,
            )

        return host_db, guest_db
    
    def _find_continuous_regions(self, mask, min_duration, sample_rate, window_ms):
        """Find continuous True regions in boolean mask"""
        regions = []
        start = None
        
        for i, is_silent in enumerate(mask):
            if is_silent and start is None:
                start = i
            elif not is_silent and start is not None:
                duration = (i - start) * window_ms / 1000
                if duration >= min_duration:
                    start_time = start * window_ms / 1000
                    end_time = i * window_ms / 1000
                    regions.append((start_time, end_time))
                start = None
        
        # Handle case where silence extends to end
        if start is not None:
            duration = (len(mask) - start) * window_ms / 1000
            if duration >= min_duration:
                start_time = start * window_ms / 1000
                end_time = len(mask) * window_ms / 1000
                regions.append((start_time, end_time))
        
        return regions
    
    def _verify_mutual_silence(self, host_audio, guest_audio, 
            start, end, threshold_db):
        """
        Double-check that detected region is truly mutual silence.
        Quality gate to prevent false positives.
        """
        # Extract segments (pydub uses milliseconds)
        host_segment = host_audio[int(start*1000):int(end*1000)]
        guest_segment = guest_audio[int(start*1000):int(end*1000)]
        
        # Check max dB in each segment
        host_max = host_segment.max_dBFS if len(host_segment) > 0 else -100
        guest_max = guest_segment.max_dBFS if len(guest_segment) > 0 else -100
        
        return (host_max < threshold_db) and (guest_max < threshold_db)
    
    def get_name(self) -> str:
        return "cross_talk_detector"
