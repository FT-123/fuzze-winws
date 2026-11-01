"""Создаёт SHA256SUMS.txt для файлов релиза."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIR = ROOT / "dist" / "installer"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    version = sys.argv[1].lstrip("v") if len(sys.argv) > 1 else ""
    candidates = []
    if version:
        candidates.append(INSTALLER_DIR / f"ZapretStrategyTuner-Setup-{version}.exe")
    candidates.extend(sorted(INSTALLER_DIR.glob("ZapretStrategyTuner-Setup-*.exe")))
    files = []
    for path in candidates:
        if path.is_file() and path not in files:
            files.append(path)
    if not files:
        print("Не найден установщик в dist/installer")
        return 1
    lines = [f"{sha256(path)}  {path.name}" for path in files]
    output = INSTALLER_DIR / "SHA256SUMS.txt"
    output.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(output)
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
