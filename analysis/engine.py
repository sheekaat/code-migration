"""
Layer 2 — Analysis Engine
Parses source files into UIR, classifies architectural patterns,
scores complexity, and builds the dependency graph.
"""

from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from typing import Optional

from shared.models import (
    SourceFile, SourceLanguage, UIRNode,
    ArchitecturalPattern, ComplexityTier,
    DependencyGraph, WorkspaceManifest,
)
from shared.config import get_logger

log = get_logger(__name__)


# ─── Pattern detection rules ─────────────────────────────────────────────────

_CSHARP_PATTERNS: list[tuple[re.Pattern, ArchitecturalPattern]] = [
    (re.compile(r"IRepository|Repository\b|DbContext", re.I),  ArchitecturalPattern.REPOSITORY),
    (re.compile(r"\[ApiController\]|\[Route\]|ControllerBase", re.I), ArchitecturalPattern.CONTROLLER),
    (re.compile(r"IService\b|Service\b.*:.*I\w+Service", re.I), ArchitecturalPattern.SERVICE),
    (re.compile(r"class\s+\w+Dto\b|class\s+\w+ViewModel\b", re.I), ArchitecturalPattern.DTO),
    (re.compile(r"\[Table\]|Entity\b|DbSet<", re.I), ArchitecturalPattern.ENTITY),
    (re.compile(r"IMiddleware|RequestDelegate", re.I), ArchitecturalPattern.MIDDLEWARE),
    (re.compile(r"ICommand\b|CommandHandler", re.I), ArchitecturalPattern.COMMAND),
]

_VB6_PATTERNS: list[tuple[re.Pattern, ArchitecturalPattern]] = [
    (re.compile(r"Form_Load|Form_Unload|cmdOK|txtInput", re.I), ArchitecturalPattern.UI_FORM),
    (re.compile(r"ADODB\.|Recordset|OpenRecordset", re.I), ArchitecturalPattern.DATA_ACCESS),
    (re.compile(r"Class_Initialize|Class_Terminate", re.I), ArchitecturalPattern.SERVICE),
]

_TIBCO_PATTERNS: list[tuple[re.Pattern, ArchitecturalPattern]] = [
    (re.compile(r"publish|subscribe|PublishToTopic", re.I), ArchitecturalPattern.PUBSUB),
    (re.compile(r"requestReply|HTTPRequest|HTTPResponse", re.I), ArchitecturalPattern.REQUEST_REPLY),
    (re.compile(r"receive|Receive|accept", re.I), ArchitecturalPattern.ESB_ROUTING),
]

_XAML_PATTERNS: list[tuple[re.Pattern, ArchitecturalPattern]] = [
    (re.compile(r"INotifyPropertyChanged|ViewModel|Binding", re.I), ArchitecturalPattern.MVVM),
    (re.compile(r"<Window|<UserControl|<Page", re.I), ArchitecturalPattern.UI_FORM),
    (re.compile(r"ICommand|RelayCommand|DelegateCommand", re.I), ArchitecturalPattern.COMMAND),
]

_PATTERN_RULES: dict[SourceLanguage, list[tuple[re.Pattern, ArchitecturalPattern]]] = {
    SourceLanguage.CSHARP:   _CSHARP_PATTERNS,
    SourceLanguage.ASPNET:   _CSHARP_PATTERNS,
    SourceLanguage.VB6:      _VB6_PATTERNS,
    SourceLanguage.TIBCO_BW: _TIBCO_PATTERNS,
    SourceLanguage.WPF_XAML: _XAML_PATTERNS,
}


# ─── AST Parsers ─────────────────────────────────────────────────────────────

