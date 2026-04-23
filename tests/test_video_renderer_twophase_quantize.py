def test_classify_segments_exact_keyframe_hit_is_copy():
    """Segment starting exactly on a keyframe must classify as `copy`."""

    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = [0.0, 2.5, 5.0, 10.0]
    keep_segments = [(5.0, 8.0)]
    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert len(result) == 1
    seg = result[0]
    assert seg["type"] == "copy", f"Expected 'copy', got {seg['type']!r}"
    assert seg["kf_start"] == 5.0, f"Expected kf_start=5.0, got {seg['kf_start']}"
    assert seg["start"] == 5.0
    assert seg["end"] == 8.0


def test_classify_segments_within_tolerance_is_copy_snapped():
    """Segment starting within snap tolerance snaps to the prior keyframe and stays `copy`."""

    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = [0.0, 2.5, 5.0]
    keep_segments = [(2.55, 4.0)]
    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert len(result) == 1
    seg = result[0]
    assert seg["type"] == "copy", f"Expected 'copy' within tolerance, got {seg['type']!r}"
    assert seg["kf_start"] == 2.5, f"Expected kf_start snapped to 2.5, got {seg['kf_start']}"
    assert seg["start"] == 2.55


def test_classify_segments_keyframe_after_start_is_bridge():
    """Nearest keyframe after start must not be used for `copy`; the segment must bridge."""

    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = [0.0, 3.0, 6.0]
    keep_segments = [(2.95, 5.0)]
    result = classify_segments_by_keyframe(keep_segments, keyframes, snap_tolerance_s=0.1)

    assert len(result) == 1
    seg = result[0]
    assert seg["type"] == "bridge", f"Expected 'bridge', got {seg['type']!r}"
    assert seg["kf_start"] == 0.0, f"Expected largest prior keyframe 0.0, got {seg['kf_start']}"


def test_classify_segments_outside_tolerance_is_bridge():
    """Segment starting outside tolerance from any keyframe is classified as `bridge`."""

    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = [0.0, 2.0, 5.0]
    keep_segments = [(3.5, 4.5)]
    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert len(result) == 1
    seg = result[0]
    assert seg["type"] == "bridge", f"Expected 'bridge' outside tolerance, got {seg['type']!r}"
    assert seg["kf_start"] == 2.0, f"Expected kf_start=2.0, got {seg['kf_start']}"
    assert seg["start"] == 3.5


def test_classify_all_bridge():
    """Empty keyframe lists force every segment to `bridge` with `kf_start=0.0`."""

    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keyframes = []
    keep_segments = [(1.0, 3.0), (5.0, 7.0), (10.0, 12.0)]
    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert len(result) == 3, f"Expected 3 segments, got {len(result)}"
    for index, seg in enumerate(result):
        assert seg["type"] == "bridge", f"Segment {index}: expected 'bridge', got {seg['type']!r}"
        assert seg["kf_start"] == 0.0, f"Segment {index}: expected kf_start=0.0, got {seg['kf_start']}"


def test_classify_all_copy():
    """All segments already on keyframes must classify as `copy`."""

    from io_.video_renderer_twophase import classify_segments_by_keyframe

    keep_segments = [(0.0, 1.0), (2.0, 3.5), (4.0, 6.0)]
    keyframes = [0.0, 2.0, 4.0, 8.0]
    result = classify_segments_by_keyframe(keep_segments, keyframes)

    assert [seg["type"] for seg in result] == ["copy", "copy", "copy"]
    assert [seg["kf_start"] for seg in result] == [0.0, 2.0, 4.0]


def test_quantize_segments_to_frames_exact_boundaries():
    """Segments already on frame boundaries must remain unchanged."""

    from io_.video_renderer_twophase import quantize_segments_to_frames

    fps = 60.0
    segs = [(0.0, 1.0), (2.0, 3.5)]
    result = quantize_segments_to_frames(segs, fps)
    assert len(result) == 2
    assert abs(result[0][0] - 0.0) < 1e-9
    assert abs(result[0][1] - 1.0) < 1e-9
    assert abs(result[1][0] - 2.0) < 1e-9
    assert abs(result[1][1] - 3.5) < 1e-9


def test_quantize_segments_to_frames_rounds_to_nearest_frame():
    """Mid-frame boundaries must round to the nearest frame."""

    from io_.video_renderer_twophase import quantize_segments_to_frames

    fps = 60.0
    segs = [(0.005, 1.008)]
    result = quantize_segments_to_frames(segs, fps)
    assert len(result) == 1
    assert abs(result[0][0] - 0.0) < 1e-9, f"start should round to 0.0, got {result[0][0]}"
    assert abs(result[0][1] - 1.0) < 1e-9, f"end should round to 1.0, got {result[0][1]}"


def test_quantize_segments_to_frames_zero_fps_passthrough():
    """Zero or `None` fps returns the original segments unchanged."""

    from io_.video_renderer_twophase import quantize_segments_to_frames

    segs = [(1.5, 3.7), (5.1, 7.9)]
    assert quantize_segments_to_frames(segs, 0.0) == segs
    assert quantize_segments_to_frames(segs, None) == segs


def test_quantize_segments_to_frames_degenerate_segment_gets_one_frame():
    """When rounding collapses a segment to zero duration, the helper must still emit one frame."""

    from io_.video_renderer_twophase import quantize_segments_to_frames

    fps = 60.0
    frame = 1.0 / 60.0
    segs = [(0.008, 0.009)]
    result = quantize_segments_to_frames(segs, fps)
    assert len(result) == 1
    q_s, q_e = result[0]
    assert q_e > q_s, f"Degenerate segment must have q_end > q_start; got [{q_s}, {q_e}]"
    assert abs((q_e - q_s) - frame) < 1e-9, (
        f"Degenerate segment duration must be exactly 1 frame ({frame:.6f}s), got {q_e - q_s:.6f}s"
    )
