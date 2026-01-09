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
        Detect mutual silence regions (both speakers silent).
        
        Handles edge cases:
        - Cross-talk: One speaks while other listens → KEEP
        - Turn-taking: Natural back-and-forth → KEEP  
        - True pause: Both silent > threshold → REMOVE
        """
        threshold_db = self.config.get('silence_threshold_db', -45)
        min_duration = self.config.get('min_pause_duration', 2.5)
        window_ms = self.config.get('silence_window_ms', 100)
        
        # Step 1: Calculate dB envelopes for both tracks
        host_db = calculate_db_envelope(host_audio, window_ms)
        guest_db = calculate_db_envelope(guest_audio, window_ms)
        
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
        
        # Step 5: Verify each region (quality gate)
        verified_regions = []
        for start, end in mutual_silence_regions:
            if self._verify_mutual_silence(
                host_audio, guest_audio, start, end, threshold_db
            ):
                verified_regions.append((start, end))
        
        return verified_regions
    
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