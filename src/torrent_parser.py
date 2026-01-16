"""
A .torrent file parser that decodes bencoded data and extracts torrent metadata.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
from pathlib import Path
import hashlib


class BencodeError(Exception):
    """Exception raised for bencode parsing errors."""
    pass


class TorrentParser:
    """Parser for .torrent files using bencode format."""
    
    def __init__(self, torrent_path: Union[str, Path]) -> None:
        """
        Initialize the parser with a torrent file path.
        
        Args:
            torrent_path: Path to the .torrent file
        """
        self.torrent_path = Path(torrent_path)
        if not self.torrent_path.exists():
            raise FileNotFoundError(f"Torrent file not found: {torrent_path}")
        
        self.data: Optional[Dict[str, Any]] = None
        self._raw_data: bytes = b""
    
    def parse(self) -> Dict[str, Any]:
        """
        Parse the torrent file and return the decoded data.
        
        Returns:
            Dictionary containing the parsed torrent data
        """
        with open(self.torrent_path, 'rb') as f:
            self._raw_data = f.read()
        
        self.data, _ = self._decode_bencode(self._raw_data, 0)
        if not isinstance(self.data, dict):
            raise BencodeError("Torrent file must start with a dictionary")
        
        return self.data
    
    def _decode_bencode(self, data: bytes, index: int) -> Tuple[Any, int]:
        """
        Decode bencoded data recursively.
        
        Args:
            data: The raw bytes to decode
            index: Current position in the data
            
        Returns:
            Tuple of (decoded_value, new_index)
        """
        if index >= len(data):
            raise BencodeError(f"Unexpected end of data at index {index}")
        
        char = data[index:index+1]
        
        # Integer: i<number>e
        if char == b'i':
            end_index = data.find(b'e', index + 1)
            if end_index == -1:
                raise BencodeError(f"Unterminated integer at index {index}")
            try:
                value = int(data[index + 1:end_index])
                return value, end_index + 1
            except ValueError:
                raise BencodeError(f"Invalid integer at index {index}")
        
        # List: l<elements>e
        elif char == b'l':
            index += 1
            result: List[Any] = []
            while index < len(data) and data[index:index+1] != b'e':
                value, index = self._decode_bencode(data, index)
                result.append(value)
            if index >= len(data):
                raise BencodeError(f"Unterminated list at index {index}")
            return result, index + 1
        
        # Dictionary: d<key-value pairs>e
        elif char == b'd':
            index += 1
            result: Dict[Any, Any] = {}
            while index < len(data) and data[index:index+1] != b'e':
                key, index = self._decode_bencode(data, index)
                value, index = self._decode_bencode(data, index)
                # Convert dictionary keys from bytes to strings (bencode spec)
                if isinstance(key, bytes):
                    key = key.decode('utf-8', errors='replace')
                result[key] = value
            if index >= len(data):
                raise BencodeError(f"Unterminated dictionary at index {index}")
            return result, index + 1
        
        # String: <length>:<data>
        elif char.isdigit():
            colon_index = data.find(b':', index)
            if colon_index == -1:
                raise BencodeError(f"No colon found for string at index {index}")
            try:
                length = int(data[index:colon_index])
            except ValueError:
                raise BencodeError(f"Invalid string length at index {index}")
            
            start_index = colon_index + 1
            end_index = start_index + length
            if end_index > len(data):
                raise BencodeError(f"String length exceeds data at index {index}")
            
            value = data[start_index:end_index]
            return value, end_index
        
        else:
            raise BencodeError(f"Unexpected character '{char.decode('latin-1', errors='replace')}' at index {index}")
    
    def get_info_hash(self) -> str:
        """
        Calculate and return the SHA-1 hash of the 'info' dictionary.
        
        Returns:
            Hexadecimal string of the info hash
        """
        if self.data is None:
            self.parse()
        
        if 'info' not in self.data:
            raise ValueError("Torrent file missing 'info' dictionary")
        
        # Re-encode the info dictionary to calculate its hash
        info_bytes = self._encode_bencode(self.data['info'])
        return hashlib.sha1(info_bytes).hexdigest()
    
    def _encode_bencode(self, value: Any) -> bytes:
        """
        Encode a Python value to bencode format.
        
        Args:
            value: The value to encode
            
        Returns:
            Bencoded bytes
        """
        if isinstance(value, int):
            return f"i{value}e".encode('utf-8')
        elif isinstance(value, bytes):
            return f"{len(value)}:".encode('utf-8') + value
        elif isinstance(value, str):
            value_bytes = value.encode('utf-8')
            return f"{len(value_bytes)}:".encode('utf-8') + value_bytes
        elif isinstance(value, list):
            result = b"l"
            for item in value:
                result += self._encode_bencode(item)
            result += b"e"
            return result
        elif isinstance(value, dict):
            result = b"d"
            # Bencode requires keys to be sorted
            for key in sorted(value.keys()):
                result += self._encode_bencode(key)
                result += self._encode_bencode(value[key])
            result += b"e"
            return result
        else:
            raise BencodeError(f"Cannot encode type: {type(value)}")
    
    def get_announce_urls(self) -> List[str]:
        """
        Get all announce URLs from the torrent.
        
        Returns:
            List of announce URLs
        """
        if self.data is None:
            self.parse()
        
        urls: List[str] = []
        
        # Single announce URL
        if 'announce' in self.data:
            url = self.data['announce']
            if isinstance(url, bytes):
                urls.append(url.decode('utf-8', errors='replace'))
            else:
                urls.append(str(url))
        
        # Announce list (list of lists)
        if 'announce-list' in self.data:
            for tier in self.data['announce-list']:
                if isinstance(tier, list):
                    for url in tier:
                        if isinstance(url, bytes):
                            url_str = url.decode('utf-8', errors='replace')
                        else:
                            url_str = str(url)
                        if url_str not in urls:
                            urls.append(url_str)
        
        return urls
    
    def get_files(self) -> List[Dict[str, Any]]:
        """
        Get list of files in the torrent.
        
        Returns:
            List of file dictionaries with 'length' and 'path' keys
        """
        if self.data is None:
            self.parse()
        
        if 'info' not in self.data:
            return []
        
        info = self.data['info']
        
        # Single file torrent
        if 'length' in info:
            name = info.get('name', b'').decode('utf-8', errors='replace') if isinstance(info.get('name'), bytes) else str(info.get('name', ''))
            return [{
                'length': info['length'],
                'path': [name]
            }]
        
        # Multi-file torrent
        if 'files' in info:
            files = []
            for file_info in info['files']:
                path = file_info.get('path', [])
                if isinstance(path, list):
                    path = [p.decode('utf-8', errors='replace') if isinstance(p, bytes) else str(p) for p in path]
                else:
                    path = [str(path)]
                
                files.append({
                    'length': file_info.get('length', 0),
                    'path': path
                })
            return files
        
        return []
    
    def get_total_size(self) -> int:
        """
        Get the total size of all files in the torrent.
        
        Returns:
            Total size in bytes
        """
        files = self.get_files()
        return sum(f['length'] for f in files)
    
    def get_piece_length(self) -> int:
        """
        Get the piece length (chunk size) for the torrent.
        
        Returns:
            Piece length in bytes
        """
        if self.data is None:
            self.parse()
        
        if 'info' not in self.data:
            return 0
        
        return self.data['info'].get('piece length', 0)
    
    def get_piece_count(self) -> int:
        """
        Get the number of pieces in the torrent.
        
        Returns:
            Number of pieces
        """
        if self.data is None:
            self.parse()
        
        if 'info' not in self.data or 'pieces' not in self.data['info']:
            return 0
        
        pieces = self.data['info']['pieces']
        if isinstance(pieces, bytes):
            # Each piece hash is 20 bytes (SHA-1)
            return len(pieces) // 20
        
        return 0
    
    def get_name(self) -> str:
        """
        Get the name of the torrent.
        
        Returns:
            Torrent name
        """
        if self.data is None:
            self.parse()
        
        if 'info' not in self.data:
            return ""
        
        name = self.data['info'].get('name', b'')
        if isinstance(name, bytes):
            return name.decode('utf-8', errors='replace')
        return str(name)
    
    def get_creation_date(self) -> Optional[int]:
        """
        Get the creation date of the torrent (Unix timestamp).
        
        Returns:
            Creation date timestamp or None if not present
        """
        if self.data is None:
            self.parse()
        
        return self.data.get('creation date')
    
    def get_comment(self) -> Optional[str]:
        """
        Get the comment from the torrent.
        
        Returns:
            Comment string or None if not present
        """
        if self.data is None:
            self.parse()
        
        comment = self.data.get('comment')
        if comment is None:
            return None
        
        if isinstance(comment, bytes):
            return comment.decode('utf-8', errors='replace')
        return str(comment)
    
    def get_created_by(self) -> Optional[str]:
        """
        Get the 'created by' field from the torrent.
        
        Returns:
            Created by string or None if not present
        """
        if self.data is None:
            self.parse()
        
        created_by = self.data.get('created by')
        if created_by is None:
            return None
        
        if isinstance(created_by, bytes):
            return created_by.decode('utf-8', errors='replace')
        return str(created_by)
    
    def print_summary(self) -> None:
        """
        Print a human-readable summary of the torrent.
        """
        if self.data is None:
            self.parse()
        
        print(f"Torrent: {self.get_name()}")
        print(f"Info Hash: {self.get_info_hash()}")
        print(f"Total Size: {self._format_size(self.get_total_size())}")
        print(f"Piece Length: {self._format_size(self.get_piece_length())}")
        print(f"Number of Pieces: {self.get_piece_count()}")
        
        creation_date = self.get_creation_date()
        if creation_date:
            from datetime import datetime
            print(f"Creation Date: {datetime.fromtimestamp(creation_date)}")
        
        created_by = self.get_created_by()
        if created_by:
            print(f"Created By: {created_by}")
        
        comment = self.get_comment()
        if comment:
            print(f"Comment: {comment}")
        
        print(f"\nAnnounce URLs ({len(self.get_announce_urls())}):")
        for url in self.get_announce_urls():
            print(f"  - {url}")
        
        files = self.get_files()
        print(f"\nFiles ({len(files)}):")
        for i, file_info in enumerate(files, 1):
            path_str = '/'.join(file_info['path'])
            size = self._format_size(file_info['length'])
            print(f"  {i}. {path_str} ({size})")
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """
        Format bytes into human-readable size.
        
        Args:
            size_bytes: Size in bytes
            
        Returns:
            Formatted size string
        """
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"


def main() -> None:
    """Example usage of the torrent parser."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python torrent_parser.py <torrent_file>")
        sys.exit(1)
    
    torrent_file = sys.argv[1]
    
    try:
        parser = TorrentParser(torrent_file)
        parser.parse()
        parser.print_summary()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