class CSharpParser:
    """Lightweight regex-based C# → UIR parser."""

    CLASS_RE   = re.compile(r"(?:public|internal|private)?\s*(?:abstract\s+)?class\s+(\w+)")
    METHOD_RE  = re.compile(
        r"(?:(?:public|private|protected|internal|static|async|override|virtual)\s+)+"
        r"(\w[\w<>\[\],\s]*?)\s+(\w+)\s*\(([^)]*)\)"
    )
    IMPORT_RE  = re.compile(r"^using\s+([\w.]+);", re.M)
    ANNOT_RE   = re.compile(r"\[(\w+(?:\([^)]*\))?)\]")

    def parse(self, sf: SourceFile) -> UIRNode:
        root = UIRNode(kind="file", name=sf.path, source_language=sf.language)
        src = sf.raw_content

        for m in self.IMPORT_RE.finditer(src):
            root.children.append(UIRNode(kind="import", name=m.group(1)))

        for m in self.CLASS_RE.finditer(src):
            cls_node = UIRNode(kind="class", name=m.group(1), source_language=sf.language)
            annotations = self.ANNOT_RE.findall(src[max(0, m.start()-200):m.start()])
            cls_node.annotations = annotations
            root.children.append(cls_node)

        for m in self.METHOD_RE.finditer(src):
            method_node = UIRNode(
                kind="method",
                name=m.group(2),
                return_type=m.group(1).strip(),
                source_language=sf.language,
            )
            params_raw = m.group(3)
            method_node.parameters = _parse_params(params_raw)
            root.children.append(method_node)

        return root


class VB6Parser:
    """Lightweight VB6 → UIR parser."""

    SUB_RE  = re.compile(r"(?:Public|Private)?\s*Sub\s+(\w+)\s*\(([^)]*)\)", re.I)
    FUNC_RE = re.compile(r"(?:Public|Private)?\s*Function\s+(\w+)\s*\(([^)]*)\)\s+As\s+(\w+)", re.I)
    DIM_RE  = re.compile(r"Dim\s+(\w+)\s+As\s+(\w+)", re.I)

    def parse(self, sf: SourceFile) -> UIRNode:
        root = UIRNode(kind="file", name=sf.path, source_language=sf.language)
        src = sf.raw_content

        for m in self.SUB_RE.finditer(src):
            root.children.append(UIRNode(
                kind="method", name=m.group(1),
                return_type="void", source_language=sf.language,
                parameters=_parse_vb_params(m.group(2)),
            ))

        for m in self.FUNC_RE.finditer(src):
            root.children.append(UIRNode(
                kind="method", name=m.group(1),
                return_type=m.group(3), source_language=sf.language,
                parameters=_parse_vb_params(m.group(2)),
            ))

        return root


class TibcoBWParser:
    """Parses Tibco BW XML process files into UIR."""

    def parse(self, sf: SourceFile) -> UIRNode:
        root = UIRNode(kind="file", name=sf.path, source_language=sf.language)
        try:
            tree = ET.fromstring(sf.raw_content)
        except ET.ParseError as e:
            log.warning("XML parse error in %s: %s", sf.path, e)
            return root

        ns = {"bw": "http://xmlns.tibco.com/bw/process/2003"}
        for activity in tree.iter():
            tag = activity.tag.split("}")[-1]
            if tag in ("activity", "transition", "process"):
                node = UIRNode(
                    kind=tag,
                    name=activity.get("name", ""),
                    source_language=sf.language,
                    metadata={
                        "type": activity.get("type", ""),
                        "x": activity.get("x", ""),
                        "y": activity.get("y", ""),
                    },
                )
                root.children.append(node)
        return root


class XAMLParser:
    """Parses XAML/WPF files into UIR."""

    BINDING_RE  = re.compile(r"Binding\s+(\w+)|{Binding\s+(\w+)}", re.I)
    COMMAND_RE  = re.compile(r"Command=\{Binding\s+(\w+)\}", re.I)
    CONTROL_RE  = re.compile(r"<(Button|TextBox|DataGrid|ListBox|ComboBox|CheckBox|Label)[^>]*>", re.I)

    def parse(self, sf: SourceFile) -> UIRNode:
        root = UIRNode(kind="file", name=sf.path, source_language=sf.language)
        src = sf.raw_content

        for m in self.BINDING_RE.finditer(src):
            prop = m.group(1) or m.group(2)
            root.children.append(UIRNode(kind="binding", name=prop, source_language=sf.language))

        for m in self.COMMAND_RE.finditer(src):
            root.children.append(UIRNode(kind="command", name=m.group(1), source_language=sf.language))

        for m in self.CONTROL_RE.finditer(src):
            root.children.append(UIRNode(kind="ui_control", name=m.group(1), source_language=sf.language))

        return root


_PARSERS: dict[SourceLanguage, object] = {
    SourceLanguage.CSHARP:   CSharpParser(),
    SourceLanguage.ASPNET:   CSharpParser(),
    SourceLanguage.VB6:      VB6Parser(),
    SourceLanguage.TIBCO_BW: TibcoBWParser(),
    SourceLanguage.WPF_XAML: XAMLParser(),
}


