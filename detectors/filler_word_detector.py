# detectors/filler_word_detector.py
#
# Detects specific words/phrases (e.g. "uh", "uhm", "you know") in host and
# guest audio tracks via the AssemblyAI transcription API.
# Returns a combined list of (start_sec, end_sec) tuples for every match —
# one entry per word occurrence regardless of which speaker said it.
#
# Required env vars:  AAI_SETTINGS_API_KEY, AAI_SETTINGS_BASE_URL
# Config key:         WORDS_TO_REMOVE['words_to_remove']  (list of str)

import os
import tempfile
import time
from typing import List, Tuple

import requests

from .base_detector import BaseDetector
from config import WORDS_TO_REMOVE
from utils.logger import get_logger

logger = get_logger(__name__)

# How long to wait between status-polling retries (seconds).
_POLL_INTERVAL_SEC = 3


class FillerWordDetector(BaseDetector):
    """
    Transcribes both audio tracks via AssemblyAI and returns the time ranges
    of every configured word/phrase that should be removed.

    Multi-word phrases (e.g. "you know") are matched by comparing consecutive
    word windows against the phrase token sequence.

    If the API key is absent, or if any API call fails, an empty list is
    returned so the pipeline degrades gracefully.
    """

    # ── Public interface ───────────────────────────────────────────────────

    def detect(self, host_audio, guest_audio) -> List[Tuple[float, float]]:
        """
        Transcribe both tracks and return merged word-removal ranges.

        Args:
            host_audio:  pydub AudioSegment for the host track.
            guest_audio: pydub AudioSegment for the guest track.

        Returns:
            Combined list of (start_sec, end_sec) tuples from both tracks,
            unsorted.  Caller (WordRemover) is responsible for sorting/merging.
        """
        api_key = os.getenv("AAI_SETTINGS_API_KEY", "").strip()
        base_url = os.getenv("AAI_SETTINGS_BASE_URL", "").strip().rstrip("/")

        if not api_key or not base_url:
            logger.warning(
                "[FillerWordDetector] AAI_SETTINGS_API_KEY or AAI_SETTINGS_BASE_URL "
                "not set — skipping word detection."
            )
            return []

        target_words: List[str] = WORDS_TO_REMOVE.get("words_to_remove", [])
        if not target_words:
            logger.info("[FillerWordDetector] WORDS_TO_REMOVE is empty — nothing to detect.")
            return []

        logger.info(
            "[FillerWordDetector] Detecting word(s): %s",
            ", ".join(repr(w) for w in target_words),
        )

        headers = {"authorization": api_key}
        segments: List[Tuple[float, float]] = []

        for label, audio in (("host", host_audio), ("guest", guest_audio)):
            track_segments = self._process_track(label, audio, target_words, base_url, headers)
            logger.info(
                "[FillerWordDetector] %s track: %d match(es) found.", label, len(track_segments)
            )
            for start_s, end_s in track_segments:
                logger.info(
                    "[FillerWordDetector]   → %s %.3fs–%.3fs (%.0fms)",
                    label, start_s, end_s, (end_s - start_s) * 1000,
                )
            segments.extend(track_segments)

        return segments

    def get_name(self) -> str:
        return "filler_word_detector"

    def validate_config(self) -> bool:
        """Returns True only when the API key env var is populated."""
        return bool(os.getenv("AAI_SETTINGS_API_KEY", "").strip())

    # ── Private helpers ────────────────────────────────────────────────────

    def _process_track(
        self,
        label: str,
        audio,
        target_words: List[str],
        base_url: str,
        headers: dict,
    ) -> List[Tuple[float, float]]:
        """Export one pydub AudioSegment, upload it, transcribe, return matches."""
        temp_path = None
        try:
            temp_path = self._export_to_temp_mp3(audio, label)
            audio_url = self._upload_audio(temp_path, base_url, headers, label)
            transcript_words = self._transcribe(audio_url, base_url, headers, label)
            return self._find_matches(transcript_words, target_words)
        except Exception as exc:
            logger.error("[FillerWordDetector] %s track failed: %s", label, exc)
            return []
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass  # Non-critical; temp dir will clean up eventually

    def _export_to_temp_mp3(self, audio, label: str) -> str:
        """Write pydub AudioSegment to a named temp .mp3 file; return its path."""
        fd, temp_path = tempfile.mkstemp(suffix=f"_{label}.mp3", prefix="aai_")
        os.close(fd)  # Close OS handle so pydub can open the file for writing
        audio.export(temp_path, format="mp3")
        logger.debug("[FillerWordDetector] Exported %s audio → %s", label, temp_path)
        return temp_path

    def _upload_audio(self, file_path: str, base_url: str, headers: dict, label: str) -> str:
        """Upload audio file to AssemblyAI; return the hosted audio URL."""
        logger.info("[FillerWordDetector] Uploading %s audio to AssemblyAI…", label)
        with open(file_path, "rb") as f:
            response = requests.post(f"{base_url}/v2/upload", headers=headers, data=f)

        if response.status_code != 200:
            raise RuntimeError(
                f"Upload failed ({response.status_code}): {response.text}"
            )

        audio_url = response.json()["upload_url"]
        logger.debug("[FillerWordDetector] %s upload URL: %s", label, audio_url)
        return audio_url

    def _transcribe(
        self, audio_url: str, base_url: str, headers: dict, label: str
    ) -> List[dict]:
        """
        Submit a transcript request and poll until completion.
        Returns the raw word-level list from the API response.
        """
        payload = {
            "audio_url": audio_url,
            "speech_models": ["universal-3-pro", "universal-2"],
            "language_detection": True,
            "speaker_labels": False,
            # Must be True so disfluencies ("uh", "uhm", etc.) are preserved
            # in the word-level results instead of being silently stripped.
            "disfluencies": True,
        }
        response = requests.post(f"{base_url}/v2/transcript", headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Transcript request failed ({response.status_code}): {response.text}"
            )

        transcript_id = response.json()["id"]
        poll_url = f"{base_url}/v2/transcript/{transcript_id}"
        logger.info("[FillerWordDetector] Polling transcript %s for %s track…", transcript_id, label)

        while True:
            poll_response = requests.get(poll_url, headers=headers)
            transcript = poll_response.json()
            status = transcript.get("status")

            if status == "completed":
                words = transcript.get("words") or []
                logger.info(
                    "[FillerWordDetector] %s transcript complete — %d word(s) in response.",
                    label,
                    len(words),
                )
                return words

            if status == "error":
                raise RuntimeError(
                    f"AssemblyAI transcription error for {label}: {transcript.get('error')}"
                )

            # Still processing — wait and retry
            logger.debug("[FillerWordDetector] %s status=%s, retrying in %ds…", label, status, _POLL_INTERVAL_SEC)
            time.sleep(_POLL_INTERVAL_SEC)

    def _find_matches(
        self, words: List[dict], target_phrases: List[str]
    ) -> List[Tuple[float, float]]:
        """
        Scan the word list for any phrase in target_phrases.

        Single-token phrases:  matched against each word individually.
        Multi-token phrases:   matched against consecutive word windows.

        All timestamps from the API are in milliseconds; the returned tuples
        are in seconds.
        """
        matches: List[Tuple[float, float]] = []

        for phrase in target_phrases:
            tokens = phrase.lower().split()
            phrase_len = len(tokens)

            for i in range(len(words) - phrase_len + 1):
                window = words[i : i + phrase_len]
                window_texts = [w["text"].strip(".,!?;:").lower() for w in window]

                if window_texts == tokens:
                    # Timestamps are in milliseconds — convert to seconds
                    start_sec = window[0]["start"] / 1000.0
                    end_sec = window[-1]["end"] / 1000.0
                    matches.append((start_sec, end_sec))
                    logger.info(
                        "[FillerWordDetector] Matched word %r at %.3f–%.3fs",
                        phrase,
                        start_sec,
                        end_sec,
                    )

        return matches
