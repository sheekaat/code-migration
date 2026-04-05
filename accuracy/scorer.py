"""
Accuracy Engine — Multi-Dimensional Scoring
Scores converted code across 5 dimensions and produces a weighted
overall accuracy score. If score < 85%, triggers the remediation loop.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from shared.models import ConversionResult, TargetLanguage, SourceLanguage
from shared.config import get_logger

log = get_logger(__name__)

ACCURACY_THRESHOLD = 85.0   # percent — below this triggers self-healing


# ─── Score Dimensions ─────────────────────────────────────────────────────────

class Dimension(str, Enum):
    SYNTAX     = "syntax"       # does code parse / compile cleanly?
    SEMANTIC   = "semantic"     # does it preserve original logic/intent?
    STRUCTURAL = "structural"   # correct class/method/package structure?
    BEHAVIORAL = "behavioral"   # would it behave identically at runtime?
    COVERAGE   = "coverage"     # what % of source constructs were translated?


# Weights must sum to 1.0
DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.SYNTAX:     0.20,
    Dimension.SEMANTIC:   0.30,
    Dimension.STRUCTURAL: 0.20,
    Dimension.BEHAVIORAL: 0.20,
    Dimension.COVERAGE:   0.10,
}


@dataclass
class DimensionScore:
    dimension: Dimension
    score: float              # 0–100
    weight: float
    issues: list[str] = field(default_factory=list)
    details: str = ""

    @property
    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class AccuracyReport:
    result_id: str
    file_path: str
    dimension_scores: dict[Dimension, DimensionScore] = field(default_factory=dict)
    overall_score: float = 0.0
    passed: bool = False
    iteration: int = 1
    all_issues: list[str] = field(default_factory=list)
    remediation_applied: list[str] = field(default_factory=list)

    def compute_overall(self) -> float:
        total = sum(ds.weighted for ds in self.dimension_scores.values())
        self.overall_score = round(total, 2)
        self.passed = self.overall_score >= ACCURACY_THRESHOLD
        self.all_issues = [
            issue
            for ds in self.dimension_scores.values()
            for issue in ds.issues
        ]
        return self.overall_score

    def failed_dimensions(self) -> list[Dimension]:
        return [
            d for d, ds in self.dimension_scores.items()
            if ds.score < 70.0
        ]

    def summary_line(self) -> str:
        icon = "✅" if self.passed else "❌"
        dims = " | ".join(
            f"{d.value[:3].upper()}={ds.score:.0f}"
            for d, ds in self.dimension_scores.items()
        )
        return f"{icon} {self.overall_score:.1f}% [{dims}] iter={self.iteration}"


# ─── Per-dimension scorers ─────────────────────────────────────────────────────

class SyntaxScorer:
    """Checks brace balance, required keywords, and obvious syntax errors."""

    def score(self, code: str, target: TargetLanguage) -> DimensionScore:
        issues: list[str] = []
        s = 100.0

        opens  = code.count("{")
        closes = code.count("}")
        if abs(opens - closes) >= 2:
            issues.append(f"Unbalanced braces: {opens} open / {closes} close")
            s -= 30

        if target == TargetLanguage.JAVA_SPRING:
            if "class " not in code and "interface " not in code:
                issues.append("No class/interface declaration found")
                s -= 25
            if "import " not in code and len(code.strip()) > 100:
                issues.append("No import statements — likely missing dependencies")
                s -= 10
            # Unclosed string literals (rough)
            if code.count('"') % 2 != 0:
                issues.append("Possible unclosed string literal")
                s -= 10

        elif target == TargetLanguage.REACT_JS:
            if "import " not in code and "require(" not in code:
                issues.append("No import statements found")
                s -= 15
            if "export " not in code:
                issues.append("No export statement — component not importable")
                s -= 20
            parens_open  = code.count("(")
            parens_close = code.count(")")
            if abs(parens_open - parens_close) > 3:
                issues.append(f"Unbalanced parentheses: {parens_open} open / {parens_close} close")
                s -= 20

        return DimensionScore(
            dimension=Dimension.SYNTAX,
            score=max(0.0, s),
            weight=DIMENSION_WEIGHTS[Dimension.SYNTAX],
            issues=issues,
        )


class SemanticScorer:
    """Checks that key logic constructs from source appear in converted code."""

    # Source patterns that must survive conversion
    _JAVA_REQUIRED: list[tuple[re.Pattern, str, float]] = [
        (re.compile(r'\[ApiController\]'),         "@RestController",             15),
        (re.compile(r'\[HttpGet'),                  "@GetMapping",                 10),
        (re.compile(r'\[HttpPost'),                 "@PostMapping",                10),
        (re.compile(r'IActionResult'),              "ResponseEntity",              10),
        (re.compile(r'\.Where\('),                  ".stream().filter(",           8),
        (re.compile(r'\.Select\('),                 ".map(",                       8),
        (re.compile(r'IRepository|DbContext'),      "@Repository",                 8),
        (re.compile(r'\[FromBody\]'),               "@RequestBody",                7),
        (re.compile(r'async\s+Task'),               "CompletableFuture|async",     5),
    ]
    _REACT_REQUIRED: list[tuple[re.Pattern, str, float]] = [
        (re.compile(r'Form_Load|Page_Load', re.I), "useEffect",                   15),
        (re.compile(r'Dim\s+\w+\s+As', re.I),     "useState|let |const ",        10),
        (re.compile(r'MsgBox', re.I),              "alert|Modal",                 8),
        (re.compile(r'INotifyPropertyChanged'),    "useState",                    12),
        (re.compile(r'ICommand'),                  "onClick|onChange",            10),
        (re.compile(r'For\s+\w+\s*=', re.I),      "for |map(|forEach(",          8),
    ]

    def score(
        self, source: str, converted: str, target: TargetLanguage
    ) -> DimensionScore:
        issues: list[str] = []
        s = 100.0

        rules = (
            self._JAVA_REQUIRED
            if target == TargetLanguage.JAVA_SPRING
            else self._REACT_REQUIRED
        )

        for src_pattern, expected_target, penalty in rules:
            if src_pattern.search(source):
                # Source has this construct — check it's translated
                alts = expected_target.split("|")
                if not any(alt in converted for alt in alts):
                    issues.append(
                        f"Source construct '{src_pattern.pattern}' not translated "
                        f"to '{expected_target}'"
                    )
                    s -= penalty

        # TODO density penalty
        todo_count = converted.count("// TODO")
        lines = max(converted.count("\n"), 1)
        todo_ratio = todo_count / lines
        if todo_ratio > 0.08:
            penalty = min(40, int(todo_ratio * 150))
            issues.append(f"High TODO density: {todo_count} TODOs ({todo_ratio:.0%})")
            s -= penalty

        return DimensionScore(
            dimension=Dimension.SEMANTIC,
            score=max(0.0, s),
            weight=DIMENSION_WEIGHTS[Dimension.SEMANTIC],
            issues=issues,
        )


class StructuralScorer:
    """Checks package/module structure, class naming, annotations."""

    def score(self, converted: str, target: TargetLanguage) -> DimensionScore:
        issues: list[str] = []
        s = 100.0

        if target == TargetLanguage.JAVA_SPRING:
            if not re.search(r'^package\s+[\w.]+;', converted, re.M):
                issues.append("Missing package declaration")
                s -= 20
            if not re.search(r'@(?:RestController|Service|Repository|Component)\b', converted):
                issues.append("No Spring stereotype annotation (@Service, @RestController, etc.)")
                s -= 20
            # Constructor injection preferred over field injection
            if "@Autowired" in converted and "private final" not in converted:
                issues.append("Field injection used — prefer constructor injection")
                s -= 10
            if not re.search(r'public\s+class\s+\w+', converted):
                issues.append("No public class declaration found")
                s -= 15

        elif target == TargetLanguage.REACT_JS:
            if not re.search(r"import React|from 'react'|from \"react\"", converted):
                issues.append("Missing React import")
                s -= 20
            if not re.search(r'const\s+\w+\s*(?::\s*React\.FC)?.*=.*(?:=>|\bfunction\b)', converted):
                issues.append("No functional component declaration found")
                s -= 20
            if "class " in converted and "extends React.Component" in converted:
                issues.append("Class component used — should be functional component")
                s -= 15
            if not re.search(r"export default\s+\w+", converted):
                issues.append("Missing default export")
                s -= 15

        return DimensionScore(
            dimension=Dimension.STRUCTURAL,
            score=max(0.0, s),
            weight=DIMENSION_WEIGHTS[Dimension.STRUCTURAL],
            issues=issues,
        )


class BehavioralScorer:
    """
    Checks runtime behavioral equivalence indicators:
    null safety, error handling, async correctness, data flow.
    """

    def score(
        self, source: str, converted: str, target: TargetLanguage
    ) -> DimensionScore:
        issues: list[str] = []
        s = 100.0

        if target == TargetLanguage.JAVA_SPRING:
            # Null safety
            if "??" in source and "Optional" not in converted and "orElse" not in converted:
                issues.append("Null-coalescing operator not translated to Optional")
                s -= 12
            # Error handling
            if "try" in source and "catch" in source:
                if "try" not in converted or "catch" not in converted:
                    issues.append("Try/catch block missing in converted code")
                    s -= 15
            # Async correctness
            if "async" in source and "await" in source:
                if "CompletableFuture" not in converted and "Mono" not in converted:
                    issues.append("Async/await not translated to Java async pattern")
                    s -= 15
            # Transaction handling
            if "transaction" in source.lower() and "@Transactional" not in converted:
                issues.append("Transaction context may be missing (@Transactional)")
                s -= 8

        elif target == TargetLanguage.REACT_JS:
            # State management
            if re.search(r'\bglobal\s+\w+|Public\s+\w+\s+As', source, re.I):
                if "useState" not in converted and "useContext" not in converted:
                    issues.append("Global/public VB6 state not mapped to React state")
                    s -= 15
            # Event handlers
            if re.search(r'_Click|_Change|_KeyPress', source, re.I):
                if "onClick" not in converted and "onChange" not in converted:
                    issues.append("VB6 event handlers not converted to React events")
                    s -= 15
            # Error boundaries
            if re.search(r'On Error|Try.*Catch', source, re.I):
                if "try" not in converted and "catch" not in converted:
                    issues.append("Error handling not converted")
                    s -= 10
            # API calls replacing COM/DB
            if re.search(r'ADODB|Recordset|OpenRecordset', source, re.I):
                if "fetch(" not in converted and "axios" not in converted:
                    issues.append("Database access not converted to API call")
                    s -= 12

        return DimensionScore(
            dimension=Dimension.BEHAVIORAL,
            score=max(0.0, s),
            weight=DIMENSION_WEIGHTS[Dimension.BEHAVIORAL],
            issues=issues,
        )


class CoverageScorer:
    """
    Estimates what % of source constructs appear (in some form) in the output.
    Heuristic: count identifiable source tokens and check for translation.
    """

    _METHOD_TOKENS = re.compile(
        r'\b(?:Sub|Function|void|public\s+\w+\s+\w+\s*\(|def\s+\w+)', re.I
    )

    def score(self, source: str, converted: str) -> DimensionScore:
        issues: list[str] = []

        source_methods  = len(self._METHOD_TOKENS.findall(source))
        converted_lines = len([l for l in converted.splitlines() if l.strip()])
        source_lines    = len([l for l in source.splitlines() if l.strip()])

        if source_lines == 0:
            return DimensionScore(
                dimension=Dimension.COVERAGE,
                score=100.0,
                weight=DIMENSION_WEIGHTS[Dimension.COVERAGE],
            )

        # Heuristic: converted should be at least 60% the length of source
        # (Java tends to be more verbose, React less so)
        ratio = converted_lines / source_lines
        if ratio < 0.4:
            issues.append(
                f"Converted output ({converted_lines} lines) is much shorter "
                f"than source ({source_lines} lines) — possible missing code"
            )
            s = 50.0
        elif ratio < 0.6:
            issues.append("Converted output significantly shorter than source")
            s = 70.0
        else:
            s = 100.0

        # Penalise stubs
        stub_count = converted.count("// AUTO-GENERATED STUB")
        if stub_count > 0:
            s -= min(40, stub_count * 20)
            issues.append(f"{stub_count} unconverted stub(s) remain")

        return DimensionScore(
            dimension=Dimension.COVERAGE,
            score=max(0.0, s),
            weight=DIMENSION_WEIGHTS[Dimension.COVERAGE],
            issues=issues,
        )


# ─── Accuracy Engine ──────────────────────────────────────────────────────────

class AccuracyEngine:
    """
    Computes multi-dimensional accuracy score and decides
    whether the conversion passes the 85% threshold.
    """

    def __init__(self):
        self._syntax     = SyntaxScorer()
        self._semantic   = SemanticScorer()
        self._structural = StructuralScorer()
        self._behavioral = BehavioralScorer()
        self._coverage   = CoverageScorer()

    def score(
        self,
        result: ConversionResult,
        iteration: int = 1,
    ) -> AccuracyReport:
        sf       = result.source_file
        source   = sf.raw_content  if sf else ""
        converted = result.converted_code or ""
        target   = result.target_language
        path     = sf.path if sf else "unknown"

        report = AccuracyReport(
            result_id=result.id,
            file_path=path,
            iteration=iteration,
        )

        report.dimension_scores = {
            Dimension.SYNTAX:     self._syntax.score(converted, target),
            Dimension.SEMANTIC:   self._semantic.score(source, converted, target),
            Dimension.STRUCTURAL: self._structural.score(converted, target),
            Dimension.BEHAVIORAL: self._behavioral.score(source, converted, target),
            Dimension.COVERAGE:   self._coverage.score(source, converted),
        }

        report.compute_overall()
        log.info("  Accuracy: %s — %s", path, report.summary_line())
        return report
