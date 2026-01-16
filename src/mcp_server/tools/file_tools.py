"""File listing tools."""

from pathlib import Path
from typing import Any

from ..state import DEFAULT_DOWNLOADS_DIR
from ..utils import format_size


def register_file_tools(mcp) -> None:
    """Register file-related tools with the MCP server."""

    @mcp.tool()
    def list_downloaded_files(
        directory: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List files in the downloads directory.

        Args:
            directory: Path to check. Defaults to the 'downloads' folder.

        Returns:
            List of downloaded files with their sizes.
        """
        downloads_dir = Path(directory) if directory else DEFAULT_DOWNLOADS_DIR

        if not downloads_dir.exists():
            return []

        files = []
        for item in downloads_dir.iterdir():
            if item.is_file():
                size = item.stat().st_size
                files.append(
                    {
                        "name": item.name,
                        "path": str(item.absolute()),
                        "size_bytes": size,
                        "size_formatted": format_size(size),
                    }
                )
            elif item.is_dir():
                # Calculate total size of directory
                total_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                files.append(
                    {
                        "name": item.name,
                        "path": str(item.absolute()),
                        "type": "directory",
                        "size_bytes": total_size,
                        "size_formatted": format_size(total_size),
                    }
                )

        return files
