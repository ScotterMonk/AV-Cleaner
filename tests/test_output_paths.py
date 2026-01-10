from __future__ import annotations

from pathlib import Path

from utils.path_helpers import make_fixed_output_path, make_processed_output_path


def test_make_processed_output_path_uses_mp4_even_for_non_mp4_input() -> None:
    cases = [
        "video.mp4",
        "video.avi",
        "video.wmv",
        "my.video.mkv",
        "no_ext",
        str(Path("nested") / "clip.avi"),
    ]

    for inp in cases:
        outp = make_processed_output_path(inp)
        out_path = Path(outp)
        assert out_path.suffix.lower() == ".mp4"
        assert out_path.stem.endswith("_processed")
        assert out_path.parent == Path(inp).parent


def test_make_fixed_output_path_preserves_extension() -> None:
    inp = "video_processed.mp4"
    assert make_fixed_output_path(inp) == "video_processed_fixed.mp4"

