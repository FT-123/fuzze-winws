import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import queue
import os
import sys
from typing import List, Optional

from presets import fetch_preset_targets, search_app_hosts_online, export_presets_to_file, import_presets_from_file
from fuzzer_engine import FuzzerEngine, WinwsParams
from updater import check_and_download_github_exe, reset_base_bats_from_github

from ui_components import RoundedButton, StyledCard, GradientFooterCanvas
from analytics import FuzzingAnalyticsCanvas
from tray import TrayManager
from history_dialog import HistoryDialog
from params_dialog import InteractiveParamsDialog


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
        self.root.after(200, lambda: self._update_params_display(force_reload=True))

    def _get_current_params_from_ui(self) -> Optional[WinwsParams]:
        if not hasattr(self, "param_vars"):
            return None
        try:
            return WinwsParams(
                tcp_split=int(self.param_vars["tcp_split"].get().strip()),
                tcp_seqovl=int(self.param_vars["tcp_seqovl"].get().strip()),
                tcp_ttl=int(self.param_vars["tcp_ttl"].get().strip()),
                udp_repeats=int(self.param_vars["udp_repeats"].get().strip()),
                udp_cutoff=str(self.param_vars["udp_cutoff"].get()).strip()
            )
        except (ValueError, KeyError):
            return None

    def _update_params_display(self, params: Optional[WinwsParams] = None, force_reload: bool = False):
        if params is None:
            if not force_reload:
                existing = self._get_current_params_from_ui()
                if existing is not None:
                    return
            try:
                temp_engine = FuzzerEngine(bat_path=self.bat_path_var.get())
                params = temp_engine.extract_baseline()
            except Exception:
                return

        if params and hasattr(self, "param_vars"):
            self.param_vars["tcp_split"].set(str(params.tcp_split))
            self.param_vars["tcp_seqovl"].set(str(params.tcp_seqovl))
            self.param_vars["tcp_ttl"].set(str(params.tcp_ttl))
            self.param_vars["udp_repeats"].set(str(params.udp_repeats))
            self.param_vars["udp_cutoff"].set(str(params.udp_cutoff))

    def _apply_custom_params(self):
        params = self._get_current_params_from_ui()
        if params is None:
            messagebox.showerror("Ошибка", "Некорректные значения параметров! Проверьте введенные числа.")
            return

        bat_file = self.bat_path_var.get()
        if not os.path.exists(bat_file):
            messagebox.showerror("Ошибка", f"Файл '{bat_file}' не найден!")
            return

        try:
            temp_engine = FuzzerEngine(bat_path=bat_file)
            temp_engine.patch_original_bat(params)
            messagebox.showinfo("Успех", f"Параметры успешно сохранены в '{os.path.basename(bat_file)}'!")
            self.log_message(f"[+] Пользовательские параметры применены к '{os.path.basename(bat_file)}': {params}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось обновить .bat файл: {e}")

    def _reset_params_to_baseline(self):
        self._update_params_display(force_reload=True)
        self.log_message("[-] Параметры сброшены к значениям из .bat файла.")

    def _open_interactive_params_window(self):
        InteractiveParamsDialog(self.root, self.param_vars, on_run_test_cb=self._run_single_test)

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
        header_card = StyledCard(main_container, card_bg="#0d101d", border_color="#22273d", padding=4)
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
        sec1_card = StyledCard(main_container, card_bg="#111422", border_color="#22273d", padding=5)
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
        RoundedButton(svc_frame, text="♻️ Восстановить .bat", command=self._reset_base_bats, radius=6, bg_color="#3a86ff", hover_bg="#2563eb", width=125, height=22).pack(side=tk.LEFT, padx=2)

        # --- Section 2: Presets Card ---
        sec2_card = StyledCard(main_container, card_bg="#111422", border_color="#22273d", padding=5)
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

        import_btn = RoundedButton(
            preset_btn_container,
            text="📥 Импорт",
            command=self._import_presets,
            radius=6,
            bg_color="#181c2e",
            hover_bg="#3a86ff",
            width=80,
            height=22
        )
        import_btn.grid(row=0, column=len(presets_list)+1, padx=2, pady=1)

        export_btn = RoundedButton(
            preset_btn_container,
            text="📤 Экспорт",
            command=self._export_presets,
            radius=6,
            bg_color="#181c2e",
            hover_bg="#3a86ff",
            width=80,
            height=22
        )
        export_btn.grid(row=0, column=len(presets_list)+2, padx=2, pady=1)

        # --- Section 3: Middle Split (Hosts + Analytics + Parameters) ---
        middle_frame = tk.Frame(main_container, bg="#08090f")
        middle_frame.pack(fill=tk.X, expand=False, pady=(0, 4))

        hosts_card = StyledCard(middle_frame, card_bg="#111422", border_color="#22273d", padding=5)
        hosts_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))

        hosts_frame = hosts_card.inner_frame
        tk.Label(hosts_frame, text="🌐 Целевые домены", font=("Segoe UI", 9, "bold"), bg="#111422", fg="#00f5d4").pack(anchor=tk.W, pady=(0, 2))

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

        RoundedButton(hosts_btn_frame, text="🗑️ Удалить", command=self._remove_selected_host, radius=6, width=75, height=20).pack(side=tk.LEFT, padx=1)
        RoundedButton(hosts_btn_frame, text="🧹 Очистить", command=self._clear_hosts, radius=6, width=75, height=20).pack(side=tk.LEFT, padx=1)

        analytics_card = StyledCard(middle_frame, card_bg="#111422", border_color="#22273d", padding=5)
        analytics_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2)

        analytics_frame = analytics_card.inner_frame
        tk.Label(analytics_frame, text="📈 Аналитика пробива", font=("Segoe UI", 9, "bold"), bg="#111422", fg="#00f5d4").pack(anchor=tk.W, pady=(0, 2))

        self.analytics_chart = FuzzingAnalyticsCanvas(analytics_frame, bg="#0d101d", height=70)
        self.analytics_chart.pack(fill=tk.BOTH, expand=True)

        params_card = StyledCard(middle_frame, card_bg="#111422", border_color="#22273d", padding=5)
        params_card.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 0))

        params_frame = params_card.inner_frame
        params_title_label = tk.Label(
            params_frame,
            text="🎛️ Параметры ⚙️",
            font=("Segoe UI", 9, "bold"),
            bg="#111422",
            fg="#00f5d4",
            cursor="hand2"
        )
        params_title_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 2))
        params_title_label.bind("<Button-1>", lambda e: self._open_interactive_params_window())

        self.param_vars = {
            "tcp_split": tk.StringVar(value="1"),
            "tcp_seqovl": tk.StringVar(value="664"),
            "tcp_ttl": tk.StringVar(value="0"),
            "udp_repeats": tk.StringVar(value="8"),
            "udp_cutoff": tk.StringVar(value="n4")
        }
        self.param_entries = {}

        param_names = [
            ("TCP Split:", "tcp_split"),
            ("TCP SeqOvl:", "tcp_seqovl"),
            ("TCP TTL:", "tcp_ttl"),
            ("UDP Repeats:", "udp_repeats"),
            ("UDP Cutoff:", "udp_cutoff")
        ]

        for row, (title, key) in enumerate(param_names, start=1):
            tk.Label(params_frame, text=title, font=("Segoe UI", 8, "bold"), bg="#111422", fg="#8f9bb3").grid(row=row, column=0, sticky=tk.W, pady=1, padx=(0, 4))
            entry = tk.Entry(
                params_frame,
                textvariable=self.param_vars[key],
                width=6,
                font=("Consolas", 8, "bold"),
                bg="#181c2e",
                fg="#00f5d4",
                insertbackground="#00f5d4",
                bd=0,
                highlightthickness=1,
                highlightbackground="#22273d",
                highlightcolor="#00f5d4",
                justify=tk.CENTER
            )
            entry.grid(row=row, column=1, sticky=tk.E, pady=1)
            self.param_entries[key] = entry

        self.require_100_var = tk.BooleanVar(value=False)
        strict_chk = tk.Checkbutton(
            params_frame,
            text="🎯 100% пробив",
            variable=self.require_100_var,
            font=("Segoe UI", 8, "bold"),
            bg="#111422",
            fg="#00f5d4",
            selectcolor="#181c2e",
            activebackground="#111422",
            activeforeground="#00f5d4",
            bd=0,
            highlightthickness=0
        )
        strict_chk.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(3, 1))

        single_test_btn = RoundedButton(
            params_frame,
            text="⚡ Разовый тест",
            command=self._run_single_test,
            radius=6,
            bg_color="#7000ff",
            fg_color="#ffffff",
            hover_bg="#8a2be2",
            font=("Segoe UI", 8, "bold"),
            width=115,
            height=20
        )
        single_test_btn.grid(row=7, column=0, columnspan=2, pady=(2, 1))

        btn_sub_frame = tk.Frame(params_frame, bg="#111422")
        btn_sub_frame.grid(row=8, column=0, columnspan=2, pady=(1, 0))

        apply_btn = RoundedButton(
            btn_sub_frame,
            text="💾 В .bat",
            command=self._apply_custom_params,
            radius=5,
            bg_color="#181c2e",
            fg_color="#00f5d4",
            hover_bg="#22273d",
            font=("Segoe UI", 7, "bold"),
            width=55,
            height=18
        )
        apply_btn.pack(side=tk.LEFT, padx=1)

        reset_btn = RoundedButton(
            btn_sub_frame,
            text="🔄 Из .bat",
            command=self._reset_params_to_baseline,
            radius=5,
            bg_color="#181c2e",
            fg_color="#8f9bb3",
            hover_bg="#22273d",
            font=("Segoe UI", 7, "bold"),
            width=55,
            height=18
        )
        reset_btn.pack(side=tk.LEFT, padx=1)

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
        log_card = StyledCard(main_container, card_bg="#05060a", border_color="#22273d", padding=5)
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

        status_card = StyledCard(footer_container, card_bg="#111422", border_color="#22273d", padding=2)
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
                try:
                    hosts = search_app_hosts_online(app_name)
                    self.root.after(0, lambda: self._on_app_hosts_found(app_name, hosts))
                except Exception as e:
                    err_msg = str(e)
                    self.root.after(0, lambda: self.log_message(f"[!] Ошибка поиска хостов для '{app_name}': {err_msg}"))
                    self.root.after(0, lambda: self.status_var.set("Ошибка поиска хостов"))

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

        self.log_message(f"[+] Для '{app_name}' найдено и добавлено {added_count} доменов (сохранено в историю).")
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
                if success:
                    file_list_str = ", ".join(files[:6]) + ("..." if len(files) > 6 else "")
                    self.log_message(f"[+] {msg}\n    Обновлено: {file_list_str}")
                    self.status_var.set("Чистые .bat файлы восстановлены")
                    info_msg = f"Успешно восстановлено {len(files)} базовых .bat файлов из GitHub!\n\nФайлы перезаписаны рядом с fuzzer.exe."
                    messagebox.showinfo("Успех", info_msg)
                else:
                    self.log_message(f"[!] {msg}")
                    self.status_var.set("Ошибка восстановления .bat")
                    messagebox.showerror("Ошибка", msg)
            except Exception as e:
                self.log_message(f"[!] Ошибка восстановления .bat: {e}")
                self.status_var.set("Ошибка восстановления .bat")
                messagebox.showerror("Ошибка", str(e))

        threading.Thread(target=task, daemon=True).start()

    def _trigger_update(self):
        if not messagebox.askyesno("Обновление", "Запустить обновление fuzzer.exe с GitHub?\nТекущий процесс будет перезапущен с новой версией."):
            return

        self.log_message("[*] Загрузка обновленного fuzzer.exe с GitHub...")
        self.status_var.set("Скачивание fuzzer.exe...")

        def worker():
            try:
                success, msg = check_and_download_github_exe()
                if not success:
                    self.root.after(0, lambda: self.log_message(f"[!] Ошибка обновления: {msg}"))
                    self.root.after(0, lambda: self.status_var.set("Ошибка обновления"))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self.log_message(f"[!] Ошибка скачивания обновления: {err_msg}"))
                self.root.after(0, lambda: self.status_var.set("Ошибка скачивания fuzzer.exe"))

        threading.Thread(target=worker, daemon=True).start()

    def _browse_bat(self):
        file_selected = filedialog.askopenfilename(
            title="Выберите батник стратегии Zapret",
            filetypes=[("BAT Files", "*.bat"), ("All Files", "*.*")]
        )
        if file_selected:
            self.bat_path_var.set(file_selected)
            self._update_params_display(force_reload=True)

    def _add_preset_hosts(self, preset_name: str):
        self.log_message(f"[*] Загрузка хостов и IP для '{preset_name}'...")
        self.status_var.set(f"Поиск доменов для {preset_name}...")

        def worker():
            try:
                targets = fetch_preset_targets(preset_name, resolve_ips=True)
                self.root.after(0, lambda: self._on_preset_loaded(preset_name, targets))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self.log_message(f"[!] Ошибка загрузки пресета '{preset_name}': {err_msg}"))
                self.root.after(0, lambda: self.status_var.set("Ошибка загрузки пресета"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_preset_loaded(self, preset_name: str, targets: List[str]):
        added_count = 0
        for host in targets:
            if host not in self.target_hosts:
                self.target_hosts.append(host)
                self.hosts_listbox.insert(tk.END, host)
                added_count += 1

        self.log_message(f"[+] Для '{preset_name}' добавлено {added_count} новых доменов (всего: {len(self.target_hosts)}).")
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

    def _import_presets(self):
        file_path = filedialog.askopenfilename(
            title="Выберите JSON файл пресетов",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if file_path:
            ok, count = import_presets_from_file(file_path)
            if ok:
                self.log_message(f"[+] Импортировано {count} пресетов из '{os.path.basename(file_path)}'")
                messagebox.showinfo("Импорт пресетов", f"Успешно импортировано пресетов: {count}")
            else:
                messagebox.showerror("Ошибка", "Не удалось прочитать или распознать файл пресетов.")

    def _export_presets(self):
        file_path = filedialog.asksaveasfilename(
            title="Сохранить пресеты как JSON",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if file_path:
            if export_presets_to_file(file_path):
                self.log_message(f"[+] Пресеты экспортированы в '{os.path.basename(file_path)}'")
                messagebox.showinfo("Экспорт пресетов", "Пресеты успешно сохранены!")
            else:
                messagebox.showerror("Ошибка", "Не удалось экспортировать пресеты.")

    def _run_single_test(self):
        if not self.target_hosts:
            messagebox.showwarning("Внимание", "Список целевых хостов пуст! Добавьте хосты для проверки.")
            return

        bat_file = self.bat_path_var.get()
        if not os.path.exists(bat_file):
            messagebox.showerror("Ошибка", f"Файл '{bat_file}' не найден!")
            return

        try:
            params = WinwsParams(
                tcp_split=int(self.param_vars["tcp_split"].get().strip()),
                tcp_seqovl=int(self.param_vars["tcp_seqovl"].get().strip()),
                tcp_ttl=int(self.param_vars["tcp_ttl"].get().strip()),
                udp_repeats=int(self.param_vars["udp_repeats"].get().strip()),
                udp_cutoff=str(self.param_vars["udp_cutoff"].get()).strip()
            )
        except ValueError:
            messagebox.showerror("Ошибка", "Некорректные значения параметров! Убедитесь, что числа введены верно.")
            return

        self.start_btn.set_state(tk.DISABLED)
        self.stop_btn.set_state(tk.NORMAL)
        self.status_var.set("Выполнение разового теста...")

        require_100 = self.require_100_var.get() if hasattr(self, "require_100_var") else False
        self.engine = FuzzerEngine(
            bat_path=bat_file,
            log_callback=self.log_message,
            status_callback=self._on_engine_status,
            require_100_percent=require_100
        )

        def worker():
            try:
                success = self.engine.run_single_test(params, self.target_hosts)
                if success:
                    self.root.after(0, lambda: self._on_single_test_success(params))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self.log_message(f"[!] Ошибка выполнения разового теста: {err_msg}"))
            finally:
                self.root.after(0, self._on_fuzzing_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _on_single_test_success(self, params: WinwsParams):
        if messagebox.askyesno("Успех!", "Разовый тест прошел успешно! Применить эти параметры к .bat файлу?"):
            if self.engine:
                self.engine.patch_original_bat(params)
            else:
                temp_engine = FuzzerEngine(bat_path=self.bat_path_var.get())
                temp_engine.patch_original_bat(params)
            self._update_params_display(params)

    def _clear_hosts(self):
        self.hosts_listbox.delete(0, tk.END)
        self.target_hosts.clear()
        self.log_message("[-] Список хостов очищен.")

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

        require_100 = self.require_100_var.get() if hasattr(self, "require_100_var") else False
        self.engine = FuzzerEngine(
            bat_path=bat_file,
            log_callback=self.log_message,
            status_callback=self._on_engine_status,
            require_100_percent=require_100
        )

        def worker():
            try:
                self.engine.run_fuzzing(self.target_hosts)
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self.log_message(f"[!] Ошибка асинхронного подбора: {err_msg}"))
            finally:
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
            self.root.after(0, lambda p=status_dict["params"]: self._update_params_display(p))
        if "message" in status_dict:
            m = status_dict["message"]
            self.root.after(0, lambda: self.status_var.set(m))

    def log_message(self, text: str):
        self.log_queue.put(text)

    def _append_log_with_tags(self, msg: str):
        if "Результат:" in msg and "доступно" in msg:
            try:
                parts = msg.split("Результат:").strip().split()
                counts = parts[0].split("/")
                passed, total = int(counts[0]), int(counts)
                rate_pct = round((passed / max(1, total)) * 100.0, 1)

                step_name = "Р"
                self.analytics_chart.add_data_point(step_name, rate_pct, 45.0)
            except Exception:
                pass

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