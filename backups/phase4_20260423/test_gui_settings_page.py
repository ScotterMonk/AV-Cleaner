import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

from ui.gui_settings_page import SettingsPage


class _PanelStub:
    def __init__(self, master: tk.Widget, bg: str) -> None:
        self.frame = MagicMock()
        self.body = MagicMock()

    def grid(self, *args, **kwargs) -> None:
        pass


class _AppStub:
    def __init__(self, root: tk.Tk, project_dir: Path) -> None:
        self._project_dir = project_dir
        self._palette = {
            "bg": "#101010",
            "panel": "#202020",
            "panel2": "#303030",
            "text": "#ffffff",
            "muted": "#aaaaaa",
            "edge2": "#404040",
        }
        self._ui_colors = {"accent_line": "#39FF14"}
        self.statuses: list[str] = []
        self.root = root

    def _mono(self, weight: str | None = None):
        return ("Cascadia Mono", 9, weight or "normal")

    def _make_btn(self, parent: tk.Widget, text: str, command, kind: str = "secondary") -> MagicMock:
        return MagicMock()

    def _make_panel(self, parent: tk.Widget, title: str) -> _PanelStub:
        return _PanelStub(parent, self._palette["panel"])

    def set_status(self, text: str) -> None:
        self.statuses.append(text)


def _setup_mocks(monkeypatch):
    """Setup mocks for tkinter to avoid TclError/RuntimeError."""
    # Mock classes using a simple lambda that returns a MagicMock without any spec
    monkeypatch.setattr("tkinter.Tk", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.Frame", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.Label", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.Button", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.Canvas", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.Scrollbar", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.Entry", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.Checkbutton", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.Radiobutton", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("tkinter.OptionMenu", lambda *a, **kw: MagicMock())

    class MockVar:
        def __init__(self, value=None, **kwargs):
            self.val = value

        def get(self):
            return str(self.val) if self.val is not None else ""

        def set(self, value):
            self.val = value

    class MockBooleanVar(MockVar):
        def get(self):
            return bool(self.val)

    monkeypatch.setattr("tkinter.StringVar", MockVar)
    monkeypatch.setattr("tkinter.BooleanVar", MockBooleanVar)


def test_settings_page_reload_loads_filler_word_mute_fields(monkeypatch, tmp_path):
    config_data = (
        {},
        {"processors": []},
        {"PODCAST_HIGH_QUALITY": {}},
        {
            "words_to_remove": ["uh", "um"],
            "confidence_required_host": 1.0,
            "confidence_required_guest": 0.92,
            "filler_mute_inset_ms": 35,
            "filler_mute_gap_threshold_ms": 75,
        },
    )
    monkeypatch.setattr(
        "ui.gui_settings_page.ConfigEditor.load_gui_pipeline_quality_words",
        lambda _path: config_data,
    )

    _setup_mocks(monkeypatch)

    root = tk.Tk()
    try:
        page = SettingsPage(root, _AppStub(root, tmp_path))

        assert page._word_vars["filler_mute_inset_ms"].get() == "35"
        assert page._word_vars["filler_mute_gap_threshold_ms"].get() == "75"
    finally:
        if hasattr(root, "destroy"):
            root.destroy()


def test_settings_page_save_writes_filler_word_mute_fields(monkeypatch, tmp_path):
    writes: list[dict] = []
    config_data = (
        {
            "gui_width": 1000,
            "gui_height": 700,
            "font_family": "Segoe UI",
            "font_title_size": 18,
            "font_section_size": 11,
            "font_body_size": 10,
            "font_mono_family": "Cascadia Mono",
            "font_mono_size": 9,
            "button_height": 10,
            "default_video_player": "",
            "ui_button_caption_color": "#39FF14",
            "ui_accent_font_color": "#39FF14",
            "ui_accent_line_color": "#39FF14",
            # Pane-width fields added 2026-03-15
            "pane_console_width_pct": 55,
            "pane_filler_words_found_pct": 45,
        },
        {"processors": []},
        {"PODCAST_HIGH_QUALITY": {"nvenc": {}, "normalization": {}}},
        {
            "words_to_remove": ["uh"],
            "confidence_required_host": 1.0,
            "confidence_required_guest": 0.92,
            "filler_mute_inset_ms": 30,
            "filler_mute_gap_threshold_ms": 60,
        },
    )
    monkeypatch.setattr(
        "ui.gui_settings_page.ConfigEditor.load_gui_pipeline_quality_words",
        lambda _path: config_data,
    )
    monkeypatch.setattr("ui.gui_settings_page.messagebox.showinfo", lambda *args: None)
    monkeypatch.setattr("ui.gui_settings_page.messagebox.showerror", lambda *args: None)

    def _capture_write(_config_path, _gui_update, _pipe_cfg, _qual_presets, words_cfg):
        writes.append(words_cfg.copy())

    monkeypatch.setattr("ui.gui_settings_page.ConfigEditor.write_gui_and_pipeline", _capture_write)

    _setup_mocks(monkeypatch)

    root = tk.Tk()
    try:
        page = SettingsPage(root, _AppStub(root, tmp_path))
        page._word_vars["filler_mute_inset_ms"].set("45")
        page._word_vars["filler_mute_gap_threshold_ms"].set("95")

        page._save()

        assert writes[-1]["filler_mute_inset_ms"] == 45
        assert writes[-1]["filler_mute_gap_threshold_ms"] == 95
    finally:
        if hasattr(root, "destroy"):
            root.destroy()
