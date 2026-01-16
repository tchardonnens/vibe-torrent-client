"""
Utility formatting functions for the TUI.
"""


def format_seconds(seconds: float) -> str:
    """Format seconds into a human-readable time string."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:d}h {minutes:02d}m {secs:02d}s"
    return f"{minutes:d}m {secs:02d}s"


def format_size(size_bytes: int) -> str:
    """Format bytes into a human-readable size string."""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def format_eta(total_pieces: int, completed_pieces: int, pieces_per_sec: float) -> str:
    """Calculate and format ETA based on remaining pieces."""
    if pieces_per_sec <= 0 or total_pieces <= 0:
        return "--:--"
    remaining = max(0, total_pieces - completed_pieces)
    return format_seconds(remaining / pieces_per_sec)


def calculate_speed(downloaded_bytes: int, elapsed: float) -> str:
    """Calculate and format download speed."""
    if elapsed <= 0:
        return "0 B/s"
    
    bytes_per_sec = downloaded_bytes / elapsed
    return f"{format_size(int(bytes_per_sec))}/s"
