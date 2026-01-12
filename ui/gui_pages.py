from __future__ import annotations

import os
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

from ui.gui_config_editor import ConfigEditor


# Settings page layout tuning
# - Increase this value to make both panes shorter and lift footer buttons up.
SETTINGS_PANES_HEIGHT_REDUCTION_PX = 120
# - Vertical gap between GUI-pane input rows.
SETTINGS_GUI_FIELD_ROW_GAP_PX = 4


class MainPage(tk.Frame):
    # Modified by Claude-4.5-Sonnet | 2026-01-08_08
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, bg=app._palette["bg"])
        self._app = app

        grid = tk.Frame(self, bg=app._palette["bg"])
        grid.pack(fill="both", expand=True)

        grid.grid_rowconfigure(0, weight=0)
        grid.grid_rowconfigure(1, weight=0)
        grid.grid_rowconfigure(2, weight=1)
        grid.grid_columnconfigure(0, weight=1)

        # Files
        files_panel = app._make_panel(grid, "Files")
        files_panel.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 14))
        self._build_files(files_panel.body)

        # Actions (full width)
        actions_panel = app._make_panel(grid, "Actions")
        actions_panel.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 14))
        self._build_actions(actions_panel.body)

        # Logs
        logs_panel = app._make_panel(grid, "Console")
        logs_panel.grid(row=2, column=0, sticky="nsew")
        self._build_logs(logs_panel.body)

    def _build_files(self, parent: tk.Frame) -> None:
        app = self._app
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=0)
        parent.columnconfigure(3, weight=0)

        hdr = app._mono(weight="bold")
        tk.Label(parent, text="BROWSE", font=hdr, bg=app._palette["panel"], fg=app._palette["muted"]).grid(
            row=0, column=0, padx=8, pady=(0, 10), sticky="w"
        )
        tk.Label(parent, text="FILE", font=hdr, bg=app._palette["panel"], fg=app._palette["muted"]).grid(
            row=0, column=1, padx=8, pady=(0, 10), sticky="w"
        )
        tk.Label(parent, text="SIZE", font=hdr, bg=app._palette["panel"], fg=app._palette["muted"]).grid(
            row=0, column=2, padx=8, pady=(0, 10), sticky="w"
        )
        tk.Label(parent, text="LENGTH", font=hdr, bg=app._palette["panel"], fg=app._palette["muted"]).grid(
            row=0, column=3, padx=8, pady=(0, 10), sticky="w"
        )

        self._build_file_row(parent, row_index=1, role="host")
        self._build_file_row(parent, row_index=2, role="guest")

    def _build_file_row(self, parent: tk.Frame, row_index: int, role: str) -> None:
        app = self._app
        btn_text = "BROWSE HOST" if role == "host" else "BROWSE GUEST"
        app._create_file_row(parent, row_index=row_index, role=role, button_text=btn_text)

    def _build_actions(self, parent: tk.Frame) -> None:
        # Modified by Claude-4.5-Sonnet | 2026-01-08_08
        app = self._app

        # Row 1: NORMALIZE GUEST AUDIO, REMOVE PAUSES, RUN ALL
        row1 = tk.Frame(parent, bg=app._palette["panel"])
        row1.pack(fill="x", pady=(0, 10))
        app._make_btn(row1, "NORMALIZE GUEST AUDIO", self._normalize_audio_clicked, kind="secondary").pack(
            side="left", padx=(0, 6)
        )
        app._make_btn(row1, "REMOVE PAUSES", self._remove_pauses_clicked, kind="secondary").pack(
            side="left", padx=(0, 6)
        )
        app._make_btn(row1, "RUN ALL", self._run_clicked, kind="primary").pack(side="left")

        # Row 2: SAVE MODIFIED FILES, CLEAR, OPEN OUT
        row2 = tk.Frame(parent, bg=app._palette["panel"])
        row2.pack(fill="x")
        app._make_btn(row2, "SAVE MODIFIED FILES", self._save_modified_clicked, kind="secondary").pack(
            side="left", padx=(0, 6)
        )
        app._make_btn(row2, "CLEAR", self._clear_clicked, kind="secondary").pack(side="left", padx=(0, 6))
        app._make_btn(row2, "OPEN OUT", self._open_output_clicked, kind="secondary").pack(side="left")

    def _build_logs(self, parent: tk.Frame) -> None:
        # Modified by Claude-4.5-Sonnet | 2026-01-08_11
        app = self._app
        wrap = tk.Frame(parent, bg=app._palette["panel"], highlightthickness=2, highlightbackground=app._palette["edge2"])
        wrap.pack(fill="both", expand=True)

        # Scrollbar for log text (comprehensive gray styling for Windows)
        scrollbar = tk.Scrollbar(
            wrap,
            bg="#555555",
            troughcolor="#2A2A2A",
            activebackground="#777777",
            highlightthickness=0,
            relief="flat",
            bd=0,
            width=16,
        )
        scrollbar.pack(side="right", fill="y")

        self._log_text = tk.Text(
            wrap,
            bg=app._palette["panel2"],
            fg=app._palette["text"],
            insertbackground=app._ui_colors["accent_line"],
            font=app._mono(),
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
            wrap="word",
            yscrollcommand=scrollbar.set,
        )
        self._log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._log_text.yview)

        self._log_text.insert("end", "AV Cleaner console. Output from running main.py will appear here.\n")
        self._log_text.configure(state="disabled")

    def clear_log_view(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def append_log_view(self, text: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_clicked(self) -> None:
        self._app.clear_logs()
        self._app.set_status("Ready")

    def _open_output_clicked(self) -> None:
        # Best-effort: open project folder; output files are next to inputs.
        try:
            os.startfile(str(self._app._project_dir))
        except Exception:
            pass

    def _run_clicked(self) -> None:
        host_row = self._app._rows.get("host")
        guest_row = self._app._rows.get("guest")
        host = host_row.path if host_row else None
        guest = guest_row.path if guest_row else None
        if not host or not guest:
            messagebox.showwarning("Missing files", "Select both HOST and GUEST files first.")
            return
        self._app.run_processing(host, guest, action="ALL")

    # Created by Claude-4.5-Sonnet | 2026-01-08_03
    def _normalize_audio_clicked(self) -> None:
        """Normalize guest audio levels to match host."""

        host_row = self._app._rows.get("host")
        guest_row = self._app._rows.get("guest")
        host = host_row.path if host_row else None
        guest = guest_row.path if guest_row else None
        if not host or not guest:
            messagebox.showwarning("Missing files", "Select both HOST and GUEST files first.")
            return
        self._app.run_processing(host, guest, action="NORMALIZE_GUEST_AUDIO")

    # Created by Claude-4.5-Sonnet | 2026-01-08_03
    def _remove_pauses_clicked(self) -> None:
        """Remove pauses longer than x seconds from both tracks."""

        host_row = self._app._rows.get("host")
        guest_row = self._app._rows.get("guest")
        host = host_row.path if host_row else None
        guest = guest_row.path if guest_row else None
        if not host or not guest:
            messagebox.showwarning("Missing files", "Select both HOST and GUEST files first.")
            return
        self._app.run_processing(host, guest, action="REMOVE_PAUSES")

    # Created by Claude-4.5-Sonnet | 2026-01-08_03
    def _save_modified_clicked(self) -> None:
        """Save new files with _fixed suffix."""

        host_row = self._app._rows.get("host")
        guest_row = self._app._rows.get("guest")
        host = host_row.path if host_row else None
        guest = guest_row.path if guest_row else None
        if not host or not guest:
            messagebox.showwarning("Missing files", "Select both HOST and GUEST files first.")
            return

        self._app.save_fixed_outputs(host, guest)


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
            tk.Label(row, text=label, font=app._mono(weight="bold"), bg=app._palette["panel"], fg=app._palette["muted"]).pack(
                side="left"
            )
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

        self._pipe_container = tk.Frame(parent, bg=app._palette["panel"])
        self._pipe_container.pack(fill="both", expand=True)

    def _render_pipeline_toggles(self, pipe_cfg: dict) -> None:
        app = self._app
        for c in self._pipe_container.winfo_children():
            c.destroy()

        self._pipe_vars.clear()

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

        proc_sec = mk_section("PROCESSORS")
        for i, p in enumerate(pipe_cfg.get("processors", [])):
            t = str(p.get("type"))
            mk_toggle(proc_sec, f"processors:{i}", t, bool(p.get("enabled")))

        note = tk.Label(
            self._pipe_container,
            text="Toggles write back to PIPELINE_CONFIG['processors'] in config.py.\nDetectors run automatically as needed.",
            font=app._mono(),
            bg=app._palette["panel"],
            fg=app._palette["muted"],
            justify="left",
        )
        note.pack(anchor="w")

    def _reload(self) -> None:
        try:
            gui_dict, pipe_cfg = ConfigEditor.load_gui_and_pipeline(self._config_path)
        except Exception as e:
            messagebox.showerror("Config load failed", str(e))
            return

        for k, v in self._vars.items():
            v.set(str(gui_dict.get(k, "")))
        self._render_pipeline_toggles(pipe_cfg)
        self._app.set_status("Settings loaded")

    def _save(self) -> None:
        def to_int(key: str) -> int:
            raw = self._vars[key].get().strip()
            if raw == "":
                raise ValueError(f"{key} is required")
            return int(raw)

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

            _, pipe_cfg = ConfigEditor.load_gui_and_pipeline(self._config_path)
            for k, var in self._pipe_vars.items():
                group, idx_s = k.split(":", 1)
                idx = int(idx_s)
                pipe_cfg[group][idx]["enabled"] = bool(var.get())

            # Back-compat / hardening: detectors are no longer user-facing.
            # If an older config.py still has PIPELINE_CONFIG['detectors'], drop it when saving.
            pipe_cfg.pop("detectors", None)

            ConfigEditor.write_gui_and_pipeline(self._config_path, gui_update, pipe_cfg)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self._app.set_status("Saved to config.py")
        messagebox.showinfo("Saved", "config.py updated. Restart GUI to apply all typography/layout/color changes.")

