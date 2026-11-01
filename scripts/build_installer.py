"""Сборка fuzzer.exe и установщика Inno Setup.

Примеры:
    python scripts/build_installer.py
    python scripts/build_installer.py --skip-build
    python scripts/build_installer.py --skip-inno
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = BUILD / "dist"
STAGE = BUILD / "stage"
INSTALLER = ROOT / "installer"
ASSETS = ROOT / "assets"

sys.path.insert(0, str(ROOT))
from version import __version__  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def log(message: str) -> None:
    print(f"[build] {message}")


def clean_stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True, exist_ok=True)


def version_info_file(version: str) -> Path:
    parts = [int(part) for part in (version.split(".") + ["0", "0", "0", "0"])[:4]]
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tuple(parts)},
    prodvers={tuple(parts)},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'FT-123'),
        StringStruct('FileDescription', 'Zapret Strategy Tuner'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'fuzzer'),
        StringStruct('OriginalFilename', 'fuzzer.exe'),
        StringStruct('ProductName', 'Zapret Strategy Tuner'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path = BUILD / "version_info.txt"
    path.write_text(content, encoding="utf-8")
    return path


def build_exe(version: str) -> Path:
    log("сборка fuzzer.exe через PyInstaller")
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--uac-admin",
        "--name",
        "fuzzer",
        "--icon",
        str(ASSETS / "icon.ico"),
        "--version-file",
        str(version_info_file(version)),
        "--collect-submodules",
        "ui",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD / "pyinstaller"),
        "--specpath",
        str(BUILD),
        str(ROOT / "main.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    exe = DIST / "fuzzer.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"PyInstaller не создал {exe}")
    return exe


def copy_tree(source: Path, destination: Path, ignore=None) -> None:
    if not source.is_dir():
        log(f"пропуск отсутствующего каталога: {source}")
        return
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)


def stage_files(exe: Path) -> None:
    log("подготовка build/stage")
    clean_stage()
    shutil.copy2(exe, STAGE / "fuzzer.exe")

    personal = {
        "list-general-user.txt",
        "list-exclude-user.txt",
        "ipset-exclude-user.txt",
    }

    def ignore_lists(directory, names):
        return {
            name for name in names
            if name in personal or name.endswith(".back") or name.endswith(".backup")
        }

    def ignore_bin(directory, names):
        return {name for name in names if name == "_winws1_backup"}

    copy_tree(ROOT / "bin", STAGE / "bin", ignore=ignore_bin)
    copy_tree(ROOT / "lua", STAGE / "lua")
    copy_tree(ROOT / "files", STAGE / "files")
    copy_tree(ROOT / "lists", STAGE / "lists", ignore=ignore_lists)
    copy_tree(ROOT / "utils", STAGE / "utils")
    shutil.rmtree(STAGE / "utils" / "test results", ignore_errors=True)
    copy_tree(ROOT / "base bats", STAGE / "base bats")
    copy_tree(ROOT / "docs", STAGE / "docs")

    for name in ("service.bat", "LICENSE.txt", "THIRD_PARTY.md", "README.md"):
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, STAGE / name)

    for bat in ROOT.glob("general*.bat"):
        if bat.name.lower() == "auto-config.bat":
            continue
        shutil.copy2(bat, STAGE / bat.name)

    # В установщик не должны попасть личные данные и результаты запусков.
    for forbidden in (
        "settings.json",
        "history.json",
        "auto-config.bat",
        "_fuzzer_temp.bat",
        "_fuzzer_run.bat",
    ):
        path = STAGE / forbidden
        if path.exists():
            path.unlink()

    log(f"stage готов: {STAGE}")


def find_iscc() -> Path | None:
    candidates = [
        os.environ.get("ISCC"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        shutil.which("ISCC.exe"),
        shutil.which("iscc"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def build_installer(version: str) -> Path:
    iscc = find_iscc()
    if not iscc:
        raise FileNotFoundError(
            "Inno Setup не найден. Установите Inno Setup 6 или задайте ISCC."
        )

    log("сборка установщика")
    output_dir = ROOT / "dist" / "installer"
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(iscc),
        f"/DMyAppVersion={version}",
        str(INSTALLER / "ZapretTuner.iss"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    setup = output_dir / f"ZapretStrategyTuner-Setup-{version}.exe"
    if not setup.is_file():
        raise FileNotFoundError(f"Установщик не создан: {setup}")
    return setup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true", help="не собирать fuzzer.exe")
    parser.add_argument("--skip-inno", action="store_true", help="только подготовить stage")
    parser.add_argument("--version", default=__version__)
    args = parser.parse_args()

    try:
        if args.skip_build:
            exe = DIST / "fuzzer.exe"
            if not exe.is_file():
                raise FileNotFoundError(f"нет готового exe: {exe}")
            log(f"использую готовый exe: {exe}")
        else:
            exe = build_exe(args.version)

        stage_files(exe)

        if args.skip_inno:
            log("Inno Setup пропущен")
            return 0

        setup = build_installer(args.version)
        log(f"готово: {setup}")
        return 0
    except subprocess.CalledProcessError as error:
        log(f"команда завершилась с ошибкой: {error}")
        return 1
    except Exception as error:
        log(f"ошибка: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
