# detectors/filler_word_detector.py

from .base_detector import BaseDetector
from typing import List, Tuple

class FillerWordDetector(BaseDetector):
    """
    FUTURE FEATURE: Detects filler words using AI transcription.
    Example: "uhh", "umm", "like", "you know"
    
    Requires: whisper, faster-whisper, or similar AI model
    """
    
    def detect(self, host_audio, guest_audio) -> List[Tuple[float, float]]:
        """Detect filler words using AI transcription"""
        # Placeholder for future implementation
        # 
        # Implementation would:
        # 1. Transcribe audio with word-level timestamps
        # 2. Identify filler words
        # 3. Return their time ranges
        #
        # Example with Whisper:
        # import whisper
        # model = whisper.load_model("base")
        # result = model.transcribe(audio, word_timestamps=True)
        # 
        # filler_segments = []
        # for segment in result['segments']:
        #     for word in segment['words']:
        #         if word['word'].lower() in self.config['filler_words']:
        #             filler_segments.append((word['start'], word['end']))
        
        return []
    
    def get_name(self) -> str:
        return "filler_word_detector"
    
    def validate_config(self) -> bool:
        """Check if AI model is available"""
        # For now, always disabled
        return False