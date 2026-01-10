"""
AV Cleaner GUI.
Run: python app.py
"""

import ast
import os
import pprint
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
import tkinter as tk
from tkinter import filedialog, messagebox

import ffmpeg

from config import GUI
from utils.path_helpers import make_fixed_output_path, make_processed_output_path


PROJECT_DIR = Path(__file__).resolve().parent


@dataclass
class _FileRowState:
    path: str | None
    file_var: tk.StringVar
    size_var: tk.StringVar
    length_var: tk.StringVar


def format_bytes(num_bytes: int) -> str:
    """Format bytes as a compact human-readable string."""

    if num_bytes < 0:
        return ""

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def get_video_duration_seconds(video_path: str) -> float:
    """Return video duration in seconds using ffprobe via ffmpeg-python."""

    probe = ffmpeg.probe(video_path)
    duration_str = probe.get("format", {}).get("duration")
    if not duration_str:
        return 0.0
    try:
        return float(duration_str)
    except (TypeError, ValueError):
        return 0.0


# Created by gpt-5.2 | 2026-01-08_01
class AVCleanerGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("AV Cleaner")

        self._palette = {
            "bg": "#0B0D10",
            "panel": "#12161B",
            "panel2": "#0F1318",
            "text": "#E9EEF5",
            "muted": "#A3ABB8",
            "edge": "#E9EEF5",
            "edge2": "#2C3440",
            "accent": "#FCEE09",
            "danger": "#FF3B30",
            "good": "#00E676",
        }

        self._fonts = {
            "family": str(GUI.get("font_family", "Segoe UI")),
            "mono_family": str(GUI.get("font_mono_family", "Cascadia Mono")),
            "title": int(GUI.get("font_title_size", 18)),
            "section": int(GUI.get("font_section_size", 11)),
            "body": int(GUI.get("font_body_size", 10)),
            "mono": int(GUI.get("font_mono_size", 9)),
        }

        self._button_height = int(GUI.get("button_height", 12))

        width = int(GUI.get("gui_width", 1100))
        height = int(GUI.get("gui_height", 720))
        self.geometry(f"{width}x{height}")
        self.minsize(940, 620)

        self.configure(bg=self._palette["bg"])

        self._rows: dict[str, _FileRowState] = {}
        self._status_var = tk.StringVar(value="Ready")

        self._log_queue: Queue[str] = Queue()
        self._proc: subprocess.Popen | None = None

        self._build_shell()
        self._poll_log_queue()

    def _f(self, size: int, weight: str = "normal", family: str | None = None) -> tuple[str, int, str]:
        return (family or self._fonts["family"], size, weight)

    def _mono(self, size: int | None = None, weight: str = "normal") -> tuple[str, int, str]:
        return (self._fonts["mono_family"], int(size or self._fonts["mono"]), weight)

    def _style_label(self, w: tk.Label, *, fg: str | None = None, bg: str | None = None) -> None:
        w.configure(
            bg=bg or self._palette["panel"],
            fg=fg or self._palette["text"],
        )

    def _make_panel(self, parent: tk.Widget, title: str) -> tk.Frame:
        # Modified by Claude-4.5-Sonnet | 2026-01-08_03
        # 1px yellow borders
        outer = tk.Frame(
            parent,
            bg=self._palette["panel"],
            highlightthickness=1,
            highlightbackground=self._palette["accent"],
            highlightcolor=self._palette["accent"],
            relief="flat",
            bd=0,
        )

        # Bold header with accent stripe
        hdr = tk.Frame(outer, bg=self._palette["panel2"], highlightthickness=0, bd=0)
        hdr.pack(fill="x")
        
        # Accent stripe on left edge
        stripe = tk.Frame(hdr, bg=self._palette["accent"], width=6)
        stripe.pack(side="left", fill="y")
        
        lbl = tk.Label(hdr, text=title.upper(), font=self._f(self._fonts["section"], "bold"))
        lbl.configure(bg=self._palette["panel2"], fg=self._palette["accent"])
        lbl.pack(side="left", padx=16, pady=14)

        body = tk.Frame(outer, bg=self._palette["panel"])
        body.pack(fill="both", expand=True, padx=16, pady=16)
        outer.body = body  # type: ignore[attr-defined]
        return outer

    def _make_btn(self, parent: tk.Widget, text: str, command, *, kind: str = "primary") -> tk.Button:
        # Modified by Claude-4.5-Sonnet | 2026-01-08_04
        # Flat buttons with yellow text and edge glow on hover
        # button_height from config controls vertical padding
        
        # Metallic gradient simulation: dark gunmetal with highlights
        bg_metal_dark = "#2A2D32"
        bg_metal_light = "#3A3F47"
        bg_metal = bg_metal_light if kind == "primary" else bg_metal_dark
        
        # Yellow text for all buttons
        fg_yellow = self._palette["accent"]
        
        # Edge color: matches background when inactive (invisible outline)
        edge_invisible = bg_metal
        edge_glow = self._palette["accent"]
        
        # Calculate height in text lines (approximation for visual consistency)
        # Tkinter button height is in text lines, not pixels
        btn_height_lines = max(1, self._button_height // 10)
        
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            font=self._f(self._fonts["body"], "bold"),
            bg=bg_metal,
            fg=fg_yellow,
            activebackground=bg_metal,
            activeforeground=fg_yellow,
            relief="flat",
            bd=0,
            highlightthickness=3,
            highlightbackground=edge_invisible,
            highlightcolor=edge_invisible,
            height=btn_height_lines,
            padx=16,
            pady=0,
        )
        
        # Cursor
        try:
            btn.configure(cursor="hand2")
        except tk.TclError:
            pass
        
        # Hover effects: light up edges
        def _enter(_evt=None) -> None:
            btn.configure(
                highlightbackground=edge_glow,
                highlightcolor=edge_glow,
                bg="#454C57",
                relief="flat"
            )
        
        def _leave(_evt=None) -> None:
            btn.configure(
                highlightbackground=edge_invisible,
                highlightcolor=edge_invisible,
                bg=bg_metal,
                relief="flat"
            )
        
        btn.bind("<Enter>", _enter)
        btn.bind("<Leave>", _leave)
        return btn

    def _build_shell(self) -> None:
        # Top bar
        top = tk.Frame(self, bg=self._palette["bg"])
        top.pack(fill="x", padx=18, pady=(18, 8))

        title = tk.Label(top, text="AV CLEANER", font=self._f(self._fonts["title"], "bold"), bg=self._palette["bg"], fg=self._palette["text"])
        title.pack(side="left")

        nav = tk.Frame(top, bg=self._palette["bg"])
        nav.pack(side="right")

        self._page_container = tk.Frame(self, bg=self._palette["bg"])
        self._page_container.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        self._page_container.grid_rowconfigure(0, weight=1)
        self._page_container.grid_columnconfigure(0, weight=1)

        self._pages: dict[str, tk.Frame] = {}
        self._pages["main"] = MainPage(self._page_container, app=self)
        self._pages["settings"] = SettingsPage(self._page_container, app=self)
        for page in self._pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self._nav_main_btn = self._make_btn(nav, "MAIN", lambda: self.show_page("main"), kind="secondary")
        self._nav_main_btn.pack(side="left", padx=(0, 10))
        self._nav_settings_btn = self._make_btn(nav, "SETTINGS", lambda: self.show_page("settings"), kind="secondary")
        self._nav_settings_btn.pack(side="left")

        # Status bar
        status = tk.Frame(self, bg=self._palette["panel2"], highlightthickness=2, highlightbackground=self._palette["edge2"])
        status.pack(fill="x", padx=18, pady=(0, 18))
        tk.Label(status, text="STATUS", font=self._mono(self._fonts["mono"], "bold"), bg=self._palette["panel2"], fg=self._palette["muted"]).pack(side="left", padx=12, pady=10)
        tk.Label(status, textvariable=self._status_var, font=self._mono(self._fonts["mono"]), bg=self._palette["panel2"], fg=self._palette["text"]).pack(side="left", padx=10, pady=10)

        self.show_page("main")

    def show_page(self, name: str) -> None:
        page = self._pages[name]
        page.tkraise()

    def set_status(self, text: str) -> None:
        self._status_var.set(text)

    def clear_logs(self) -> None:
        self._log_queue.put("__CLEAR__")

    def append_log(self, text: str) -> None:
        self._log_queue.put(text)

    def _poll_log_queue(self) -> None:
        try:
            while True:
                line = self._log_queue.get_nowait()
                if line == "__CLEAR__":
                    main: MainPage = self._pages["main"]  # type: ignore[assignment]
                    main.clear_log_view()
                else:
                    main = self._pages["main"]  # type: ignore[assignment]
                    main.append_log_view(line)
        except Empty:
            pass
        self.after(60, self._poll_log_queue)

    def run_processing(self, host_path: str, guest_path: str, *, action: str = "ALL") -> None:
        if self._proc and self._proc.poll() is None:
            messagebox.showwarning("Already running", "A job is already running.")
            return

        self.clear_logs()
        self.set_status("Running…")

        cmd = [
            sys.executable,
            "main.py",
            "--host",
            host_path,
            "--guest",
            guest_path,
            "--action",
            action,
        ]
        self.append_log("$ " + " ".join(cmd) + "\n")

        def _worker() -> None:
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=str(PROJECT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert self._proc.stdout is not None
                for line in self._proc.stdout:
                    self.append_log(line)
                code = self._proc.wait()
                if code == 0:
                    self.set_status("Done")
                else:
                    self.set_status(f"Failed (exit {code})")
            except Exception as e:
                self.append_log(f"\n[GUI] Failed to run: {e}\n")
                self.set_status("Failed")

        threading.Thread(target=_worker, daemon=True).start()

    def _create_file_row(self, parent: tk.Widget, row_index: int, role: str, *, button_text: str | None = None) -> None:
        browse_btn = self._make_btn(
            parent,
            button_text or "BROWSE",
            command=lambda r=role: self._select_file(r),
            kind="secondary",
        )
        browse_btn.grid(row=row_index, column=0, padx=8, pady=6, sticky="w")

        file_var = tk.StringVar(value="")
        size_var = tk.StringVar(value="")
        length_var = tk.StringVar(value="")

        tk.Label(parent, textvariable=file_var, anchor="w", font=self._mono(), bg=self._palette["panel"], fg=self._palette["text"]).grid(row=row_index, column=1, padx=8, pady=6, sticky="ew")
        tk.Label(parent, textvariable=size_var, anchor="w", font=self._mono(), bg=self._palette["panel"], fg=self._palette["muted"]).grid(row=row_index, column=2, padx=8, pady=6, sticky="w")
        tk.Label(parent, textvariable=length_var, anchor="w", font=self._mono(), bg=self._palette["panel"], fg=self._palette["muted"]).grid(row=row_index, column=3, padx=8, pady=6, sticky="w")

        self._rows[role] = _FileRowState(path=None, file_var=file_var, size_var=size_var, length_var=length_var)

    def _select_file(self, role: str) -> None:
        title = "Select Host Video" if role == "host" else "Select Guest Video"
        video_path = filedialog.askopenfilename(
            title=title,
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if not video_path:
            return

        self._set_row_for_path(role=role, video_path=video_path)

    def _set_row_for_path(self, role: str, video_path: str) -> None:
        row = self._rows[role]
        row.path = video_path

        row.file_var.set(os.path.basename(video_path))

        try:
            size_bytes = os.path.getsize(video_path)
            row.size_var.set(format_bytes(size_bytes))
        except OSError:
            row.size_var.set("")

        try:
            duration_s = get_video_duration_seconds(video_path)
            row.length_var.set(f"{duration_s:.2f}s")
        except Exception:
            row.length_var.set("")


class MainPage(tk.Frame):
    # Modified by Claude-4.5-Sonnet | 2026-01-08_08
    def __init__(self, parent: tk.Widget, app: AVCleanerGUI) -> None:
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
        tk.Label(parent, text="BROWSE", font=hdr, bg=app._palette["panel"], fg=app._palette["muted"]).grid(row=0, column=0, padx=8, pady=(0, 10), sticky="w")
        tk.Label(parent, text="FILE", font=hdr, bg=app._palette["panel"], fg=app._palette["muted"]).grid(row=0, column=1, padx=8, pady=(0, 10), sticky="w")
        tk.Label(parent, text="SIZE", font=hdr, bg=app._palette["panel"], fg=app._palette["muted"]).grid(row=0, column=2, padx=8, pady=(0, 10), sticky="w")
        tk.Label(parent, text="LENGTH", font=hdr, bg=app._palette["panel"], fg=app._palette["muted"]).grid(row=0, column=3, padx=8, pady=(0, 10), sticky="w")

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
        app._make_btn(row1, "NORMALIZE GUEST AUDIO", self._normalize_audio_clicked, kind="secondary").pack(side="left", padx=(0, 6))
        app._make_btn(row1, "REMOVE PAUSES", self._remove_pauses_clicked, kind="secondary").pack(side="left", padx=(0, 6))
        app._make_btn(row1, "RUN ALL", self._run_clicked, kind="primary").pack(side="left")
        
        # Row 2: SAVE MODIFIED FILES, CLEAR, OPEN OUT
        row2 = tk.Frame(parent, bg=app._palette["panel"])
        row2.pack(fill="x")
        app._make_btn(row2, "SAVE MODIFIED FILES", self._save_modified_clicked, kind="secondary").pack(side="left", padx=(0, 6))
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
            width=16
        )
        scrollbar.pack(side="right", fill="y")

        self._log_text = tk.Text(
            wrap,
            bg=app._palette["panel2"],
            fg=app._palette["text"],
            insertbackground=app._palette["accent"],
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
            os.startfile(str(PROJECT_DIR))
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

        # Match the pipeline naming behavior (_processed.mp4) so we can locate outputs.
        # Note: "NORMALIZE GUEST AUDIO" intentionally does NOT generate a new host file.
        host_processed = make_processed_output_path(host)
        guest_processed = make_processed_output_path(guest)

        host_exists = os.path.exists(host_processed)
        guest_exists = os.path.exists(guest_processed)

        if not host_exists and not guest_exists:
            messagebox.showwarning(
                "Nothing to save",
                "Expected processed files not found. Run an action first.\n\nMissing:\n"
                + "\n".join([host_processed, guest_processed]),
            )
            return

        def to_fixed(path: str) -> str:
            return make_fixed_output_path(path)

        try:
            saved_lines = []

            if host_exists:
                host_fixed = to_fixed(host_processed)
                shutil.copy2(host_processed, host_fixed)
                saved_lines.append(f"  {host_fixed}")

            if guest_exists:
                guest_fixed = to_fixed(guest_processed)
                shutil.copy2(guest_processed, guest_fixed)
                saved_lines.append(f"  {guest_fixed}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self._app.append_log("[GUI] Saved fixed copies:\n" + "\n".join(saved_lines) + "\n")
        self._app.set_status("Saved _fixed files")


class SettingsPage(tk.Frame):
    def __init__(self, parent: tk.Widget, app: AVCleanerGUI) -> None:
        super().__init__(parent, bg=app._palette["bg"])
        self._app = app
        self._config_path = PROJECT_DIR / "config.py"

        grid = tk.Frame(self, bg=app._palette["bg"])
        grid.pack(fill="both", expand=True)
        grid.grid_rowconfigure(0, weight=1)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        gui_panel = app._make_panel(grid, "GUI")
        gui_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self._build_gui_form(gui_panel.body)

        pipeline_panel = app._make_panel(grid, "Pipeline")
        pipeline_panel.grid(row=0, column=1, sticky="nsew")
        self._build_pipeline_form(pipeline_panel.body)

        footer = tk.Frame(self, bg=app._palette["bg"])
        footer.pack(fill="x", pady=(14, 0))
        app._make_btn(footer, "SAVE TO config.py", self._save, kind="primary").pack(side="right")
        app._make_btn(footer, "RELOAD", self._reload, kind="secondary").pack(side="right", padx=(0, 12))

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
        }

        def add_row(label: str, key: str) -> None:
            row = tk.Frame(parent, bg=app._palette["panel"])
            row.pack(fill="x", pady=6)
            tk.Label(row, text=label, font=app._mono(weight="bold"), bg=app._palette["panel"], fg=app._palette["muted"]).pack(side="left")
            ent = tk.Entry(
                row,
                textvariable=self._vars[key],
                font=app._mono(),
                bg=app._palette["panel2"],
                fg=app._palette["text"],
                insertbackground=app._palette["accent"],
                relief="flat",
                highlightthickness=2,
                highlightbackground=app._palette["edge2"],
                highlightcolor=app._palette["accent"],
            )
            ent.pack(side="right", fill="x", expand=True)

        add_row("Window width", "gui_width")
        add_row("Window height", "gui_height")
        tk.Frame(parent, height=10, bg=app._palette["panel"]).pack(fill="x")
        add_row("Font family", "font_family")
        add_row("Title size", "font_title_size")
        add_row("Section size", "font_section_size")
        add_row("Body size", "font_body_size")
        tk.Frame(parent, height=10, bg=app._palette["panel"]).pack(fill="x")
        add_row("Mono family", "font_mono_family")
        add_row("Mono size", "font_mono_size")
        tk.Frame(parent, height=10, bg=app._palette["panel"]).pack(fill="x")
        add_row("Button height", "button_height")

        note = tk.Label(
            parent,
            text="These values are written into the GUI dict in config.py.\nRestart GUI to fully apply typography changes.",
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
            tk.Label(self._pipe_container, text=title, font=app._mono(weight="bold"), bg=app._palette["panel"], fg=app._palette["muted"]).pack(anchor="w")
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
            gui_dict, pipe_cfg = _ConfigEditor.load_gui_and_pipeline(self._config_path)
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
            }

            _, pipe_cfg = _ConfigEditor.load_gui_and_pipeline(self._config_path)
            for k, var in self._pipe_vars.items():
                group, idx_s = k.split(":", 1)
                idx = int(idx_s)
                pipe_cfg[group][idx]["enabled"] = bool(var.get())

            # Back-compat / hardening: detectors are no longer user-facing.
            # If an older config.py still has PIPELINE_CONFIG['detectors'], drop it when saving.
            pipe_cfg.pop("detectors", None)

            _ConfigEditor.write_gui_and_pipeline(self._config_path, gui_update, pipe_cfg)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self._app.set_status("Saved to config.py")
        messagebox.showinfo("Saved", "config.py updated. Restart GUI to apply all typography/layout changes.")


class _ConfigEditor:
    @staticmethod
    def load_gui_and_pipeline(config_path: Path) -> tuple[dict, dict]:
        src = config_path.read_text(encoding="utf-8")
        mod = ast.parse(src)
        gui_val = None
        pipe_val = None
        for node in mod.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name == "GUI":
                    gui_val = ast.literal_eval(node.value)
                if name == "PIPELINE_CONFIG":
                    pipe_val = ast.literal_eval(node.value)
        if not isinstance(gui_val, dict):
            raise ValueError("Could not find GUI dict in config.py")
        if not isinstance(pipe_val, dict):
            raise ValueError("Could not find PIPELINE_CONFIG dict in config.py")
        return gui_val, pipe_val

    @staticmethod
    def write_gui_and_pipeline(config_path: Path, gui_dict: dict, pipeline_cfg: dict) -> None:
        src = config_path.read_text(encoding="utf-8")
        lines = src.splitlines(keepends=True)
        mod = ast.parse(src)

        repls: list[tuple[int, int, str]] = []

        def mk_block(name: str, val: dict) -> str:
            body = pprint.pformat(val, width=100, sort_dicts=False)
            return f"{name} = {body}\n"

        for node in mod.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in {"GUI", "PIPELINE_CONFIG"}:
                    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
                        raise ValueError("Python did not provide AST line ranges for config.py")
                    start = int(node.lineno) - 1
                    end = int(node.end_lineno)
                    new_text = mk_block(name, gui_dict if name == "GUI" else pipeline_cfg)
                    repls.append((start, end, new_text))

        if not repls:
            raise ValueError("Could not locate GUI/PIPELINE_CONFIG assignments to rewrite")

        repls.sort(key=lambda t: t[0], reverse=True)
        for start, end, new_text in repls:
            lines[start:end] = [new_text]

        config_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    app = AVCleanerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
