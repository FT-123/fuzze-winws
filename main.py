import ctypes
import os
import subprocess
import sys
import traceback

# Добавляем директорию скрипта в sys.path для корректного импорта модулей
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import tkinter as tk
from tkinter import messagebox

from config import (
    LOG_FILE,
    LOGS_DIR,
    ensure_app_dirs,
    ensure_default_strategy,
)
from ui import ZapretFuzzerApp

LOG_PATH = LOG_FILE


def _is_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _message(text: str, flags: int) -> int:
    try:
        return int(ctypes.windll.user32.MessageBoxW(None, text, "Zapret Strategy Tuner", flags))
    except Exception:
        return 0


def _ensure_admin() -> bool:
    """Требует запуск от администратора (winws/WinDivert).

    В собранном exe это дополнительно делает манифест requireAdministrator,
    но для запуска из исходников проверка нужна здесь.
    """
    if _is_admin():
        return True

    answer = _message(
        "Для запуска winws/WinDivert нужны права администратора.\n\n"
        "Перезапустить приложение с правами администратора?",
        4 | 0x30,  # MB_YESNO | MB_ICONWARNING
    )
    if answer != 6:  # IDYES
        return False

    frozen = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
    if frozen:
        executable = sys.executable
        arguments = subprocess.list2cmdline(sys.argv[1:])
    else:
        executable = sys.executable
        arguments = subprocess.list2cmdline(sys.argv)

    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, arguments, None, 1
        )
    except Exception as error:
        _message(f"Не удалось перезапустить от администратора:\n{error}", 0x10)
        return False

    if result <= 32:
        _message(
            "Не удалось запросить права администратора.\n"
            "Запустите приложение через «Запуск от имени администратора».",
            0x10,
        )
        return False
    return False


def _log_exception(exc_type, exc_value, exc_tb) -> None:
    text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass
    print(text, file=sys.stderr)


def main() -> None:
    ensure_app_dirs()
    if not _ensure_admin():
        return

    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    ensure_default_strategy()
    root = tk.Tk()

    def report_callback_exception(exc_type, exc_value, exc_tb):
        _log_exception(exc_type, exc_value, exc_tb)
        try:
            messagebox.showerror(
                "Ошибка приложения",
                f"{exc_value}\n\nПодробности записаны в:\n{LOG_PATH}",
            )
        except tk.TclError:
            pass

    root.report_callback_exception = report_callback_exception
    ZapretFuzzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _log_exception(*sys.exc_info())
        raise
