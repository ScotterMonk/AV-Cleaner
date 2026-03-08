# processors/word_remover.py
#
# Translates FillerWordDetector results into removal ranges on the EditManifest.
#
# Uses the same manifest accumulator pattern as SegmentRemover:
#   manifest.add_removal() → manifest.compute_keep_segments()
# Because compute_keep_segments() always derives keep_segments from the full
# accumulated removal_segments list, WordRemover and SegmentRemover can run in
# any order without clobbering each other's cuts.

from .base_processor import BaseProcessor
from core.interfaces import EditManifest
from utils.logger import get_logger, format_time_cut

logger = get_logger(__name__)


class WordRemover(BaseProcessor):
    """
    Reads filler_word_detector results and appends them to the shared
    removal accumulator on the EditManifest.

    Both host and guest videos receive identical cuts (sync-safe), matching
    the behaviour of SegmentRemover.
    """

    def process(
        self, manifest: EditManifest, host_audio, guest_audio, detection_results
    ) -> EditManifest:
        # Mark that word-removal ran for this pipeline execution.
        manifest.word_removal_applied = True

        word_segments = detection_results.get("filler_word_detector", [])

        # If no words detected, leave the manifest unchanged.
        if not word_segments:
            logger.info("[WordRemover] No filler words detected — nothing to remove.")
            return manifest

        sorted_words = sorted(word_segments, key=lambda x: x[0])

        # Keep a copy for end-of-run logging (mirrors pause_removals on SegmentRemover).
        manifest.word_removals = list(sorted_words)

        # Log each removal against the original timeline.
        for start_s, end_s in sorted_words:
            logger.info(
                "[WordRemover] Remove %.3fs–%.3fs (%.0fms)",
                start_s,
                end_s,
                (end_s - start_s) * 1000,
            )

        # Accumulate into the shared removal list, then (re)derive keep_segments.
        # If SegmentRemover already ran, its removals are already in removal_segments
        # and the recomputed keep_segments will be their union.
        for start_s, end_s in sorted_words:
            manifest.add_removal(start_s, end_s)

        total_duration = host_audio.duration_seconds
        manifest.compute_keep_segments(total_duration)

        total_removed = sum(end - start for start, end in sorted_words)
        logger.info(
            "[PROCESSOR COMPLETE] Removed %d filler word(s) from both videos (sync-safe)"
            " - Total time cut: %s",
            len(sorted_words),
            format_time_cut(total_removed),
        )

        return manifest

    def get_name(self) -> str:
        return "WordRemover"
