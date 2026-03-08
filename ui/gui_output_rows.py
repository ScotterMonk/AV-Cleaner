from __future__ import annotations

import tkinter as tk

from ui.gui_helpers import FileRowState
from ui.gui_tooltip import GuiTooltip


# Created by gpt-5.4 | 2026-03-07
def output_row_create(app, parent: tk.Widget, row_index: int, role: str, *, label_text: str) -> FileRowState:
    """Build one MODDED FILES output row and return its state container."""

    tk.Label(
        parent,
        text=label_text,
        anchor="w",
        font=app._mono(weight="bold"),
        bg=app._palette["panel"],
        fg=app._palette["muted"],
    ).grid(row=row_index, column=0, padx=8, pady=6, sticky="w")

    file_var = tk.StringVar(value="")
    size_var = tk.StringVar(value="")
    length_var = tk.StringVar(value="")

    file_cell = tk.Frame(parent, bg=app._palette["panel"])
    file_cell.grid(row=row_index, column=1, padx=8, pady=6, sticky="ew")
    file_cell.columnconfigure(1, weight=1)

    play_btn = tk.Button(
        file_cell,
        text="▶",
        command=lambda r=role: app._play_modded_row(r),
        font=app._f(app._fonts["body"], "bold"),
        bg=app._palette["panel"],
        fg=app._ui_colors["accent_line"],
        activebackground=app._palette["panel2"],
        activeforeground=app._ui_colors["accent_font"],
        relief="flat",
        bd=0,
        padx=2,
        pady=0,
        highlightthickness=0,
    )
    play_btn.grid(row=0, column=0, padx=(0, 8), sticky="w")
    play_btn.grid_remove()
    try:
        play_btn.configure(cursor="hand2")
    except tk.TclError:
        pass

    play_btn.bind("<Enter>", lambda _evt: play_btn.configure(bg=app._palette["panel2"]))
    play_btn.bind("<Leave>", lambda _evt: play_btn.configure(bg=app._palette["panel"]))
    play_btn._gui_tooltip = GuiTooltip(  # type: ignore[attr-defined]
        play_btn,
        "Play",
        bg=app._palette["panel2"],
        fg=app._ui_colors["accent_font"],
        border=app._ui_colors["accent_line"],
    )

    tk.Label(
        file_cell,
        textvariable=file_var,
        anchor="w",
        font=app._mono(),
        bg=app._palette["panel"],
        fg=app._palette["text"],
    ).grid(row=0, column=1, sticky="ew")
    tk.Label(
        parent,
        textvariable=size_var,
        anchor="w",
        font=app._mono(),
        bg=app._palette["panel"],
        fg=app._palette["muted"],
    ).grid(row=row_index, column=2, padx=8, pady=6, sticky="w")
    tk.Label(
        parent,
        textvariable=length_var,
        anchor="w",
        font=app._mono(),
        bg=app._palette["panel"],
        fg=app._palette["muted"],
    ).grid(row=row_index, column=3, padx=8, pady=6, sticky="w")

    return FileRowState(
        path=None,
        file_var=file_var,
        size_var=size_var,
        length_var=length_var,
        play_btn=play_btn,
    )
