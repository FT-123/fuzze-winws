import socket
import concurrent.futures
import json
import urllib.request
import urllib.parse
import re
import os
import ipaddress
import subprocess
from typing import List, Dict

HISTORY_FILE = "history.json"

# Официальные домены заблокированных и замедляемых сервисов
DEFAULT_GAME_PRESETS: Dict[str, Dict[str, List[str]]] = {
    "Discord": {
        "description": "Discord голос, чаты, CDN и медиа",
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
            "gateway.discord.gg"
        ]
    },
    "YouTube": {
        "description": "YouTube видео и CDN сервера",
        "domains": [
            "youtube.com",
            "googlevideo.com",
            "ytimg.com",
            "youtu.be",
            "youtubei.googleapis.com",
            "yt3.ggpht.com"
        ]
    },
    "Telegram": {
        "description": "Telegram мессенджер, голос и веб-версия",
        "domains": [
            "t.me",
            "telegram.org",
            "telegram.me",
            "web.telegram.org",
            "api.telegram.org"
        ]
    },
    "Steam": {
        "description": "Steam магазин, сообщество и инвентарь",
        "domains": [
            "steampowered.com",
            "steamcommunity.com",
            "steamstatic.com",
            "steamcontent.com"
        ]
    },
    "Twitch": {
        "description": "Twitch стримы и чаты",
        "domains": [
            "twitch.tv",
            "ttvnw.net",
            "jtvnw.net"
        ]
    },
    "ChatGPT / OpenAI": {
        "description": "ChatGPT и API OpenAI",
        "domains": [
            "chatgpt.com",
            "openai.com",
            "oaistatic.com",
            "oaiusercontent.com"
        ]
    },
    "Instagram & Meta": {
        "description": "Instagram, Facebook и CDN",
        "domains": [
            "instagram.com",
            "cdninstagram.com",
            "facebook.com",
            "fbcdn.net"
        ]
    },
    "Twitter / X": {
        "description": "X (Twitter) и медиа-сервера",
        "domains": [
            "x.com",
            "twitter.com",
            "twimg.com"
        ]
    },
    "Notion": {
        "description": "Notion заметки и базы знаний",
        "domains": [
            "notion.so",
            "notion.site",
            "notion.new"
        ]
    },
    "Spotify": {
        "description": "Spotify музыка и подкасты",
        "domains": [
            "spotify.com",
            "scdn.co",
            "spotifycdn.com"
        ]
    },
    "Rainbow Six Siege": {
        "description": "Ubisoft & Rainbow Six Siege сервера",
        "domains": [
            "ubisoft.com",
            "ubi.com",
            "public-ubiservices.ubi.com",
            "ubiservices.ubi.com",
            "game-rainbow6.ubisoft.com",
            "r6s-stats.ubisoft.com",
            "connect.ubisoft.com",
            "uplay.com"
        ]
    }
}


def is_valid_public_ip(ip_str: str) -> bool:
    """Проверяет, что IP адрес является публичным (не loopback, private, bogon)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return not (ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_reserved)
    except ValueError:
        return False


def load_history() -> Dict[str, List[str]]:
    """Загружает историю поисков из JSON файла."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_to_history(app_name: str, hosts: List[str]):
    """Сохраняет найденное приложение и его хосты в историю."""
    history = load_history()
    history[app_name] = hosts
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


def capture_active_process_ips(process_name: str) -> List[str]:
    """
    Перехватывает целевые IP-адреса активных сетевых подключений процесса в Windows (PowerShell).
    """
    active_ips = set()
    if os.name != 'nt' or not process_name:
        return []
    try:
        cmd = f"powershell -Command \"Get-NetTCPConnection | Where-Object {{ (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName -like '*{process_name}*' }} | Select-Object -ExpandProperty RemoteAddress\""
        output = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        for line in output.splitlines():
            ip = line.strip()
            if is_valid_public_ip(ip):
                active_ips.add(ip)
    except Exception:
        pass
    return list(active_ips)


def search_app_hosts_online(app_name: str) -> List[str]:
    """
    Точный поиск хостов приложения/сайта без шума и мусорных IP.
    """
    app_clean = app_name.strip().lower()
    clean_alnum = re.sub(r'[^a-zA-Z0-9]', '', app_clean)
    found_targets = set()

    # 1. Если введено прямое доменное имя
    if "." in app_clean and " " not in app_clean:
        domain = app_clean.lstrip("https://").lstrip("http://").split("/")[0]
        found_targets.add(domain)
        if not domain.startswith("www."):
            found_targets.add(f"www.{domain}")
        save_to_history(app_name, list(found_targets))
        return list(found_targets)

    # 2. Поиск по известным сопоставлениям
    known_aliases = {
        "discord": ["discord.com", "discord.gg", "discord.media", "discordapp.com", "discordapp.net", "cdn.discordapp.com", "media.discordapp.net", "gateway.discord.gg"],
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
        "minecraft": ["minecraft.net", "mojang.com"]
    }

    for alias_key, alias_domains in known_aliases.items():
        if alias_key in clean_alnum:
            found_targets.update(alias_domains)

    # 3. Поиск по встроенным пресетам
    for preset, data in DEFAULT_GAME_PRESETS.items():
        if app_clean in preset.lower() or preset.lower() in app_clean:
            found_targets.update(data["domains"])

    # 4. Если запущен соответствующий процесс в Windows, снимаем его IP
    process_ips = capture_active_process_ips(clean_alnum)
    found_targets.update(process_ips)

    # 5. Фолбэк для неизвестных одиночных названий
    if not found_targets and clean_alnum:
        found_targets.add(f"{clean_alnum}.com")

    final_hosts = list(found_targets)
    if final_hosts:
        save_to_history(app_name, final_hosts)

    return final_hosts


def fetch_preset_targets(preset_name: str, resolve_ips: bool = False) -> List[str]:
    all_presets = dict(DEFAULT_GAME_PRESETS)
    history = load_history()

    for hist_app, hist_hosts in history.items():
        if hist_app not in all_presets:
            all_presets[hist_app] = {"domains": hist_hosts}

    if preset_name not in all_presets:
        return []

    return list(all_presets[preset_name]["domains"])