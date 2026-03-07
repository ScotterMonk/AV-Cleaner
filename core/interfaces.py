# core/interfaces.py

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Any

@dataclass
class AudioFilter:
    filter_name: str
    params: Dict[str, Any]

@dataclass
class EditManifest:
    """
    The recipe for the final video.
    """
    # Time ranges (start, end) from the ORIGINAL file to keep.
    # If empty, the whole file is kept.
    keep_segments: List[Tuple[float, float]] = field(default_factory=list)

    # Pause removal bookkeeping (original timeline segments REMOVED).
    # - Used for logging + optional pause-removal log file.
    # - Render logic MUST continue to rely on keep_segments only.
    pause_removals: List[Tuple[float, float]] = field(default_factory=list)

    # True when the pause-removal processor ran (even if zero pauses detected).
    pause_removal_applied: bool = False
    
    # FFmpeg filters to apply to the Host Track
    host_filters: List[AudioFilter] = field(default_factory=list)
    
    # FFmpeg filters to apply to the Guest Track
    guest_filters: List[AudioFilter] = field(default_factory=list)

    def add_host_filter(self, name, **kwargs):
        self.host_filters.append(AudioFilter(name, kwargs))

    def add_guest_filter(self, name, **kwargs):
        self.guest_filters.append(AudioFilter(name, kwargs))

