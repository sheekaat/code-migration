"""
Shared domain models used across all platform layers.
These form the Unified Intermediate Representation (UIR).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import uuid


# ─── Enumerations ────────────────────────────────────────────────────────────

class SourceLanguage(str, Enum):
    CSHARP      = "csharp"
    VB6         = "vb6"
    TIBCO_BW    = "tibco_bw"
    WPF_XAML    = "wpf_xaml"
    ASPNET      = "aspnet"


class TargetLanguage(str, Enum):
    JAVA_SPRING = "java_spring"
    REACT_JS    = "react_js"


class ComplexityTier(str, Enum):
    GREEN  = "green"   # rule-engine only
    AMBER  = "amber"   # rule-engine + LLM validation
    RED    = "red"     # full LLM + mandatory human review


class ConversionStatus(str, Enum):
    PENDING       = "pending"
    IN_PROGRESS   = "in_progress"
    RULE_APPLIED  = "rule_applied"
    LLM_CONVERTED = "llm_converted"
    VALIDATED     = "validated"
    NEEDS_REVIEW  = "needs_review"
    APPROVED      = "approved"
    FAILED        = "failed"


class ArchitecturalPattern(str, Enum):
    REPOSITORY          = "repository"
    SERVICE             = "service"
    CONTROLLER          = "controller"
    DTO                 = "dto"
    ENTITY              = "entity"
    FACTORY             = "factory"
    OBSERVER            = "observer"
    COMMAND             = "command"
    MVC                 = "mvc"
    MVVM                = "mvvm"
    ESB_ROUTING         = "esb_routing"
    PUBSUB              = "pubsub"
    REQUEST_REPLY       = "request_reply"
    UI_FORM             = "ui_form"
    DATA_ACCESS         = "data_access"
    MIDDLEWARE          = "middleware"
    UNKNOWN             = "unknown"


# ─── Core AST / UIR nodes ────────────────────────────────────────────────────

@dataclass
class UIRNode:
    """
    Unified Intermediate Representation node.
    Language-agnostic representation of a code construct.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = ""                    # e.g. "class", "method", "field", "import"
    name: str = ""
    source_language: Optional[SourceLanguage] = None
    annotations: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)   # public, static, async, etc.
    return_type: Optional[str] = None
    parameters: list[dict[str, str]] = field(default_factory=list)
    body: Optional[str] = None        # raw source body (for LLM conversion)
    children: list["UIRNode"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceFile:
    """Represents one source file from the legacy codebase."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    path: str = ""
    language: Optional[SourceLanguage] = None
    raw_content: str = ""
    uir: Optional[UIRNode] = None              # Parsed IR
    pattern: ArchitecturalPattern = ArchitecturalPattern.UNKNOWN
    complexity_score: int = 0
    complexity_tier: ComplexityTier = ComplexityTier.GREEN
    dependencies: list[str] = field(default_factory=list)   # other file paths
    line_count: int = 0
    char_count: int = 0


@dataclass
class ConversionChunk:
    """A bounded unit of code sent to the LLM for conversion."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_file_id: str = ""
    chunk_index: int = 0
    total_chunks: int = 1
    source_code: str = ""
    context_summary: str = ""         # compact summary of prior chunks
    conversion_manifest: str = ""     # shared rules / naming conventions
    converted_code: Optional[str] = None
    confidence: float = 0.0
    tokens_used: int = 0


@dataclass
class ConversionResult:
    """Full conversion output for one source file."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_file: Optional[SourceFile] = None
    target_language: Optional[TargetLanguage] = None
    target_path: str = ""
    converted_code: str = ""
    status: ConversionStatus = ConversionStatus.PENDING
    confidence: float = 0.0
    rules_applied: list[str] = field(default_factory=list)
    llm_chunks_used: int = 0
    total_tokens: int = 0
    validation_passed: bool = False
    review_notes: str = ""
    reviewer: Optional[str] = None


@dataclass
class DependencyGraph:
    """Directed graph of source file dependencies."""
    nodes: dict[str, SourceFile] = field(default_factory=dict)     # path → SourceFile
    edges: dict[str, list[str]] = field(default_factory=dict)      # path → [dep paths]

    def add_file(self, f: SourceFile) -> None:
        self.nodes[f.path] = f
        if f.path not in self.edges:
            self.edges[f.path] = []

    def add_dependency(self, from_path: str, to_path: str) -> None:
        self.edges.setdefault(from_path, []).append(to_path)

    def topological_order(self) -> list[str]:
        """Return file paths in dependency order (leaves first)."""
        visited: set[str] = set()
        order: list[str] = []

        def visit(path: str) -> None:
            if path in visited:
                return
            visited.add(path)
            for dep in self.edges.get(path, []):
                visit(dep)
            order.append(path)

        for path in self.nodes:
            visit(path)
        return order


@dataclass
class WorkspaceManifest:
    """
    Top-level workspace object that travels through all pipeline stages.
    Created by ingestion, enriched by each subsequent layer.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    repo_path: str = ""
    source_language: Optional[SourceLanguage] = None
    target_language: Optional[TargetLanguage] = None
    files: list[SourceFile] = field(default_factory=list)
    dependency_graph: Optional[DependencyGraph] = None
    conversion_results: list[ConversionResult] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    conversion_manifest: str = ""     # shared context doc for LLM calls

    def get_file_by_path(self, path: str) -> Optional[SourceFile]:
        return next((f for f in self.files if f.path == path), None)

    def summary(self) -> dict[str, Any]:
        tiers = {t: 0 for t in ComplexityTier}
        for f in self.files:
            tiers[f.complexity_tier] += 1
        return {
            "total_files": len(self.files),
            "complexity": {t.value: c for t, c in tiers.items()},
            "patterns": _count_patterns(self.files),
        }


def _count_patterns(files: list[SourceFile]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in files:
        k = f.pattern.value
        counts[k] = counts.get(k, 0) + 1
    return counts
