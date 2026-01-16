"""
File manager for writing downloaded pieces to disk.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from torrent_parser import TorrentFile


class FileManager:
    """Manages writing downloaded pieces to files."""
    
    def __init__(self, output_dir: Path, files: List["TorrentFile"], piece_length: int) -> None:
        """
        Initialize file manager.
        
        Args:
            output_dir: Directory to write files to
            files: List of TorrentFile objects
            piece_length: Length of each piece in bytes
        """
        self.output_dir = Path(output_dir)
        self.files = files
        self.piece_length = piece_length
        self.file_handles: Dict[str, any] = {}
        self.file_offsets: Dict[int, List[Tuple[str, int, int, int]]] = {}
        # piece_index -> [(file_path, offset_in_file, length, offset_in_piece)]
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate file offsets
        self._calculate_offsets()
    
    def _calculate_offsets(self) -> None:
        """Calculate which file each piece belongs to and the offset within that file."""
        current_offset = 0
        
        for file_info in self.files:
            file_path = self.output_dir / file_info.full_path
            file_length = file_info.length
            
            # Calculate which pieces overlap with this file
            file_start = current_offset
            file_end = current_offset + file_length
            
            # Determine piece range
            start_piece = file_start // self.piece_length
            end_piece = (file_end - 1) // self.piece_length
            
            for piece_index in range(start_piece, end_piece + 1):
                piece_start = piece_index * self.piece_length
                piece_end = piece_start + self.piece_length
                
                # Calculate overlap
                overlap_start = max(piece_start, file_start)
                overlap_end = min(piece_end, file_end)
                
                if overlap_start < overlap_end:
                    offset_in_file = overlap_start - file_start
                    offset_in_piece = overlap_start - piece_start
                    length = overlap_end - overlap_start
                    self.file_offsets.setdefault(piece_index, []).append(
                        (str(file_path), offset_in_file, length, offset_in_piece)
                    )
            
            current_offset += file_length
    
    def _get_file_handle(self, file_path: str):
        """Get or create a file handle for writing."""
        if file_path not in self.file_handles:
            # Create parent directories
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            # Open file for random access (create if missing)
            if Path(file_path).exists():
                self.file_handles[file_path] = open(file_path, 'r+b')
            else:
                self.file_handles[file_path] = open(file_path, 'w+b')
        return self.file_handles[file_path]
    
    def write_piece(self, piece_index: int, piece_data: bytes) -> None:
        """
        Write a piece to the appropriate file(s).
        
        Args:
            piece_index: Index of the piece
            piece_data: Piece data to write
        """
        if piece_index not in self.file_offsets:
            return
        
        segments = self.file_offsets[piece_index]
        for file_path, offset_in_file, length, offset_in_piece in segments:
            # Get file handle
            f = self._get_file_handle(file_path)
            # Seek to the correct position
            f.seek(offset_in_file)
            # Write the piece slice that maps to this file segment
            f.write(piece_data[offset_in_piece:offset_in_piece + length])
    
    def close_all(self) -> None:
        """Close all open file handles."""
        for f in self.file_handles.values():
            f.close()
        self.file_handles.clear()
    
    def __del__(self) -> None:
        """Cleanup on deletion."""
        self.close_all()
