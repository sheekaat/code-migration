"""Accuracy Engine — Remediation Executor
Executes targeted repairs for each failure strategy.
Each repair is as surgical as possible to minimise token usage.
"""

from __future__ import annotations
import re
from typing import Optional

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

from shared.models import ConversionResult, TargetLanguage, ConversionStatus
from shared.config import get_logger
from accuracy.analyser import (
    FailureAnalysis, FailureDetail,
    RemediationStrategy, FailureCategory,
)

log = get_logger(__name__)


# ─── Structural Fix (zero LLM tokens) ────────────────────────────────────────

_JAVA_PACKAGE_HEADER = "package com.company.app;\n\n"
_JAVA_COMMON_IMPORTS = (
    "import org.springframework.web.bind.annotation.*;\n"
    "import org.springframework.http.ResponseEntity;\n"
    "import org.springframework.stereotype.*;\n"
    "import java.util.*;\n"
    "import java.util.stream.Collectors;\n"
    "import java.util.Optional;\n\n"
)
_REACT_HEADER = "import React, { useState, useEffect, useCallback } from 'react';\n\n"


def apply_structural_fix(code: str, target: TargetLanguage, issues: list[str]) -> str:
    """
    Zero-token fixes: prepend missing headers, append missing exports.
    Applied first — cheapest possible repair.
    """
    if target == TargetLanguage.JAVA_SPRING:
        if not re.search(r'^package\s+', code, re.M):
            code = _JAVA_PACKAGE_HEADER + code
        if "import org.springframework" not in code:
            # Find package line and insert after it
            pkg_match = re.search(r'^package.*;\n', code, re.M)
            if pkg_match:
                insert_at = pkg_match.end()
                code = code[:insert_at] + "\n" + _JAVA_COMMON_IMPORTS + code[insert_at:]
            else:
                code = _JAVA_COMMON_IMPORTS + code

    elif target == TargetLanguage.REACT_JS:
        if "import React" not in code and "from 'react'" not in code:
            code = _REACT_HEADER + code
        if "export default" not in code:
            # Try to find the component name
            m = re.search(r'const\s+(\w+)\s*(?::\s*React\.FC)?.*?=\s*(?:async\s*)?\(', code)
            if m:
                code = code.rstrip() + f"\n\nexport default {m.group(1)};\n"
            else:
                code = code.rstrip() + "\n\nexport default Component;\n"

    return code


# ─── Syntax Fix (zero LLM tokens) ─────────────────────────────────────────────

def apply_syntax_fix(code: str, target: TargetLanguage) -> str:
    """Auto-repair common syntax problems without LLM."""
    # Balance braces — append missing closing braces
    opens  = code.count("{")
    closes = code.count("}")
    diff   = opens - closes
    if diff > 0:
        code = code.rstrip() + "\n" + ("}" * diff) + "\n"

    # Balance parentheses (JS/TS)
    if target == TargetLanguage.REACT_JS:
        p_opens  = code.count("(")
        p_closes = code.count(")")
        p_diff   = p_opens - p_closes
        if 0 < p_diff <= 3:
            code = code.rstrip() + (")" * p_diff) + "\n"

    return code


# ─── Annotation Rule Patch (zero LLM tokens) ─────────────────────────────────

_ANNOTATION_PATCHES: list[tuple[re.Pattern, str, str]] = [
    # If class extends ControllerBase and @RestController missing
    (re.compile(r'(public class \w+\s*(?:extends\s+\w+)?)\s*\{'),
     "@RestController\n", "missing_rest_controller"),

    # If @RequestMapping route present but @RestController missing
    (re.compile(r'(@RequestMapping\([^)]+\)\s*\n)(public class)'),
     r"\1@RestController\n\2", "add_rest_controller_above_route"),
]


