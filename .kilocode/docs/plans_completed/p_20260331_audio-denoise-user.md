# User Query — Audio Noise Reduction

**Date**: 2026-03-31
**Short plan name**: audio-denoise

## Original Query

> The host says "welcome you on palisades gold radio today" but the processed output drops "palisades". The guest hasn't spoken yet — their audio is just "a bit dirty" (ambient noise). The CrossTalkDetector sees the guest's noise floor as "not silent" which prevents proper mutual-silence detection, causing speech segments in the host track to be mis-cut. Fix: add audio noise reduction to clean both tracks before detection runs.

## Why (Inferred Intent)

Dirty/noisy audio on either track poisons the CrossTalkDetector's mutual-silence logic, causing it to either miss real pauses or — worse — cut through speech. The user wants both tracks denoised so detectors make better decisions, and as a secondary benefit, the output audio sounds cleaner for the listener.

## Addendum (from architect)

User also requested separate per-track config flags: `noise_reduction_host: True` and `noise_reduction_guest: True` so each track can be independently toggled (in addition to the master `noise_reduction_enabled` switch).

## Scope

- New `noisereduce` dependency, in-memory denoising of both host+guest audio before detectors run, config keys to enable/tune (including per-track host/guest toggles), integration with existing pipeline, output audio denoising via FFmpeg `afftdn` filter.
