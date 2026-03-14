from __future__ import annotations

import re


# Created by gpt-5.4 | 2026-03-07
def progress_line_mirror_should(line: str) -> bool:
    """Return True when a non-FFmpeg line should also appear in PROGRESS."""

    return any(
        token in line
        for token in (
            "[ACTION START]",
            "[ACTION COMPLETE]",
            "[FUNCTION START]",
            "[FUNCTION COMPLETE]",
            "[FUNCTION FAILED]",
            "[PREFLIGHT START]",
            "[PREFLIGHT COMPLETE]",
            "[RUN SUMMARY]",
            "[RUN START]",
            "[RUN COMPLETE]",
            "[DETAIL]",
        )
    )


# Created by coder-sr | 2026-03-12
def progress_line_transform(line: str) -> str:
    """Transform a line before writing it to the PROGRESS pane.

    Filler-word DETAIL lines contain a verbose per-word list after ' | '.
    Strip that tail so only the summary counts are shown in PROGRESS.
    The CONSOLE still receives the original, unmodified line.

    Example input:
        '12:30:24 [DETAIL] Host vid filler words: 0 removed, 0 muted, 3 skipped | "you know" @ ...'
    Example output:
        '12:30:24 [DETAIL] Host vid filler words: 0 removed, 0 muted, 3 skipped'
    """
    if "[DETAIL]" in line and "filler words:" in line and " | " in line:
        return line.split(" | ")[0]
    return line


# Created by gpt-5.4 | 2026-03-07
def result_line_paths_parse(line: str) -> tuple[str | None, str | None]:
    """Extract host and guest output paths from a [RESULT] line."""

    if not line.startswith("[RESULT]"):
        return None, None

    match = re.search(r"host=(.+?)\s+guest=(.+)$", line.strip())
    if match is None:
        return None, None

    return match.group(1).strip(), match.group(2).strip()
