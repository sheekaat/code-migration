"""Enhanced Accuracy Remediation with Per-Dimension Targeting

This module provides:
1. Extended rule-based pre-fixes for common conversion issues
2. Per-dimension targeted LLM prompts for surgical fixes
3. Dimension-aware iteration tracking

Strategies applied in order (cheapest first):
  1. EXTENDED_STRUCTURAL_FIX - package, imports, exports, headers
  2. SYNTAX_FIX - balance braces, fix common syntax errors
  3. ANNOTATION_RULES - @RestController, @Service, @Repository
  4. TYPE_MAPPING_RULES - bool→boolean, string→String, etc.
  5. PATTERN_RULES - LINQ→Stream, events→hooks, etc.
  6. DIMENSION_TARGETED_LLM_PATCH - specific prompts per failing dimension
  7. FULL_LLM_RETRY - complete re-conversion with context
  8. HUMAN_REVIEW - flag for manual intervention
"""

from __future__ import annotations
import re
from typing import Optional, Dict, List
from dataclasses import dataclass

from shared.models import ConversionResult, TargetLanguage
from shared.config import get_logger
from accuracy.scorer import AccuracyReport, Dimension, DimensionScore
from accuracy.analyser import (
    FailureAnalysis, FailureDetail,
    RemediationStrategy, FailureCategory,
)

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

log = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# EXTENDED RULE-BASED PRE-FIXES (Zero LLM tokens)
# ═══════════════════════════════════════════════════════════════════════════

# Java Spring patterns
_JAVA_PATTERNS = [
    # Missing @RestController on controller classes
    (re.compile(r'public\s+class\s+(\w+)(?:Controller|Resource)\b'),
     r'@RestController\npublic class \1',
     "Added @RestController to controller class"),
    
    # Missing @Service on service classes
    (re.compile(r'public\s+class\s+(\w+)Service\b(?!.*@Service)'),
     r'@Service\npublic class \1Service',
     "Added @Service to service class"),
    
    # Missing @Repository on repository classes
    (re.compile(r'public\s+(?:interface|class)\s+(\w+)Repository\b(?!.*@Repository)'),
     r'@Repository\npublic interface \1Repository',
     "Added @Repository to repository interface"),
    
    # Missing @Component on component classes
    (re.compile(r'public\s+class\s+(\w+)Component\b(?!.*@(Component|Service|Repository|RestController))'),
     r'@Component\npublic class \1Component',
     "Added @Component to component class"),
    
    # Missing @Autowired on constructor injection
    (re.compile(r'public\s+(\w+)\(([^)]+\w+\s+\w+)\)(?!.*@Autowired)'),
     r'@Autowired\n    public \1(\2)',
     "Added @Autowired to constructor"),
    
    # Missing @RequestMapping on controller methods without HTTP method annotations
    (re.compile(r'(@RestController.*?public\s+class.*?\{(?:[^{}]|\{[^{}]*\})*?)\n\s+(public\s+\w+\s+\w+\([^)]*\)\s*\{)'),
     r'\1\n    @RequestMapping\n    \2',
     "Added @RequestMapping to controller method"),
    
    # String type fixes
    (re.compile(r'\bstring\b(?=\s+\w+)'),
     'String',
     "Fixed string → String type mapping"),
    
    # bool type fixes
    (re.compile(r'\bbool\b(?=\s+\w+)'),
     'boolean',
     "Fixed bool → boolean type mapping"),
    
    # int type consistency
    (re.compile(r'\bInt32\b|\bInteger\b(?=\s+\w+)'),
     'int',
     "Fixed Int32/Integer → int type mapping"),
]

