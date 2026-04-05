"""
File Splitter — Post-processes LLM output to split multi-class files
Parses special comments like "// path/to/File.java" to extract separate files.
Works for any target language.
"""

from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from shared.config import get_logger

log = get_logger(__name__)


@dataclass
class FileSegment:
    """Represents a single file extracted from combined output."""
    relative_path: str  # e.g., "com/company/entity/Customer.java"
    content: str
    language: str  # e.g., "java", "typescript"


class FileSplitter:
    """
    Splits LLM-generated code containing multiple classes/files into separate files.
    
    Detects file path comments in formats like:
      - // com/example/Entity.java
      - # src/components/Button.tsx
      - <!-- src/app.service.ts -->
    """
    
    # Regex patterns to detect file path comments (language-agnostic)
    FILE_PATH_PATTERNS = [
        # Java/C/JS style: // path/to/File.java
        re.compile(r'^\s*//\s*([\w./\\-]+\.(?:java|cs|cpp|c|h|js|jsx|ts|tsx))\s*$', re.MULTILINE),
        # Python/Shell style: # path/to/file.py
        re.compile(r'^\s*#\s*([\w./\\-]+\.(?:py|sh|rb|pl))\s*$', re.MULTILINE),
        # XML/HTML style: <!-- path/to/file.xml -->
        re.compile(r'^\s*<!--\s*([\w./\\-]+\.(?:xml|html|xaml|svg))\s*-->\s*$', re.MULTILINE | re.IGNORECASE),
    ]
    
    def __init__(self):
        self.segments: list[FileSegment] = []
    
    def split_content(self, combined_content: str, base_language: str) -> list[FileSegment]:
        """
        Split combined content into separate files based on path comments.
        
        Args:
            combined_content: The LLM output with embedded file path comments
            base_language: Target language hint (e.g., "java", "typescript")
        
        Returns:
            List of FileSegment objects, each representing one file
        """
        self.segments = []
        
        # Find all file path markers and their positions
        markers = self._find_markers(combined_content)
        
        if not markers:
            log.debug("No file path markers found, returning as single file")
            return []
        
        # Extract content between markers
        for i, (path, start, end) in enumerate(markers):
            segment_content = combined_content[start:end].strip()
            
            # Clean up the content - remove the marker comment itself
            segment_content = self._remove_marker_comment(segment_content, path)
            
            # Detect language from extension
            lang = self._detect_language(path, base_language)
            
            # Normalize path separators
            relative_path = path.replace('\\', '/')
            
            self.segments.append(FileSegment(
                relative_path=relative_path,
                content=segment_content,
                language=lang
            ))
            log.debug("Extracted segment: %s (%d chars)", relative_path, len(segment_content))
        
        log.info("Split content into %d files", len(self.segments))
        return self.segments
    
    def _find_markers(self, content: str) -> list[tuple[str, int, int]]:
        """Find all file path markers and their positions."""
        markers = []
        
        for pattern in self.FILE_PATH_PATTERNS:
            for match in pattern.finditer(content):
                path = match.group(1)
                start = match.start()
                markers.append((path, start, None))  # End will be filled later
        
        # Sort by position
        markers.sort(key=lambda x: x[1])
        
        # Calculate end positions (start of next marker or end of content)
        result = []
        for i, (path, start, _) in enumerate(markers):
            if i + 1 < len(markers):
                end = markers[i + 1][1]
            else:
                end = len(content)
            result.append((path, start, end))
        
        return result
    
    def _remove_marker_comment(self, content: str, path: str) -> str:
        """Remove the file path marker comment from the content."""
        # Match and remove the first line if it's the marker
        patterns = [
            rf'^\s*//\s*{re.escape(path)}\s*\n?',
            rf'^\s*#\s*{re.escape(path)}\s*\n?',
            rf'^\s*<!--\s*{re.escape(path)}\s*-->\s*\n?',
        ]
        
        for pattern in patterns:
            content = re.sub(pattern, '', content, count=1, flags=re.MULTILINE | re.IGNORECASE)
        
        return content.strip()
    
    def _detect_language(self, path: str, fallback: str) -> str:
        """Detect language from file extension."""
        ext_map = {
            '.java': 'java',
            '.cs': 'csharp',
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'jsx',
            '.ts': 'typescript',
            '.tsx': 'tsx',
            '.cpp': 'cpp',
            '.c': 'c',
            '.h': 'c',
            '.xml': 'xml',
            '.html': 'html',
            '.xaml': 'xaml',
        }
        
        ext = Path(path).suffix.lower()
        return ext_map.get(ext, fallback)
    
    def write_segments(self, output_dir: Path, segments: Optional[list[FileSegment]] = None) -> list[Path]:
        """
        Write segments to disk, maintaining directory structure.
        Converts Java package notation (com.company.Class) to paths (com/company/Class.java).
        
        Returns:
            List of paths to written files
        """
        if segments is None:
            segments = self.segments
        
        written = []
        for seg in segments:
            # Convert dot notation to path separators for Java-like structures
            relative_path = seg.relative_path
            if seg.language == 'java' and '.' in relative_path.replace('/', '').replace('\\', ''):
                # Likely a Java package path like com.company.Class.java
                # Convert to com/company/Class.java
                parts = relative_path.replace('\\', '/').split('/')
                new_parts = []
                for part in parts:
                    # If part looks like a package (has dots but isn't just the filename)
                    if '.' in part and not part.endswith('.java'):
                        # Split by dots to create directories
                        new_parts.extend(part.split('.'))
                    else:
                        new_parts.append(part)
                relative_path = '/'.join(new_parts)
            
            file_path = output_dir / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(seg.content, encoding='utf-8')
            written.append(file_path)
            log.info("Wrote %s", file_path)
        
        return written


def should_split_file(content: str) -> bool:
    """Check if content appears to contain multiple files."""
    splitter = FileSplitter()
    markers = splitter._find_markers(content)
    return len(markers) > 1


def split_and_write_file(combined_file: Path, output_dir: Path) -> list[Path]:
    """
    Convenience function to split a combined file and write segments.
    
    Args:
        combined_file: Path to the combined file (e.g., OrderProcessing.java)
        output_dir: Base directory for output
    
    Returns:
        List of paths to the split files
    """
    content = combined_file.read_text(encoding='utf-8')
    
    splitter = FileSplitter()
    segments = splitter.split_content(content, base_language='java')
    
    if not segments:
        log.info("File %s does not contain multiple file markers, skipping split", combined_file)
        return [combined_file]
    
    # Write segments
    written = splitter.write_segments(output_dir, segments)
    
    # Optionally remove the original combined file
    # combined_file.unlink()
    
    return written
