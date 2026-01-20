"""utils/progress_log.py

Custom logging handler for progress/action logs.

Captures log lines with special tokens (e.g., [ACTION START], [SUBFUNCTION START]) 
and writes them to a file. These are the same lines that appear in the GUI PROGRESS pane.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Sequence


# Tokens that indicate a line should be captured in the progress log
_PROGRESS_TOKENS = (
    "[ACTION START]",
    "[ACTION COMPLETE]",
    "[SUBFUNCTION START]",
    "[SUBFUNCTION COMPLETE]",
    "[SUBFUNCTION FAILED]",
    "[PREFLIGHT START]",
    "[PREFLIGHT COMPLETE]",
    "[RUN SUMMARY]",
    "[DETAIL]",
    "[RUN START]",
    "[RUN COMPLETE]",
)


class ProgressLogHandler(logging.Handler):
    """Logging handler that writes progress/action lines to a file."""

    def __init__(self, log_file_path: str | Path):
        super().__init__()
        self.log_file_path = Path(log_file_path)
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Clear the file at initialization
        self.log_file_path.write_text("", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        """Write log record to file if it contains a progress token."""
        try:
            msg = self.format(record)
            
            # Only write lines with progress tokens
            if any(token in msg for token in _PROGRESS_TOKENS):
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
        except Exception:
            self.handleError(record)


def progress_log_path(project_dir: str | Path, *, now: datetime | None = None) -> Path:
    """Generate the progress log file path for a given project directory.
    
    Args:
        project_dir: Directory where the progress log should be saved
        now: Optional datetime for the filename (defaults to current time)
    
    Returns:
        Path to the progress log file
    """
    dt = now or datetime.now()
    filename = f"{dt.date().isoformat()}-processing-log.txt"
    return Path(project_dir) / filename