# React/TypeScript patterns
_REACT_PATTERNS = [
    # Missing import for common hooks
    (re.compile(r'^(?!.*import.*React)(?=.*useState|useEffect|useCallback)'),
     "import React, { useState, useEffect, useCallback } from 'react';\n",
     "Added React hooks import"),
    
    # Missing export default
    (re.compile(r'const\s+(\w+)\s*=\s*(?:React\.)?FC.*?=>(?!.*export default)'),
     r'export default \1;',
     "Added default export for component"),
    
    # Function component without proper typing
    (re.compile(r'function\s+(\w+)\s*\(([^)]*)\)(?!\s*:\s*React\.)'),
     r'function \1(\2): JSX.Element',
     "Added return type annotation to function component"),
    
    # onClick handler not using useCallback
    (re.compile(r'onClick=\{(\w+)\}(?!.*useCallback)'),
     r'onClick={useCallback(\1, [])}',
     "Wrapped onClick handler in useCallback"),
    
    # VB6 event pattern → React
    (re.compile(r'(\w+)_Click\s*\('),
     r'onClick={handle\1Click}',
     "Converted VB6 _Click event to React onClick"),
    
    # VB6 Change event → React
    (re.compile(r'(\w+)_Change\s*\('),
     r'onChange={handle\1Change}',
     "Converted VB6 _Change event to React onChange"),
]


def apply_extended_structural_fix(
    code: str,
    target: TargetLanguage,
    report: AccuracyReport
) -> tuple[str, List[str]]:
    """Apply extended structural fixes based on target language and issues.
    
    Returns: (fixed_code, list_of_applied_fixes)
    """
    applied = []
    original_code = code
    
    # Add package declaration for Java if missing
    if target == TargetLanguage.JAVA_SPRING:
        if not re.search(r'^package\s+', code, re.MULTILINE):
            code = "package com.company.app;\n\n" + code
            applied.append("Added package declaration")
        
        # Add common imports if controller has HTTP annotations but no Spring imports
        if re.search(r'@(GetMapping|PostMapping|RequestMapping)', code):
            if 'import org.springframework' not in code:
                imports = (
                    "import org.springframework.web.bind.annotation.*;\n"
                    "import org.springframework.http.ResponseEntity;\n"
                    "import org.springframework.stereotype.*;\n"
                )
                # Insert after package line
                pkg_match = re.search(r'^package.*;\s*', code, re.MULTILINE)
                if pkg_match:
                    insert_pos = pkg_match.end()
                    code = code[:insert_pos] + "\n" + imports + code[insert_pos:]
                    applied.append("Added Spring Web imports")
    
    # Apply language-specific regex patterns
    patterns = _JAVA_PATTERNS if target == TargetLanguage.JAVA_SPRING else _REACT_PATTERNS
    
    for pattern, replacement, description in patterns:
        if pattern.search(code):
            code = pattern.sub(replacement, code)
            if code != original_code:
                applied.append(description)
                original_code = code
    
    return code, applied


def apply_syntax_fix(code: str, target: TargetLanguage) -> tuple[str, List[str]]:
    """Apply syntax fixes and return (fixed_code, applied_fixes)."""
    applied = []
    
    # Balance braces
    opens = code.count("{")
    closes = code.count("}")
    diff = opens - closes
    if diff > 0:
        code = code.rstrip() + "\n" + ("}" * diff) + "\n"
        applied.append(f"Added {diff} missing closing braces")
    elif diff < 0:
        # Too many closing braces - remove extras at end
        code = code.rstrip()
        for _ in range(abs(diff)):
            if code.endswith("}"):
                code = code[:-1].rstrip()
        code += "\n"
        applied.append(f"Removed {abs(diff)} extra closing braces")
    
    # Balance parentheses for JS/TS
    if target == TargetLanguage.REACT_JS:
        p_opens = code.count("(")
        p_closes = code.count(")")
        p_diff = p_opens - p_closes
        if 0 < p_diff <= 3:
            code = code.rstrip() + (")" * p_diff) + "\n"
            applied.append(f"Added {p_diff} missing closing parentheses")
    
    # Fix missing semicolons in Java (basic heuristic)
    if target == TargetLanguage.JAVA_SPRING:
        lines = code.split('\n')
        fixed_lines = []
        for line in lines:
            stripped = line.strip()
            # Add semicolon to lines that look like statements but don't have one
            if (stripped and 
                not stripped.endswith((';', '{', '}', '//', '/*', '*/', ',')) and
                not stripped.startswith(('import', 'package', '@', 'public', 'private', 'protected', 'class', 'interface', 'if', 'for', 'while', 'return')) and
                re.search(r'[a-zA-Z0-9_\]]\s*$', stripped)):
                line = line + ';'
            fixed_lines.append(line)
        if fixed_lines != lines:
            code = '\n'.join(fixed_lines)
            applied.append("Added missing semicolons")
    
    return code, applied


