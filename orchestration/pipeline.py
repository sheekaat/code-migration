"""
Orchestration Pipeline
Ties all 6 layers together into a single end-to-end workflow.
Can be run directly or imported and used programmatically.
"""

from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from typing import List, Optional

from shared.config import load_config, get_logger
from shared.models import TargetLanguage, WorkspaceManifest
from ingestion.crawler import RepoCrawler
from analysis.engine import analyse
from conversion.pipeline import ConversionPipeline
from validation.runner import ValidationRunner
from output.generator import OutputGenerator

log = get_logger("orchestration")


class MigrationOrchestrator:
    """
    End-to-end migration pipeline.

    Usage:
        orchestrator = MigrationOrchestrator(config)
        output_dir = orchestrator.run("/path/to/legacy/repo")
    """

    def __init__(self, config: dict):
        self.config = config

    def run(
        self,
        repo_path: str,
        target_language: TargetLanguage | None = None,
        skip_patterns: Optional[List[str]] = None,
    ) -> str:
        start = time.time()
        log.info("=" * 60)
        log.info("Migration started for: %s", repo_path)
        if skip_patterns:
            log.info("Skip patterns: %s", skip_patterns)
        log.info("=" * 60)

        # ── Layer 1: Ingestion ────────────────────────────────────────────
        log.info("[1/6] Ingesting repository...")
        crawler = RepoCrawler(repo_path, target_language=target_language, skip_patterns=skip_patterns)
        manifest: WorkspaceManifest = crawler.crawl()
        _checkpoint(manifest, "ingestion")

        # ── Layer 2: Analysis ────────────────────────────────────────────
        log.info("[2/6] Running analysis engine...")
        manifest = analyse(manifest, self.config)
        _checkpoint(manifest, "analysis")

        # ── Layer 3: Conversion ───────────────────────────────────────────
        log.info("[3/6] Running conversion pipeline...")
        pipeline = ConversionPipeline(self.config)
        manifest = pipeline.convert_manifest(manifest)
        _checkpoint(manifest, "conversion")

        # ── Layer 4: Validation ───────────────────────────────────────────
        log.info("[4/6] Running automated validation...")
        validator = ValidationRunner(self.config)
        reports = validator.validate_manifest(manifest)
        _checkpoint(manifest, "validation")

        # ── Layer 5: Flag for review (handled by Review UI) ───────────────
        needs_review = [
            r for r in manifest.conversion_results
            if not r.validation_passed
        ]
        log.info("[5/6] %d file(s) flagged for human review", len(needs_review))

        # ── Layer 6: Output ───────────────────────────────────────────────
        log.info("[6/6] Generating output...")
        generator = OutputGenerator(self.config)
        output_dir = generator.generate(manifest, reports)

        elapsed = time.time() - start
        self._print_summary(manifest, reports, output_dir, elapsed)
        return output_dir

    def _print_summary(self, manifest, reports, output_dir, elapsed):
        total     = len(manifest.conversion_results)
        validated = sum(1 for r in manifest.conversion_results if r.validation_passed)
        review    = sum(1 for r in manifest.conversion_results if not r.validation_passed)

        log.info("")
        log.info("=" * 60)
        log.info("MIGRATION COMPLETE in %.1fs", elapsed)
        log.info("  Total files converted : %d", total)
        log.info("  Validated             : %d (%.0f%%)", validated, 100*validated/max(total,1))
        log.info("  Needs review          : %d", review)
        if "llm" in manifest.stats:
            llm = manifest.stats["llm"]
            log.info("  Tokens used           : %s", f"{llm.get('total_tokens_used', 0):,}")
            log.info("  Cache hit rate        : %s", llm.get("cache_hit_rate", "0%"))
        log.info("  Output directory      : %s", output_dir)
        log.info("=" * 60)


def _checkpoint(manifest: WorkspaceManifest, stage: str) -> None:
    """Save workspace stats after each stage (for debugging / resume)."""
    log.info("  → %s stats: %s", stage, json.dumps(manifest.stats.get(stage, {})))


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated legacy code migration platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m orchestration.pipeline --repo /path/to/csharp-project
  python -m orchestration.pipeline --repo /path/to/vb6-project --target react_js
  python -m orchestration.pipeline --repo /path/to/tibco-bw --config custom.yaml
        """,
    )
    parser.add_argument("--repo",   required=True, help="Path to legacy repository")
    parser.add_argument("--target", choices=[t.value for t in TargetLanguage],
                        help="Override target language detection")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--output", help="Override output directory")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.output:
        config.setdefault("output", {})["base_dir"] = args.output

    target = TargetLanguage(args.target) if args.target else None
    orchestrator = MigrationOrchestrator(config)
    orchestrator.run(args.repo, target_language=target)


if __name__ == "__main__":
    main()

# ─── Accuracy-loop-enhanced entrypoint ───────────────────────────────────────

def run_with_accuracy_loop(
    repo_path: str,
    config_path: str = "config.yaml",
    target_language=None,
) -> str:
    """
    Full pipeline with self-healing accuracy loop.
    Drop-in replacement for MigrationOrchestrator.run().
    """
    from shared.config import load_config
    from ingestion.crawler import RepoCrawler
    from analysis.engine import analyse
    from conversion.pipeline import ConversionPipeline
    from validation.runner import ValidationRunner
    from accuracy.loop import run_accuracy_loop
    from accuracy.knowledge_base import KnowledgeBase
    from output.generator import OutputGenerator

    cfg = load_config(config_path)
    kb  = KnowledgeBase.load()

    manifest = RepoCrawler(repo_path, target_language=target_language).crawl()
    manifest = analyse(manifest, cfg)
    manifest = ConversionPipeline(cfg).convert_manifest(manifest)
    manifest = run_accuracy_loop(manifest, cfg, kb=kb)       # <-- accuracy loop
    reports  = ValidationRunner(cfg).validate_manifest(manifest)
    output_dir = OutputGenerator(cfg).generate(manifest, reports)

    acc = manifest.stats.get("accuracy", {})
    log.info("Accuracy: %s pass rate, avg score %s", acc.get("pass_rate"), acc.get("avg_score"))
    return output_dir
