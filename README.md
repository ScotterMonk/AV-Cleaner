# AV Cleaner
by Scott Howard Swain

## Application overview
Automate "Cleaning" of synchronized dual-video recordings (host + guest). Features:
- Finds average audio level (db) of both files. Normalizes avg audio levels of guest video to fit host video audio level.
- Finds spikes above y db in guest video and reduce them to y.
- Trims silent pauses.
- With all changes, maintains perfect sync and audio quality.
Deeper:
- Built with a plugin-based architecture for easy extension (e.g., later features such as AI-based filler word removal).
- All relevant settings in config file.

## Commands
1) Run GUI: `py app.py`
2) Run CLI (Click): `python main.py --host path/to/host.mp4 --guest path/to/guest.mp4`
3) Override normalization mode: `python main.py --host ... --guest ... --norm-mode MATCH_HOST|STANDARD_LUFS`
