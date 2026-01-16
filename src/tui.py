"""
Simple curses-based TUI for torrent progress.
"""

from __future__ import annotations

import curses
import sys
import time
from typing import Optional


class TorrentTUI:
    """Minimal TUI showing progress and speed metrics."""

    def __init__(self, name: str, total_pieces: int, total_bytes: int) -> None:
        self.name = name
        self.total_pieces = total_pieces
        self.total_bytes = total_bytes
        self.start_time = time.time()
        self.stdscr: Optional["curses._CursesWindow"] = None
        self.enabled = sys.stdout.isatty()

    def start(self) -> None:
        """Initialize curses UI."""
        if not self.enabled:
            return
        self.stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        try:
            curses.curs_set(0)
        except Exception:
            pass
        self.stdscr.nodelay(True)

    def stop(self) -> None:
        """Restore terminal state."""
        if not self.enabled or not self.stdscr:
            return
        curses.nocbreak()
        curses.echo()
        curses.endwin()
        self.stdscr = None

    def update(
        self,
        completed_pieces: int,
        pieces_per_sec: float,
        chunks_per_sec: float,
        active_peers: int,
        total_peers: int,
        downloaded_bytes: int
    ) -> None:
        """Render the UI."""
        if not self.enabled or not self.stdscr:
            return

        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()

        title = f"Torrent: {self.name}"
        self._add_line(0, title[:width - 1])

        percent = (completed_pieces / self.total_pieces * 100.0) if self.total_pieces else 0.0
        bar_width = max(10, width - 22)
        filled = int(bar_width * percent / 100.0)
        bar = "[" + "#" * filled + "-" * (bar_width - filled) + "]"
        self._add_line(2, f"{bar} {percent:6.2f}%")

        elapsed = time.time() - self.start_time
        eta = self._format_eta(completed_pieces, pieces_per_sec)
        line3 = (
            f"Pieces: {completed_pieces}/{self.total_pieces}  "
            f"Peers: {active_peers}/{total_peers}  "
            f"Elapsed: {self._format_seconds(elapsed)}  "
            f"ETA: {eta}"
        )
        self._add_line(4, line3[:width - 1])

        line4 = (
            f"Chunks/s: {chunks_per_sec:6.2f}  "
            f"Pieces/s: {pieces_per_sec:6.2f}  "
            f"Downloaded: {self._format_size(downloaded_bytes)} / {self._format_size(self.total_bytes)}"
        )
        self._add_line(5, line4[:width - 1])

        self.stdscr.refresh()

    def _add_line(self, row: int, text: str) -> None:
        if not self.stdscr:
            return
        try:
            self.stdscr.addstr(row, 0, text)
        except Exception:
            pass

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"

    def _format_eta(self, completed_pieces: int, pieces_per_sec: float) -> str:
        if pieces_per_sec <= 0 or self.total_pieces <= 0:
            return "--:--"
        remaining = max(0, self.total_pieces - completed_pieces)
        return self._format_seconds(remaining / pieces_per_sec)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        size = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"
