import tkinter as tk
from tkinter import ttk
from ui_components import RoundedButton, StyledCard
from presets import load_history


class HistoryDialog(tk.Toplevel):
    """Компактное диалоговое окно истории приложений."""
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
        card = StyledCard(self, card_bg="#111422", border_color="#22273d", padding=6)
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
            self.listbox.insert(tk.END, f"  ⚡ {app_name:<18} — [{len(hosts)} доменов]")

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