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


# Regex to detect Java class/interface/enum declarations
JAVA_CLASS_PATTERN = re.compile(
    r'^\s*(?:public\s+|abstract\s+|final\s+)?'
    r'(?:class|interface|enum|record)\s+'
    r'([A-Z][A-Za-z0-9_]*)',
    re.MULTILINE
)

# Regex to detect existing package declaration
JAVA_PACKAGE_PATTERN = re.compile(r'^\s*package\s+([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\s*;', re.MULTILINE)

# Class type detection patterns
CLASS_TYPE_PATTERNS = {
    'entity': [
        r'@Entity\s*\n',
        r'@Table\s*\(',
        r'extends\s+.*Entity',
        r'@Id\s+\n',
        r'@Column\s*\(',
    ],
    'repository': [
        r'@Repository\s*\n',
        r'extends\s+.*Repository',
        r'extends\s+JpaRepository',
        r'extends\s+CrudRepository',
    ],
    'service': [
        r'@Service\s*\n',
        r'@Transactional\s*\n',
        r'class\s+\w+Service\s*[<{]',
        r'class\s+\w+ServiceImpl',
    ],
    'controller': [
        r'@RestController\s*\n',
        r'@Controller\s*\n',
        r'@RequestMapping\s*\(',
        r'@GetMapping\s*\(',
        r'@PostMapping\s*\(',
    ],
    'dto': [
        r'@Data\s*\n',
        r'@Builder\s*\n',
        r'@NoArgsConstructor',
        r'@AllArgsConstructor',
        r'@Schema\s*\(',
        r'class\s+\w+(?:Dto|DTO|Request|Response|Summary|Profile)\s*[<{]',
    ],
    'exception': [
        r'extends\s+(?:RuntimeException|Exception)',
        r'class\s+\w+Exception\s*[<{]',
    ],
    'config': [
        r'@Configuration\s*\n',
        r'@Enable\w+\s*\n',
        r'@ComponentScan',
        r'class\s+\w+Config\s*[<{]',
    ],
    'validator': [
        r'@Validator\s*\n',
        r'implements\s+ConstraintValidator',
        r'class\s+\w+Validator\s*[<{]',
    ],
    'security': [
        r'@Component\s*\n.*Security',
        r'class\s+\w*Security\w*\s*[<{]',
    ],
    'util': [
        r'class\s+\w+Util\w*\s*[<{]',
        r'class\s+\w+Helper\w*\s*[<{]',
    ],
}


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
    
    def split_java_classes(self, content: str, base_path: str = "") -> list[FileSegment]:
        """
        Intelligently split Java content with multiple classes into separate files.
        
        Each public class gets its own file named after the class.
        Package declaration is derived from the file path.
        
        Args:
            content: Java source code potentially containing multiple classes
            base_path: Base relative path (e.g., "com/company/service")
            
        Returns:
            List of FileSegment objects, one per class
        """
        segments = []
        
        # Find all class declarations with their positions
        matches = list(JAVA_CLASS_PATTERN.finditer(content))
        if len(matches) <= 1:
            # Single class - no splitting needed
            return []
        
        log.info(f"Detected {len(matches)} classes in content, splitting...")
        
        # Extract existing package declaration
        existing_package = None
        pkg_match = JAVA_PACKAGE_PATTERN.search(content)
        if pkg_match:
            existing_package = pkg_match.group(1)
        
        # Split content for each class
        for i, match in enumerate(matches):
            class_name = match.group(1)
            start_pos = match.start()
            
            # Find the end of this class (start of next class or end of content)
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(content)
            
            # Extract class content
            class_content = content[start_pos:end_pos].strip()
            
            # Detect class type for proper package placement
            class_type = self._detect_class_type(class_content, class_name)
            
            # Build proper file path based on class type
            if base_path:
                relative_path = self._build_package_path(base_path, class_type, class_name)
            else:
                relative_path = f"{class_name}.java"
            
            # Determine package from path
            package = self._path_to_package(relative_path)
            if existing_package and not package:
                package = existing_package
            
            # Add package declaration if not present
            if package and not JAVA_PACKAGE_PATTERN.search(class_content):
                class_content = f"package {package};\n\n{class_content}"
            
            segments.append(FileSegment(
                relative_path=relative_path,
                content=class_content,
                language='java'
            ))
            log.info(f"  Extracted class: {class_name} ({class_type}) -> {relative_path}")
        
        return segments
    
    def _path_to_package(self, relative_path: str) -> Optional[str]:
        """
        Convert a file path to a Java package name.
        
        Example:
            "com/company/entity/Customer.java" -> "com.company.entity"
            "service/OrderService.java" -> "service"
        """
        path = Path(relative_path)
        # Get all parent directories as package components
        parts = path.parent.parts
        if parts:
            return '.'.join(parts)
        return None
    
    def _detect_class_type(self, class_content: str, class_name: str) -> str:
        """
        Detect the type of class from its content to determine proper package.
        
        Returns one of: entity, repository, service, controller, dto, exception,
                       config, validator, security, util, or other
        """
        for class_type, patterns in CLASS_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, class_content, re.IGNORECASE):
                    return class_type
        return 'other'
    
    def _build_package_path(self, base_path: str, class_type: str, class_name: str) -> str:
        """
        Build proper package path based on class type.
        
        Args:
            base_path: Base path like "com/macys" or "com/macys/usermanagement"
            class_type: Detected class type (entity, service, dto, etc.)
            class_name: Class name for additional heuristics
        
        Returns:
            Proper relative path like "com/macys/dto/ClaimDto.java"
        """
        # Type to package suffix mapping
        type_to_package = {
            'entity': 'entity',
            'repository': 'repository',
            'service': 'service',
            'controller': 'controller',
            'dto': 'dto',
            'exception': 'exception',
            'config': 'config',
            'validator': 'validation',
            'security': 'security',
            'util': 'util',
            'other': '',  # Keep in base path
        }
        
        # Normalize base path
        base = base_path.rstrip('/')
        
        # Get suffix for class type
        suffix = type_to_package.get(class_type, '')
        
        # Special case: if base path already ends with the type suffix, don't duplicate
        if suffix and base.endswith(f'/{suffix}'):
            return f"{base}/{class_name}.java"
        
        # Special case: if base contains a domain segment (like 'user', 'usermanagement')
        # and we're not adding a type suffix that's already in the path
        if suffix:
            return f"{base}/{suffix}/{class_name}.java"
        else:
            return f"{base}/{class_name}.java"
    
    def intelligent_split(self, content: str, base_path: str = "", language: str = "java") -> list[FileSegment]:
        """
        Intelligently split content using multiple strategies.
        
        Strategy order:
        1. Look for explicit path markers (// com/example/File.java)
        2. For Java: detect multiple classes and split
        3. Return empty list if no splitting needed
        
        Args:
            content: Source code content
            base_path: Base directory path for the file
            language: Programming language
            
        Returns:
            List of FileSegment objects
        """
        # Strategy 1: Try explicit markers first
        segments = self.split_content(content, language)
        if segments:
            return segments
        
        # Strategy 2: For Java, try class-based splitting
        if language == 'java':
            segments = self.split_java_classes(content, base_path)
            if segments:
                return segments
        
        return []
    
    def _build_domain_consolidation_map(self, domains: set[str]) -> dict[str, str]:
        """
        Smart domain consolidation - auto-detect similar domains without hardcoding.
        
        Algorithm:
        1. Normalize plurals (users -> user, orders -> order)
        2. Find domains that are prefixes of others (user matches userservice)
        3. Group by common root and pick shortest as canonical
        
        Examples:
        - {user, users, userservice, usercontroller} -> {users: user, userservice: user, usercontroller: user}
        - {order, orders, orderservice} -> {orders: order, orderservice: order}
        - {customer, customers, customerrepo} -> {customers: customer, customerrepo: customer}
        
        Returns:
            Dict mapping variant domain -> canonical domain
        """
        if not domains or len(domains) < 2:
            return {}
        
        consolidation_map = {}
        domains_list = sorted(domains, key=len)  # Shortest first
        
        # Common suffixes that indicate type (not part of domain)
        type_suffixes = ['service', 'controller', 'repository', 'repo', 'dao', 'impl',
                        'entity', 'model', 'dto', 'request', 'response', 'validator',
                        'config', 'util', 'helper', 'exception', 'handler', 'mapper',
                        'factory', 'host', 'process', 'processing', 'management']
        
        def extract_root(domain: str) -> str:
            """Extract root domain name by removing type suffixes and plural 's'."""
            root = domain.lower()
            # Remove type suffixes
            for suffix in type_suffixes:
                if root.endswith(suffix) and len(root) > len(suffix):
                    root = root[:-len(suffix)]
                    break
            # Normalize plural (remove trailing s if present)
            if root.endswith('s') and len(root) > 1:
                root = root[:-1]
            return root
        
        # Build groups of similar domains
        processed = set()
        groups = []
        
        for domain in domains_list:
            if domain in processed:
                continue
            
            root = extract_root(domain)
            if not root or len(root) < 2:
                continue
            
            # Find all domains that match this root
            group = [domain]
            processed.add(domain)
            
            for other in domains_list:
                if other in processed:
                    continue
                other_root = extract_root(other)
                
                # Match if: same root, or one is prefix of other
                if (root == other_root or 
                    domain.startswith(other_root) or 
                    other.startswith(root)):
                    group.append(other)
                    processed.add(other)
            
            if len(group) > 1:
                groups.append(group)
        
        # Build consolidation map: pick shortest as canonical
        for group in groups:
            canonical = min(group, key=len)  # Shortest is canonical
            for variant in group:
                if variant != canonical:
                    consolidation_map[variant] = canonical
                    log.debug(f"Domain consolidation: {variant} -> {canonical}")
        
        return consolidation_map

    def write_segments(self, output_dir: Path, segments: list[FileSegment], base_package: str = "") -> list[Path]:
        """
        Write segments to files in the output directory.
        
        Args:
            output_dir: Base output directory
            segments: List of FileSegment objects to write
            base_package: Base Java package (e.g., "com/macys", "org/company")
        
        Returns:
            List of paths to written files
        """
        if segments is None:
            segments = self.segments
        
        # Deduplicate segments by relative_path
        # For duplicates, keep the one with more content (more complete implementation)
        seen_paths = {}
        for seg in segments:
            path_key = seg.relative_path.replace('\\', '/').lower()
            
            if path_key not in seen_paths:
                seen_paths[path_key] = seg
            else:
                existing = seen_paths[path_key]
                # Compare content length and complexity
                existing_score = len(existing.content) + existing.content.count('\n')
                new_score = len(seg.content) + seg.content.count('\n')
                
                # Also prefer content with more imports (more complete)
                existing_score += existing.content.count('import ')
                new_score += seg.content.count('import ')
                
                if new_score > existing_score:
                    log.info(f"Duplicate {seg.relative_path}: Replacing with more complete version ({new_score} vs {existing_score} lines/chars)")
                    seen_paths[path_key] = seg
                else:
                    log.info(f"Duplicate {seg.relative_path}: Keeping existing (better or equal: {existing_score} vs {new_score})")
        
        unique_segments = list(seen_paths.values())
        
        # Smart domain consolidation - auto-detect similar domains from all segments
        # Collect all unique domain names from Java paths
        all_domains = set()
        for seg in unique_segments:
            if seg.language == 'java':
                path_parts = seg.relative_path.split('/')
                if len(path_parts) >= 3 and path_parts[0] == 'com' and path_parts[1] == 'macys':
                    all_domains.add(path_parts[2])
        
        # Build consolidation map using smart similarity detection
        domain_consolidation = self._build_domain_consolidation_map(all_domains)
        if domain_consolidation:
            log.info(f"Smart domain consolidation: {domain_consolidation}")
        
        written = []
        for seg in unique_segments:
            relative_path = seg.relative_path
            
            # Validate: Java files should only be in base_package/* paths
            if seg.language == 'java' and not relative_path.startswith(base_package):
                # Check if it's a raw legacy path - redirect to app package
                # Use pattern matching for any legacy project name (starts with uppercase)
                first_part = relative_path.split('/')[0] if '/' in relative_path else relative_path
                if first_part and first_part[0].isupper():  # Starts with uppercase = legacy project name
                    log.warning(f"Redirecting legacy path to {base_package}/app: {relative_path}")
                    file_name = Path(relative_path).name
                    relative_path = f"{base_package}/app/{file_name}"
            
            # Apply domain consolidation to normalize package variations
            if seg.language == 'java' and domain_consolidation:
                path_parts = relative_path.split('/')
                base_parts = base_package.split('/')
                if len(path_parts) >= len(base_parts) + 1:
                    # Check if path starts with base_package
                    is_base = all(path_parts[i] == base_parts[i] for i in range(len(base_parts)))
                    if is_base:
                        domain = path_parts[len(base_parts)]
                        if domain in domain_consolidation:
                            canonical_domain = domain_consolidation[domain]
                            if domain != canonical_domain:
                                path_parts[len(base_parts)] = canonical_domain
                                relative_path = '/'.join(path_parts)
                                log.info(f"Domain consolidated: {domain} -> {canonical_domain}: {relative_path}")
            
            # Convert dot notation to path separators for Java-like structures
            slash_count = relative_path.count('/') + relative_path.count('\\')
            if seg.language == 'java' and '.' in relative_path and slash_count <= 1:
                # Likely a Java package path like com.company.Class.java
                # Convert to com/company/Class.java
                parts = relative_path.split('.')
                if len(parts) > 2 and parts[-1] in ['java', 'cs', 'vb']:
                    # Keep extension, convert rest to path
                    path_parts = parts[:-1]
                    relative_path = '/'.join(path_parts) + '.' + parts[-1]
            
            file_path = output_dir / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(seg.content, encoding='utf-8')
            written.append(file_path)
            log.info("Wrote %s", file_path)
        
        return written


