"""Проверка обновлений и установка нового релиза через Inno Setup."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from version import __version__

GITHUB_REPO_OWNER = "FT-123"
GITHUB_REPO_NAME = "fuzze-winws"
RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/latest"
)
USER_AGENT = f"ZapretStrategyTuner/{__version__}"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

ProgressCallback = Callable[[int, int], None]


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    tag: str
    name: str
    notes: str
    installer_url: str
    installer_name: str
    checksums_url: str
    published_at: str = ""


def parse_version(value: str) -> tuple:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def _pick_assets(assets):
    installer = None
    checksums = None
    for asset in assets or []:
        name = str(asset.get("name", ""))
        if not name:
            continue
        if re.fullmatch(r"ZapretStrategyTuner-Setup-.+\.exe", name, re.IGNORECASE):
            installer = asset
        elif name.lower() == "sha256sums.txt":
            checksums = asset
    return installer, checksums


def parse_release(data: dict) -> Optional[UpdateInfo]:
    if not isinstance(data, dict):
        raise UpdateError("Некорректный ответ GitHub")
    tag = str(data.get("tag_name", ""))
    if not tag:
        raise UpdateError("В релизе нет tag_name")
    installer, checksums = _pick_assets(data.get("assets"))
    if not installer:
        raise UpdateError("В релизе нет установщика ZapretStrategyTuner-Setup-*.exe")
    if not checksums:
        raise UpdateError("В релизе нет SHA256SUMS.txt — обновление отменено")
    return UpdateInfo(
        version=tag.lstrip("v"),
        tag=tag,
        name=str(data.get("name", "")),
        notes=str(data.get("body", "")),
        installer_url=str(installer.get("browser_download_url", "")),
        installer_name=str(installer.get("name", "")),
        checksums_url=str(checksums.get("browser_download_url", "")),
        published_at=str(data.get("published_at", "")),
    )


def fetch_latest_release() -> Optional[UpdateInfo]:
    request = urllib.request.Request(
        RELEASE_API,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        if error.code == 403:
            raise UpdateError("GitHub API: превышен лимит запросов, попробуйте позже") from error
        raise UpdateError(f"GitHub API: HTTP {error.code}") from error
    except (OSError, ValueError) as error:
        raise UpdateError(f"Не удалось проверить обновления: {error}") from error
    return parse_release(data)


def check_for_update(current: str = __version__) -> Optional[UpdateInfo]:
    info = fetch_latest_release()
    if info is None:
        return None
    return info if is_newer(info.version, current) else None


def _download(url: str, destination: str, progress: Optional[ProgressCallback] = None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
    except (OSError, urllib.error.URLError) as error:
        raise UpdateError(f"Ошибка скачивания: {error}") from error


def parse_checksums(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            result[parts[1].lstrip("*")] = parts[0].lower()
    return result


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_installer(
    info: UpdateInfo, progress: Optional[ProgressCallback] = None
) -> str:
    if not info.installer_url or not info.checksums_url:
        raise UpdateError("В релизе не хватает ссылок на установщик/контрольные суммы")

    safe_name = os.path.basename(urllib.parse.unquote(info.installer_name))
    if not re.fullmatch(r"ZapretStrategyTuner-Setup-.+\.exe", safe_name, re.IGNORECASE):
        raise UpdateError("Подозрительное имя установщика")

    target_dir = os.path.join(tempfile.gettempdir(), "ZapretStrategyTuner-update")
    os.makedirs(target_dir, exist_ok=True)
    destination = os.path.join(target_dir, safe_name)
    partial = destination + ".part"

    _download(info.installer_url, partial, progress)

    request = urllib.request.Request(info.checksums_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            checksums = parse_checksums(response.read().decode("utf-8", errors="ignore"))
    except (OSError, urllib.error.URLError) as error:
        raise UpdateError(f"Не удалось скачать SHA256SUMS.txt: {error}") from error

    expected = checksums.get(safe_name)
    if not expected:
        raise UpdateError(f"В SHA256SUMS.txt нет хеша для {safe_name}")

    actual = file_sha256(partial)
    if actual.lower() != expected.lower():
        try:
            os.remove(partial)
        except OSError:
            pass
        raise UpdateError("SHA256 установщика не совпал — обновление отменено")

    os.replace(partial, destination)
    return destination


def build_update_script(installer_path: str, app_path: str, pid: Optional[int] = None) -> str:
    pid = pid or os.getpid()
    return rf"""@echo off
