# tests/test_word_removal.py
#
# Tests for the word-removal pipeline:
#   - EditManifest.add_removal() / compute_keep_segments()
#   - SegmentRemover refactor (accumulator pattern)
#   - WordRemover processor
#   - FillerWordDetector._find_matches() (pure logic, no API calls)
#   - Combined accumulation: SegmentRemover + WordRemover union

import types
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_audio(duration: float):
    """Return a minimal object with .duration_seconds."""
    audio = types.SimpleNamespace()
    audio.duration_seconds = duration
    return audio


# ── EditManifest.add_removal / compute_keep_segments ─────────────────────────

class TestEditManifestAccumulator:
    def test_single_removal_middle(self):
        from core.interfaces import EditManifest
        m = EditManifest()
        m.add_removal(2.0, 4.0)
        result = m.compute_keep_segments(10.0)
        assert result == [(0.0, 2.0), (4.0, 10.0)]
        assert m.keep_segments == result

    def test_removal_at_start(self):
        from core.interfaces import EditManifest
        m = EditManifest()
        m.add_removal(0.0, 3.0)
        result = m.compute_keep_segments(10.0)
        assert result == [(3.0, 10.0)]

    def test_removal_at_end(self):
        from core.interfaces import EditManifest
        m = EditManifest()
        m.add_removal(8.0, 10.0)
        result = m.compute_keep_segments(10.0)
        assert result == [(0.0, 8.0)]

    def test_multiple_non_overlapping_removals(self):
        from core.interfaces import EditManifest
        m = EditManifest()
        m.add_removal(2.0, 4.0)
        m.add_removal(8.0, 9.0)
        result = m.compute_keep_segments(10.0)
        assert result == [(0.0, 2.0), (4.0, 8.0), (9.0, 10.0)]

    def test_overlapping_removals_merged(self):
        from core.interfaces import EditManifest
        m = EditManifest()
        m.add_removal(1.0, 5.0)
        m.add_removal(3.0, 7.0)  # overlaps with first
        result = m.compute_keep_segments(10.0)
        assert result == [(0.0, 1.0), (7.0, 10.0)]

    def test_adjacent_removals_merged(self):
        from core.interfaces import EditManifest
        m = EditManifest()
        m.add_removal(1.0, 3.0)
        m.add_removal(3.0, 5.0)  # butts up against first
        result = m.compute_keep_segments(10.0)
        assert result == [(0.0, 1.0), (5.0, 10.0)]

    def test_empty_removal_segments_leaves_keep_segments_unchanged(self):
        from core.interfaces import EditManifest
        m = EditManifest()
        result = m.compute_keep_segments(10.0)
        # Should not modify keep_segments when nothing queued
        assert result == []
        assert m.keep_segments == []

    def test_second_call_accumulates_both_sets(self):
        """Calling compute_keep_segments twice after adding more removals
        produces the union of all removals."""
        from core.interfaces import EditManifest
        m = EditManifest()

        # First processor adds a pause at 2–4s
        m.add_removal(2.0, 4.0)
        m.compute_keep_segments(10.0)
        assert m.keep_segments == [(0.0, 2.0), (4.0, 10.0)]

        # Second processor adds a word at 7–7.5s
        m.add_removal(7.0, 7.5)
        m.compute_keep_segments(10.0)
        assert m.keep_segments == [(0.0, 2.0), (4.0, 7.0), (7.5, 10.0)]


# ── SegmentRemover (refactored) ───────────────────────────────────────────────

