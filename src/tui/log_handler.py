"""
Custom log handler for the TUI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tui import TorrentTUI


class TUILogHandler(logging.Handler):
    """Custom log handler that captures logs for the TUI."""
    
    def __init__(self, tui: "TorrentTUI") -> None:
        super().__init__()
        self.tui = tui
        self.setFormatter(logging.Formatter(
            "%(asctime)s │ %(levelname)-7s │ %(message)s",
            datefmt="%H:%M:%S"
        ))
    
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.tui.add_log(msg, record.levelno)
        except Exception:
            pass
