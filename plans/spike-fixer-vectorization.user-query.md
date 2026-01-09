# User Query

Reduce analysis time for long videos (pure NumPy vectorization)

## Summary
Reduce wall-clock time and CPU usage in the Phase 1 extraction + analysis portion of [`ProcessingPipeline.execute()`](../core/pipeline.py:24) by eliminating Python-level hot loops and keeping computation in efficient NumPy vectorized primitives.

## Primary target
Remove the per-window Python loop in [`SpikeFixerDetector.detect()`](../detectors/spike_fixer_detector.py:13) and compute the same peak-per-window values using bulk NumPy operations (reshape/window the sample array once, then do vectorized reductions like `max(abs(...), axis=...)`).

## Approach
- Replace the loop over windows with reshape-based windowing + NumPy reductions.
- Handle edge padding and stereo vs mono consistently.

## Expected gain
Often ~10×–100× for spike detection itself on long files because you remove per-window Python overhead. End-to-end pipeline speedup depends on how much time you currently spend in spike detection versus FFmpeg rendering.

## Why this works
The current loop does ~N / window_samples iterations; for 55 minutes at 44.1 kHz and 50 ms windows that’s ~66k Python iterations.

