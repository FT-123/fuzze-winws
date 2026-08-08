import tkinter as tk
from typing import Tuple


class RoundedButton(tk.Canvas):
    """Кастомная кнопка с закругленными углами в стиле Neural Expressive."""
    def __init__(self, parent, text="", command=None, radius=6,
                 bg_color="#1a1f33", fg_color="#f0f4f8",
                 hover_bg="#2a314d", active_bg="#00f5d4",
                 disabled_bg="#121524", disabled_fg="#525b75",
                 font=("Segoe UI", 8, "bold"), width=95, height=24,
                 border_color=None, cursor="hand2"):
        parent_bg = parent["bg"] if isinstance(parent, (tk.Frame, tk.LabelFrame, tk.Toplevel, tk.Tk)) and "bg" in parent.keys() else "#111422"
        super().__init__(parent, bg=parent_bg, height=height, width=width, highlightthickness=0, bd=0, cursor=cursor)
        self.command = command
        self.radius = radius
        self.normal_bg = bg_color
        self.hover_bg = hover_bg
        self.active_bg = active_bg
        self.disabled_bg = disabled_bg
        self.disabled_fg = disabled_fg
        self.normal_fg = fg_color
        self.fg_color = fg_color
        self.text = text
        self.font = font
        self.border_color = border_color
        self.is_disabled = False
        self.current_bg = bg_color

        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _create_rounded_polygon(self, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _draw(self, fill_color, text_color=None):
        self.delete("all")
        w = self.winfo_width() or self.winfo_reqwidth()
        h = self.winfo_height() or self.winfo_reqheight()
        if w < 10 or h < 10:
            return
        r = min(self.radius, h // 2, w // 2)
        txt_col = text_color if text_color else self.fg_color

        if self.border_color:
            self._create_rounded_polygon(1, 1, w - 1, h - 1, r, fill=self.border_color)
            self._create_rounded_polygon(2, 2, w - 2, h - 2, max(1, r - 1), fill=fill_color)
        else:
            self._create_rounded_polygon(1, 1, w - 1, h - 1, r, fill=fill_color)

        self.create_text(w / 2, h / 2, text=self.text, fill=txt_col, font=self.font)

    def _on_resize(self, event):
        self._draw(self.current_bg)

    def _on_enter(self, event):
        if not self.is_disabled:
            self.current_bg = self.hover_bg
            self._draw(self.hover_bg)

    def _on_leave(self, event):
        if not self.is_disabled:
            self.current_bg = self.normal_bg
            self._draw(self.normal_bg)

    def _on_click(self, event):
        if not self.is_disabled and self.command:
            self.current_bg = self.active_bg
            self._draw(self.active_bg)
            self.after(120, lambda: self._draw(self.hover_bg if self.current_bg == self.active_bg else self.current_bg))
            self.command()

    def set_state(self, state):
        if state == tk.DISABLED or state == "disabled":
            self.is_disabled = True
            self.current_bg = self.disabled_bg
            self._draw(self.disabled_bg, self.disabled_fg)
            self.config(cursor="")
        else:
            self.is_disabled = False
            self.current_bg = self.normal_bg
            self._draw(self.normal_bg, self.normal_fg)
            self.config(cursor="hand2")

    def config(self, **kwargs):
        if "state" in kwargs:
            self.set_state(kwargs.pop("state"))
        if "text" in kwargs:
            self.text = kwargs.pop("text")
            self._draw(self.current_bg)
        if kwargs:
            super().config(**kwargs)

    configure = config


class StyledCard(tk.Frame):
    """Надежный контейнер-карточка на базе tk.Frame с аккуратной рамкой и автоматическим подгоном высоты."""
    def __init__(self, parent, card_bg="#111422", border_color="#22273d", padding=6, **kwargs):
        kwargs.pop("bg", None)
        super().__init__(
            parent,
            bg=card_bg,
            highlightbackground=border_color,
            highlightthickness=1,
            bd=0,
            padx=padding,
            pady=padding,
            **kwargs
        )
        self.inner_frame = self


class GradientFooterCanvas(tk.Canvas):
    """Кастомный нижний холст с плавным переходящим градиентом от фонового к тёмно-акцентному тону."""
    def __init__(self, parent, height=20, start_color="#08090f", end_color="#18112e", glow_color="#00f5d4", **kwargs):
        super().__init__(parent, height=height, highlightthickness=0, bd=0, bg=start_color, **kwargs)
        self.start_color = start_color
        self.end_color = end_color
        self.glow_color = glow_color
        self.bind("<Configure>", self._draw_gradient)

    def _hex_to_rgb(self, hex_str: str) -> Tuple[int, int, int]:
        hex_str = hex_str.lstrip('#')
        return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

    def _rgb_to_hex(self, rgb: Tuple[int, int, int]) -> str:
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    def _draw_gradient(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 0 or h <= 0:
            return

        r1, g1, b1 = self._hex_to_rgb(self.start_color)
        r2, g2, b2 = self._hex_to_rgb(self.end_color)

        steps = max(1, h)
        for i in range(steps):
            ratio = i / float(steps)
            nr = int(r1 + (r2 - r1) * ratio)
            ng = int(g1 + (g2 - g1) * ratio)
            nb = int(b1 + (b2 - b1) * ratio)
            color = self._rgb_to_hex((nr, ng, nb))
            self.create_line(0, i, w, i, fill=color)

        self.create_line(0, h - 1, w, h - 1, fill=self.glow_color, width=1)