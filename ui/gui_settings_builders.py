"""
gui_settings_builders.py

Form-building helpers for SettingsPage.
Each function takes the SettingsPage instance (`page`) as its first argument so
it can create and read instance variables (page._vars, page._qual_vars, etc.)
without coupling to a specific class hierarchy.
"""
from __future__ import annotations

import tkinter as tk

# Vertical gap between input rows inside the GUI-settings pane.
_ROW_GAP = 4


# ---------------------------------------------------------------------------
# GUI pane
# ---------------------------------------------------------------------------

def build_gui_form(page, parent: tk.Frame) -> None:
    """Build the GUI-settings form and store tk.StringVars on *page._vars*."""
    app = page._app
    page._vars = {
        "gui_width": tk.StringVar(),
        "gui_height": tk.StringVar(),
        "font_family": tk.StringVar(),
        "font_title_size": tk.StringVar(),
        "font_section_size": tk.StringVar(),
        "font_body_size": tk.StringVar(),
        "font_mono_family": tk.StringVar(),
        "font_mono_size": tk.StringVar(),
        "button_height": tk.StringVar(),
        "default_video_player": tk.StringVar(),
        # Accent colors
        "ui_button_caption_color": tk.StringVar(),
        "ui_accent_font_color": tk.StringVar(),
        "ui_accent_line_color": tk.StringVar(),
        # Pane split percentages (must sum to 100)
        "pane_console_width_pct": tk.StringVar(),
        "pane_filler_words_found_pct": tk.StringVar(),
    }

    def _entry(row: tk.Frame, key: str) -> tk.Entry:
        return tk.Entry(
            row,
            textvariable=page._vars[key],
            font=app._mono(),
            bg=app._palette["panel2"],
            fg=app._palette["text"],
            insertbackground=app._ui_colors["accent_line"],
            relief="flat",
            highlightthickness=2,
            highlightbackground=app._palette["edge2"],
            highlightcolor=app._ui_colors["accent_line"],
        )

    def add_row(label: str, key: str) -> None:
        row = tk.Frame(parent, bg=app._palette["panel"])
        row.pack(fill="x", pady=_ROW_GAP)
        tk.Label(
            row, text=label,
            font=app._mono(weight="bold"),
            bg=app._palette["panel"],
            fg=app._palette["muted"],
        ).pack(side="left")
        _entry(row, key).pack(side="right", fill="x", expand=True)

    add_row("Window width", "gui_width")
    add_row("Window height", "gui_height")
    add_row("Font family", "font_family")
    add_row("Title size", "font_title_size")
    add_row("Section size", "font_section_size")
    add_row("Body size", "font_body_size")
    add_row("Mono family", "font_mono_family")
    add_row("Mono size", "font_mono_size")
    add_row("Button height", "button_height")

    # Video-player row has an extra SCAN button
    player_row = tk.Frame(parent, bg=app._palette["panel"])
    player_row.pack(fill="x", pady=_ROW_GAP)
    tk.Label(
        player_row, text="Default Video Player",
        font=app._mono(weight="bold"),
        bg=app._palette["panel"],
        fg=app._palette["muted"],
    ).pack(side="left")
    app._make_btn(player_row, "SCAN", page._scan_default_video_player, kind="secondary").pack(side="right")
    _entry(player_row, "default_video_player").pack(side="right", fill="x", expand=True, padx=(12, 8))

    add_row("Button caption color", "ui_button_caption_color")
    add_row("Accent font color", "ui_accent_font_color")
    add_row("Accent line color", "ui_accent_line_color")
    add_row("Console pane width %", "pane_console_width_pct")
    add_row("Filler words pane width %", "pane_filler_words_found_pct")

    tk.Label(
        parent,
        text=(
            "These values are written into the GUI dict in config.py.\n"
            "SCAN detects media players for the current operating system.\n"
            "Choose one, then use SAVE TO config.py to persist it.\n"
            "Restart GUI to fully apply typography/layout/color changes.\n"
            "Colors accept #RRGGBB.  Pane widths must sum to 100."
        ),
        font=app._mono(),
        bg=app._palette["panel"],
        fg=app._palette["muted"],
        justify="left",
    ).pack(anchor="w", pady=(14, 0))


