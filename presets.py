import socket
import concurrent.futures
from typing import List, Dict

GAME_PRESETS: Dict[str, Dict[str, List[str]]] = {
    "Rainbow Six Siege": {
        "description": "Ubisoft & Rainbow Six Siege сервера и сервисы авторизации",
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
    "Roblox": {
        "description": "Roblox авторизация и игровые сервера",
        "domains": [
            "roblox.com",
            "rbxcdn.com",
            "roblox.cn"
        ]
    }
}


def resolve_domain(domain: str) -> List[str]:
    """Разрешает домен в список активных IP адресов."""
    resolved = set()
    try:
        _, _, ip_list = socket.gethostbyname_ex(domain)
        for ip in ip_list:
            resolved.add(ip)
    except Exception:
        pass
    return list(resolved)


def fetch_preset_targets(preset_name: str, resolve_ips: bool = True) -> List[str]:
    """Возвращает список доменов и их IP адресов для пресета."""
    if preset_name not in GAME_PRESETS:
        return []

    domains = GAME_PRESETS[preset_name]["domains"]
    result = list(domains)

    if resolve_ips:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_dom = {executor.submit(resolve_domain, dom): dom for dom in domains}
            for future in concurrent.futures.as_completed(future_to_dom):
                ips = future.result()
                result.extend(ips)

    return list(set(result))