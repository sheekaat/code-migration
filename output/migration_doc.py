"""
Migration Document Tracking

Tracks migration session state, file records, and progress.
"""
import json
import hashlib
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
from enum import Enum


class MigrationStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class FileRecord:
    """Record of a single file's migration."""
    source_path: str
    source_hash: str
    converted_code: Optional[str] = None
    target_language: str = ""
    conversion_status: str = "pending"
    confidence: float = 0.0
    detected_component_type: Optional[str] = None
    package_path: Optional[str] = None
    class_name: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    conversion_time_seconds: float = 0.0
    converted_at: Optional[str] = None


@dataclass
class MigrationSession:
    """Migration session metadata."""
    session_id: str
    started_at: str
    source_repo_path: str
    target_language: str
    status: str = "in_progress"
    completed_at: Optional[str] = None
    total_files: int = 0
    processed_files: int = 0
    successful_files: int = 0
    failed_files: int = 0


class MigrationDocument:
    """
    Tracks migration progress and enables resume functionality.
    
    Stored as JSON in output/migration_job_*/MIGRATION_DOC.json
    """
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.doc_path = self.output_dir / "MIGRATION_DOC.json"
        self.session: Optional[MigrationSession] = None
        self.files: Dict[str, FileRecord] = {}  # source_path -> FileRecord
        
        # Load existing if present
        if self.doc_path.exists():
            self._load()
    
    @property
    def session_id(self) -> Optional[str]:
        """Get current session ID."""
        return self.session.session_id if self.session else None
    
    def load(self) -> bool:
        """Load existing migration document. Returns True if loaded successfully."""
        if not self.doc_path.exists():
            return False
        try:
            self._load()
            return True
        except Exception:
            return False
    
    def _load(self):
        """Internal: Load existing migration document."""
        try:
            with open(self.doc_path, 'r') as f:
                data = json.load(f)
            
            # Load session
            if 'session' in data:
                self.session = MigrationSession(**data['session'])
            
            # Load file records
            for path, record_data in data.get('files', {}).items():
                self.files[path] = FileRecord(**record_data)
                
        except Exception:
            # If corrupt, start fresh
            self.session = None
            self.files = {}
    
    def _save(self):
        """Save migration document to disk."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        data = {
            'version': '1.0',
            'saved_at': datetime.now().isoformat(),
            'session': asdict(self.session) if self.session else None,
            'files': {path: asdict(record) for path, record in self.files.items()}
        }
        
        with open(self.doc_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def start_session(self, source_repo_path: str, target_language: str, total_files: int = 0, config: dict = None):
        """Start a new migration session."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.session = MigrationSession(
            session_id=timestamp,
            started_at=datetime.now().isoformat(),
            source_repo_path=source_repo_path,
            target_language=target_language,
            total_files=total_files
        )
        self._save()
    
    def add_file_record(
        self,
        source_path: str,
        source_content: str,
        converted_code: Optional[str] = None,
        source_language: str = "",
        target_language: str = "",
        conversion_status: str = "pending",
        confidence: float = 0.0,
        detected_component_type: Optional[str] = None,
        package_path: Optional[str] = None,
        class_name: Optional[str] = None,
        errors: Optional[List[str]] = None,
        conversion_time_seconds: float = 0.0
    ):
        """Add or update a file record."""
        source_hash = hashlib.md5(source_content.encode()).hexdigest()
        
        self.files[source_path] = FileRecord(
            source_path=source_path,
            source_hash=source_hash,
            converted_code=converted_code,
            target_language=target_language,
            conversion_status=conversion_status,
            confidence=confidence,
            detected_component_type=detected_component_type,
            package_path=package_path,
            class_name=class_name,
            errors=errors or [],
            conversion_time_seconds=conversion_time_seconds,
            converted_at=datetime.now().isoformat() if converted_code else None
        )
        
        # Update session counts
        if self.session:
            self.session.processed_files = len([f for f in self.files.values() if f.converted_at])
            self.session.successful_files = len([f for f in self.files.values() if f.conversion_status == 'completed'])
            self.session.failed_files = len([f for f in self.files.values() if f.conversion_status == 'failed'])
        
        self._save()
    
    def get_file_record(self, source_path: str) -> Optional[FileRecord]:
        """Get record for a specific file."""
        return self.files.get(source_path)
    
    def is_file_converted(self, source_path: str, current_content: str) -> bool:
        """Check if file was already converted and hasn't changed."""
        record = self.files.get(source_path)
        if not record or not record.converted_code:
            return False
        
        # Check if source changed
        current_hash = hashlib.md5(current_content.encode()).hexdigest()
        return record.source_hash == current_hash
    
    def update_file_record(
        self,
        source_path: str,
        converted_code: Optional[str] = None,
        conversion_status: Optional[str] = None,
        confidence: Optional[float] = None,
        errors: Optional[List[str]] = None,
        validation_issues: Optional[List[str]] = None,
        increment_attempt: bool = False,
    ):
        """Update an existing file record (backward compatibility)."""
        if source_path not in self.files:
            return
        
        record = self.files[source_path]
        
        if converted_code is not None:
            record.converted_code = converted_code
        if conversion_status is not None:
            record.conversion_status = conversion_status
        if confidence is not None:
            record.confidence = confidence
        if errors is not None:
            record.errors = errors
        if validation_issues is not None:
            record.errors = validation_issues
        
        record.converted_at = datetime.now().isoformat()
        
        # Update session counts
        if self.session:
            self.session.processed_files = len([f for f in self.files.values() if f.converted_at])
            self.session.successful_files = len([f for f in self.files.values() if f.conversion_status == 'completed'])
            self.session.failed_files = len([f for f in self.files.values() if f.conversion_status == 'failed'])
        
        self._save()
    
    def complete_session(self, status: str = "completed"):
        """Mark session as complete."""
        if self.session:
            self.session.status = status
            self.session.completed_at = datetime.now().isoformat()
            self._save()
    
    def end_session(self, status=None, summary_stats=None):
        """End session (backward compatibility alias for complete_session)."""
        status_str = status.value if hasattr(status, 'value') else str(status) if status else "completed"
        self.complete_session(status=status_str)
    
    def get_resumeable_files(self, all_source_files: List[str]) -> List[str]:
        """Get list of files that still need conversion."""
        needs_conversion = []
        
        for source_path in all_source_files:
            record = self.files.get(source_path)
            
            if not record:
                # Never converted
                needs_conversion.append(source_path)
            elif not record.converted_code:
                # No converted output
                needs_conversion.append(source_path)
            elif record.conversion_status == 'failed':
                # Previous failure - retry
                needs_conversion.append(source_path)
        
        return needs_conversion


# Backward compatibility alias
MigrationDocManager = MigrationDocument
