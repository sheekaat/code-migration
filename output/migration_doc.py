"""
Migration Document Generator

Tracks all details of a code migration run for later investigation and accuracy fixes.
This document is created fresh for every migration and stored in the output folder.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

log = logging.getLogger(__name__)


class MigrationStatus(Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


@dataclass
class FileMigrationRecord:
    """Record of a single file's migration attempt."""
    source_path: str
    source_language: str
    target_language: str
    source_hash: str  # MD5 hash of source content
    converted_code: str
    conversion_status: str
    confidence: float
    detected_component_type: Optional[str] = None
    package_path: Optional[str] = None
    class_name: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    validation_issues: List[Dict] = field(default_factory=list)
    conversion_attempts: int = 1
    llm_prompt_used: Optional[str] = None
    conversion_time_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class MigrationSession:
    """Complete record of a migration session."""
    session_id: str
    start_time: str
    source_repo_path: str
    target_language: str
    total_files: int = 0
    processed_files: int = 0
    successful_conversions: int = 0
    failed_conversions: int = 0
    needs_review: int = 0
    status: str = MigrationStatus.IN_PROGRESS.value
    files: List[FileMigrationRecord] = field(default_factory=list)
    config_used: Dict = field(default_factory=dict)
    end_time: Optional[str] = None
    summary_stats: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "source_repo_path": self.source_repo_path,
            "target_language": self.target_language,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "successful_conversions": self.successful_conversions,
            "failed_conversions": self.failed_conversions,
            "needs_review": self.needs_review,
            "status": self.status,
            "files": [f.to_dict() for f in self.files],
            "config_used": self.config_used,
            "end_time": self.end_time,
            "summary_stats": self.summary_stats,
        }


