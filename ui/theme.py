"""Визуальные темы приложения (светлая и тёмная, в духе Gemini)."""
import tkinter as tk
from tkinter import ttk

from config import load_settings, update_settings

FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"

LIGHT = {
    "BG": "#f6f8fc",
    "SURFACE": "#ffffff",
    "SURFACE_ALT": "#f1f3f4",
    "SURFACE_SOFT": "#f8f9fa",
    "BORDER": "#e3e6eb",
    "BORDER_STRONG": "#dadce0",
    "INK": "#1f1f1f",
    "INK_SOFT": "#3c4043",
    "MUTED": "#5f6368",
    "MUTED_LIGHT": "#80868b",
    "ACCENT": "#1a73e8",
    "ACCENT_HOVER": "#1765cc",
    "ACCENT_SOFT": "#e8f0fe",
    "ACCENT_SOFT_HOVER": "#d2e3fc",
    "ON_ACCENT": "#ffffff",
    "SELECT_FG": "#174ea6",
    "GREEN": "#137333",
    "RED": "#c5221f",
    "RED_SOFT": "#fce8e6",
    "RED_SOFT_HOVER": "#f7d7d4",
    "AMBER": "#b06000",
    "PURPLE": "#7b4fd6",
    "DISABLED_BG": "#eef1f5",
    "DISABLED_FG": "#9aa0a6",
    "TRACK": "#e8eaed",
    "GRADIENT": ("#4285f4", "#9b72cb", "#d96570"),
}

DARK = {
    "BG": "#131314",
    "SURFACE": "#1e1f20",
    "SURFACE_ALT": "#2a2b2d",
    "SURFACE_SOFT": "#1a1b1c",
    "BORDER": "#333537",
    "BORDER_STRONG": "#444746",
    "INK": "#e3e3e3",
    "INK_SOFT": "#c4c7c5",
    "MUTED": "#9aa0a6",
    "MUTED_LIGHT": "#8e918f",
    "ACCENT": "#8ab4f8",
    "ACCENT_HOVER": "#aecbfa",
    "ACCENT_SOFT": "#1e3050",
    "ACCENT_SOFT_HOVER": "#2b4370",
    "ON_ACCENT": "#0b1220",
    "SELECT_FG": "#d3e3fd",
    "GREEN": "#81c995",
    "RED": "#f28b82",
    "RED_SOFT": "#3b1f1e",
    "RED_SOFT_HOVER": "#4d2927",
    "AMBER": "#fdd663",
    "PURPLE": "#c58af9",
    "DISABLED_BG": "#282a2c",
    "DISABLED_FG": "#6b6f72",
    "TRACK": "#3c4043",
    "GRADIENT": ("#7aa7ff", "#c58af9", "#f28b82"),
}

MODE = "light"


def apply_mode(mode: str) -> None:
    """Применяет палитру: обновляет модульные константы цветов."""
    global MODE
    MODE = mode if mode in ("light", "dark") else "light"
    globals().update(DARK if MODE == "dark" else LIGHT)


def _read_settings() -> dict:
    return load_settings()


def load_mode() -> str:
    mode = str(_read_settings().get("theme", "light")).lower()
    return mode if mode in ("light", "dark") else "light"


def save_mode(mode: str) -> None:
    update_settings(theme=mode)


def set_mode(mode: str) -> None:
    apply_mode(mode)
    save_mode(MODE)


def toggle() -> str:
    set_mode("dark" if MODE == "light" else "light")
    return MODE


def is_dark() -> bool:
    return MODE == "dark"


def toggle_label() -> str:
    return "Светлая тема" if MODE == "dark" else "Тёмная тема"


def font(size: int, weight: str = "normal"):
    return (FONT_FAMILY, size, weight)


MONO = (MONO_FAMILY, 9)


def setup_ttk(root: tk.Misc) -> None:
    """Настраивает ttk-виджеты под текущую тему."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=INK, font=font(9))
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=SURFACE, foreground=INK, font=font(9))

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=INK_SOFT,
        rowheight=28,
        borderwidth=0,
        font=font(9),
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE_ALT,
        foreground=MUTED,
        relief="flat",
        borderwidth=0,
        font=font(8, "bold"),
    )
    style.map(
        "Treeview",
        background=[("selected", ACCENT_SOFT)],
        foreground=[("selected", SELECT_FG)],
    )
    style.map("Treeview.Heading", background=[("active", ACCENT_SOFT)])

    for name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(
            name,
            background=BORDER_STRONG,
            troughcolor=SURFACE_SOFT,
            bordercolor=SURFACE_SOFT,
            lightcolor=BORDER_STRONG,
            darkcolor=BORDER_STRONG,
            arrowcolor=MUTED,
            relief="flat",
            width=10,
        )
        style.map(name, background=[("active", MUTED_LIGHT)])

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=INK,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        arrowcolor=MUTED,
        padding=6,
        relief="flat",
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE)],
        foreground=[("readonly", INK)],
        selectbackground=[("readonly", SURFACE)],
        selectforeground=[("readonly", INK)],
        bordercolor=[("focus", ACCENT)],
    )

    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_SOFT)
    root.option_add("*TCombobox*Listbox.selectForeground", SELECT_FG)
    root.option_add("*TCombobox*Listbox.font", font(9))


apply_mode(load_mode())
