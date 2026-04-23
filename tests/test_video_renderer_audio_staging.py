import ffmpeg
import pytest

from core.interfaces import AudioFilter
from io_.video_renderer import _build_filter_chain


def _filter_graph_compile(filters, keep_segments):
    video_stream, audio_stream = _build_filter_chain(
        input_path="fake.mp4",
        filters=filters,
        keep_segments=keep_segments,
        input_kwargs={},
    )
    stream = ffmpeg.output(video_stream, audio_stream, "out.mp4", vcodec="libx264", acodec="aac")
    args = ffmpeg.compile(stream, overwrite_output=True)
    return args[args.index("-filter_complex") + 1]


def test_build_filter_chain_orders_staged_audio_filters_around_trim_reset():
    filter_graph = _filter_graph_compile(
        filters=[
            AudioFilter(
                filter_name="volume",
                params={"volume": 0, "enable": "between(t,1.0,2.0)"},
                stage="original_timeline",
            ),
            AudioFilter(
                filter_name="loudnorm",
                params={"I": -16.0, "TP": -1.5, "LRA": 11.0},
                stage="post_trim",
            ),
        ],
        keep_segments=[(0.0, 5.0)],
    )

    original_idx = filter_graph.index("volume=")
    atrim_idx = filter_graph.index("atrim=")
    asetpts_idx = filter_graph.index("asetpts=PTS-STARTPTS")
    post_trim_idx = filter_graph.rindex("loudnorm=")

    assert original_idx < atrim_idx
    assert atrim_idx < asetpts_idx
    assert asetpts_idx < post_trim_idx


def test_build_filter_chain_raises_for_misstaged_filters():
    # Test that a filter staged as 'original_timeline' but with no enable=between
    # raises a ValueError, as per the requirement that original_timeline filters
    # must declare enable=between(t,...).
    with pytest.raises(ValueError) as exc_info:
        _build_filter_chain(
            input_path="fake.mp4",
            filters=[
                AudioFilter(
                    filter_name="volume",
                    params={"volume": 0},
                    stage="original_timeline",
                )
            ],
            keep_segments=[(0.0, 5.0)],
            input_kwargs={},
        )
    assert "original_timeline filters must declare enable=between(t,...)" in str(exc_info.value)


def test_build_filter_chain_keeps_combined_concat_for_audio_video_lockstep():
    filter_graph = _filter_graph_compile(
        filters=[
            AudioFilter(
                filter_name="volume",
                params={"volume": 0, "enable": "between(t,0.5,0.75)"},
                stage="original_timeline",
            ),
            AudioFilter(
                filter_name="alimiter",
                params={"limit": 0.98},
                stage="post_trim",
            ),
        ],
        keep_segments=[(0.0, 2.0), (3.0, 5.0)],
    )

    assert "concat=a=1:n=2:v=1" in filter_graph
    assert "concat=a=1:n=2:v=0" not in filter_graph


@pytest.mark.parametrize(
    ("audio_filter", "message_fragment"),
    [
        (
            AudioFilter(
                filter_name="alimiter",
                params={"limit": 0.98},
                stage="original_timeline",
            ),
            "original_timeline filters must declare enable=between(t,...)",
        ),
        (
            AudioFilter(
                filter_name="volume",
                params={"volume": 0, "enable": "between(t,1.0,2.0)"},
                stage="post_trim",
            ),
            "post_trim filters cannot declare enable=between(t,...)",
        ),
    ],
)
def test_build_filter_chain_raises_for_audio_filter_stage_mismatch(audio_filter, message_fragment):
    with pytest.raises(ValueError) as exc_info:
        _build_filter_chain(
            input_path="fake.mp4",
            filters=[audio_filter],
            keep_segments=[(0.0, 5.0)],
            input_kwargs={},
        )
    assert message_fragment in str(exc_info.value)
