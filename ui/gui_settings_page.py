from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox

from ui.gui_config_editor import ConfigEditor
from ui.gui_settings_builders import build_gui_form, build_pipeline_form, render_pipeline_toggles
from ui.video_player_picker import video_player_pick
from utils.video_player_discovery import video_player_discover, video_player_platform_label


# Increase this value to make both panes shorter and lift footer buttons up.
SETTINGS_PANES_HEIGHT_REDUCTION_PX = 120


class SettingsPage(tk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, bg=app._palette["bg"])
        self._app = app
        self._config_path = app._project_dir / "config.py"

        # Footer (packed first to reserve space at bottom)
        footer = tk.Frame(self, bg=app._palette["bg"])
        footer.pack(side="bottom", fill="x", pady=(14, SETTINGS_PANES_HEIGHT_REDUCTION_PX))
        app._make_btn(footer, "SAVE TO config.py", self._save, kind="primary").pack(side="right")
        app._make_btn(footer, "RELOAD", self._reload, kind="secondary").pack(side="right", padx=(0, 12))

        # Two-pane grid
        grid = tk.Frame(self, bg=app._palette["bg"])
        grid.pack(side="top", fill="both", expand=True)
        grid.grid_rowconfigure(0, weight=1)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        gui_panel = app._make_panel(grid, "GUI")
        gui_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self._build_gui_form(gui_panel.body)

        pipeline_panel = app._make_panel(grid, "Pipeline")
        pipeline_panel.grid(row=0, column=1, sticky="nsew")
        self._build_pipeline_form(pipeline_panel.body)

        self._reload()

    # ------------------------------------------------------------------ #
    # Form construction – delegated to gui_settings_builders               #
    # ------------------------------------------------------------------ #

    def _build_gui_form(self, parent: tk.Frame) -> None:
        # Creates self._vars on this instance.
        build_gui_form(self, parent)

    def _build_pipeline_form(self, parent: tk.Frame) -> None:
        # Creates self._pipe_vars, _word_vars, _qual_vars, _bool_vars,
        # _norm_mode, _enc_mode, _enc_quality, plus the scrollable canvas.
        build_pipeline_form(self, parent)

    def _render_pipeline_toggles(self, pipe_cfg: dict, qual_presets: dict, words_cfg: dict) -> None:
        render_pipeline_toggles(self, pipe_cfg, qual_presets, words_cfg)

    # ------------------------------------------------------------------ #
    # Video-player scan                                                    #
    # ------------------------------------------------------------------ #

    # Created by gpt-5.4 | 2026-03-07
    def _scan_default_video_player(self) -> None:
        options = video_player_discover()
        if not options:
            platform_label = video_player_platform_label()
            messagebox.showinfo(
                "No media players found",
                f"No supported media players were found for {platform_label}.",
            )
            return

        selected_path = video_player_pick(self, self._app, options)
        if not selected_path:
            return

        self._vars["default_video_player"].set(selected_path)
        player_name = Path(selected_path).name
        self._app.set_status(f"Default video player selected: {player_name}. Click SAVE TO config.py.")

    # ------------------------------------------------------------------ #
    # Reload                                                               #
    # ------------------------------------------------------------------ #

    # Modified by gpt-5.4 | 2026-03-07
    def _reload(self) -> None:
        try:
            gui_dict, pipe_cfg, qual_presets, words_cfg = ConfigEditor.load_gui_pipeline_quality_words(
                self._config_path
            )
        except Exception as e:
            messagebox.showerror("Config load failed", str(e))
            return

        for k, v in self._vars.items():
            v.set(str(gui_dict.get(k, "")))

        self._render_pipeline_toggles(pipe_cfg, qual_presets, words_cfg)
        self._app.set_status("Settings loaded")

    # ------------------------------------------------------------------ #
    # Save                                                                 #
    # ------------------------------------------------------------------ #

    # Modified 2026-03-15: added all previously missing config.py fields
    def _save(self) -> None:
        # ---- local conversion helpers ----
        def to_int(key: str) -> int:
            raw = self._vars[key].get().strip()
            if raw == "":
                raise ValueError(f"{key} is required")
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"{key} must be an integer")

        def to_color(key: str) -> str:
            raw = self._vars[key].get().strip()
            if raw == "":
                raise ValueError(f"{key} is required")
            return raw

        def to_int_s(var: tk.StringVar, label: str) -> int:
            raw = var.get().strip()
            if raw == "":
                raise ValueError(f"{label} is required")
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"{label} must be an integer")

        def to_float_s(var: tk.StringVar, label: str) -> float:
            raw = var.get().strip()
            if raw == "":
                raise ValueError(f"{label} is required")
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f"{label} must be a number")

        def to_float_word(key: str, label: str) -> float:
            raw = self._word_vars[key].get().strip()
            if raw == "":
                raise ValueError(f"{label} is required")
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f"{label} must be a number")

        def to_int_word(key: str, label: str) -> int:
            raw = self._word_vars[key].get().strip()
            if raw == "":
                raise ValueError(f"{label} is required")
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"{label} must be an integer")

        try:
            # ---- GUI dict ----
            gui_update = {
                "gui_width": to_int("gui_width"),
                "gui_height": to_int("gui_height"),
                "font_family": self._vars["font_family"].get().strip() or "Segoe UI",
                "font_title_size": to_int("font_title_size"),
                "font_section_size": to_int("font_section_size"),
                "font_body_size": to_int("font_body_size"),
                "font_mono_family": self._vars["font_mono_family"].get().strip() or "Cascadia Mono",
                "font_mono_size": to_int("font_mono_size"),
                "button_height": to_int("button_height"),
                "default_video_player": self._vars["default_video_player"].get().strip(),
                "ui_button_caption_color": to_color("ui_button_caption_color"),
                "ui_accent_font_color": to_color("ui_accent_font_color"),
                "ui_accent_line_color": to_color("ui_accent_line_color"),
                # Pane split percentages
                "pane_console_width_pct": to_int("pane_console_width_pct"),
                "pane_filler_words_found_pct": to_int("pane_filler_words_found_pct"),
            }

            _, pipe_cfg, qual_presets, words_cfg = ConfigEditor.load_gui_pipeline_quality_words(
                self._config_path
            )

            # ---- Pipeline toggles ----
            for k, var in self._pipe_vars.items():
                group, idx_s = k.split(":", 1)
                pipe_cfg[group][int(idx_s)]["enabled"] = bool(var.get())
            pipe_cfg.pop("detectors", None)

            # ---- Quality preset ----
            preset = qual_presets.get("PODCAST_HIGH_QUALITY")
            if not preset:
                raise ValueError("PODCAST_HIGH_QUALITY preset missing in config.py")

            # Analysis / silence settings
            preset["silence_threshold_db"] = to_int_s(
                self._qual_vars["silence_threshold_db"], "Silence threshold (dB)"
            )
            preset["max_pause_duration"] = to_float_s(
                self._qual_vars["max_pause_duration"], "Max pause duration (sec)"
            )
            preset["new_pause_duration"] = to_float_s(
                self._qual_vars["new_pause_duration"], "New pause duration (sec)"
            )
            preset["silence_window_ms"] = to_int_s(
                self._qual_vars["silence_window_ms"], "Silence window (ms)"
            )
            preset["spike_threshold_db"] = to_int_s(
                self._qual_vars["spike_threshold_db"], "Spike threshold (dB)"
            )

            # Normalization
            preset["normalization"] = {
                "mode": self._norm_mode.get().strip() or "MATCH_HOST",
                "standard_target": to_float_s(
                    self._qual_vars["normalization_standard_target"], "Standard target (LUFS)"
                ),
                "max_gain_db": to_float_s(
                    self._qual_vars["normalization_max_gain_db"], "Max gain (dB)"
                ),
            }

            # Encoder (CPU vs GPU)
            is_gpu = self._enc_mode.get() == "gpu"
            qual_val = to_int_s(self._enc_quality, "Quality (CRF/CQ)")
            preset["cuda_encode_enabled"] = is_gpu
            preset["cuda_decode_enabled"] = bool(self._bool_vars["cuda_decode_enabled"].get())
            preset["cuda_require_support"] = bool(self._bool_vars["cuda_require_support"].get())

            # CPU encoding
            preset["video_codec"] = self._qual_vars["video_codec"].get().strip() or "libx264"
            preset["video_preset"] = self._qual_vars["video_preset"].get().strip() or "fast"
            preset["crf"] = qual_val

            # Audio
            preset["audio_codec"] = self._qual_vars["audio_codec"].get().strip() or "aac"
            preset["audio_bitrate"] = self._qual_vars["audio_bitrate"].get().strip() or "320k"

            # NVENC block
            if "nvenc" not in preset or not isinstance(preset["nvenc"], dict):
                preset["nvenc"] = {}
            preset["nvenc"]["codec"] = self._qual_vars["nvenc_codec"].get().strip() or "h264_nvenc"
            preset["nvenc"]["preset"] = self._qual_vars["nvenc_preset"].get().strip() or "p4"
            preset["nvenc"]["rc"] = self._qual_vars["nvenc_rc"].get().strip() or "vbr"
            preset["nvenc"]["cq"] = qual_val

            # Render / performance
            preset["chunk_parallel_enabled"] = bool(self._bool_vars["chunk_parallel_enabled"].get())
            preset["chunk_size"] = to_int_s(self._qual_vars["chunk_size"], "Chunk size")
            preset["cut_fade_ms"] = to_int_s(self._qual_vars["cut_fade_ms"], "Cut fade (ms)")
            preset["two_phase_render_enabled"] = bool(self._bool_vars["two_phase_render_enabled"].get())
            preset["keyframe_snap_tolerance_s"] = to_float_s(
                self._qual_vars["keyframe_snap_tolerance_s"], "Keyframe snap tolerance (sec)"
            )
            cpu_pct = to_int_s(self._qual_vars["cpu_limit_pct"], "CPU limit %")
            if not (1 <= cpu_pct <= 100):
                raise ValueError("CPU limit % must be between 1 and 100")
            preset["cpu_limit_pct"] = cpu_pct

            # ---- Words to remove ----
            words_raw = self._word_vars["words_to_remove"].get().strip()
            words_cfg["words_to_remove"] = [w.strip() for w in words_raw.split(",") if w.strip()]
            words_cfg["confidence_required_host"] = to_float_word(
                "confidence_required_host", "Host confidence required"
            )
            words_cfg["confidence_required_guest"] = to_float_word(
                "confidence_required_guest", "Guest confidence required"
            )
            words_cfg["confidence_bonus_per_word"] = to_float_word(
                "confidence_bonus_per_word", "Confidence bonus per word"
            )
            words_cfg["filler_mute_inset_ms"] = to_int_word(
                "filler_mute_inset_ms", "Mute inset (ms)"
            )
            words_cfg["filler_mute_gap_threshold_ms"] = to_int_word(
                "filler_mute_gap_threshold_ms", "Mute gap threshold (ms)"
            )

            ConfigEditor.write_gui_and_pipeline(
                self._config_path,
                gui_update,
                pipe_cfg,
                qual_presets,
                words_cfg,
            )

        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self._app.set_status("Saved to config.py")
        messagebox.showinfo(
            "Saved",
            "config.py updated. Restart GUI to apply all typography/layout/color changes.",
        )
