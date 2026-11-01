"""Пресеты приложений, история и вспомогательные функции поиска хостов."""
import json
import os
import re
import subprocess
from typing import Dict, List, Optional
from urllib.parse import urlparse

from config import HISTORY_FILE
from validators import is_valid_domain, is_valid_public_ip  # noqa: F401 (реэкспорт для тестов)

# База официальных доменов популярных заблокированных / замедляемых сервисов.
DEFAULT_GAME_PRESETS: Dict[str, Dict[str, object]] = {
    "Discord": {
        "description": "Discord голос, чаты, CDN, RTC и медиа",
        "domains": [
            "discord.com",
            "discord.gg",
            "discord.media",
            "discordapp.com",
            "discordapp.net",
            "discordcdn.com",
            "cdn.discordapp.com",
            "media.discordapp.net",
            "router.discordapp.net",
            "gateway.discord.gg",
            "discordapp.io",
            "discord.co",
            "discord.dev",
            "discord.statuspage.io",
            "dis.gd",
        ],
    },
    "YouTube": {
        "description": "YouTube видео и CDN сервера (googlevideo)",
        "domains": [
            "youtube.com",
            "googlevideo.com",
            "ytimg.com",
            "youtu.be",
            "youtubei.googleapis.com",
            "yt3.ggpht.com",
            "www.youtube.com",
        ],
    },
    "Telegram": {
        "description": "Telegram мессенджер, голос и веб-версия",
        "domains": [
            "t.me",
            "telegram.org",
            "telegram.me",
            "web.telegram.org",
            "api.telegram.org",
        ],
    },
    "Steam": {
        "description": "Steam магазин, сообщество и инвентарь",
        "domains": [
            "steampowered.com",
            "steamcommunity.com",
            "steamstatic.com",
            "steamcontent.com",
        ],
    },
    "Twitch": {
        "description": "Twitch стримы и чаты",
        "domains": ["twitch.tv", "ttvnw.net", "jtvnw.net"],
    },
    "ChatGPT / OpenAI": {
        "description": "ChatGPT и API OpenAI",
        "domains": [
            "chatgpt.com",
            "openai.com",
            "oaistatic.com",
            "oaiusercontent.com",
        ],
    },
    "Instagram & Meta": {
        "description": "Instagram, Facebook и CDN",
        "domains": ["instagram.com", "cdninstagram.com", "facebook.com", "fbcdn.net"],
    },
    "Twitter / X": {
        "description": "X (Twitter) и медиа-сервера",
        "domains": ["x.com", "twitter.com", "twimg.com"],
    },
    "Notion": {
        "description": "Notion заметки и базы знаний",
        "domains": ["notion.so", "notion.site", "notion.new"],
    },
    "Spotify": {
        "description": "Spotify музыка и подкасты",
        "domains": ["spotify.com", "scdn.co", "spotifycdn.com"],
    },
    "Gemini": {
        "description": "Google Gemini, AI Studio и Vertex AI",
        "domains": [
            "generativelanguage.googleapis.com",
            "us-central1-aiplatform.googleapis.com",
            "europe-west3-aiplatform.googleapis.com",
            "gemini.google.com",
            "aistudio.google.com",
            "accounts.google.com",
            "myactivity.google.com",
            "workspace.google.com",
        ],
    },
}

_KNOWN_ALIASES: Dict[str, List[str]] = {
    "discord": ["discord.com", "discord.gg", "discord.media", "discordapp.com", "discordapp.net", "cdn.discordapp.com", "media.discordapp.net", "gateway.discord.gg", "router.discordapp.net"],
    "youtube": ["youtube.com", "googlevideo.com", "ytimg.com", "youtu.be", "youtubei.googleapis.com", "yt3.ggpht.com"],
    "telegram": ["t.me", "telegram.org", "telegram.me", "web.telegram.org", "api.telegram.org"],
    "steam": ["steampowered.com", "steamcommunity.com", "steamcontent.com", "steamstatic.com"],
    "twitch": ["twitch.tv", "ttvnw.net", "jtvnw.net"],
    "chatgpt": ["chatgpt.com", "openai.com", "oaistatic.com", "oaiusercontent.com"],
    "openai": ["chatgpt.com", "openai.com", "oaistatic.com", "oaiusercontent.com"],
    "instagram": ["instagram.com", "cdninstagram.com"],
    "facebook": ["facebook.com", "fbcdn.net"],
    "twitter": ["x.com", "twitter.com", "twimg.com"],
    "x": ["x.com", "twitter.com", "twimg.com"],
    "notion": ["notion.so", "notion.site", "notion.new"],
    "spotify": ["spotify.com", "scdn.co", "spotifycdn.com"],
    "rutracker": ["rutracker.org", "rutracker.cc", "rutracker.net"],
    "genshin": ["hoyoverse.com", "mihoyo.com", "genshinimpact.com"],
    "apex": ["ea.com", "respawn.com"],
    "valorant": ["riotgames.com", "pvp.net"],
    "minecraft": ["minecraft.net", "mojang.com"],
    "gemini": ["gemini.google.com", "generativelanguage.googleapis.com", "aistudio.google.com"],
}


