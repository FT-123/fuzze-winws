import socket
import concurrent.futures
import json
import urllib.request
import urllib.parse
import re
import os
from typing import List, Dict

HISTORY_FILE = "history.json"

DEFAULT_GAME_PRESETS: Dict[str, Dict[str, List[str]]] = {
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
    },
    "Discord": {
        "description": "Discord голос, чаты, CDN и медиа",
        "domains": [
            "discord.com",
            "discordapp.com",
            "discord.gg",
            "discord.media",
            "discordapp.net",
            "discordcdn.com",
            "cdn.discordapp.com",
            "media.discordapp.net",
            "router.discordapp.net"
        ]
    },
    "YouTube": {
        "description": "YouTube видео и CDN сервера",
        "domains": [
            "youtube.com",
            "googlevideo.com",
            "ytimg.com",
            "youtu.be",
            "youtubei.googleapis.com"
        ]
    },
    "Steam": {
        "description": "Steam магазин, сообщество и загрузки",
        "domains": [
            "steampowered.com",
            "steamcommunity.com",
            "steamstatic.com",
            "steamcontent.com"
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
    }
}


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


def search_app_hosts_online(app_name: str) -> List[str]:
    """
    Ищет хосты/домены приложения в сети (DNS генерация + поиск по известным доменам),
    добавляет результаты и сохраняет в историю.
    """
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', app_name.lower())
    found_domains = set()

    # 1. Если имя является готовым доменным именем
    if "." in app_name and " " not in app_name:
        found_domains.add(app_name.strip())

    # 2. Генерируем стандартные кандидатные домены
    if clean_name:
        candidates = [
            f"{clean_name}.com",
            f"{clean_name}.net",
            f"{clean_name}.org",
            f"{clean_name}.io",
            f"{clean_name}.ru",
            f"api.{clean_name}.com",
            f"cdn.{clean_name}.com",
            f"game.{clean_name}.com",
            f"auth.{clean_name}.com",
            f"server.{clean_name}.com"
        ]

        # Известные сопоставления популярных сервисов и игр
        known_aliases = {
            "telegram": ["t.me", "telegram.org", "telegram.me", "web.telegram.org"],
            "steam": ["steampowered.com", "steamcommunity.com", "steamcontent.com"],
            "discord": ["discord.com", "discord.gg", "discordapp.com"],
            "youtube": ["youtube.com", "googlevideo.com", "ytimg.com"],
            "genshin": ["hoyoverse.com", "mihoyo.com", "genshinimpact.com"],
            "apex": ["ea.com", "respawn.com"],
            "valorant": ["riotgames.com", "pvp.net"],
            "twitch": ["twitch.tv", "ttvnw.net"],
            "spotify": ["spotify.com", "scdn.co"],
            "minecraft": ["minecraft.net", "mojang.com"]
        }

        for alias_key, alias_domains in known_aliases.items():
            if alias_key in clean_name:
                candidates.extend(alias_domains)

        for cand in candidates:
            try:
                socket.gethostbyname(cand)
                found_domains.add(cand)
            except Exception:
                pass

    # 3. Проверяем совпадения со встроенными пресетами
    for preset, data in DEFAULT_GAME_PRESETS.items():
        if app_name.lower() in preset.lower():
            found_domains.update(data["domains"])

    # 4. Разрешаем домены в IP адреса
    resolved_targets = list(found_domains)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_dom = {executor.submit(resolve_domain, dom): dom for dom in found_domains}
        for future in concurrent.futures.as_completed(future_to_dom):
            ips = future.result()
            resolved_targets.extend(ips)

    final_hosts = list(set(resolved_targets))

    # 5. Сохраняем в историю
    if final_hosts:
        save_to_history(app_name, final_hosts)

    return final_hosts


def resolve_domain(domain: str) -> List[str]:
    resolved = set()
    try:
        _, _, ip_list = socket.gethostbyname_ex(domain)
        for ip in ip_list:
            resolved.add(ip)
    except Exception:
        pass
    return list(resolved)


def fetch_preset_targets(preset_name: str, resolve_ips: bool = True) -> List[str]:
    all_presets = dict(DEFAULT_GAME_PRESETS)
    history = load_history()

    for hist_app, hist_hosts in history.items():
        if hist_app not in all_presets:
            all_presets[hist_app] = {"domains": hist_hosts}

    if preset_name not in all_presets:
        return []

    domains = all_presets[preset_name]["domains"]
    result = list(domains)

    if resolve_ips:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_dom = {executor.submit(resolve_domain, dom): dom for dom in domains if
                             not dom.replace('.', '').isdigit()}
            for future in concurrent.futures.as_completed(future_to_dom):
                ips = future.result()
                result.extend(ips)

    return list(set(result))