# ═══════════════════════════════════════════════════════════════════════════
# PER-DIMENSION TARGETED LLM PROMPTS
# ═══════════════════════════════════════════════════════════════════════════

def build_dimension_targeted_prompt(
    code: str,
    source: str,
    target: TargetLanguage,
    report: AccuracyReport,
    failures: List[FailureDetail]
) -> Optional[str]:
    """Build a targeted LLM prompt based on the weakest dimension.
    
    Analyzes the dimension scores and creates specific instructions
    for the dimension with the lowest score.
    """
    if not report.dimension_scores:
        return None
    
    # Find the weakest dimension
    weakest = min(
        report.dimension_scores.values(),
        key=lambda ds: ds.score
    )
    
    target_name = "Java Spring Boot 3" if target == TargetLanguage.JAVA_SPRING else "ReactJS 18 TypeScript"
    
    # Build dimension-specific instructions
    if weakest.dimension == Dimension.SYNTAX:
        return _build_syntax_prompt(code, target_name, weakest)
    elif weakest.dimension == Dimension.SEMANTIC:
        return _build_semantic_prompt(code, source, target_name, weakest, failures)
    elif weakest.dimension == Dimension.STRUCTURAL:
        return _build_structural_prompt(code, target_name, weakest)
    elif weakest.dimension == Dimension.BEHAVIORAL:
        return _build_behavioral_prompt(code, source, target_name, weakest, failures)
    elif weakest.dimension == Dimension.COVERAGE:
        return _build_coverage_prompt(code, source, target_name, weakest)
    else:
        return None


def _build_syntax_prompt(code: str, target_name: str, dim_score: DimensionScore) -> str:
    """Prompt for syntax issues."""
    issues_text = "\n".join(f"  - {issue}" for issue in dim_score.issues[:5])
    
    return f"""Fix SYNTAX ERRORS in this {target_name} code.

The code has compile/syntax issues that must be resolved:
{issues_text}

Specific fixes required:
  1. Balance all opening/closing braces {{ }}
  2. Balance all parentheses ( )
  3. Add missing semicolons where needed
  4. Fix any typos in keywords or type names
  5. Ensure all string literals are properly closed

Return ONLY the fixed code. No explanations. No markdown fences.

CODE TO FIX:
{code}
"""


def _build_semantic_prompt(
    code: str,
    source: str,
    target_name: str,
    dim_score: DimensionScore,
    failures: List[FailureDetail]
) -> str:
    """Prompt for semantic translation issues."""
    issues_text = "\n".join(f"  - {issue}" for issue in dim_score.issues[:5])
    
    # Extract repair hints from semantic-related failures
    hints = []
    for f in failures:
        if f.dimension == Dimension.SEMANTIC and f.repair_hint:
            hints.append(f"  - {f.repair_hint}")
    hints_text = "\n".join(hints[:3]) if hints else "  - Ensure all logic patterns are correctly translated"
    
    return f"""Fix SEMANTIC TRANSLATION ISSUES in this {target_name} code.

The conversion has incorrect semantic mappings:
{issues_text}

Specific translation fixes needed:
{hints_text}

Translation rules to apply:
  - LINQ → Stream API (Select → map, Where → filter, FirstOrDefault → findFirst)
  - Entity Framework → JPA/Hibernate or fetch/axios
  - C# events → React hooks or Java listeners
  - Extension methods → static utility classes
  - Nullable types → Optional<T> or proper null checks

Return ONLY the corrected code. No explanations. No markdown fences.

ORIGINAL SOURCE (for reference):
{source[:2000]}

CODE TO FIX:
{code}
"""


def _build_structural_prompt(code: str, target_name: str, dim_score: DimensionScore) -> str:
    """Prompt for structural issues."""
    issues_text = "\n".join(f"  - {issue}" for issue in dim_score.issues[:5])
    
    return f"""Fix STRUCTURAL ISSUES in this {target_name} code.

The code has missing structural elements:
{issues_text}

Required structural fixes:
  1. Add correct package/namespace declaration
  2. Add all necessary imports (no unused imports)
  3. Add proper class-level annotations (@RestController, @Service, etc.)
  4. Ensure proper file organization
  5. Add missing public/private access modifiers
  6. Ensure proper class naming conventions

Return ONLY the fixed code. No explanations. No markdown fences.

CODE TO FIX:
{code}
"""