# ---------------------------------------------------------------------------
# История (пресеты + успешные/неуспешные сессии подбора)
# ---------------------------------------------------------------------------

def _dedupe(values) -> List[str]:
    seen = set()
    result = []
    for value in values:
        item = str(value).strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            result.append(item)
    return result


def _empty_store() -> Dict[str, object]:
    return {"presets": {}, "sessions": []}


def _read_store() -> Dict[str, object]:
    """Читает history.json и мигрирует старый формат {app: [hosts]}."""
    if not os.path.isfile(HISTORY_FILE):
        return _empty_store()

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return _empty_store()

    if not isinstance(raw, dict):
        return _empty_store()

    if "presets" in raw or "sessions" in raw:
        presets = raw.get("presets")
        sessions = raw.get("sessions")
        return {
            "presets": presets if isinstance(presets, dict) else {},
            "sessions": sessions if isinstance(sessions, list) else [],
        }

    # Старый формат: { "Discord": ["discord.com", ...], ... }
    legacy = {
        str(name): _dedupe(hosts)
        for name, hosts in raw.items()
        if isinstance(hosts, list)
    }
    return {"presets": legacy, "sessions": []}


def _write_store(store: Dict[str, object]) -> None:
    directory = os.path.dirname(os.path.abspath(HISTORY_FILE))
    os.makedirs(directory, exist_ok=True)
    temp_path = HISTORY_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(store, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, HISTORY_FILE)


def load_history() -> Dict[str, List[str]]:
    """Загружает сохранённые пресеты {имя: [хосты]}."""
    store = _read_store()
    presets = store.get("presets", {})
    if not isinstance(presets, dict):
        return {}
    return {
        str(name): _dedupe(hosts)
        for name, hosts in presets.items()
        if isinstance(hosts, list)
    }


def save_to_history(app_name: str, hosts: List[str]) -> None:
    """Сохраняет пресет приложения в историю."""
    name = str(app_name).strip()
    if not name:
        return

    store = _read_store()
    presets = store["presets"]  # type: ignore[index]
    presets[name] = _dedupe(hosts)  # type: ignore[index]
    try:
        _write_store(store)
    except OSError:
        pass


def load_sessions() -> List[Dict[str, object]]:
    """Возвращает историю запусков подбора (новые записи первыми)."""
    store = _read_store()
    sessions = store.get("sessions", [])
    if not isinstance(sessions, list):
        return []
    return [item for item in reversed(sessions) if isinstance(item, dict)]


def add_session(record: Dict[str, object]) -> None:
    """Добавляет запись о запуске подбора в историю (максимум 200 записей)."""
    store = _read_store()
    sessions = store.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    sessions.append(record)
    store["sessions"] = sessions[-200:]
    try:
        _write_store(store)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Пресеты и поиск хостов
# ---------------------------------------------------------------------------

def capture_active_process_ips(process_name: str) -> List[str]:
    """Возвращает публичные удалённые IP активных соединений процесса (Windows)."""
    if os.name != "nt" or not process_name:
        return []

    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "", process_name)
    if not safe_name:
        return []

    script = (
        "Get-NetTCPConnection | "
        "Where-Object { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue)."
        f"ProcessName -like '*{safe_name}*' }} | "
        "Select-Object -ExpandProperty RemoteAddress"
    )
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    return _dedupe(ip.strip() for ip in output.splitlines() if is_valid_public_ip(ip.strip()))


def _normalise_domain(application: str) -> Optional[str]:
    """Пытается извлечь домен из строки вида ``https://example.com/path``."""
    value = application.strip().lower()
    if not value:
        return None

    if "://" in value or "/" in value:
        parsed = urlparse(value if "://" in value else "http://" + value)
        candidate = (parsed.hostname or "").lower()
    else:
        candidate = value

    candidate = candidate.strip(".")
    return candidate if is_valid_domain(candidate) else None


