# core/pipeline.py

import inspect
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

    # Modified by gpt-5.4 | 2026-03-08
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
        detection_results = {
            # Detectors can depend on input paths (ex: SpikeFixerDetector FFmpeg analysis).
            "host_video_path": host_video_path,
            "guest_video_path": guest_video_path,
        }

        detector_names = [d.get_name() for d in self.detectors]
        logger.info("[DETECTOR] Execution order: %s", " -> ".join(detector_names) if detector_names else "(none)")

        for idx, detector in enumerate(self.detectors):
            detector_name = detector.get_name()
            logger.info("Running %s (%s/%s)...", detector_name, idx + 1, len(self.detectors))

            # Dependency/ordering logging: what is available to this detector right now.
            available_keys = sorted(detection_results.keys())
            logger.debug(
                "[DETECTOR] %s starting; available prior results: %s",
                detector_name,
                ", ".join(available_keys) if available_keys else "(none)",
            )

            # Pass accumulated detection_results when the detector supports it.
            supports_detection_results = False
            try:
                sig = inspect.signature(detector.detect)
                params = list(sig.parameters.values())
                supports_detection_results = any(
                    (p.kind == inspect.Parameter.VAR_KEYWORD) or (p.name == "detection_results")
                    for p in params
                )
            except Exception:
                # If introspection fails, stay conservative and call the legacy 2-arg signature.
                supports_detection_results = False

            if supports_detection_results:
                logger.debug("[DETECTOR] %s will receive accumulated detection_results", detector_name)
                result = detector.detect(host_audio, guest_audio, detection_results)
            else:
                logger.debug("[DETECTOR] %s does not accept detection_results (legacy signature)", detector_name)
                result = detector.detect(host_audio, guest_audio)

            detection_results[detector_name] = result

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
            completion_details = None
            
            if processor_name == "AudioNormalizer":
                friendly = "Normalize Guest Audio"
            elif processor_name == "SegmentRemover":
                friendly = "Remove pauses"
            elif processor_name == "WordRemover":
                friendly = "Remove filler words"
            elif processor_name == "SpikeFixer":
                # Keep user-facing title stable; report spike count after completion.
                friendly = "Remove audio spikes"

            if friendly:
                logger.info(f"[SUBFUNCTION START] {friendly}")

            manifest = processor.process(manifest, host_audio, guest_audio, detection_results)

            # Log [SUBFUNCTION COMPLETE] first
            if friendly:
                logger.info(f"[SUBFUNCTION COMPLETE] {friendly}")

            # Then log details on separate line immediately after with [DETAIL] token for PROGRESS pane
            if processor_name == "SegmentRemover":
                from utils.logger import format_time_cut
                removals = getattr(manifest, "pause_removals", []) or []
                total_removed_seconds = sum(end - start for start, end in removals)
                logger.info(
                    f"[DETAIL] Removed {len(removals)} pause(s) from both Guest and Host videos | "
                    f"Total time removed: {format_time_cut(total_removed_seconds)}"
                )
            elif processor_name == "WordRemover":
                from utils.logger import format_time_cut
                from utils.time_helpers import seconds_to_hms

                word_removals = getattr(manifest, "word_removals", []) or []
                word_removal_details = getattr(manifest, "word_removal_details", []) or []
                total_removed_seconds = sum(end - start for start, end in word_removals)

                host_word_details = [
                    detail
                    for detail in word_removal_details
                    if str(detail.get("track") or "").lower() == "host"
                ]
                guest_word_details = [
                    detail
                    for detail in word_removal_details
                    if str(detail.get("track") or "").lower() == "guest"
                ]

                if host_word_details or guest_word_details:
                    for label, track_details in (("Host", host_word_details), ("Guest", guest_word_details)):
                        if not track_details:
                            continue

                        detail_parts = []
                        removed_count = 0
                        muted_count = 0
                        skipped_count = 0
                        for detail in track_details:
                            timestamp = seconds_to_hms(float(detail["start_sec"]))
                            confidence = float(detail.get("confidence", 0.0) or 0.0)
                            action = str(detail.get("action") or "cut").lower()
                            if action == "mute":
                                muted_count += 1
                            elif action == "skip":
                                skipped_count += 1
                            else:
                                removed_count += 1
                            detail_parts.append(
                                f'"{str(detail.get("text") or "").strip()}" @ {timestamp.split(".", 1)[0]} '
                                f'({action}, confidence: {confidence:.4f})'
                            )

                        logger.info(
                            f"[DETAIL] {label} vid filler words: {removed_count} removed, {muted_count} muted, {skipped_count} skipped | "
                            f"{'; '.join(detail_parts)}"
                        )
                else:
                    logger.info(
                        f"[DETAIL] Removed {len(word_removals)} filler word(s) from both Guest and Host videos | "
                        f"Total time removed: {format_time_cut(total_removed_seconds)}"
                    )
            elif processor_name == "AudioNormalizer":
                gain_db = getattr(manifest, "guest_audio_gain_db_applied", None)
                gain_est_db = getattr(manifest, "guest_audio_gain_db_estimate", None)
                if gain_db is not None:
                    logger.info(f"[DETAIL] Guest audio adjusted: {gain_db:+.1f} dB")
                elif gain_est_db is not None:
                    logger.info(f"[DETAIL] Guest audio adjusted (estimated): {gain_est_db:+.1f} dB")
            elif processor_name == "SpikeFixer":
                spike_regions = detection_results.get("spike_fixer_detector", []) or []
                logger.info(f"[DETAIL] Fixed {len(spike_regions)} audio spike(s) in guest video")

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
        
        return host_out, guest_out