def _build_behavioral_prompt(
    code: str,
    source: str,
    target_name: str,
    dim_score: DimensionScore,
    failures: List[FailureDetail]
) -> str:
    """Prompt for behavioral equivalence issues."""
    issues_text = "\n".join(f"  - {issue}" for issue in dim_score.issues[:5])
    
    # Extract behavioral hints
    hints = []
    for f in failures:
        if f.dimension == Dimension.BEHAVIORAL and f.repair_hint:
            hints.append(f"  - {f.repair_hint}")
    hints_text = "\n".join(hints[:3]) if hints else "  - Ensure runtime behavior matches original"
    
    return f"""Fix BEHAVIORAL EQUIVALENCE issues in this {target_name} code.

The code doesn't behave like the original:
{issues_text}

Behavioral fixes required:
{hints_text}

Critical behavioral checks:
  - Async/await properly converted to CompletableFuture or Promises
  - Error handling preserves original behavior (try/catch, error boundaries)
  - State management correctly mapped (useState, useReducer, class fields)
  - Transaction boundaries preserved (@Transactional)
  - Null safety equivalent (Optional, null checks)
  - Side effects properly handled (useEffect, @PostConstruct)

Return ONLY the fixed code. No explanations. No markdown fences.

ORIGINAL SOURCE (for reference):
{source[:2000]}

CODE TO FIX:
{code}
"""


def _build_coverage_prompt(code: str, source: str, target_name: str, dim_score: DimensionScore) -> str:
    """Prompt for incomplete coverage (stubs)."""
    issues_text = "\n".join(f"  - {issue}" for issue in dim_score.issues[:5])
    
    # Calculate lines to estimate how much is stubbed
    source_lines = len(source.split('\n'))
    code_lines = len(code.split('\n'))
    
    return f"""Complete the PARTIAL CONVERSION of this {target_name} code.

The conversion has incomplete coverage:
{issues_text}

Coverage statistics:
  - Source had ~{source_lines} lines
  - Current output has ~{code_lines} lines
  - Missing logic needs to be implemented

Requirements:
  1. Replace all AUTO-GENERATED STUBS with real implementations
  2. Convert ALL methods from source, not just the main ones
  3. Include helper methods and private functions
  4. Preserve ALL business logic from original
  5. Add TODO comments only for genuinely untranslatable logic

Return the COMPLETE converted code. No explanations. No markdown fences.

ORIGINAL SOURCE:
{source[:3000]}

CURRENT INCOMPLETE CODE:
{code}
"""


# ═══════════════════════════════════════════════════════════════════════════
# ENHANCED REMEDIATION EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════

