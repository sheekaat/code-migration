"""
Accuracy Engine — Self-Healing Accuracy Loop
Main orchestrator: score → analyse → remediate → re-score → repeat.

If accuracy < 85%:
  1. Analyse which dimensions failed
  2. Apply cheapest fix first (structural > syntax > rule > llm_patch > llm_retry)
  3. Re-score
  4. Repeat up to max_iterations
  5. If still < 85% → flag for human review + persist failure pattern
  6. Update knowledge base with any new learned rules
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import time

from shared.models import (
    ConversionResult, ConversionStatus, WorkspaceManifest,
)
from shared.config import get_logger
from accuracy.scorer import AccuracyEngine, AccuracyReport, ACCURACY_THRESHOLD
from accuracy.analyser import FailureAnalyser, RemediationStrategy
from accuracy.enhanced_remediation import EnhancedRemediationExecutor, apply_extended_structural_fix
from accuracy.knowledge_base import KnowledgeBase

log = get_logger(__name__)

MAX_ITERATIONS = 3


@dataclass
class LoopResult:
    """Full history of all iterations for a single file."""
    file_path: str
    iterations: list[AccuracyReport] = field(default_factory=list)
    final_score: float = 0.0
    passed: bool = False
    total_remediation_tokens: int = 0
    strategies_used: list[str] = field(default_factory=list)
    escalated_to_human: bool = False

    def delta(self) -> float:
        """Score improvement from first to last iteration."""
        if len(self.iterations) < 2:
            return 0.0
        return self.iterations[-1].overall_score - self.iterations[0].overall_score


class SelfHealingAccuracyLoop:
    """
    Runs up to MAX_ITERATIONS of score → analyse → remediate
    until accuracy >= 85% or iterations exhausted.
    Uses EnhancedRemediationExecutor with per-dimension targeting.
    """

    def __init__(self, config: dict, knowledge_base: Optional[KnowledgeBase] = None):
        self.config      = config
        self.scorer      = AccuracyEngine()
        self.analyser    = FailureAnalyser()
        self.remediator  = EnhancedRemediationExecutor(config)
        self.kb          = knowledge_base or KnowledgeBase.load()

    def run(self, result: ConversionResult) -> LoopResult:
        sf       = result.source_file
        path     = sf.path if sf else "unknown"
        target   = result.target_language
        source   = sf.raw_content if sf else ""

        loop = LoopResult(file_path=path)
        start = time.time()

        # ── Pre-pass: apply learned rules from knowledge base ─────────────
        if self.kb.rules and sf and target:
            patched, kb_rules = self.kb.apply_learned_rules(
                result.converted_code or "", sf.language, target
            )
            if kb_rules:
                log.info("  KB pre-pass: applied %d learned rules", len(kb_rules))
                result.converted_code = patched
                result.rules_applied  = list(result.rules_applied or []) + kb_rules

        # ── Extended structural pre-pass ──────────────────────────────────
        if target and result.converted_code:
            patched, structural_fixes = apply_extended_structural_fix(
                result.converted_code, target, None
            )
            if structural_fixes:
                log.info("  Structural pre-pass: applied %d fixes", len(structural_fixes))
                result.converted_code = patched
                result.rules_applied = list(result.rules_applied or []) + structural_fixes

        for iteration in range(1, MAX_ITERATIONS + 1):
            log.info("  [Accuracy Loop] %s — iteration %d/%d", path, iteration, MAX_ITERATIONS)

            # ── Score ──────────────────────────────────────────────────────
            report = self.scorer.score(result, iteration=iteration)
            loop.iterations.append(report)

            if report.passed:
                log.info("  PASSED at iteration %d (%.1f%%)", iteration, report.overall_score)
                break

            if iteration == MAX_ITERATIONS:
                log.warning(
                    "  EXHAUSTED iterations — final score %.1f%% (threshold %.0f%%)",
                    report.overall_score, ACCURACY_THRESHOLD,
                )
                break

            # ── Analyse ────────────────────────────────────────────────────
            analysis = self.analyser.analyse(report)

            if not analysis.failures:
                log.info("  No specific failures identified — attempting full LLM retry")

            # ── Remediate ──────────────────────────────────────────────────
            result = self.remediator.remediate(result, analysis, iteration)
            strategies = analysis.strategies_needed()
            loop.strategies_used.extend(s.value for s in strategies)

            if RemediationStrategy.HUMAN_REVIEW in strategies:
                loop.escalated_to_human = True

            # Record correction in knowledge base
            for failure in analysis.failures:
                self.kb.record_correction(
                    file_path=path,
                    issue=failure.description,
                    before_score=report.overall_score,
                    after_score=0.0,   # will update after re-score
                    strategy=failure.strategy.value,
                )

        # ── Final state ────────────────────────────────────────────────────
        final_report = loop.iterations[-1]
        loop.final_score = final_report.overall_score
        loop.passed      = final_report.passed

        if not loop.passed:
            result.status = ConversionStatus.NEEDS_REVIEW
            result.review_notes = (
                f"Self-healing loop exhausted ({MAX_ITERATIONS} iterations). "
                f"Final score: {loop.final_score:.1f}%. "
                f"Issues: {'; '.join(final_report.all_issues[:3])}"
            )

        # ── Update knowledge base ──────────────────────────────────────────
        if loop.delta() > 5:
            log.info(
                "  Score improved +%.1f%% — persisting strategies to KB",
                loop.delta(),
            )
        self.kb.save()

        elapsed = time.time() - start
        log.info(
            "  Loop done in %.1fs. Score: %.1f%% → %.1f%% (%s). Strategies: %s",
            elapsed,
            loop.iterations[0].overall_score if loop.iterations else 0,
            loop.final_score,
            "PASS" if loop.passed else "FAIL",
            list(set(loop.strategies_used)),
        )
        return loop

    def run_for_manifest(self, manifest: WorkspaceManifest) -> dict:
        """Run the accuracy loop for every conversion result in a manifest."""
        log.info("Running self-healing accuracy loop on %d files", len(manifest.conversion_results))
        all_loops: list[LoopResult] = []
        passed = 0
        escalated = 0

        for result in manifest.conversion_results:
            if not result.converted_code:
                continue
            loop = self.run(result)
            all_loops.append(loop)
            if loop.passed:
                passed += 1
            if loop.escalated_to_human:
                escalated += 1

        total = len(all_loops)
        avg_score = sum(l.final_score for l in all_loops) / max(total, 1)
        avg_delta = sum(l.delta() for l in all_loops) / max(total, 1)

        stats = {
            "total":         total,
            "passed":        passed,
            "pass_rate":     f"{100*passed//max(total,1)}%",
            "avg_score":     f"{avg_score:.1f}%",
            "avg_improvement": f"+{avg_delta:.1f}%",
            "escalated_to_human": escalated,
            "kb_rules": self.kb.stats()["total_rules"],
        }
        manifest.stats["accuracy"] = stats
        log.info("Accuracy loop complete: %s", stats)
        return stats


# ─── Convenience wrapper ──────────────────────────────────────────────────────

def run_accuracy_loop(
    manifest: WorkspaceManifest,
    config: dict,
    kb: Optional[KnowledgeBase] = None,
) -> WorkspaceManifest:
    """
    Drop-in function to run the full self-healing loop on a manifest.
    Called from the orchestration pipeline between conversion and output.
    """
    loop = SelfHealingAccuracyLoop(config, knowledge_base=kb)
    loop.run_for_manifest(manifest)
    return manifest
