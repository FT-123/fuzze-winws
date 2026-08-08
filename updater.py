import urllib.parse
import urllib.request
import json
import os
import sys
import subprocess

GITHUB_REPO_OWNER = "FT-123"
GITHUB_REPO_NAME = "fuzze-winws"


def execute_self_update(new_exe_data: bytes, current_exe_path: str = None) -> bool:
    """
    Создает временный файл с новым .exe, спавнит скрытый батник _updater.bat,
    который завершает текущий процесс fuzzer.exe, подменяет старый fuzzer.exe на новый,
    запускает новый fuzzer.exe, батник закрывается и удаляется без следов.
    """
    if current_exe_path is None:
        current_exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath("fuzzer.exe")

    current_pid = os.getpid()
    exe_dir = os.path.dirname(os.path.abspath(current_exe_path))
    new_exe_path = os.path.join(exe_dir, "_fuzzer_new.exe")
    bat_script_path = os.path.join(exe_dir, "_updater.bat")

    try:
        # 1. Сохраняем скачанный бинарник во временный файл
        with open(new_exe_path, "wb") as f:
            f.write(new_exe_data)

        # 2. Создаем батник скрытого обновления
        bat_content = f"""@echo off
chcp 65001 >nul
timeout /t 1 /nobreak >nul
taskkill /F /PID {current_pid} >nul 2>&1
taskkill /F /IM fuzzer.exe >nul 2>&1
:wait_loop
tasklist /FI "PID eq {current_pid}" 2>NUL | find /I "{current_pid}" >NUL
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)
move /Y "{new_exe_path}" "{current_exe_path}" >nul 2>&1
start "" "{current_exe_path}"
del /F /Q "%~f0" >nul 2>&1
"""
        with open(bat_script_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        # 3. Запускаем батник скрыто в фоновом режиме
        if os.name == 'nt':
            subprocess.Popen(["cmd.exe", "/c", bat_script_path], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen(["/bin/sh", bat_script_path])

        # 4. Завершаем текущий процесс fuzzer.exe
        sys.exit(0)
        return True

    except Exception as e:
        print(f"Ошибка самообновления: {e}")
        return False


def check_and_download_github_exe(repo_owner: str = GITHUB_REPO_OWNER,
                                  repo_name: str = GITHUB_REPO_NAME) -> tuple[bool, str]:
    """
    Скачивает fuzzer.exe из последнего релиза GitHub (https://github.com/FT-123/fuzze-winws)
    и запускает процедуру замены.
    """
    try:
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Zapret-Fuzzer-Updater/1.0"}
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                return False, f"Ошибка GitHub API: HTTP {response.status}"
            data = json.loads(response.read().decode('utf-8'))

        assets = data.get("assets", [])
        exe_url = None
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".exe") or "fuzzer" in name:
                exe_url = asset.get("browser_download_url")
                break

        if not exe_url:
            exe_url = data.get("zipball_url")

        if not exe_url:
            return False, "Файл fuzzer.exe не найден в релизе GitHub."

        exe_req = urllib.request.Request(
            exe_url,
            headers={"User-Agent": "Zapret-Fuzzer-Updater/1.0"}
        )
        with urllib.request.urlopen(exe_req, timeout=30) as exe_resp:
            new_exe_data = exe_resp.read()

        execute_self_update(new_exe_data)
        return True, "Обновление запущено!"

    except Exception as e:
        return False, f"Ошибка обновления: {str(e)}"


def reset_base_bats_from_github(repo_owner: str = GITHUB_REPO_OWNER,
                                repo_name: str = GITHUB_REPO_NAME,
                                target_dir: str = None) -> tuple[bool, str, list[str]]:
    """
    Скачивает чистые оригинальные .bat файлы из папки 'base bats' репозитория GitHub
    (https://github.com/FT-123/fuzze-winws/tree/master/base%20bats)
    и перезаписывает их в корневой папке приложения (рядом с fuzzer.exe).
    """
    if target_dir is None:
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath("fuzzer.exe")
        target_dir = os.path.dirname(os.path.abspath(exe_path))

    downloaded_files = []
    known_bats = [
        "general (ALT1).bat", "general (ALT2).bat", "general (ALT3).bat",
        "general (ALT4).bat", "general (ALT5).bat", "general (ALT6).bat",
        "general (ALT7).bat", "general (ALT8).bat", "general (ALT9).bat",
        "general (ALT10).bat", "general (ALT11).bat", "general.bat",
        "discord.bat", "youtube.bat"
    ]

    try:
        # 1. Запрашиваем через GitHub API содержимое папки 'base bats' на ветке master
        api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/base%20bats?ref=master"
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Zapret-Fuzzer-Updater/1.0"}
        )

        items_to_download = []
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    if isinstance(data, list):
                        for item in data:
                            if item.get("type") == "file" and item.get("name", "").lower().endswith(".bat"):
                                d_url = item.get(
                                    "download_url") or f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/master/base%20bats/{urllib.parse.quote(item.get('name'))}"
                                items_to_download.append((item.get("name"), d_url))
        except Exception:
            # Фолбэк при сбое API (например, из-за лимита запросов GitHub)
            pass

        # Если API не вернул данные, используем список известных базовых файлов
        if not items_to_download:
            for fname in known_bats:
                encoded_fname = urllib.parse.quote(fname)
                raw_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/master/base%20bats/{encoded_fname}"
                items_to_download.append((fname, raw_url))

        # 2. Скачиваем и перезаписываем каждый .bat файл
        for fname, d_url in items_to_download:
            try:
                file_req = urllib.request.Request(
                    d_url,
                    headers={"User-Agent": "Zapret-Fuzzer-Updater/1.0"}
                )
                with urllib.request.urlopen(file_req, timeout=12) as f_resp:
                    if f_resp.status == 200:
                        content = f_resp.read()
                        out_path = os.path.join(target_dir, fname)
                        with open(out_path, "wb") as f_out:
                            f_out.write(content)

                        # Удаляем старый .bak бэкап, чтобы движок заново отсчитывал бэкап от чистого базового файла
                        bak_path = out_path + ".bak"
                        if os.path.exists(bak_path):
                            try:
                                os.remove(bak_path)
                            except Exception:
                                pass

                        downloaded_files.append(fname)
            except Exception:
                continue

        if not downloaded_files:
            return False, "Не удалось скачать файлы из репозитория GitHub.", []

        return True, f"Успешно восстановлено {len(downloaded_files)} файлов .bat из 'base bats'!", downloaded_files

    except Exception as e:
        return False, f"Ошибка восстановления базовых батников: {str(e)}", []

