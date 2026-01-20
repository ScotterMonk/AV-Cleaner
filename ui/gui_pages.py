from __future__ import annotations

"""GUI pages (Tkinter Frames).

This module contains page-level UI building blocks used by the main GUI app.

Design notes:
- The GUI is intentionally composed from small helpers on the app object
  (see: app._make_panel(), app._make_btn(), app._create_file_row()).
- Page classes focus on layout + wiring (callbacks), while the app owns state
  (selected files, logs, status) and actions (running processing, saving).
"""

import os
import tkinter as tk
from tkinter import messagebox


panel_external_padding_y = 6

class MainPage(tk.Frame):
    # Modified by gpt-5.2 | 2026-01-12_01
    # Modified by Claude-4.5-Sonnet | 2026-01-08_08
    #
    # Purpose
    # -------
    # The main "home" page for the GUI.
    #
    # Responsibilities
    # ----------------
    # - Define the high-level layout (files panel, actions panel, console panel).
    # - Provide button callbacks that validate inputs then delegate to the app.
    # - Manage the console Text widget used by the app's logging bridge.
    #
    # Non-responsibilities
    # --------------------
    # - Does not run ffmpeg / processing directly; delegates to the app.
    # - Does not own file row state; reads rows from app._rows.
    def __init__(self, parent: tk.Widget, app) -> None:
        # Modified by gpt-5.2 | 2026-01-18_01
        super().__init__(parent, bg=app._palette["bg"])
        self._app = app

        # A single grid wrapper makes it easy to allocate fixed-height top panels
        # (Files + Actions) and give the remaining space to the console.
        grid = tk.Frame(self, bg=app._palette["bg"])
        grid.pack(fill="both", expand=True)

        # Layout strategy:
        # - Row 0: Files panel (fixed height by content)
        # - Row 1: Two columns. Each column stacks:
        #     - Left: Actions (fixed) + Console (expand)
        #     - Right: Controls (fixed) + Progress (expand)
        grid.grid_rowconfigure(0, weight=0)
        grid.grid_rowconfigure(1, weight=1)
        grid.grid_columnconfigure(0, weight=1)

        # Files
        # -----
        # Two-row table where each row represents an input role:
        # - host
        # - guest
        files_panel = app._make_panel(grid, "Files")
        files_panel.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, panel_external_padding_y))
        self._build_files(files_panel.body)

        # Row 1: Two columns; each column stacks a fixed-height top panel and
        # an expandable bottom panel.
        row1 = tk.Frame(grid, bg=app._palette["bg"])
        row1.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        row1.grid_rowconfigure(0, weight=1)
        row1.grid_columnconfigure(0, weight=1)
        row1.grid_columnconfigure(1, weight=1)

        # Left column: Actions (top) + Console (bottom)
        left_col = tk.Frame(row1, bg=app._palette["bg"])
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        left_col.grid_rowconfigure(0, weight=0)
        left_col.grid_rowconfigure(1, weight=1)
        left_col.grid_columnconfigure(0, weight=1)

        actions_panel = app._make_panel(left_col, "Actions")
        actions_panel.grid(row=0, column=0, sticky="nsew", pady=(0, panel_external_padding_y))
        self._build_actions(actions_panel.body)

        console_panel = app._make_panel(left_col, "Console")
        console_panel.grid(row=1, column=0, sticky="nsew")
        self._build_logs(console_panel.body)

        # Right column: Controls (top) + Progress (bottom)
        right_col = tk.Frame(row1, bg=app._palette["bg"])
        right_col.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        right_col.grid_rowconfigure(0, weight=0)
        right_col.grid_rowconfigure(1, weight=1)
        right_col.grid_columnconfigure(0, weight=1)

        controls_panel = app._make_panel(right_col, "Controls")
        controls_panel.grid(row=0, column=0, sticky="nsew", pady=(0, panel_external_padding_y))
        self._build_controls(controls_panel.body)

        progress_panel = app._make_panel(right_col, "Progress")
        progress_panel.grid(row=1, column=0, sticky="nsew")
        self._build_progress(progress_panel.body)

    def _build_files(self, parent: tk.Frame) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        app = self._app

        # Table layout:
        #   col 0: browse button
        #   col 1: selected file path (stretch)
        #   col 2: file size
        #   col 3: media length / duration
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=0)
        parent.columnconfigure(3, weight=0)

        # Header row: use monospace + bold so it resembles a simple table.
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

        # Input rows: host first, guest second.
        # The app helper wires up the browse action and populates size/length.
        self._build_file_row(parent, row_index=1, role="host")
        self._build_file_row(parent, row_index=2, role="guest")

    def _build_file_row(self, parent: tk.Frame, row_index: int, role: str) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        app = self._app

        # Label the browse button by role so users always know which input they
        # are picking (host vs guest).
        btn_text = "BROWSE HOST" if role == "host" else "BROWSE GUEST"
        app._create_file_row(parent, row_index=row_index, role=role, button_text=btn_text)

    def _build_controls(self, parent: tk.Frame) -> None:
        # Modified by gpt-5.2 | 2026-01-12_02
        app = self._app

        # Center the buttons
        container = tk.Frame(parent, bg=app._palette["panel"])
        container.pack(expand=True)

        # VCR-like buttons: Play, Pause, Stop
        # Using unicode symbols
        app._make_btn(container, "▶", lambda: None, kind="primary").pack(side="left", padx=6)
        app._make_btn(container, "‖", lambda: None, kind="secondary").pack(side="left", padx=6)
        app._make_btn(container, "⏹", lambda: None, kind="secondary").pack(side="left", padx=6)

    def _build_actions(self, parent: tk.Frame) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Modified by Claude-4.5-Sonnet | 2026-01-08_08
        app = self._app

        # Actions are arranged as two packed rows for simple left-to-right flow.
        # Using pack() here keeps the button row heights content-driven.

        # Single row: PROCESS, SAVE MODIFIED FILES, CLEAR, OPEN OUT
        # Keep all actions aligned on one line with consistent horizontal spacing.
        row = tk.Frame(parent, bg=app._palette["panel"])
        row.pack(fill="x")
        app._make_btn(row, "PROCESS", self._run_clicked, kind="primary").pack(side="left", padx=(0, 6))
        app._make_btn(row, "SAVE MODIFIED FILES", self._save_modified_clicked, kind="secondary").pack(
            side="left", padx=(0, 6)
        )
        app._make_btn(row, "CLEAR", self._clear_clicked, kind="secondary").pack(side="left", padx=(0, 6))
        app._make_btn(row, "OPEN OUT", self._open_output_clicked, kind="secondary").pack(side="left")

    def _build_logs(self, parent: tk.Frame) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Modified by Claude-4.5-Sonnet | 2026-01-08_11
        # Modified by gpt-5.2 | 2026-01-15_01
        app = self._app

        # Outer wrapper adds an "edge" so the console reads as a distinct surface.
        wrap = tk.Frame(parent, bg=app._palette["panel"], highlightthickness=2, highlightbackground=app._palette["edge2"])
        wrap.pack(fill="both", expand=True)

        # Console header (visible from start so users know column layout)
        self._console_header = tk.Frame(
            wrap,
            bg=app._palette["panel2"],
            height=20,
        )
        self._console_header.pack_propagate(False)
        self._console_header.pack(side="top", fill="x")

        from ui.gui_ffmpeg_formatter import get_header_line

        self._header_text = tk.Text(
            self._console_header,
            bg=app._palette["panel2"],
            fg=app._palette["muted"],
            font=app._mono(),
            relief="flat",
            bd=0,
            padx=0,
            pady=0,
            height=1,
            wrap="none",
            cursor="arrow",
        )
        self._header_text.pack(side="left", fill="both", expand=True)
        self._header_text.insert("1.0", get_header_line())
        self._header_text.configure(state="disabled")

        # Invisible scrollbar spacer so header matches the body scrollbar width.
        header_scrollbar = tk.Scrollbar(
            self._console_header,
            bg=app._palette["panel2"],
            troughcolor=app._palette["panel2"],
            activebackground=app._palette["panel2"],
            highlightthickness=0,
            relief="flat",
            bd=0,
            width=12,
        )
        header_scrollbar.pack(side="right", fill="y")

        # Console area (scrolling pane).
        self._log_area = tk.Frame(wrap, bg=app._palette["panel"])
        self._log_area.pack(side="top", fill="both", expand=True, pady=(15, 0))

        # Scrollbar for log text (comprehensive gray styling for Windows)
        scrollbar = tk.Scrollbar(
            self._log_area,
            bg="#555555",
            troughcolor="#2A2A2A",
            activebackground="#777777",
            highlightthickness=0,
            relief="flat",
            bd=0,
            width=12,
        )
        scrollbar.pack(side="right", fill="y")

        self._log_text = tk.Text(
            self._log_area,
            bg=app._palette["panel2"],
            fg=app._palette["text"],
            insertbackground=app._ui_colors["accent_line"],
            font=app._mono(),
            relief="flat",
            bd=0,
            padx=16,
            pady=10,
            wrap="word",
            yscrollcommand=scrollbar.set,
        )
        self._log_text.pack(side="left", fill="both", expand=True)
        self._enable_text_copy_shortcuts(self._log_text)
        scrollbar.config(command=self._log_text.yview)

        # Initial banner line: users can confirm the console is working even
        # before any processing begins.
        self._log_text.insert("end", "AV Cleaner console. Output from running main.py will appear here.\n")
        self._log_text.configure(state="disabled")

    def _build_progress(self, parent: tk.Frame) -> None:
        # Created by gpt-5.2 | 2026-01-15_01
        app = self._app

        # Outer wrapper adds an "edge" so the progress reads as a distinct surface.
        wrap = tk.Frame(parent, bg=app._palette["panel"], highlightthickness=2, highlightbackground=app._palette["edge2"])
        wrap.pack(fill="both", expand=True)

        # Progress area (scrolling pane).
        self._progress_area = tk.Frame(wrap, bg=app._palette["panel"])
        self._progress_area.pack(side="top", fill="both", expand=True)

        scrollbar = tk.Scrollbar(
            self._progress_area,
            bg="#555555",
            troughcolor="#2A2A2A",
            activebackground="#777777",
            highlightthickness=0,
            relief="flat",
            bd=0,
            width=12,
        )
        scrollbar.pack(side="right", fill="y")

        self._progress_text = tk.Text(
            self._progress_area,
            bg=app._palette["panel2"],
            fg=app._palette["text"],
            insertbackground=app._ui_colors["accent_line"],
            font=app._mono(),
            relief="flat",
            bd=0,
            padx=16,
            pady=10,
            wrap="word",
            yscrollcommand=scrollbar.set,
        )
        self._progress_text.pack(side="left", fill="both", expand=True)
        self._enable_text_copy_shortcuts(self._progress_text)
        scrollbar.config(command=self._progress_text.yview)

        self._progress_text.insert("end", "High level progress output will appear here.\n")
        self._progress_text.configure(state="disabled")

    def _enable_text_copy_shortcuts(self, widget: tk.Text) -> None:
        # Created by gpt-5.2 | 2026-01-18_02
        """Make read-only Text widgets copyable via Ctrl+C on Windows.

        Tkinter Text widgets in `state="disabled"` can allow selection, but may not
        reliably receive focus / default copy bindings depending on platform/theme.
        We bind focus + copy explicitly.
        """

        def focus_on_click(event) -> None:
            widget.focus_set()

        def copy_selection(event):
            try:
                selected = widget.get("sel.first", "sel.last")
            except tk.TclError:
                return "break"

            widget.clipboard_clear()
            widget.clipboard_append(selected)
            widget.update()
            return "break"

        widget.bind("<Button-1>", focus_on_click, add=True)
        widget.bind("<<Copy>>", copy_selection)
        widget.bind("<Control-c>", copy_selection)
        widget.bind("<Control-C>", copy_selection)
        widget.bind("<Control-Insert>", copy_selection)

    def clear_log_view(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Text widgets must be writable to edit contents; switch state briefly.
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def clear_progress_view(self) -> None:
        # Created by gpt-5.2 | 2026-01-15_01
        self._progress_text.configure(state="normal")
        self._progress_text.delete("1.0", "end")
        self._progress_text.configure(state="disabled")

    def append_log_view(self, text: str) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Append and auto-scroll. The widget stays read-only outside of writes.
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def append_progress_view(self, text: str) -> None:
        # Created by gpt-5.2 | 2026-01-15_01
        self._progress_text.configure(state="normal")
        self._progress_text.insert("end", text)
        self._progress_text.see("end")
        self._progress_text.configure(state="disabled")

    def _clear_clicked(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Progress header stays visible (shows column layout at all times)
        self._app.clear_logs()
        try:
            self._app.clear_progress()
        except Exception:
            pass
        self._app.set_status("Ready")

    def _open_output_clicked(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Best-effort: open project folder; output files are next to inputs.
        # Windows-only convenience: os.startfile opens Explorer at the folder.
        try:
            os.startfile(str(self._app._project_dir))
        except Exception:
            # If we can't open a folder (permissions, invalid path), ignore.
            pass

    def _run_clicked(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # "PROCESS" requires both files because it performs sync-preserving edits
        # that must be applied to host + guest together.
        host_row = self._app._rows.get("host")
        guest_row = self._app._rows.get("guest")
        host = host_row.path if host_row else None
        guest = guest_row.path if guest_row else None
        if not host or not guest:
            messagebox.showwarning("Missing files", "Select both HOST and GUEST files first.")
            return
        self._app.run_processing(host, guest)

    # Created by Claude-4.5-Sonnet | 2026-01-08_03
    def _save_modified_clicked(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        """Save new files with _fixed suffix."""

        # Saving outputs is a separate step so users can run multiple actions and
        # review logs before writing files.
        host_row = self._app._rows.get("host")
        guest_row = self._app._rows.get("guest")
        host = host_row.path if host_row else None
        guest = guest_row.path if guest_row else None
        if not host or not guest:
            messagebox.showwarning("Missing files", "Select both HOST and GUEST files first.")
            return

        self._app.save_fixed_outputs(host, guest)

