"""Базовые модели параметров winws (zapret1)."""
import re
from dataclasses import dataclass
from typing import Tuple


@dataclass
class WinwsParams:
    tcp_split: int = 1
    tcp_seqovl: int = 664
    tcp_ttl: int = 0
    desync_mode: str = "split"
    fooling_mode: str = "none"
    udp_repeats: int = 8
    udp_cutoff: str = "n4"
    any_protocol: bool = False

    def to_key(self) -> Tuple[int, int, int, str, str, int, str, bool]:
        return (
            self.tcp_split,
            self.tcp_seqovl,
            self.tcp_ttl,
            self.desync_mode,
            self.fooling_mode,
            self.udp_repeats,
            self.udp_cutoff,
            self.any_protocol,
        )

    def describe(self) -> str:
        return (
            f"desync={self.desync_mode}, fooling={self.fooling_mode}, "
            f"split={self.tcp_split}, seqovl={self.tcp_seqovl}, ttl={self.tcp_ttl}, "
            f"repeats={self.udp_repeats}, cutoff={self.udp_cutoff}"
        )


def validate_params(params: WinwsParams) -> None:
    """Проверяет значения перед вставкой в командную строку."""
    if not 1 <= params.tcp_split <= 65535:
        raise ValueError("TCP Split должен быть от 1 до 65535")
    if not 0 <= params.tcp_seqovl <= 65535:
        raise ValueError("TCP SeqOvl должен быть от 0 до 65535")
    if not 0 <= params.tcp_ttl <= 255:
        raise ValueError("TCP TTL должен быть от 0 до 255")
    if not 1 <= params.udp_repeats <= 100:
        raise ValueError("Repeats должен быть от 1 до 100")

    if not re.fullmatch(r"[a-z0-9,]+", params.desync_mode or ""):
        raise ValueError("Desync mode содержит недопустимые символы")
    if not re.fullmatch(r"[a-z0-9,]+", params.fooling_mode or ""):
        raise ValueError("Fooling mode содержит недопустимые символы")
    if not re.fullmatch(r"[a-z0-9]+", params.udp_cutoff or ""):
        raise ValueError("Cutoff содержит недопустимые символы")
