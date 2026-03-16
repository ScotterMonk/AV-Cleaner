# tests/test_renderer.py
"""Unit tests for _apply_cut_fades() in io_/video_renderer.py.

Covers:
  - zero-fade passthrough (cut_fade_s=0 disables all fades)
  - single-segment passthrough (nothing was cut, no fades needed)
  - first segment: fade-out only (no cut precedes it -> no fade-in)
  - last segment:  fade-in only  (no cut follows it  -> no fade-out)
  - middle segment: fade-in then fade-out
  - too-short segment guard (duration < required fade budget -> skip + log)
  - exact st parameter value for fade-out (duration − cut_fade_s)
  - exact d parameter value (equals cut_fade_s)
"""

import pytest
from io_.video_renderer import _apply_cut_fades


FADE_S = 0.015  # 15 ms — default podcast fade duration


class TestApplyCutFades:
    """Behaviour of _apply_cut_fades(segments, cut_fade_s)."""

    # ── Passthrough / disabled ────────────────────────────────────────────────

    def test_zero_fade_returns_no_fades_for_all_segments(self):
        """cut_fade_s=0 disables fading entirely; every slot is an empty list."""
        segments = [(0.0, 5.0), (6.0, 11.0), (12.0, 17.0)]
        result = _apply_cut_fades(segments, cut_fade_s=0.0)
        assert result == [[], [], []]

    def test_single_segment_no_fades(self):
        """One segment means nothing was cut — no fades should be applied."""
        result = _apply_cut_fades([(0.0, 60.0)], cut_fade_s=FADE_S)
        assert result == [[]]

    # ── Per-position behaviour ────────────────────────────────────────────────

    def test_first_segment_fade_out_only(self):
        """First segment: no cut precedes it, so fade-in is skipped; only fade-out."""
        segs = [(0.0, 5.0), (6.0, 11.0), (12.0, 17.0)]
        result = _apply_cut_fades(segs, cut_fade_s=FADE_S)
        first = result[0]
        assert len(first) == 1
        assert first[0]["type"] == "out"

    def test_last_segment_fade_in_only(self):
        """Last segment: no cut follows it, so fade-out is skipped; only fade-in."""
        segs = [(0.0, 5.0), (6.0, 11.0), (12.0, 17.0)]
        result = _apply_cut_fades(segs, cut_fade_s=FADE_S)
        last = result[-1]
        assert len(last) == 1
        assert last[0]["type"] == "in"

    def test_middle_segment_fade_in_then_fade_out(self):
        """Middle segment: cut on both sides -> fade-in first, then fade-out."""
        segs = [(0.0, 5.0), (6.0, 11.0), (12.0, 17.0)]
        result = _apply_cut_fades(segs, cut_fade_s=FADE_S)
        middle = result[1]
        assert len(middle) == 2
        assert middle[0]["type"] == "in"
        assert middle[1]["type"] == "out"

    # ── Too-short guard ───────────────────────────────────────────────────────

    def test_too_short_middle_segment_skipped(self):
        """Middle segment shorter than 2×fade budget -> no fades (guard fires)."""
        # cut_fade_s=0.015 -> budget for middle = 0.030 s; segment is 0.020 s.
        short_middle = (6.0, 6.020)   # 20 ms — below the 30 ms budget
        segs = [(0.0, 5.0), short_middle, (10.0, 15.0)]
        result = _apply_cut_fades(segs, cut_fade_s=FADE_S)
        assert result[1] == [], "Too-short middle segment should produce an empty fade list"

    # ── Exact parameter values ────────────────────────────────────────────────

    def test_exact_st_parameter_for_fade_out(self):
        """Fade-out start time (st) must equal segment_duration − cut_fade_s.

        After asetpts the segment PTS runs 0 -> duration.  The fade-out must
        start at (duration − cut_fade_s) so it ends exactly at the segment tail.
        """
        duration = 5.0
        cut_fade_s = FADE_S
        segs = [(0.0, duration), (6.0, 11.0)]   # two segments -> first gets fade-out
        result = _apply_cut_fades(segs, cut_fade_s=cut_fade_s)
        fade_out_spec = result[0][0]             # first segment, only spec
        assert fade_out_spec["type"] == "out"
        assert abs(fade_out_spec["st"] - (duration - cut_fade_s)) < 1e-9

    def test_exact_d_parameter_matches_cut_fade_s(self):
        """The d (duration) field in every spec must equal cut_fade_s exactly."""
        cut_fade_s = 0.016   # 16 ms — value from config
        segs = [(0.0, 5.0), (6.0, 11.0), (12.0, 17.0)]
        result = _apply_cut_fades(segs, cut_fade_s=cut_fade_s)
        for slot in result:
            for spec in slot:
                assert spec["d"] == cut_fade_s, (
                    f"Expected d={cut_fade_s}, got {spec['d']} in spec {spec}"
                )
