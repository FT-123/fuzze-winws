import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import queue
import os
import sys
import time
from typing import List, Optional

from config import (
    APP_DIR,
    AUTO_STRATEGY,
    LISTS_DIR,
    ensure_app_dirs,
    ensure_default_strategy,
    load_settings,
    update_settings,
)
from presets import (
    fetch_preset_targets, search_app_hosts_online,
    export_presets_to_file, import_presets_from_file
)
from fuzzer_engine import FuzzerEngine, WinwsParams, validate_params
from updater import (
    UpdateError,
    UpdateInfo,
    check_for_update,
    download_installer,
    launch_update,
    reset_base_bats_from_github,
)
from version import __version__

from ui.components import RoundedButton, StyledCard, GradientFooterCanvas, FuzzingMetricsFrame
from ui import theme
from ui.theme import MONO, MONO_FAMILY, font as ui_font, setup_ttk
from ui.tray import HAS_PYSTRAY, TrayManager
from ui.dialogs import DomainListsDialog, HistoryDialog, InteractiveParamsWindow


class ZapretFuzzerApp:
    def __init__(self, root: tk.Tk):
        ensure_app_dirs()
        self.root = root
        self.root.title("Zapret Strategy Tuner")
        window_width, window_height = 1020, 880
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_x = max(0, (screen_width - window_width) // 2)
        window_y = max(0, (screen_height - window_height) // 2 - 20)
        self.root.geometry(f"{window_width}x{window_height}+{window_x}+{window_y}")
        self.root.minsize(940, 760)
        self.root.configure(bg=theme.BG)

        self.bat_path_var = tk.StringVar(value=ensure_default_strategy())
        self.status_var = tk.StringVar(value="Система готова к работе")
        self.winws_status_var = tk.StringVar(value="Остановлен")
        self.target_hosts: List[str] = []
        self.engine: Optional[FuzzerEngine] = None
        self.log_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.ui_queue = queue.Queue()
        self._winws_probe_active = False
        self._fuzzing_started_at = 0.0
        self._metrics_step = 0
        self._metrics_total = 0
        self._metrics_passed = 0
        self._metrics_hosts = 0
        self._last_engine_status = None
        self._winws2_mode = False
        self.search_mode_var = tk.StringVar(value="Стандартный")
        self.engine_var = tk.StringVar(value="движок: —")
        self.advanced_visible = False
        self._service_running = False
        self._update_info: Optional[UpdateInfo] = None

        self.tray_manager = TrayManager(self.root, on_restore=self._restore_from_tray, on_exit=self._exit_app)
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._setup_styles()
        self._build_ui()
        self._apply_advanced_visibility()
        self._restore_saved_targets()
        self._start_log_listener()
        self._check_winws_periodically()
        self.root.after(200, self._update_params_display)
        self.root.after(300, self._validate_engine_assets)
        self.root.after(320, self._log_tray_backend)
        self.root.after(500, self._tick_elapsed)
        self.root.after(2000, self._check_updates_silently)

    def _setup_styles(self):
        setup_ttk(self.root)

    def _build_ui(self):
        main_container = tk.Frame(self.root, bg=theme.BG)
        main_container.pack(fill=tk.BOTH, expand=True, padx=22, pady=(12, 4))

        # ---------------- Header ----------------
        header = tk.Frame(main_container, bg=theme.BG)
        header.pack(fill=tk.X, pady=(0, 10))

        tk.Label(
            header, text="✦", font=ui_font(22, "bold"), bg=theme.BG, fg=theme.ACCENT
        ).pack(side=tk.LEFT, padx=(0, 10))

        title_box = tk.Frame(header, bg=theme.BG)
        title_box.pack(side=tk.LEFT)
        tk.Label(
            title_box,
            text="Zapret Strategy Tuner",
            font=ui_font(18, "bold"),
            bg=theme.BG,
            fg=theme.INK,
        ).pack(anchor=tk.W)
        tk.Label(
            title_box,
            text=f"Автонастройка обхода DPI · выберите сервисы, остальное — само · v{__version__}",
            font=ui_font(9),
            bg=theme.BG,
            fg=theme.MUTED,
        ).pack(anchor=tk.W, pady=(1, 0))

        header_right = tk.Frame(header, bg=theme.BG)
        header_right.pack(side=tk.RIGHT)

        RoundedButton(
            header_right,
            text="В трей",
            command=self._minimize_to_tray,
            radius=16,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=76,
            height=30,
            font=ui_font(9),
        ).pack(side=tk.RIGHT, padx=(8, 0))

        self.theme_btn = RoundedButton(
            header_right,
            text=theme.toggle_label(),
            command=self._toggle_theme,
            radius=16,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=116,
            height=30,
            font=ui_font(9),
        )
        self.theme_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self.advanced_btn = RoundedButton(
            header_right,
            text="Дополнительно",
            command=self._toggle_advanced,
            radius=16,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=124,
            height=30,
            font=ui_font(9),
        )
        self.advanced_btn.pack(side=tk.RIGHT, padx=(8, 0))

        status_box = tk.Frame(header_right, bg=theme.SURFACE_ALT, padx=12, pady=6)
        status_box.pack(side=tk.RIGHT)
        tk.Label(
            status_box, text="winws", font=ui_font(8, "bold"), bg=theme.SURFACE_ALT, fg=theme.MUTED
        ).pack(side=tk.LEFT, padx=(0, 6))
        self.winws_status_lbl = tk.Label(
            status_box,
            textvariable=self.winws_status_var,
            font=ui_font(9, "bold"),
            bg=theme.SURFACE_ALT,
            fg=theme.RED,
        )
        self.winws_status_lbl.pack(side=tk.LEFT)

        # ---------------- Strategy card ----------------
        self.strategy_card = StyledCard(main_container, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=12)
        self.strategy_card.pack(fill=tk.X, pady=(0, 8))
        strategy_frame = self.strategy_card.inner_frame

        strategy_title = tk.Frame(strategy_frame, bg=theme.SURFACE)
        strategy_title.pack(fill=tk.X)
        tk.Label(
            strategy_title,
            text="Стратегия",
            font=ui_font(11, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(side=tk.LEFT)
        self.engine_label = tk.Label(
            strategy_title,
            textvariable=self.engine_var,
            font=ui_font(8),
            bg=theme.SURFACE,
            fg=theme.MUTED,
        )
        self.engine_label.pack(side=tk.RIGHT)

        file_row = tk.Frame(strategy_frame, bg=theme.SURFACE)
        file_row.pack(fill=tk.X, pady=(8, 0))

        tk.Label(
            file_row,
            text="Файл стратегии",
            width=15,
            anchor=tk.W,
            font=ui_font(9),
            bg=theme.SURFACE,
            fg=theme.MUTED,
        ).pack(side=tk.LEFT)

        for text, command, width in (
            ("Обновить", self._trigger_update, 86),
            ("История", self._open_history_dialog, 84),
            ("Обзор…", self._browse_bat, 80),
        ):
            RoundedButton(
                file_row,
                text=text,
                command=command,
                radius=15,
                bg_color=theme.SURFACE if text != "История" else theme.ACCENT_SOFT,
                fg_color=theme.INK_SOFT if text != "История" else theme.ACCENT,
                hover_bg=theme.SURFACE_ALT if text != "История" else theme.ACCENT_SOFT_HOVER,
                border_color=theme.BORDER if text != "История" else theme.ACCENT_SOFT_HOVER,
                width=width,
                height=30,
                font=ui_font(9),
            ).pack(side=tk.RIGHT, padx=(6, 0))

        bat_entry = tk.Entry(
            file_row,
            textvariable=self.bat_path_var,
            bg=theme.SURFACE_SOFT,
            fg=theme.INK,
            insertbackground=theme.ACCENT,
            font=(MONO_FAMILY, 9),
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.ACCENT,
        )
        bat_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 4))

        tk.Frame(strategy_frame, bg=theme.BORDER, height=1).pack(fill=tk.X, pady=8)

        service_row = tk.Frame(strategy_frame, bg=theme.SURFACE)
        service_row.pack(fill=tk.X)

        tk.Label(
            service_row,
            text="Служба winws",
            width=15,
            anchor=tk.W,
            font=ui_font(9),
            bg=theme.SURFACE,
            fg=theme.MUTED,
        ).pack(side=tk.LEFT)

        service_buttons = tk.Frame(service_row, bg=theme.SURFACE)
        service_buttons.pack(side=tk.LEFT, fill=tk.X, expand=True)

        RoundedButton(
            service_buttons,
            text="Запустить",
            command=self._start_winws_service,
            radius=15,
            bg_color=theme.ACCENT,
            fg_color=theme.ON_ACCENT,
            hover_bg=theme.ACCENT_HOVER,
            border_color=theme.ACCENT,
            width=96,
            height=32,
            font=ui_font(9, "bold"),
        ).pack(side=tk.LEFT, padx=(0, 6))

        RoundedButton(
            service_buttons,
            text="Остановить",
            command=self._stop_winws_service,
            radius=15,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=98,
            height=32,
            font=ui_font(9),
        ).pack(side=tk.LEFT, padx=(0, 6))

        RoundedButton(
            service_buttons,
            text="Перезапустить",
            command=self._restart_winws_service,
            radius=15,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=112,
            height=32,
            font=ui_font(9),
        ).pack(side=tk.LEFT, padx=(0, 6))

        RoundedButton(
            service_buttons,
            text="Сброс WinDivert",
            command=self._reset_windivert_service,
            radius=15,
            bg_color=theme.RED_SOFT,
            fg_color=theme.RED,
            hover_bg=theme.RED_SOFT_HOVER,
            border_color=theme.RED_SOFT_HOVER,
            width=124,
            height=32,
            font=ui_font(9),
        ).pack(side=tk.LEFT, padx=(0, 6))

        RoundedButton(
            service_buttons,
            text="Восстановить .bat",
            command=self._reset_base_bats,
            radius=15,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=132,
            height=32,
            font=ui_font(9),
        ).pack(side=tk.LEFT)

        # ---------------- Presets card ----------------
        presets_card = StyledCard(main_container, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=12)
        presets_card.pack(fill=tk.X, pady=(0, 8))
        self.presets_card = presets_card
        presets_frame = presets_card.inner_frame

        presets_title = tk.Frame(presets_frame, bg=theme.SURFACE)
        presets_title.pack(fill=tk.X)
        tk.Label(
            presets_title,
            text="Быстрый выбор",
            font=ui_font(11, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(side=tk.LEFT)
        tk.Label(
            presets_title,
            text="выберите сервисы — приложение само проверит и настроит",
            font=ui_font(8),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
        ).pack(side=tk.LEFT, padx=(10, 0))

        preset_row = tk.Frame(presets_frame, bg=theme.SURFACE)
        preset_row.pack(fill=tk.X, pady=(8, 0))

        presets_list = [
            ("Gemini", "Gemini"),
            ("Discord", "Discord"),
            ("YouTube", "YouTube"),
            ("Steam", "Steam"),
            ("Telegram", "Telegram"),
        ]

        for label, name in presets_list:
            RoundedButton(
                preset_row,
                text=label,
                command=lambda p=name: self._add_preset_hosts(p),
                radius=15,
                bg_color=theme.ACCENT_SOFT,
                fg_color=theme.ACCENT,
                hover_bg=theme.ACCENT_SOFT_HOVER,
                border_color=theme.ACCENT_SOFT_HOVER,
                width=94,
                height=30,
                font=ui_font(9, "bold"),
            ).pack(side=tk.LEFT, padx=(0, 6))

        RoundedButton(
            preset_row,
            text="Поиск по имени",
            command=self._search_app_by_name,
            radius=15,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=126,
            height=30,
            font=ui_font(9),
        ).pack(side=tk.LEFT, padx=(6, 6))

        RoundedButton(
            preset_row,
            text="Импорт",
            command=self._import_presets,
            radius=15,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=84,
            height=30,
            font=ui_font(9),
        ).pack(side=tk.LEFT, padx=(0, 6))

        RoundedButton(
            preset_row,
            text="Экспорт",
            command=self._export_presets,
            radius=15,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=86,
            height=30,
            font=ui_font(9),
        ).pack(side=tk.LEFT)

        # ---------------- Middle row ----------------
        middle_frame = tk.Frame(main_container, bg=theme.BG)
        middle_frame.pack(fill=tk.X, pady=(0, 8))

        hosts_card = StyledCard(middle_frame, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=12)
        hosts_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        hosts_frame = hosts_card.inner_frame

        tk.Label(
            hosts_frame,
            text="Целевые домены",
            font=ui_font(11, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(anchor=tk.W)
        tk.Label(
            hosts_frame,
            text="проверяются по HTTPS после запуска winws",
            font=ui_font(8),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
        ).pack(anchor=tk.W, pady=(1, 8))

        frame_host_list = tk.Frame(hosts_frame, bg=theme.SURFACE)
        frame_host_list.pack(fill=tk.BOTH, expand=True)

        self.hosts_listbox = tk.Listbox(
            frame_host_list,
            height=5,
            font=ui_font(9),
            selectmode=tk.SINGLE,
            exportselection=False,
            bg=theme.SURFACE,
            fg=theme.INK_SOFT,
            selectbackground=theme.ACCENT_SOFT,
            selectforeground=theme.SELECT_FG,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.ACCENT,
            activestyle="none",
            bd=0,
            relief=tk.FLAT,
        )
        self.hosts_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame_host_list, orient=tk.VERTICAL, command=self.hosts_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hosts_listbox.config(yscrollcommand=scrollbar.set)

        hosts_btn_frame = tk.Frame(hosts_frame, bg=theme.SURFACE)
        hosts_btn_frame.pack(fill=tk.X, pady=(8, 0))

        RoundedButton(
            hosts_btn_frame,
            text="Удалить",
            command=self._remove_selected_host,
            radius=14,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=80,
            height=28,
            font=ui_font(8),
        ).pack(side=tk.LEFT, padx=(0, 6))
        RoundedButton(
            hosts_btn_frame,
            text="Очистить",
            command=self._clear_hosts,
            radius=14,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=80,
            height=28,
            font=ui_font(8),
        ).pack(side=tk.LEFT)
        RoundedButton(
            hosts_btn_frame,
            text="Списки доменов",
            command=self._open_domain_lists,
            radius=14,
            bg_color=theme.ACCENT_SOFT,
            fg_color=theme.ACCENT,
            hover_bg=theme.ACCENT_SOFT_HOVER,
            border_color=theme.ACCENT_SOFT_HOVER,
            width=132,
            height=28,
            font=ui_font(8, "bold"),
        ).pack(side=tk.LEFT, padx=(6, 0))

        metrics_card = StyledCard(middle_frame, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=12)
        metrics_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        metrics_frame = metrics_card.inner_frame

        tk.Label(
            metrics_frame,
            text="Метрики подбора",
            font=ui_font(11, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(anchor=tk.W)
        tk.Label(
            metrics_frame,
            text="текущий прогресс и активный профиль",
            font=ui_font(8),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
        ).pack(anchor=tk.W, pady=(1, 10))

        tk.Label(
            metrics_frame,
            text="Проверка доменов: HTTPS с валидацией сертификата.\nОдин профиль — примерно 10–15 секунд.",
            font=ui_font(8),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
            justify=tk.LEFT,
        ).pack(side=tk.BOTTOM, anchor=tk.W, pady=(8, 0))

        self.metrics_panel = FuzzingMetricsFrame(metrics_frame, bg=theme.SURFACE)
        self.metrics_panel.pack(fill=tk.BOTH, expand=True)

        params_card = StyledCard(middle_frame, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=12)
        params_card.pack(side=tk.RIGHT, fill=tk.Y)
        self.params_card = params_card
        params_frame = params_card.inner_frame

        params_title_label = tk.Label(
            params_frame,
            text="Параметры",
            font=ui_font(11, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
            cursor="hand2",
        )
        params_title_label.grid(row=0, column=0, columnspan=2, sticky=tk.W)
        params_title_label.bind("<Button-1>", lambda e: self._open_interactive_params_window())

        tk.Label(
            params_frame,
            text="нажмите, чтобы открыть редактор",
            font=ui_font(8),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
            cursor="hand2",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))

        self.param_vars = {
            "tcp_split": tk.StringVar(value="1"),
            "tcp_seqovl": tk.StringVar(value="664"),
            "tcp_ttl": tk.StringVar(value="0"),
            "desync_mode": tk.StringVar(value="split"),
            "fooling_mode": tk.StringVar(value="none"),
            "udp_repeats": tk.StringVar(value="8"),
            "udp_cutoff": tk.StringVar(value="n4"),
            "any_protocol": tk.BooleanVar(value=False),
        }
        self.param_entries = {}

        param_names = [
            ("Split", "tcp_split"),
            ("SeqOvl", "tcp_seqovl"),
            ("TTL", "tcp_ttl"),
            ("Repeats", "udp_repeats"),
            ("Cutoff", "udp_cutoff"),
        ]

        for row, (title, key) in enumerate(param_names, start=2):
            tk.Label(
                params_frame,
                text=title,
                font=ui_font(9),
                bg=theme.SURFACE,
                fg=theme.MUTED,
            ).grid(row=row, column=0, sticky=tk.W, pady=1, padx=(0, 10))
            entry = tk.Entry(
                params_frame,
                textvariable=self.param_vars[key],
                width=8,
                font=(MONO_FAMILY, 9, "bold"),
                bg=theme.SURFACE_SOFT,
                fg=theme.INK,
                insertbackground=theme.ACCENT,
                relief=tk.FLAT,
                bd=0,
                highlightthickness=1,
                highlightbackground=theme.BORDER,
                highlightcolor=theme.ACCENT,
                justify=tk.CENTER,
            )
            entry.grid(row=row, column=1, sticky=tk.E, pady=1, ipady=2)
            self.param_entries[key] = entry

        self.require_100_var = tk.BooleanVar(value=False)
        strict_chk = tk.Checkbutton(
            params_frame,
            text="100% пробив",
            variable=self.require_100_var,
            font=ui_font(9),
            bg=theme.SURFACE,
            fg=theme.INK_SOFT,
            selectcolor=theme.SURFACE,
            activebackground=theme.SURFACE,
            activeforeground=theme.INK,
            highlightthickness=0,
            bd=0,
        )
        strict_chk.grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(6, 2))

        param_btn_box = tk.Frame(params_frame, bg=theme.SURFACE)
        param_btn_box.grid(row=8, column=0, columnspan=2, pady=(2, 0))

        RoundedButton(
            param_btn_box,
            text="В .bat",
            command=self._apply_custom_params,
            radius=13,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=88,
            height=28,
            font=ui_font(8),
        ).pack(side=tk.LEFT, padx=(0, 6))
        RoundedButton(
            param_btn_box,
            text="Из .bat",
            command=self._reset_params_to_baseline,
            radius=13,
            bg_color=theme.SURFACE,
            fg_color=theme.MUTED,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=88,
            height=28,
            font=ui_font(8),
        ).pack(side=tk.LEFT)

        # ---------------- Control bar ----------------
        ctrl_frame = tk.Frame(main_container, bg=theme.BG)
        ctrl_frame.pack(fill=tk.X, pady=(0, 8))

        self.start_btn = RoundedButton(
            ctrl_frame,
            text="Настроить и запустить",
            command=self._start_fuzzing,
            radius=21,
            bg_color=theme.ACCENT,
            fg_color=theme.ON_ACCENT,
            hover_bg=theme.ACCENT_HOVER,
            border_color=theme.ACCENT,
            height=42,
            font=ui_font(10, "bold"),
        )
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.stop_btn = RoundedButton(
            ctrl_frame,
            text="Остановить",
            command=self._stop_fuzzing,
            radius=21,
            bg_color=theme.RED_SOFT,
            fg_color=theme.RED,
            hover_bg=theme.RED_SOFT_HOVER,
            border_color=theme.RED_SOFT_HOVER,
            width=124,
            height=42,
            font=ui_font(10, "bold"),
        )
        self.stop_btn.set_state("disabled")
        self.stop_btn.pack(side=tk.RIGHT)

        self.single_test_btn = RoundedButton(
            ctrl_frame,
            text="Разовый тест",
            command=self._run_single_test,
            radius=21,
            bg_color=theme.ACCENT_SOFT,
            fg_color=theme.ACCENT,
            hover_bg=theme.ACCENT_SOFT_HOVER,
            border_color=theme.ACCENT_SOFT_HOVER,
            width=138,
            height=42,
            font=ui_font(10, "bold"),
        )
        self.single_test_btn.pack(side=tk.RIGHT, padx=(8, 8))

        mode_box = tk.Frame(ctrl_frame, bg=theme.BG)
        mode_box.pack(side=tk.RIGHT, padx=(8, 0))
        tk.Label(
            mode_box,
            text="Режим",
            font=ui_font(8),
            bg=theme.BG,
            fg=theme.MUTED,
        ).pack(side=tk.LEFT, padx=(0, 6))
        mode_combo = ttk.Combobox(
            mode_box,
            textvariable=self.search_mode_var,
            values=("Быстрый", "Стандартный", "Глубокий"),
            state="readonly",
            width=12,
            font=ui_font(9),
        )
        mode_combo.pack(side=tk.LEFT)
        mode_combo.bind("<<ComboboxSelected>>", lambda _event: self._persist_targets())

        # ---------------- Log card ----------------
        log_card = StyledCard(main_container, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=12)
        log_card.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        log_frame = log_card.inner_frame

        log_header = tk.Frame(log_frame, bg=theme.SURFACE)
        log_header.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            log_header,
            text="Журнал",
            font=ui_font(11, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(side=tk.LEFT)
        tk.Label(
            log_header,
            text="winws · curl · результаты проверок",
            font=ui_font(8),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
        ).pack(side=tk.LEFT, padx=(10, 0))

        frame_text_scroll = tk.Frame(log_frame, bg=theme.SURFACE_SOFT)
        frame_text_scroll.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            frame_text_scroll,
            bg=theme.SURFACE_SOFT,
            fg=theme.INK_SOFT,
            insertbackground=theme.ACCENT,
            font=MONO,
            wrap=tk.WORD,
            height=6,
            bd=0,
            padx=10,
            pady=8,
            highlightthickness=0,
            relief=tk.FLAT,
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)

        self.log_text.tag_config("plus", foreground=theme.GREEN)
        self.log_text.tag_config("star", foreground=theme.ACCENT)
        self.log_text.tag_config("warn", foreground=theme.AMBER)
        self.log_text.tag_config("minus", foreground=theme.RED)

        log_scroll = ttk.Scrollbar(frame_text_scroll, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

        # ---------------- Footer ----------------
        footer_container = tk.Frame(self.root, bg=theme.BG)
        footer_container.pack(side=tk.BOTTOM, fill=tk.X)

        gradient = GradientFooterCanvas(footer_container, height=3)
        gradient.pack(fill=tk.X)

        status_bar = tk.Frame(footer_container, bg=theme.BG, height=26)
        status_bar.pack(fill=tk.X, padx=22, pady=(5, 4))

        tk.Label(
            status_bar,
            textvariable=self.status_var,
            font=ui_font(9),
            bg=theme.BG,
            fg=theme.MUTED,
        ).pack(side=tk.LEFT)

        tk.Label(
            status_bar,
            text="zapret-discord-youtube",
            font=ui_font(8),
            bg=theme.BG,
            fg=theme.MUTED_LIGHT,
        ).pack(side=tk.RIGHT)

        self.update_btn = RoundedButton(
            status_bar,
            text="",
            command=self._trigger_update,
            radius=11,
            bg_color=theme.ACCENT_SOFT,
            fg_color=theme.ACCENT,
            hover_bg=theme.ACCENT_SOFT_HOVER,
            border_color=theme.ACCENT_SOFT_HOVER,
            width=176,
            height=22,
            font=ui_font(8, "bold"),
        )

    def _minimize_to_tray(self):
        self.tray_manager.minimize_to_tray()

    def _log_tray_backend(self) -> None:
        if HAS_PYSTRAY:
            self.log_message("[i] Трей: системный значок (pystray).")
        else:
            self.log_message(
                "[!] Трей: pystray не найден, используется компактный оверлей."
            )

    def _restore_saved_targets(self):
        settings = load_settings()
        saved_mode = settings.get("search_mode")
        if saved_mode in ("Быстрый", "Стандартный", "Глубокий"):
            self.search_mode_var.set(saved_mode)
        saved_strategy = settings.get("strategy")
        if isinstance(saved_strategy, str) and os.path.isfile(saved_strategy):
            self.bat_path_var.set(saved_strategy)
            self._update_params_display()
        for host in settings.get("targets", []):
            if isinstance(host, str) and host and host not in self.target_hosts:
                self.target_hosts.append(host)
                self.hosts_listbox.insert(tk.END, f" {host}")

    def _persist_targets(self) -> None:
        update_settings(
            targets=list(self.target_hosts)[:500],
            search_mode=self.search_mode_var.get(),
            strategy=self.bat_path_var.get(),
        )

    def _search_mode_key(self) -> str:
        return {
            "Быстрый": "quick",
            "Стандартный": "standard",
            "Глубокий": "deep",
        }.get(self.search_mode_var.get(), "standard")

    def _on_auto_finished(self, success: bool) -> None:
        if success and os.path.isfile(AUTO_STRATEGY):
            self.bat_path_var.set(AUTO_STRATEGY)
            self._update_params_display()
        self._persist_targets()
        self._fuzzing_started_at = 0.0
        if hasattr(self, "metrics_panel"):
            self.metrics_panel.stop_indeterminate()
        if success:
            self._service_running = FuzzerEngine.is_winws_alive()
            # winws может быть оставлен запущенным — даём пользователю возможность остановить его.
            self.start_btn.set_state("normal")
            self.stop_btn.set_state("normal" if self._service_running else "disabled")
        else:
            self._on_fuzzing_finished()

    def _toggle_theme(self):
        theme.toggle()
        self._rebuild_ui()

    def _toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        self._apply_advanced_visibility()

    def _apply_advanced_visibility(self):
        visible = self.advanced_visible
        self.advanced_btn.set_text("Скрыть" if visible else "Дополнительно")
        if visible:
            self.strategy_card.pack(fill=tk.X, pady=(0, 8), before=self.presets_card)
            self.params_card.pack(side=tk.RIGHT, fill=tk.Y)
            self.single_test_btn.pack(side=tk.RIGHT, padx=(8, 8))
        else:
            self.strategy_card.pack_forget()
            self.params_card.pack_forget()
            self.single_test_btn.pack_forget()

    def _capture_ui_state(self) -> dict:
        return {
            "targets": list(self.target_hosts),
            "params": {key: var.get() for key, var in self.param_vars.items()},
            "require_100": self.require_100_var.get(),
            "log": self.log_text.get("1.0", "end-1c"),
            "engine_status": self._last_engine_status,
        }

    def _rebuild_ui(self):
        state = self._capture_ui_state()
        for child in list(self.root.winfo_children()):
            child.destroy()

        self.root.configure(bg=theme.BG)
        self._setup_styles()
        self._build_ui()
        self._apply_advanced_visibility()
        self._refresh_update_button()
        self._restore_ui_state(state)
        self.root.update_idletasks()

    def _restore_ui_state(self, state: dict):
        self.hosts_listbox.delete(0, tk.END)
        for host in state["targets"]:
            self.hosts_listbox.insert(tk.END, f" {host}")

        engine_status = state.get("engine_status")
        if engine_status:
            self._apply_engine_status(engine_status)

        for key, value in state["params"].items():
            if key in self.param_vars:
                self.param_vars[key].set(value)

        self.require_100_var.set(bool(state.get("require_100", False)))

        log_text = state.get("log", "")
        if log_text:
            self.log_text.config(state=tk.NORMAL)
            for line in log_text.splitlines():
                tag = self._tag_for_message(line)
                if tag:
                    self.log_text.insert(tk.END, line + "\n", tag)
                else:
                    self.log_text.insert(tk.END, line + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)

        running = bool(self.engine and self.engine.is_running) or self._service_running
        self.start_btn.set_state("disabled" if running else "normal")
        self.stop_btn.set_state("normal" if running else "disabled")

    def _restore_from_tray(self):
        self.tray_manager.restore_from_tray()

    def _on_window_close(self):
        self._minimize_to_tray()

    def _exit_app(self):
        if self.engine:
            self.engine.stop()
        self.tray_manager.stop()
        self.root.destroy()

    def _validate_engine_assets(self):
        if os.name == "nt":
            try:
                import ctypes

                if not ctypes.windll.shell32.IsUserAnAdmin():
                    self.log_message(
                        "[!] Нет прав администратора: winws/winws2 не сможет "
                        "захватить трафик. Перезапустите приложение от имени администратора."
                    )
            except Exception:
                pass

        bat = self.bat_path_var.get()
        if os.path.isfile(bat):
            engine = FuzzerEngine(bat_path=bat).detect_engine_type()
            self.log_message(
                f"[i] Текущий движок: {engine} · {os.path.basename(bat)}"
            )
            winws2_ready = all(
                os.path.isfile(os.path.join(APP_DIR, relative))
                for relative in (
                    os.path.join("bin", "winws2.exe"),
                    os.path.join("lua", "zapret-lib.lua"),
                    os.path.join("lua", "zapret-antidpi.lua"),
                )
            )
            if engine == "winws1" and winws2_ready:
                self.log_message(
                    "[i] winws2 доступен: выберите winws2-батник в «Дополнительно», "
                    "чтобы работать через zapret2/Lua."
                )

        issues = FuzzerEngine.check_engine_assets(bat)
        if not issues:
            self.log_message("[+] Комплект движка zapret найден.")
            return

        self.log_message("[!] Не хватает файлов движка zapret рядом с приложением:")
        for issue in issues:
            self.log_message(f"      - {issue}")
        messagebox.showwarning(
            "Комплект движка zapret",
            "Не найдены файлы движка zapret:\n\n"
            + "\n".join(f"• {issue}" for issue in issues)
            + "\n\nСкопируйте bin/, lists/ и service.bat из архива zapret-discord-youtube "
            "в папку программы.",
        )

    def _start_winws_service(self):
        bat = self.bat_path_var.get()
        if not os.path.exists(bat):
            messagebox.showerror("Ошибка", f"Файл '{bat}' не найден!")
            return

        issues = FuzzerEngine.check_engine_assets(bat)
        if issues:
            messagebox.showerror(
                "Движок zapret не найден",
                "Не хватает файлов:\n\n" + "\n".join(f"• {item}" for item in issues),
            )
            return

        self.log_message(f"[*] Запуск winws.exe ({os.path.basename(bat)})...")
        self.status_var.set("Запуск winws.exe...")

        def task():
            alive = FuzzerEngine.start_winws(bat)
            self._run_on_ui(lambda: self._on_service_started(alive))

        threading.Thread(target=task, daemon=True).start()

    def _on_service_started(self, alive: bool):
        self._service_running = alive
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
        self._service_running = False
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

            def task():
                hosts = search_app_hosts_online(app_name)
                self._run_on_ui(lambda: self._on_app_hosts_found(app_name, hosts))

            threading.Thread(target=task, daemon=True).start()

    def _on_app_hosts_found(self, app_name: str, hosts: List[str]):
        if not hosts:
            self.log_message(f"[!] Не удалось найти известные домены для '{app_name}'.")
            self.status_var.set("Хосты не найдены")
            messagebox.showinfo("Результат поиска", f"Не удалось автоматически определить домены для '{app_name}'.")
            return

        added_count = 0
        for h in hosts:
            if h not in self.target_hosts:
                self.target_hosts.append(h)
                self.hosts_listbox.insert(tk.END, f" {h}")
                added_count += 1

        self.log_message(f"[+] Найдено {len(hosts)} хостов для '{app_name}' (добавлено новых: {added_count}).")
        self.status_var.set(f"Добавлено {added_count} хостов")
        self._persist_targets()

    def _open_history_dialog(self):
        HistoryDialog(self.root, on_select_callback=self._on_history_hosts_selected)

    def _open_domain_lists(self):
        bat = self.bat_path_var.get()
        if bat and os.path.exists(bat):
            lists_dir = os.path.join(os.path.dirname(os.path.abspath(bat)), "lists")
        else:
            lists_dir = LISTS_DIR

        def on_save(counts: dict) -> None:
            self.log_message(
                f"[+] Личные списки сохранены: обход {counts.get('include', 0)}, "
                f"исключения {counts.get('exclude', 0)}."
            )
            self.status_var.set("Списки доменов сохранены")

        DomainListsDialog(self.root, lists_dir, on_save_callback=on_save)

    def _on_history_hosts_selected(self, app_name: str, hosts: List[str]):
        added_count = 0
        for h in hosts:
            if h not in self.target_hosts:
                self.target_hosts.append(h)
                self.hosts_listbox.insert(tk.END, f" {h}")
                added_count += 1
        self.log_message(f"[+] Загружено {len(hosts)} хостов из истории для '{app_name}' (новых: {added_count}).")
        self.status_var.set(f"Загружено {added_count} хостов")
        self._persist_targets()

    def _reset_base_bats(self):
        msg_prompt = "Скачать чистые оригинальные .bat файлы из папки 'base bats' репозитория GitHub?\n\nВсе имеющиеся .bat файлы в папке приложения будут перезаписаны исходными версиями."
        if not messagebox.askyesno("Восстановление .bat файлов", msg_prompt):
            return

        self.log_message("[*] Загрузка чистых исходных .bat файлов из GitHub ('base bats')...")
        self.status_var.set("Загрузка .bat файлов...")

        def task():
            try:
                if self.engine:
                    self.engine.stop()
                FuzzerEngine.stop_winws()
                success, msg, files = reset_base_bats_from_github()
                def report():
                    if success:
                        file_list_str = ", ".join(files[:6]) + ("..." if len(files) > 6 else "")
                        self.log_message(f"[+] {msg}\n    Обновлено: {file_list_str}")
                        self.status_var.set("Чистые .bat файлы восстановлены")
                        messagebox.showinfo(
                            "Успех",
                            f"Успешно восстановлено {len(files)} базовых .bat файлов!\n\n"
                            f"Файлы перезаписаны в {APP_DIR}.",
                        )
                    else:
                        self.log_message(f"[!] {msg}")
                        self.status_var.set("Ошибка восстановления .bat")
                        messagebox.showerror("Ошибка", msg)
                self._run_on_ui(report)
            except Exception as e:
                def report_error():
                    self.log_message(f"[!] Ошибка восстановления .bat: {e}")
                    self.status_var.set("Ошибка восстановления .bat")
                    messagebox.showerror("Ошибка", str(e))
                self._run_on_ui(report_error)

        threading.Thread(target=task, daemon=True).start()

    def _is_installed(self) -> bool:
        return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())

    def _refresh_update_button(self) -> None:
        if not hasattr(self, "update_btn"):
            return
        if self._update_info is not None:
            self.update_btn.set_text(f"Обновить до v{self._update_info.version}")
            self.update_btn.pack(side=tk.RIGHT, padx=(0, 8))
        else:
            self.update_btn.pack_forget()

    def _check_updates_silently(self) -> None:
        if not self._is_installed():
            return

        def worker():
            try:
                info = check_for_update(__version__)
            except UpdateError as error:
                self.log_message(f"[i] Проверка обновлений: {error}")
                return
            except Exception:
                return
            if info is not None:
                self._run_on_ui(lambda: self._show_update_available(info))

        threading.Thread(target=worker, daemon=True).start()

    def _show_update_available(self, info: UpdateInfo) -> None:
        self._update_info = info
        self._refresh_update_button()
        self.log_message(
            f"[i] Доступно обновление: v{info.version} (установлена v{__version__})."
        )
        self.status_var.set(f"Доступно обновление v{info.version}")

    def _update_error(self, message: str) -> None:
        self.log_message(f"[!] Обновление: {message}")
        self.status_var.set("Обновление не выполнено")
        messagebox.showerror("Обновление", message)

    def _trigger_update(self):
        if not self._is_installed():
            messagebox.showinfo(
                "Обновление",
                "Автообновление доступно только для установленной версии.\n"
                "Скачайте новый установщик со страницы релизов GitHub.",
            )
            return

        if not messagebox.askyesno(
            "Обновление",
            f"Проверить обновления?\n\nТекущая версия: v{__version__}",
        ):
            return

        self.status_var.set("Проверка обновлений...")

        def worker():
            try:
                info = check_for_update(__version__)
            except UpdateError as error:
                message = str(error)
                self._run_on_ui(lambda: self._update_error(message))
                return
            except Exception as error:
                message = str(error)
                self._run_on_ui(lambda: self._update_error(message))
                return
            self._run_on_ui(lambda: self._on_update_checked(info))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_checked(self, info: Optional[UpdateInfo]) -> None:
        if info is None:
            self.log_message(f"[i] Обновлений нет. Установлена v{__version__}.")
            self.status_var.set("Обновлений нет")
            messagebox.showinfo(
                "Обновление",
                f"Установлена последняя версия: v{__version__}.",
            )
            return

        self._show_update_available(info)
        if not messagebox.askyesno(
            "Обновление",
            f"Доступна версия v{info.version}.\n\n"
            "Скачать и установить сейчас?\n"
            "Приложение будет закрыто, обновление установится и запустится заново.",
        ):
            return
        self._start_update_download(info)

    def _start_update_download(self, info: UpdateInfo) -> None:
        self.log_message(f"[*] Скачивание установщика v{info.version}...")
        self.status_var.set(f"Скачивание v{info.version}...")
        last_bucket = [-1]

        def progress(downloaded: int, total: int) -> None:
            percent = int(downloaded * 100 / total) if total else 0
            bucket = percent // 10
            if bucket != last_bucket[0]:
                last_bucket[0] = bucket
                self.log_message(f"    установщик: {percent}%")

        def worker():
            try:
                path = download_installer(info, progress)
            except UpdateError as error:
                message = str(error)
                self._run_on_ui(lambda: self._update_error(message))
                return
            except Exception as error:
                message = str(error)
                self._run_on_ui(lambda: self._update_error(message))
                return
            self._run_on_ui(lambda: self._finish_update(path))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_update(self, installer_path: str) -> None:
        self.log_message("[*] Останавливаю движок и запускаю установщик...")
        try:
            if self.engine:
                self.engine.stop()
            FuzzerEngine.stop_winws()
        except Exception as error:
            self.log_message(f"[!] Не удалось остановить движок: {error}")
        self._service_running = False

        try:
            ok = launch_update(installer_path)
        except Exception as error:
            self._update_error(f"Не удалось запустить установщик обновления: {error}")
            return

        if not ok:
            self._update_error("Не удалось запустить установщик обновления.")
            return

        self.log_message("[+] Установщик запущен. Приложение перезапустится после обновления.")
        self.status_var.set("Установка обновления...")
        self.root.after(600, self._exit_for_update)

    def _exit_for_update(self) -> None:
        """Завершает процесс, чтобы установщик мог заменить файлы."""
        try:
            self.tray_manager.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        # Гарантированный выход: update-bat ждёт исчезновения именно этого PID.
        os._exit(0)

    def _browse_bat(self):
        file_selected = filedialog.askopenfilename(
            title="Выберите батник стратегии Zapret",
            filetypes=[("BAT Files", "*.bat"), ("All Files", "*.*")]
        )
        if file_selected:
            self.bat_path_var.set(file_selected)
            self._update_params_display()
            self._persist_targets()

    def _add_preset_hosts(self, preset_name: str):
        self.log_message(f"[*] Загрузка хостов и IP для '{preset_name}'...")
        self.status_var.set(f"Поиск доменов для {preset_name}...")

        def worker():
            targets = fetch_preset_targets(preset_name, resolve_ips=True)
            self._run_on_ui(lambda: self._on_preset_loaded(preset_name, targets))

        threading.Thread(target=worker, daemon=True).start()

    def _on_preset_loaded(self, preset_name: str, targets: List[str]):
        added_count = 0
        for t in targets:
            if t not in self.target_hosts:
                self.target_hosts.append(t)
                self.hosts_listbox.insert(tk.END, f" {t}")
                added_count += 1
        self.log_message(f"[+] Пресет '{preset_name}': загружено {len(targets)} доменов/IP (добавлено новых: {added_count}).")
        self.status_var.set(f"Пресет {preset_name} добавлен")
        self._persist_targets()

    def _remove_selected_host(self):
        selected_indices = self.hosts_listbox.curselection()
        if selected_indices:
            idx = selected_indices[0]
            val = self.hosts_listbox.get(idx).strip()
            self.hosts_listbox.delete(idx)
            if val in self.target_hosts:
                self.target_hosts.remove(val)
            self.log_message(f"[-] Удален хост: {val}")
            self._persist_targets()

    def _clear_hosts(self):
        self.hosts_listbox.delete(0, tk.END)
        self.target_hosts.clear()
        self.log_message("[-] Список целевых доменов полностью очищен.")
        self._persist_targets()

    def _import_presets(self):
        file_path = filedialog.askopenfilename(
            title="Импортировать список доменов",
            filetypes=[("JSON Files", "*.json"), ("TXT Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            imported = import_presets_from_file(file_path)
            if not imported:
                messagebox.showwarning("Импорт", "В выбранном файле не найдено корректных доменов.")
                return

            added_count = 0
            for item in imported:
                if item not in self.target_hosts:
                    self.target_hosts.append(item)
                    self.hosts_listbox.insert(tk.END, f" {item}")
                    added_count += 1
            self.log_message(
                f"[+] Из файла '{os.path.basename(file_path)}' импортировано "
                f"{len(imported)} доменов (новых: {added_count})."
            )
            self.status_var.set("Импорт завершён")
            self._persist_targets()

    def _export_presets(self):
        if not self.target_hosts:
            messagebox.showwarning("Экспорт", "Список доменов пуст! Нечего экспортировать.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Сохранить целевые домены в файл",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("TXT Files", "*.txt")]
        )
        if file_path:
            success = export_presets_to_file(file_path, self.target_hosts)
            if success:
                self.log_message(f"[+] Список из {len(self.target_hosts)} доменов экспортирован в '{os.path.basename(file_path)}'.")
                self.status_var.set("Экспорт завершен")
            else:
                messagebox.showerror("Экспорт", "Ошибка сохранения файла.")

    def _run_single_test(self):
        if not self.target_hosts:
            messagebox.showwarning("Внимание", "Список целевых доменов пуст! Добавьте хотя бы один пресет или домен.")
            return

        bat = self.bat_path_var.get()
        issues = FuzzerEngine.check_engine_assets(bat)
        if issues:
            messagebox.showerror(
                "Движок zapret не найден",
                "Не хватает файлов:\n\n" + "\n".join(f"• {item}" for item in issues),
            )
            return

        params = self._get_current_params_from_ui()
        if self._winws2_mode or FuzzerEngine(bat_path=bat).detect_engine_type() == "winws2":
            messagebox.showinfo(
                "Lua-стратегия winws2",
                "Для winws2 параметры задаются Lua-инстансами.\n"
                "Используйте кнопку «Настроить и запустить» — приложение подберёт их само.",
            )
            return
        try:
            validate_params(params)
        except ValueError as error:
            messagebox.showerror("Некорректные параметры", str(error))
            return

        self.log_message(f"[*] Запуск разового теста ({params.describe()})...")

        self.start_btn.set_state("disabled")
        self.stop_btn.set_state("normal")
        self._fuzzing_started_at = time.monotonic()
        self._metrics_step = 0
        self._metrics_total = 0
        self._metrics_passed = 0
        self._metrics_hosts = 0
        if hasattr(self, "metrics_panel"):
            self.metrics_panel.reset_metrics()
            self.metrics_panel.start_indeterminate("Проверка параметров...")

        def worker():
            try:
                self.engine = FuzzerEngine(
                    bat_path=bat,
                    log_callback=self.log_message,
                    status_callback=self._on_engine_status,
                    require_100_percent=self.require_100_var.get()
                )
                success = self.engine.run_single_test(params, list(self.target_hosts))
                self._run_on_ui(lambda: self._on_single_test_success(success, params))
            except Exception as error:
                message = f"[!] Ошибка разового теста: {error}"
                self._run_on_ui(lambda: self.log_message(message))
            finally:
                self._run_on_ui(self._on_fuzzing_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _on_single_test_success(self, success: bool, params: WinwsParams):
        if success:
            self.log_message("\n[+] РАЗОВЫЙ ТЕСТ ПРОШЁЛ УСПЕШНО!")
            self.status_var.set("Разовый тест успешно прошёл!")
        else:
            self.log_message("\n[-] Разовый тест не прошёл требуемый порог доступности.")
            self.status_var.set("Разовый тест не прошёл порог")

    def _get_current_params_from_ui(self) -> WinwsParams:
        def parse_int(val: str, default: int) -> int:
            try:
                return int(val.strip())
            except ValueError:
                return default

        return WinwsParams(
            tcp_split=parse_int(self.param_vars["tcp_split"].get(), 1),
            tcp_seqovl=parse_int(self.param_vars["tcp_seqovl"].get(), 664),
            tcp_ttl=parse_int(self.param_vars["tcp_ttl"].get(), 0),
            desync_mode=self.param_vars["desync_mode"].get(),
            fooling_mode=self.param_vars["fooling_mode"].get(),
            udp_repeats=parse_int(self.param_vars["udp_repeats"].get(), 8),
            udp_cutoff=self.param_vars["udp_cutoff"].get().strip(),
            any_protocol=self.param_vars["any_protocol"].get()
        )

    def _update_params_display(self):
        bat = self.bat_path_var.get()
        if os.path.exists(bat):
            try:
                temp_engine = FuzzerEngine(bat_path=bat)
                engine = temp_engine.detect_engine_type()
                self.engine_var.set(
                    "движок: winws2 (Lua)" if engine == "winws2" else "движок: winws1"
                )
                if engine == "winws2":
                    self._winws2_mode = True
                    for entry in self.param_entries.values():
                        entry.config(state="disabled")
                    return

                self._winws2_mode = False
                for entry in self.param_entries.values():
                    entry.config(state="normal")
                baseline = temp_engine.extract_baseline()
                self.param_vars["tcp_split"].set(str(baseline.tcp_split))
                self.param_vars["tcp_seqovl"].set(str(baseline.tcp_seqovl))
                self.param_vars["tcp_ttl"].set(str(baseline.tcp_ttl))
                self.param_vars["desync_mode"].set(baseline.desync_mode)
                self.param_vars["fooling_mode"].set(baseline.fooling_mode)
                self.param_vars["udp_repeats"].set(str(baseline.udp_repeats))
                self.param_vars["udp_cutoff"].set(baseline.udp_cutoff)
                self.param_vars["any_protocol"].set(baseline.any_protocol)
            except Exception:
                pass
        else:
            self.engine_var.set("движок: —")

    def _apply_custom_params(self):
        bat = self.bat_path_var.get()
        if not os.path.exists(bat):
            messagebox.showerror("Ошибка", f"Файл '{bat}' не найден!")
            return

        if self._winws2_mode or FuzzerEngine(bat_path=bat).detect_engine_type() == "winws2":
            messagebox.showinfo(
                "Lua-стратегия winws2",
                "Ручная запись параметров доступна только для winws1.",
            )
            return

        params = self._get_current_params_from_ui()
        try:
            validate_params(params)
        except ValueError as error:
            messagebox.showerror("Некорректные параметры", str(error))
            return

        try:
            temp_engine = FuzzerEngine(bat_path=bat, log_callback=self.log_message)
            temp_engine.patch_original_bat(params)
            self.log_message(f"[+] Параметры из UI записаны в '{os.path.basename(bat)}'.")
            self.status_var.set("Параметры сохранены в .bat")
            messagebox.showinfo("Сохранено", f"Параметры успешно обновлены в файле '{os.path.basename(bat)}'!")
        except Exception as e:
            self.log_message(f"[!] Ошибка сохранения параметров: {e}")
            messagebox.showerror("Ошибка", str(e))

    def _reset_params_to_baseline(self):
        self._update_params_display()
        self.log_message("[*] Значения полей параметров сброшены к текущим из .bat файла.")
        self.status_var.set("Параметры сброшены из .bat")

    def _open_interactive_params_window(self):
        cur_p = self._get_current_params_from_ui()

        def apply_cb(p: WinwsParams):
            self.param_vars["tcp_split"].set(str(p.tcp_split))
            self.param_vars["tcp_seqovl"].set(str(p.tcp_seqovl))
            self.param_vars["tcp_ttl"].set(str(p.tcp_ttl))
            self.param_vars["desync_mode"].set(p.desync_mode)
            self.param_vars["fooling_mode"].set(p.fooling_mode)
            self.param_vars["udp_repeats"].set(str(p.udp_repeats))
            self.param_vars["udp_cutoff"].set(p.udp_cutoff)
            self.param_vars["any_protocol"].set(p.any_protocol)
            self.log_message(f"[+] Параметры обновлены вручную: desync={p.desync_mode}, split={p.tcp_split}, seqovl={p.tcp_seqovl}")

        def test_cb(p: WinwsParams):
            apply_cb(p)
            self._run_single_test()

        InteractiveParamsWindow(self.root, cur_p, on_apply_callback=apply_cb, on_test_callback=test_cb)

    def _start_fuzzing(self):
        if not self.target_hosts:
            messagebox.showwarning("Внимание", "Список целевых доменов пуст! Добавьте пресеты или введите сервисы.")
            return

        bat = self.bat_path_var.get()
        if not os.path.exists(bat):
            messagebox.showerror("Ошибка", f"Файл стратегии '{bat}' не найден!")
            return

        issues = FuzzerEngine.check_engine_assets(bat)
        if issues:
            messagebox.showerror(
                "Движок zapret не найден",
                "Не хватает файлов:\n\n" + "\n".join(f"• {item}" for item in issues),
            )
            return

        self.start_btn.set_state("disabled")
        self.stop_btn.set_state("normal")
        self.status_var.set("Диагностика и настройка...")
        self._fuzzing_started_at = time.monotonic()
        self._metrics_step = 0
        self._metrics_total = 0
        self._metrics_passed = 0
        self._metrics_hosts = 0
        self._persist_targets()

        if hasattr(self, 'metrics_panel'):
            self.metrics_panel.reset_metrics()
            self.metrics_panel.start_indeterminate("Диагностика сети...")

        def worker():
            success = False
            try:
                self.engine = FuzzerEngine(
                    bat_path=bat,
                    log_callback=self.log_message,
                    status_callback=self._on_engine_status,
                    require_100_percent=self.require_100_var.get()
                )
                self.engine.search_mode = self._search_mode_key()
                success = self.engine.run_fuzzing(list(self.target_hosts))
            except Exception as e:
                self.log_message(f"[!] Ошибка автонастройки: {e}")
            finally:
                self._run_on_ui(lambda: self._on_auto_finished(success))

        threading.Thread(target=worker, daemon=True).start()

    def _stop_fuzzing(self):
        was_running = bool(self.engine and self.engine.is_running)
        if self.engine:
            self.engine.stop()
        if was_running:
            self.log_message("[!] Пользователь запросил остановку подбора...")
            self.status_var.set("Останавливаем подбор...")
            return
        FuzzerEngine.stop_winws()
        self._service_running = False
        self.log_message("[-] winws остановлен.")
        self.status_var.set("winws остановлен")

    def _on_fuzzing_finished(self):
        self._fuzzing_started_at = 0.0
        if hasattr(self, "metrics_panel"):
            self.metrics_panel.stop_indeterminate()
        self.start_btn.set_state("normal")
        self.stop_btn.set_state("disabled")

    def _on_engine_status(self, status_dict: dict):
        """Вызывается из рабочего потока — Tk обновляем в главном."""
        self.status_queue.put(status_dict)

    def _apply_engine_status(self, status: dict):
        if "message" in status:
            self.status_var.set(status["message"])

        params = status.get("params")
        if params:
            self.param_vars["tcp_split"].set(str(params.tcp_split))
            self.param_vars["tcp_seqovl"].set(str(params.tcp_seqovl))
            self.param_vars["tcp_ttl"].set(str(params.tcp_ttl))
            self.param_vars["desync_mode"].set(params.desync_mode)
            self.param_vars["fooling_mode"].set(params.fooling_mode)
            self.param_vars["udp_repeats"].set(str(params.udp_repeats))
            self.param_vars["udp_cutoff"].set(params.udp_cutoff)
            self.param_vars["any_protocol"].set(params.any_protocol)

        if hasattr(self, "metrics_panel"):
            state = str(status.get("state", ""))
            if state == "DIAGNOSTICS":
                self.metrics_panel.start_indeterminate(
                    str(status.get("message") or "Диагностика сети...")
                )
            elif state in ("SUCCESS", "FAILED", "ERROR", "STOPPED"):
                self.metrics_panel.stop_indeterminate()
            elif "step" in status or "total_steps" in status:
                if "step" in status:
                    self._metrics_step = int(status.get("step", 0) or 0)
                if "total_steps" in status:
                    self._metrics_total = int(status.get("total_steps", 0) or 0)
                if "passed" in status:
                    self._metrics_passed = int(status.get("passed", 0) or 0)
                if "total_hosts" in status:
                    self._metrics_hosts = int(status.get("total_hosts", 0) or 0)
                passed = self._metrics_passed
                total_hosts = self._metrics_hosts
                if self._fuzzing_started_at:
                    elapsed = int(time.monotonic() - self._fuzzing_started_at)
                else:
                    elapsed = int(status.get("elapsed_sec", 0) or 0)
                strategy = ""
                if params:
                    strategy = (
                        f"{params.desync_mode} | split {params.tcp_split} | "
                        f"seqovl {params.tcp_seqovl} | ttl {params.tcp_ttl}"
                    )
                self.metrics_panel.update_metrics(
                    self._metrics_step, self._metrics_total, passed, total_hosts, strategy, elapsed
                )

        self._last_engine_status = status

    def log_message(self, text: str):
        self.log_queue.put(text)

    def _run_on_ui(self, callback):
        """Планирует выполнение callback в главном потоке Tk."""
        self.ui_queue.put(callback)

    def _start_log_listener(self):
        def check_queue():
            while not self.ui_queue.empty():
                callback = self.ui_queue.get_nowait()
                try:
                    callback()
                except Exception as error:
                    self.log_message(f"[!] Ошибка UI-колбэка: {error}")
            while not self.status_queue.empty():
                self._apply_engine_status(self.status_queue.get_nowait())
            while not self.log_queue.empty():
                self._append_log_with_tags(self.log_queue.get_nowait())
            self.root.after(80, check_queue)

        self.root.after(80, check_queue)

    @staticmethod
    def _tag_for_message(msg: str):
        if "[+]" in msg or "[O]" in msg or "УСПЕХ" in msg:
            return "plus"
        if "[-]" in msg or "[X]" in msg or "ОШИБКА" in msg:
            return "minus"
        if "[~]" in msg or "[*]" in msg:
            return "warn"
        if "[i]" in msg:
            return "star"
        return None

    def _append_log_with_tags(self, msg: str):
        self.log_text.config(state=tk.NORMAL)
        tag = self._tag_for_message(msg)
        if tag:
            self.log_text.insert(tk.END, msg + "\n", tag)
        else:
            self.log_text.insert(tk.END, msg + "\n")

        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _tick_elapsed(self):
        if self._fuzzing_started_at and hasattr(self, "metrics_panel"):
            self.metrics_panel.set_elapsed(
                int(time.monotonic() - self._fuzzing_started_at)
            )
        self.root.after(500, self._tick_elapsed)

    def _check_winws_periodically(self):
        if not self._winws_probe_active:
            self._winws_probe_active = True

            def probe():
                alive = FuzzerEngine.is_winws_alive()
                self._run_on_ui(lambda: self._apply_winws_status(alive))

            threading.Thread(target=probe, daemon=True).start()

        self.root.after(2500, self._check_winws_periodically)

    def _apply_winws_status(self, alive: bool):
        self._winws_probe_active = False
        self._service_running = alive
        if alive:
            self.winws_status_var.set("Запущен")
            if hasattr(self, 'winws_status_lbl'):
                self.winws_status_lbl.config(fg=theme.GREEN)
        else:
            self.winws_status_var.set("Остановлен")
            if hasattr(self, 'winws_status_lbl'):
                self.winws_status_lbl.config(fg=theme.RED)

