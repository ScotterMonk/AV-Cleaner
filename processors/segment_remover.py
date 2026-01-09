# processors/segment_remover.py

from .base_processor import BaseProcessor
from core.interfaces import EditManifest
from typing import List, Tuple

class SegmentRemover(BaseProcessor):
    """
    Translates detected 'silence/bad' segments into 'keep/good' segments
    for the EditManifest.
    """

    def process(self, manifest: EditManifest, host_audio, guest_audio, detection_results) -> EditManifest:
        # 1. Get the list of "Bad" segments (Pauses/Cross-talk)
        # These are the times we want to REMOVE.
        pauses = detection_results.get('cross_talk_detector', [])
        
        # If no pauses detected, we keep the whole file.
        if not pauses:
            return manifest
            
        # 2. Get total duration from the host audio
        # (Assuming host/guest are synchronized and roughly same length)
        total_duration = host_audio.duration_seconds
        
        # 3. Calculate the "Inverse" (The segments to KEEP)
        keep_segments = self._invert_segments(pauses, total_duration)
        
        # 4. Update the Manifest
        # The Renderer will look at this list to generate FFmpeg trim commands
        manifest.keep_segments = keep_segments
        
        return manifest

    def _invert_segments(self, remove_segments: List[Tuple[float, float]], total_duration: float) -> List[Tuple[float, float]]:
        """
        Converts a list of segments to REMOVE into a list of segments to KEEP.
        
        Example:
            Duration: 10.0
            Remove: [(2.0, 4.0), (8.0, 9.0)]
            Result: [(0.0, 2.0), (4.0, 8.0), (9.0, 10.0)]
        """
        keep_segments = []
        current_time = 0.0
        
        # Sort just in case detection results came in out of order
        sorted_removals = sorted(remove_segments, key=lambda x: x[0])
        
        for start_remove, end_remove in sorted_removals:
            # If there is a gap between current time and the start of the cut, KEEP it.
            if start_remove > current_time:
                keep_segments.append((current_time, start_remove))
            
            # Move our pointer to the end of the cut
            current_time = max(current_time, end_remove)
            
        # Capture the final segment (from last cut to end of file)
        if current_time < total_duration:
            keep_segments.append((current_time, total_duration))
            
        return keep_segments

    def get_name(self) -> str:
        return "SegmentRemover"