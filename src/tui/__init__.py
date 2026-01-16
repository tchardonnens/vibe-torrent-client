"""
TUI module for torrent progress display.
"""

from .constants import ColorPairs
from .formatters import calculate_speed, format_eta, format_seconds, format_size
from .log_handler import TUILogHandler
from .tui import TorrentTUI

__all__ = [
    "TorrentTUI",
    "TUILogHandler",
    "ColorPairs",
    "format_seconds",
    "format_size",
    "format_eta",
    "calculate_speed",
]