# ---------------------------------------------------------------------------
# Pipeline pane – scrollable container setup
# ---------------------------------------------------------------------------

def build_pipeline_form(page, parent: tk.Frame) -> None:
    """
    Create all pipeline tk.Vars and set up the scrollable canvas.
    Variables are stored on *page* so _reload / _save can access them.
    """
    app = page._app
    page._pipe_vars = {}

    page._word_vars = {
        "words_to_remove": tk.StringVar(),
        "confidence_required_host": tk.StringVar(value="1.00"),
        "confidence_required_guest": tk.StringVar(value="0.90"),
        "confidence_bonus_per_word": tk.StringVar(value="0.05"),
        "filler_mute_inset_ms": tk.StringVar(value="30"),
        "filler_mute_gap_threshold_ms": tk.StringVar(value="60"),
    }

    # All QUALITY_PRESETS string/numeric values
    page._qual_vars = {
        "silence_threshold_db": tk.StringVar(value="-30"),
        "max_pause_duration": tk.StringVar(value="1.0"),
        "new_pause_duration": tk.StringVar(value="0.8"),
        "silence_window_ms": tk.StringVar(value="200"),
        "spike_threshold_db": tk.StringVar(value="-5"),
        "normalization_standard_target": tk.StringVar(value="-16.0"),
        "normalization_max_gain_db": tk.StringVar(value="15.0"),
        # Codec / encoding
        "audio_codec": tk.StringVar(value="aac"),
        "audio_bitrate": tk.StringVar(value="320k"),
        "video_codec": tk.StringVar(value="libx264"),
        "video_preset": tk.StringVar(value="fast"),
        # NVENC
        "nvenc_codec": tk.StringVar(value="h264_nvenc"),
        "nvenc_preset": tk.StringVar(value="p4"),
        "nvenc_rc": tk.StringVar(value="vbr"),
        # Render / performance
        "chunk_size": tk.StringVar(value="50"),
        "cut_fade_ms": tk.StringVar(value="16"),
        "keyframe_snap_tolerance_s": tk.StringVar(value="0.1"),
        "cpu_limit_pct": tk.StringVar(value="80"),
        "cpu_rate_correction": tk.StringVar(value="0.90"),
        "gpu_limit_pct": tk.StringVar(value="100"),
    }

    page._norm_mode = tk.StringVar(value="MATCH_HOST")
    # Encoder radio (cpu / gpu) and CRF/CQ quality number
    page._enc_mode = tk.StringVar(value="cpu")
    page._enc_quality = tk.StringVar(value="18")

    # Boolean toggles that are NOT processor-enable toggles
    page._bool_vars = {
        "cuda_decode_enabled": tk.BooleanVar(value=False),
        "cuda_require_support": tk.BooleanVar(value=True),
        "chunk_parallel_enabled": tk.BooleanVar(value=True),
        "two_phase_render_enabled": tk.BooleanVar(value=True),
    }

    # Scrollable canvas
    outer = tk.Frame(parent, bg=app._palette["panel"])
    outer.pack(fill="both", expand=True)

    page._pipe_canvas = tk.Canvas(
        outer, bg=app._palette["panel"], highlightthickness=0, bd=0, relief="flat"
    )
    page._pipe_scroll = tk.Scrollbar(outer, orient="vertical", command=page._pipe_canvas.yview)
    page._pipe_canvas.configure(yscrollcommand=page._pipe_scroll.set)

    page._pipe_scroll.pack(side="right", fill="y")
    page._pipe_canvas.pack(side="left", fill="both", expand=True)

    page._pipe_container = tk.Frame(page._pipe_canvas, bg=app._palette["panel"])
    page._pipe_window = page._pipe_canvas.create_window(
        (0, 0), window=page._pipe_container, anchor="nw"
    )

    def _on_container_configure(_evt=None):
        page._pipe_canvas.configure(scrollregion=page._pipe_canvas.bbox("all"))

    def _on_canvas_configure(_evt=None):
        page._pipe_canvas.itemconfigure(page._pipe_window, width=page._pipe_canvas.winfo_width())

    page._pipe_container.bind("<Configure>", _on_container_configure)
    page._pipe_canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(evt):
        delta = int(-1 * (evt.delta / 120)) if getattr(evt, "delta", 0) else 0
        if delta:
            page._pipe_canvas.yview_scroll(delta, "units")

    page._pipe_canvas.bind("<Enter>", lambda _e: page._pipe_canvas.bind_all("<MouseWheel>", _on_mousewheel))
    page._pipe_canvas.bind("<Leave>", lambda _e: page._pipe_canvas.unbind_all("<MouseWheel>"))


