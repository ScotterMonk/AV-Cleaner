from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from queue import Empty, Queue

import tkinter as tk
from tkinter import filedialog, messagebox

from config import GUI
from ui.gui_helpers import FileRowState, format_bytes, get_video_duration_seconds
from ui.gui_pages import MainPage
from ui.gui_settings_page import SettingsPage
from ui.gui_ffmpeg_formatter import format_ffmpeg_progress_line, should_show_progress_line, reset_progress_counter
from ui.gui_outputs import save_fixed_outputs as gui_save_fixed_outputs
from utils.path_helpers import make_processed_output_path


def _should_mirror_to_progress(line: str) -> bool:
    """True for non-FFmpeg lines that should also appear in the PROGRESS pane."""

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


class AVCleanerGUI(tk.Tk):
    # Created by gpt-5.2 | 2026-01-08_01
    def __init__(self, *, project_dir: Path | None = None) -> None:
        super().__init__()

        self._project_dir = project_dir or Path(__file__).resolve().parents[1]

        self.title("AV Cleaner")

        # Accent colors are intentionally split so users can theme captions vs accent-fonts vs lines.
        neon_green = "#39FF14"
        self._ui_colors = {
            "button_caption": str(GUI.get("ui_button_caption_color", neon_green)),
            "accent_font": str(GUI.get("ui_accent_font_color", neon_green)),
            "accent_line": str(GUI.get("ui_accent_line_color", neon_green)),
        }

        self._palette = {
            "bg": "#0B0D10",
            "panel": "#12161B",
            "panel2": "#0F1318",
            "text": "#E9EEF5",
            "muted": "#A3ABB8",
            "edge": "#E9EEF5",
            "edge2": "#2C3440",
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

        self._rows: dict[str, FileRowState] = {}
        self._status_var = tk.StringVar(value="Ready")

        self._log_queue: Queue[str] = Queue()
        self._progress_queue: Queue[str] = Queue()
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
        outer = tk.Frame(
            parent,
            bg=self._palette["panel"],
            highlightthickness=1,
            highlightbackground=self._ui_colors["accent_line"],
            highlightcolor=self._ui_colors["accent_line"],
            relief="flat",
            bd=0,
        )

        # Bold header with accent stripe
        hdr = tk.Frame(outer, bg=self._palette["panel2"], highlightthickness=0, bd=0)
        hdr.pack(fill="x")

        # Accent stripe on left edge
        stripe = tk.Frame(hdr, bg=self._ui_colors["accent_line"], width=6)
        stripe.pack(side="left", fill="y")

        lbl = tk.Label(hdr, text=title.upper(), font=self._f(self._fonts["section"], "bold"))
        lbl.configure(bg=self._palette["panel2"], fg=self._ui_colors["accent_font"])
        lbl.pack(side="left", padx=16, pady=3)

        body = tk.Frame(outer, bg=self._palette["panel"])
        body.pack(fill="both", expand=True, padx=16, pady=12)
        outer.body = body  # type: ignore[attr-defined]
        return outer

    def _make_btn(self, parent: tk.Widget, text: str, command, *, kind: str = "primary") -> tk.Button:
        # Modified by Claude-4.5-Sonnet | 2026-01-08_04
        # Flat buttons with caption color controlled via config.

        # Metallic gradient simulation: dark gunmetal with highlights
        bg_metal_dark = "#2A2D32"
        bg_metal_light = "#3A3F47"
        bg_metal = bg_metal_light if kind == "primary" else bg_metal_dark

        fg_caption = self._ui_colors["button_caption"]

        # Edge color: matches background when inactive (invisible outline)
        edge_invisible = bg_metal
        edge_glow = self._ui_colors["accent_line"]

        # Calculate height in text lines (approximation for visual consistency)
        # Tkinter button height is in text lines, not pixels
        btn_height_lines = max(1, self._button_height // 10)

        btn = tk.Button(
            parent,
            text=text,
            command=command,
            font=self._f(self._fonts["body"], "bold"),
            bg=bg_metal,
            fg=fg_caption,
            activebackground=bg_metal,
            activeforeground=fg_caption,
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
                relief="flat",
            )

        def _leave(_evt=None) -> None:
            btn.configure(
                highlightbackground=edge_invisible,
                highlightcolor=edge_invisible,
                bg=bg_metal,
                relief="flat",
            )

        btn.bind("<Enter>", _enter)
        btn.bind("<Leave>", _leave)
        return btn

    def _build_shell(self) -> None:
        # Top bar
        top = tk.Frame(self, bg=self._palette["bg"])
        top.pack(fill="x", padx=18, pady=(18, 8))

        title = tk.Label(
            top,
            text="AV CLEANER",
            font=self._f(self._fonts["title"], "bold"),
            bg=self._palette["bg"],
            fg=self._palette["text"],
        )
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
        tk.Label(
            status,
            text="STATUS",
            font=self._mono(self._fonts["mono"], "bold"),
            bg=self._palette["panel2"],
            fg=self._palette["muted"],
        ).pack(side="left", padx=12, pady=10)
        tk.Label(
            status,
            textvariable=self._status_var,
            font=self._mono(self._fonts["mono"]),
            bg=self._palette["panel2"],
            fg=self._palette["text"],
        ).pack(side="left", padx=10, pady=10)

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

    def clear_progress(self) -> None:
        self._progress_queue.put("__CLEAR__")

    def append_progress(self, text: str) -> None:
        self._progress_queue.put(text)

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

        try:
            while True:
                line = self._progress_queue.get_nowait()
                if line == "__CLEAR__":
                    main: MainPage = self._pages["main"]  # type: ignore[assignment]
                    main.clear_progress_view()
                else:
                    main = self._pages["main"]  # type: ignore[assignment]
                    main.append_progress_view(line)
        except Empty:
            pass
        self.after(60, self._poll_log_queue)

    # Modified by gpt-5.2 | 2026-01-13_01
    def run_processing(self, host_path: str, guest_path: str, *, action: str = "ALL") -> None:
        if self._proc and self._proc.poll() is None:
            messagebox.showwarning("Already running", "A job is already running.")
            return

        self.clear_logs()
        self.clear_progress()
        self.set_status("Running…")

        # Reset FFmpeg progress line counter for new process
        reset_progress_counter()

        # Progress header is now always visible (no need to show it here)

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
                    cwd=str(self._project_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert self._proc.stdout is not None
                for line in self._proc.stdout:
                    # Format FFmpeg progress lines to align with header columns
                    formatted_line, is_progress = format_ffmpeg_progress_line(line)
                    
                    if is_progress:
                        # Only show every other progress line to reduce console spam
                        if should_show_progress_line(show_every_nth=2):
                            self.append_progress(formatted_line)
                    else:
                        # Pass through non-progress lines as-is
                        self.append_log(line)
                        if _should_mirror_to_progress(line):
                            self.append_progress(line)
                        
                code = self._proc.wait()
                if code == 0:
                    host_processed = make_processed_output_path(host_path)
                    guest_processed = make_processed_output_path(guest_path)

                    if os.path.exists(host_processed):
                        self.after(0, self._set_row_for_path, "host", host_processed)
                    if os.path.exists(guest_processed):
                        self.after(0, self._set_row_for_path, "guest", guest_processed)

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

        tk.Label(
            parent,
            textvariable=file_var,
            anchor="w",
            font=self._mono(),
            bg=self._palette["panel"],
            fg=self._palette["text"],
        ).grid(row=row_index, column=1, padx=8, pady=6, sticky="ew")
        tk.Label(
            parent,
            textvariable=size_var,
            anchor="w",
            font=self._mono(),
            bg=self._palette["panel"],
            fg=self._palette["muted"],
        ).grid(row=row_index, column=2, padx=8, pady=6, sticky="w")
        tk.Label(
            parent,
            textvariable=length_var,
            anchor="w",
            font=self._mono(),
            bg=self._palette["panel"],
            fg=self._palette["muted"],
        ).grid(row=row_index, column=3, padx=8, pady=6, sticky="w")

        self._rows[role] = FileRowState(path=None, file_var=file_var, size_var=size_var, length_var=length_var)

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

    def save_fixed_outputs(self, host: str, guest: str) -> None:
        try:
            saved = gui_save_fixed_outputs(host, guest, project_dir=self._project_dir)
            if not saved:
                return
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self.append_log("[GUI] Saved fixed copies:\n" + "\n".join(f"  {p}" for p in saved) + "\n")
        self.set_status("Saved _fixed files")


def main() -> None:
    app = AVCleanerGUI()
    app.mainloop()

