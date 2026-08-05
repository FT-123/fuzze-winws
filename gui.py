import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import queue
import os
import sys
import ctypes
from typing import List, Optional, Tuple, Dict

from presets import DEFAULT_GAME_PRESETS, fetch_preset_targets, search_app_hosts_online, load_history
from fuzzer_engine import FuzzerEngine, WinwsParams
from updater import check_and_download_github_exe

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False


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


class StyledCard(tk.Frame):
    """Надежный контейнер-карточка на базе tk.Frame с аккуратной рамкой и автоматическим подгоном высоты."""
    def __init__(self, parent, bg="#08090f", card_bg="#111422", border_color="#22273d", padding=6, **kwargs):
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

    def _rgb_to_hex(self, rgb):
        return f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"

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


class MiniTrayOverlay(tk.Toplevel):
    """Компактная плавающая мини-панель для разворачивания приложения при сворачивании."""
    def __init__(self, parent, on_restore_cb, on_exit_cb):
        super().__init__(parent)
        self.on_restore_cb = on_restore_cb
        self.on_exit_cb = on_exit_cb

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#111422")

        ws = self.winfo_screenwidth()
        hs = self.winfo_screenheight()
        w, h = 220, 38
        x = max(10, ws - w - 24)
        y = max(10, hs - h - 64)
        self.geometry(f"{w}x{h}+{x}+{y}")

        frame = tk.Frame(self, bg="#111422", highlightbackground="#00f5d4", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(frame, text="⚡ Zapret Fuzzer", font=("Segoe UI", 8, "bold"), bg="#111422", fg="#00f5d4")
        lbl.pack(side=tk.LEFT, padx=(8, 4))

        btn_restore = tk.Button(
            frame, text="↗ Развернуть", font=("Segoe UI", 8, "bold"),
            bg="#1a1f33", fg="#f0f4f8", activebackground="#00f5d4", activeforeground="#08090f",
            bd=0, command=self._restore, cursor="hand2", padx=6, pady=2
        )
        btn_restore.pack(side=tk.LEFT, padx=4)

        btn_close = tk.Button(
            frame, text="✕", font=("Segoe UI", 8, "bold"),
            bg="#111422", fg="#ff4757", activebackground="#ff4757", activeforeground="#ffffff",
            bd=0, command=self._exit, cursor="hand2", padx=4
        )
        btn_close.pack(side=tk.RIGHT, padx=6)

    def _restore(self):
        self.destroy()
        self.on_restore_cb()

    def _exit(self):
        self.destroy()
        self.on_exit_cb()


class TrayManager:
    """Универсальный менеджер системного трея с интеграцией pystray и плавающим оверлеем."""
    def __init__(self, root: tk.Tk, on_restore_cb, on_exit_cb):
        self.root = root
        self.on_restore_cb = on_restore_cb
        self.on_exit_cb = on_exit_cb
        self.is_minimized = False
        self.pystray_icon = None
        self.overlay_window = None

    def _create_pystray_image(self):
        if not HAS_PYSTRAY:
            return None
        img = Image.new('RGBA', (64, 64), color=(8, 9, 15, 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse([6, 6, 58, 58], fill=(0, 245, 212, 255))
        draw.polygon([(28, 14), (44, 14), (30, 32), (40, 32), (20, 52), (28, 32), (20, 32)], fill=(8, 9, 15, 255))
        return img

    def _start_pystray(self) -> bool:
        if not HAS_PYSTRAY or self.pystray_icon is not None:
            return False
        try:
            image = self._create_pystray_image()
            menu = pystray.Menu(
                pystray.MenuItem("Показать Zapret Fuzzer", lambda icon, item: self.root.after(0, self.restore_from_tray)),
                pystray.MenuItem("Выход", lambda icon, item: self.root.after(0, self.on_exit_cb))
            )
            self.pystray_icon = pystray.Icon("ZapretFuzzer", image, "Zapret Fuzzer & Strategy Tuner", menu)
            threading.Thread(target=self.pystray_icon.run, daemon=True).start()
            return True
        except Exception:
            self.pystray_icon = None
            return False

    def minimize_to_tray(self):
        self.is_minimized = True
        self.root.withdraw()

        started_pystray = self._start_pystray()

        if not started_pystray and (self.overlay_window is None or not self.overlay_window.winfo_exists()):
            self.overlay_window = MiniTrayOverlay(self.root, on_restore_cb=self.restore_from_tray, on_exit_cb=self.on_exit_cb)

    def restore_from_tray(self):
        self.is_minimized = False
        if self.overlay_window and self.overlay_window.winfo_exists():
            self.overlay_window.destroy()
            self.overlay_window = None

        if self.pystray_icon:
            try:
                self.pystray_icon.stop()
            except Exception:
                pass
            self.pystray_icon = None

        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()


class HistoryDialog(tk.Toplevel):
    """Компактное диалоговое окно истории."""
    def __init__(self, parent, on_select_callback):
        super().__init__(parent)
        self.title("🧠 Neural Expressive — История приложений")
        self.geometry("450x280")
        self.resizable(False, False)
        self.configure(bg="#08090f")
        self.on_select_callback = on_select_callback

        self._build_ui()
        self.transient(parent)
        self.grab_set()

    def _build_ui(self):
        card = StyledCard(self, bg="#08090f", card_bg="#111422", border_color="#22273d", padding=6)
        card.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        container = card.inner_frame

        header_lbl = tk.Label(
            container,
            text="📜 История найденных приложений & хостов",
            font=("Segoe UI", 9, "bold"),
            bg="#111422",
            fg="#00f5d4"
        )
        header_lbl.pack(anchor=tk.W, pady=(0, 4))

        frame_list = tk.Frame(container, bg="#111422")
        frame_list.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        self.listbox = tk.Listbox(
            frame_list,
            height=5,
            font=("Consolas", 8),
            selectmode=tk.SINGLE,
            bg="#181c2e",
            fg="#f0f4f8",
            selectbackground="#7000ff",
            selectforeground="#ffffff",
            highlightthickness=0,
            activestyle="none",
            bd=0
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        self.history_data = load_history()
        for app_name, hosts in self.history_data.items():
            self.listbox.insert(tk.END, f"  ⚡ {app_name:<18} — [{len(hosts)} хостов/IP]")

        btn_frame = tk.Frame(container, bg="#111422")
        btn_frame.pack(fill=tk.X)

        RoundedButton(
            btn_frame,
            text="📥 Загрузить в фуззер",
            command=self._load_selected,
            radius=6,
            bg_color="#00f5d4",
            fg_color="#08090f",
            hover_bg="#00d4b8",
            width=130,
            height=24
        ).pack(side=tk.RIGHT, padx=(4, 0))

        RoundedButton(
            btn_frame,
            text="Закрыть",
            command=self.destroy,
            radius=6,
            bg_color="#1a1f33",
            fg_color="#f0f4f8",
            hover_bg="#2a314d",
            width=75,
            height=24
        ).pack(side=tk.RIGHT)

    def _load_selected(self):
        selection = self.listbox.curselection()
        if selection:
            idx = selection[0]
            app_name = list(self.history_data.keys())[idx]
            hosts = self.history_data[app_name]
            self.on_select_callback(app_name, hosts)
            self.destroy()


class ZapretFuzzerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Zapret Fuzzer & Strategy Tuner — Neural Expressive UI v3.8")
        self.root.geometry("820x560")
        self.root.minsize(760, 500)
        self.root.configure(bg="#08090f")

        self.bat_path_var = tk.StringVar(value="general (ALT11).bat")
        self.status_var = tk.StringVar(value="Система готова к работе")
        self.winws_status_var = tk.StringVar(value="Не запущен")
        self.target_hosts: List[str] = []
        self.engine: Optional[FuzzerEngine] = None
        self.log_queue = queue.Queue()

        self.tray_manager = TrayManager(self.root, on_restore_cb=self._restore_from_tray, on_exit_cb=self._exit_app)
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._setup_styles()
        self._build_ui()
        self._start_log_listener()
        self._check_winws_periodically()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        BG_DARK = "#08090f"
        BG_CARD = "#111422"
        FG_TEXT = "#f0f4f8"

        style.configure(".", background=BG_DARK, foreground=FG_TEXT)
        style.configure("TFrame", background=BG_DARK)
        style.configure("TLabel", background=BG_CARD, foreground=FG_TEXT, font=("Segoe UI", 8))

    def _build_ui(self):
        main_container = tk.Frame(self.root, bg="#08090f")
        main_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))

        # --- Header Banner Card ---
        header_card = StyledCard(main_container, bg="#08090f", card_bg="#0d101d", border_color="#22273d", padding=4)
        header_card.pack(fill=tk.X, pady=(0, 4))

        header_content = header_card.inner_frame
        tk.Label(
            header_content,
            text="🧠 ZAPRET FUZZER & STRATEGY TUNER",
            font=("Segoe UI", 10, "bold"),
            bg="#0d101d",
            fg="#00f5d4"
        ).pack(side=tk.LEFT, padx=4)

        tk.Label(
            header_content,
            text="NEURAL EXPRESSIVE UI v3.8",
            font=("Segoe UI", 7, "bold"),
            bg="#0d101d",
            fg="#7000ff"
        ).pack(side=tk.LEFT, padx=(6, 0))

        RoundedButton(
            header_content,
            text="📥 В трей",
            command=self._minimize_to_tray,
            radius=6,
            bg_color="#1e1836",
            fg_color="#d1c4e9",
            hover_bg="#7000ff",
            width=65,
            height=20
        ).pack(side=tk.RIGHT, padx=2)

        # --- Section 1: Strategy & Winws Control Card ---
        sec1_card = StyledCard(main_container, bg="#08090f", card_bg="#111422", border_color="#22273d", padding=5)
        sec1_card.pack(fill=tk.X, pady=(0, 4))

        top_frame = sec1_card.inner_frame

        tk.Label(top_frame, text="⚡ Настройки стратегии и управление winws", font=("Segoe UI", 9, "bold"), bg="#111422", fg="#00f5d4").grid(row=0, column=0, columnspan=7, sticky=tk.W, pady=(0, 2))

        tk.Label(top_frame, text="Файл стратегии:", font=("Segoe UI", 8, "bold"), bg="#111422", fg="#8f9bb3").grid(row=1, column=0, sticky=tk.W, padx=(0, 4))

        bat_entry = tk.Entry(
            top_frame,
            textvariable=self.bat_path_var,
            bg="#181c2e",
            fg="#00f5d4",
            insertbackground="#00f5d4",
            font=("Consolas", 8, "bold"),
            bd=0,
            highlightthickness=1,
            highlightbackground="#22273d",
            highlightcolor="#00f5d4"
        )
        bat_entry.grid(row=1, column=1, sticky=tk.EW, padx=2)

        RoundedButton(top_frame, text="📁 Обзор...", command=self._browse_bat, radius=6, width=70, height=22).grid(row=1, column=2, padx=2)
        RoundedButton(top_frame, text="📜 История", command=self._open_history_dialog, radius=6, bg_color="#7000ff", hover_bg="#8a2be2", width=75, height=22).grid(row=1, column=3, padx=2)
        RoundedButton(top_frame, text="🔄 Обновить", command=self._trigger_update, radius=6, bg_color="#e76f51", hover_bg="#f4a261", width=75, height=22).grid(row=1, column=4, padx=2)

        tk.Label(top_frame, text="Статус winws:", font=("Segoe UI", 8, "bold"), bg="#111422", fg="#8f9bb3").grid(row=1, column=5, padx=(6, 2))
        self.winws_status_lbl = tk.Label(top_frame, textvariable=self.winws_status_var, font=("Segoe UI", 8, "bold"), bg="#111422", fg="#ff4757")
        self.winws_status_lbl.grid(row=1, column=6, sticky=tk.W)

        top_frame.columnconfigure(1, weight=1)

        svc_frame = tk.Frame(top_frame, bg="#111422")
        svc_frame.grid(row=2, column=0, columnspan=7, sticky=tk.EW, pady=(4, 0))

        tk.Label(svc_frame, text="Служба:", font=("Segoe UI", 8, "bold"), bg="#111422", fg="#8f9bb3").pack(side=tk.LEFT, padx=(0, 4))

        RoundedButton(svc_frame, text="▶ Запустить", command=self._start_winws_service, radius=6, bg_color="#2ec4b6", fg_color="#08090f", hover_bg="#20ad96", width=80, height=22).pack(side=tk.LEFT, padx=2)
        RoundedButton(svc_frame, text="⏹ Остановить", command=self._stop_winws_service, radius=6, width=80, height=22).pack(side=tk.LEFT, padx=2)
        RoundedButton(svc_frame, text="🔄 Перезапустить", command=self._restart_winws_service, radius=6, width=100, height=22).pack(side=tk.LEFT, padx=2)
        RoundedButton(svc_frame, text="🧹 Сброс WinDivert", command=self._reset_windivert_service, radius=6, bg_color="#ff4757", hover_bg="#ff6b81", width=110, height=22).pack(side=tk.LEFT, padx=(6, 2))

        # --- Section 2: Presets Card ---
        sec2_card = StyledCard(main_container, bg="#08090f", card_bg="#111422", border_color="#22273d", padding=5)
        sec2_card.pack(fill=tk.X, pady=(0, 4))

        preset_frame = sec2_card.inner_frame
        tk.Label(preset_frame, text="🎯 Пресеты приложений", font=("Segoe UI", 9, "bold"), bg="#111422", fg="#00f5d4").pack(anchor=tk.W, pady=(0, 2))

        preset_btn_container = tk.Frame(preset_frame, bg="#111422")
        preset_btn_container.pack(fill=tk.X)

        presets_list = [
            ("🎯 Rainbow Six", "Rainbow Six Siege"),
            ("💬 Discord", "Discord"),
            ("📺 YouTube", "YouTube"),
            ("🎮 Steam", "Steam"),
            ("✈️ Telegram", "Telegram")
        ]

        for i, (label, name) in enumerate(presets_list):
            btn = RoundedButton(
                preset_btn_container,
                text=label,
                command=lambda p=name: self._add_preset_hosts(p),
                radius=6,
                bg_color="#1e1836",
                fg_color="#d1c4e9",
                hover_bg="#7000ff",
                width=105,
                height=22
            )
            btn.grid(row=0, column=i, padx=2, pady=1, sticky=tk.EW)
            preset_btn_container.columnconfigure(i, weight=1)

        search_app_btn = RoundedButton(
            preset_btn_container,
            text="🔎 Поиск по имени",
            command=self._search_app_by_name,
            radius=6,
            width=110,
            height=22
        )
        search_app_btn.grid(row=0, column=len(presets_list), padx=2, pady=1)

        # --- Section 3: Middle Split (Hosts + Analytics + Parameters) ---
        middle_frame = tk.Frame(main_container, bg="#08090f")
        middle_frame.pack(fill=tk.X, expand=False, pady=(0, 4))

        hosts_card = StyledCard(middle_frame, bg="#08090f", card_bg="#111422", border_color="#22273d", padding=5)
        hosts_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))

        hosts_frame = hosts_card.inner_frame
        tk.Label(hosts_frame, text="🌐 Цели и IP", font=("Segoe UI", 9, "bold"), bg="#111422", fg="#00f5d4").pack(anchor=tk.W, pady=(0, 2))

        frame_host_list = tk.Frame(hosts_frame, bg="#111422")
        frame_host_list.pack(fill=tk.BOTH, expand=True)

        self.hosts_listbox = tk.Listbox(
            frame_host_list,
            height=3,
            font=("Consolas", 8),
            selectmode=tk.SINGLE,
            bg="#181c2e",
            fg="#f0f4f8",
            selectbackground="#7000ff",
            selectforeground="#ffffff",
            highlightthickness=0,
            activestyle="none",
            bd=0
        )
        self.hosts_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame_host_list, orient=tk.VERTICAL, command=self.hosts_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hosts_listbox.config(yscrollcommand=scrollbar.set)

        hosts_btn_frame = tk.Frame(hosts_frame, bg="#111422")
        hosts_btn_frame.pack(fill=tk.X, pady=(2, 0))

        RoundedButton(hosts_btn_frame, text="🗑️ Удалить", command=self._remove_selected_host, radius=6, width=95, height=20).pack(side=tk.LEFT, padx=1)
        RoundedButton(hosts_btn_frame, text="🧹 Очистить", command=self._clear_hosts, radius=6, width=75, height=20).pack(side=tk.LEFT, padx=1)

        analytics_card = StyledCard(middle_frame, bg="#08090f", card_bg="#111422", border_color="#22273d", padding=5)
        analytics_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)

        analytics_frame = analytics_card.inner_frame
        tk.Label(analytics_frame, text="📈 Аналитика пробива", font=("Segoe UI", 9, "bold"), bg="#111422", fg="#00f5d4").pack(anchor=tk.W, pady=(0, 2))

        self.analytics_chart = FuzzingAnalyticsCanvas(analytics_frame, bg="#0d101d", height=70)
        self.analytics_chart.pack(fill=tk.BOTH, expand=True)

        params_card = StyledCard(middle_frame, bg="#08090f", card_bg="#111422", border_color="#22273d", padding=5)
        params_card.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 0))

        params_frame = params_card.inner_frame
        tk.Label(params_frame, text="🎛️ Параметры", font=("Segoe UI", 9, "bold"), bg="#111422", fg="#00f5d4").grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 2))

        self.param_labels = {}
        param_names = [
            ("TCP Split:", "tcp_split", "1"),
            ("TCP SeqOvl:", "tcp_seqovl", "664"),
            ("TCP TTL:", "tcp_ttl", "0"),
            ("UDP Repeats:", "udp_repeats", "8"),
            ("UDP Cutoff:", "udp_cutoff", "n4")
        ]

        for row, (title, key, default_val) in enumerate(param_names, start=1):
            tk.Label(params_frame, text=title, font=("Segoe UI", 8, "bold"), bg="#111422", fg="#8f9bb3").grid(row=row, column=0, sticky=tk.W, pady=1, padx=(0, 4))
            val_lbl = tk.Label(params_frame, text=default_val, font=("Consolas", 8, "bold"), bg="#111422", fg="#00f5d4")
            val_lbl.grid(row=row, column=1, sticky=tk.E, pady=1)
            self.param_labels[key] = val_lbl

        # --- Section 4: Engine Execution Controls ---
        ctrl_frame = tk.Frame(main_container, bg="#08090f")
        ctrl_frame.pack(fill=tk.X, pady=(0, 4))

        self.start_btn = RoundedButton(
            ctrl_frame,
            text="🚀 Запустить подбор стратегии (Neural Async Fuzzing)",
            command=self._start_fuzzing,
            radius=8,
            bg_color="#00f5d4",
            fg_color="#08090f",
            hover_bg="#00d4b8",
            font=("Segoe UI", 9, "bold"),
            height=28
        )
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        self.stop_btn = RoundedButton(
            ctrl_frame,
            text="🛑 Остановить",
            command=self._stop_fuzzing,
            radius=8,
            bg_color="#ff4757",
            fg_color="#ffffff",
            hover_bg="#ff6b81",
            font=("Segoe UI", 9, "bold"),
            width=100,
            height=28
        )
        self.stop_btn.set_state(tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT, padx=(2, 0))

        # --- Section 5: Terminal Console Log Card ---
        log_card = StyledCard(main_container, bg="#08090f", card_bg="#05060a", border_color="#22273d", padding=5)
        log_card.pack(fill=tk.BOTH, expand=True, pady=(0, 2))

        log_frame = log_card.inner_frame
        tk.Label(log_frame, text="💻 Консоль подбора", font=("Segoe UI", 9, "bold"), bg="#05060a", fg="#00f5d4").pack(anchor=tk.W, pady=(0, 2))

        frame_text_scroll = tk.Frame(log_frame, bg="#05060a")
        frame_text_scroll.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            frame_text_scroll,
            bg="#05060a",
            fg="#d0d7de",
            insertbackground="#00f5d4",
            font=("Consolas", 8),
            wrap=tk.WORD,
            height=5,
            bd=0,
            highlightthickness=0
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.log_text.tag_config("plus", foreground="#00ff9d", font=("Consolas", 8, "bold"))
        self.log_text.tag_config("star", foreground="#00f0ff")
        self.log_text.tag_config("warn", foreground="#ffd166", font=("Consolas", 8, "bold"))
        self.log_text.tag_config("minus", foreground="#ff4757")

        log_scroll = ttk.Scrollbar(frame_text_scroll, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

        # --- Bottom Gradient & Status Bar ---
        footer_container = tk.Frame(self.root, bg="#08090f")
        footer_container.pack(side=tk.BOTTOM, fill=tk.X)

        self.gradient_footer = GradientFooterCanvas(footer_container, height=20, start_color="#08090f", end_color="#18112e", glow_color="#00f5d4")
        self.gradient_footer.pack(fill=tk.X)

        status_card = StyledCard(footer_container, bg="#08090f", card_bg="#111422", border_color="#22273d", padding=2)
        status_card.pack(fill=tk.X, padx=6, pady=(0, 2))

        status_bar = tk.Label(
            status_card.inner_frame,
            textvariable=self.status_var,
            bg="#111422",
            fg="#8f9bb3",
            font=("Segoe UI", 8),
            anchor=tk.W,
            padx=4,
            pady=1
        )
        status_bar.pack(side=tk.LEFT, fill=tk.X)

    def _minimize_to_tray(self):
        self.tray_manager.minimize_to_tray()
        self.status_var.set("Приложение свернуто в трей")

    def _restore_from_tray(self):
        self.tray_manager.restore_from_tray()
        self.status_var.set("Система готова к работе")

    def _on_window_close(self):
        if messagebox.askyesno("Сворачивание", "Свернуть приложение в трей?\n(Выберите 'Нет' для полного выхода)"):
            self._minimize_to_tray()
        else:
            self._exit_app()

    def _exit_app(self):
        if self.engine:
            self.engine.stop()
        self.root.destroy()
        sys.exit(0)

    def _start_winws_service(self):
        bat = self.bat_path_var.get()
        if not os.path.exists(bat):
            messagebox.showerror("Ошибка", f"Файл '{bat}' не найден!")
            return
        self.log_message(f"[*] Запуск winws.exe ({bat})...")
        alive = FuzzerEngine.start_winws(bat)
        if alive:
            self.log_message("[+] winws.exe успешно запущен!")
            self.status_var.set("winws.exe запущен")
        else:
            self.log_message("[!] Не удалось запустить winws.exe.")
            self.status_var.set("Ошибка запуска winws.exe")

    def _stop_winws_service(self):
        self.log_message("[*] Остановка winws.exe...")
        FuzzerEngine.stop_winws()
        self.log_message("[-] winws.exe остановлен.")
        self.status_var.set("winws.exe остановлен")

    def _restart_winws_service(self):
        self._stop_winws_service()
        self.root.after(1000, self._start_winws_service)

    def _reset_windivert_service(self):
        self.log_message("[*] Сброс драйвера WinDivert и принудительная остановка winws...")
        FuzzerEngine.reset_windivert()
        self.log_message("[+] Драйвер WinDivert сброшен.")
        self.status_var.set("WinDivert сброшен")

    def _search_app_by_name(self):
        app_name = simpledialog.askstring("Поиск программы", "Введите название программы или игры (например, Telegram или Apex Legends):")
        if app_name and app_name.strip():
            app_name = app_name.strip()
            self.log_message(f"[*] Поиск хостов в интернете для программы '{app_name}'...")
            self.status_var.set(f"Поиск хостов для {app_name}...")

            def worker():
                hosts = search_app_hosts_online(app_name)
                self.root.after(0, lambda: self._on_app_hosts_found(app_name, hosts))

            threading.Thread(target=worker, daemon=True).start()

    def _on_app_hosts_found(self, app_name: str, hosts: List[str]):
        if not hosts:
            self.log_message(f"[!] Для программы '{app_name}' не удалось автоматически найти хосты.")
            messagebox.showinfo("Результат", f"Для '{app_name}' не найдены хосты в DNS. Попробуйте ввести точный домен.")
            return

        added_count = 0
        for h in hosts:
            if h not in self.target_hosts:
                self.target_hosts.append(h)
                self.hosts_listbox.insert(tk.END, h)
                added_count += 1

        self.log_message(f"[+] Для '{app_name}' найдено и добавлено {added_count} хостов/IP (сохранено в историю).")
        self.status_var.set(f"Добавлено {added_count} хостов для {app_name}")

    def _open_history_dialog(self):
        HistoryDialog(self.root, on_select_callback=self._on_history_hosts_selected)

    def _on_history_hosts_selected(self, app_name: str, hosts: List[str]):
        added_count = 0
        for h in hosts:
            if h not in self.target_hosts:
                self.target_hosts.append(h)
                self.hosts_listbox.insert(tk.END, h)
                added_count += 1
        self.log_message(f"[+] Из истории '{app_name}' загружено {added_count} хостов.")

    def _trigger_update(self):
        if not messagebox.askyesno("Обновление", "Запустить обновление fuzzer.exe с GitHub?\nТекущий процесс будет перезапущен с новой версией."):
            return

        self.log_message("[*] Загрузка обновленного fuzzer.exe с GitHub...")
        self.status_var.set("Скачивание fuzzer.exe...")

        def worker():
            success, msg = check_and_download_github_exe()
            if not success:
                self.root.after(0, lambda: self.log_message(f"[!] Ошибка обновления: {msg}"))

        threading.Thread(target=worker, daemon=True).start()

    def _browse_bat(self):
        file_selected = filedialog.askopenfilename(
            title="Выберите батник стратегии Zapret",
            filetypes=[("BAT Files", "*.bat"), ("All Files", "*.*")]
        )
        if file_selected:
            self.bat_path_var.set(file_selected)
            self._update_params_display()

    def _add_preset_hosts(self, preset_name: str):
        self.log_message(f"[*] Загрузка хостов и IP для '{preset_name}'...")
        self.status_var.set(f"Поиск IP адресов для {preset_name}...")

        def worker():
            targets = fetch_preset_targets(preset_name, resolve_ips=True)
            self.root.after(0, lambda: self._on_preset_loaded(preset_name, targets))

        threading.Thread(target=worker, daemon=True).start()

    def _on_preset_loaded(self, preset_name: str, targets: List[str]):
        added_count = 0
        for host in targets:
            if host not in self.target_hosts:
                self.target_hosts.append(host)
                self.hosts_listbox.insert(tk.END, host)
                added_count += 1

        self.log_message(f"[+] Для '{preset_name}' добавлено {added_count} новых хостов/IP (всего: {len(self.target_hosts)}).")
        self.status_var.set(f"Добавлено {added_count} хостов для {preset_name}")

    def _remove_selected_host(self):
        selection = self.hosts_listbox.curselection()
        if selection:
            idx = selection[0]
            host = self.hosts_listbox.get(idx)
            self.hosts_listbox.delete(idx)
            if host in self.target_hosts:
                self.target_hosts.remove(host)
            self.log_message(f"[-] Удален хост: {host}")

    def _clear_hosts(self):
        self.hosts_listbox.delete(0, tk.END)
        self.target_hosts.clear()
        self.log_message("[-] Список хостов очищен.")

    def _update_params_display(self, params: Optional[WinwsParams] = None):
        if params is None:
            try:
                temp_engine = FuzzerEngine(bat_path=self.bat_path_var.get())
                params = temp_engine.extract_baseline()
            except Exception:
                return

        self.param_labels["tcp_split"].config(text=str(params.tcp_split))
        self.param_labels["tcp_seqovl"].config(text=str(params.tcp_seqovl))
        self.param_labels["tcp_ttl"].config(text=str(params.tcp_ttl))
        self.param_labels["udp_repeats"].config(text=str(params.udp_repeats))
        self.param_labels["udp_cutoff"].config(text=str(params.udp_cutoff))

    def _start_fuzzing(self):
        if not self.target_hosts:
            messagebox.showwarning("Внимание", "Список целевых хостов пуст! Нажмите на кнопку игры или добавьте хост.")
            return

        bat_file = self.bat_path_var.get()
        if not os.path.exists(bat_file):
            messagebox.showerror("Ошибка", f"Файл '{bat_file}' не найден!")
            return

        self.start_btn.set_state(tk.DISABLED)
        self.stop_btn.set_state(tk.NORMAL)
        self.status_var.set("Асинхронный подбор в процессе...")
        self.analytics_chart.clear_data()

        self.engine = FuzzerEngine(
            bat_path=bat_file,
            log_callback=self.log_message,
            status_callback=self._on_engine_status
        )

        def worker():
            self.engine.run_fuzzing(self.target_hosts)
            self.root.after(0, self._on_fuzzing_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _stop_fuzzing(self):
        if self.engine:
            self.engine.stop()
            self.log_message("[!] Запрос остановки...")

    def _on_fuzzing_finished(self):
        self.start_btn.set_state(tk.NORMAL)
        self.stop_btn.set_state(tk.DISABLED)
        self.status_var.set("Работа завершена")
        self._update_params_display()

    def _on_engine_status(self, status_dict: dict):
        if "params" in status_dict:
            self.root.after(0, lambda: self._update_params_display(status_dict["params"]))
        if "message" in status_dict:
            self.status_var.set(status_dict["message"])

    def log_message(self, text: str):
        self.log_queue.put(text)
        if "Результат:" in text and "доступно" in text:
            try:
                parts = text.split("Результат:").strip().split()
                counts = parts[0].split("/")
                passed, total = int(counts[0]), int(counts)
                rate_pct = round((passed / max(1, total)) * 100.0, 1)

                step_name = "Р "
                self.root.after(0, lambda: self.analytics_chart.add_data_point(step_name, rate_pct, 45.0))
            except Exception:
                pass

    def _append_log_with_tags(self, msg: str):
        if msg.startswith("[+]"):
            self.log_text.insert(tk.END, msg[:3], "plus")
            self.log_text.insert(tk.END, msg[3:] + "\n")
        elif msg.startswith("[*]"):
            self.log_text.insert(tk.END, msg[:3], "star")
            self.log_text.insert(tk.END, msg[3:] + "\n")
        elif msg.startswith("[!]"):
            self.log_text.insert(tk.END, msg[:3], "warn")
            self.log_text.insert(tk.END, msg[3:] + "\n")
        elif msg.startswith("[-]"):
            self.log_text.insert(tk.END, msg[:3], "minus")
            self.log_text.insert(tk.END, msg[3:] + "\n")
        else:
            self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)

    def _start_log_listener(self):
        def check_queue():
            while not self.log_queue.empty():
                msg = self.log_queue.get()
                self._append_log_with_tags(msg)
            self.root.after(100, check_queue)

        self.root.after(100, check_queue)

    def _check_winws_periodically(self):
        def check():
            alive = FuzzerEngine.is_winws_alive()
            if alive:
                self.winws_status_var.set("🟢 ONLINE (winws.exe)")
                self.winws_status_lbl.config(foreground="#00f5d4")
            else:
                self.winws_status_var.set("🔴 OFFLINE")
                self.winws_status_lbl.config(foreground="#ff4757")
            self.root.after(2000, check)

        self.root.after(1000, check)