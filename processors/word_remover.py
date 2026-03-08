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
from config import WORDS_TO_REMOVE
from core.interfaces import EditManifest
from utils.logger import get_logger, format_time_cut

logger = get_logger(__name__)


class WordRemover(BaseProcessor):
    """
    Reads filler_word_detector results and appends them to the shared
    removal accumulator on the EditManifest.

    Filler words are cut sync-safely only when the opposite track is silent.
    Otherwise the filler-word span is muted only on the speaking track so the
    other speaker's audio is preserved.
    """

    # Modified by gpt-5.4 | 2026-03-08
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

        cut_words = []
        word_details = []
        for segment in word_segments:
            if isinstance(segment, dict):
                start_s = float(segment["start_sec"])
                end_s = float(segment["end_sec"])
                detail = {
                    "track": str(segment.get("track") or ""),
                    "text": str(segment.get("text") or ""),
                    "start_sec": start_s,
                    "end_sec": end_s,
                    "confidence": float(segment.get("confidence", 0.0) or 0.0),
                }
                action = self._word_action_decide(detail, host_audio, guest_audio)
                detail["action"] = action
                word_details.append(detail)
                if action == "cut":
                    cut_words.append((start_s, end_s))
                elif action == "mute":
                    self._word_mute_add(manifest, detail)
                continue

            start_s, end_s = segment
            cut_words.append((start_s, end_s))
            word_details.append(
                {
                    "track": "",
                    "text": "",
                    "start_sec": start_s,
                    "end_sec": end_s,
                    "confidence": 0.0,
                    "action": "cut",
                }
            )

        sorted_words = sorted(cut_words, key=lambda x: x[0])
        sorted_word_details = sorted(word_details, key=lambda x: x["start_sec"])

        # Keep a copy for end-of-run logging (mirrors pause_removals on SegmentRemover).
        manifest.word_removals = list(sorted_words)
        manifest.word_removal_details = list(sorted_word_details)

        # Log each removal against the original timeline.
        for start_s, end_s in sorted_words:
            logger.info(
                "[WordRemover] Remove %.3fs–%.3fs (%.0fms)",
                start_s,
                end_s,
                (end_s - start_s) * 1000,
            )

        for detail in sorted_word_details:
            if detail.get("action") == "mute":
                logger.info(
                    "[WordRemover] Mute %s word %r at %.3fs–%.3fs (confidence=%.4f)",
                    str(detail.get("track") or "unknown"),
                    str(detail.get("text") or ""),
                    float(detail["start_sec"]),
                    float(detail["end_sec"]),
                    float(detail.get("confidence", 0.0) or 0.0),
                )
            elif detail.get("action") == "skip":
                logger.info(
                    "[WordRemover] Skip %s word %r at %.3fs–%.3fs (confidence=%.4f below threshold)",
                    str(detail.get("track") or "unknown"),
                    str(detail.get("text") or ""),
                    float(detail["start_sec"]),
                    float(detail["end_sec"]),
                    float(detail.get("confidence", 0.0) or 0.0),
                )

        # Accumulate into the shared removal list, then (re)derive keep_segments.
        # If SegmentRemover already ran, its removals are already in removal_segments
        # and the recomputed keep_segments will be their union.
        for start_s, end_s in sorted_words:
            manifest.add_removal(start_s, end_s)

        total_duration = host_audio.duration_seconds
        if sorted_words:
            manifest.compute_keep_segments(total_duration)

        total_removed = sum(end - start for start, end in sorted_words)
        muted_count = sum(1 for detail in sorted_word_details if detail.get("action") == "mute")
        skipped_count = sum(1 for detail in sorted_word_details if detail.get("action") == "skip")
        logger.info(
            f"[PROCESSOR COMPLETE] Processed {len(sorted_word_details)} filler word(s): "
            f"{len(sorted_words)} cut sync-safe, {muted_count} muted single-track, {skipped_count} skipped low-confidence"
            f" - Total time cut: {format_time_cut(total_removed)}"
        )

        return manifest

    # Created by gpt-5.4 | 2026-03-08
    def _word_action_decide(self, detail: dict, host_audio, guest_audio) -> str:
        """Return whether a matched filler word should be cut or muted."""

        track = str(detail.get("track") or "").lower()
        start_ms = int(float(detail["start_sec"]) * 1000)
        end_ms = int(float(detail["end_sec"]) * 1000)
        threshold_db = float(self.config.get("silence_threshold_db", -45))
        confidence = float(detail.get("confidence", 0.0) or 0.0)

        if track == "host":
            confidence_required = float(WORDS_TO_REMOVE.get("confidence_required_host", 0.0) or 0.0)
        elif track == "guest":
            confidence_required = float(WORDS_TO_REMOVE.get("confidence_required_guest", 0.0) or 0.0)
        else:
            confidence_required = 0.0

        if confidence < confidence_required:
            return "skip"

        if track == "host":
            other_audio = guest_audio
        elif track == "guest":
            other_audio = host_audio
        else:
            return "cut"

        other_segment = other_audio[start_ms:end_ms]
        other_rms = other_segment.dBFS if len(other_segment) > 0 else -100.0
        return "cut" if other_rms < threshold_db else "mute"

    # Created by gpt-5.4 | 2026-03-08
    def _word_mute_add(self, manifest: EditManifest, detail: dict) -> None:
        """Add a single-track mute filter for one filler-word span."""

        start_s = float(detail["start_sec"])
        end_s = float(detail["end_sec"])
        enable_expr = f"between(t,{start_s:.3f},{end_s:.3f})"
        track = str(detail.get("track") or "").lower()

        if track == "host":
            manifest.add_host_filter("volume", volume=0, enable=enable_expr)
        elif track == "guest":
            manifest.add_guest_filter("volume", volume=0, enable=enable_expr)

    def get_name(self) -> str:
        return "WordRemover"
