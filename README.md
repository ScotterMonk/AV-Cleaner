# AV Cleaner
by Scott Howard Swain

## Application overview
Automate "Cleaning" of synchronized dual-video recordings (host + guest):
- All relevant settings in config file.
- Users only control which PROCESSORS run; DETECTORS are enabled automatically behind the scenes based on processor requirements.
- Find average audio level (db) of both files. Normalize avg audio levels of guest video to fit host video audio level.
- Find spikes above y db in guest video and reduce them to y.
- Trimming silent pauses.
- Maintaining perfect sync and audio quality.
- Built with a plugin-based architecture for easy extension (e.g., later features such as AI-based filler word removal).

## Commands
1) Run GUI: `py app.py`
2) Run CLI (Click): `python main.py --host path/to/host.mp4 --guest path/to/guest.mp4`
3) Override normalization mode: `python main.py --host ... --guest ... --norm-mode MATCH_HOST|STANDARD_LUFS`
