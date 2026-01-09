# detectors/base_detector.py

from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any

class BaseDetector(ABC):
    """
    Abstract Base Class for all audio detectors.
    Enforces the structure for Silence, Cross-Talk, and Spike detectors.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize with the full configuration dictionary.
        """
        self.config = config

    @abstractmethod
    def detect(self, host_audio, guest_audio) -> List[Tuple[float, float]]:
        """
        Analyze audio and return a list of timestamps.
        
        Args:
            host_audio: Pydub AudioSegment for the host track
            guest_audio: Pydub AudioSegment for the guest track
            
        Returns:
            List of (start_time, end_time) tuples in seconds.
            Example: [(0.5, 2.1), (10.0, 12.5)]
        """
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """
        Return the unique name of this detector for logging/results.
        Example: 'cross_talk_detector'
        """
        pass
    
    def validate_config(self) -> bool:
        """
        Optional: Check if the required settings exist in self.config.
        Returns True by default. Override in subclasses if strict validation is needed.
        """
        return True