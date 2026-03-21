from __future__ import annotations
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Sidecar lives at project root (one level above utils/).
_OVERRIDE_FILE = Path(__file__).resolve().parent.parent / "_cpu_override.json"
_TMP_FILE = _OVERRIDE_FILE.with_suffix(".tmp")


def read_live_cpu_pct() -> int | None:
    """Return cpu_limit_pct from override file, or None if absent/invalid."""
    try:
        data = json.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        pct = int(data["cpu_limit_pct"])
        if not (1 <= pct <= 100):
            raise ValueError(f"out of range: {pct}")
        return pct
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("cpu_override: could not read override file: %s", exc)
        return None


def write_live_cpu_pct(pct: int) -> None:
    """Write cpu_limit_pct to override file atomically."""
    try:
        _TMP_FILE.write_text(json.dumps({"cpu_limit_pct": pct}), encoding="utf-8")
        os.replace(str(_TMP_FILE), str(_OVERRIDE_FILE))
    except Exception as exc:
        logger.warning("cpu_override: could not write override file: %s", exc)


def clear_live_cpu_pct() -> None:
    """Delete override file; silent if not found."""
    try:
        _OVERRIDE_FILE.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("cpu_override: could not clear override file: %s", exc)


def resolve_threads(config: dict) -> int:
    """Return thread count, applying live override if present, else config default."""
    # Local import avoids circular dependency risk at module load time.
    from io_.video_renderer import cpu_threads_from_config
    try:
        pct = read_live_cpu_pct()
        if pct is not None:
            merged = {**(config or {}), "cpu_limit_pct": pct}
            return cpu_threads_from_config(merged)
    except Exception as exc:
        logger.warning("cpu_override: resolve_threads fallback: %s", exc)
    return cpu_threads_from_config(config or {})
