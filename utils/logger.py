# utils/logger.py

import logging
import sys
from typing import Optional

# Default log format: Time - Level - Message
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%H:%M:%S"

def setup_logger(name: str = "video_trimmer", level: int = logging.INFO, log_file: Optional[str] = None) -> logging.Logger:
    """
    Configures the root logger for the application.
    Should be called once at the start of main.py.
    
    Args:
        name: Name of the logger
        level: Logging level (logging.INFO, logging.DEBUG)
        log_file: Optional path to write logs to a file
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent adding handlers multiple times if setup is called twice
    if logger.hasHandlers():
        return logger

    # 1. Console Handler (Standard Output)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(console_handler)

    # 2. File Handler (Optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(file_handler)

    # Prevent propagation to root logger if using a named logger
    # (prevents logs appearing twice if other libraries use logging)
    logger.propagate = False

    return logger

def get_logger(name: str) -> logging.Logger:
    """
    Get a child logger for a specific module.
    
    Usage in other files:
        from utils.logger import get_logger
        logger = get_logger(__name__)
    """
    # If the module name is 'core.pipeline', this creates 'video_trimmer.core.pipeline'
    # ensuring it inherits settings from the main 'video_trimmer' logger.
    parent_name = "video_trimmer"
    
    if name.startswith(parent_name):
        return logging.getLogger(name)
    
    return logging.getLogger(f"{parent_name}.{name}")


def format_duration(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.ms (milliseconds trimmed)."""
    sign = "-" if seconds < 0 else ""
    total_ms = int(round(abs(seconds) * 1000))

    total_seconds, ms = divmod(total_ms, 1000)
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)

    ms_str = f"{ms:03d}".rstrip("0")
    if not ms_str:
        ms_str = "0"

    return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}.{ms_str}"


def format_time_cut(seconds: float) -> str:
    """Convert seconds to MM:SS or HH:MM:SS (rounded to nearest second)."""
    sign = "-" if seconds < 0 else ""
    total_seconds = int(round(abs(seconds)))

    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)

    if hours:
        return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{sign}{minutes:02d}:{secs:02d}"