def apply_annotation_rule(code: str, failures: list[FailureDetail]) -> str:
    """
    Apply targeted annotation patches based on failure hints.
    Does not use LLM — pure regex surgery.
    """
    for failure in failures:
        if failure.category != FailureCategory.MISSING_ANNOTATION:
            continue
        hint = failure.repair_hint

        if "@RestController" in hint and "@RestController" not in code:
            # Insert before the first public class declaration
            code = re.sub(
                r'(public\s+class\s+\w+)',
                r'@RestController\n\1',
                code,
                count=1,
            )

        elif "@Service" in hint and "@Service" not in code and "@RestController" not in code:
            code = re.sub(r'(public\s+class\s+\w+)', r'@Service\n\1', code, count=1)

        elif "@Repository" in hint and "@Repository" not in code:
            code = re.sub(r'(public\s+class\s+\w+)', r'@Repository\n\1', code, count=1)

        elif "import React" in hint and "import React" not in code:
            code = "import React, { useState, useEffect } from 'react';\n" + code

        elif "export default" in hint and "export default" not in code:
            m = re.search(r'const\s+(\w+)', code)
            name = m.group(1) if m else "Component"
            code = code.rstrip() + f"\n\nexport default {name};\n"

    return code


# ─── LLM Patch (targeted re-prompt — minimal tokens) ─────────────────────────

def build_patch_prompt(
    code: str,
    failures: list[FailureDetail],
    target: TargetLanguage,
) -> str:
    """Build a surgical patch prompt focusing only on identified failures."""
    target_name = (
        "Java Spring Boot 3 (Java 17)"
        if target == TargetLanguage.JAVA_SPRING
        else "ReactJS 18 (TypeScript)"
    )

    issues_list = "\n".join(
        f"  - {f.description}\n    FIX: {f.repair_hint}"
        for f in failures
    )

    return f"""You are doing a targeted patch on partially-converted {target_name} code.
The code has SPECIFIC issues listed below. Fix ONLY those issues.
Do not refactor, rename, or restructure anything else.
Return the complete fixed code. No explanations. No markdown fences.

## CRITICAL: NO Stubs or Placeholders
- NEVER add mock implementations, Thread.sleep, or placeholder comments
- NEVER use "This method would contain" or "For example" comments
- MUST provide actual working implementations for all fixes

## Issues to fix
{issues_list}

## Code to patch
{code}
"""


# ─── LLM Full Retry (complete re-conversion with enriched context) ────────────

def build_retry_prompt(
    source: str,
    failed_report_summary: str,
    target: TargetLanguage,
    iteration: int,
) -> str:
    """Build a full retry prompt with failure context injected."""
    target_name = (
        "Java Spring Boot 3 (Java 17)"
        if target == TargetLanguage.JAVA_SPRING
        else "ReactJS 18 (TypeScript)"
    )

    return f"""Convert the following source code to {target_name}.

This is retry attempt {iteration}. A previous attempt scored below 85% accuracy.
The specific failures were:
{failed_report_summary}

Fix all of these issues in your conversion.
Return ONLY the converted code. No markdown fences. No explanation.
Add '// TODO: Manual review' for any logic you cannot confidently translate.

## CRITICAL: Convert ALL Business Logic (Previous attempt had stubs!)
- NEVER output mock implementations, placeholder logic, or Thread.sleep
- NEVER use comments like "This method would contain" or "For example" or "Further methods would be..."
- NEVER claim "logic was not provided" - you HAVE the full source, convert it completely
- NEVER use "In a real scenario" or placeholder log statements - convert the ACTUAL implementation
- NEVER leave commented-out code blocks showing "what would be implemented" - implement it!
- MUST convert ALL methods from the source file - count them and ensure same number in output
- MUST convert ALL loop bodies, conditionals, and method calls with actual working code
- MUST convert ALL repository/service calls to actual JPA/Spring code
- MUST include ALL private helper methods - don't skip them
- Convert EVERY line of business logic - don't skip anything

## Source code
{source}
"""


# ─── Remediation Executor ─────────────────────────────────────────────────────

