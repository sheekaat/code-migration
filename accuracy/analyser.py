"""
Accuracy Engine — Failure Analysis & Remediation Router
Classifies why a conversion failed and routes each failure
to the correct repair strategy.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from shared.config import get_logger
from accuracy.scorer import AccuracyReport, Dimension

log = get_logger(__name__)


# ─── Failure categories ───────────────────────────────────────────────────────

class FailureCategory(str, Enum):
    MISSING_ANNOTATION   = "missing_annotation"    # @RestController, @Service, etc.
    MISSING_TYPE_MAP     = "missing_type_map"       # string→String, bool→boolean
    UNTRANSLATED_PATTERN = "untranslated_pattern"   # LINQ, VB6 events, etc.
    STRUCTURAL_ISSUE     = "structural_issue"       # wrong package, no export
    ASYNC_MISMATCH       = "async_mismatch"         # async/await not converted
    STATE_NOT_MAPPED     = "state_not_mapped"       # globals not in useState
    INCOMPLETE_COVERAGE  = "incomplete_coverage"    # stubs remain
    BEHAVIORAL_GAP       = "behavioral_gap"         # null safety, tx handling
    SYNTAX_ERROR         = "syntax_error"           # parse/compile issue
    COMPLEX_LOGIC        = "complex_logic"          # too complex for rules


class RemediationStrategy(str, Enum):
    ADD_RULE         = "add_rule"          # extend rule engine with new pattern
    LLM_RETRY        = "llm_retry"         # re-send to LLM with targeted prompt
    LLM_PATCH        = "llm_patch"         # ask LLM to fix a specific section
    HUMAN_REVIEW     = "human_review"      # flag for manual intervention
    LEARN_RULE       = "learn_rule"        # persist correction as new rule
    STRUCTURAL_FIX   = "structural_fix"    # prepend package/import boilerplate
    SYNTAX_FIX       = "syntax_fix"        # auto-fix common syntax problems


@dataclass
class FailureDetail:
    category: FailureCategory
    strategy: RemediationStrategy
    dimension: Dimension
    description: str
    repair_hint: str = ""        # concrete instruction for the repair


@dataclass
class FailureAnalysis:
    report: AccuracyReport
    failures: list[FailureDetail] = field(default_factory=list)
    primary_strategy: RemediationStrategy = RemediationStrategy.LLM_RETRY

    def strategies_needed(self) -> list[RemediationStrategy]:
        seen: set[RemediationStrategy] = set()
        order: list[RemediationStrategy] = []
        for f in self.failures:
            if f.strategy not in seen:
                seen.add(f.strategy)
                order.append(f.strategy)
        return order


# ─── Issue classifiers ────────────────────────────────────────────────────────

_ANNOTATION_PATTERNS = [
    (re.compile(r"Missing @RestController"), FailureCategory.MISSING_ANNOTATION,
     "Add @RestController annotation to the class header."),
    (re.compile(r"Missing @Service|No Spring stereotype"), FailureCategory.MISSING_ANNOTATION,
     "Add appropriate Spring stereotype (@Service, @Repository, etc.)."),
    (re.compile(r"Missing React import"), FailureCategory.STRUCTURAL_ISSUE,
     "Prepend: import React, { useState, useEffect } from 'react';"),
    (re.compile(r"Missing default export"), FailureCategory.STRUCTURAL_ISSUE,
     "Append: export default <ComponentName>;"),
    (re.compile(r"Missing package declaration"), FailureCategory.STRUCTURAL_ISSUE,
     "Prepend: package com.company.app;"),
    (re.compile(r"not translated to.*GetMapping|not translated to.*PostMapping"), FailureCategory.MISSING_ANNOTATION,
     "Apply HTTP method annotation rule for this endpoint."),
    (re.compile(r"LINQ.*not translated|Select.*not translated|Where.*not translated"),
     FailureCategory.UNTRANSLATED_PATTERN,
     "Apply LINQ→Stream API translation rules."),
    (re.compile(r"VB6 event handlers not converted"), FailureCategory.UNTRANSLATED_PATTERN,
     "Convert _Click/_Change handlers to onClick/onChange."),
    (re.compile(r"Async.*not translated|async/await not"), FailureCategory.ASYNC_MISMATCH,
     "Wrap async logic in CompletableFuture or use @Async."),
    (re.compile(r"Global.*state not mapped|public.*state"), FailureCategory.STATE_NOT_MAPPED,
     "Map VB6 module-level variables to React useState hooks."),
    (re.compile(r"stub.*remain|AUTO-GENERATED STUB"), FailureCategory.INCOMPLETE_COVERAGE,
     "Replace stubs with actual LLM conversion pass."),
    (re.compile(r"Database access not converted"), FailureCategory.UNTRANSLATED_PATTERN,
     "Replace ADODB/Recordset calls with fetch() or axios API calls."),
    (re.compile(r"Unbalanced braces|unclosed string"), FailureCategory.SYNTAX_ERROR,
     "Fix syntax: check for missing closing braces or quotes."),
    (re.compile(r"Transaction.*missing"), FailureCategory.BEHAVIORAL_GAP,
     "Add @Transactional annotation to service methods that modify data."),
    (re.compile(r"Null-coalescing.*not translated"), FailureCategory.BEHAVIORAL_GAP,
     "Wrap nullable values in Optional<T> with .orElse() fallback."),
    (re.compile(r"Try/catch block missing"), FailureCategory.BEHAVIORAL_GAP,
     "Re-add error handling around translated logic."),
]

# Category → Strategy mapping
_CATEGORY_STRATEGY: dict[FailureCategory, RemediationStrategy] = {
    FailureCategory.MISSING_ANNOTATION:   RemediationStrategy.ADD_RULE,
    FailureCategory.MISSING_TYPE_MAP:     RemediationStrategy.ADD_RULE,
    FailureCategory.UNTRANSLATED_PATTERN: RemediationStrategy.LLM_PATCH,
    FailureCategory.STRUCTURAL_ISSUE:     RemediationStrategy.STRUCTURAL_FIX,
    FailureCategory.ASYNC_MISMATCH:       RemediationStrategy.LLM_PATCH,
    FailureCategory.STATE_NOT_MAPPED:     RemediationStrategy.LLM_PATCH,
    FailureCategory.INCOMPLETE_COVERAGE:  RemediationStrategy.LLM_RETRY,
    FailureCategory.BEHAVIORAL_GAP:       RemediationStrategy.LLM_PATCH,
    FailureCategory.SYNTAX_ERROR:         RemediationStrategy.SYNTAX_FIX,
    FailureCategory.COMPLEX_LOGIC:        RemediationStrategy.HUMAN_REVIEW,
}


def _dimension_from_category(cat: FailureCategory) -> Dimension:
    mapping = {
        FailureCategory.MISSING_ANNOTATION:   Dimension.STRUCTURAL,
        FailureCategory.MISSING_TYPE_MAP:     Dimension.SEMANTIC,
        FailureCategory.UNTRANSLATED_PATTERN: Dimension.SEMANTIC,
        FailureCategory.STRUCTURAL_ISSUE:     Dimension.STRUCTURAL,
        FailureCategory.ASYNC_MISMATCH:       Dimension.BEHAVIORAL,
        FailureCategory.STATE_NOT_MAPPED:     Dimension.BEHAVIORAL,
        FailureCategory.INCOMPLETE_COVERAGE:  Dimension.COVERAGE,
        FailureCategory.BEHAVIORAL_GAP:       Dimension.BEHAVIORAL,
        FailureCategory.SYNTAX_ERROR:         Dimension.SYNTAX,
        FailureCategory.COMPLEX_LOGIC:        Dimension.SEMANTIC,
    }
    return mapping.get(cat, Dimension.SEMANTIC)


# ─── Failure Analyser ─────────────────────────────────────────────────────────

class FailureAnalyser:
    """
    Takes an AccuracyReport and produces a FailureAnalysis with
    concrete per-issue repair strategies.
    """

    def analyse(self, report: AccuracyReport) -> FailureAnalysis:
        analysis = FailureAnalysis(report=report)

        for issue in report.all_issues:
            detail = self._classify_issue(issue, report)
            if detail:
                analysis.failures.append(detail)

        # Determine primary strategy — prefer cheaper options first
        strategies = analysis.strategies_needed()
        if not strategies:
            analysis.primary_strategy = RemediationStrategy.LLM_RETRY
        elif RemediationStrategy.STRUCTURAL_FIX in strategies:
            analysis.primary_strategy = RemediationStrategy.STRUCTURAL_FIX
        elif RemediationStrategy.ADD_RULE in strategies:
            analysis.primary_strategy = RemediationStrategy.ADD_RULE
        elif RemediationStrategy.SYNTAX_FIX in strategies:
            analysis.primary_strategy = RemediationStrategy.SYNTAX_FIX
        elif RemediationStrategy.LLM_PATCH in strategies:
            analysis.primary_strategy = RemediationStrategy.LLM_PATCH
        elif RemediationStrategy.HUMAN_REVIEW in strategies:
            analysis.primary_strategy = RemediationStrategy.HUMAN_REVIEW
        else:
            analysis.primary_strategy = RemediationStrategy.LLM_RETRY

        # If score is very low on behavioral — escalate to human
        behavioral = report.dimension_scores.get(Dimension.BEHAVIORAL)
        if behavioral and behavioral.score < 40:
            analysis.failures.append(FailureDetail(
                category=FailureCategory.COMPLEX_LOGIC,
                strategy=RemediationStrategy.HUMAN_REVIEW,
                dimension=Dimension.BEHAVIORAL,
                description="Behavioral score critically low — complex logic needs human review",
                repair_hint="Manual review of business logic translation required",
            ))
            analysis.primary_strategy = RemediationStrategy.HUMAN_REVIEW

        log.info(
            "  Failure analysis: %d issues, primary strategy: %s",
            len(analysis.failures),
            analysis.primary_strategy.value,
        )
        return analysis

    def _classify_issue(self, issue: str, report: AccuracyReport) -> Optional[FailureDetail]:
        for pattern, category, hint in _ANNOTATION_PATTERNS:
            if pattern.search(issue):
                return FailureDetail(
                    category=category,
                    strategy=_CATEGORY_STRATEGY[category],
                    dimension=_dimension_from_category(category),
                    description=issue,
                    repair_hint=hint,
                )
        # Default — unknown issue → LLM patch
        return FailureDetail(
            category=FailureCategory.COMPLEX_LOGIC,
            strategy=RemediationStrategy.LLM_PATCH,
            dimension=Dimension.SEMANTIC,
            description=issue,
            repair_hint="Ask LLM to specifically address this issue.",
        )
