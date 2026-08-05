import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import queue
import os
from typing import List, Optional

from presets import DEFAULT_GAME_PRESETS, fetch_preset_targets, search_app_hosts_online, load_history
from fuzzer_engine import FuzzerEngine, WinwsParams
from updater import check_and_download_github_exe


class HistoryDialog(tk.Toplevel):
    """Диалоговое окно истории добавленных программ и игр в стиле Neural Expressive."""
    def __init__(self, parent, on_select_callback):
        super().__init__(parent)
        self.title("История приложений")
        self.geometry("560x410")
        self.resizable(False, False)
        self.configure(bg="#08090f")
        self.on_select_callback = on_select_callback

        self._build_ui()
        self.transient(parent)
        self.grab_set()


    def _build_ui(self):
        container = ttk.Frame(self, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        header_lbl = ttk.Label(
            container,
            text="📜 История найденных приложений & хостов",
            font=("Segoe UI", 11, "bold"),
            foreground="#00f5d4"
        )
        header_lbl.pack(anchor=tk.W, pady=(0, 10))

        frame_list = ttk.Frame(container)
        frame_list.pack(fill=tk.BOTH, expand=True, pady=(0, 14))

        self.listbox = tk.Listbox(
            frame_list,
            font=("Consolas", 10),
            selectmode=tk.SINGLE,
            bg="#111422",
            fg="#f0f4f8",
            selectbackground="#7000ff",
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#22273d",
            activestyle="none",
            bd=0
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        self.history_data = load_history()
        for app_name, hosts in self.history_data.items():
            self.listbox.insert(tk.END, f"  ⚡ {app_name:<22} — [{len(hosts)} хостов/IP]")

        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X)

        ttk.Button(
            btn_frame,
            text="📥 Загрузить в фуззер",
            style="Accent.TButton",
            command=self._load_selected
        ).pack(side=tk.RIGHT, padx=(8, 0))

        ttk.Button(
            btn_frame,
            text="Закрыть",
            command=self.destroy
        ).pack(side=tk.RIGHT)

    def _load_selected(self):
        selection = self.listbox.curselection()
        if selection:
            idx = selection[0]
            app_name = list(self.history_data.keys())[idx]
            hosts = self.history_data[app_name]
            self.on_select_callback(app_name, hosts)
            self.destroy()


class SearchAppDialog(tk.Toplevel):
    """Диалоговое окно поиска хостов приложения в стиле Neural Expressive."""
    def __init__(self, parent, on_search_callback):
        super().__init__(parent)
        self.title("Поиск программы")
        self.geometry("460x210")
        self.resizable(False, False)
        self.configure(bg="#08090f")
        self.on_search_callback = on_search_callback

        self._build_ui()
        self.transient(parent)
        self.grab_set()

    def _build_ui(self):
        container = ttk.Frame(self, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        # Заголовок
        header_lbl = ttk.Label(
            container,
            text="🔎 Поиск хостов по имени приложения",
            font=("Segoe UI", 11, "bold"),
            foreground="#00f5d4",
            background="#08090f"  # Прозрачный фон под цвет окна
        )
        header_lbl.pack(anchor=tk.W, pady=(0, 6))

        # Описание / Подсказка
        sub_lbl = ttk.Label(
            container,
            text="Введите название программы или игры (например, Telegram, Discord, Apex Legends):",
            font=("Segoe UI", 9),
            foreground="#8f9bb3",
            background="#08090f",  # Прозрачный фон под цвет окна
            wraplength=410
        )
        sub_lbl.pack(anchor=tk.W, pady=(0, 14))

        # Поле ввода
        self.entry = tk.Entry(
            container,
            bg="#181c2e",
            fg="#00f5d4",
            insertbackground="#00f5d4",
            font=("Consolas", 11, "bold"),
            bd=0,
            highlightthickness=1,
            highlightbackground="#22273d",
            highlightcolor="#00f5d4"
        )
        self.entry.pack(fill=tk.X, ipady=6, pady=(0, 18))
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self._submit())

        # Кнопки действия
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X)

        ttk.Button(
            btn_frame,
            text="🔎 Найти хосты",
            style="Accent.TButton",
            command=self._submit
        ).pack(side=tk.RIGHT, padx=(8, 0))

        ttk.Button(
            btn_frame,
            text="Отмена",
            command=self.destroy
        ).pack(side=tk.RIGHT)

    def _submit(self):
        val = self.entry.get().strip()
        if val:
            self.on_search_callback(val)
            self.destroy()

class ZapretFuzzerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Zapret Fuzzer & Strategy Tuner — Version 0.1.5")
        self.root.geometry("1020x820")
        self.root.minsize(1020, 820)
        self.root.configure(bg="#08090f")

        self.bat_path_var = tk.StringVar(value="general (ALT11).bat")
        self.status_var = tk.StringVar(value="Система готова к работе")
        self.winws_status_var = tk.StringVar(value="Не запущен")
        self.target_hosts: List[str] = []
        self.engine: Optional[FuzzerEngine] = None
        self.log_queue = queue.Queue()

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
        BORDER_COL = "#22273d"

        style.configure(".", background=BG_DARK, foreground=FG_TEXT)
        style.configure("TFrame", background=BG_DARK)
        style.configure("Card.TFrame", background=BG_CARD)

        style.configure(
            "TLabelframe",
            background=BG_CARD,
            foreground="#00f5d4",
            bordercolor=BORDER_COL,
            darkcolor=BG_CARD,
            lightcolor=BG_CARD,
            borderwidth=1
        )
        style.configure(
            "TLabelframe.Label",
            font=("Segoe UI", 10, "bold"),
            background=BG_CARD,
            foreground="#00f5d4"
        )

        style.configure(
            "TLabel",
            background=BG_CARD,
            foreground=FG_TEXT,
            font=("Segoe UI", 9)
        )

        # Standard button styling
        style.configure(
            "TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(10, 6),
            background="#1a1f33",
            foreground="#f0f4f8",
            borderwidth=0,
            focusthickness=0
        )
        style.map(
            "TButton",
            background=[('active', '#2a314d'), ('disabled', '#121524')],
            foreground=[('disabled', '#525b75')]
        )

        # Primary Accent Button (Neural Cyan)
        style.configure(
            "Accent.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 8),
            background="#00f5d4",
            foreground="#08090f"
        )
        style.map(
            "Accent.TButton",
            background=[('active', '#00d4b8'), ('disabled', '#1a2430')],
            foreground=[('disabled', '#3e5263')]
        )

        # Emergency / Stop Button (Cyber Red)
        style.configure(
            "Stop.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 8),
            background="#ff4757",
            foreground="#ffffff"
        )
        style.map(
            "Stop.TButton",
            background=[('active', '#ff6b81'), ('disabled', '#2a1a24')],
            foreground=[('disabled', '#523342')]
        )

        # Preset Button (Quantum Violet)
        style.configure(
            "Preset.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(8, 6),
            background="#1e1836",
            foreground="#d1c4e9"
        )
        style.map(
            "Preset.TButton",
            background=[('active', '#7000ff')],
            foreground=[('active', '#ffffff')]
        )

        # Update & Utility Buttons
        style.configure(
            "Update.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(8, 5),
            background="#e76f51",
            foreground="#ffffff"
        )
        style.map("Update.TButton", background=[('active', '#f4a261')])

        style.configure(
            "History.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(8, 5),
            background="#7000ff",
            foreground="#ffffff"
        )
        style.map("History.TButton", background=[('active', '#8a2be2')])

        # Service Controls
        style.configure(
            "SvcStart.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(8, 5),
            background="#2ec4b6",
            foreground="#08090f"
        )
        style.map("SvcStart.TButton", background=[('active', '#20ad96')])

        style.configure(
            "SvcReset.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(8, 5),
            background="#ff4757",
            foreground="#ffffff"
        )
        style.map("SvcReset.TButton", background=[('active', '#ff6b81')])

    def _build_ui(self):
        # Master container
        main_container = ttk.Frame(self.root, padding=14)
        main_container.pack(fill=tk.BOTH, expand=True)

        # --- Top Banner Header ---
        header_frame = tk.Frame(main_container, bg="#0d101d", highlightthickness=1, highlightbackground="#22273d")
        header_frame.pack(fill=tk.X, pady=(0, 12))

        header_content = tk.Frame(header_frame, bg="#0d101d", padx=14, pady=10)
        header_content.pack(fill=tk.X)

        title_label = tk.Label(
            header_content,
            text="🧠 ZAPRET FUZZER & STRATEGY TUNER",
            font=("Segoe UI", 13, "bold"),
            bg="#0d101d",
            fg="#00f5d4"
        )
        title_label.pack(side=tk.LEFT)

        subtitle_label = tk.Label(
            header_content,
            text="Version 0.1.5",
            font=("Segoe UI", 8, "bold"),
            bg="#0d101d",
            fg="#7000ff"
        )
        subtitle_label.pack(side=tk.LEFT, padx=(10, 0))

        # --- Section 1: Strategy & Winws Control ---
        top_frame = ttk.LabelFrame(main_container, text=" ⚡ Настройки стратегии и управление winws ", padding=12)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        # Row 0: Strategy File + Status
        ttk.Label(top_frame, text="Файл стратегии:", font=("Segoe UI", 9, "bold"), foreground="#8f9bb3").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))

        bat_entry = tk.Entry(
            top_frame,
            textvariable=self.bat_path_var,
            bg="#181c2e",
            fg="#00f5d4",
            insertbackground="#00f5d4",
            font=("Consolas", 10, "bold"),
            bd=0,
            highlightthickness=1,
            highlightbackground="#22273d",
            highlightcolor="#00f5d4"
        )
        bat_entry.grid(row=0, column=1, sticky=tk.EW, padx=6)

        ttk.Button(top_frame, text="📁 Обзор...", command=self._browse_bat).grid(row=0, column=2, padx=3)
        ttk.Button(top_frame, text="📜 История", style="History.TButton", command=self._open_history_dialog).grid(row=0, column=3, padx=3)
        ttk.Button(top_frame, text="🔄 Обновить", style="Update.TButton", command=self._trigger_update).grid(row=0, column=4, padx=3)

        ttk.Label(top_frame, text="Статус winws:", font=("Segoe UI", 9, "bold"), foreground="#8f9bb3").grid(row=0, column=5, padx=(14, 6))
        self.winws_status_lbl = ttk.Label(top_frame, textvariable=self.winws_status_var, font=("Segoe UI", 9, "bold"), foreground="#ff4757")
        self.winws_status_lbl.grid(row=0, column=6, sticky=tk.W)

        top_frame.columnconfigure(1, weight=1)

        # Row 1: Service Management Controls
        svc_frame = tk.Frame(top_frame, bg="#111422", bd=0, highlightthickness=0)
        svc_frame.grid(row=1, column=0, columnspan=5, sticky=tk.EW, pady=(12, 0))

        ttk.Label(svc_frame, text="Управление службой:", font=("Segoe UI", 13, "bold"), foreground="#8f9bb3", background="#111422").pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(svc_frame, text="▶ Запустить", style="SvcStart.TButton", command=self._start_winws_service).pack(side=tk.LEFT, padx=3)
        ttk.Button(svc_frame, text="⏹ Остановить", command=self._stop_winws_service).pack(side=tk.LEFT, padx=3)
        ttk.Button(svc_frame, text="🔄 Перезапустить", command=self._restart_winws_service).pack(side=tk.LEFT, padx=3)
        ttk.Button(svc_frame, text="🧹 Сброс WinDivert", style="SvcReset.TButton", command=self._reset_windivert_service).pack(side=tk.LEFT, padx=(18, 3))

        # --- Section 2: Presets & Online Search ---
        preset_frame = ttk.LabelFrame(main_container, text=" 🎯 Поиск и пресеты приложений ", padding=12)
        preset_frame.pack(fill=tk.X, pady=(0, 10))

        preset_btn_container = ttk.Frame(preset_frame)
        preset_btn_container.pack(fill=tk.X)

        presets_list = [
            ("🎯 Rainbow Six Siege", "Rainbow Six Siege"),
            ("💬 Discord", "Discord"),
            ("📺 YouTube", "YouTube"),
            ("🎮 Steam", "Steam"),
            ("✈️ Telegram", "Telegram")
        ]

        for i, (label, name) in enumerate(presets_list):
            btn = ttk.Button(
                preset_btn_container,
                text=label,
                style="Preset.TButton",
                command=lambda p=name: self._add_preset_hosts(p)
            )
            btn.grid(row=0, column=i, padx=3, pady=2, sticky=tk.EW)
            preset_btn_container.columnconfigure(i, weight=1)

        search_app_btn = ttk.Button(
            preset_btn_container,
            text="🔎 Поиск по имени",
            command=self._search_app_by_name
        )
        search_app_btn.grid(row=0, column=len(presets_list), padx=3, pady=2)

        # --- Section 3: Middle Split (Hosts List + Parameter Dashboard) ---
        middle_frame = ttk.Frame(main_container)
        middle_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 10))

        # Hosts Panel
        hosts_frame = ttk.LabelFrame(middle_frame, text=" 🌐 Целевые хосты и IP (до 12 параллельно, порог: 8) ", padding=10)
        hosts_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        self.hosts_listbox = tk.Listbox(
            hosts_frame,
            height=7,
            selectmode=tk.SINGLE,
            font=("Consolas", 10),
            bg="#181c2e",
            fg="#f0f4f8",
            selectbackground="#7000ff",
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground="#22273d",
            activestyle="none",
            bd=0
        )
        self.hosts_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(hosts_frame, orient=tk.VERTICAL, command=self.hosts_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hosts_listbox.config(yscrollcommand=scrollbar.set)

        hosts_btn_frame = ttk.Frame(hosts_frame)
        hosts_btn_frame.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(hosts_btn_frame, text="🗑️ Удалить выбранный", command=self._remove_selected_host).pack(side=tk.LEFT, padx=2)
        ttk.Button(hosts_btn_frame, text="🧹 Очистить список", command=self._clear_hosts).pack(side=tk.LEFT, padx=2)

        # Parameters Dashboard Panel
        params_frame = ttk.LabelFrame(middle_frame, text=" 🎛️ Панель параметров ", padding=10)
        params_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))

        self.param_labels = {}
        param_names = [
            ("TCP Split Pos:", "tcp_split", "1"),
            ("TCP Seq Ovl:", "tcp_seqovl", "664"),
            ("TCP TTL:", "tcp_ttl", "0"),
            ("UDP Repeats:", "udp_repeats", "8"),
            ("UDP Cutoff:", "udp_cutoff", "n4")
        ]

        for row, (title, key, default_val) in enumerate(param_names):
            ttk.Label(
                params_frame,
                text=title,
                font=("Segoe UI", 9, "bold"),
                foreground="#8f9bb3"
            ).grid(row=row, column=0, sticky=tk.W, pady=4, padx=(0, 10))

            val_lbl = ttk.Label(
                params_frame,
                text=default_val,
                font=("Consolas", 11, "bold"),
                foreground="#00f5d4"
            )
            val_lbl.grid(row=row, column=1, sticky=tk.E, pady=4)
            self.param_labels[key] = val_lbl

        # --- Section 4: Engine Actions ---
        ctrl_frame = ttk.Frame(main_container)
        ctrl_frame.pack(fill=tk.X, pady=(0, 10))

        self.start_btn = ttk.Button(
            ctrl_frame,
            text="🚀 Запустить подбор стратегии",
            style="Accent.TButton",
            command=self._start_fuzzing
        )
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self.stop_btn = ttk.Button(
            ctrl_frame,
            text="🛑 Остановить",
            style="Stop.TButton",
            command=self._stop_fuzzing,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.RIGHT, padx=(6, 0))

        # --- Section 5: Console Terminal Log ---
        log_frame = ttk.LabelFrame(main_container, text=" 💻 Консоль подбора и тестирования ", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            bg="#05060a",
            fg="#d0d7de",
            insertbackground="#00f5d4",
            font=("Consolas", 9),
            wrap=tk.WORD,
            bd=0,
            highlightthickness=1,
            highlightbackground="#22273d"
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Log color tags
        self.log_text.tag_config("plus", foreground="#00ff9d", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("star", foreground="#00f0ff")
        self.log_text.tag_config("warn", foreground="#ffd166", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("minus", foreground="#ff4757")

        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

        # Bottom Status Bar
        status_bar_frame = tk.Frame(self.root, bg="#111422", highlightthickness=1, highlightbackground="#22273d")
        status_bar_frame.pack(side=tk.BOTTOM, fill=tk.X)

        status_bar = tk.Label(
            status_bar_frame,
            textvariable=self.status_var,
            bg="#111422",
            fg="#8f9bb3",
            font=("Segoe UI", 9),
            anchor=tk.W,
            padx=10,
            pady=5
        )
        status_bar.pack(side=tk.LEFT, fill=tk.X)

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
        def start_search(app_name: str):
            self.log_message(f"[*] Поиск хостов в интернете для программы '{app_name}'...")
            self.status_var.set(f"Поиск хостов для {app_name}...")

            def worker():
                hosts = search_app_hosts_online(app_name)
                self.root.after(0, lambda: self._on_app_hosts_found(app_name, hosts))

            threading.Thread(target=worker, daemon=True).start()

        SearchAppDialog(self.root, on_search_callback=start_search)

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

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Фуззинг в процессе...")

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
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Работа завершена")
        self._update_params_display()

    def _on_engine_status(self, status_dict: dict):
        if "params" in status_dict:
            self.root.after(0, lambda: self._update_params_display(status_dict["params"]))
        if "message" in status_dict:
            self.status_var.set(status_dict["message"])

    def log_message(self, text: str):
        self.log_queue.put(text)

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