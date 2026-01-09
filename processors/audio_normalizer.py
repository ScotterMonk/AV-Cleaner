# processors/audio_normalizer.py

from .base_processor import BaseProcessor
from analyzers.audio_level_analyzer import calculate_lufs

class AudioNormalizer(BaseProcessor):
    def process(self, manifest, host_audio, guest_audio, detection_results):
        config = self.config['normalization']
        mode = config.get('mode', 'MATCH_HOST')
        
        # Calculate integrated LUFS
        host_lufs = calculate_lufs(host_audio)
        guest_lufs = calculate_lufs(guest_audio)
        
        if mode == 'MATCH_HOST':
            # Target is Host's level
            diff = host_lufs - guest_lufs
            
            # Apply safety clamp
            gain_to_apply = min(diff, config.get('max_gain_db', 15.0))
            
            # Add filter instructions
            # Host gets NO filter (it is the reference)
            # Guest gets volume filter
            manifest.add_guest_filter('volume', volume=f"{gain_to_apply}dB")
            
        elif mode == 'STANDARD_LUFS':
            target = config.get('standard_target', -16.0)
            
            # Use FFmpeg's loudnorm for professional correction on BOTH
            manifest.add_host_filter('loudnorm', I=target, TP=-1.5, LRA=11)
            manifest.add_guest_filter('loudnorm', I=target, TP=-1.5, LRA=11)
            
        return manifest
    
    def get_name(self): return "AudioNormalizer"