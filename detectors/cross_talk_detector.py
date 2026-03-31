# detectors/cross_talk_detector.py

from .base_detector import BaseDetector
from analyzers.audio_envelope import calculate_db_envelope
import numpy as np
from typing import List, Tuple


# Modified by gpt-5.2 | 2026-01-19_01
class CrossTalkDetector(BaseDetector):
    """
    Detects pauses where BOTH speakers are silent simultaneously.
    This prevents cutting when one person speaks while the other listens.
    
    Critical for quality: Only removes awkward pauses, not natural turn-taking.
    """
    
    # Modified by gpt-5.2 | 2026-01-19_01
    def detect(self, host_audio, guest_audio, detection_results=None) -> List[Tuple[float, float]]:
        """
        Detect mutual silence regions (both speakers silent) that exceed `max_pause_duration`.

        For each detected pause region (start..end), we *replace the entire pause* with a
        fixed-length pause of `new_pause_duration` by removing only the *excess* beyond
        `new_pause_duration`.

        Example: 5-second pause with max_pause_duration=1.2s and new_pause_duration=0.5s
          - Detected: 0.0 to 5.0 (5s total)
          - Returned: 0.5 to 5.0 (4.5s to remove, keeps 0.5s replacement pause)
        
        Handles edge cases:
        - Cross-talk: One speaks while other listens -> KEEP
        - Turn-taking: Natural back-and-forth -> KEEP
        - True pause: Both silent > max_pause_duration -> REMOVE EXCESS
        """
        from utils.logger import format_time_cut, get_logger
        logger = get_logger(__name__)

        # Self-healing: apply in-memory filler-word mutes to local copies so that
        # a muted word adjacent to natural silence expands the mutual-silence zone.
        # The shared audio objects passed by the pipeline are NOT modified.
        filler_results = (detection_results or {}).get("filler_word_detector", [])
        if filler_results:
            from utils.audio_helpers import audio_apply_mutes

            host_mute_ranges = [
                (seg["start_sec"], seg["end_sec"])
                for seg in filler_results
                if isinstance(seg, dict) and str(seg.get("track", "")).lower() == "host"
            ]
            guest_mute_ranges = [
                (seg["start_sec"], seg["end_sec"])
                for seg in filler_results
                if isinstance(seg, dict) and str(seg.get("track", "")).lower() == "guest"
            ]
            if host_mute_ranges:
                host_audio = audio_apply_mutes(host_audio, host_mute_ranges)
                logger.debug(
                    "[CrossTalkDetector] Applied %d host filler-word mute(s) to local copy for analysis",
                    len(host_mute_ranges),
                )
            if guest_mute_ranges:
                guest_audio = audio_apply_mutes(guest_audio, guest_mute_ranges)
                logger.debug(
                    "[CrossTalkDetector] Applied %d guest filler-word mute(s) to local copy for analysis",
                    len(guest_mute_ranges),
                )

        threshold_db = self.config.get("silence_threshold_db", -45)
        max_pause_duration = self.config.get("max_pause_duration", 2.5)
        new_pause_duration = self.config.get("new_pause_duration", 0.5)
        window_ms = self.config.get("silence_window_ms", 100)

        # Safety clamps:
        # - new_pause_duration cannot be negative.
        # - If new_pause_duration is longer than the detected pause, we remove nothing.
        try:
            new_pause_duration = max(0.0, float(new_pause_duration))
        except (TypeError, ValueError):
            new_pause_duration = 0.5

        logger.info(
            "CrossTalkDetector config: threshold=%sdB, max_pause_duration=%ss, new_pause_duration=%ss, window=%sms",
            threshold_db,
            max_pause_duration,
            new_pause_duration,
            window_ms,
        )
        
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
            max_pause_duration,
            host_audio.frame_rate,
            window_ms
        )

        # Step 4b: Protect recording boundaries.
        # Silence at the very beginning (pre-show countdown, intro) and the very
        # end (outro, wrap-up) is a natural recording boundary — not an
        # awkward mid-conversation pause.  Noise reduction can lower the noise
        # floor enough to make these regions register as "true silence" even
        # though they were previously masked by room tone.  Removing them
        # chops off the recording head/tail and surprises the user.
        if mutual_silence_regions:
            one_window_s = window_ms / 1000.0
            # Derive duration from the envelope length (already aligned in Step 1b)
            # so the guard works regardless of whether the audio object exposes
            # duration_seconds (test mocks may not).
            audio_dur_s = len(host_db) * one_window_s

            pre_guard_count = len(mutual_silence_regions)
            mutual_silence_regions = [
                (s, e) for s, e in mutual_silence_regions
                if s >= one_window_s and (audio_dur_s - e) >= one_window_s
            ]
            skipped = pre_guard_count - len(mutual_silence_regions)
            if skipped:
                logger.info(
                    "[DETECTOR] Skipped %d boundary pause(s) at head/tail of recording",
                    skipped,
                )

        # Step 5: Verify each region and remove only the portion beyond new_pause_duration
        verified_regions = []
        for start, end in mutual_silence_regions:
            if self._verify_mutual_silence(
                host_audio, guest_audio, start, end, threshold_db
            ):
                # Replace the entire pause with `new_pause_duration`.
                # That means we keep the first `new_pause_duration` seconds of the pause and
                # remove the remaining portion.
                keep_len = min(new_pause_duration, max(0.0, end - start))
                trimmed_start = start + keep_len
                if trimmed_start < end:
                    verified_regions.append((trimmed_start, end))
                    logger.debug(
                        "Detected pause %.2fs to %.2fs (duration=%.2fs) -> removing %.2fs to %.2fs (excess=%.2fs)",
                        start,
                        end,
                        (end - start),
                        trimmed_start,
                        end,
                        (end - trimmed_start),
                    )
        
        total_seconds = sum(end - start for start, end in verified_regions)
        logger.info(
            "[DETECTOR] Found %s pauses (total duration: %s to remove)",
            len(verified_regions),
            format_time_cut(total_seconds),
        )
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

        Uses sub-window RMS checking: the segment is split into small windows
        (200 ms each) and if ANY sub-window in EITHER track exceeds the
        silence threshold, the region is rejected.  This catches brief speech
        (e.g. "yeah", "mm-hmm") buried inside an otherwise-silent region that
        would pass a whole-segment RMS check because the speech energy gets
        averaged out across a long pause.
        """
        from utils.logger import get_logger
        logger = get_logger(__name__)

        # Sub-window size for verification (ms).  Smaller = more sensitive to
        # brief speech within the pause.  200 ms catches single syllables
        # without being so small that a single loud sample triggers rejection.
        verify_window_ms = 200

        start_ms = int(start * 1000)
        end_ms = int(end * 1000)

        host_segment = host_audio[start_ms:end_ms]
        guest_segment = guest_audio[start_ms:end_ms]

        seg_len_ms = len(host_segment)
        if seg_len_ms == 0:
            return False

        # Walk through sub-windows; reject if ANY window has speech.
        offset = 0
        while offset < seg_len_ms:
            win_end = min(offset + verify_window_ms, seg_len_ms)
            h_win = host_segment[offset:win_end]
            g_win = guest_segment[offset:win_end]

            h_db = h_win.dBFS if len(h_win) > 0 else -100.0
            g_db = g_win.dBFS if len(g_win) > 0 else -100.0

            # If EITHER speaker is above the threshold in this window,
            # someone is talking — this is NOT true mutual silence.
            if h_db >= threshold_db or g_db >= threshold_db:
                logger.debug(
                    "Verify rejected pause %.2fs-%.2fs: sub-window at +%dms "
                    "has host=%.1fdB / guest=%.1fdB (threshold=%.1fdB)",
                    start, end, offset, h_db, g_db, threshold_db,
                )
                return False

            offset = win_end

        return True
    
    def get_name(self) -> str:
        return "cross_talk_detector"
