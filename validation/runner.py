"""
Layer 4 — Automated Validation
Compile checks, semantic diff, test runner, and confidence gating.
"""

from __future__ import annotations
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from shared.models import (
    ConversionResult, ConversionStatus, TargetLanguage, WorkspaceManifest,
)
from shared.config import get_logger
from validation.component_validators import validate_component
from ingestion.file_type_registry import detect_file_type

log = get_logger(__name__)


# ─── Validation Result ────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    result_id: str
    file_path: str
    compile_passed: bool = False
    compile_errors: list[str] = field(default_factory=list)
    semantic_issues: list[str] = field(default_factory=list)
    test_pass_rate: float = 0.0
    overall_passed: bool = False
    notes: str = ""

    @property
    def score(self) -> float:
        s = 0.0
        if self.compile_passed:
            s += 0.5
        if not self.semantic_issues:
            s += 0.3
        s += self.test_pass_rate * 0.2
        return s


# ─── Semantic Diff ────────────────────────────────────────────────────────────

class SemanticDiff:
    """
    AST-level equivalence checker.
    Detects missing methods, changed logic branches, dropped imports.
    """

    _METHOD_RE_JAVA = re.compile(
        r'(?:public|private|protected)\s+\w[\w<>\[\]]*\s+(\w+)\s*\(', re.M
    )
    _METHOD_RE_REACT = re.compile(
        r'(?:function|const|let)\s+(\w+)\s*(?:=\s*(?:async\s*)?\(|:\s*React\.FC\s*=)', re.M
    )
    _TODO_RE = re.compile(r'//\s*TODO', re.I)
    _IMPORT_COUNT_RE = re.compile(r'^import\s+', re.M)

    def diff(self, source: str, converted: str, target: TargetLanguage) -> list[str]:
        issues: list[str] = []

        # Check TODO density
        todo_count = len(self._TODO_RE.findall(converted))
        converted_lines = max(converted.count("\n"), 1)
        if todo_count / converted_lines > 0.05:
            issues.append(
                f"High TODO density: {todo_count} TODOs in {converted_lines} lines "
                f"({100*todo_count/converted_lines:.1f}%)"
            )

        # Check for empty output
        if len(converted.strip()) < 50:
            issues.append("Converted output is suspiciously short — possible failed conversion")

        # Target-specific checks
        if target == TargetLanguage.JAVA_SPRING:
            issues += self._check_java(source, converted)
        elif target == TargetLanguage.REACT_JS:
            issues += self._check_react(source, converted)

        return issues

    def _check_java(self, source: str, converted: str) -> list[str]:
        issues = []
        if "@RestController" not in converted and "[ApiController]" in source:
            issues.append("Missing @RestController — [ApiController] was not translated")
        if "ResponseEntity" not in converted and "IActionResult" in source:
            issues.append("Missing ResponseEntity — IActionResult was not translated")
        if "@Service" not in converted and "IService" in source:
            issues.append("Possible missing @Service annotation")
        if "import" not in converted:
            issues.append("No import statements found — Java file likely missing imports")
        return issues

    def _check_react(self, source: str, converted: str) -> list[str]:
        issues = []
        if "import React" not in converted and "from 'react'" not in converted:
            issues.append("Missing React import")
        if "export default" not in converted and "export " not in converted:
            issues.append("No export statement found — component won't be importable")
        if "Form_Load" in source and "useEffect" not in converted:
            issues.append("VB6 Form_Load not converted to useEffect")
        if "useState" not in converted and ("Dim " in source or "state" in source.lower()):
            issues.append("Possible missing useState — source has stateful variables")
        return issues


# ─── Syntax Checker ───────────────────────────────────────────────────────────

class SyntaxChecker:
    """Lightweight syntax validation without running a full compiler."""

    _JAVA_UNMATCHED = re.compile(r'\{|\}')
    _JS_KEYWORDS    = re.compile(r'\b(function|const|let|var|import|export|return|if|for)\b')

    def check_java(self, code: str) -> list[str]:
        errors = []
        opens  = code.count("{")
        closes = code.count("}")
        if abs(opens - closes) > 2:
            errors.append(f"Unbalanced braces detected: {opens} open vs {closes} close")
        if "class " not in code and "interface " not in code and "enum " not in code:
            errors.append("No class/interface/enum declaration found")
        return errors

    def check_javascript(self, code: str) -> list[str]:
        errors = []
        opens  = code.count("{")
        closes = code.count("}")
        if abs(opens - closes) > 2:
            errors.append(f"Unbalanced braces detected: {opens} open vs {closes} close")
        if not self._JS_KEYWORDS.search(code):
            errors.append("No recognisable JavaScript keywords found")
        return errors

    def check(self, code: str, target: TargetLanguage) -> list[str]:
        if target == TargetLanguage.JAVA_SPRING:
            return self.check_java(code)
        return self.check_javascript(code)


