import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import queue
import os
from typing import List

from presets import DEFAULT_GAME_PRESETS, fetch_preset_targets, search_app_hosts_online, load_history
from fuzzer_engine import FuzzerEngine, WinwsParams
from updater import check_and_download_github_exe


class HistoryDialog(tk.Toplevel):
    """Диалоговое окно истории добавленных программ и игр."""
    def __init__(self, parent, on_select_callback):
        super().__init__(parent)
        self.title("История добавленных программ и игр")
        self.geometry("520x360")
        self.resizable(False, False)
        self.on_select_callback = on_select_callback

        self._build_ui()
        self.transient(parent)
        self.grab_set()

    def _build_ui(self):
        container = ttk.Frame(self, padding=15)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="История ранее найденных программ:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))

        frame_list = ttk.Frame(container)
        frame_list.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.listbox = tk.Listbox(frame_list, font=("Consolas", 9), selectmode=tk.SINGLE)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.config(yscrollcommand=scrollbar.set)

        self.history_data = load_history()
        for app_name, hosts in self.history_data.items():
            self.listbox.insert(tk.END, f"{app_name} ({len(hosts)} хостов/IP)")

        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="Загрузить хосты в фуззер", style="Accent.TButton", command=self._load_selected).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Закрыть", command=self.destroy).pack(side=tk.RIGHT)

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
        self.root.title("Zapret Fuzzer & Strategy Tuner — GUI Edition")
        self.root.geometry("960x740")
        self.root.minsize(860, 650)

        self.bat_path_var = tk.StringVar(value="general (ALT11).bat")
        self.status_var = tk.StringVar(value="Готов к работе")
        self.winws_status_var = tk.StringVar(value="Не запущен")
        self.target_hosts: List[str] = []
        self.engine: FuzzerEngine = None
        self.log_queue = queue.Queue()

        self._setup_styles()
        self._build_ui()
        self._start_log_listener()
        self._check_winws_periodically()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        style.configure(".", background="#f5f6f8", foreground="#2b2d42")
        style.configure("TFrame", background="#f5f6f8")
        style.configure("TLabelframe", background="#f5f6f8", foreground="#1d3557")
        style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"), foreground="#1d3557")

        style.configure("TButton", font=("Segoe UI", 9), padding=5)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), background="#2a9d8f", foreground="white")
        style.map("Accent.TButton", background=[('active', '#218380'), ('disabled', '#cccccc')])

        style.configure("Preset.TButton", font=("Segoe UI", 9, "bold"), padding=5, background="#457b9d", foreground="white")
        style.map("Preset.TButton", background=[('active', '#1d3557')])

        style.configure("Update.TButton", font=("Segoe UI", 9, "bold"), background="#e76f51", foreground="white")
        style.map("Update.TButton", background=[('active', '#f4a261')])

        style.configure("History.TButton", font=("Segoe UI", 9, "bold"), background="#6c5ce7", foreground="white")
        style.map("History.TButton", background=[('active', '#a29bfe')])

        style.configure("Stop.TButton", font=("Segoe UI", 10, "bold"), background="#e63946", foreground="white")
        style.map("Stop.TButton", background=[('active', '#c1121f')])

    def _build_ui(self):
        main_container = ttk.Frame(self.root, padding=10)
        main_container.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.LabelFrame(main_container, text=" Настройки файла стратегии и управление ", padding=10)
        top_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top_frame, text="Файл стратегии:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        bat_entry = ttk.Entry(top_frame, textvariable=self.bat_path_var, width=38)
        bat_entry.grid(row=0, column=1, sticky=tk.EW, padx=5)

        browse_btn = ttk.Button(top_frame, text="Обзор...", command=self._browse_bat)
        browse_btn.grid(row=0, column=2, padx=3)

        history_btn = ttk.Button(top_frame, text="📜 История", style="History.TButton", command=self._open_history_dialog)
        history_btn.grid(row=0, column=3, padx=3)

        update_btn = ttk.Button(top_frame, text="🔄 Обновить", style="Update.TButton", command=self._trigger_update)
        update_btn.grid(row=0, column=4, padx=3)

        ttk.Label(top_frame, text="winws.exe:").grid(row=0, column=5, padx=(10, 5))
        self.winws_status_lbl = ttk.Label(top_frame, textvariable=self.winws_status_var, font=("Segoe UI", 9, "bold"), foreground="#e63946")
        self.winws_status_lbl.grid(row=0, column=6, sticky=tk.W)

        top_frame.columnconfigure(1, weight=1)

        preset_frame = ttk.LabelFrame(main_container, text=" Поиск и быстрый выбор приложений/игр ", padding=10)
        preset_frame.pack(fill=tk.X, pady=(0, 8))

        preset_btn_container = ttk.Frame(preset_frame)
        preset_btn_container.pack(fill=tk.X)

        presets_list = [
            ("🎯 Rainbow Six Siege", "Rainbow Six Siege"),
            ("💬 Discord", "Discord"),
            ("📺 YouTube", "YouTube"),
            ("🎮 Steam", "Steam"),
            ("🎲 Roblox", "Roblox")
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
            text="🔎 Найти приложение по имени",
            command=self._search_app_by_name
        )
        search_app_btn.grid(row=0, column=len(presets_list), padx=3, pady=2)

        middle_frame = ttk.Frame(main_container)
        middle_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 8))

        hosts_frame = ttk.LabelFrame(middle_frame, text=" Целевые хосты и IP адреса (проверяются по 12 хостов одновременно) ", padding=8)
        hosts_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        self.hosts_listbox = tk.Listbox(hosts_frame, height=7, selectmode=tk.SINGLE, font=("Consolas", 9))
        self.hosts_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(hosts_frame, orient=tk.VERTICAL, command=self.hosts_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hosts_listbox.config(yscrollcommand=scrollbar.set)

        hosts_btn_frame = ttk.Frame(hosts_frame)
        hosts_btn_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Button(hosts_btn_frame, text="Удалить выбранный", command=self._remove_selected_host).pack(side=tk.LEFT, padx=2)
        ttk.Button(hosts_btn_frame, text="Очистить список", command=self._clear_hosts).pack(side=tk.LEFT, padx=2)

        params_frame = ttk.LabelFrame(middle_frame, text=" Панель параметров ", padding=8)
        params_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5, 0))

        self.param_labels = {}
        param_names = [
            ("TCP Split Pos:", "tcp_split", "1"),
            ("TCP Seq Ovl:", "tcp_seqovl", "664"),
            ("TCP TTL:", "tcp_ttl", "0"),
            ("UDP Repeats:", "udp_repeats", "8"),
            ("UDP Cutoff:", "udp_cutoff", "n4")
        ]

        for row, (title, key, default_val) in enumerate(param_names):
            ttk.Label(params_frame, text=title, font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky=tk.W, pady=2, padx=(0, 5))
            val_lbl = ttk.Label(params_frame, text=default_val, font=("Consolas", 10, "bold"), foreground="#2a9d8f")
            val_lbl.grid(row=row, column=1, sticky=tk.E, pady=2)
            self.param_labels[key] = val_lbl

        ctrl_frame = ttk.Frame(main_container)
        ctrl_frame.pack(fill=tk.X, pady=(0, 8))

        self.start_btn = ttk.Button(
            ctrl_frame,
            text="🚀 Запустить подбор стратегии (12 параллельных целей)",
            style="Accent.TButton",
            command=self._start_fuzzing
        )
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.stop_btn = ttk.Button(
            ctrl_frame,
            text="🛑 Остановить",
            style="Stop.TButton",
            command=self._stop_fuzzing,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.RIGHT, padx=(5, 0))

        log_frame = ttk.LabelFrame(main_container, text=" Консоль подбора и тестирования ", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9), wrap=tk.WORD)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=3)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

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

    def _update_params_display(self, params: WinwsParams = None):
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
        self.status_var.set("Фуззинг в процессе (12 хостов)...")

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

    def _start_log_listener(self):
        def check_queue():
            while not self.log_queue.empty():
                msg = self.log_queue.get()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
            self.root.after(100, check_queue)

        self.root.after(100, check_queue)

    def _check_winws_periodically(self):
        def check():
            alive = FuzzerEngine.is_winws_alive()
            if alive:
                self.winws_status_var.set("Запущен (winws.exe)")
                self.winws_status_lbl.config(foreground="#2a9d8f")
            else:
                self.winws_status_var.set("Не запущен")
                self.winws_status_lbl.config(foreground="#e63946")
            self.root.after(2000, check)

        self.root.after(1000, check)

