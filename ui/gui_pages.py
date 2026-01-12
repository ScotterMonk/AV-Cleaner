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
        super().__init__(parent, bg=app._palette["bg"])
        self._app = app

        # A single grid wrapper makes it easy to allocate fixed-height top panels
        # (Files + Actions) and give the remaining space to the console.
        grid = tk.Frame(self, bg=app._palette["bg"])
        grid.pack(fill="both", expand=True)

        # Layout strategy:
        # - Row 0: Files panel (fixed height by content)
        # - Row 1: Actions panel (fixed height by content)
        # - Row 2: Console panel (takes remaining space)
        grid.grid_rowconfigure(0, weight=0)
        grid.grid_rowconfigure(1, weight=0)
        grid.grid_rowconfigure(2, weight=1)
        grid.grid_columnconfigure(0, weight=1)

        # Files
        # -----
        # Two-row table where each row represents an input role:
        # - host
        # - guest
        files_panel = app._make_panel(grid, "Files")
        files_panel.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 14))
        self._build_files(files_panel.body)

        # Actions (full width)
        # --------------------
        # Primary processing controls. This panel uses two horizontal button rows.
        actions_panel = app._make_panel(grid, "Actions")
        actions_panel.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 14))
        self._build_actions(actions_panel.body)

        # Logs
        # ----
        # Console output pane. The app writes here while processing.
        logs_panel = app._make_panel(grid, "Console")
        logs_panel.grid(row=2, column=0, sticky="nsew")
        self._build_logs(logs_panel.body)

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

    def _build_actions(self, parent: tk.Frame) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Modified by Claude-4.5-Sonnet | 2026-01-08_08
        app = self._app

        # Actions are arranged as two packed rows for simple left-to-right flow.
        # Using pack() here keeps the button row heights content-driven.

        # Row 1: NORMALIZE GUEST AUDIO, REMOVE PAUSES, RUN ALL
        # "RUN ALL" is the primary action (styled differently).
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
        # - SAVE MODIFIED FILES: writes final outputs (if already processed)
        # - CLEAR: clears the console and resets status
        # - OPEN OUT: opens the output folder (best-effort)
        row2 = tk.Frame(parent, bg=app._palette["panel"])
        row2.pack(fill="x")
        app._make_btn(row2, "SAVE MODIFIED FILES", self._save_modified_clicked, kind="secondary").pack(
            side="left", padx=(0, 6)
        )
        app._make_btn(row2, "CLEAR", self._clear_clicked, kind="secondary").pack(side="left", padx=(0, 6))
        app._make_btn(row2, "OPEN OUT", self._open_output_clicked, kind="secondary").pack(side="left")

    def _build_logs(self, parent: tk.Frame) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Modified by Claude-4.5-Sonnet | 2026-01-08_11
        app = self._app

        # Outer wrapper adds an "edge" so the console reads as a distinct surface.
        wrap = tk.Frame(parent, bg=app._palette["panel"], highlightthickness=2, highlightbackground=app._palette["edge2"])
        wrap.pack(fill="both", expand=True)

        # Progress header (hidden by default; shown when an Action starts)
        self._progress_header = tk.Frame(
            wrap,
            bg=app._palette["panel2"],
            height=20,
        )
        self._progress_header.pack_propagate(False)
        # Pack then immediately hide so later we can show it in a stable position
        # (above the log area) via pack(before=...).
        self._progress_header.pack(side="top", fill="x")
        self._progress_header.pack_forget()

        # Use a Text widget for the header so it uses the exact same character-based
        # formatting as the data lines (ensures perfect alignment)
        from ui.gui_ffmpeg_formatter import get_header_line

        # Header is a one-line, read-only Text widget so it shares:
        # - font metrics (monospace)
        # - padding
        # - character alignment
        # with the scrolling log below (which prints ffmpeg-like columns).
        self._header_text = tk.Text(
            self._progress_header,
            bg=app._palette["panel2"],
            fg=app._palette["muted"],
            font=app._mono(),
            relief="flat",
            bd=0,
            # Text widget *internal* padding (inside the Text widget border).
            # This shifts the insertion point for all rendered text, adding 10px
            # on the left AND right edges of the header line.
            # Keeping it equal to the log Text's padx makes header columns start
            # at the same x-position as the data lines below.
            padx=0,
            pady=0,  # Remove vertical padding to keep it slim
            height=1,
            wrap="none",
            cursor="arrow",
        )
        self._header_text.pack(side="left", fill="both", expand=True)

        # Insert header line with same formatting as data
        self._header_text.insert("1.0", get_header_line())
        self._header_text.configure(state="disabled")  # Make it read-only

        # Use an actual Scrollbar (styled invisibly) instead of a Frame spacer.
        header_scrollbar = tk.Scrollbar(
            self._progress_header,
            bg=app._palette["panel2"],           # Match header background (invisible)
            troughcolor=app._palette["panel2"],  # Match header background (invisible)
            activebackground=app._palette["panel2"],  # Match header background (invisible)
            highlightthickness=0,
            relief="flat",
            bd=0,
            width=12,  # Same width as data scrollbar
        )
        header_scrollbar.pack(side="right", fill="y")

        # Log area (scrolling pane). Moved down to create separation under the header.
        # Note: when the header is hidden, the extra top padding keeps the console
        # from feeling cramped against the panel border.
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
            # Text widget *internal* padding (inside the Text widget border).
            # This adds 10px on the left AND right edges before/after text.
            # Matching the header's padx keeps header + data column alignment.
            padx=16,
            pady=10,
            wrap="word",
            yscrollcommand=scrollbar.set,
        )
        self._log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._log_text.yview)

        # Initial banner line: users can confirm the console is working even
        # before any processing begins.
        self._log_text.insert("end", "AV Cleaner console. Output from running main.py will appear here.\n")
        self._log_text.configure(state="disabled")

    def show_progress_header(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        """Show the fixed header row above the scrolling console."""

        if not hasattr(self, "_progress_header") or not hasattr(self, "_log_area"):
            return

        # Ensure it appears above the scrolling pane.
        # pack(before=...) keeps the header in a stable position even if other
        # widgets are re-packed later.
        self._progress_header.pack(side="top", fill="x", before=self._log_area)

    def hide_progress_header(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        """Hide the fixed header row above the scrolling console."""

        if not hasattr(self, "_progress_header"):
            return
        try:
            self._progress_header.pack_forget()
        except Exception:
            # Tkinter can raise if called mid-destroy; hiding the header is best-effort.
            pass

    def clear_log_view(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Text widgets must be writable to edit contents; switch state briefly.
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def append_log_view(self, text: str) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Append and auto-scroll. The widget stays read-only outside of writes.
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_clicked(self) -> None:
        # Modified by gpt-5.2 | 2026-01-12_01
        # Clearing should also hide the progress header so the console returns to
        # an "idle" look.
        self.hide_progress_header()
        self._app.clear_logs()
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
        # "RUN ALL" requires both files because it performs sync-preserving edits
        # that must be applied to host + guest together.
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
        # Modified by gpt-5.2 | 2026-01-12_01
        """Normalize guest audio levels to match host."""

        # Normalization is defined relative to the host track, so both must exist.
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
        # Modified by gpt-5.2 | 2026-01-12_01
        """Remove pauses longer than x seconds from both tracks."""

        # Pause removal must trim both streams identically to preserve sync.
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