def search_app_hosts_online(app_name: str) -> List[str]:
    """Ищет известные домены приложения по имени или домену.

    Онлайн-поиска здесь нет: используются встроенные пресеты и таблица
    псевдонимов. Возвращает пустой список, если ничего не найдено (никаких
    выдуманных ``<name>.com``).
    """
    app_clean = app_name.strip().lower()
    if not app_clean:
        return []

    found = set()

    domain = _normalise_domain(app_clean)
    if domain:
        hosts = _dedupe([domain, "www." + domain] if not domain.startswith("www.") else [domain])
        save_to_history(app_name, hosts)
        return hosts

    words = re.findall(r"[a-z0-9]+", app_clean)
    word_set = set(words)
    compact = re.sub(r"[^a-z0-9]", "", app_clean)

    for alias, domains in _KNOWN_ALIASES.items():
        if alias in word_set or alias == compact:
            found.update(domains)

    for preset_name, data in DEFAULT_GAME_PRESETS.items():
        preset_lower = preset_name.lower()
        preset_words = set(re.findall(r"[a-z0-9]+", preset_lower))
        if (
            preset_lower == app_clean
            or preset_words.issubset(word_set)
            or compact == re.sub(r"[^a-z0-9]", "", preset_lower)
        ):
            found.update(data["domains"])  # type: ignore[arg-type]

    hosts = _dedupe(found)
    if hosts:
        save_to_history(app_name, hosts)
    return hosts


def _resolve_preset_key(preset_name: str, presets: Dict[str, Dict[str, object]]) -> Optional[str]:
    if preset_name in presets:
        return preset_name

    wanted = preset_name.strip().lower()
    for name in presets:
        if name.strip().lower() == wanted:
            return name
    for name in presets:
        if wanted and wanted in name.strip().lower():
            return name
    return None


def fetch_preset_targets(preset_name: str, resolve_ips: bool = False) -> List[str]:
    """Возвращает список доменов для пресета (включая пользовательскую историю)."""
    del resolve_ips  # зарезервировано на будущее; DNS-резолв здесь не нужен

    presets: Dict[str, Dict[str, object]] = {
        name: {"domains": list(data["domains"])}
        for name, data in DEFAULT_GAME_PRESETS.items()
    }
    for history_name, hosts in load_history().items():
        presets.setdefault(history_name, {"domains": hosts})

    key = _resolve_preset_key(preset_name, presets)
    if key is None:
        return []

    domains = presets[key].get("domains", [])
    return _dedupe(domains) if isinstance(domains, list) else []


def export_presets_to_file(filepath: str, hosts: Optional[List[str]] = None) -> bool:
    """Экспортирует пресеты (или только переданный список хостов) в JSON."""
    try:
        if hosts is not None:
            data: Dict[str, object] = {
                "Экспорт": {
                    "description": "Экспортированный список целевых доменов",
                    "domains": _dedupe(hosts),
                }
            }
        else:
            data = {}
            for name, preset in DEFAULT_GAME_PRESETS.items():
                data[name] = {
                    "description": preset.get("description", ""),
                    "domains": list(preset["domains"]),  # type: ignore[arg-type]
                }
            for name, preset_hosts in load_history().items():
                if name in data:
                    merged = _dedupe(
                        list(data[name]["domains"]) + preset_hosts  # type: ignore[index]
                    )
                    data[name]["domains"] = merged  # type: ignore[index]
                else:
                    data[name] = {
                        "description": f"Пользовательский пресет {name}",
                        "domains": preset_hosts,
                    }

        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def import_presets_from_file(filepath: str) -> List[str]:
    """Импортирует домены из JSON (пресеты/список) или TXT и возвращает их.

    JSON-пресеты дополнительно сохраняются в историю под своими именами.
    """
    try:
        with open(filepath, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    except OSError:
        return []

    hosts: List[str] = []
    parsed = None
    if filepath.lower().endswith(".json"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return []

    if isinstance(parsed, dict):
        for name, value in parsed.items():
            if isinstance(value, list):
                entries = value
            elif isinstance(value, dict) and isinstance(value.get("domains"), list):
                entries = value["domains"]
            else:
                continue

            preset_hosts = _dedupe(
                entry for entry in entries if isinstance(entry, str) and is_valid_domain(entry)
            )
            if preset_hosts:
                save_to_history(str(name), preset_hosts)
                hosts.extend(preset_hosts)
    elif isinstance(parsed, list):
        hosts.extend(entry for entry in parsed if isinstance(entry, str))
    else:
        hosts.extend(
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    return _dedupe(host for host in hosts if is_valid_domain(host))
