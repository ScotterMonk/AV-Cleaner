import os

from core.interfaces import DEFAULT_AUDIO_FILTER_STAGE
from utils.logger import get_logger

logger = get_logger(__name__)


def _audio_filter_stage_get(audio_filter) -> str:
    """Return the declared stage, defaulting for legacy filter stand-ins."""
    return getattr(audio_filter, "stage", DEFAULT_AUDIO_FILTER_STAGE)


def _audio_filter_original_timeline_get(audio_filter) -> bool:
    """True when the filter carries an original-timeline enable expression."""
    enable_expr = str((getattr(audio_filter, "params", {}) or {}).get("enable", "")).strip()
    return enable_expr.startswith("between(t,")


def audio_filters_partition(filters: list) -> tuple[list, list]:
    """Validate stages and split filters into original-timeline and post-trim groups."""
    filters_original_timeline: list = []
    filters_post_trim: list = []

    for audio_filter in filters or []:
        filter_name = getattr(audio_filter, "filter_name", "<unknown>")
        filter_stage = _audio_filter_stage_get(audio_filter)
        uses_original_timeline = _audio_filter_original_timeline_get(audio_filter)

        if filter_stage == "original_timeline" and not uses_original_timeline:
            raise ValueError(
                "Audio filter stage mismatch for "
                f"{filter_name}: original_timeline filters must declare "
                "enable=between(t,...)."
            )

        if filter_stage == "post_trim" and uses_original_timeline:
            raise ValueError(
                "Audio filter stage mismatch for "
                f"{filter_name}: post_trim filters cannot declare "
                "enable=between(t,...)."
            )

        if filter_stage == "original_timeline":
            filters_original_timeline.append(audio_filter)
            continue

        if filter_stage == "post_trim":
            filters_post_trim.append(audio_filter)
            continue

        raise ValueError(
            f"Audio filter stage mismatch for {filter_name}: unsupported stage {filter_stage!r}."
        )

    return filters_original_timeline, filters_post_trim


def audio_filters_apply(audio_stream, filters: list):
    """Apply a sequence of FFmpeg audio filters in order."""
    for audio_filter in filters or []:
        audio_stream = audio_stream.filter(audio_filter.filter_name, **audio_filter.params)
    return audio_stream


def audio_segments_build(
    audio_stream,
    keep_segments: list,
    cut_fade_s: float,
    fade_specs: list,
    input_path: str,
    split_required: bool,
) -> list:
    """Build per-segment audio streams after any original-timeline filters."""
    segments_audio = []
    audio_inputs = None

    if len(keep_segments) > 1 and split_required:
        logger.debug(
            "audio_segments_build(%s): inserting asplit(outputs=%s) before per-segment atrim",
            os.path.basename(str(input_path)),
            len(keep_segments),
        )
        split_node = audio_stream.filter_multi_output("asplit", outputs=len(keep_segments))
        audio_inputs = [split_node.stream(i) for i in range(len(keep_segments))]

    for idx, (start, end) in enumerate(keep_segments):
        audio_input = audio_inputs[idx] if audio_inputs is not None else audio_stream
        segment_audio = audio_input.filter_("atrim", start=start, end=end).filter_(
            "asetpts",
            "PTS-STARTPTS",
        )

        for fade_spec in fade_specs[idx]:
            segment_audio = segment_audio.filter_(
                "afade",
                t=fade_spec["type"],
                st=fade_spec["st"],
                d=fade_spec["d"],
            )

        segments_audio.append(segment_audio)

    return segments_audio
