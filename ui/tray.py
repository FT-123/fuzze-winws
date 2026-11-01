import tkinter as tk
from typing import Callable, Optional

from ui import theme
from ui.theme import font

try:
    import pystray
    from PIL import Image, ImageDraw

    HAS_PYSTRAY = True
except ImportError:  # pragma: no cover - зависит от окружения
    HAS_PYSTRAY = False


class MiniTrayOverlay(tk.Toplevel):
    """Компактный оверлей вместо системного трея, если pystray недоступен."""

    def __init__(self, parent, on_restore: Callable[[], None], on_exit: Callable[[], None]):
        super().__init__(parent)
        self.on_restore_cb = on_restore
        self.on_exit_cb = on_exit

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=theme.BG)

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"210x44+{screen_w - 224}+{screen_h - 92}")

        frame = tk.Frame(self, bg=theme.SURFACE, highlightbackground=theme.BORDER, highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="✦ Zapret Tuner",
            font=font(9, "bold"),
            bg=theme.SURFACE,
            fg=theme.INK,
        ).pack(side=tk.LEFT, padx=10)

        tk.Button(
            frame,
            text="Выход",
            font=font(8),
            bg=theme.SURFACE,
            fg=theme.RED,
            activebackground=theme.SURFACE_ALT,
            activeforeground=theme.RED,
            bd=0,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._exit,
        ).pack(side=tk.RIGHT, padx=(0, 8))

        tk.Button(
            frame,
            text="Открыть",
            font=font(8, "bold"),
            bg=theme.SURFACE,
            fg=theme.ACCENT,
            activebackground=theme.SURFACE_ALT,
            activeforeground=theme.ACCENT,
            bd=0,
            relief=tk.FLAT,
            cursor="hand2",
            command=self._restore,
        ).pack(side=tk.RIGHT, padx=(0, 4))

    def _restore(self) -> None:
        self.destroy()
        self.on_restore_cb()

    def _exit(self) -> None:
        self.destroy()
        self.on_exit_cb()


class TrayManager:
    """Сворачивание окна в системный трей (pystray) с fallback-оверлеем."""

    def __init__(self, root: tk.Tk, on_restore: Callable[[], None], on_exit: Callable[[], None]):
        self.root = root
        self.on_restore = on_restore
        self.on_exit = on_exit
        self.icon = None
        self.mini_overlay: Optional[MiniTrayOverlay] = None

    def _create_pystray_image(self):
        image = Image.new("RGB", (64, 64), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse([8, 8, 56, 56], fill=(232, 240, 254))
        draw.polygon([(32, 14), (37, 27), (50, 32), (37, 37), (32, 50), (27, 37), (14, 32), (27, 27)], fill=(26, 115, 232))
        return image

    def _call_on_main_thread(self, callback: Callable[[], None]) -> None:
        """pystray работает в своём потоке — Tk-вызовы только через after()."""
        try:
            self.root.after(0, callback)
        except (tk.TclError, RuntimeError):
            pass

    def _start_pystray(self) -> None:
        if not HAS_PYSTRAY or self.icon is not None:
            return

        menu = pystray.Menu(
            pystray.MenuItem(
                "Открыть Zapret Tuner",
                lambda icon, item: self._call_on_main_thread(self.on_restore),
            ),
            pystray.MenuItem(
                "Выход",
                lambda icon, item: self._call_on_main_thread(self.on_exit),
            ),
        )
        self.icon = pystray.Icon(
            "zapret_fuzzer",
            self._create_pystray_image(),
            "Zapret Strategy Tuner",
            menu,
        )
        self.icon.run_detached()

    def minimize_to_tray(self) -> None:
        self.root.withdraw()
        if HAS_PYSTRAY:
            self._start_pystray()
        elif not self.mini_overlay or not self.mini_overlay.winfo_exists():
            self.mini_overlay = MiniTrayOverlay(self.root, self.on_restore, self.on_exit)

    def restore_from_tray(self) -> None:
        self.stop()
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None

        if self.mini_overlay is not None and self.mini_overlay.winfo_exists():
            self.mini_overlay.destroy()
        self.mini_overlay = None
