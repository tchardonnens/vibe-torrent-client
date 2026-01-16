"""
Main TorrentTUI class with stats panel and scrolling log.
"""

from __future__ import annotations

import curses
import logging
import sys
import time
from collections import deque
from typing import Optional, Deque

from .constants import ColorPairs
from .formatters import format_seconds, format_size, format_eta, calculate_speed
from .log_handler import TUILogHandler


class TorrentTUI:
    """Enhanced TUI with stats panel and scrolling log canvas."""

    def __init__(self, name: str, total_pieces: int, total_bytes: int) -> None:
        self.name = name
        self.total_pieces = total_pieces
        self.total_bytes = total_bytes
        self.start_time = time.time()
        self.stdscr: Optional["curses._CursesWindow"] = None
        self.enabled = sys.stdout.isatty()
        
        # Log buffer
        self.log_buffer: Deque[tuple[str, int]] = deque(maxlen=500)
        self.log_scroll_offset = 0
        
        # Cache for last stats to avoid flicker
        self._last_stats: dict = {}
        
        # Log handler reference
        self._log_handler: Optional[TUILogHandler] = None

    def start(self) -> None:
        """Initialize curses UI and capture logging."""
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
        self.stdscr.keypad(True)
        
        # Initialize colors
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            
            # Define color pairs
            curses.init_pair(ColorPairs.TITLE, curses.COLOR_CYAN, -1)
            curses.init_pair(ColorPairs.PROGRESS, curses.COLOR_GREEN, -1)
            curses.init_pair(ColorPairs.STATS, curses.COLOR_WHITE, -1)
            curses.init_pair(ColorPairs.LOG_INFO, curses.COLOR_WHITE, -1)
            curses.init_pair(ColorPairs.LOG_WARNING, curses.COLOR_YELLOW, -1)
            curses.init_pair(ColorPairs.LOG_ERROR, curses.COLOR_RED, -1)
            curses.init_pair(ColorPairs.BORDER, curses.COLOR_BLUE, -1)
            curses.init_pair(ColorPairs.SPEED, curses.COLOR_MAGENTA, -1)
        
        # Install log handler (only show WARNING and above in TUI)
        self._log_handler = TUILogHandler(self)
        self._log_handler.setLevel(logging.WARNING)
        
        # Add handler to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(self._log_handler)
        
        # Initial draw
        self._draw_frame()

    def stop(self) -> None:
        """Restore terminal state."""
        if not self.enabled or not self.stdscr:
            return
        
        # Remove log handler
        if self._log_handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(self._log_handler)
            self._log_handler = None
        
        curses.nocbreak()
        curses.echo()
        curses.endwin()
        self.stdscr = None

    def add_log(self, message: str, level: int = logging.INFO) -> None:
        """Add a log message to the buffer."""
        self.log_buffer.append((message, level))
        # Auto-scroll to bottom when new log arrives
        self.log_scroll_offset = 0

    def _draw_frame(self) -> None:
        """Draw the static frame elements."""
        if not self.stdscr:
            return
        
        height, width = self.stdscr.getmaxyx()
        
        # Clear screen
        self.stdscr.erase()
        
        # Draw borders and divider
        border_attr = curses.color_pair(ColorPairs.BORDER) if curses.has_colors() else 0
        
        # Top border
        self._safe_addstr(0, 0, "╭" + "─" * (width - 2) + "╮", border_attr)
        
        # Stats section header (row 1)
        self._safe_addstr(1, 0, "│", border_attr)
        self._safe_addstr(1, width - 1, "│", border_attr)
        
        # Divider between stats and logs (row 9)
        stats_end = 9
        if height > stats_end:
            self._safe_addstr(stats_end, 0, "├" + "─" * (width - 2) + "┤", border_attr)
        
        # Log section header
        if height > stats_end + 1:
            log_header = " LOGS "
            log_header_pos = (width - len(log_header)) // 2
            self._safe_addstr(stats_end + 1, 0, "│", border_attr)
            title_attr = curses.color_pair(ColorPairs.TITLE) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
            self._safe_addstr(stats_end + 1, log_header_pos, log_header, title_attr)
            self._safe_addstr(stats_end + 1, width - 1, "│", border_attr)
        
        # Side borders for stats section
        for row in range(2, stats_end):
            if row < height:
                self._safe_addstr(row, 0, "│", border_attr)
                self._safe_addstr(row, width - 1, "│", border_attr)
        
        # Side borders for log section
        for row in range(stats_end + 2, height - 1):
            self._safe_addstr(row, 0, "│", border_attr)
            self._safe_addstr(row, width - 1, "│", border_attr)
        
        # Bottom border
        if height > 1:
            self._safe_addstr(height - 1, 0, "╰" + "─" * (width - 2) + "╯", border_attr)

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

        try:
            # Handle input (for scrolling)
            self._handle_input()
            
            height, width = self.stdscr.getmaxyx()
            if width < 40 or height < 15:
                self._safe_addstr(0, 0, "Terminal too small!")
                self.stdscr.refresh()
                return
            
            # Redraw frame
            self._draw_frame()
            
            # Content width (inside borders)
            content_width = width - 4
            
            # Title
            title = f" ⚡ {self.name} "
            title_attr = curses.color_pair(ColorPairs.TITLE) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
            title_pos = (width - len(title)) // 2
            self._safe_addstr(1, title_pos, title[:content_width], title_attr)
            
            # Progress bar (row 3)
            percent = (completed_pieces / self.total_pieces * 100.0) if self.total_pieces else 0.0
            bar_width = max(20, content_width - 10)
            filled = int(bar_width * percent / 100.0)
            
            progress_attr = curses.color_pair(ColorPairs.PROGRESS) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
            bar_empty = "-" * (bar_width - filled)
            bar_filled = "#" * filled
            
            self._safe_addstr(3, 2, "[", 0)
            self._safe_addstr(3, 3, bar_filled, progress_attr)
            self._safe_addstr(3, 3 + filled, bar_empty, 0)
            self._safe_addstr(3, 3 + bar_width, "]", 0)
            self._safe_addstr(3, 3 + bar_width + 1, f" {percent:5.1f}%", progress_attr)
            
            # Stats row 1: Pieces and Peers
            stats_attr = curses.color_pair(ColorPairs.STATS) if curses.has_colors() else 0
            elapsed = time.time() - self.start_time
            eta = format_eta(self.total_pieces, completed_pieces, pieces_per_sec)
            
            stats_line1 = (
                f" 📦 Pieces: {completed_pieces}/{self.total_pieces}  "
                f"│  👥 Peers: {active_peers}/{total_peers}  "
                f"│  ⏱  Elapsed: {format_seconds(elapsed)}  "
                f"│  ⏳ ETA: {eta}"
            )
            self._safe_addstr(5, 2, stats_line1[:content_width], stats_attr)
            
            # Stats row 2: Speed metrics
            speed_attr = curses.color_pair(ColorPairs.SPEED) if curses.has_colors() else 0
            download_speed = calculate_speed(downloaded_bytes, elapsed)
            
            stats_line2 = (
                f" 🚀 Speed: {download_speed}  "
                f"│  📊 Chunks/s: {chunks_per_sec:6.1f}  "
                f"│  🧩 Pieces/s: {pieces_per_sec:5.2f}"
            )
            self._safe_addstr(6, 2, stats_line2[:content_width], speed_attr)
            
            # Stats row 3: Download progress
            stats_line3 = (
                f" 📥 Downloaded: {format_size(downloaded_bytes)} / {format_size(self.total_bytes)}"
            )
            self._safe_addstr(7, 2, stats_line3[:content_width], stats_attr)
            
            # Render logs (starting from row 11)
            self._render_logs(height, width)
            
            self.stdscr.refresh()
            
        except Exception:
            # If anything goes wrong, try to refresh anyway
            try:
                self.stdscr.refresh()
            except Exception:
                pass

    def _handle_input(self) -> None:
        """Handle keyboard input for scrolling."""
        if not self.stdscr:
            return
        
        try:
            key = self.stdscr.getch()
            if key == curses.KEY_UP or key == ord('k'):
                self.log_scroll_offset = min(
                    self.log_scroll_offset + 1,
                    max(0, len(self.log_buffer) - 1)
                )
            elif key == curses.KEY_DOWN or key == ord('j'):
                self.log_scroll_offset = max(0, self.log_scroll_offset - 1)
            elif key == curses.KEY_PPAGE:  # Page Up
                self.log_scroll_offset = min(
                    self.log_scroll_offset + 10,
                    max(0, len(self.log_buffer) - 1)
                )
            elif key == curses.KEY_NPAGE:  # Page Down
                self.log_scroll_offset = max(0, self.log_scroll_offset - 10)
            elif key == ord('g'):  # Go to top (oldest)
                self.log_scroll_offset = max(0, len(self.log_buffer) - 1)
            elif key == ord('G'):  # Go to bottom (newest)
                self.log_scroll_offset = 0
        except Exception:
            pass

    def _render_logs(self, height: int, width: int) -> None:
        """Render the scrolling log section."""
        if not self.stdscr:
            return
        
        log_start_row = 11
        log_end_row = height - 2
        log_height = log_end_row - log_start_row
        content_width = width - 4
        
        if log_height <= 0:
            return
        
        # Get logs to display (newest first, then apply scroll offset)
        logs = list(self.log_buffer)
        logs.reverse()  # Newest first
        
        # Apply scroll offset
        if self.log_scroll_offset > 0:
            logs = logs[self.log_scroll_offset:]
        
        # Render visible logs
        for i, (message, level) in enumerate(logs[:log_height]):
            row = log_start_row + i
            if row >= log_end_row:
                break
            
            # Choose color based on log level
            if curses.has_colors():
                if level >= logging.ERROR:
                    attr = curses.color_pair(ColorPairs.LOG_ERROR)
                elif level >= logging.WARNING:
                    attr = curses.color_pair(ColorPairs.LOG_WARNING)
                else:
                    attr = curses.color_pair(ColorPairs.LOG_INFO)
            else:
                attr = 0
            
            # Truncate message to fit
            display_msg = message[:content_width]
            self._safe_addstr(row, 2, " " * content_width, 0)  # Clear line
            self._safe_addstr(row, 2, display_msg, attr)
        
        # Show scroll indicator if scrolled
        if self.log_scroll_offset > 0:
            scroll_indicator = f" ↑ {self.log_scroll_offset} more "
            indicator_attr = curses.color_pair(ColorPairs.TITLE) if curses.has_colors() else curses.A_REVERSE
            self._safe_addstr(log_start_row, width - len(scroll_indicator) - 2, scroll_indicator, indicator_attr)

    def _safe_addstr(self, row: int, col: int, text: str, attr: int = 0) -> None:
        """Safely add a string to the screen."""
        if not self.stdscr:
            return
        try:
            height, width = self.stdscr.getmaxyx()
            if row >= height or col >= width or row < 0 or col < 0:
                return
            # Truncate text to avoid wrapping
            max_len = width - col - 1
            if max_len <= 0:
                return
            self.stdscr.addstr(row, col, text[:max_len], attr)
        except Exception:
            pass
