"""
Conversion Pipeline
Orchestrates rule engine → LLM converter routing based on complexity tier.
"""

from __future__ import annotations

from shared.models import (
    WorkspaceManifest, SourceFile, ConversionResult,
    ConversionStatus, ComplexityTier, TargetLanguage,
)
from shared.config import get_logger, load_config
from conversion.rule_engine.engine import RuleEngine
from conversion.llm_converter.converter import LLMConverter
from ingestion.file_type_registry import detect_file_type, ComponentType
from conversion.component_templates import get_conversion_template

log = get_logger(__name__)


class ConversionPipeline:
    def __init__(self, config: dict):
        self.config = config
        self.rule_engine  = RuleEngine(config)
        self.llm_converter = LLMConverter(config)
        self._threshold = config.get("conversion", {}).get("confidence_threshold", 0.75)
        self._rule_first  = config.get("conversion", {}).get("rule_engine_first", True)

    def convert_manifest(self, manifest: WorkspaceManifest) -> WorkspaceManifest:
        if not manifest.target_language:
            raise ValueError("WorkspaceManifest has no target_language set")

        target = manifest.target_language
        order = manifest.dependency_graph.topological_order() if manifest.dependency_graph else [
            f.path for f in manifest.files
        ]

        results: list[ConversionResult] = []
        stats = {"green": 0, "amber": 0, "red": 0, "total_tokens": 0}

        for path in order:
            sf = manifest.get_file_by_path(path)
            if not sf:
                continue
            result = self._convert_file(sf, target)
            results.append(result)
            stats[sf.complexity_tier.value] += 1
            stats["total_tokens"] += result.total_tokens

        manifest.conversion_results = results
        manifest.stats["conversion"] = stats
        manifest.stats["llm"] = self.llm_converter.stats()

        approved = sum(1 for r in results if r.confidence >= self._threshold)
        log.info(
            "Conversion complete. %d/%d files above confidence threshold.",
            approved, len(results),
        )
        return manifest

    def _convert_file(self, sf: SourceFile, target: TargetLanguage) -> ConversionResult:
        log.info(
            "Converting %s [%s / %s]",
            sf.path, sf.complexity_tier.value, sf.pattern.value,
        )

        result: ConversionResult

        # Detect file type and get component-specific template
        file_type_info = detect_file_type(sf.path, sf.raw_content)
        primary_component = file_type_info.components[0] if file_type_info.components else None
        
        if primary_component:
            log.info("  Detected: %s -> %s (conf=%.2f)",
                primary_component.type.name,
                primary_component.suggested_target_type,
                primary_component.conversion_confidence
            )

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
                result = self.llm_converter.convert(sf, target, prior_result=result, 
                                                     component_info=primary_component)
            return result

        # RED tier or XAML — full LLM with component template
        result = self.llm_converter.convert(sf, target, component_info=primary_component)

        # Flag for human review if still low confidence
        if result.confidence < self._threshold:
            result.status = ConversionStatus.NEEDS_REVIEW
            log.warning("  Low confidence (%.2f) — flagged for review: %s", result.confidence, sf.path)

        return result


if __name__ == "__main__":
    import argparse, json, pickle, os
    from ingestion.crawler import RepoCrawler
    from analysis.engine import analyse

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    manifest = RepoCrawler(args.repo).crawl()
    manifest = analyse(manifest, cfg)
    pipeline = ConversionPipeline(cfg)
    manifest = pipeline.convert_manifest(manifest)

    print(json.dumps({
        "files_converted": len(manifest.conversion_results),
        "stats": manifest.stats,
    }, indent=2))
