"""Подготовка движка zapret/winws для сборки установщика.

В GitHub Actions исходники upstream подтягиваются через actions/checkout
в build/upstream/*. Локально скрипт может скачать их сам.

Пример:
    python scripts/prepare_engine.py
    python scripts/prepare_engine.py --flowseal-dir build/upstream/flowseal ^
        --zapret2-dir build/upstream/zapret2
"""
import argparse
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "build" / "engine-cache"
FLOWSEAL_URL = (
    "https://codeload.github.com/Flowseal/zapret-discord-youtube/"
    "zip/refs/tags/1.9.6"
)
ZAPRET2_URL = (
    "https://github.com/bol-van/zapret2/releases/download/v1.0.4/"
    "zapret2-v1.0.4.zip"
)
PERSONAL_LISTS = {
    "list-general-user.txt",
    "list-exclude-user.txt",
    "ipset-exclude-user.txt",
}


def log(message: str) -> None:
    print(f"[engine] {message}")


def find_payload(path: Path, marker: str) -> Path:
    """Возвращает каталог, внутри которого лежит marker."""
    if (path / marker).exists():
        return path
    candidates = [item for item in path.iterdir() if item.is_dir()]
    for candidate in candidates:
        if (candidate / marker).exists():
            return candidate
    raise FileNotFoundError(f"В {path} не найден {marker}")


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        log(f"использую кэш {destination.name}")
        return
    log(f"скачиваю {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "zapret-tuner-build"})
    with urllib.request.urlopen(request, timeout=120) as response, open(destination, "wb") as handle:
        shutil.copyfileobj(response, handle)


def extract(archive: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(target)
    entries = [item for item in target.iterdir() if item.is_dir()]
    if len(entries) == 1:
        return entries[0]
    return target


def copy_ignore_personal(directory, names):
    ignored = set()
    for name in names:
        if (
            name in PERSONAL_LISTS
            or name.endswith(".bak")
            or name.endswith(".bat1")
            or name.endswith(".back")
            or name.endswith(".backup")
        ):
            ignored.add(name)
    return ignored


def copy_merge(source: Path, destination: Path, ignore=None) -> None:
    if not source.is_dir():
        log(f"пропуск {source}")
        return
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)


def copy_general_bats(source: Path, destination: Path) -> None:
    for bat in source.glob("general*.bat"):
        if bat.suffix.lower() != ".bat":
            continue
        if bat.name.lower() == "auto-config.bat":
            continue
        shutil.copy2(bat, destination / bat.name)


def find_binaries(path: Path) -> Path:
    direct = path / "binaries" / "windows-x86_64"
    if direct.is_dir():
        return direct
    for candidate in path.rglob("windows-x86_64"):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"В {path} не найден windows-x86_64")


def prepare(flowseal_dir: Path, zapret2_dir: Path, dest: Path) -> None:
    flowseal = find_payload(flowseal_dir, "service.bat")
    zapret2 = find_payload(zapret2_dir, "lua")
    binaries = find_binaries(zapret2)

    log("копирую winws1-ассеты Flowseal")
    copy_merge(flowseal / "bin", dest / "bin")
    copy_merge(
        flowseal / "lists",
        dest / "lists",
        ignore=copy_ignore_personal,
    )
    copy_merge(flowseal / "utils", dest / "utils")
    for name in ("service.bat",):
        source = flowseal / name
        if source.is_file():
            shutil.copy2(source, dest / name)
    copy_general_bats(flowseal, dest)
    if (flowseal / "base bats").is_dir():
        copy_merge(flowseal / "base bats", dest / "base bats")

    log("копирую winws2/Lua-ассеты zapret2")
    copy_merge(binaries, dest / "bin")
    copy_merge(zapret2 / "lua", dest / "lua")
    copy_merge(zapret2 / "files" / "fake", dest / "files" / "fake")

    template = ROOT / "templates" / "general (ZAPRET2).bat"
    if template.is_file():
        shutil.copy2(template, dest / "general (ZAPRET2).bat")
        log("скопирован general (ZAPRET2).bat")
    else:
        log("[!] templates/general (ZAPRET2).bat не найден")

    for name in PERSONAL_LISTS:
        path = dest / "lists" / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    log("готово: bin, lists, lua, files, service.bat, general*.bat")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flowseal-dir", type=Path)
    parser.add_argument("--zapret2-dir", type=Path)
    parser.add_argument("--dest", type=Path, default=ROOT)
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()

    if args.force_download:
        shutil.rmtree(CACHE, ignore_errors=True)

    if args.flowseal_dir:
        flowseal_dir = args.flowseal_dir
    else:
        archive = CACHE / "flowseal-1.9.6.zip"
        download(FLOWSEAL_URL, archive)
        flowseal_dir = extract(archive, CACHE / "flowseal-1.9.6")

    if args.zapret2_dir:
        zapret2_dir = args.zapret2_dir
    else:
        archive = CACHE / "zapret2-v1.0.4.zip"
        download(ZAPRET2_URL, archive)
        zapret2_dir = extract(archive, CACHE / "zapret2-v1.0.4")

    try:
        prepare(Path(flowseal_dir), Path(zapret2_dir), Path(args.dest))
    except Exception as error:
        log(f"ошибка: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
