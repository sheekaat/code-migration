"""
Streaming Conversion Pipeline
Processes files one at a time and writes output immediately to reduce memory usage.
Ideal for large repositories.
"""

from __future__ import annotations
from pathlib import Path
from typing import Generator, Optional
import time

from shared.models import (
    WorkspaceManifest, SourceFile, ConversionResult,
    ConversionStatus, ComplexityTier, TargetLanguage,
)
from shared.config import get_logger
from conversion.rule_engine.engine import RuleEngine
from conversion.llm_converter.converter import LLMConverter
from output.generator import OutputGenerator
from output.migration_doc import MigrationDocument, MigrationStatus

log = get_logger(__name__)


class StreamingConversionPipeline:
    """
    Memory-efficient conversion pipeline that streams results.
    
    Yields after each file conversion instead of keeping all results in memory.
    Writes output files immediately for processed files.
    """

    def __init__(self, config: dict):
        self.config = config
        self.rule_engine = RuleEngine(config)
        self.llm_converter = LLMConverter(config)
        self.output_generator = OutputGenerator(config)
        self._threshold = config.get("conversion", {}).get("confidence_threshold", 0.75)
        self._rule_first = config.get("conversion", {}).get("rule_engine_first", True)
        self._stats = {"green": 0, "amber": 0, "red": 0, "total_tokens": 0, "processed": 0}
        self.base_package = config.get("java", {}).get("base_package", "com.macys").replace(".", "/")
        self.migration_doc: Optional[MigrationDocument] = None

    def convert_manifest_streaming(
        self,
        manifest: WorkspaceManifest,
        output_dir: Path,
    ) -> Generator[ConversionResult, None, None]:
        """
        Convert files one at a time, yielding after each file.
        
        Args:
            manifest: Workspace manifest with files to convert
            output_dir: Directory to write output files
            
        Yields:
            ConversionResult after each file is processed
        """
        if not manifest.target_language:
            raise ValueError("WorkspaceManifest has no target_language set")

        target = manifest.target_language
        order = manifest.dependency_graph.topological_order() if manifest.dependency_graph else [
            f.path for f in manifest.files
        ]

        # Filter out non-convertible files
        convertible_files = []
        skipped_files = []
        for path in order:
            sf = manifest.get_file_by_path(path)
            if sf and sf.skip_conversion:
                skipped_files.append((path, sf.skip_reason))
            else:
                convertible_files.append(path)
        
        if skipped_files:
            log.info(f"Skipping {len(skipped_files)} non-convertible files:")
            for path, reason in skipped_files[:10]:  # Show first 10
                log.info(f"  - {path}: {reason}")
            if len(skipped_files) > 10:
                log.info(f"  ... and {len(skipped_files) - 10} more")
        
        order = convertible_files
        total_files = len(order)
        log.info(f"Streaming conversion: {total_files} files to process")
        
        # Initialize migration document for tracking
        self.migration_doc = MigrationDocument(output_dir)
        
        # Check for existing migration to resume from
        resumed_files = {}
        if self.migration_doc.load():
            if self.migration_doc.session and self.migration_doc.session.status == MigrationStatus.IN_PROGRESS.value:
                log.info(f"[RESUME] Found incomplete migration. Session: {self.migration_doc.session_id}")
                log.info(f"[RESUME] Previously processed: {self.migration_doc.session.processed_files}/{self.migration_doc.session.total_files}")
                
                # Build map of successfully converted files
                for record in self.migration_doc.session.files:
                    if record.conversion_status in ["completed", "llm_converted"]:
                        # Check if source file changed (using hash)
                        sf = manifest.get_file_by_path(record.source_path)
                        if sf:
                            import hashlib
                            current_hash = hashlib.md5(sf.raw_content.encode()).hexdigest()
                            if current_hash == record.source_hash:
                                resumed_files[record.source_path] = record
                                log.info(f"[RESUME] Will skip {record.source_path} (already converted)")
                            else:
                                log.info(f"[RESUME] Source changed for {record.source_path}, will reconvert")
            else:
                # Start new session
                self.migration_doc = MigrationDocument(output_dir)
                self.migration_doc.start_session(
                    source_repo_path=str(manifest.files[0].path if manifest.files else "unknown"),
                    target_language=target.value,
                    total_files=total_files,
                    config=self.config
                )
        else:
            # Start new session
            self.migration_doc = MigrationDocument(output_dir)
            self.migration_doc.start_session(
                source_repo_path=str(manifest.files[0].path if manifest.files else "unknown"),
                target_language=target.value,
                total_files=total_files,
                config=self.config
            )

        for idx, path in enumerate(order, 1):
            sf = manifest.get_file_by_path(path)
            if not sf:
                log.warning(f"[{idx}/{total_files}] File not found in manifest: {path}")
                continue

            # Check if file was already converted in previous run
            if path in resumed_files:
                record = resumed_files[path]
                log.info(f"[{idx}/{total_files}] RESUMING {sf.path} - using cached conversion")
                
                # Reconstruct result from previous record
                from shared.models import ConversionResult, ConversionStatus
                result = ConversionResult(
                    source_file=sf,
                    target_language=target,
                    converted_code=record.converted_code,
                    status=ConversionStatus.LLM_CONVERTED if record.conversion_status == "llm_converted" else ConversionStatus.COMPLETED,
                    confidence=record.confidence,
                    llm_chunks_used=0,  # Not tracked in old record
                    total_tokens=0,
                )
                elapsed = 0.0
                
                # Write output immediately using Maven structure
                if result.converted_code:
                    try:
                        base_path = self._determine_package_path(sf)
                        splitter = FileSplitter()
                        segments = splitter.intelligent_split(
                            result.converted_code,
                            base_path=base_path,
                            language='java'
                        )
                        if segments:
                            splitter.write_segments(output_dir / "src" / "main" / "java", segments, base_package=self.base_package)
                            log.info(f"  ✓ Written output for {sf.path} (from cache)")
                        else:
                            # Single file - write directly
                            output_path = output_dir / "src" / "main" / "java" / Path(sf.path).with_suffix('.java')
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_text(result.converted_code, encoding='utf-8')
                            log.info(f"  ✓ Written output for {sf.path} (from cache)")
                    except Exception as e:
                        log.error(f"  ✗ Failed to write output for {sf.path}: {e}")
                
                # Re-add to migration doc
                if self.migration_doc:
                    self.migration_doc.add_file_record(
                        source_path=sf.path,
                        source_content=sf.raw_content,
                        converted_code=record.converted_code,
                        source_language=sf.language.value if sf.language else "unknown",
                        target_language=target.value,
                        conversion_status=record.conversion_status,
                        confidence=record.confidence,
                        detected_component_type=sf.pattern.value if sf.pattern else None,
                        package_path=self._determine_package_path(sf) if target == TargetLanguage.JAVA_SPRING else None,
                        class_name=Path(sf.path).stem,
                        conversion_time_seconds=0.0
                    )
                
                yield result
                continue

            log.info(f"[{idx}/{total_files}] Converting {sf.path} (tier: {sf.complexity_tier.value})")
            
            # Convert single file
            start_time = time.time()
            try:
                result = self._convert_file(sf, target)
                elapsed = time.time() - start_time
                log.info(f"  ✓ Converted in {elapsed:.1f}s (confidence: {result.confidence:.2f})")
            except Exception as e:
                elapsed = time.time() - start_time
                log.error(f"  ✗ Conversion failed after {elapsed:.1f}s: {e}")
                # Create error result
                from shared.models import ConversionStatus
                result = ConversionResult(
                    source_file=sf,
                    status=ConversionStatus.FAILED,
                    converted_code="",
                    confidence=0.0,
                    errors=[str(e)]
                )
            
            # Update stats
            self._stats[sf.complexity_tier.value] += 1
            self._stats["total_tokens"] += result.total_tokens
            self._stats["processed"] = idx
            
            # Track in migration document
            if self.migration_doc:
                self.migration_doc.add_file_record(
                    source_path=sf.path,
                    source_content=sf.raw_content,
                    converted_code=result.converted_code or "",
                    source_language=sf.language.value if sf.language else "unknown",
                    target_language=target.value,
                    conversion_status=result.status.value if result.status else "unknown",
                    confidence=result.confidence,
                    detected_component_type=sf.pattern.value if sf.pattern else None,
                    package_path=self._determine_package_path(sf) if target == TargetLanguage.JAVA_SPRING else None,
                    class_name=Path(sf.path).stem,
                    errors=[result.review_notes] if result.review_notes else [],
                    conversion_time_seconds=elapsed
                )

            # Write output immediately (streaming) using Maven structure
            if result.converted_code:
                try:
                    self._write_file_output(result, output_dir, target)
                    log.info(f"  ✓ Written output for {sf.path}")
                except Exception as e:
                    log.error(f"  ✗ Failed to write output for {sf.path}: {e}")

            yield result

        # Update manifest stats at end
        manifest.stats["conversion"] = self._stats.copy()
        manifest.stats["llm"] = self.llm_converter.stats()
        
        # Attach migration document to manifest for later stages
        manifest.migration_doc = self.migration_doc
        
        # End migration document session
        if self.migration_doc:
            self.migration_doc.end_session(
                status=MigrationStatus.COMPLETED if self._stats.get("failed", 0) == 0 else MigrationStatus.NEEDS_REVIEW,
                summary_stats=self._stats.copy()
            )

    def _convert_file(self, sf: SourceFile, target: TargetLanguage) -> ConversionResult:
        """Convert a single file using appropriate strategy."""
        result: ConversionResult

        if sf.complexity_tier == ComplexityTier.GREEN and self._rule_first:
            # Rule engine only
            result = self.rule_engine.convert(sf, target)
            if result.confidence >= self._threshold:
                log.debug("  Rule engine sufficient (conf=%.2f)", result.confidence)
                return result

        if sf.complexity_tier == ComplexityTier.AMBER:
            # Rule engine first, LLM refines if confidence low
            result = self.rule_engine.convert(sf, target)
            if result.confidence < self._threshold:
                log.debug("  Rule engine insufficient, escalating to LLM")
                result = self.llm_converter.convert(sf, target, prior_result=result)
            return result

        # RED tier or XAML — full LLM
        result = self.llm_converter.convert(sf, target)

        # Flag for human review if still low confidence
        if result.confidence < self._threshold:
            result.status = ConversionStatus.NEEDS_REVIEW
            log.warning("  Low confidence (%.2f) — flagged for review: %s", result.confidence, sf.path)

        return result

    def _write_file_output(
        self,
        result: ConversionResult,
        output_dir: Path,
        target: TargetLanguage,
    ) -> None:
        """Write a single converted file to output directory."""
        source_file = result.source_file
        if not source_file:
            return

        from output.file_splitter import FileSplitter, should_split_file
        
        # Check if content needs intelligent splitting (multiple classes)
        if target == TargetLanguage.JAVA_SPRING and should_split_file(result.converted_code, 'java'):
            log.info("  Detected multi-class content, intelligently splitting...")
            
            # Determine base package path from source file
            base_path = self._determine_package_path(source_file)
            
            splitter = FileSplitter()
            segments = splitter.intelligent_split(
                result.converted_code,
                base_path=base_path,
                language='java'
            )
            
            if segments:
                written = splitter.write_segments(output_dir / "src" / "main" / "java", segments, base_package=self.base_package)
                log.info("  Split into %d files: %s", len(written), 
                        [p.name for p in written])
                return
        
        # Default: write as single file
        relative_path = Path(source_file.path)
        
        # Map extension based on target language
        if target == TargetLanguage.JAVA_SPRING:
            output_path = output_dir / "src" / "main" / "java" / relative_path.with_suffix('.java')
        elif target == TargetLanguage.REACT_JS:
            output_path = output_dir / "src" / relative_path.with_suffix('.tsx')
        else:
            output_path = output_dir / relative_path

        # Create directories
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        output_path.write_text(result.converted_code, encoding='utf-8')
    
    def _determine_package_path(self, source_file: SourceFile) -> str:
        """
        Determine Java package path from source file.
        Creates consistent domain-based structure: com.macys.<domain>
        
        Examples:
            UserController.cs -> com/macys/user
            UserManagementService.cs -> com/macys/usermanagement
            OrderService.cs -> com/macys/order
        """
        import re
        src_path = Path(source_file.path)
        stem = src_path.stem
        
        # Extract domain from class name by removing type suffixes
        # UserController -> user, UserManagementService -> usermanagement
        type_suffixes = [
            'Controller', 'Service', 'Repository', 'Repo', 'Dao', 'Impl',
            'Entity', 'Model', 'Dto', 'DTO', 'Request', 'Response',
            'Validator', 'Config', 'Configuration', 'Util', 'Helper',
            'Exception', 'Handler', 'Mapper', 'Factory', 'Host'
        ]
        
        domain = stem
        for suffix in type_suffixes:
            if domain.endswith(suffix):
                domain = domain[:-len(suffix)]
                break
        
        # Convert to lowercase package name
        # Handle camelCase by inserting underscores, then convert
        domain = re.sub(r'([a-z])([A-Z])', r'\1\2', domain).lower()
        
        # Clean up - remove any non-alphanumeric
        domain = re.sub(r'[^a-z0-9]', '', domain)
        
        # Smart domain consolidation - normalize common variations
        # This works generically for any domain without hardcoding specific names
        domain = self._normalize_domain(domain)
        
        # Additional type suffix removal for common Java patterns
        type_suffixes = ['service', 'controller', 'repository', 'repo', 'dao', 'impl',
                        'entity', 'model', 'dto', 'request', 'response', 'validator',
                        'config', 'util', 'helper', 'exception', 'handler', 'mapper',
                        'factory', 'host', 'process', 'processing', 'management']
        
        for suffix in type_suffixes:
            if domain.endswith(suffix) and len(domain) > len(suffix):
                domain = domain[:-len(suffix)]
                break
        
        # Final plural normalization
        if domain.endswith('s') and len(domain) > 1:
            domain = domain[:-1]
        
        # Ensure we have a valid domain name
        if not domain or len(domain) < 2:
            domain = "app"
        
        return f"{self.base_package}/{domain}"

    def _normalize_domain(self, domain: str) -> str:
        """
        Smart domain consolidation - normalize common variations.
        Works generically for any domain without hardcoding.
        
        Examples:
        - users -> user (plural normalization)
        - userservice -> user (type suffix removal)
        - usercontroller -> user (type suffix removal)
        """
        import re
        
        # Common suffixes that indicate type (not part of domain)
        type_suffixes = ['service', 'controller', 'repository', 'repo', 'dao', 'impl',
                        'entity', 'model', 'dto', 'request', 'response', 'validator',
                        'config', 'util', 'helper', 'exception', 'handler', 'mapper',
                        'factory', 'host', 'process', 'processing', 'management', 'api']
        
        domain = domain.lower()
        
        # Remove type suffixes
        for suffix in type_suffixes:
            if domain.endswith(suffix) and len(domain) > len(suffix) + 1:
                domain = domain[:-len(suffix)]
                break
        
        # Normalize plural (remove trailing s if present)
        if domain.endswith('s') and len(domain) > 1:
            domain = domain[:-1]
        
        # Clean up any remaining non-alphanumeric
        domain = re.sub(r'[^a-z0-9]', '', domain)
        
        return domain

    def get_stats(self) -> dict:
        """Get current conversion stats."""
        return self._stats.copy()
    
    def print_final_stats(self) -> None:
        """Print final migration statistics including token usage."""
        stats = self._stats
        log.info("=" * 60)
        log.info("MIGRATION COMPLETE - FINAL STATISTICS")
        log.info("=" * 60)
        log.info(f"Total files in manifest:     {stats.get('total_files', 0)}")
        log.info(f"Files skipped (non-convertible): {stats.get('total_skipped', 0)}")
        log.info(f"Files processed:             {stats.get('processed', 0)}")
        log.info(f"Successful conversions:      {stats.get('successful', 0)}")
        log.info(f"Failed conversions:          {stats.get('failed', 0)}")
        log.info(f"LLM API calls made:          {stats.get('llm_calls', 0)}")
        log.info(f"Total tokens used:           {stats.get('total_tokens', 0):,}")
        log.info("=" * 60)
        
        # Also write to a stats file
        if hasattr(self, 'migration_doc') and self.migration_doc:
            stats_path = Path(self.migration_doc.output_dir) / "MIGRATION_STATS.json"
            import json
            with open(stats_path, 'w') as f:
                json.dump(stats, f, indent=2)
            log.info(f"Statistics saved to: {stats_path}")