def should_split_file(content: str, language: str = "java") -> bool:
    """Check if content appears to contain multiple files or classes."""
    splitter = FileSplitter()
    # Check for explicit markers
    markers = splitter._find_markers(content)
    if len(markers) > 1:
        return True
    # For Java, check for multiple class declarations
    if language == 'java':
        classes = list(JAVA_CLASS_PATTERN.finditer(content))
        return len(classes) > 1
    return False


def split_and_write_file(combined_file: Path, output_dir: Path, base_path: str = "") -> list[Path]:
    """
    Convenience function to split a combined file and write segments.
    Uses intelligent splitting strategies.
    
    Args:
        combined_file: Path to the combined file (e.g., OrderProcessing.java)
        output_dir: Base directory for output
        base_path: Base relative path for generated files (e.g., "com/company/entity")
    
    Returns:
        List of paths to the split files
    """
    content = combined_file.read_text(encoding='utf-8')
    language = 'java' if combined_file.suffix == '.java' else 'unknown'
    
    splitter = FileSplitter()
    segments = splitter.intelligent_split(content, base_path=base_path, language=language)
    
    if not segments:
        log.info("File %s does not need splitting", combined_file)
        return [combined_file]
    
    # Write segments
    written = splitter.write_segments(output_dir, segments)
    log.info("Split %s into %d files", combined_file.name, len(written))
    
    return written
