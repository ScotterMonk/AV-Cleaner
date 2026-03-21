# tests/test_cpu_override.py
"""Unit tests for the cpu_override module covering read, write, clear, and resolve_threads with all edge cases."""

import json
import pytest
from pathlib import Path

import utils.cpu_override as mod


@pytest.fixture(autouse=True)
def isolate_override_file(tmp_path, monkeypatch):
    """Redirect _OVERRIDE_FILE and _TMP_FILE to temp location for isolation.
    
    Prevents tests from touching the real project root _cpu_override.json.
    """
    override = tmp_path / "_cpu_override.json"
    tmp = tmp_path / "_cpu_override.tmp"
    monkeypatch.setattr(mod, "_OVERRIDE_FILE", override)
    monkeypatch.setattr(mod, "_TMP_FILE", tmp)
    yield override


def test_read_returns_none_when_absent(isolate_override_file):
    assert mod.read_live_cpu_pct() is None


def test_read_returns_none_on_malformed_json(isolate_override_file):
    isolate_override_file.write_text("not json", encoding="utf-8")
    assert mod.read_live_cpu_pct() is None


def test_read_returns_none_on_out_of_range(isolate_override_file):
    isolate_override_file.write_text(json.dumps({"cpu_limit_pct": 0}), encoding="utf-8")
    assert mod.read_live_cpu_pct() is None


def test_read_returns_valid_value(isolate_override_file):
    isolate_override_file.write_text(json.dumps({"cpu_limit_pct": 40}), encoding="utf-8")
    assert mod.read_live_cpu_pct() == 40


def test_write_produces_readable_file(isolate_override_file):
    mod.write_live_cpu_pct(55)
    assert mod.read_live_cpu_pct() == 55


def test_write_is_atomic(isolate_override_file, tmp_path):
    """tmp file is removed after successful atomic os.replace."""
    mod.write_live_cpu_pct(30)
    tmp = tmp_path / "_cpu_override.tmp"
    assert not tmp.exists()


def test_clear_removes_file(isolate_override_file):
    mod.write_live_cpu_pct(50)
    mod.clear_live_cpu_pct()
    assert not isolate_override_file.exists()


def test_clear_is_silent_when_absent(isolate_override_file):
    mod.clear_live_cpu_pct()  # must not raise


def test_resolve_threads_uses_override(isolate_override_file, monkeypatch):
    mod.write_live_cpu_pct(100)
    # Patch to return the cpu_limit_pct for easy verification
    import io_.video_renderer as vr
    monkeypatch.setattr(vr, "cpu_threads_from_config", lambda cfg: cfg.get("cpu_limit_pct", -1))
    result = mod.resolve_threads({"cpu_limit_pct": 10})
    assert result == 100


def test_resolve_threads_falls_back_without_override(isolate_override_file, monkeypatch):
    import io_.video_renderer as vr
    monkeypatch.setattr(vr, "cpu_threads_from_config", lambda cfg: 7)
    result = mod.resolve_threads({"cpu_limit_pct": 80})
    assert result == 7
