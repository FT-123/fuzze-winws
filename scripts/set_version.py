"""Устанавливает версию приложения из аргумента или тега.

Пример: python scripts/set_version.py v1.2.3
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "version.py"


def main() -> int:
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    version = raw.strip().lstrip("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        print(f"Некорректная версия: {raw!r}")
        return 1
    VERSION_FILE.write_text(
        '"""Единая версия приложения."""\n\n'
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    print(f"version.py -> {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
