# conftest.py
# Ensure the project root is always on sys.path when pytest runs.
# Without this, packages like io_, core, processors, utils, etc. cannot be
# resolved by test modules — pytest does not auto-insert the rootdir for
# projects without a setup.py / pyproject.toml installed in editable mode.

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


# NOTE: processing-complete chime suppression is handled inside
# processing_complete_alert_play() itself via PYTEST_CURRENT_TEST env-var
# guard (utils/processing_alert.py).  A prior monkeypatch approach here kept
# regressing because gui_app.py imports the function directly — the patch
# swapped the module attribute but gui_app already held the real reference.
