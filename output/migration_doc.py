"""
Migration Document - Tracks migration progress and enables resume functionality.
"""

from __future__ import annotations
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from shared.config import get_logger

log = get_logger(__name__)


class MigrationStatus(Enum):
    """Status of a migration session."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"


@dataclass
class FileMigrationRecord:
    """Record of a single file's migration attempt."""
    source_path: str
    source_content: str = ""
    converted_code: str = ""
    source_hash: str = ""
    source_language: str = "unknown"
    target_language: str = "unknown"
    conversion_status: str = "pending"
    confidence: float = 0.0
    detected_component_type: Optional[str] = None
    package_path: Optional[str] = None
    class_name: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    conversion_time_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def __post_init__(self):
        if not self.source_hash and self.source_content:
            self.source_hash = hashlib.md5(self.source_content.encode()).hexdigest()


@dataclass
class MigrationSession:
    """A single migration session."""
    session_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    source_repo_path: str = ""
    target_language: str = ""
    total_files: int = 0
    processed_files: int = 0
    status: str = "in_progress"
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    files: List[FileMigrationRecord] = field(default_factory=list)
    summary_stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MigrationDocument:
    """Tracks the entire migration process with file-level details."""
    output_dir: Path
    session_id: str = ""
    session: Optional[MigrationSession] = None
    
    def __post_init__(self):
        if not self.session_id:
            self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def start_session(
        self,
        source_repo_path: str,
        target_language: str,
        total_files: int,
        config: Optional[Dict] = None
    ) -> None:
        """Start a new migration session."""
        self.session = MigrationSession(
            session_id=self.session_id,
            source_repo_path=source_repo_path,
            target_language=target_language,
            total_files=total_files,
            config=config or {},
            status=MigrationStatus.IN_PROGRESS.value
        )
        self._save()
        log.info(f"Started migration session: {self.session_id}")
    
    def add_file_record(
        self,
        source_path: str,
        source_content: str,
        converted_code: str,
        source_language: str = "unknown",
        target_language: str = "unknown",
        conversion_status: str = "pending",
        confidence: float = 0.0,
        detected_component_type: Optional[str] = None,
        package_path: Optional[str] = None,
        class_name: Optional[str] = None,
        errors: Optional[List[str]] = None,
        conversion_time_seconds: float = 0.0
    ) -> None:
        """Add a file record to the session."""
        if not self.session:
            log.warning("Cannot add file record - no active session")
            return
        
        record = FileMigrationRecord(
            source_path=source_path,
            source_content=source_content[:1000] if source_content else "",  # Truncate for storage
            converted_code=converted_code[:1000] if converted_code else "",  # Truncate for storage
            source_language=source_language,
            target_language=target_language,
            conversion_status=conversion_status,
            confidence=confidence,
            detected_component_type=detected_component_type,
            package_path=package_path,
            class_name=class_name,
            errors=errors or [],
            conversion_time_seconds=conversion_time_seconds
        )
        
        # Check if this file already exists in the session
        existing_idx = None
        for idx, r in enumerate(self.session.files):
            if r.source_path == source_path:
                existing_idx = idx
                break
        
        if existing_idx is not None:
            self.session.files[existing_idx] = record
        else:
            self.session.files.append(record)
        
        self.session.processed_files = len(self.session.files)
        self._save()
    
    def end_session(
        self,
        status: MigrationStatus,
        summary_stats: Optional[Dict] = None
    ) -> None:
        """End the migration session."""
        if not self.session:
            return
        
        self.session.status = status.value
        self.session.end_time = datetime.now().isoformat()
        self.session.summary_stats = summary_stats or {}
        self._save()
        log.info(f"Ended migration session: {self.session_id} with status: {status.value}")
    
    def load(self) -> bool:
        """Load migration document from disk. Returns True if found."""
        doc_path = self._get_doc_path()
        if not doc_path.exists():
            return False
        
        try:
            with open(doc_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.session_id = data.get('session_id', self.session_id)
            
            if 'session' in data and data['session']:
                session_data = data['session']
                self.session = MigrationSession(
                    session_id=session_data.get('session_id', self.session_id),
                    source_repo_path=session_data.get('source_repo_path', ''),
                    target_language=session_data.get('target_language', ''),
                    total_files=session_data.get('total_files', 0),
                    processed_files=session_data.get('processed_files', 0),
                    status=session_data.get('status', 'in_progress'),
                    start_time=session_data.get('start_time', datetime.now().isoformat()),
                    end_time=session_data.get('end_time'),
                    config=session_data.get('config', {}),
                    summary_stats=session_data.get('summary_stats', {}),
                    files=[FileMigrationRecord(**f) for f in session_data.get('files', [])]
                )
            
            log.info(f"Loaded migration document: {self.session_id}")
            return True
        except Exception as e:
            log.error(f"Failed to load migration document: {e}")
            return False
    
    def _save(self) -> None:
        """Save migration document to disk."""
        doc_path = self._get_doc_path()
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'session_id': self.session_id,
            'session': None
        }
        
        if self.session:
            session_dict = asdict(self.session)
            data['session'] = session_dict
        
        try:
            with open(doc_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            log.error(f"Failed to save migration document: {e}")
    
    def _get_doc_path(self) -> Path:
        """Get path to migration document file."""
        return self.output_dir / 'MIGRATION_DOC.json'


@dataclass
class MigrationDocManager:
    """Manager for migration documents."""
    
    @staticmethod
    def get_or_create_migration_doc(output_dir: Path) -> MigrationDocument:
        """Get existing migration doc or create new one."""
        doc = MigrationDocument(output_dir)
        if doc.load():
            log.info(f"Resuming migration: {doc.session_id}")
        return doc
