"""Личные списки доменов пользователя.

* ``list-general-user.txt`` — домены, которые нужно обходить;
* ``list-exclude-user.txt`` — домены, которые нельзя трогать.

Файлы лежат рядом с приложением (в установленной версии — в LocalAppData),
поэтому запись не требует прав администратора.
"""
import os
from typing import Iterable, List, Tuple

from validators import is_valid_domain

INCLUDE = "include"
EXCLUDE = "exclude"

FILES = {
    INCLUDE: "list-general-user.txt",
    EXCLUDE: "list-exclude-user.txt",
}


def _normalize(value: str) -> str:
    return str(value).strip().lower()


class UserLists:
    def __init__(self, lists_dir: str):
        self.lists_dir = os.path.abspath(lists_dir)

    def path(self, kind: str) -> str:
        return os.path.join(self.lists_dir, FILES[kind])

    def ensure(self) -> None:
        os.makedirs(self.lists_dir, exist_ok=True)
        for kind in FILES:
            path = self.path(kind)
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8", newline="\n"):
                    pass

    def read_lines(self, kind: str) -> List[str]:
        self.ensure()
        try:
            with open(self.path(kind), "r", encoding="utf-8", errors="ignore") as handle:
                return [line.rstrip("\r\n") for line in handle]
        except OSError:
            return []

    def load(self, kind: str) -> List[str]:
        """Только валидные домены, без комментариев и дублей."""
        result: List[str] = []
        seen = set()
        for line in self.read_lines(kind):
            value = _normalize(line)
            if not value or value.startswith("#"):
                continue
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def save_lines(self, kind: str, lines: Iterable[str]) -> Tuple[int, List[str]]:
        """Сохраняет строки, сохраняя комментарии и отбрасывая мусор.

        Возвращает (количество доменов, список некорректных строк).
        """
        self.ensure()
        saved: List[str] = []
        invalid: List[str] = []
        seen = set()

        for raw in lines:
            line = str(raw).strip()
            if not line:
                continue
            if line.startswith("#"):
                saved.append(line)
                continue
            value = _normalize(line)
            if not is_valid_domain(value):
                invalid.append(line)
                continue
            if value in seen:
                continue
            seen.add(value)
            saved.append(value)

        # Комментарии не должны дублироваться и висеть в конце без доменов.
        cleaned: List[str] = []
        seen_comments = set()
        for line in saved:
            if line.startswith("#"):
                if line in seen_comments:
                    continue
                seen_comments.add(line)
            cleaned.append(line)

        temp_path = self.path(kind) + ".tmp"
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            for line in cleaned:
                handle.write(line + "\n")
        os.replace(temp_path, self.path(kind))
        return len(seen), invalid

    def save(self, kind: str, domains: Iterable[str]) -> Tuple[int, List[str]]:
        return self.save_lines(kind, domains)

    def add(self, kind: str, domains: Iterable[str]) -> Tuple[int, List[str]]:
        lines = self.read_lines(kind)
        existing = {_normalize(line) for line in lines if line.strip() and not line.startswith("#")}
        added = 0
        for domain in domains:
            value = _normalize(domain)
            if not value or value in existing or not is_valid_domain(value):
                continue
            lines.append(value)
            existing.add(value)
            added += 1
        saved, invalid = self.save_lines(kind, lines)
        return added, invalid

    def remove(self, kind: str, domains: Iterable[str]) -> int:
        targets = {_normalize(domain) for domain in domains if _normalize(domain)}
        lines = self.read_lines(kind)
        kept = [
            line for line in lines
            if line.startswith("#") or _normalize(line) not in targets
        ]
        self.save_lines(kind, kept)
        return len(lines) - len(kept)
