import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from fuzzer_engine import WinwsParams, validate_params
from presets import load_sessions
from user_lists import EXCLUDE, INCLUDE, UserLists
from ui.components import RoundedButton, StyledCard
from ui import theme
from ui.theme import MONO_FAMILY, font, setup_ttk


class HistoryDialog(tk.Toplevel):
    """История запусков подбора параметров."""

    def __init__(self, parent, on_select_callback: Callable[[str, list], None]):
        super().__init__(parent)
        self.title("История подбора")
        self.geometry("900x500")
        self.minsize(820, 440)
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.grab_set()

        setup_ttk(self)
        self.on_select_callback = on_select_callback
        self.sessions = load_sessions()
        self._build_ui()

    def _build_ui(self) -> None:
        card = StyledCard(self, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=18)
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        frame = card.inner_frame

        tk.Label(
            frame,
            text="Сохранённые запуски",
            font=font(14, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(anchor=tk.W)
        tk.Label(
            frame,
            text="Сохранённые запуски: параметры, домены и результат проверки",
            font=font(9),
            bg=theme.SURFACE,
            fg=theme.MUTED,
        ).pack(anchor=tk.W, pady=(1, 12))

        columns = ("date", "strategy", "hosts", "params", "ratio")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        headers = {
            "date": ("Дата и время", 145),
            "strategy": ("Стратегия", 145),
            "hosts": ("Хосты", 55),
            "params": ("Параметры winws", 300),
            "ratio": ("Результат", 105),
        }
        for column, (title, width) in headers.items():
            self.tree.heading(column, text=title)
            self.tree.column(
                column,
                width=width,
                anchor=tk.CENTER if column in ("hosts", "ratio") else tk.W,
            )

        buttons = tk.Frame(frame, bg=theme.SURFACE)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, pady=(14, 0))

        RoundedButton(
            buttons,
            text="Загрузить хосты",
            command=self._load_selected,
            radius=16,
            bg_color=theme.ACCENT,
            fg_color=theme.ON_ACCENT,
            hover_bg=theme.ACCENT_HOVER,
            border_color=theme.ACCENT,
            width=150,
            height=34,
            font=font(9, "bold"),
        ).pack(side=tk.RIGHT, padx=(8, 0))
        RoundedButton(
            buttons,
            text="Закрыть",
            command=self.destroy,
            radius=16,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=100,
            height=34,
            font=font(9),
        ).pack(side=tk.RIGHT)

        tree_frame = tk.Frame(frame, bg=theme.SURFACE)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for index, record in enumerate(self.sessions):
            params = record.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            if record.get("strategy_label"):
                param_str = str(record["strategy_label"])
            else:
                param_str = (
                    f"{params.get('desync_mode', '?')}  ·  split {params.get('tcp_split', '?')}"
                    f"  ·  seqovl {params.get('tcp_seqovl', '?')}"
                    f"  ·  ttl {params.get('tcp_ttl', '?')}"
                    f"  ·  fooling {params.get('fooling_mode', '?')}"
                )
            result = "Успех" if record.get("success") else "Провал"
            ratio = f"{result}  {record.get('passed_count', 0)}/{record.get('total_count', 0)}"
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    str(record.get("timestamp", "—")).replace("T", " "),
                    record.get("strategy_file", "—"),
                    len(record.get("target_hosts") or []),
                    param_str,
                    ratio,
                ),
            )

        if not self.sessions:
            tk.Label(
                frame,
                text="История пока пуста — запустите разовый тест или подбор стратегии.",
                font=font(9),
                bg=theme.SURFACE,
                fg=theme.MUTED_LIGHT,
            ).pack(anchor=tk.W, pady=(10, 0))

    def _load_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Предупреждение", "Выберите запись из истории!", parent=self)
            return

        record = self.sessions[int(selected[0])]
        hosts = [str(host) for host in (record.get("target_hosts") or [])]
        if not hosts:
            messagebox.showinfo("История", "В этой записи нет сохранённых хостов.", parent=self)
            return

        if self.on_select_callback:
            self.on_select_callback(f"История {record.get('timestamp', '')}".strip(), hosts)
        self.destroy()