# ---------------------------------------------------------------------------
# Pipeline pane – actual form rendering (called on every reload)
# ---------------------------------------------------------------------------

def render_pipeline_toggles(page, pipe_cfg: dict, qual_presets: dict, words_cfg: dict) -> None:
    """Clear and repopulate the scrollable pipeline pane with current config values."""
    app = page._app

    for child in page._pipe_container.winfo_children():
        child.destroy()
    page._pipe_vars.clear()

    # ---- load preset values ----
    preset = qual_presets.get("PODCAST_HIGH_QUALITY", {})

    page._qual_vars["silence_threshold_db"].set(str(preset.get("silence_threshold_db", -30)))
    page._qual_vars["max_pause_duration"].set(str(preset.get("max_pause_duration", 1.0)))
    page._qual_vars["new_pause_duration"].set(str(preset.get("new_pause_duration", 0.8)))
    page._qual_vars["silence_window_ms"].set(str(preset.get("silence_window_ms", 200)))
    page._qual_vars["spike_threshold_db"].set(str(preset.get("spike_threshold_db", -5)))

    norm = preset.get("normalization") if isinstance(preset.get("normalization"), dict) else {}
    page._norm_mode.set(str(norm.get("mode", "MATCH_HOST")))
    page._qual_vars["normalization_standard_target"].set(str(norm.get("standard_target", -16.0)))
    page._qual_vars["normalization_max_gain_db"].set(str(norm.get("max_gain_db", 15.0)))

    page._qual_vars["audio_codec"].set(str(preset.get("audio_codec", "aac")))
    page._qual_vars["audio_bitrate"].set(str(preset.get("audio_bitrate", "320k")))
    page._qual_vars["video_codec"].set(str(preset.get("video_codec", "libx264")))
    page._qual_vars["video_preset"].set(str(preset.get("video_preset", "fast")))

    nvenc = preset.get("nvenc") if isinstance(preset.get("nvenc"), dict) else {}
    page._qual_vars["nvenc_codec"].set(str(nvenc.get("codec", "h264_nvenc")))
    page._qual_vars["nvenc_preset"].set(str(nvenc.get("preset", "p4")))
    page._qual_vars["nvenc_rc"].set(str(nvenc.get("rc", "vbr")))

    page._qual_vars["chunk_size"].set(str(preset.get("chunk_size", 50)))
    page._qual_vars["cut_fade_ms"].set(str(preset.get("cut_fade_ms", 16)))
    page._qual_vars["keyframe_snap_tolerance_s"].set(str(preset.get("keyframe_snap_tolerance_s", 0.1)))
    page._qual_vars["cpu_limit_pct"].set(str(preset.get("cpu_limit_pct", 80)))
    page._qual_vars["cpu_rate_correction"].set(str(preset.get("cpu_rate_correction", 0.90)))
    # Map stored int (100/60/20) back to the dropdown display string
    _gpu_pct_to_label = {100: "100% -> 5 workers", 60: "60% -> 3 workers", 20: "20% -> 1 worker"}
    _gpu_stored = int(preset.get("gpu_limit_pct", 100))
    page._qual_vars["gpu_limit_pct"].set(_gpu_pct_to_label.get(_gpu_stored, "100% -> 5 workers"))

    cuda_enc = bool(preset.get("cuda_encode_enabled", False))
    page._enc_mode.set("gpu" if cuda_enc else "cpu")
    page._bool_vars["cuda_decode_enabled"].set(bool(preset.get("cuda_decode_enabled", False)))
    page._bool_vars["cuda_require_support"].set(bool(preset.get("cuda_require_support", True)))
    page._bool_vars["chunk_parallel_enabled"].set(bool(preset.get("chunk_parallel_enabled", True)))
    page._bool_vars["two_phase_render_enabled"].set(bool(preset.get("two_phase_render_enabled", True)))

    page._enc_quality.set(str(preset.get("crf", 18)))

    words_list = words_cfg.get("words_to_remove", [])
    if not isinstance(words_list, list):
        words_list = []
    page._word_vars["words_to_remove"].set(
        ", ".join(str(w).strip() for w in words_list if str(w).strip())
    )
    page._word_vars["confidence_required_host"].set(str(words_cfg.get("confidence_required_host", 1.0)))
    page._word_vars["confidence_required_guest"].set(str(words_cfg.get("confidence_required_guest", 0.9)))
    page._word_vars["confidence_bonus_per_word"].set(str(words_cfg.get("confidence_bonus_per_word", 0.05)))
    page._word_vars["filler_mute_inset_ms"].set(str(words_cfg.get("filler_mute_inset_ms", 30)))
    page._word_vars["filler_mute_gap_threshold_ms"].set(str(words_cfg.get("filler_mute_gap_threshold_ms", 60)))

    # ---- local builder helpers ----
    def mk_section(title: str) -> tk.Frame:
        tk.Label(
            page._pipe_container, text=title,
            font=app._mono(weight="bold"),
            bg=app._palette["panel"],
            fg=app._palette["muted"],
        ).pack(anchor="w")
        sec = tk.Frame(page._pipe_container, bg=app._palette["panel"])
        sec.pack(fill="x", pady=(8, 14))
        return sec

    def mk_toggle(sec: tk.Frame, key: str, label: str, initial: bool) -> None:
        """Processor-enable checkbox stored in page._pipe_vars."""
        var = tk.BooleanVar(value=initial)
        page._pipe_vars[key] = var
        row = tk.Frame(sec, bg=app._palette["panel"])
        row.pack(fill="x", pady=4)
        tk.Checkbutton(
            row, text=label, variable=var, font=app._mono(),
            bg=app._palette["panel"], fg=app._palette["text"],
            activebackground=app._palette["panel"], activeforeground=app._palette["text"],
            selectcolor=app._palette["panel2"], highlightthickness=0, bd=0,
        ).pack(side="left")

    def mk_bool_row(sec: tk.Frame, key: str, label: str) -> None:
        """Checkbox tied to page._bool_vars[key]."""
        row = tk.Frame(sec, bg=app._palette["panel"])
        row.pack(fill="x", pady=4)
        tk.Checkbutton(
            row, text=label, variable=page._bool_vars[key], font=app._mono(),
            bg=app._palette["panel"], fg=app._palette["text"],
            activebackground=app._palette["panel"], activeforeground=app._palette["text"],
            selectcolor=app._palette["panel2"], highlightthickness=0, bd=0,
        ).pack(side="left")

    def mk_kv_row(sec: tk.Frame, label: str, var: tk.StringVar, width: int = 10) -> None:
        row = tk.Frame(sec, bg=app._palette["panel"])
        row.pack(fill="x", pady=4)
        tk.Label(
            row, text=label,
            font=app._mono(weight="bold"),
            bg=app._palette["panel"],
            fg=app._palette["text"],
        ).pack(side="left")
        tk.Entry(
            row, textvariable=var, font=app._mono(),
            bg=app._palette["panel2"], fg=app._palette["text"],
            insertbackground=app._ui_colors["accent_line"],
            relief="flat", highlightthickness=2,
            highlightbackground=app._palette["edge2"],
            highlightcolor=app._ui_colors["accent_line"],
            width=width,
        ).pack(side="right", padx=(0, 5))

    def mk_dropdown_row(sec: tk.Frame, label: str, var: tk.StringVar, choices: list) -> None:
        """Label + OptionMenu dropdown stored in an existing StringVar."""
        row = tk.Frame(sec, bg=app._palette["panel"])
        row.pack(fill="x", pady=4)
        tk.Label(
            row, text=label,
            font=app._mono(weight="bold"),
            bg=app._palette["panel"],
            fg=app._palette["text"],
        ).pack(side="left")
        menu = tk.OptionMenu(row, var, *choices)
        menu.config(
            font=app._mono(),
            bg=app._palette["panel2"],
            fg=app._palette["text"],
            activebackground=app._palette["panel2"],
            activeforeground=app._palette["text"],
            highlightthickness=0,
            relief="flat",
            bd=0,
        )
        menu["menu"].config(
            font=app._mono(),
            bg=app._palette["panel2"],
            fg=app._palette["text"],
            activebackground=app._ui_colors["accent_line"],
            activeforeground=app._palette["text"],
        )
        menu.pack(side="right", padx=(0, 5))

    # ---- Quality Presets section ----
    qual_sec = mk_section("QUALITY PRESETS")
    mk_kv_row(qual_sec, "Silence threshold (dB)", page._qual_vars["silence_threshold_db"])
    mk_kv_row(qual_sec, "Max pause duration (sec)", page._qual_vars["max_pause_duration"])
    mk_kv_row(qual_sec, "New pause duration (sec)", page._qual_vars["new_pause_duration"])
    mk_kv_row(qual_sec, "Silence window (ms)", page._qual_vars["silence_window_ms"])
    mk_kv_row(qual_sec, "Spike threshold (dB)", page._qual_vars["spike_threshold_db"])

    tk.Label(
        qual_sec, text="Normalization mode",
        font=app._mono(weight="bold"),
        bg=app._palette["panel"],
        fg=app._palette["text"],
    ).pack(anchor="w", pady=(6, 0))

    row_norm = tk.Frame(qual_sec, bg=app._palette["panel"])
    row_norm.pack(fill="x", pady=(2, 8))
    for val, lbl in [("MATCH_HOST", "Match host"), ("STANDARD_LUFS", "Standard LUFS")]:
        tk.Radiobutton(
            row_norm, text=lbl, variable=page._norm_mode, value=val,
            font=app._mono(), bg=app._palette["panel"], fg=app._palette["text"],
            selectcolor=app._palette["panel2"],
            activebackground=app._palette["panel"], activeforeground=app._palette["text"],
            highlightthickness=0, bd=0,
        ).pack(side="left", padx=(0, 10))

    mk_kv_row(qual_sec, "Standard target (LUFS)", page._qual_vars["normalization_standard_target"])
    mk_kv_row(qual_sec, "Max gain (dB)", page._qual_vars["normalization_max_gain_db"])

    # ---- Processors section ----
    proc_sec = mk_section("PROCESSORS")
    for i, p in enumerate(pipe_cfg.get("processors", [])):
        mk_toggle(proc_sec, f"processors:{i}", str(p.get("type")), bool(p.get("enabled")))

    # ---- Filler Word Detection section ----
    words_sec = mk_section("FILLER WORD DETECTION")
    mk_kv_row(words_sec, "Words to remove (comma-separated)", page._word_vars["words_to_remove"], width=28)
    mk_kv_row(words_sec, "Host confidence required", page._word_vars["confidence_required_host"])
    mk_kv_row(words_sec, "Guest confidence required", page._word_vars["confidence_required_guest"])
    mk_kv_row(words_sec, "Confidence bonus per word", page._word_vars["confidence_bonus_per_word"])
    mk_kv_row(words_sec, "Mute inset (ms)", page._word_vars["filler_mute_inset_ms"])
    mk_kv_row(words_sec, "Mute gap threshold (ms)", page._word_vars["filler_mute_gap_threshold_ms"])

    # ---- Video Encoding section ----
    enc_sec = mk_section("VIDEO ENCODING")

    tk.Label(
        enc_sec, text="Encoder",
        font=app._mono(weight="bold"),
        bg=app._palette["panel"],
        fg=app._palette["text"],
    ).pack(anchor="w")
    row_enc = tk.Frame(enc_sec, bg=app._palette["panel"])
    row_enc.pack(fill="x", pady=(2, 8))
    for val, lbl in [("cpu", "CPU (libx264)"), ("gpu", "NVIDIA GPU (NVENC)")]:
        tk.Radiobutton(
            row_enc, text=lbl, variable=page._enc_mode, value=val,
            font=app._mono(), bg=app._palette["panel"], fg=app._palette["text"],
            selectcolor=app._palette["panel2"],
            activebackground=app._palette["panel"], activeforeground=app._palette["text"],
            highlightthickness=0, bd=0,
        ).pack(side="left", padx=(0, 10))

    mk_bool_row(enc_sec, "cuda_decode_enabled", "CUDA decode enabled")
    mk_bool_row(enc_sec, "cuda_require_support", "Require CUDA support")

    tk.Label(
        enc_sec, text="Quality (0-51, Lower is Better)",
        font=app._mono(weight="bold"),
        bg=app._palette["panel"],
        fg=app._palette["text"],
    ).pack(anchor="w")
    row_qual = tk.Frame(enc_sec, bg=app._palette["panel"])
    row_qual.pack(fill="x", pady=(2, 4))
    tk.Entry(
        row_qual, textvariable=page._enc_quality, font=app._mono(),
        bg=app._palette["panel2"], fg=app._palette["text"],
        insertbackground=app._ui_colors["accent_line"],
        relief="flat", highlightthickness=2,
        highlightbackground=app._palette["edge2"],
        highlightcolor=app._ui_colors["accent_line"],
        width=6,
    ).pack(side="left")
    tk.Label(
        row_qual, text="Rec: 16-18 (High), 0 (Lossless)",
        font=app._mono(), bg=app._palette["panel"], fg=app._palette["muted"],
    ).pack(side="left", padx=10)

    # Standard libx264 CPU presets ordered from fastest to highest quality
    _CPU_PRESETS = [
        "ultrafast", "superfast", "veryfast", "faster",
        "fast", "medium", "slow", "slower", "veryslow", "placebo",
    ]

    mk_kv_row(enc_sec, "CPU codec", page._qual_vars["video_codec"])
    mk_dropdown_row(enc_sec, "CPU preset", page._qual_vars["video_preset"], _CPU_PRESETS)
    # NVENC performance presets: p1 (fastest) → p7 (slowest / best quality)
    _NVENC_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]

    mk_kv_row(enc_sec, "NVENC codec", page._qual_vars["nvenc_codec"])
    mk_dropdown_row(enc_sec, "NVENC preset - p1 (fastest) ... p7 (slowest / best quality)", page._qual_vars["nvenc_preset"], _NVENC_PRESETS)
    mk_kv_row(enc_sec, "NVENC rate control", page._qual_vars["nvenc_rc"])
    mk_kv_row(enc_sec, "Audio codec", page._qual_vars["audio_codec"])
    mk_kv_row(enc_sec, "Audio bitrate", page._qual_vars["audio_bitrate"])

    # ---- Render / Performance section ----
    render_sec = mk_section("RENDER / PERFORMANCE")
    mk_bool_row(render_sec, "chunk_parallel_enabled", "Chunk parallel enabled")
    mk_kv_row(render_sec, "Chunk size (frames)", page._qual_vars["chunk_size"])
    mk_kv_row(render_sec, "Cut fade (ms)", page._qual_vars["cut_fade_ms"])
    mk_bool_row(render_sec, "two_phase_render_enabled", "Two-phase render enabled")
    mk_kv_row(render_sec, "Keyframe snap tolerance (sec)", page._qual_vars["keyframe_snap_tolerance_s"])
    mk_kv_row(render_sec, "CPU limit % (1–100)", page._qual_vars["cpu_limit_pct"])
    mk_kv_row(render_sec, "CPU rate correction (0.10–1.00)", page._qual_vars["cpu_rate_correction"])
    # GPU worker cap: maps percentage to NVENC concurrent session count
    _GPU_LIMIT_OPTS = ["100% -> 5 workers", "60% -> 3 workers", "20% -> 1 worker"]
    mk_dropdown_row(render_sec, "GPU limit % (NVENC workers)", page._qual_vars["gpu_limit_pct"], _GPU_LIMIT_OPTS)

    tk.Label(
        page._pipe_container,
        text=(
            "Settings save to QUALITY_PRESETS, PIPELINE_CONFIG, and WORDS_TO_REMOVE in config.py.\n"
            "Words to remove should be comma-separated. Restart GUI to apply full pipeline changes."
        ),
        font=app._mono(),
        bg=app._palette["panel"],
        fg=app._palette["muted"],
        justify="left",
    ).pack(anchor="w", pady=(14, 0))