from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox

from ui.gui_config_editor import ConfigEditor


# Settings page layout tuning
# - Increase this value to make both panes shorter and lift footer buttons up.
SETTINGS_PANES_HEIGHT_REDUCTION_PX = 120
# - Vertical gap between GUI-pane input rows.
SETTINGS_GUI_FIELD_ROW_GAP_PX = 4


class SettingsPage(tk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, bg=app._palette["bg"])
        self._app = app
        self._config_path = app._project_dir / "config.py"

        # Footer (packed first to reserve space at bottom)
        footer = tk.Frame(self, bg=app._palette["bg"])
        # Bottom padding reserves space so the footer buttons sit higher, and both panes
        # lose the same amount of vertical space.
        footer.pack(side="bottom", fill="x", pady=(14, SETTINGS_PANES_HEIGHT_REDUCTION_PX))
        app._make_btn(footer, "SAVE TO config.py", self._save, kind="primary").pack(side="right")
        app._make_btn(footer, "RELOAD", self._reload, kind="secondary").pack(side="right", padx=(0, 12))

        # Grid (panes) takes remaining space
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

    def _build_gui_form(self, parent: tk.Frame) -> None:
        app = self._app
        self._vars: dict[str, tk.StringVar] = {
            "gui_width": tk.StringVar(),
            "gui_height": tk.StringVar(),
            "font_family": tk.StringVar(),
            "font_title_size": tk.StringVar(),
            "font_section_size": tk.StringVar(),
            "font_body_size": tk.StringVar(),
            "font_mono_family": tk.StringVar(),
            "font_mono_size": tk.StringVar(),
            "button_height": tk.StringVar(),
            # Accent colors (split for easy theming)
            "ui_button_caption_color": tk.StringVar(),
            "ui_accent_font_color": tk.StringVar(),
            "ui_accent_line_color": tk.StringVar(),
        }

        def add_row(label: str, key: str) -> None:
            row = tk.Frame(parent, bg=app._palette["panel"])
            row.pack(fill="x", pady=SETTINGS_GUI_FIELD_ROW_GAP_PX)
            tk.Label(
                row,
                text=label,
                font=app._mono(weight="bold"),
                bg=app._palette["panel"],
                fg=app._palette["muted"],
            ).pack(side="left")
            ent = tk.Entry(
                row,
                textvariable=self._vars[key],
                font=app._mono(),
                bg=app._palette["panel2"],
                fg=app._palette["text"],
                insertbackground=app._ui_colors["accent_line"],
                relief="flat",
                highlightthickness=2,
                highlightbackground=app._palette["edge2"],
                highlightcolor=app._ui_colors["accent_line"],
            )
            ent.pack(side="right", fill="x", expand=True)

        add_row("Window width", "gui_width")
        add_row("Window height", "gui_height")
        add_row("Font family", "font_family")
        add_row("Title size", "font_title_size")
        add_row("Section size", "font_section_size")
        add_row("Body size", "font_body_size")
        add_row("Mono family", "font_mono_family")
        add_row("Mono size", "font_mono_size")
        add_row("Button height", "button_height")
        add_row("Button caption color", "ui_button_caption_color")
        add_row("Accent font color", "ui_accent_font_color")
        add_row("Accent line color", "ui_accent_line_color")

        note = tk.Label(
            parent,
            text=(
                "These values are written into the GUI dict in config.py.\n"
                "Restart GUI to fully apply typography/layout/color changes.\n"
                "Colors accept #RRGGBB."
            ),
            font=app._mono(),
            bg=app._palette["panel"],
            fg=app._palette["muted"],
            justify="left",
        )
        note.pack(anchor="w", pady=(14, 0))

    def _build_pipeline_form(self, parent: tk.Frame) -> None:
        app = self._app
        self._pipe_vars: dict[str, tk.BooleanVar] = {}

        # Quality preset vars (PODCAST_HIGH_QUALITY)
        self._qual_vars: dict[str, tk.StringVar] = {
            "silence_threshold_db": tk.StringVar(value="-45"),
            "min_pause_duration": tk.StringVar(value="2"),
            "silence_window_ms": tk.StringVar(value="100"),
            "spike_threshold_db": tk.StringVar(value="-5"),
            "normalization_standard_target": tk.StringVar(value="-16.0"),
            "normalization_max_gain_db": tk.StringVar(value="15.0"),
        }
        self._norm_mode = tk.StringVar(value="MATCH_HOST")

        # Encoder vars
        self._enc_mode = tk.StringVar(value="cpu")
        self._enc_quality = tk.StringVar(value="18")

        # Scrollable container for pipeline pane
        outer = tk.Frame(parent, bg=app._palette["panel"])
        outer.pack(fill="both", expand=True)

        self._pipe_canvas = tk.Canvas(
            outer,
            bg=app._palette["panel"],
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self._pipe_scroll = tk.Scrollbar(outer, orient="vertical", command=self._pipe_canvas.yview)
        self._pipe_canvas.configure(yscrollcommand=self._pipe_scroll.set)

        self._pipe_scroll.pack(side="right", fill="y")
        self._pipe_canvas.pack(side="left", fill="both", expand=True)

        self._pipe_container = tk.Frame(self._pipe_canvas, bg=app._palette["panel"])
        self._pipe_window = self._pipe_canvas.create_window((0, 0), window=self._pipe_container, anchor="nw")

        def _on_container_configure(_evt=None):
            self._pipe_canvas.configure(scrollregion=self._pipe_canvas.bbox("all"))

        def _on_canvas_configure(_evt=None):
            # Keep inner frame width in sync with canvas width.
            self._pipe_canvas.itemconfigure(self._pipe_window, width=self._pipe_canvas.winfo_width())

        self._pipe_container.bind("<Configure>", _on_container_configure)
        self._pipe_canvas.bind("<Configure>", _on_canvas_configure)

        # Mousewheel scrolling (Windows/macOS)
        def _on_mousewheel(evt):
            # On Windows, evt.delta is typically multiples of 120
            delta = int(-1 * (evt.delta / 120)) if getattr(evt, "delta", 0) else 0
            if delta:
                self._pipe_canvas.yview_scroll(delta, "units")

        def _bind_mousewheel(_evt=None):
            self._pipe_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(_evt=None):
            self._pipe_canvas.unbind_all("<MouseWheel>")

        self._pipe_canvas.bind("<Enter>", _bind_mousewheel)
        self._pipe_canvas.bind("<Leave>", _unbind_mousewheel)

    def _render_pipeline_toggles(self, pipe_cfg: dict, qual_presets: dict) -> None:
        app = self._app
        for c in self._pipe_container.winfo_children():
            c.destroy()

        self._pipe_vars.clear()

        # Load encoding settings (assuming generic 'PODCAST_HIGH_QUALITY' preset)
        preset = qual_presets.get("PODCAST_HIGH_QUALITY", {})

        # Load quality-preset settings
        self._qual_vars["silence_threshold_db"].set(str(preset.get("silence_threshold_db", -45)))
        self._qual_vars["min_pause_duration"].set(str(preset.get("min_pause_duration", 2)))
        self._qual_vars["silence_window_ms"].set(str(preset.get("silence_window_ms", 100)))
        self._qual_vars["spike_threshold_db"].set(str(preset.get("spike_threshold_db", -5)))

        norm = preset.get("normalization")
        if not isinstance(norm, dict):
            norm = {}
        self._norm_mode.set(str(norm.get("mode", "MATCH_HOST")))
        self._qual_vars["normalization_standard_target"].set(str(norm.get("standard_target", -16.0)))
        self._qual_vars["normalization_max_gain_db"].set(str(norm.get("max_gain_db", 15.0)))

        cuda_enabled = bool(preset.get("cuda_encode_enabled", False))
        self._enc_mode.set("gpu" if cuda_enabled else "cpu")

        # Default quality display (CRF as master, or fallback to NVENC CQ)
        start_q = preset.get("crf", 23)
        self._enc_quality.set(str(start_q))

        def mk_section(title: str) -> tk.Frame:
            tk.Label(
                self._pipe_container,
                text=title,
                font=app._mono(weight="bold"),
                bg=app._palette["panel"],
                fg=app._palette["muted"],
            ).pack(anchor="w")
            sec = tk.Frame(self._pipe_container, bg=app._palette["panel"])
            sec.pack(fill="x", pady=(8, 14))
            return sec

        def mk_toggle(sec: tk.Frame, key: str, label: str, initial: bool) -> None:
            var = tk.BooleanVar(value=initial)
            self._pipe_vars[key] = var
            row = tk.Frame(sec, bg=app._palette["panel"])
            row.pack(fill="x", pady=4)
            chk = tk.Checkbutton(
                row,
                text=label,
                variable=var,
                font=app._mono(),
                bg=app._palette["panel"],
                fg=app._palette["text"],
                activebackground=app._palette["panel"],
                activeforeground=app._palette["text"],
                selectcolor=app._palette["panel2"],
                highlightthickness=0,
                bd=0,
            )
            chk.pack(side="left")

        def mk_kv_row(sec: tk.Frame, label: str, var: tk.StringVar, width: int = 10) -> None:
            row = tk.Frame(sec, bg=app._palette["panel"])
            row.pack(fill="x", pady=4)
            tk.Label(
                row,
                text=label,
                font=app._mono(weight="bold"),
                bg=app._palette["panel"],
                fg=app._palette["text"],
            ).pack(side="left")
            ent = tk.Entry(
                row,
                textvariable=var,
                font=app._mono(),
                bg=app._palette["panel2"],
                fg=app._palette["text"],
                insertbackground=app._ui_colors["accent_line"],
                relief="flat",
                highlightthickness=2,
                highlightbackground=app._palette["edge2"],
                highlightcolor=app._ui_colors["accent_line"],
                width=width,
            )
            # Add a small right padding so inputs don't visually touch the scrollbar.
            ent.pack(side="right", padx=(0, 5))

        # --- Quality Presets Section ---
        qual_sec = mk_section("QUALITY PRESETS")
        mk_kv_row(qual_sec, "Silence threshold (dB)", self._qual_vars["silence_threshold_db"], width=10)
        mk_kv_row(qual_sec, "Min pause duration (sec)", self._qual_vars["min_pause_duration"], width=10)
        mk_kv_row(qual_sec, "Silence window (ms)", self._qual_vars["silence_window_ms"], width=10)
        mk_kv_row(qual_sec, "Spike threshold (dB)", self._qual_vars["spike_threshold_db"], width=10)

        tk.Label(
            qual_sec,
            text="Normalization mode",
            font=app._mono(weight="bold"),
            bg=app._palette["panel"],
            fg=app._palette["text"],
        ).pack(anchor="w", pady=(6, 0))

        row_norm = tk.Frame(qual_sec, bg=app._palette["panel"])
        row_norm.pack(fill="x", pady=(2, 8))

        def mk_norm_radio(val: str, label: str) -> None:
            r = tk.Radiobutton(
                row_norm,
                text=label,
                variable=self._norm_mode,
                value=val,
                font=app._mono(),
                bg=app._palette["panel"],
                fg=app._palette["text"],
                selectcolor=app._palette["panel2"],
                activebackground=app._palette["panel"],
                activeforeground=app._palette["text"],
                highlightthickness=0,
                bd=0,
            )
            r.pack(side="left", padx=(0, 10))

        mk_norm_radio("MATCH_HOST", "Match host")
        mk_norm_radio("STANDARD_LUFS", "Standard LUFS")

        mk_kv_row(qual_sec, "Standard target (LUFS)", self._qual_vars["normalization_standard_target"], width=10)
        mk_kv_row(qual_sec, "Max gain (dB)", self._qual_vars["normalization_max_gain_db"], width=10)

        proc_sec = mk_section("PROCESSORS")
        for i, p in enumerate(pipe_cfg.get("processors", [])):
            t = str(p.get("type"))
            mk_toggle(proc_sec, f"processors:{i}", t, bool(p.get("enabled")))

        # --- Encoding Section ---
        enc_sec = mk_section("VIDEO ENCODING")

        # Encoder Selection
        lbl_enc = tk.Label(
            enc_sec,
            text="Encoder",
            font=app._mono(weight="bold"),
            bg=app._palette["panel"],
            fg=app._palette["text"],
        )
        lbl_enc.pack(anchor="w")

        row_enc = tk.Frame(enc_sec, bg=app._palette["panel"])
        row_enc.pack(fill="x", pady=(2, 8))

        def mk_radio(val: str, label: str):
            r = tk.Radiobutton(
                row_enc,
                text=label,
                variable=self._enc_mode,
                value=val,
                font=app._mono(),
                bg=app._palette["panel"],
                fg=app._palette["text"],
                selectcolor=app._palette["panel2"],
                activebackground=app._palette["panel"],
                activeforeground=app._palette["text"],
                highlightthickness=0,
                bd=0,
            )
            r.pack(side="left", padx=(0, 10))

        mk_radio("cpu", "CPU (libx264)")
        mk_radio("gpu", "NVIDIA GPU (NVENC)")

        # Quality
        lbl_qual = tk.Label(
            enc_sec,
            text="Quality (0-51, Lower is Better)",
            font=app._mono(weight="bold"),
            bg=app._palette["panel"],
            fg=app._palette["text"],
        )
        lbl_qual.pack(anchor="w")

        row_qual = tk.Frame(enc_sec, bg=app._palette["panel"])
        row_qual.pack(fill="x", pady=(2, 0))

        ent_qual = tk.Entry(
            row_qual,
            textvariable=self._enc_quality,
            font=app._mono(),
            bg=app._palette["panel2"],
            fg=app._palette["text"],
            insertbackground=app._ui_colors["accent_line"],
            relief="flat",
            highlightthickness=2,
            highlightbackground=app._palette["edge2"],
            highlightcolor=app._ui_colors["accent_line"],
            width=6,
        )
        ent_qual.pack(side="left")

        tk.Label(
            row_qual,
            text="Rec: 16-18 (High), 0 (Lossless)",
            font=app._mono(),
            bg=app._palette["panel"],
            fg=app._palette["muted"],
        ).pack(side="left", padx=10)

        note = tk.Label(
            self._pipe_container,
            text="Settings save to QUALITY_PRESETS & PIPELINE_CONFIG in config.py.\nRestart GUI to apply full pipeline changes.",
            font=app._mono(),
            bg=app._palette["panel"],
            fg=app._palette["muted"],
            justify="left",
        )
        note.pack(anchor="w", pady=(14, 0))

    def _reload(self) -> None:
        try:
            gui_dict, pipe_cfg, qual_presets = ConfigEditor.load_gui_and_pipeline(self._config_path)
        except Exception as e:
            messagebox.showerror("Config load failed", str(e))
            return

        for k, v in self._vars.items():
            v.set(str(gui_dict.get(k, "")))
        self._render_pipeline_toggles(pipe_cfg, qual_presets)
        self._app.set_status("Settings loaded")

    def _save(self) -> None:
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

        try:
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
                "ui_button_caption_color": to_color("ui_button_caption_color"),
                "ui_accent_font_color": to_color("ui_accent_font_color"),
                "ui_accent_line_color": to_color("ui_accent_line_color"),
            }

            _, pipe_cfg, qual_presets = ConfigEditor.load_gui_and_pipeline(self._config_path)

            # Update Pipeline Config
            for k, var in self._pipe_vars.items():
                group, idx_s = k.split(":", 1)
                idx = int(idx_s)
                pipe_cfg[group][idx]["enabled"] = bool(var.get())
            pipe_cfg.pop("detectors", None)

            # Update Quality Presets (Encode Settings)
            preset = qual_presets.get("PODCAST_HIGH_QUALITY")
            if not preset:
                # Should not happen typically
                raise ValueError("PODCAST_HIGH_QUALITY preset missing in config.py")

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

            # Update Quality Preset (analysis + normalization)
            preset["silence_threshold_db"] = to_int_s(
                self._qual_vars["silence_threshold_db"], "Silence threshold (dB)"
            )
            preset["min_pause_duration"] = to_float_s(
                self._qual_vars["min_pause_duration"], "Min pause duration (sec)"
            )
            preset["silence_window_ms"] = to_int_s(self._qual_vars["silence_window_ms"], "Silence window (ms)")
            preset["spike_threshold_db"] = to_int_s(self._qual_vars["spike_threshold_db"], "Spike threshold (dB)")

            preset["normalization"] = {
                "mode": self._norm_mode.get().strip() or "MATCH_HOST",
                "standard_target": to_float_s(
                    self._qual_vars["normalization_standard_target"], "Standard target (LUFS)"
                ),
                "max_gain_db": to_float_s(self._qual_vars["normalization_max_gain_db"], "Max gain (dB)"),
            }

            is_gpu = self._enc_mode.get() == "gpu"
            qual_val = int(self._enc_quality.get().strip())

            preset["cuda_encode_enabled"] = is_gpu
            preset["crf"] = qual_val

            # Ensure nvenc block exists
            if "nvenc" not in preset or not isinstance(preset["nvenc"], dict):
                preset["nvenc"] = {"codec": "h264_nvenc", "preset": "p4", "rc": "vbr"}

            preset["nvenc"]["cq"] = qual_val

            ConfigEditor.write_gui_and_pipeline(self._config_path, gui_update, pipe_cfg, qual_presets)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self._app.set_status("Saved to config.py")
        messagebox.showinfo("Saved", "config.py updated. Restart GUI to apply all typography/layout/color changes.")

