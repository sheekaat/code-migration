"""
Knowledge Base for File Type and Component Patterns

Stores and retrieves learned patterns for different file types and components.
Used to improve conversion quality over time.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import json

from ingestion.file_type_registry import ComponentType, FileCategory
from shared.models import SourceLanguage, TargetLanguage
from shared.config import get_logger

log = get_logger(__name__)


@dataclass
class LearnedPattern:
    """A learned conversion pattern."""
    pattern_id: str
    source_language: SourceLanguage
    target_language: TargetLanguage
    component_type: ComponentType
    
    # Pattern matching
    source_signature: str  # Regex or key phrases that identify this pattern
    target_template: str  # The conversion template/output
    
    # Metadata
    success_count: int = 0
    failure_count: int = 0
    first_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    accuracy_score: float = 0.0
    
    # Context
    example_source: str = ""
    example_target: str = ""
    common_issues: List[str] = field(default_factory=list)


@dataclass
class FileTypeKnowledge:
    """Knowledge about a specific file type."""
    source_language: SourceLanguage
    file_extension: str
    component_types: List[ComponentType]
    common_patterns: List[str]
    conversion_challenges: List[str]
    recommended_approach: str


class FileTypeKnowledgeBase:
    """Knowledge base for file type and component patterns."""
    
    KB_PATH = Path("knowledge_base/file_type_patterns.json")
    
    def __init__(self):
        self.patterns: Dict[str, LearnedPattern] = {}
        self.file_type_knowledge: Dict[str, FileTypeKnowledge] = {}
        self._load()
    
    def _load(self):
        """Load knowledge base from disk."""
        if self.KB_PATH.exists():
            try:
                with open(self.KB_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for pattern_data in data.get('patterns', []):
                    pattern = LearnedPattern(**pattern_data)
                    self.patterns[pattern.pattern_id] = pattern
                
                for lang, knowledge_data in data.get('file_types', {}).items():
                    self.file_type_knowledge[lang] = FileTypeKnowledge(**knowledge_data)
                
                log.info(f"Loaded {len(self.patterns)} patterns from knowledge base")
            except Exception as e:
                log.error(f"Failed to load knowledge base: {e}")
    
    def save(self):
        """Save knowledge base to disk."""
        try:
            self.KB_PATH.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                'patterns': [asdict(p) for p in self.patterns.values()],
                'file_types': {
                    k: asdict(v) for k, v in self.file_type_knowledge.items()
                },
                'updated_at': datetime.now().isoformat(),
            }
            
            with open(self.KB_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
            
            log.info(f"Saved {len(self.patterns)} patterns to knowledge base")
        except Exception as e:
            log.error(f"Failed to save knowledge base: {e}")
    
    def find_pattern(
        self,
        source_lang: SourceLanguage,
        target_lang: TargetLanguage,
        component_type: ComponentType,
        source_snippet: str,
    ) -> Optional[LearnedPattern]:
        """Find a matching pattern for a source snippet."""
        for pattern in self.patterns.values():
            if (pattern.source_language == source_lang and
                pattern.target_language == target_lang and
                pattern.component_type == component_type):
                
                # Check if signature matches
                if pattern.source_signature in source_snippet:
                    pattern.last_used = datetime.now().isoformat()
                    return pattern
        
        return None
    
    def record_pattern(
        self,
        source_lang: SourceLanguage,
        target_lang: TargetLanguage,
        component_type: ComponentType,
        source_signature: str,
        target_template: str,
        example_source: str = "",
        example_target: str = "",
    ) -> LearnedPattern:
        """Record a new learned pattern."""
        pattern_id = f"{source_lang.value}_{component_type.name}_{target_lang.value}_{len(self.patterns)}"
        
        pattern = LearnedPattern(
            pattern_id=pattern_id,
            source_language=source_lang,
            target_language=target_lang,
            component_type=component_type,
            source_signature=source_signature,
            target_template=target_template,
            example_source=example_source,
            example_target=example_target,
        )
        
        self.patterns[pattern_id] = pattern
        self.save()
        
        log.info(f"Recorded new pattern: {pattern_id}")
        return pattern
    
    def record_success(self, pattern_id: str, accuracy: float):
        """Record a successful pattern application."""
        if pattern_id in self.patterns:
            pattern = self.patterns[pattern_id]
            pattern.success_count += 1
            # Update rolling accuracy score
            total = pattern.success_count + pattern.failure_count
            pattern.accuracy_score = ((pattern.accuracy_score * (total - 1)) + accuracy) / total
            pattern.last_used = datetime.now().isoformat()
            self.save()
    
    def record_failure(self, pattern_id: str, issue: str):
        """Record a failed pattern application."""
        if pattern_id in self.patterns:
            pattern = self.patterns[pattern_id]
            pattern.failure_count += 1
            if issue not in pattern.common_issues:
                pattern.common_issues.append(issue)
            self.save()
    
    def get_file_type_knowledge(self, source_lang: SourceLanguage) -> Optional[FileTypeKnowledge]:
        """Get stored knowledge about a file type."""
        return self.file_type_knowledge.get(source_lang.value)
    
    def set_file_type_knowledge(self, knowledge: FileTypeKnowledge):
        """Store knowledge about a file type."""
        self.file_type_knowledge[knowledge.source_language.value] = knowledge
        self.save()


# Initialize default file type knowledge
def _init_default_knowledge():
    """Initialize default knowledge for common file types."""
    kb = FileTypeKnowledgeBase()
    
    # VB6 Knowledge
    if SourceLanguage.VB6.value not in kb.file_type_knowledge:
        vb6_knowledge = FileTypeKnowledge(
            source_language=SourceLanguage.VB6,
            file_extension='.frm,.cls,.bas,.vbp',
            component_types=[
                ComponentType.FORM,
                ComponentType.CLASS,
                ComponentType.MODULE,
                ComponentType.DATA_ACCESS,
            ],
            common_patterns=[
                'Form with ADODB data binding',
                'Business logic class with validation',
                'Utility module with shared functions',
                'Data access class with Recordset operations',
            ],
            conversion_challenges=[
                'ADODB to JPA mapping',
                'Form event handling to React hooks',
                'Global state to Context API',
                'Error handling (On Error) to try/catch',
            ],
            recommended_approach='''
1. Detect component type by extension and content analysis
2. For Forms: Convert to React with useState/useEffect
3. For Classes: Convert to Spring Service or Repository
4. For Modules: Convert to Java Utility class
5. Always preserve business logic exactly
            '''.strip(),
        )
        kb.set_file_type_knowledge(vb6_knowledge)
    
    # C# Knowledge
    if SourceLanguage.CSHARP.value not in kb.file_type_knowledge:
        csharp_knowledge = FileTypeKnowledge(
            source_language=SourceLanguage.CSHARP,
            file_extension='.cs,.csproj',
            component_types=[
                ComponentType.CLASS,
                ComponentType.INTERFACE,
                ComponentType.ENUM,
                ComponentType.SERVICE,
                ComponentType.DATA_ACCESS,
            ],
            common_patterns=[
                'Controller with action methods',
                'Service with business logic',
                'Repository with LINQ queries',
                'Entity with DataAnnotations',
            ],
            conversion_challenges=[
                'LINQ to Stream API conversion',
                'async/await to CompletableFuture',
                'DataAnnotations to JPA annotations',
                'Dependency injection mapping',
            ],
            recommended_approach='''
1. Parse class type by attributes and inheritance
2. Controllers → @RestController
3. Services → @Service
4. Repositories → @Repository with JPA
5. Entities → @Entity with proper mappings
            '''.strip(),
        )
        kb.set_file_type_knowledge(csharp_knowledge)
    
    # Tibco BW Knowledge
    if SourceLanguage.TIBCO_BW.value not in kb.file_type_knowledge:
        tibco_knowledge = FileTypeKnowledge(
            source_language=SourceLanguage.TIBCO_BW,
            file_extension='.bwp,.process',
            component_types=[
                ComponentType.PROCESS,
                ComponentType.ACTIVITY,
                ComponentType.WORKFLOW,
            ],
            common_patterns=[
                'HTTP Receiver with response',
                'JDBC Query with mapping',
                'Process with publish-subscribe',
                'Workflow with decision logic',
            ],
            conversion_challenges=[
                'Activity mapping to Spring Integration',
                'XPath to SpEL expressions',
                'Publish-subscribe to MessageChannels',
                'Transaction boundaries',
            ],
            recommended_approach='''
1. Parse process XML to activity graph
2. Map activities to Spring Integration handlers
3. HTTP Receiver → Http.inboundGateway
4. JDBC → JdbcTemplate or Repository
5. Mapper → Transformer
6. Publish → MessageChannel.send
            '''.strip(),
        )
        kb.set_file_type_knowledge(tibco_knowledge)
    
    log.info("Initialized default file type knowledge")


# Initialize on module load
_init_default_knowledge()


# Global instance
file_kb = FileTypeKnowledgeBase()