# ─── Complexity Scorer ───────────────────────────────────────────────────────

_BRANCH_PATTERNS = re.compile(
    r"\b(if|else|elif|for|foreach|while|switch|case|catch|&&|\|\|)\b"
)


def compute_complexity(sf: SourceFile, config: dict) -> tuple[int, ComplexityTier]:
    """Cyclomatic complexity estimate + tier assignment."""
    branches = len(_BRANCH_PATTERNS.findall(sf.raw_content))
    score = 1 + branches
    red   = config.get("analysis", {}).get("complexity_red_threshold", 20)
    amber = config.get("analysis", {}).get("complexity_amber_threshold", 10)
    if score >= red:
        return score, ComplexityTier.RED
    if score >= amber:
        return score, ComplexityTier.AMBER
    return score, ComplexityTier.GREEN


# ─── Dependency Graph Builder ────────────────────────────────────────────────

_CSHARP_USING   = re.compile(r"^using\s+([\w.]+);", re.M)
_VB6_REFERENCE  = re.compile(r"'#Reference\s+([\w.]+)", re.M)
_TIBCO_CALL     = re.compile(r'callProcess\s+name="([^"]+)"', re.I)


def build_dependency_graph(files: list[SourceFile]) -> DependencyGraph:
    graph = DependencyGraph()
    path_index = {f.path: f for f in files}

    for f in files:
        graph.add_file(f)

    for f in files:
        refs: list[str] = []
        if f.language in (SourceLanguage.CSHARP, SourceLanguage.ASPNET):
            refs = _CSHARP_USING.findall(f.raw_content)
        elif f.language == SourceLanguage.VB6:
            refs = _VB6_REFERENCE.findall(f.raw_content)
        elif f.language == SourceLanguage.TIBCO_BW:
            refs = _TIBCO_CALL.findall(f.raw_content)

        for ref in refs:
            # Find matching file path by name
            for dep_path in path_index:
                if ref.replace(".", "/") in dep_path or dep_path.endswith(ref):
                    graph.add_dependency(f.path, dep_path)
                    break

    return graph


# ─── Pattern Classifier ──────────────────────────────────────────────────────

def classify_pattern(sf: SourceFile) -> ArchitecturalPattern:
    rules = _PATTERN_RULES.get(sf.language, [])
    for pattern_re, arch_pattern in rules:
        if pattern_re.search(sf.raw_content):
            return arch_pattern
    return ArchitecturalPattern.UNKNOWN


# ─── Analysis Pipeline ───────────────────────────────────────────────────────

def analyse(manifest: WorkspaceManifest, config: dict) -> WorkspaceManifest:
    """Run the full analysis pass on a WorkspaceManifest."""
    log.info("Running analysis on %d files", len(manifest.files))

    for sf in manifest.files:
        # Parse to UIR
        parser = _PARSERS.get(sf.language)
        if parser:
            sf.uir = parser.parse(sf)

        # Classify pattern
        sf.pattern = classify_pattern(sf)

        # Score complexity
        sf.complexity_score, sf.complexity_tier = compute_complexity(sf, config)

    # Build dependency graph
    manifest.dependency_graph = build_dependency_graph(manifest.files)

    tier_counts = {t.value: 0 for t in ComplexityTier}
    for f in manifest.files:
        tier_counts[f.complexity_tier.value] += 1

    manifest.stats["analysis"] = {
        "complexity_tiers": tier_counts,
        "patterns_found": _count_patterns(manifest.files),
    }
    log.info("Analysis complete. Tiers: %s", tier_counts)
    return manifest


def _count_patterns(files: list[SourceFile]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in files:
        k = f.pattern.value
        counts[k] = counts.get(k, 0) + 1
    return counts


# ─── Param helpers ───────────────────────────────────────────────────────────

def _parse_params(raw: str) -> list[dict[str, str]]:
    params = []
    for p in raw.split(","):
        p = p.strip()
        if not p:
            continue
        parts = p.split()
        if len(parts) >= 2:
            params.append({"type": parts[-2], "name": parts[-1]})
        elif parts:
            params.append({"type": "unknown", "name": parts[0]})
    return params


def _parse_vb_params(raw: str) -> list[dict[str, str]]:
    params = []
    for p in raw.split(","):
        p = p.strip()
        m = re.match(r"(\w+)\s+As\s+(\w+)", p, re.I)
        if m:
            params.append({"type": m.group(2), "name": m.group(1)})
    return params
