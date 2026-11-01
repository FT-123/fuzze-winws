"""
Совместимый модуль gui.py для импорта ZapretFuzzerApp из пакетной структуры ui/.
"""
from ui.app import ZapretFuzzerApp
from ui.components import RoundedButton, StyledCard, GradientFooterCanvas, FuzzingMetricsFrame
from ui.tray import MiniTrayOverlay, TrayManager
from ui.dialogs import HistoryDialog, InteractiveParamsWindow

__all__ = [
    "ZapretFuzzerApp",
    "RoundedButton",
    "StyledCard",
    "GradientFooterCanvas",
    "FuzzingMetricsFrame",
    "MiniTrayOverlay",
    "TrayManager",
    "HistoryDialog",
    "InteractiveParamsWindow"
]