class DomainListsDialog(tk.Toplevel):
    """Редактор личных списков list-general-user / list-exclude-user."""

    def __init__(
        self,
        parent,
        lists_dir: str,
        on_save_callback: Callable[[dict], None] = None,
    ):
        super().__init__(parent)
        self.title("Списки доменов")
        self.geometry("840x620")
        self.minsize(720, 520)
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.grab_set()

        setup_ttk(self)
        self.store = UserLists(lists_dir)
        self.store.ensure()
        self.on_save_callback = on_save_callback
        self.buffers = {
            INCLUDE: self.store.read_lines(INCLUDE),
            EXCLUDE: self.store.read_lines(EXCLUDE),
        }
        self.current = INCLUDE
        self.tab_buttons = {}

        self._build_ui()
        self._show(INCLUDE, store_current=False)

    def _build_ui(self) -> None:
        card = StyledCard(self, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=18)
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        frame = card.inner_frame

        tk.Label(
            frame,
            text="Списки доменов",
            font=font(14, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(anchor=tk.W)
        tk.Label(
            frame,
            text=(
                "Личные списки winws. Не входят в установщик, обновление их не трогает. "
                "Изменения применятся после перезапуска движка."
            ),
            font=font(9),
            bg=theme.SURFACE,
            fg=theme.MUTED,
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(1, 12))

        tabs = tk.Frame(frame, bg=theme.SURFACE)
        tabs.pack(fill=tk.X)
        for kind, title in ((INCLUDE, "Обход"), (EXCLUDE, "Исключения")):
            button = RoundedButton(
                tabs,
                text=title,
                command=lambda k=kind: self._show(k),
                radius=15,
                width=170,
                height=32,
                font=font(9, "bold"),
            )
            button.pack(side=tk.LEFT, padx=(0, 8))
            self.tab_buttons[kind] = button

        self.path_var = tk.StringVar()
        tk.Label(
            frame,
            textvariable=self.path_var,
            font=(MONO_FAMILY, 8),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(10, 6))

        text_frame = tk.Frame(frame, bg=theme.SURFACE_SOFT)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text = tk.Text(
            text_frame,
            bg=theme.SURFACE_SOFT,
            fg=theme.INK,
            insertbackground=theme.ACCENT,
            font=(MONO_FAMILY, 9),
            wrap=tk.NONE,
            undo=True,
            bd=0,
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=theme.BORDER,
            highlightcolor=theme.ACCENT,
        )
        y_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text.yview)
        x_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.text.xview)
        self.text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="Один домен на строку. Пустые строки и #-комментарии игнорируются.",
            font=font(8),
            bg=theme.SURFACE,
            fg=theme.MUTED_LIGHT,
        ).pack(anchor=tk.W, pady=(6, 0))

        add_row = tk.Frame(frame, bg=theme.SURFACE)
        add_row.pack(fill=tk.X, pady=(8, 0))

        self.add_var = tk.StringVar()
        add_entry = tk.Entry(
            add_row,
            textvariable=self.add_var,
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
        add_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 8))
        add_entry.bind("<Return>", lambda _e: self._add_domain())

        RoundedButton(
            add_row,
            text="Добавить",
            command=self._add_domain,
            radius=14,
            bg_color=theme.ACCENT,
            fg_color=theme.ON_ACCENT,
            hover_bg=theme.ACCENT_HOVER,
            border_color=theme.ACCENT,
            width=100,
            height=30,
            font=font(9, "bold"),
        ).pack(side=tk.RIGHT)

        buttons = tk.Frame(frame, bg=theme.SURFACE)
        buttons.pack(fill=tk.X, pady=(14, 0))

        RoundedButton(
            buttons,
            text="Импорт TXT",
            command=self._import_txt,
            radius=16,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=120,
            height=34,
            font=font(9),
        ).pack(side=tk.LEFT)
        RoundedButton(
            buttons,
            text="Сохранить",
            command=self._save,
            radius=16,
            bg_color=theme.ACCENT,
            fg_color=theme.ON_ACCENT,
            hover_bg=theme.ACCENT_HOVER,
            border_color=theme.ACCENT,
            width=130,
            height=34,
            font=font(9, "bold"),
        ).pack(side=tk.RIGHT, padx=(8, 0))
        RoundedButton(
            buttons,
            text="Закрыть",
            command=self.destroy,
            radius=16,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=100,
            height=34,
            font=font(9),
        ).pack(side=tk.RIGHT)

    def _store_current(self) -> None:
        self.buffers[self.current] = self.text.get("1.0", "end-1c").splitlines()

    def _count(self, kind: str) -> int:
        return sum(
            1
            for line in self.buffers.get(kind, [])
            if line.strip() and not line.strip().startswith("#")
        )

    def _paint_tabs(self) -> None:
        for kind, button in self.tab_buttons.items():
            active = kind == self.current
            if active:
                button.set_colors(theme.ACCENT_SOFT, theme.ACCENT, theme.ACCENT_SOFT_HOVER, theme.ACCENT_SOFT_HOVER)
            else:
                button.set_colors(theme.SURFACE, theme.INK_SOFT, theme.SURFACE_ALT, theme.BORDER)
            button.set_text(
                f"Обход ({self._count(INCLUDE)})" if kind == INCLUDE
                else f"Исключения ({self._count(EXCLUDE)})"
            )

    def _show(self, kind: str, store_current: bool = True) -> None:
        if store_current and hasattr(self, "text") and self.text.winfo_exists():
            self._store_current()
        self.current = kind
        self.text.delete("1.0", tk.END)
        lines = self.buffers.get(kind, [])
        if lines:
            self.text.insert("1.0", "\n".join(lines))
        self.path_var.set(self.store.path(kind))
        self._paint_tabs()
        self.text.focus_set()

    def _add_domain(self) -> None:
        value = self.add_var.get().strip()
        if not value:
            return
        existing = {
            line.strip().lower()
            for line in self.text.get("1.0", "end-1c").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        for item in value.replace(",", " ").split():
            domain = item.strip().lower()
            if not domain or domain in existing:
                continue
            current = self.text.get("1.0", "end-1c")
            prefix = "" if not current or current.endswith("\n") else "\n"
            self.text.insert(tk.END, prefix + domain)
            existing.add(domain)
        self.add_var.set("")
        self._store_current()
        self._paint_tabs()

    def _import_txt(self) -> None:
        path = filedialog.askopenfilename(
            title="Импорт доменов",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as handle:
                lines = handle.read().splitlines()
        except OSError as error:
            messagebox.showerror("Импорт", str(error), parent=self)
            return
        current = self.text.get("1.0", "end-1c").rstrip("\n")
        extra = "\n".join(line.strip() for line in lines if line.strip())
        if extra:
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", (current + "\n" + extra).strip("\n"))
        self._store_current()
        self._paint_tabs()

    def _save(self) -> None:
        self._store_current()
        invalid = []
        for kind in (INCLUDE, EXCLUDE):
            _saved, bad = self.store.save_lines(kind, self.buffers.get(kind, []))
            invalid.extend(bad)
            self.buffers[kind] = self.store.read_lines(kind)

        self._show(self.current, store_current=False)
        if invalid:
            preview = "\n".join(invalid[:8])
            messagebox.showwarning(
                "Некорректные строки",
                "Эти строки пропущены:\n\n" + preview,
                parent=self,
            )

        include = set(self.store.load(INCLUDE))
        exclude = set(self.store.load(EXCLUDE))
        overlap = sorted(include & exclude)
        if overlap:
            messagebox.showinfo(
                "Исключения имеют приоритет",
                "Эти домены есть и в обходе, и в исключениях.\n"
                "winws не будет их трогать:\n\n" + "\n".join(overlap[:10]),
                parent=self,
            )

        counts = {
            INCLUDE: len(include),
            EXCLUDE: len(exclude),
        }
        if self.on_save_callback:
            self.on_save_callback(counts)
        self.path_var.set(self.store.path(self.current))


class InteractiveParamsWindow(tk.Toplevel):
    """Ручное редактирование всех параметров WinwsParams."""

    DESYNC_MODES = [
        "split",
        "split2",
        "disorder",
        "disorder2",
        "fake",
        "fake,split2",
        "fake,disorder2",
        "multisplit",
        "multidisorder",
        "oob",
        "syndata",
    ]
    FOOLING_MODES = ["none", "md5sig", "badsum", "badseq", "ts"]

    def __init__(
        self,
        parent,
        current_params: WinwsParams,
        on_apply_callback: Callable[[WinwsParams], None],
        on_test_callback: Callable[[WinwsParams], None],
    ):
        super().__init__(parent)
        self.title("Параметры winws")
        self.geometry("620x520")
        self.minsize(560, 480)
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.grab_set()

        setup_ttk(self)
        self.on_apply_callback = on_apply_callback
        self.on_test_callback = on_test_callback

        self.vars = {
            "tcp_split": tk.StringVar(value=str(current_params.tcp_split)),
            "tcp_seqovl": tk.StringVar(value=str(current_params.tcp_seqovl)),
            "tcp_ttl": tk.StringVar(value=str(current_params.tcp_ttl)),
            "desync_mode": tk.StringVar(value=current_params.desync_mode),
            "fooling_mode": tk.StringVar(value=current_params.fooling_mode),
            "udp_repeats": tk.StringVar(value=str(current_params.udp_repeats)),
            "udp_cutoff": tk.StringVar(value=current_params.udp_cutoff),
            "any_protocol": tk.BooleanVar(value=current_params.any_protocol),
        }

        self._build_ui()

    def _build_ui(self) -> None:
        card = StyledCard(self, bg=theme.BG, card_bg=theme.SURFACE, border_color=theme.BORDER, padding=18)
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        frame = card.inner_frame

        tk.Label(
            frame,
            text="Параметры winws",
            font=font(14, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(anchor=tk.W)
        tk.Label(
            frame,
            text="Значения записываются в командную строку .bat: пробелы и кавычки запрещены.",
            font=font(9),
            bg=theme.SURFACE,
            fg=theme.MUTED,
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(1, 14))

        grid = tk.Frame(frame, bg=theme.SURFACE)
        grid.pack(fill=tk.X)
        grid.columnconfigure(1, weight=1)

        fields = [
            ("Позиция split", "tcp_split", None),
            ("SeqOvl", "tcp_seqovl", None),
            ("TTL", "tcp_ttl", None),
            ("Desync mode", "desync_mode", self.DESYNC_MODES),
            ("Fooling mode", "fooling_mode", self.FOOLING_MODES),
            ("Repeats", "udp_repeats", None),
            ("Cutoff", "udp_cutoff", None),
        ]

        for row, (label_text, key, choices) in enumerate(fields):
            tk.Label(
                grid,
                text=label_text,
                font=font(9, "bold"),
                bg=theme.SURFACE,
                fg=theme.INK_SOFT,
            ).grid(row=row, column=0, sticky=tk.W, pady=6, padx=(0, 14))

            if choices:
                widget = ttk.Combobox(
                    grid,
                    textvariable=self.vars[key],
                    values=choices,
                    width=24,
                    font=font(9),
                )
            else:
                widget = tk.Entry(
                    grid,
                    textvariable=self.vars[key],
                    width=24,
                    font=(MONO_FAMILY, 9),
                    bg=theme.SURFACE_SOFT,
                    fg=theme.INK,
                    insertbackground=theme.ACCENT,
                    relief=tk.FLAT,
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=theme.BORDER,
                    highlightcolor=theme.ACCENT,
                    justify=tk.LEFT,
                )
            widget.grid(row=row, column=1, sticky=tk.EW, pady=4, ipady=5 if not choices else 0)

        tk.Checkbutton(
            grid,
            text="Any protocol  ·  --dpi-desync-any-protocol",
            variable=self.vars["any_protocol"],
            font=font(9),
            bg=theme.SURFACE,
            fg=theme.INK_SOFT,
            selectcolor=theme.SURFACE,
            activebackground=theme.SURFACE,
            activeforeground=theme.INK,
            highlightthickness=0,
            bd=0,
        ).grid(row=len(fields), column=0, columnspan=2, sticky=tk.W, pady=(10, 4))

        buttons = tk.Frame(frame, bg=theme.SURFACE)
        buttons.pack(fill=tk.X, side=tk.BOTTOM, pady=(16, 0))

        RoundedButton(
            buttons,
            text="Разовый тест",
            command=self._on_test,
            radius=16,
            bg_color=theme.ACCENT_SOFT,
            fg_color=theme.ACCENT,
            hover_bg=theme.ACCENT_SOFT_HOVER,
            border_color=theme.ACCENT_SOFT_HOVER,
            width=140,
            height=34,
            font=font(9, "bold"),
        ).pack(side=tk.LEFT)
        RoundedButton(
            buttons,
            text="Сохранить",
            command=self._on_apply,
            radius=16,
            bg_color=theme.ACCENT,
            fg_color=theme.ON_ACCENT,
            hover_bg=theme.ACCENT_HOVER,
            border_color=theme.ACCENT,
            width=120,
            height=34,
            font=font(9, "bold"),
        ).pack(side=tk.RIGHT, padx=(8, 0))
        RoundedButton(
            buttons,
            text="Закрыть",
            command=self.destroy,
            radius=16,
            bg_color=theme.SURFACE,
            fg_color=theme.INK_SOFT,
            hover_bg=theme.SURFACE_ALT,
            border_color=theme.BORDER,
            width=100,
            height=34,
            font=font(9),
        ).pack(side=tk.RIGHT)

    @staticmethod
    def _to_int(value: str, default: int) -> int:
        try:
            return int(value.strip())
        except ValueError:
            return default

    def _get_params(self) -> WinwsParams:
        params = WinwsParams(
            tcp_split=self._to_int(self.vars["tcp_split"].get(), 1),
            tcp_seqovl=self._to_int(self.vars["tcp_seqovl"].get(), 664),
            tcp_ttl=self._to_int(self.vars["tcp_ttl"].get(), 0),
            desync_mode=self.vars["desync_mode"].get().strip(),
            fooling_mode=self.vars["fooling_mode"].get().strip(),
            udp_repeats=self._to_int(self.vars["udp_repeats"].get(), 8),
            udp_cutoff=self.vars["udp_cutoff"].get().strip(),
            any_protocol=self.vars["any_protocol"].get(),
        )
        validate_params(params)
        return params

    def _on_test(self) -> None:
        try:
            params = self._get_params()
        except ValueError as error:
            messagebox.showerror("Некорректные параметры", str(error), parent=self)
            return
        if self.on_test_callback:
            self.on_test_callback(params)
        self.destroy()

    def _on_apply(self) -> None:
        try:
            params = self._get_params()
        except ValueError as error:
            messagebox.showerror("Некорректные параметры", str(error), parent=self)
            return
        if self.on_apply_callback:
            self.on_apply_callback(params)
        self.destroy()
