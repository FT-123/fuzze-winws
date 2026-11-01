import tkinter as tk
from typing import Tuple

from ui import theme


def _hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    value = hex_str.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _shade(hex_color: str, factor: float) -> str:
    """Затемняет/осветляет цвет: factor < 1 — темнее, > 1 — светлее."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(
        (
            max(0, min(255, int(r * factor))),
            max(0, min(255, int(g * factor))),
            max(0, min(255, int(b * factor))),
        )
    )


def _rounded_points(x1, y1, x2, y2, r):
    return [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]


def draw_rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
    return canvas.create_polygon(_rounded_points(x1, y1, x2, y2, r), smooth=True, **kwargs)


class RoundedButton(tk.Canvas):
    """Плоская кнопка со скруглёнными углами в стиле Gemini."""

    def __init__(
        self,
        parent,
        text="",
        command=None,
        radius=16,
        bg_color=None,
        fg_color=None,
        hover_bg=None,
        active_bg=None,
        border_color=None,
        width=120,
        height=32,
        font=theme.font(9),
        disabled_bg=None,
        disabled_fg=None,
    ):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent["bg"],
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            takefocus=0,
        )
        self.command = command
        self.radius = radius
        self.bg_color = bg_color or theme.SURFACE
        self.fg_color = fg_color or theme.INK
        self.hover_bg = hover_bg or theme.SURFACE_ALT
        self.active_bg = active_bg or self.hover_bg
        self.border_color = border_color or _shade(self.bg_color, 0.90)
        self.disabled_bg = disabled_bg or theme.DISABLED_BG
        self.disabled_fg = disabled_fg or theme.DISABLED_FG
        self.btn_text = text
        self.font = font
        self.current_bg = self.bg_color
        self.state = "normal"

        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

        self._draw()

    def _size(self):
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1:
            width = int(self["width"])
        if height <= 1:
            height = int(self["height"])
        return width, height

    def _draw(self):
        self.delete("all")
        width, height = self._size()
        pad = 1
        radius = max(2, min(self.radius, (height - 2 * pad) / 2))

        if self.state == "disabled":
            fill = self.disabled_bg
            outline = _shade(self.disabled_bg, 0.96)
            text_color = self.disabled_fg
        else:
            fill = self.current_bg
            outline = self.border_color
            text_color = self.fg_color

        draw_rounded_rect(
            self,
            pad,
            pad,
            width - pad,
            height - pad,
            radius,
            fill=fill,
            outline=outline,
            width=1,
        )
        self.create_text(
            width / 2,
            height / 2,
            text=self.btn_text,
            fill=text_color,
            font=self.font,
        )

    def _on_resize(self, _event):
        self._draw()

    def _on_enter(self, _event):
        if self.state == "normal":
            self.current_bg = self.hover_bg
            self._draw()

    def _on_leave(self, _event):
        if self.state == "normal":
            self.current_bg = self.bg_color
            self._draw()

    def _on_press(self, _event):
        if self.state == "normal":
            self.current_bg = self.active_bg
            self._draw()

    def _on_release(self, event):
        if self.state != "normal":
            return
        self.current_bg = self.hover_bg
        self._draw()
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        if inside and self.command:
            self.command()

    def set_state(self, state: str):
        self.state = state
        if state == "disabled":
            self.config(cursor="")
        else:
            self.config(cursor="hand2")
        self._draw()

    def set_text(self, text: str):
        self.btn_text = text
        self._draw()

    def set_colors(self, bg_color, fg_color, hover_bg=None, border_color=None):
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_bg = hover_bg or bg_color
        self.border_color = border_color or _shade(bg_color, 0.90)
        self.current_bg = self.bg_color
        self._draw()


class StyledCard(tk.Frame):
    """Карточка с тонкой рамкой и внутренними отступами."""

    def __init__(
        self,
        parent,
        bg=None,
        card_bg=None,
        border_color=None,
        padding=16,
        **kwargs,
    ):
        bg = bg or theme.BG
        card_bg = card_bg or theme.SURFACE
        border_color = border_color or theme.BORDER
        super().__init__(parent, bg=border_color, bd=0, highlightthickness=0, **kwargs)
        container = tk.Frame(self, bg=card_bg)
        container.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.inner_frame = tk.Frame(container, bg=card_bg)
        self.inner_frame.pack(fill=tk.BOTH, expand=True, padx=padding, pady=padding)


class GradientFooterCanvas(tk.Canvas):
    """Тонкая градиентная линия-акцент в палитре Gemini."""

    def __init__(self, parent, height=3, start_color=None, end_color=None, **kwargs):
        super().__init__(
            parent,
            height=height,
            bg=parent["bg"],
            bd=0,
            highlightthickness=0,
            **kwargs,
        )
        if start_color and end_color:
            self.stops = [start_color, end_color]
        else:
            self.stops = list(theme.GRADIENT)
        self.bind("<Configure>", self._draw_gradient)

    def _draw_gradient(self, _event=None):
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 0:
            return

        stops = [_hex_to_rgb(color) for color in self.stops]
        segments = len(stops) - 1
        for x in range(width):
            position = (x / max(1, width - 1)) * segments
            index = min(int(position), segments - 1)
            t = position - index
            r1, g1, b1 = stops[index]
            r2, g2, b2 = stops[index + 1]
            color = _rgb_to_hex(
                (
                    int(r1 + (r2 - r1) * t),
                    int(g1 + (g2 - g1) * t),
                    int(b1 + (b2 - b1) * t),
                )
            )
            self.create_line(x, 0, x, height, fill=color)


class ProgressBar(tk.Canvas):
    """Тонкий скруглённый индикатор: определённый или «бегущий»."""

    def __init__(self, parent, height=6, bg=None, track=None, fill=None, **kwargs):
        super().__init__(
            parent,
            height=height,
            bg=bg or theme.SURFACE,
            bd=0,
            highlightthickness=0,
            **kwargs,
        )
        self.track = track or theme.TRACK
        self.fill = fill or theme.ACCENT
        self._ratio = 0.0
        self._indeterminate = False
        self._offset = 0
        self._after_id = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Destroy>", self._on_destroy)
        self._draw()

    def set(self, ratio: float):
        self.stop_indeterminate()
        self._ratio = max(0.0, min(1.0, ratio))
        self._draw()

    def start_indeterminate(self):
        if self._indeterminate:
            return
        self._indeterminate = True
        self._offset = 0
        self._tick()

    def stop_indeterminate(self):
        self._indeterminate = False
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._draw()

    def _on_destroy(self, _event):
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _tick(self):
        if not self._indeterminate:
            return
        width = self.winfo_width()
        if width <= 1:
            width = 120
        self._offset = (self._offset + 6) % (width + 80)
        self._draw()
        try:
            self._after_id = self.after(50, self._tick)
        except tk.TclError:
            self._after_id = None

    def _draw(self):
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1:
            width = int(self["width"] or 100)
        if height <= 1:
            height = int(self["height"])
        radius = height / 2

        draw_rounded_rect(self, 0, 0, width, height, radius, fill=self.track, outline="")

        if self._indeterminate:
            segment = max(42, int(width * 0.22))
            x1 = self._offset - segment
            x2 = self._offset
            if x2 > 0 and x1 < width:
                draw_rounded_rect(
                    self,
                    max(0, x1),
                    0,
                    min(width, x2),
                    height,
                    radius,
                    fill=self.fill,
                    outline="",
                )
            return

        if self._ratio > 0:
            fill_width = max(height, width * self._ratio)
            draw_rounded_rect(self, 0, 0, fill_width, height, radius, fill=self.fill, outline="")


class FuzzingMetricsFrame(tk.Frame):
    """Компактная карточка метрик текущего подбора."""

    def __init__(self, parent, bg=None, **kwargs):
        super().__init__(parent, bg=bg or theme.SURFACE, **kwargs)
        self.bg = bg or theme.SURFACE

        self.var_progress_str = tk.StringVar(value="Готов к работе")
        self.var_success_rate = tk.StringVar(value="0 / 0 (0%)")
        self.var_active_strategy = tk.StringVar(value="Из батника")
        self.var_elapsed_time = tk.StringVar(value="00:00")

        self._build_ui()

    def _build_ui(self):
        grid = tk.Frame(self, bg=self.bg)
        grid.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        grid.columnconfigure(1, weight=1)

        tk.Label(
            grid, text="Прогресс", font=theme.font(8), bg=self.bg, fg=theme.MUTED
        ).grid(row=0, column=0, sticky=tk.W, pady=(0, 2))
        tk.Label(
            grid,
            textvariable=self.var_progress_str,
            font=theme.font(9, "bold"),
            bg=self.bg,
            fg=theme.ACCENT,
        ).grid(row=0, column=1, sticky=tk.E, pady=(0, 2))

        self.progress = ProgressBar(grid, bg=self.bg, height=6)
        self.progress.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(0, 10))

        tk.Label(
            grid, text="Пройдено", font=theme.font(8), bg=self.bg, fg=theme.MUTED
        ).grid(row=2, column=0, sticky=tk.W, pady=2)
        tk.Label(
            grid,
            textvariable=self.var_success_rate,
            font=theme.font(9, "bold"),
            bg=self.bg,
            fg=theme.INK,
        ).grid(row=2, column=1, sticky=tk.E, pady=2)

        tk.Label(
            grid, text="Время", font=theme.font(8), bg=self.bg, fg=theme.MUTED
        ).grid(row=3, column=0, sticky=tk.W, pady=2)
        tk.Label(
            grid,
            textvariable=self.var_elapsed_time,
            font=theme.font(9, "bold"),
            bg=self.bg,
            fg=theme.INK,
        ).grid(row=3, column=1, sticky=tk.E, pady=2)

        tk.Label(
            grid, text="Профиль", font=theme.font(8), bg=self.bg, fg=theme.MUTED
        ).grid(row=4, column=0, sticky=tk.NW, pady=(2, 0))
        tk.Label(
            grid,
            textvariable=self.var_active_strategy,
            font=theme.font(8, "bold"),
            bg=self.bg,
            fg=theme.INK_SOFT,
            wraplength=190,
            justify=tk.RIGHT,
        ).grid(row=4, column=1, sticky=tk.E, pady=(2, 0))

    def update_metrics(
        self,
        current_step: int,
        total_steps: int,
        passed: int,
        total_hosts: int,
        strategy_str: str,
        elapsed_sec: int,
    ):
        ratio = (current_step / total_steps) if total_steps > 0 else 0.0
        percent = int(ratio * 100)
        self.var_progress_str.set(f"{current_step} / {total_steps} ({percent}%)")
        self.progress.set(ratio)

        host_percent = int((passed / max(1, total_hosts)) * 100) if total_hosts > 0 else 0
        self.var_success_rate.set(f"{passed} / {total_hosts} ({host_percent}%)")

        minutes, seconds = divmod(max(0, elapsed_sec), 60)
        self.var_elapsed_time.set(f"{minutes:02d}:{seconds:02d}")

        if strategy_str:
            self.var_active_strategy.set(strategy_str)

    def start_indeterminate(self, text: str = "Диагностика..."):
        self.var_progress_str.set(text)
        self.progress.start_indeterminate()

    def stop_indeterminate(self):
        self.progress.stop_indeterminate()

    def set_elapsed(self, elapsed_sec: int):
        minutes, seconds = divmod(max(0, elapsed_sec), 60)
        self.var_elapsed_time.set(f"{minutes:02d}:{seconds:02d}")

    def reset_metrics(self):
        self.var_progress_str.set("В процессе...")
        self.var_success_rate.set("0 / 0 (0%)")
        self.var_elapsed_time.set("00:00")
        self.var_active_strategy.set("Подбор...")
        self.progress.set(0.0)
