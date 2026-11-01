"""Общие валидаторы доменов и IP-адресов."""
import ipaddress
import re

_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def is_valid_domain(value: str) -> bool:
    """Проверяет, что строка похожа на корректное DNS-имя (без схемы и пути)."""
    if not value or len(value) > 253:
        return False

    domain = value.strip().lower()
    if not domain or domain.startswith(".") or domain.endswith("."):
        return False
    if any(ch.isspace() for ch in domain):
        return False

    labels = domain.split(".")
    if len(labels) < 2:
        return False
    # Числовой "TLD" — это IP, а не домен.
    if labels[-1].isdigit():
        return False

    return all(_LABEL_RE.match(label) for label in labels)


def is_valid_public_ip(value: str) -> bool:
    """Проверяет, что IP-адрес является публичным (не loopback/private/bogon)."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )
