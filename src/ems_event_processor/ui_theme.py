"""Session-only desktop colors and ttk styles; no processing dependencies."""

from tkinter import ttk

PALETTES = {
    "light": {
        "background": "#f1f5f9",
        "surface": "#ffffff",
        "text": "#1e293b",
        "muted": "#64748b",
        "border": "#cbd5e1",
        "primary": "#0f4c5c",
        "primary_hover": "#0b3844",
        "primary_text": "#ffffff",
        "soft": "#e6f4f1",
        "disabled": "#e3e9ef",
        "disabled_text": "#718095",
        "field": "#f8fafc",
        "success": "#15803d",
        "warning": "#8a5105",
        "error": "#b91c1c",
    },
    "dark": {
        "background": "#111b28",
        "surface": "#1c2a3b",
        "text": "#eef4fb",
        "muted": "#b1c2d4",
        "border": "#3d5065",
        "primary": "#82d4df",
        "primary_hover": "#abe6ed",
        "primary_text": "#102c2a",
        "soft": "#253f43",
        "disabled": "#2d3d50",
        "disabled_text": "#a1b2c5",
        "field": "#142133",
        "success": "#8ce1b4",
        "warning": "#ffd18a",
        "error": "#ffacb6",
    },
}


def apply_styles(style: ttk.Style, mode: str, family: str) -> dict[str, str]:
    colors = PALETTES[mode]
    style.theme_use("clam")  # Native Windows themes ignore many dark-mode color settings.
    style.configure("TFrame", background=colors["background"])
    style.configure(
        "Card.TFrame",
        background=colors["surface"],
        borderwidth=1,
        relief="solid",
        bordercolor=colors["border"],
    )
    style.configure("Inner.TFrame", background=colors["surface"])
    style.configure("Soft.TFrame", background=colors["soft"])
    style.configure(
        "Field.TFrame",
        background=colors["field"],
        borderwidth=1,
        relief="solid",
        bordercolor=colors["border"],
    )
    style.configure(
        "Metric.TFrame",
        background=colors["field"],
        borderwidth=1,
        relief="solid",
        bordercolor=colors["border"],
    )
    for name, background, foreground, size, weight in [
        ("TLabel", "background", "text", 11, "normal"),
        ("File.TLabel", "field", "text", 11, "bold"),
        ("FileHint.TLabel", "field", "muted", 9, "normal"),
        ("FileIcon.TLabel", "soft", "primary", 12, "bold"),
        ("MetricCount.TLabel", "field", "text", 20, "bold"),
        ("MetricCaption.TLabel", "field", "muted", 9, "normal"),
        ("Title.TLabel", "background", "text", 20, "bold"),
        ("Subtitle.TLabel", "background", "muted", 11, "normal"),
        ("Footnote.TLabel", "background", "muted", 9, "normal"),
        ("CardTitle.TLabel", "surface", "text", 13, "bold"),
        ("Card.TLabel", "surface", "text", 11, "normal"),
        ("Muted.TLabel", "surface", "muted", 10, "normal"),
        ("Filename.TLabel", "surface", "text", 12, "bold"),
        ("Count.TLabel", "surface", "text", 23, "bold"),
        ("CountCaption.TLabel", "surface", "muted", 10, "normal"),
        ("Badge.TLabel", "soft", "primary", 10, "bold"),
        ("Status.TLabel", "surface", "text", 12, "bold"),
        ("Success.TLabel", "surface", "success", 12, "bold"),
        ("Warning.TLabel", "surface", "warning", 12, "bold"),
        ("Error.TLabel", "surface", "error", 12, "bold"),
    ]:
        style.configure(
            name,
            background=colors[background],
            foreground=colors[foreground],
            font=(family, size, weight),
        )
    for name, background, foreground in [
        ("Primary.TButton", "primary", "primary_text"),
        ("Secondary.TButton", "surface", "text"),
    ]:
        style.configure(
            name,
            background=colors[background],
            foreground=colors[foreground],
            font=(family, 11, "bold"),
            padding=(20, 12),
            bordercolor=colors["border"],
            focuscolor=colors[foreground],
            lightcolor=colors[background],
            darkcolor=colors[background],
            borderwidth=1,
        )
        hover = colors["primary_hover"] if name.startswith("Primary") else colors["field"]
        style.map(
            name,
            background=[("disabled", colors["disabled"]), ("active", hover)],
            foreground=[("disabled", colors["disabled_text"])],
            bordercolor=[("focus", colors["primary"])],
        )
    style.configure(
        "Theme.TRadiobutton",
        background=colors["background"],
        foreground=colors["muted"],
        font=(family, 10),
        padding=(8, 8),
        indicatorcolor=colors["field"],
        indicatorbackground=colors["field"],
    )
    style.map(
        "Theme.TRadiobutton",
        foreground=[("selected", colors["text"])],
        background=[("active", colors["background"])],
        indicatorcolor=[("selected", colors["primary"])],
    )
    style.configure(
        "Path.TEntry",
        fieldbackground=colors["field"],
        foreground=colors["muted"],
        bordercolor=colors["border"],
        padding=(10, 7),
        font=(family, 10),
    )
    style.map(
        "Path.TEntry",
        fieldbackground=[("readonly", colors["field"])],
        foreground=[("readonly", colors["muted"])],
        selectbackground=[("!disabled", colors["primary"])],
        selectforeground=[("!disabled", colors["primary_text"])],
    )
    style.configure(
        "EMS.Horizontal.TProgressbar",
        troughcolor=colors["field"],
        background=colors["primary"],
        bordercolor=colors["border"],
        lightcolor=colors["primary"],
        darkcolor=colors["primary"],
    )
    style.configure(
        "Vertical.TScrollbar",
        background=colors["border"],
        troughcolor=colors["background"],
        arrowcolor=colors["text"],
        bordercolor=colors["background"],
    )
    return colors