class TestSegmentRemoverAccumulator:
    def test_sets_keep_segments_via_accumulator(self):
        from core.interfaces import EditManifest
        from processors.segment_remover import SegmentRemover

        processor = SegmentRemover({})
        manifest = processor.process(
            EditManifest(),
            _mock_audio(10.0),
            _mock_audio(10.0),
            {"cross_talk_detector": [(2.0, 4.0), (8.0, 9.0)]},
        )
        assert manifest.keep_segments == [(0.0, 2.0), (4.0, 8.0), (9.0, 10.0)]

    def test_no_pauses_leaves_keep_segments_empty(self):
        from core.interfaces import EditManifest
        from processors.segment_remover import SegmentRemover

        processor = SegmentRemover({})
        manifest = processor.process(
            EditManifest(),
            _mock_audio(10.0),
            _mock_audio(10.0),
            {"cross_talk_detector": []},
        )
        assert manifest.keep_segments == []  # empty = keep everything

    def test_removal_segments_populated(self):
        from core.interfaces import EditManifest
        from processors.segment_remover import SegmentRemover

        processor = SegmentRemover({})
        manifest = processor.process(
            EditManifest(),
            _mock_audio(10.0),
            _mock_audio(10.0),
            {"cross_talk_detector": [(3.0, 5.0)]},
        )
        assert (3.0, 5.0) in manifest.removal_segments


# ── WordRemover ───────────────────────────────────────────────────────────────

