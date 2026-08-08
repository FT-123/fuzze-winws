import tkinter as tk
import os
from typing import List, Tuple


class FuzzingAnalyticsCanvas(tk.Canvas):
    """Компактная векторная диаграмма доступности доменов и задержки (ping ms). Все шрифты целые."""
    def __init__(self, parent, bg="#0d101d", **kwargs):
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self.data_history: List[Tuple[str, float, float]] = []
        self.bind("<Configure>", self.redraw)

    def add_data_point(self, label: str, success_rate: float, latency: float):
        self.data_history.append((label, success_rate, latency))
        if len(self.data_history) > 20:
            self.data_history.pop(0)
        self.redraw()

    def clear_data(self):
        self.data_history.clear()
        self.redraw()

    def redraw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 20 or h < 20:
            return

        pad_left, pad_right, pad_top, pad_bottom = 28, 10, 14, 18
        chart_w = w - pad_left - pad_right
        chart_h = h - pad_top - pad_bottom

        self.create_rectangle(pad_left, pad_top, w - pad_right, h - pad_bottom, outline="#22273d", fill="#08090f")

        for pct in [0, 50, 100]:
            y = pad_top + chart_h * (1.0 - pct / 100.0)
            self.create_line(pad_left, y, w - pad_right, y, fill="#181c2e", dash=(2, 4))
            self.create_text(pad_left - 4, y, text=f"{pct}%", fill="#525b75", font=("Segoe UI", 7, "bold"), anchor="e")

        if not self.data_history:
            self.create_text(w / 2, h / 2, text="📊 Ожидание данных раунда...", fill="#525b75", font=("Segoe UI", 8, "italic"))
            return

        n = len(self.data_history)
        step_x = chart_w / max(1, n - 1) if n > 1 else chart_w / 2

        points_success = []
        points_latency = []
        max_lat = max([lat for _, _, lat in self.data_history if lat > 0] or [100.0])

        for i, (label, rate, lat) in enumerate(self.data_history):
            x = pad_left + (i * step_x if n > 1 else chart_w / 2)
            y_rate = pad_top + chart_h * (1.0 - rate / 100.0)
            y_lat = pad_top + chart_h * (1.0 - min(lat, max_lat) / max_lat)

            points_success.append((x, y_rate))
            points_latency.append((x, y_lat))

            self.create_text(x, h - pad_bottom + 8, text=label.replace("МУТАЦИЯ #", "#"), fill="#8f9bb3", font=("Segoe UI", 7))

        if len(points_success) > 1:
            poly_points = [pad_left, h - pad_bottom]
            for x, y in points_success:
                poly_points.extend([x, y])
            poly_points.extend([points_success[-1][0], h - pad_bottom])
            self.create_polygon(poly_points, fill="#00f5d4", stipple="gray25" if os.name == 'nt' else "")

            for i in range(len(points_success) - 1):
                self.create_line(points_success[i][0], points_success[i], points_success[i+1][0], points_success[i+1], fill="#00f5d4", width=2, capstyle=tk.ROUND)

            for i in range(len(points_latency) - 1):
                self.create_line(points_latency[i][0], points_latency[i], points_latency[i+1][0], points_latency[i+1], fill="#7000ff", width=1, dash=(3, 2))

        for (x, y) in points_success:
            self.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#00f5d4", outline="#ffffff")

        self.create_line(w - 120, pad_top - 6, w - 108, pad_top - 6, fill="#00f5d4", width=2)
        self.create_text(w - 104, pad_top - 6, text="Успех (%)", fill="#00f5d4", font=("Segoe UI", 7, "bold"), anchor="w")

        self.create_line(w - 52, pad_top - 6, w - 40, pad_top - 6, fill="#7000ff", width=2)
        self.create_text(w - 36, pad_top - 6, text="Пинг", fill="#7000ff", font=("Segoe UI", 7, "bold"), anchor="w")