import tkinter as tk
import threading

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False


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