class EnhancedRemediationExecutor:
    """Enhanced executor with per-dimension targeting and extended rules."""
    
    def __init__(self, config: dict):
        self.config = config
        llm_cfg = config.get("llm", {})
        self.model = llm_cfg.get("model", "gemini-2.0-flash")
        self.max_tokens = llm_cfg.get("max_tokens", 8000)
        self.temperature = 0.05
        
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
        """Apply enhanced remediation with per-dimension targeting."""
        code = result.converted_code or ""
        target = result.target_language
        source = result.source_file.raw_content if result.source_file else ""
        report = analysis.report
        applied: list[str] = list(result.rules_applied or [])
        
        log.info("Enhanced remediation iter=%d", iteration)
        
        # 1. Extended structural fixes
        code, structural_fixes = apply_extended_structural_fix(code, target, report)
        if structural_fixes:
            applied.extend(structural_fixes)
            log.info("  Applied %d structural fixes", len(structural_fixes))
        
        # 2. Syntax fixes
        code, syntax_fixes = apply_syntax_fix(code, target)
        if syntax_fixes:
            applied.extend(syntax_fixes)
            log.info("  Applied %d syntax fixes", len(syntax_fixes))
        
        # 3. Per-dimension targeted LLM patch (NEW)
        if report.overall_score < 85 and iteration <= 2:
            targeted_prompt = build_dimension_targeted_prompt(
                code, source, target, report, analysis.failures
            )
            if targeted_prompt and self.model_instance:
                new_code = self._llm_targeted_patch(targeted_prompt)
                if new_code and len(new_code) > len(code) * 0.8:  # Sanity check
                    code = new_code
                    applied.append(f"dimension_targeted_llm_patch_iter{iteration}")
                    log.info("  Applied dimension-targeted LLM patch")
        
        # 4. Standard LLM patch for specific failures
        llm_failures = [
            f for f in analysis.failures
            if f.strategy == RemediationStrategy.LLM_PATCH
        ]
        if llm_failures and RemediationStrategy.LLM_RETRY not in analysis.strategies_needed():
            if not any("dimension_targeted" in a for a in applied):  # Don't double-patch
                code = self._standard_llm_patch(code, llm_failures, target) or code
                applied.append(f"standard_llm_patch_iter{iteration}")
                log.info("  Applied standard LLM patch")
        
        # 5. Full LLM retry as last resort
        if RemediationStrategy.LLM_RETRY in analysis.strategies_needed() or (
            report.overall_score < 70 and iteration == 3
        ):
            report_summary = "\n".join(f"  - {i}" for i in report.all_issues[:8])
            code = self._llm_retry(source, report_summary, target, iteration) or code
            applied.append(f"llm_full_retry_iter{iteration}")
            log.info("  Applied full LLM retry")
        
        # 6. Flag for human review
        if RemediationStrategy.HUMAN_REVIEW in analysis.strategies_needed():
            result.status = result.status or type(result.status).__getattr__(result.status, 'NEEDS_REVIEW')
            human_issues = [
                f.description for f in analysis.failures
                if f.strategy == RemediationStrategy.HUMAN_REVIEW
            ]
            result.review_notes = (
                f"Iter {iteration}: Issues requiring manual review: "
                + "; ".join(human_issues[:3])
            )
            log.warning("  Flagged for human review")
        
        result.converted_code = code
        result.rules_applied = applied
        return result
    
    def _llm_targeted_patch(self, prompt: str) -> Optional[str]:
        """Apply dimension-targeted LLM patch."""
        if not self.model_instance:
            return None
        try:
            response = self.model_instance.generate_content(
                prompt,
                generation_config={"temperature": 0.05, "max_output_tokens": self.max_tokens}
            )
            return response.text
        except Exception as e:
            log.error("Targeted LLM patch failed: %s", e)
            return None
    
    def _standard_llm_patch(
        self,
        code: str,
        failures: List[FailureDetail],
        target: TargetLanguage
    ) -> Optional[str]:
        """Apply standard failure-specific LLM patch."""
        if not self.model_instance:
            return None
        
        target_name = "Java Spring Boot" if target == TargetLanguage.JAVA_SPRING else "ReactJS TypeScript"
        issues_list = "\n".join(f"  - {f.description}\n    FIX: {f.repair_hint}" for f in failures[:5])
        
        prompt = f"""Fix these specific issues in the {target_name} code:

{issues_list}

Return ONLY the fixed code. No explanations.

CODE:
{code}
"""
        try:
            response = self.model_instance.generate_content(
                prompt,
                generation_config={"temperature": 0.05, "max_output_tokens": self.max_tokens}
            )
            return response.text
        except Exception as e:
            log.error("Standard LLM patch failed: %s", e)
            return None
    
    def _llm_retry(
        self,
        source: str,
        report_summary: str,
        target: TargetLanguage,
        iteration: int,
    ) -> Optional[str]:
        """Apply full LLM retry with context."""
        if not self.model_instance:
            return None
        
        target_name = "Java Spring Boot" if target == TargetLanguage.JAVA_SPRING else "ReactJS TypeScript"
        
        prompt = f"""Convert this source code to {target_name} (retry attempt {iteration}).

Previous attempt had these failures:
{report_summary}

Fix all issues. Return ONLY the converted code.

SOURCE:
{source}
"""
        try:
            response = self.model_instance.generate_content(
                prompt,
                generation_config={"temperature": 0.1, "max_output_tokens": self.max_tokens}
            )
            return response.text
        except Exception as e:
            log.error("LLM retry failed: %s", e)
            return None
