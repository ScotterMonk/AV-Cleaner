# core/pipeline.py

from .interfaces import EditManifest
from io_ import audio_extractor
from io_ import video_renderer
from utils.path_helpers import make_processed_output_path
from utils.logger import get_logger

logger = get_logger(__name__)

class ProcessingPipeline:
    def __init__(self, config):
        self.config = config
        self.detectors = []
        self.processors = []

    def add_detector(self, detector):
        self.detectors.append(detector)
        return self

    def add_processor(self, processor):
        self.processors.append(processor)
        return self

    def execute(
        self,
        host_video_path: str,
        guest_video_path: str,
        *,
        render_host: bool = True,
        render_guest: bool = True,
    ):
        logger.info("Phase 1: Extraction & Analysis")
        
        # 1. Extract Audio to RAM/Temp (Fast pydub loading)
        host_audio = audio_extractor.extract_audio(host_video_path)
        guest_audio = audio_extractor.extract_audio(guest_video_path)
        
        # 2. Run Detectors (Generate Detection Results)
        detection_results = {}
        for detector in self.detectors:
            logger.info(f"Running {detector.get_name()}...")
            detection_results[detector.get_name()] = detector.detect(host_audio, guest_audio)

        # 3. Run Processors (Build the Manifest)
        logger.info("Phase 2: Building Edit Manifest")
        manifest = EditManifest()
        
        for processor in self.processors:
            logger.info(f"Running {processor.get_name()}...")
            manifest = processor.process(manifest, host_audio, guest_audio, detection_results)

        # 4. Render (FFmpeg Execution)
        logger.info("Phase 3: Rendering (This may take time)")
        # Output container is MP4 regardless of input container.
        host_out = make_processed_output_path(host_video_path) if render_host else None
        guest_out = make_processed_output_path(guest_video_path) if render_guest else None
        
        video_renderer.render_project(
            host_video_path, guest_video_path, 
            manifest, 
            host_out, guest_out, 
            self.config
        )
        
        return host_out, guest_out
