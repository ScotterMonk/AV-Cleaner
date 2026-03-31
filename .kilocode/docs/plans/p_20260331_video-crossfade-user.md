# User Query — Video Crossfade at Cut Points

**Date**: 2026-03-31
**Short plan name**: video-crossfade

## Original Query

> "How difficult would it be to introduce a visual fade between the two frames that are being spliced together when cuts are made?"
> 
> Follow-up: "No 'fade to black' when I'm thinking fade from one frame (frame before cut) to the next frame (the frame that is now pushed up against 'frame before cut'). And I do want that `video_fade_duration_frames` to be put in our `config.py` so that I can play with settings. And set it initially to 4 (meaning 4 frame video fade). So yes, to me that means we go with a true crossfade/dissolve. And be sure to keep in mind that the fade must happen to both video streams in every spot it happens. Finally, another setting to add to `config.py` that turns `video_fade_on` to on or off."

## Why (Inferred Intent)

The user wants cut-points in the output video to be visually smooth — instead of a jarring hard cut, a brief dissolve (outgoing frame blending into incoming frame over 4 frames) softens the splice. This applies simultaneously to **both** the host and guest video tracks at every cut point, and should be toggleable and tunable via config without code changes.

## Scope

- **In**: Config keys, FFmpeg filter graph (xfade/acrossfade), all render paths, both host+guest streams.
- **Out**: Audio-only fade behavior (already exists via `cut_fade_ms`), GUI settings panel.

## Configuration

- **Complexity**: One Phase (Small/Med)
- **Autonomy**: High
- **Testing**: Use what is appropriate per task