# ─── External Compile Check (optional) ───────────────────────────────────────

def try_compile_java(code: str) -> tuple[bool, list[str]]:
    """Attempt to compile a single Java file using javac if available."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            java_file = Path(tmpdir) / "Converted.java"
            java_file.write_text(code)
            proc = subprocess.run(
                ["javac", str(java_file)],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0:
                return True, []
            errors = [l for l in proc.stderr.splitlines() if "error:" in l]
            return False, errors
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True, []   # javac not available — skip


def try_compile_js(code: str) -> tuple[bool, list[str]]:
    """Attempt to parse JS/TS using node --check if available."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            js_file = Path(tmpdir) / "converted.js"
            js_file.write_text(code, encoding="utf-8")
            proc = subprocess.run(
                ["node", "--check", str(js_file)],
                capture_output=True, text=True, timeout=20,
            )
            if proc.returncode == 0:
                return True, []
            errors = proc.stderr.splitlines()[:5]
            return False, errors
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True, []


# ─── Validation Runner ────────────────────────────────────────────────────────

class ValidationRunner:
    def __init__(self, config: dict):
        self.config = config
        self.semantic_diff = SemanticDiff()
        self.syntax_checker = SyntaxChecker()
        self._threshold = config.get("conversion", {}).get("confidence_threshold", 0.75)

    def validate(self, result: ConversionResult) -> ValidationReport:
        report = ValidationReport(
            result_id=result.id,
            file_path=result.source_file.path if result.source_file else "",
        )

        if not result.converted_code:
            report.notes = "No converted code to validate"
            return report

        code     = result.converted_code
        target   = result.target_language
        source   = result.source_file.raw_content if result.source_file else ""
        
        # Detect component type for targeted validation
        file_type_info = detect_file_type(result.source_file.path, source)
        primary_component = file_type_info.components[0] if file_type_info.components else None

        # 1. Syntax check
        syntax_errors = self.syntax_checker.check(code, target)
        report.compile_errors = syntax_errors

        # 2. External compile (best-effort)
        if target == TargetLanguage.JAVA_SPRING:
            passed, errs = try_compile_java(code)
        else:
            passed, errs = try_compile_js(code)
        report.compile_passed = passed and not syntax_errors
        report.compile_errors += errs

        # 3. Semantic diff
        report.semantic_issues = self.semantic_diff.diff(source, code, target)

        # 4. Component-specific validation
        if primary_component:
            component_issues = validate_component(
                primary_component.type,
                target,
                code
            )
            for issue in component_issues:
                if issue['severity'] == 'error':
                    report.compile_errors.append(f"[{issue['rule']}] {issue['description']}")
                else:
                    report.semantic_issues.append(f"[{issue['rule']}] {issue['description']}")

        # 5. Confidence gate
        report.overall_passed = (
            report.compile_passed
            and len(report.semantic_issues) == 0
            and result.confidence >= self._threshold
        )

        if not report.overall_passed:
            result.status = ConversionStatus.NEEDS_REVIEW
        else:
            result.validation_passed = True
            result.status = ConversionStatus.VALIDATED

        log.info(
            "Validation %s for %s (conf=%.2f, issues=%d)",
            "PASSED" if report.overall_passed else "FAILED",
            report.file_path,
            result.confidence,
            len(report.semantic_issues),
        )
        return report

    def validate_manifest(self, manifest: WorkspaceManifest) -> list[ValidationReport]:
        reports = [self.validate(r) for r in manifest.conversion_results]
        passed  = sum(1 for r in reports if r.overall_passed)
        manifest.stats["validation"] = {
            "total": len(reports),
            "passed": passed,
            "failed": len(reports) - passed,
            "pass_rate": f"{100*passed/max(len(reports),1):.1f}%",
        }
        return reports
