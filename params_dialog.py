import tkinter as tk
from typing import Dict
from ui_components import RoundedButton, StyledCard


class InteractiveParamsDialog(tk.Toplevel):
    """Интерактивное диалоговое окно быстрой настройки параметров."""
    def __init__(self, parent, param_vars: Dict[str, tk.StringVar], on_run_test_cb):
        super().__init__(parent)
        self.title("🎛️ Интерактивная настройка параметров")
        self.geometry("460x390")
        self.configure(bg="#08090f")
        self.transient(parent)
        self.grab_set()

        self.param_vars = param_vars
        self.on_run_test_cb = on_run_test_cb

        self._build_ui()

    def _build_ui(self):
        card = StyledCard(self, card_bg="#111422", border_color="#22273d", padding=10)
        card.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        iframe = card.inner_frame

        tk.Label(iframe, text="⚙️ Интерактивный редактор параметров Zapret", font=("Segoe UI", 10, "bold"), bg="#111422", fg="#00f5d4").pack(anchor=tk.W, pady=(0, 4))
        tk.Label(iframe, text="Введите параметры вручную для быстрого разового теста или сохранения в .bat файл.", font=("Segoe UI", 8), bg="#111422", fg="#8f9bb3", wraplength=420, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 6))

        grid_frame = tk.Frame(iframe, bg="#111422")
        grid_frame.pack(fill=tk.X, pady=4)

        self.dialog_vars = {
            "tcp_split": tk.StringVar(value=self.param_vars["tcp_split"].get()),
            "tcp_seqovl": tk.StringVar(value=self.param_vars["tcp_seqovl"].get()),
            "tcp_ttl": tk.StringVar(value=self.param_vars["tcp_ttl"].get()),
            "udp_repeats": tk.StringVar(value=self.param_vars["udp_repeats"].get()),
            "udp_cutoff": tk.StringVar(value=self.param_vars["udp_cutoff"].get())
        }

        fields = [
            ("TCP Split Pos (--dpi-desync-split-pos):", "tcp_split"),
            ("TCP Seq Ovl (--dpi-desync-split-seqovl):", "tcp_seqovl"),
            ("TCP TTL (--dpi-desync-ttl):", "tcp_ttl"),
            ("UDP Repeats (--dpi-desync-repeats):", "udp_repeats"),
            ("UDP Cutoff (--dpi-desync-cutoff):", "udp_cutoff")
        ]

        for idx, (label_text, key) in enumerate(fields):
            tk.Label(grid_frame, text=label_text, font=("Segoe UI", 8, "bold"), bg="#111422", fg="#f0f4f8").grid(row=idx, column=0, sticky=tk.W, pady=3, padx=(0, 10))
            ent = tk.Entry(
                grid_frame,
                textvariable=self.dialog_vars[key],
                width=10,
                font=("Consolas", 9, "bold"),
                bg="#181c2e",
                fg="#00f5d4",
                insertbackground="#00f5d4",
                bd=0,
                highlightthickness=1,
                highlightbackground="#22273d",
                highlightcolor="#00f5d4",
                justify=tk.CENTER
            )
            ent.grid(row=idx, column=1, sticky=tk.E, pady=3)

        cmd_preview_var = tk.StringVar()

        def update_cmd_preview(*args):
            cmd_preview_var.set(
                f"--split-pos={self.dialog_vars['tcp_split'].get()} --seqovl={self.dialog_vars['tcp_seqovl'].get()} "
                f"--ttl={self.dialog_vars['tcp_ttl'].get()} --repeats={self.dialog_vars['udp_repeats'].get()} --cutoff={self.dialog_vars['udp_cutoff'].get()}"
            )

        for v in self.dialog_vars.values():
            v.trace_add("write", update_cmd_preview)
        update_cmd_preview()

        preview_frame = tk.Frame(iframe, bg="#0d101d", bd=1, relief=tk.SOLID)
        preview_frame.pack(fill=tk.X, pady=(6, 8))
        tk.Label(preview_frame, textvariable=cmd_preview_var, font=("Consolas", 8), bg="#0d101d", fg="#00f5d4", padx=6, pady=4).pack(anchor=tk.W)

        btn_box = tk.Frame(iframe, bg="#111422")
        btn_box.pack(fill=tk.X, pady=(6, 0))

        RoundedButton(btn_box, text="⚡ Провести разовый тест", command=self._run_test_from_dialog, radius=6, bg_color="#7000ff", hover_bg="#8a2be2", width=160, height=24).pack(side=tk.LEFT, padx=2)
        RoundedButton(btn_box, text="✅ Применить", command=self._apply_and_close, radius=6, bg_color="#00f5d4", fg_color="#08090f", hover_bg="#00d4b8", width=100, height=24).pack(side=tk.LEFT, padx=2)
        RoundedButton(btn_box, text="❌ Отмена", command=self.destroy, radius=6, bg_color="#181c2e", hover_bg="#22273d", width=80, height=24).pack(side=tk.RIGHT, padx=2)

    def _apply_and_close(self):
        for k in self.dialog_vars:
            self.param_vars[k].set(self.dialog_vars[k].get())
        self.destroy()

    def _run_test_from_dialog(self):
        self._apply_and_close()
        if self.on_run_test_cb:
            self.on_run_test_cb()