class MigrationDocument:
    """
    Manages migration documentation for accuracy module investigation.
    
    This document tracks:
    - Every file processed
    - Source content hashes for integrity
    - Conversion details and prompts used
    - Validation issues found
    - Accuracy scores and confidence levels
    """
    
    def __init__(self, output_dir: Path, session_id: Optional[str] = None):
        self.output_dir = Path(output_dir)
        self.session_id = session_id or self._generate_session_id()
        self.doc_path = self.output_dir / f"migration_{self.session_id}.json"
        self.session: Optional[MigrationSession] = None
        
    def _generate_session_id(self) -> str:
        """Generate unique session ID based on timestamp."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
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
            start_time=datetime.now().isoformat(),
            source_repo_path=source_repo_path,
            target_language=target_language,
            total_files=total_files,
            config_used=config or {},
        )
        self._save()
        log.info(f"[MIGRATION_DOC] Started session {self.session_id} for {total_files} files")
    
    def add_file_record(
        self,
        source_path: str,
        source_content: str,
        converted_code: str,
        source_language: str,
        target_language: str,
        conversion_status: str,
        confidence: float,
        detected_component_type: Optional[str] = None,
        package_path: Optional[str] = None,
        class_name: Optional[str] = None,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        validation_issues: Optional[List[Dict]] = None,
        llm_prompt_used: Optional[str] = None,
        conversion_time_seconds: float = 0.0,
    ) -> FileMigrationRecord:
        """Add a file migration record."""
        if not self.session:
            raise RuntimeError("Session not started")
        
        # Calculate source content hash for integrity checking
        source_hash = hashlib.md5(source_content.encode()).hexdigest()
        
        record = FileMigrationRecord(
            source_path=source_path,
            source_language=source_language,
            target_language=target_language,
            source_hash=source_hash,
            converted_code=converted_code,
            conversion_status=conversion_status,
            confidence=confidence,
            detected_component_type=detected_component_type,
            package_path=package_path,
            class_name=class_name,
            errors=errors or [],
            warnings=warnings or [],
            validation_issues=validation_issues or [],
            llm_prompt_used=llm_prompt_used,
            conversion_time_seconds=conversion_time_seconds,
        )
        
        self.session.files.append(record)
        self.session.processed_files += 1
        
        # Update counters
        if conversion_status == "completed":
            self.session.successful_conversions += 1
        elif conversion_status == "failed":
            self.session.failed_conversions += 1
        elif conversion_status == "needs_review":
            self.session.needs_review += 1
        
        self._save()
        return record
    
    def update_file_record(
        self,
        source_path: str,
        converted_code: Optional[str] = None,
        conversion_status: Optional[str] = None,
        confidence: Optional[float] = None,
        errors: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        validation_issues: Optional[List[Dict]] = None,
        increment_attempt: bool = False,
    ) -> None:
        """Update an existing file record (used by accuracy module)."""
        if not self.session:
            raise RuntimeError("Session not started")
        
        for record in self.session.files:
            if record.source_path == source_path:
                if converted_code is not None:
                    record.converted_code = converted_code
                if conversion_status is not None:
                    record.conversion_status = conversion_status
                if confidence is not None:
                    record.confidence = confidence
                if errors is not None:
                    record.errors = errors
                if warnings is not None:
                    record.warnings = warnings
                if validation_issues is not None:
                    record.validation_issues = validation_issues
                if increment_attempt:
                    record.conversion_attempts += 1
                
                self._save()
                log.info(f"[MIGRATION_DOC] Updated record for {source_path}")
                return
        
        log.warning(f"[MIGRATION_DOC] Could not find record for {source_path}")
    
    def get_file_record(self, source_path: str) -> Optional[FileMigrationRecord]:
        """Get a file record by source path."""
        if not self.session:
            return None
        
        for record in self.session.files:
            if record.source_path == source_path:
                return record
        return None
    
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
        log.info(f"[MIGRATION_DOC] Ended session {self.session_id} with status {status.value}")
    
    def _save(self) -> None:
        """Save the migration document to disk."""
        if not self.session:
            return
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.doc_path, 'w', encoding='utf-8') as f:
            json.dump(self.session.to_dict(), f, indent=2, ensure_ascii=False)
    
    def load(self) -> bool:
        """Load an existing migration document."""
        if not self.doc_path.exists():
            return False
        
        try:
            with open(self.doc_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Reconstruct session from JSON
            self.session = MigrationSession(
                session_id=data["session_id"],
                start_time=data["start_time"],
                source_repo_path=data["source_repo_path"],
                target_language=data["target_language"],
                total_files=data.get("total_files", 0),
                processed_files=data.get("processed_files", 0),
                successful_conversions=data.get("successful_conversions", 0),
                failed_conversions=data.get("failed_conversions", 0),
                needs_review=data.get("needs_review", 0),
                status=data.get("status", MigrationStatus.IN_PROGRESS.value),
                files=[FileMigrationRecord(**f) for f in data.get("files", [])],
                config_used=data.get("config_used", {}),
                end_time=data.get("end_time"),
                summary_stats=data.get("summary_stats", {}),
            )
            return True
        except Exception as e:
            log.error(f"[MIGRATION_DOC] Failed to load {self.doc_path}: {e}")
            return False
    
    def get_low_confidence_files(self, threshold: float = 0.85) -> List[FileMigrationRecord]:
        """Get all files below confidence threshold."""
        if not self.session:
            return []
        
        return [f for f in self.session.files if f.confidence < threshold]
    
    def get_failed_files(self) -> List[FileMigrationRecord]:
        """Get all failed conversions."""
        if not self.session:
            return []
        
        return [f for f in self.session.files if f.conversion_status == "failed"]
    
    def get_files_needing_fix(self) -> List[FileMigrationRecord]:
        """Get files that need accuracy fixes."""
        if not self.session:
            return []
        
        return [
            f for f in self.session.files 
            if f.conversion_status in ["failed", "needs_review"] 
            or f.validation_issues
            or f.errors
        ]


class MigrationDocManager:
    """Manager for migration documents in the output folder."""
    
    def __init__(self, base_output_dir: Path):
        self.base_output_dir = Path(base_output_dir)
    
    def get_migration_doc(self, job_id: Optional[str] = None) -> MigrationDocument:
        """Get or create a migration document for a job."""
        # Use the migration folder in output
        migration_dir = self.base_output_dir / "migration"
        migration_dir.mkdir(parents=True, exist_ok=True)
        
        if job_id:
            return MigrationDocument(migration_dir, session_id=job_id)
        
        # Find the most recent migration doc
        docs = sorted(migration_dir.glob("migration_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if docs:
            session_id = docs[0].stem.replace("migration_", "")
            return MigrationDocument(migration_dir, session_id=session_id)
        
        # Create new
        return MigrationDocument(migration_dir)
    
    def list_migration_docs(self) -> List[Path]:
        """List all migration documents."""
        migration_dir = self.base_output_dir / "migration"
        if not migration_dir.exists():
            return []
        
        return sorted(migration_dir.glob("migration_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
