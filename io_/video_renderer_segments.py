"""Segment-merging helpers for [`io_/video_renderer.py`](io_/video_renderer.py).

These utilities are shared by the single-pass renderer and the two-phase
video/audio helpers. They live in a dedicated module so the main renderer entry
point stays within the app-standard module size limit.
"""

from utils.logger import get_logger

logger = get_logger(__name__)


# Maximum gap between two adjacent keep_segments (seconds) that is considered
# imperceptible by viewers. Segments separated by less than this threshold are
# merged before filter-graph construction, reducing node count by ~20–40%.
# 150 ms is comfortably below the ~200 ms perception floor for podcast cuts
# that land adjacent to an inserted pause (new_pause_duration = 0.8 s).
SEGMENT_GAP_MERGE_THRESHOLD_S = 0.150

# Adaptive merging: when segment count after the base-threshold pass still
# exceeds ADAPTIVE_SEGMENT_COUNT_HIGH, the merge window is widened in 10 ms
# steps until the count falls below ADAPTIVE_SEGMENT_COUNT_TARGET or the
# ceiling ADAPTIVE_SEGMENT_GAP_MAX_S is reached.
ADAPTIVE_SEGMENT_COUNT_HIGH = 150
ADAPTIVE_SEGMENT_COUNT_TARGET = 100
ADAPTIVE_SEGMENT_GAP_MAX_S = 0.300


def merge_close_segments(
    keep_segments: list,
    gap_threshold_s: float = SEGMENT_GAP_MERGE_THRESHOLD_S,
) -> list:
    """Merge adjacent keep_segments whose inter-segment gap is below *gap_threshold_s*."""
    if not keep_segments or len(keep_segments) < 2:
        return list(keep_segments) if keep_segments else []

    merged = []
    current_start, current_end = keep_segments[0]

    for next_start, next_end in keep_segments[1:]:
        gap = next_start - current_end
        if gap < gap_threshold_s:
            # Bridge the micro-gap: extend current segment rightward.
            current_end = max(current_end, next_end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = next_start, next_end

    merged.append((current_start, current_end))
    return merged


def merge_close_segments_adaptive(
    keep_segments: list,
    base_threshold_s: float = SEGMENT_GAP_MERGE_THRESHOLD_S,
    high_count: int = ADAPTIVE_SEGMENT_COUNT_HIGH,
    target_count: int = ADAPTIVE_SEGMENT_COUNT_TARGET,
    max_threshold_s: float = ADAPTIVE_SEGMENT_GAP_MAX_S,
    step_s: float = 0.010,
) -> list:
    """Merge close segments with optional adaptive threshold widening."""
    if not keep_segments or len(keep_segments) < 2:
        return list(keep_segments) if keep_segments else []

    result = merge_close_segments(keep_segments, gap_threshold_s=base_threshold_s)

    # Fast path: base threshold reduced the count to an acceptable level.
    if len(result) < high_count:
        return result

    # Adaptive widening: widen the threshold in small steps until target is met.
    threshold = base_threshold_s + step_s
    while len(result) >= target_count and threshold <= max_threshold_s:
        result = merge_close_segments(keep_segments, gap_threshold_s=threshold)
        threshold += step_s

    final_threshold_ms = (threshold - step_s) * 1000
    logger.info(
        "merge_close_segments_adaptive: high segment count triggered adaptive widening; "
        "final threshold=%.0f ms, segments %d -> %d",
        final_threshold_ms,
        len(keep_segments),
        len(result),
    )
    return result
