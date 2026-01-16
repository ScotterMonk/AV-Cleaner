# core/pipeline.py

import time

from .interfaces import EditManifest
from io_ import audio_extractor
from io_ import video_renderer
from utils.path_helpers import make_processed_output_path
from utils.logger import get_logger

from pathlib import Path

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
        phase1_start = time.time()
         
        # 1. Extract Audio to RAM/Temp (Fast pydub loading)
        host_audio = audio_extractor.extract_audio(host_video_path)
        guest_audio = audio_extractor.extract_audio(guest_video_path)
         
        # 2. Run Detectors (Generate Detection Results)
        detection_results = {}
        for detector in self.detectors:
            logger.info(f"Running {detector.get_name()}...")
            detection_results[detector.get_name()] = detector.detect(host_audio, guest_audio)

        from utils.logger import format_duration

        phase1_duration = time.time() - phase1_start
        logger.info(f"Phase 1 complete - Duration: {format_duration(phase1_duration)}")

        # 3. Run Processors (Build the Manifest)
        logger.info("Phase 2: Building Edit Manifest")
        phase2_start = time.time()
        manifest = EditManifest()
         
        for processor in self.processors:
            processor_name = str(processor.get_name())
            logger.info(f"Running {processor_name}...")

            # Mirror user-facing subfunction start/end markers.
            # These are used by the GUI PROGRESS pane to show an action-style timeline.
            friendly = None
            if processor_name == "AudioNormalizer":
                friendly = "Normalize Guest Audio"
            elif processor_name == "SegmentRemover":
                friendly = "Remove pauses"
            elif processor_name == "SpikeFixer":
                spike_regions = detection_results.get("spike_fixer_detector", []) or []
                friendly = f"Remove {len(spike_regions)} audio spikes in guest video"

            if friendly:
                logger.info(f"[SUBFUNCTION START] {friendly}")

            manifest = processor.process(manifest, host_audio, guest_audio, detection_results)

            if friendly:
                logger.info(f"[SUBFUNCTION COMPLETE] {friendly}")

        phase2_duration = time.time() - phase2_start
        logger.info(f"Phase 2 complete - Duration: {format_duration(phase2_duration)}")

        # 4. Render (FFmpeg Execution)
        logger.info("Phase 3: Rendering (This may take time)")
        phase3_start = time.time()
        # Output container is MP4 regardless of input container.
        host_out = make_processed_output_path(host_video_path) if render_host else None
        guest_out = make_processed_output_path(guest_video_path) if render_guest else None
        
        video_renderer.render_project(
            host_video_path, guest_video_path, 
            manifest, 
            host_out, guest_out, 
            self.config
        )

        phase3_duration = time.time() - phase3_start
        logger.info(f"Phase 3 complete - Duration: {format_duration(phase3_duration)}")

        # Pause-removal summary + optional log file.
        if getattr(manifest, "pause_removal_applied", False):
            from utils.pause_removal_log import pause_removal_log_write

            removed_count = len(getattr(manifest, "pause_removals", []) or [])
            logger.info(f"{removed_count} pauses removed")

            # Only save a log file when at least one pause was removed.
            if removed_count > 0:
                project_dir = Path(host_video_path).resolve().parent
                log_path = pause_removal_log_write(project_dir, manifest.pause_removals)
                if log_path:
                    logger.info(f"Pause removal log saved: {log_path}")
        
        return host_out, guest_out
