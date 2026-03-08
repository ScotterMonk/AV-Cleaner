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
            "[SUBFUNCTION START]",
            "[SUBFUNCTION COMPLETE]",
            "[SUBFUNCTION FAILED]",
            "[PREFLIGHT START]",
            "[PREFLIGHT COMPLETE]",
            "[RUN SUMMARY]",
            "[DETAIL]",
        )
    )


# Created by gpt-5.4 | 2026-03-07
def result_line_paths_parse(line: str) -> tuple[str | None, str | None]:
    """Extract host and guest output paths from a [RESULT] line."""

    if not line.startswith("[RESULT]"):
        return None, None

    match = re.search(r"host=(.+?)\s+guest=(.+)$", line.strip())
    if match is None:
        return None, None

    return match.group(1).strip(), match.group(2).strip()
