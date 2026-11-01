"""Пути приложения и значения по умолчанию.

Работает и из исходников, и из однофайловой сборки (PyInstaller/Nuitka).
"""
import json
import os
import sys

_IS_FROZEN = getattr(sys, "frozen", False) or "__compiled__" in globals()

if _IS_FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

HISTORY_FILE = os.path.join(APP_DIR, "history.json")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
BASE_BATS_DIR = os.path.join(APP_DIR, "base bats")
DEFAULT_STRATEGY_NAME = "general (ALT11).bat"
DEFAULT_STRATEGY = os.path.join(APP_DIR, DEFAULT_STRATEGY_NAME)
ZAPRET2_STRATEGY = os.path.join(APP_DIR, "general (ZAPRET2).bat")
AUTO_STRATEGY = os.path.join(APP_DIR, "auto-config.bat")
LISTS_DIR = os.path.join(APP_DIR, "lists")
USER_LISTS_DIR = LISTS_DIR
RUNTIME_DIR = os.path.join(APP_DIR, "runtime")
LOGS_DIR = os.path.join(APP_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "fuzzer_error.log")
USER_INCLUDE_LIST = os.path.join(LISTS_DIR, "list-general-user.txt")
USER_EXCLUDE_LIST = os.path.join(LISTS_DIR, "list-exclude-user.txt")


def ensure_app_dirs() -> None:
    """Создаёт рабочие каталоги и пустые личные списки при первом запуске."""
    for directory in (LISTS_DIR, RUNTIME_DIR, LOGS_DIR):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
    for path in (USER_INCLUDE_LIST, USER_EXCLUDE_LIST):
        try:
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8", newline="\n"):
                    pass
        except OSError:
            pass


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def update_settings(**values) -> None:
    data = load_settings()
    data.update(values)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(SETTINGS_FILE)), exist_ok=True)
        temp_path = SETTINGS_FILE + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, SETTINGS_FILE)
    except OSError:
        pass


def ensure_default_strategy() -> str:
    """Гарантирует, что стратегия по умолчанию лежит рядом с приложением.

    Порядок: уже настроенный auto-config → winws2-стратегия (если движок есть)
    → чистый general (ALT11).bat → копия из base bats.
    """
    if os.path.isfile(AUTO_STRATEGY):
        return AUTO_STRATEGY

    winws2_ready = all(
        os.path.isfile(os.path.join(APP_DIR, relative))
        for relative in (
            os.path.join("bin", "winws2.exe"),
            os.path.join("lua", "zapret-lib.lua"),
            os.path.join("lua", "zapret-antidpi.lua"),
        )
    )
    if winws2_ready and os.path.isfile(ZAPRET2_STRATEGY):
        return ZAPRET2_STRATEGY

    if os.path.isfile(DEFAULT_STRATEGY):
        return DEFAULT_STRATEGY

    source = os.path.join(BASE_BATS_DIR, DEFAULT_STRATEGY_NAME)
    if os.path.isfile(source):
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(source, "rb") as src, open(DEFAULT_STRATEGY, "wb") as dst:
                dst.write(src.read())
        except OSError:
            pass

    return DEFAULT_STRATEGY
