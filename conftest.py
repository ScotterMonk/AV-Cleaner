# conftest.py
# Ensure the project root is always on sys.path when pytest runs.
# Without this, packages like io_, core, processors, utils, etc. cannot be
# resolved by test modules — pytest does not auto-insert the rootdir for
# projects without a setup.py / pyproject.toml installed in editable mode.

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
