# main.py

import os
import sys
import time

# Ensure current directory is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import click

from core.pipeline import ProcessingPipeline
from detectors.cross_talk_detector import CrossTalkDetector
from detectors.spike_fixer_detector import SpikeFixerDetector
from io_.media_preflight import normalize_video_lengths
from processors.spike_fixer import SpikeFixer
from processors.audio_normalizer import AudioNormalizer
from processors.segment_remover import SegmentRemover
from config import QUALITY_PRESETS, PIPELINE_CONFIG
from utils.logger import format_duration, setup_logger


_ACTION_CHOICES = [
    "ALL",
    "NORMALIZE_GUEST_AUDIO",
    "REMOVE_PAUSES",
]


_PROCESSOR_REGISTRY = {
    "SegmentRemover": SegmentRemover,
    "AudioNormalizer": AudioNormalizer,
    "SpikeFixer": SpikeFixer,
}


def _pipeline_component_enabled(group: str, type_name: str) -> bool:
    """Return True when PIPELINE_CONFIG[group] has an enabled entry for type_name."""
    for entry in PIPELINE_CONFIG.get(group, []):
        if str(entry.get("type")) == type_name:
            return bool(entry.get("enabled"))
    return False


def _register_enabled_processors(pipeline: ProcessingPipeline, config: dict) -> None:
    """Register enabled processors (user-facing). Required detectors are added automatically."""
    for entry in PIPELINE_CONFIG.get("processors", []):
        if not entry.get("enabled"):
            continue
        t = str(entry.get("type"))
        cls = _PROCESSOR_REGISTRY.get(t)
        if cls is None:
            raise click.ClickException(f"Unknown processor type in PIPELINE_CONFIG: {t!r}")
        pipeline.add_processor(cls(config))


def _register_required_detectors(pipeline: ProcessingPipeline) -> None:
    """Add detectors implied by enabled processors (not user-facing)."""
    # SegmentRemover requires mutual-silence detection.
    if _pipeline_component_enabled("processors", "SegmentRemover"):
        pipeline.add_detector(CrossTalkDetector(pipeline.config))

    # SpikeFixer requires spike detection.
    if _pipeline_component_enabled("processors", "SpikeFixer"):
        pipeline.add_detector(SpikeFixerDetector(pipeline.config))


def _build_pipeline(config: dict, action: str) -> ProcessingPipeline:
    pipeline = ProcessingPipeline(config)

    if action == "NORMALIZE_GUEST_AUDIO":
        # Normalization runs by analyzing host+guest loudness.
        pipeline.add_processor(AudioNormalizer(config))

        # If SpikeFixer is enabled in PIPELINE_CONFIG, include it in this workflow.
        # (SpikeFixer requires SpikeFixerDetector outputs.)
        if _pipeline_component_enabled("processors", "SpikeFixer"):
            pipeline.add_detector(SpikeFixerDetector(config))
            pipeline.add_processor(SpikeFixer(config))
        return pipeline

    if action == "REMOVE_PAUSES":
        # Pause removal is mutual-silence detection + manifest keep_segments.
        pipeline.add_detector(CrossTalkDetector(config))
        pipeline.add_processor(SegmentRemover(config))
        return pipeline

    if action != "ALL":
        raise click.ClickException(f"Unknown action: {action!r}")

    _register_enabled_processors(pipeline, config)
    _register_required_detectors(pipeline)
    return pipeline

@click.command()
@click.option('--host', required=True, help='Host video path')
@click.option('--guest', required=True, help='Guest video path')
@click.option('--action', type=click.Choice(_ACTION_CHOICES), default='ALL', show_default=True,
              help='Which action to run')
@click.option('--norm-mode', type=click.Choice(['MATCH_HOST', 'STANDARD_LUFS']), 
              help='Override normalization mode')
def main(host, guest, action, norm_mode):
    """
    Video Automation Tool: Sync-safe cleaning and normalization.
    """
    logger = setup_logger()
    action_start_time = time.time()
    logger.info(f"[ACTION START] {action}")

    subfunction_name = None
    if action == "NORMALIZE_GUEST_AUDIO":
        subfunction_name = "Normalize Guest Audio"
    elif action == "REMOVE_PAUSES":
        subfunction_name = "Remove pauses"

    # Preflight: ensure host+guest durations are aligned for all actions (even guest-only).
    host, guest = normalize_video_lengths(host, guest)
     
    # Load Config
    config = QUALITY_PRESETS['PODCAST_HIGH_QUALITY'].copy()
    if norm_mode:
        config['normalization']['mode'] = norm_mode

    # Init Pipeline
    pipeline = _build_pipeline(config, action)
 
    # Run
    try:
        # Always render both host+guest outputs so the GUI/CLI can reliably switch to
        # a stable processed pair after any action (even guest-only workflows).
        if subfunction_name:
            logger.info(f"[SUBFUNCTION START] {subfunction_name}")

        h_out, g_out = pipeline.execute(host, guest)

        if subfunction_name:
            logger.info(f"[SUBFUNCTION COMPLETE] {subfunction_name}")

        created = [p for p in [h_out, g_out] if p]

        action_duration = time.time() - action_start_time
        logger.info(
            f"[ACTION COMPLETE] {action} - Duration: {format_duration(action_duration)}"
        )

        logger.info("Success! Files created:\n" + "\n".join(created))
    except Exception as e:
        if subfunction_name:
            logger.info(f"[SUBFUNCTION FAILED] {subfunction_name}")
        logger.error(f"Processing failed: {str(e)}")
        raise

if __name__ == '__main__':
    main()