chcp 65001 >nul
set "PID={pid}"
set "SETUP={installer_path}"
set "APP={app_path}"
:wait_app
tasklist /FI "PID eq %PID%" /NH 2>nul | find "%PID%" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait_app
)
start "" /wait "%SETUP%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS
start "" "%APP%"
del /F /Q "%SETUP%" >nul 2>&1
del /F /Q "%~f0" >nul 2>&1
"""


def launch_update(installer_path: str) -> bool:
    """Запускает отдельный батник, который заменит приложение и перезапустит его."""
    if not (getattr(sys, "frozen", False) or "__compiled__" in globals()):
        return False
    if not os.path.isfile(installer_path):
        return False

    app_path = os.path.abspath(sys.executable)
    script_path = os.path.join(tempfile.gettempdir(), "ZapretStrategyTuner-update.bat")
    script = build_update_script(installer_path, app_path)
    with open(script_path, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(script)

    try:
        subprocess.Popen(
            ["cmd.exe", "/c", script_path],
            creationflags=_NO_WINDOW | _DETACHED | _NEW_GROUP,
            close_fds=True,
        )
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Восстановление base bats (оставлено из прежней версии)
# ---------------------------------------------------------------------------

def reset_base_bats_from_github(
    repo_owner: str = GITHUB_REPO_OWNER,
    repo_name: str = GITHUB_REPO_NAME,
    target_dir: str = None,
) -> tuple[bool, str, list[str]]:
    """Скачивает чистые .bat из папки ``base bats`` репозитория."""
    from config import APP_DIR

    if target_dir is None:
        target_dir = APP_DIR

    downloaded_files: list[str] = []
    known_bats = [
        "general (ALT).bat", "general (ALT2).bat", "general (ALT3).bat",
        "general (ALT4).bat", "general (ALT5).bat", "general (ALT6).bat",
        "general (ALT7).bat", "general (ALT8).bat", "general (ALT9).bat",
        "general (ALT10).bat", "general (ALT11).bat", "general (ALT12).bat",
        "general (EXP).bat", "general (FAKE TLS AUTO).bat",
        "general (FAKE TLS AUTO ALT).bat", "general (FAKE TLS AUTO ALT2).bat",
        "general (FAKE TLS AUTO ALT3).bat", "general (SIMPLE FAKE).bat",
        "general (SIMPLE FAKE ALT).bat", "general (SIMPLE FAKE ALT2).bat",
    ]

    items_to_download: list[tuple[str, str]] = []
    try:
        api_url = (
            f"https://api.github.com/repos/{repo_owner}/{repo_name}"
            f"/contents/base%20bats?ref=master"
        )
        request = urllib.request.Request(
            api_url, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        if isinstance(data, list):
            for item in data:
                name = str(item.get("name", ""))
                if item.get("type") == "file" and name.lower().endswith(".bat"):
                    download_url = item.get("download_url") or (
                        f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/master/"
                        f"base%20bats/{urllib.parse.quote(name)}"
                    )
                    items_to_download.append((name, download_url))
    except (urllib.error.URLError, ValueError):
        pass

    if not items_to_download:
        for filename in known_bats:
            raw_url = (
                f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/master/"
                f"base%20bats/{urllib.parse.quote(filename)}"
            )
            items_to_download.append((filename, raw_url))

    for filename, download_url in items_to_download:
        try:
            request = urllib.request.Request(
                download_url, headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                content = response.read()
            if not content:
                continue
            out_path = os.path.join(target_dir, os.path.basename(filename))
            with open(out_path, "wb") as handle:
                handle.write(content)
            backup_path = out_path + ".bak"
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
            downloaded_files.append(os.path.basename(filename))
        except (urllib.error.URLError, OSError):
            continue

    if not downloaded_files:
        return False, "Не удалось скачать файлы из репозитория GitHub.", []
    return True, f"Успешно восстановлено {len(downloaded_files)} файлов .bat!", downloaded_files
