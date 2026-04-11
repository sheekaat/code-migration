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
        self.llm_converter = LLMConverter(config)
        self.output_generator = OutputGenerator(config)
        self._threshold = config.get("conversion", {}).get("confidence_threshold", 0.75)
        self._stats = {"green": 0, "amber": 0, "red": 0, "total_tokens": 0, "processed": 0}
        self.base_package = config.get("java", {}).get("base_package", "com.macys").replace(".", "/")
        self.service_name: Optional[str] = None  # Auto-detected from source files
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
        
        # Store output_dir and manifest for use in other methods
        self._output_dir = output_dir
        self._manifest = manifest
        
        # Use dependency graph for leaf-first processing
        if manifest.dependency_graph:
            order = manifest.dependency_graph.topological_order()
            log.info(f"Using dependency-based ordering: {len(order)} files in dependency order (leaves first)")
            
            # Log first few files to show leaf-first ordering
            if order:
                sample = order[:5]
                deps_info = []
                for path in sample:
                    deps = manifest.dependency_graph.edges.get(path, []) if manifest.dependency_graph else []
                    dep_count = len(deps)
                    deps_info.append(f"{Path(path).name}({dep_count} deps)")
                log.info(f"  First files (leaves have 0 deps): {', '.join(deps_info)}")
        else:
            order = [f.path for f in manifest.files]
            log.info(f"No dependency graph, using file order: {len(order)} files")

        # Filter out non-convertible files while preserving dependency order
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
        log.info(f"Streaming conversion: {total_files} files to process in dependency order (leaves first)")
        
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

            # Check dependencies for this file
            deps = manifest.dependency_graph.edges.get(path, []) if manifest.dependency_graph else []
            dep_names = [Path(d).name for d in deps[:3]]  # Show first 3 deps
            dep_info = f" (depends on: {', '.join(dep_names)}" + (f" +{len(deps)-3} more)" if len(deps) > 3 else ")") if deps else ""

            # Check if file was already converted in previous run
            if path in resumed_files:
                record = resumed_files[path]
                log.info(f"[{idx}/{total_files}] RESUMING {sf.path}{dep_info} - using cached conversion")
                
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
                            # Single file - write directly using proper Maven structure
                            base_path = self._determine_package_path(sf)
                            # Use original filename stem - preserve interface prefixes like "I"
                            class_name = Path(sf.path).stem
                            output_path = output_dir / "src" / "main" / "java" / Path(base_path) / f"{class_name}.java"
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

            log.info(f"[{idx}/{total_files}] Converting {sf.path}{dep_info} (tier: {sf.complexity_tier.value})")
            
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
                    target_language=target,
                    status=ConversionStatus.FAILED,
                    converted_code="",
                    confidence=0.0,
                    review_notes=str(e)
                )
            
            # Update stats
            self._stats[sf.complexity_tier.value] += 1
            self._stats["total_tokens"] += result.total_tokens
            self._stats["processed"] = idx
            
            # ── Inline accuracy check for stubs ──────────────────────────────
            if result.converted_code and target == TargetLanguage.JAVA_SPRING:
                from accuracy.scorer import BehavioralScorer
                import re
                
                scorer = BehavioralScorer()
                score_report = scorer.score(sf.raw_content, result.converted_code, target)
                
                # Debug: Count methods
                source_methods = len(re.findall(r'(public|private|protected)\s+\w+\s+\w+\s*\([^)]*\)\s*\{', sf.raw_content))
                converted_methods = len(re.findall(r'(public|private|protected)\s+\w+\s+\w+\s*\([^)]*\)\s*\{', result.converted_code))
                
                log.info(f"  [Accuracy Check] Methods: {converted_methods}/{source_methods}, Score: {score_report.score:.1f}%")
                if score_report.issues:
                    log.info(f"     Issues found: {score_report.issues}")
                
                if score_report.score < 85 or converted_methods < source_methods:  # Aggressive check
                    log.warning(f"  ⚠ DETECTED ISSUES - Retrying with anti-stub prompt...")
                    
                    # Build issues list including method count
                    all_issues = score_report.issues or []
                    if converted_methods < source_methods:
                        all_issues.append(f"Missing {source_methods - converted_methods} method(s)")
                    
                    # Retry with explicit anti-stub instructions
                    retry_result = self.llm_converter.convert_with_prompt(
                        sf, target, 
                        anti_stub=True,
                        failure_issues=all_issues
                    )
                    
                    if retry_result and retry_result.converted_code:
                        # Check if retry is better
                        retry_score = scorer.score(sf.raw_content, retry_result.converted_code, target)
                        retry_methods = len(re.findall(r'(public|private|protected)\s+\w+\s+\w+\s*\([^)]*\)\s*\{', retry_result.converted_code))
                        
                        log.info(f"  [Retry] Methods: {retry_methods}/{source_methods}, Score: {retry_score.score:.1f}%")
                        
                        if retry_score.score > score_report.score or retry_methods > converted_methods:
                            log.info(f"  ✓ Retry IMPROVED: score {score_report.score:.1f}→{retry_score.score:.1f}, methods {converted_methods}→{retry_methods}")
                            result = retry_result
                            result.confidence = retry_score.score / 100.0
                        else:
                            log.warning(f"  ✗ Retry did not improve, keeping best result")
            
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
        """Convert a single file using method-based LLM for all files."""
        from conversion.method_based_converter import (
            MethodBasedConverter, MethodExtractor,
            _init_llm_log, _log_dependency_graph
        )
        from shared.models import ConversionStatus
        
        # Initialize LLM logging once per session
        if not hasattr(self, '_llm_log_initialized'):
            _init_llm_log(self._output_dir)
            _log_dependency_graph(self._manifest)
            self._llm_log_initialized = True
        
        # Use method-based conversion for all files
        method_converter = MethodBasedConverter(self.llm_converter)
        
        # Debug: Extract and log methods found
        extractor = MethodExtractor()
        methods = extractor.extract_methods(sf.raw_content)
        log.info(f"  [DEBUG] Found {len(methods)} methods in {sf.path}")
        for m in methods:
            log.info(f"    - {m.name}: {m.end_line - m.start_line} lines")
        
        result = method_converter.convert_file(sf, target, output_dir=str(self._output_dir))
        
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
            # Use determined package path for correct Java structure
            base_path = self._determine_package_path(source_file)
            
            # Extract class name from converted code or use source filename
            # Remove 'I' prefix from interfaces (Java convention)
            class_name = Path(source_file.path).stem
            if class_name.startswith('I') and len(class_name) > 1:
                # Check if it's an interface by looking at converted code
                if 'interface' in result.converted_code[:500] or 'public interface' in result.converted_code:
                    class_name = class_name[1:]  # Remove I prefix
            
            output_path = output_dir / "src" / "main" / "java" / Path(base_path) / f"{class_name}.java"
        elif target == TargetLanguage.REACT_JS:
            output_path = output_dir / "src" / relative_path.with_suffix('.tsx')
        else:
            output_path = output_dir / relative_path
        
        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        output_path.write_text(result.converted_code, encoding='utf-8')
    
    def _determine_package_path(self, source_file: SourceFile) -> str:
        """
        Determine Java base package path - CONSOLIDATED single domain approach.
        
        All files go into: com.macys.mst.<domain>.<type>.<subdomain>
        Example: com.macys.mst.order.service.externalapi
        
        Domain is extracted once from input folder (e.g., LegacyOrderService -> order).
        Type is based on class type (service, repository, helper, etc).
        Subdomain is the service name extracted from class name.
        """
        import re
        src_path = Path(source_file.path)
        stem = src_path.stem
        
        # Extract domain once from input folder structure
        domain = self._extract_domain_from_input(src_path)
        
        # Extract service name from class name by removing type suffixes
        type_suffixes = [
            'Controller', 'Service', 'Repository', 'Repo', 'Dao', 'Impl',
            'Entity', 'Model', 'Dto', 'DTO', 'Request', 'Response',
            'Validator', 'Config', 'Configuration', 'Util', 'Helper',
            'Exception', 'Handler', 'Mapper', 'Factory', 'Host', 'Processing'
        ]
        
        subdomain = stem
        for suffix in type_suffixes:
            if subdomain.endswith(suffix):
                subdomain = subdomain[:-len(suffix)]
                break
        subdomain = re.sub(r'([a-z])([A-Z])', r'\1\2', subdomain).lower()
        subdomain = re.sub(r'[^a-z0-9]', '', subdomain)
        
        # Determine type folder based on filename
        if 'repository' in stem.lower():
            type_folder = "repository"
        elif 'service' in stem.lower():
            type_folder = "service"
        elif 'helper' in stem.lower():
            type_folder = "helper"
        elif 'util' in stem.lower():
            type_folder = "util"
        elif 'controller' in stem.lower():
            type_folder = "controller"
        else:
            type_folder = "model"
        
        # Return consolidated path: com/macys/mst/<domain>/<type>/<subdomain>
        return f"com/macys/mst/{domain}/{type_folder}/{subdomain}"
    
    def _extract_domain_from_input(self, src_path: Path) -> str:
        """Extract single consolidated domain from input folder structure."""
        # Common suffixes/prefixes to remove
        suffixes = ['service', 'core', 'legacy', 'host', 'api', 'web', 'app', 'system', 'platform']
        prefixes = ['legacy', 'core']
        
        domain = "shared"  # Default
        
        for part in src_path.parts:
            part_lower = part.lower()
            # Skip non-domain folders
            if part_lower in ('input', 'output', 'src', 'main', 'java', 'com', 'macys', 'mst',
                            'conversion', 'models', 'repositories', 'services', 'controllers',
                            'helpers', 'interfaces', 'bin', 'obj', 'properties'):
                continue
            
            # Clean the part
            cleaned = part_lower
            for prefix in prefixes:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):]
            for suffix in suffixes:
                if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
                    cleaned = cleaned[:-len(suffix)]
            
            if cleaned and len(cleaned) > 2:
                domain = cleaned
                break
        
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
