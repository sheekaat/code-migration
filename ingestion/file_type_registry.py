"""
File Type Registry and Component Classification System

Handles detection, classification, and extraction of different file types
and components within files.

Supported Source Types:
- VB6: .vbp, .frm, .cls, .bas (Forms, Classes, Modules)
- C#: .cs, .csproj (Classes, Interfaces, Enums, Structs)
- Tibco BW: .bwp, .process (Processes, Activities)
- WPF: .xaml, .xaml.cs (Views, Code-behind)
- Java: .java (legacy input)
- SQL: .sql (Stored procedures, functions)

Target Component Types:
- Java Spring: Controller, Service, Repository, Entity, DTO, Config
- React: Component, Hook, Utility, Service, Context
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List, Dict, Callable
import re

from shared.models import SourceLanguage, TargetLanguage
from shared.config import get_logger

log = get_logger(__name__)


class ComponentType(Enum):
    """Types of components that can exist in source files."""
    # UI Components
    FORM = auto()           # VB6 Form, WPF Window
    USER_CONTROL = auto()   # Custom controls
    DIALOG = auto()         # Dialog boxes
    
    # Business Logic
    CLASS = auto()          # Standard class
    SERVICE = auto()        # Business service
    MODULE = auto()         # VB6 BAS module (static methods)
    
    # Data Access
    DATA_ACCESS = auto()    # DAO, Repository pattern
    ENTITY = auto()         # Data entity/ORM
    
    # Infrastructure
    CONFIG = auto()         # Configuration
    UTILITY = auto()        # Helper/utility class
    INTERFACE = auto()      # Interface definitions
    ENUM = auto()           # Enumerations
    
    # Process/Workflow
    PROCESS = auto()        # Tibco BW process
    ACTIVITY = auto()       # Process activity
    WORKFLOW = auto()       # Workflow definition


class FileCategory(Enum):
    """High-level file categories."""
    UI = auto()
    BUSINESS_LOGIC = auto()
    DATA_ACCESS = auto()
    INFRASTRUCTURE = auto()
    CONFIGURATION = auto()


@dataclass
class ComponentInfo:
    """Information about a component within a file."""
    name: str
    type: ComponentType
    source_language: SourceLanguage
    raw_content: str
    start_line: int
    end_line: int
    dependencies: List[str] = field(default_factory=list)
    public_interface: List[str] = field(default_factory=list)  # Methods, properties
    
    # Conversion hints
    suggested_target_type: Optional[str] = None
    conversion_confidence: float = 0.5


@dataclass
class FileTypeInfo:
    """Complete information about a source file."""
    path: str
    source_language: SourceLanguage
    file_category: FileCategory
    primary_component: ComponentType
    components: List[ComponentInfo] = field(default_factory=list)
    
    # Metadata
    total_lines: int = 0
    complexity_score: float = 0.0
    has_database_access: bool = False
    has_external_calls: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# FILE TYPE DETECTORS
# ═══════════════════════════════════════════════════════════════════════════

class FileTypeDetector:
    """Detects and classifies source file types."""
    
    EXTENSION_MAP: Dict[str, SourceLanguage] = {
        '.vbp': SourceLanguage.VB6,
        '.frm': SourceLanguage.VB6,
        '.cls': SourceLanguage.VB6,
        '.bas': SourceLanguage.VB6,
        '.vb': SourceLanguage.VB6,
        '.cs': SourceLanguage.CSHARP,
        '.csproj': SourceLanguage.CSHARP,
        '.bwp': SourceLanguage.TIBCO_BW,
        '.process': SourceLanguage.TIBCO_BW,
        '.xaml': SourceLanguage.WPF_XAML,
        '.xaml.cs': SourceLanguage.WPF_XAML,
        '.sql': None,  # SQL is not a source language for conversion
        '.xml': None,
    }
    
    # Component detection patterns by language
    VB6_PATTERNS = {
        ComponentType.FORM: re.compile(
            r'^\s*VERSION\s+\d+\.\d+.*?^\s*Begin\s+\w+\s+(\w+)',
            re.MULTILINE | re.DOTALL
        ),
        ComponentType.CLASS: re.compile(
            r'^\s*VERSION\s+\d+\.\d+.*?^\s*Begin\s+VB\.Form',
            re.MULTILINE | re.DOTALL
        ),
        ComponentType.MODULE: re.compile(
            r'^\s*Attribute\s+VB_Name\s*=\s*"([^"]+)"',
            re.MULTILINE
        ),
    }
    
    CSHARP_PATTERNS = {
        ComponentType.CLASS: re.compile(
            r'(?:public|internal|private)?\s*(?:static|abstract|sealed)?\s*class\s+(\w+)',
            re.MULTILINE
        ),
        ComponentType.INTERFACE: re.compile(
            r'(?:public|internal)?\s*interface\s+(\w+)',
            re.MULTILINE
        ),
        ComponentType.ENUM: re.compile(
            r'(?:public|internal)?\s*enum\s+(\w+)',
            re.MULTILINE
        ),
        ComponentType.SERVICE: re.compile(
            r'class\s+(\w+)(?:Service|Manager|Handler|Processor)',
            re.MULTILINE
        ),
        ComponentType.DATA_ACCESS: re.compile(
            r'class\s+(\w+)(?:Repository|Dao|DataAccess|DbAccess)',
            re.MULTILINE
        ),
    }
    
    TIBCO_PATTERNS = {
        ComponentType.PROCESS: re.compile(
            r'<\w*:?process[^>]*name=["\']([^"\']+)["\']',
            re.IGNORECASE
        ),
        ComponentType.ACTIVITY: re.compile(
            r'<\w*:?activity[^>]*name=["\']([^"\']+)["\']',
            re.IGNORECASE
        ),
    }
    
    def __init__(self):
        self.component_extractors: Dict[SourceLanguage, Callable] = {
            SourceLanguage.VB6: self._extract_vb6_components,
            SourceLanguage.CSHARP: self._extract_csharp_components,
            SourceLanguage.TIBCO_BW: self._extract_tibco_components,
            SourceLanguage.WPF_XAML: self._extract_wpf_components,
        }
    
    def detect(self, file_path: str, content: str) -> FileTypeInfo:
        """Detect file type and extract components."""
        path = Path(file_path)
        ext = path.suffix.lower()
        
        # Handle compound extensions like .xaml.cs
        if '.xaml.cs' in file_path:
            ext = '.xaml.cs'
        
        source_lang = self.EXTENSION_MAP.get(ext)
        if not source_lang:
            log.warning(f"Unknown file extension: {ext} for {file_path}")
            source_lang = self._guess_language(content)
        
        # Extract components
        extractor = self.component_extractors.get(source_lang, self._extract_generic_components)
        components = extractor(file_path, content)
        
        # Determine primary component and category
        primary = components[0].type if components else ComponentType.CLASS
        category = self._categorize(components, source_lang)
        
        # Analyze for database/external access
        has_db = self._has_database_access(content, source_lang)
        has_ext = self._has_external_calls(content, source_lang)
        
        return FileTypeInfo(
            path=file_path,
            source_language=source_lang,
            file_category=category,
            primary_component=primary,
            components=components,
            total_lines=len(content.splitlines()),
            has_database_access=has_db,
            has_external_calls=has_ext,
        )
    
    def _guess_language(self, content: str) -> SourceLanguage:
        """Guess language from content patterns."""
        if 'VERSION 5.00' in content or 'Attribute VB_Name' in content:
            return SourceLanguage.VB6
        if 'namespace ' in content and 'using System;' in content:
            return SourceLanguage.CSHARP
        if '<process ' in content or 'xmlns:tibco' in content:
            return SourceLanguage.TIBCO_BW
        if '<Window ' in content or '<UserControl ' in content:
            return SourceLanguage.WPF_XAML
        return SourceLanguage.UNKNOWN
    
    def _categorize(self, components: List[ComponentInfo], lang: SourceLanguage) -> FileCategory:
        """Categorize file based on components."""
        if not components:
            return FileCategory.BUSINESS_LOGIC
        
        types = {c.type for c in components}
        
        if ComponentType.FORM in types or ComponentType.DIALOG in types:
            return FileCategory.UI
        if ComponentType.DATA_ACCESS in types or ComponentType.ENTITY in types:
            return FileCategory.DATA_ACCESS
        if ComponentType.SERVICE in types and ComponentType.DATA_ACCESS in types:
            return FileCategory.BUSINESS_LOGIC
        if ComponentType.CONFIG in types or ComponentType.UTILITY in types:
            return FileCategory.INFRASTRUCTURE
        
        return FileCategory.BUSINESS_LOGIC
    
    def _has_database_access(self, content: str, lang: SourceLanguage) -> bool:
        """Check if file contains database access patterns."""
        db_patterns = {
            SourceLanguage.VB6: [
                r'ADODB', r'Recordset', r'Connection', r'Command',
                r'Open\s+"[^"]*\.mdb"', r'Dim.*Database'
            ],
            SourceLanguage.CSHARP: [
                r'SqlConnection', r'EntityFramework', r'DbContext',
                r'IDbConnection', r'Dapper', r'ExecuteSql'
            ],
        }
        patterns = db_patterns.get(lang, [])
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False
    
    def _has_external_calls(self, content: str, lang: SourceLanguage) -> bool:
        """Check if file makes external API/service calls."""
        ext_patterns = {
            SourceLanguage.VB6: [
                r'CreateObject\s*\(', r'GetObject\s*\(', r'Shell\s*\(',
                r'MSXML2\.XMLHTTP', r'WinHttp'
            ],
            SourceLanguage.CSHARP: [
                r'HttpClient', r'WebRequest', r'RestClient',
                r'HttpWebRequest', r'WebClient'
            ],
        }
        patterns = ext_patterns.get(lang, [])
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False
    
    # ─── Component Extractors ──────────────────────────────────────────────
    
    def _extract_vb6_components(self, file_path: str, content: str) -> List[ComponentInfo]:
        """Extract components from VB6 files."""
        components = []
        path = Path(file_path)
        ext = path.suffix.lower()
        
        if ext == '.frm':
            # VB6 Form - single component
            match = self.VB6_PATTERNS[ComponentType.FORM].search(content)
            if match:
                components.append(ComponentInfo(
                    name=match.group(1) if match.lastindex else path.stem,
                    type=ComponentType.FORM,
                    source_language=SourceLanguage.VB6,
                    raw_content=content,
                    start_line=1,
                    end_line=len(content.splitlines()),
                    suggested_target_type='React Component',
                    conversion_confidence=0.75,
                ))
        
        elif ext == '.cls':
            # VB6 Class
            match = self.VB6_PATTERNS[ComponentType.CLASS].search(content)
            if match:
                # Check if it's a data access class
                comp_type = ComponentType.CLASS
                suggested = 'Java Class'
                
                if 'ADODB' in content or 'Recordset' in content:
                    comp_type = ComponentType.DATA_ACCESS
                    suggested = 'Spring Repository'
                elif any(x in content for x in ['Business', 'Service', 'Logic']):
                    comp_type = ComponentType.SERVICE
                    suggested = 'Spring Service'
                
                components.append(ComponentInfo(
                    name=path.stem,
                    type=comp_type,
                    source_language=SourceLanguage.VB6,
                    raw_content=content,
                    start_line=1,
                    end_line=len(content.splitlines()),
                    suggested_target_type=suggested,
                    conversion_confidence=0.7,
                ))
        
        elif ext == '.bas':
            # VB6 Module (static methods)
            components.append(ComponentInfo(
                name=path.stem,
                type=ComponentType.MODULE,
                source_language=SourceLanguage.VB6,
                raw_content=content,
                start_line=1,
                end_line=len(content.splitlines()),
                suggested_target_type='Java Utility Class',
                conversion_confidence=0.8,
            ))
        
        elif ext == '.vbp':
            # Project file - treat as config
            components.append(ComponentInfo(
                name=path.stem,
                type=ComponentType.CONFIG,
                source_language=SourceLanguage.VB6,
                raw_content=content,
                start_line=1,
                end_line=len(content.splitlines()),
                suggested_target_type='Project Config',
                conversion_confidence=0.9,
            ))
        
        return components or [self._create_generic_component(file_path, content, SourceLanguage.VB6)]
    
    def _extract_csharp_components(self, file_path: str, content: str) -> List[ComponentInfo]:
        """Extract components from C# files."""
        components = []
        lines = content.splitlines()
        
        # Find class/interface/enum definitions with line numbers
        for pattern_type, pattern in self.CSHARP_PATTERNS.items():
            for match in pattern.finditer(content):
                name = match.group(1)
                start_pos = match.start()
                
                # Calculate line number
                line_num = content[:start_pos].count('\n') + 1
                
                # Extract the component block (simplified)
                # In practice, you'd parse braces to find the full block
                end_line = min(line_num + 100, len(lines))  # Approximate
                
                comp_content = '\n'.join(lines[line_num-1:end_line])
                
                components.append(ComponentInfo(
                    name=name,
                    type=pattern_type,
                    source_language=SourceLanguage.CSHARP,
                    raw_content=comp_content,
                    start_line=line_num,
                    end_line=end_line,
                    suggested_target_type=self._map_csharp_to_target(pattern_type),
                    conversion_confidence=0.8,
                ))
        
        return components or [self._create_generic_component(file_path, content, SourceLanguage.CSHARP)]
    
    def _extract_tibco_components(self, file_path: str, content: str) -> List[ComponentInfo]:
        """Extract components from Tibco BW files."""
        components = []
        
        # Main process
        for match in self.TIBCO_PATTERNS[ComponentType.PROCESS].finditer(content):
            components.append(ComponentInfo(
                name=match.group(1),
                type=ComponentType.PROCESS,
                source_language=SourceLanguage.TIBCO_BW,
                raw_content=content,
                start_line=1,
                end_line=len(content.splitlines()),
                suggested_target_type='Spring Integration Flow',
                conversion_confidence=0.65,
            ))
        
        return components or [self._create_generic_component(file_path, content, SourceLanguage.TIBCO_BW)]
    
    def _extract_wpf_components(self, file_path: str, content: str) -> List[ComponentInfo]:
        """Extract components from WPF files."""
        components = []
        path = Path(file_path)
        
        if path.suffix == '.xaml':
            # XAML View
            components.append(ComponentInfo(
                name=path.stem,
                type=ComponentType.FORM,
                source_language=SourceLanguage.WPF_XAML,
                raw_content=content,
                start_line=1,
                end_line=len(content.splitlines()),
                suggested_target_type='React Component (JSX)',
                conversion_confidence=0.75,
            ))
        else:
            # Code-behind
            components.extend(self._extract_csharp_components(file_path, content))
        
        return components or [self._create_generic_component(file_path, content, SourceLanguage.WPF_XAML)]
    
    def _extract_generic_components(self, file_path: str, content: str) -> List[ComponentInfo]:
        """Fallback for unknown file types."""
        return [self._create_generic_component(file_path, content, SourceLanguage.UNKNOWN)]
    
    def _create_generic_component(self, file_path: str, content: str, lang: SourceLanguage) -> ComponentInfo:
        """Create a generic component info for unrecognized files."""
        return ComponentInfo(
            name=Path(file_path).stem,
            type=ComponentType.CLASS,
            source_language=lang,
            raw_content=content,
            start_line=1,
            end_line=len(content.splitlines()),
            suggested_target_type='Unknown - Manual Review Required',
            conversion_confidence=0.3,
        )
    
    def _map_csharp_to_target(self, comp_type: ComponentType) -> str:
        """Map C# component type to target type."""
        mapping = {
            ComponentType.CLASS: 'Java Class',
            ComponentType.INTERFACE: 'Java Interface',
            ComponentType.ENUM: 'Java Enum',
            ComponentType.SERVICE: 'Spring Service',
            ComponentType.DATA_ACCESS: 'Spring Repository',
        }
        return mapping.get(comp_type, 'Java Class')


# Global detector instance
detector = FileTypeDetector()


def detect_file_type(file_path: str, content: str) -> FileTypeInfo:
    """Convenience function to detect file type."""
    return detector.detect(file_path, content)
