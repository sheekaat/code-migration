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

        total_files = len(order)
        log.info(f"Streaming conversion: {total_files} files to process")
        
        # Initialize migration document for tracking
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

            # Write output immediately (streaming)
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
                written = splitter.write_segments(output_dir / "src", segments)
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
        Uses source directory structure + component type heuristics.
        """
        src_path = Path(source_file.path)
        stem = src_path.stem.lower()
        
        # Map of source path keywords to package components
        path_keywords = {
            'controller': 'controller',
            'controllers': 'controller',
            'ctrl': 'controller',
            'service': 'service',
            'services': 'service',
            'svc': 'service',
            'business': 'service',
            'entity': 'entity',
            'entities': 'entity',
            'model': 'entity',
            'models': 'entity',
            'domain': 'entity',
            'repository': 'repository',
            'repositories': 'repository',
            'repo': 'repository',
            'dao': 'repository',
            'data': 'repository',
            'dto': 'dto',
            'dtos': 'dto',
            'viewmodel': 'dto',
            'util': 'util',
            'utils': 'util',
            'helper': 'util',
            'helpers': 'util',
            'common': 'common',
            'config': 'config',
            'configuration': 'config',
        }
        
        # Check for component type from file type registry
        detected_type = getattr(source_file, 'detected_component_type', None)
        type_package_map = {
            'CONTROLLER': 'controller',
            'SERVICE': 'service',
            'ENTITY': 'entity',
            'REPOSITORY': 'repository',
            'DATA_ACCESS': 'repository',
            'CLASS': 'util',
            'MODULE': 'util',
        }
        
        if detected_type and detected_type in type_package_map:
            return f"com/macys/{type_package_map[detected_type]}"
        
        # Check each path component against keywords
        for part in src_path.parts:
            part_lower = part.lower()
            if part_lower in path_keywords:
                return f"com/macys/{path_keywords[part_lower]}"
        
        # Check filename stem for keywords
        for keyword, pkg in path_keywords.items():
            if keyword in stem:
                return f"com/macys/{pkg}"
        
        # Default based on file extension/type
        if stem.endswith('controller'):
            return "com/macys/controller"
        elif stem.endswith('service') or stem.endswith('svc'):
            return "com/macys/service"
        elif stem.endswith('repository') or stem.endswith('repo') or stem.endswith('dao'):
            return "com/macys/repository"
        
        # Final fallback - use directory name if meaningful
        parent = src_path.parent.name.lower()
        if parent in path_keywords:
            return f"com/macys/{path_keywords[parent]}"
        
        return "com/macys/app"

    def get_stats(self) -> dict:
        """Get current conversion stats."""
        return self._stats.copy()