class RemediationExecutor:
    """
    Runs the remediation strategy for a failed conversion.
    Strategies are ordered cheapest → most expensive:
      STRUCTURAL_FIX → SYNTAX_FIX → ADD_RULE → LLM_PATCH → LLM_RETRY → HUMAN_REVIEW
    """

    def __init__(self, config: dict):
        self.config = config
        llm_cfg = config.get("llm", {})
        self.model      = llm_cfg.get("model", "gemini-2.0-flash")
        self.max_tokens = llm_cfg.get("max_tokens", 8000)
        self.temperature = 0.05   # very low for repair passes

        self.model_instance = None
        if HAS_GEMINI:
            api_key = llm_cfg.get("api_key", "")
            if api_key:
                genai.configure(api_key=api_key)
                self.model_instance = genai.GenerativeModel(self.model)

    def remediate(
        self,
        result: ConversionResult,
        analysis: FailureAnalysis,
        iteration: int,
    ) -> ConversionResult:
        """
        Apply repairs in priority order.
        Returns an updated ConversionResult with patched code.
        """
        code   = result.converted_code or ""
        target = result.target_language
        source = result.source_file.raw_content if result.source_file else ""
        strategies = analysis.strategies_needed()
        applied: list[str] = list(result.rules_applied or [])

        log.info(
            "  Remediation iter=%d strategies=%s",
            iteration, [s.value for s in strategies],
        )

        # 1. Structural fix (free)
        if RemediationStrategy.STRUCTURAL_FIX in strategies:
            code = apply_structural_fix(code, target, analysis.report.all_issues)
            applied.append("structural_fix")
            log.info("    Applied: structural_fix")

        # 2. Syntax fix (free)
        if RemediationStrategy.SYNTAX_FIX in strategies:
            code = apply_syntax_fix(code, target)
            applied.append("syntax_fix")
            log.info("    Applied: syntax_fix")

        # 3. Annotation rule patch (free)
        if RemediationStrategy.ADD_RULE in strategies:
            code = apply_annotation_rule(code, analysis.failures)
            applied.append("annotation_rule_patch")
            log.info("    Applied: annotation_rule_patch")

        # 4. LLM patch (targeted — cheap)
        llm_failures = [
            f for f in analysis.failures
            if f.strategy == RemediationStrategy.LLM_PATCH
        ]
        if llm_failures and RemediationStrategy.LLM_RETRY not in strategies:
            code = self._llm_patch(code, llm_failures, target) or code
            applied.append(f"llm_patch_iter{iteration}")
            log.info("    Applied: llm_patch (targeted)")

        # 5. Full LLM retry (more expensive — only if patch won't suffice)
        if RemediationStrategy.LLM_RETRY in strategies or (
            analysis.report.overall_score < 60 and iteration <= 2
        ):
            report_summary = "\n".join(
                f"  - {i}" for i in analysis.report.all_issues[:10]
            )
            code = self._llm_retry(source, report_summary, target, iteration) or code
            applied.append(f"llm_retry_iter{iteration}")
            log.info("    Applied: llm_full_retry")

        # 6. Human review flag (no auto-repair — just flag)
        if RemediationStrategy.HUMAN_REVIEW in strategies:
            result.status = ConversionStatus.NEEDS_REVIEW
            result.review_notes = (
                f"Iter {iteration}: Auto-repair could not resolve all issues. "
                "Manual review required for: "
                + "; ".join(
                    f.description for f in analysis.failures
                    if f.strategy == RemediationStrategy.HUMAN_REVIEW
                )
            )
            log.warning("    Flagged for HUMAN_REVIEW")

        result.converted_code = code
        result.rules_applied  = applied
        return result

    def _llm_patch(
        self,
        code: str,
        failures: list[FailureDetail],
        target: TargetLanguage,
    ) -> Optional[str]:
        if not self.model_instance:
            return None
        prompt = build_patch_prompt(code, failures, target)
        try:
            response = self.model_instance.generate_content(prompt)
            return response.text
        except Exception as e:
            log.error("Gemini patch failed: %s", e)
            return None

    def _llm_retry(
        self,
        source: str,
        report_summary: str,
        target: TargetLanguage,
        iteration: int,
    ) -> Optional[str]:
        if not self.model_instance:
            return None
        prompt = build_retry_prompt(source, report_summary, target, iteration)
        try:
            response = self.model_instance.generate_content(prompt)
            return response.text
        except Exception as e:
            log.error("Gemini retry failed: %s", e)
            return None