class TestWordRemover:
    def test_removes_detected_words(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        processor = WordRemover({})
        manifest = processor.process(
            EditManifest(),
            _mock_audio(10.0),
            _mock_audio(10.0),
            {"filler_word_detector": [(1.0, 1.5), (6.0, 6.4)]},
        )
        assert manifest.keep_segments == [(0.0, 1.0), (1.5, 6.0), (6.4, 10.0)]

    def test_no_detections_leaves_manifest_unchanged(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        processor = WordRemover({})
        manifest = processor.process(
            EditManifest(),
            _mock_audio(10.0),
            _mock_audio(10.0),
            {"filler_word_detector": []},
        )
        assert manifest.keep_segments == []

    def test_word_removal_applied_flag_set(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        processor = WordRemover({})
        manifest = processor.process(
            EditManifest(),
            _mock_audio(10.0),
            _mock_audio(10.0),
            {"filler_word_detector": []},
        )
        assert manifest.word_removal_applied is True

    def test_word_removals_bookkeeping(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        processor = WordRemover({})
        manifest = processor.process(
            EditManifest(),
            _mock_audio(10.0),
            _mock_audio(10.0),
            {"filler_word_detector": [(2.0, 2.3)]},
        )
        assert manifest.word_removals == [(2.0, 2.3)]

    def test_word_removal_details_bookkeeping(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        processor = WordRemover({})
        manifest = processor.process(
            EditManifest(),
            _mock_audio(10.0),
            _mock_audio(10.0),
            {
                "filler_word_detector": [
                    {"track": "host", "text": "uh", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.97},
                    {"track": "guest", "text": "you know", "start_sec": 4.0, "end_sec": 4.4, "confidence": 0.81},
                ]
            },
        )
        assert manifest.word_removals == [(2.0, 2.3), (4.0, 4.4)]
        assert manifest.word_removal_details == [
            {"track": "host", "text": "uh", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.97, "action": "cut"},
            {"track": "guest", "text": "you know", "start_sec": 4.0, "end_sec": 4.4, "confidence": 0.81, "action": "cut"},
        ]

    def test_word_on_host_mutes_when_guest_not_silent(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        class _AudioSlice:
            def __init__(self, dbfs):
                self.dBFS = dbfs

            def __len__(self):
                return 100

        class _AudioWithDb:
            def __init__(self, duration, dbfs):
                self.duration_seconds = duration
                self._dbfs = dbfs

            def __getitem__(self, key):
                return _AudioSlice(self._dbfs)

        processor = WordRemover({"silence_threshold_db": -30})
        manifest = processor.process(
            EditManifest(),
            _AudioWithDb(10.0, -80.0),
            _AudioWithDb(10.0, -15.0),
            {
                "filler_word_detector": [
                    {"track": "host", "text": "um", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.99},
                ]
            },
        )
        assert manifest.word_removals == []
        assert manifest.keep_segments == []
        assert [f.filter_name for f in manifest.host_filters] == ["volume"]
        assert manifest.host_filters[0].params == {"volume": 0, "enable": "between(t,2.000,2.300)"}
        assert manifest.word_removal_details == [
            {"track": "host", "text": "um", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.99, "action": "mute"},
        ]

    def test_word_on_guest_cuts_when_host_silent(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        class _AudioSlice:
            def __init__(self, dbfs):
                self.dBFS = dbfs

            def __len__(self):
                return 100

        class _AudioWithDb:
            def __init__(self, duration, dbfs):
                self.duration_seconds = duration
                self._dbfs = dbfs

            def __getitem__(self, key):
                return _AudioSlice(self._dbfs)

        processor = WordRemover({"silence_threshold_db": -30})
        manifest = processor.process(
            EditManifest(),
            _AudioWithDb(10.0, -80.0),
            _AudioWithDb(10.0, -80.0),
            {
                "filler_word_detector": [
                    {"track": "guest", "text": "um", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.99},
                ]
            },
        )
        assert manifest.word_removals == [(2.0, 2.3)]
        assert manifest.keep_segments == [(0.0, 2.0), (2.3, 10.0)]
        assert manifest.guest_filters == []
        assert manifest.word_removal_details == [
            {"track": "guest", "text": "um", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.99, "action": "cut"},
        ]

    def test_word_on_host_skipped_when_confidence_below_host_threshold(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        class _AudioSlice:
            def __init__(self, dbfs):
                self.dBFS = dbfs

            def __len__(self):
                return 100

        class _AudioWithDb:
            def __init__(self, duration, dbfs):
                self.duration_seconds = duration
                self._dbfs = dbfs

            def __getitem__(self, key):
                return _AudioSlice(self._dbfs)

        processor = WordRemover({"silence_threshold_db": -30})
        manifest = processor.process(
            EditManifest(),
            _AudioWithDb(10.0, -80.0),
            _AudioWithDb(10.0, -80.0),
            {
                "filler_word_detector": [
                    {"track": "host", "text": "um", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.99},
                ]
            },
        )
        assert manifest.word_removals == []
        assert manifest.keep_segments == []
        assert manifest.host_filters == []
        assert manifest.word_removal_details == [
            {"track": "host", "text": "um", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.99, "action": "skip"},
        ]

    def test_word_on_guest_skipped_when_confidence_below_guest_threshold(self):
        from core.interfaces import EditManifest
        from processors.word_remover import WordRemover

        class _AudioSlice:
            def __init__(self, dbfs):
                self.dBFS = dbfs

            def __len__(self):
                return 100

        class _AudioWithDb:
            def __init__(self, duration, dbfs):
                self.duration_seconds = duration
                self._dbfs = dbfs

            def __getitem__(self, key):
                return _AudioSlice(self._dbfs)

        processor = WordRemover({"silence_threshold_db": -30})
        manifest = processor.process(
            EditManifest(),
            _AudioWithDb(10.0, -80.0),
            _AudioWithDb(10.0, -80.0),
            {
                "filler_word_detector": [
                    {"track": "guest", "text": "um", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.92},
                ]
            },
        )
        assert manifest.word_removals == []
        assert manifest.keep_segments == []
        assert manifest.guest_filters == []
        assert manifest.word_removal_details == [
            {"track": "guest", "text": "um", "start_sec": 2.0, "end_sec": 2.3, "confidence": 0.92, "action": "skip"},
        ]

    def test_get_name(self):
        from processors.word_remover import WordRemover
        assert WordRemover({}).get_name() == "WordRemover"


# ── Combined: SegmentRemover + WordRemover accumulate into a union ─────────────

class TestCombinedAccumulation:
    def test_segment_and_word_removals_unioned(self):
        """
        Running SegmentRemover then WordRemover on the same manifest must
        produce keep_segments that is the union of both removal sets.
        """
        from core.interfaces import EditManifest
        from processors.segment_remover import SegmentRemover
        from processors.word_remover import WordRemover

        host = _mock_audio(20.0)
        guest = _mock_audio(20.0)
        manifest = EditManifest()

        # Pause at 5–7s
        manifest = SegmentRemover({}).process(
            manifest, host, guest,
            {"cross_talk_detector": [(5.0, 7.0)]}
        )
        # Filler word at 12–12.5s
        manifest = WordRemover({}).process(
            manifest, host, guest,
            {"filler_word_detector": [(12.0, 12.5)]}
        )

        assert manifest.keep_segments == [
            (0.0, 5.0),
            (7.0, 12.0),
            (12.5, 20.0),
        ]

    def test_overlapping_cuts_across_processors_merged(self):
        """
        A pause and a filler word that overlap produce one merged cut.
        """
        from core.interfaces import EditManifest
        from processors.segment_remover import SegmentRemover
        from processors.word_remover import WordRemover

        host = _mock_audio(10.0)
        guest = _mock_audio(10.0)
        manifest = EditManifest()

        # Pause at 3–6s
        manifest = SegmentRemover({}).process(
            manifest, host, guest,
            {"cross_talk_detector": [(3.0, 6.0)]}
        )
        # Filler word at 5–7s (overlaps with pause)
        manifest = WordRemover({}).process(
            manifest, host, guest,
            {"filler_word_detector": [(5.0, 7.0)]}
        )

        # Should be merged to a single 3–7s removal
        assert manifest.keep_segments == [(0.0, 3.0), (7.0, 10.0)]


# ── FillerWordDetector._find_matches (pure logic, no API) ────────────────────

class TestFillerWordDetectorFindMatches:
    def _detector(self):
        from detectors.filler_word_detector import FillerWordDetector
        return FillerWordDetector({})

    def _word(self, text, start_ms, end_ms):
        return {"text": text, "start": start_ms, "end": end_ms, "confidence": 0.9}

    def test_single_word_match(self):
        det = self._detector()
        words = [
            self._word("Hi,",   160,  480),
            self._word("uh,",   640,  920),
            self._word("I'm",   920, 1120),
            self._word("Bob.",  1120, 1520),
        ]
        matches = det._find_matches(words, ["uh"])
        assert matches == [(0.64, 0.92)]

    def test_multi_word_phrase_match(self):
        det = self._detector()
        words = [
            self._word("you",   1000, 1200),
            self._word("know",  1200, 1500),
            self._word("it",    1600, 1800),
        ]
        matches = det._find_matches(words, ["you know"])
        assert matches == [(1.0, 1.5)]

    def test_no_match_returns_empty(self):
        det = self._detector()
        words = [
            self._word("Hello",  0, 500),
            self._word("world.", 600, 1000),
        ]
        matches = det._find_matches(words, ["uh", "uhm"])
        assert matches == []

    def test_punctuation_stripped_from_word(self):
        det = self._detector()
        words = [self._word("uhm,", 200, 600)]
        matches = det._find_matches(words, ["uhm"])
        assert matches == [(0.2, 0.6)]

    def test_multiple_occurrences_all_returned(self):
        det = self._detector()
        words = [
            self._word("uh,",   0,    400),
            self._word("well",  500,  900),
            self._word("uh,",   1000, 1300),
        ]
        matches = det._find_matches(words, ["uh"])
        assert len(matches) == 2
        assert (0.0, 0.4) in matches
        assert (1.0, 1.3) in matches

    def test_detailed_matches_include_track_and_phrase(self):
        det = self._detector()
        words = [
            self._word("you", 1000, 1200),
            self._word("know", 1200, 1500),
        ]
        matches = det._find_matches_detailed(words, ["you know"], "guest")
        assert matches == [
            {
                "track": "guest",
                "text": "you know",
                "start_sec": 1.0,
                "end_sec": 1.5,
                "confidence": 0.9,
            }
        ]
