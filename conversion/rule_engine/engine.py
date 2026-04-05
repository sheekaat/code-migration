"""
Layer 3a — Rule Engine
Deterministic pattern-based code translation.
Handles ~60-70% of conversion without LLM usage.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from shared.models import (
    SourceFile, SourceLanguage, TargetLanguage,
    ConversionResult, ConversionStatus, ArchitecturalPattern,
)
from shared.config import get_logger

log = get_logger(__name__)


# ─── Rule Definition ─────────────────────────────────────────────────────────

@dataclass
class TranslationRule:
    name: str
    source_lang: SourceLanguage
    target_lang: TargetLanguage
    pattern: re.Pattern
    replacement: str | Callable[[re.Match], str]
    description: str = ""
    priority: int = 50       # lower = applied first

    def apply(self, code: str) -> tuple[str, bool]:
        """Returns (transformed_code, was_applied)."""
        if callable(self.replacement):
            result = self.pattern.sub(self.replacement, code)
        else:
            result = self.pattern.sub(self.replacement, code)
        return result, result != code


# ─── C# → Java Spring Boot Rules ─────────────────────────────────────────────

CSHARP_TO_JAVA_RULES: list[TranslationRule] = [

    # ── Annotations ──────────────────────────────────────────────────────────
    TranslationRule(
        name="http_get_mapping",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[HttpGet\("?([^")]*)"?\)\]'),
        replacement=lambda m: f'@GetMapping("{m.group(1)}")' if m.group(1) else "@GetMapping",
        description="[HttpGet] → @GetMapping",
    ),
    TranslationRule(
        name="http_post_mapping",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[HttpPost\("?([^")]*)"?\)\]'),
        replacement=lambda m: f'@PostMapping("{m.group(1)}")' if m.group(1) else "@PostMapping",
        description="[HttpPost] → @PostMapping",
    ),
    TranslationRule(
        name="http_put_mapping",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[HttpPut\("?([^")]*)"?\)\]'),
        replacement=lambda m: f'@PutMapping("{m.group(1)}")' if m.group(1) else "@PutMapping",
        description="[HttpPut] → @PutMapping",
    ),
    TranslationRule(
        name="http_delete_mapping",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[HttpDelete\("?([^")]*)"?\)\]'),
        replacement=lambda m: f'@DeleteMapping("{m.group(1)}")' if m.group(1) else "@DeleteMapping",
        description="[HttpDelete] → @DeleteMapping",
    ),
    TranslationRule(
        name="route_annotation",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[Route\("([^"]*)"\)\]'),
        replacement=r'@RequestMapping("\1")',
        description="[Route] → @RequestMapping",
    ),
    TranslationRule(
        name="api_controller",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[ApiController\]'),
        replacement="@RestController",
        description="[ApiController] → @RestController",
    ),
    TranslationRule(
        name="authorize_annotation",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[Authorize\]'),
        replacement="@PreAuthorize(\"isAuthenticated()\")",
        description="[Authorize] → @PreAuthorize",
    ),
    TranslationRule(
        name="from_body",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[FromBody\]\s+'),
        replacement="@RequestBody ",
        description="[FromBody] → @RequestBody",
    ),
    TranslationRule(
        name="from_route",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[FromRoute\]\s+'),
        replacement="@PathVariable ",
        description="[FromRoute] → @PathVariable",
    ),
    TranslationRule(
        name="from_query",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\[FromQuery\]\s+'),
        replacement="@RequestParam ",
        description="[FromQuery] → @RequestParam",
    ),

    # ── Type mappings ─────────────────────────────────────────────────────────
    TranslationRule(
        name="string_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bstring\b'),
        replacement="String",
        description="string → String",
    ),
    TranslationRule(
        name="bool_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bbool\b'),
        replacement="boolean",
        description="bool → boolean",
    ),
    TranslationRule(
        name="int_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bint\b'),
        replacement="int",
        description="int → int (no-op, kept for explicit mapping)",
    ),
    TranslationRule(
        name="decimal_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bdecimal\b'),
        replacement="BigDecimal",
        description="decimal → BigDecimal",
    ),
    TranslationRule(
        name="datetime_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bDateTime\b'),
        replacement="LocalDateTime",
        description="DateTime → LocalDateTime",
    ),
    TranslationRule(
        name="list_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bList<'),
        replacement="List<",
        description="List<T> → List<T> (no-op, import changes)",
    ),
    TranslationRule(
        name="dictionary_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bDictionary<(\w+),\s*(\w+)>'),
        replacement=r'Map<\1, \2>',
        description="Dictionary<K,V> → Map<K,V>",
    ),
    TranslationRule(
        name="ienumerable_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bIEnumerable<(\w+)>'),
        replacement=r'Iterable<\1>',
        description="IEnumerable<T> → Iterable<T>",
    ),
    TranslationRule(
        name="task_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bTask<(\w+)>'),
        replacement=r'CompletableFuture<\1>',
        description="Task<T> → CompletableFuture<T>",
    ),
    TranslationRule(
        name="nullable_type",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bNullable<(\w+)>'),
        replacement=r'Optional<\1>',
        description="Nullable<T> → Optional<T>",
    ),

    # ── LINQ → Stream API ────────────────────────────────────────────────────
    TranslationRule(
        name="linq_where",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\.Where\('),
        replacement=".stream().filter(",
        description=".Where( → .stream().filter(",
    ),
    TranslationRule(
        name="linq_select",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\.Select\('),
        replacement=".map(",
        description=".Select( → .map(",
    ),
    TranslationRule(
        name="linq_first_or_default",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\.FirstOrDefault\(\)'),
        replacement=".findFirst().orElse(null)",
        description=".FirstOrDefault() → .findFirst().orElse(null)",
    ),
    TranslationRule(
        name="linq_to_list",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\.ToList\(\)'),
        replacement=".collect(Collectors.toList())",
        description=".ToList() → .collect(Collectors.toList())",
    ),
    TranslationRule(
        name="linq_any",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\.Any\('),
        replacement=".stream().anyMatch(",
        description=".Any( → .stream().anyMatch(",
    ),
    TranslationRule(
        name="linq_count",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\.Count\(\)'),
        replacement=".size()",
        description=".Count() → .size()",
    ),

    # ── Class modifiers ───────────────────────────────────────────────────────
    TranslationRule(
        name="class_declaration",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bpublic\s+class\s+(\w+)\s*:\s*ControllerBase'),
        replacement=r'@RestController\npublic class \1',
        description="class : ControllerBase → @RestController class",
    ),
    TranslationRule(
        name="override_keyword",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\boverride\b'),
        replacement="@Override\n    ",
        description="override → @Override",
    ),
    TranslationRule(
        name="var_keyword",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\bvar\b'),
        replacement="var",   # Java 10+ supports var
        description="var → var (Java 10+ compatible)",
    ),

    # ── String methods ────────────────────────────────────────────────────────
    TranslationRule(
        name="string_is_null_or_empty",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'String\.IsNullOrEmpty\((\w+)\)'),
        replacement=r'(\1 == null || \1.isEmpty())',
        description="String.IsNullOrEmpty → null check",
    ),
    TranslationRule(
        name="string_format",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'String\.Format\('),
        replacement="String.format(",
        description="String.Format → String.format",
    ),
    TranslationRule(
        name="console_writeline",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'Console\.WriteLine\('),
        replacement="System.out.println(",
        description="Console.WriteLine → System.out.println",
    ),

    # ── Exception handling ────────────────────────────────────────────────────
    TranslationRule(
        name="exception_message",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'\.Message\b'),
        replacement=".getMessage()",
        description=".Message → .getMessage()",
    ),
    TranslationRule(
        name="throw_new_exception",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'throw\s+new\s+Exception\('),
        replacement="throw new RuntimeException(",
        description="throw new Exception → throw new RuntimeException",
    ),

    # ── Imports ───────────────────────────────────────────────────────────────
    TranslationRule(
        name="remove_using",
        source_lang=SourceLanguage.CSHARP,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'^using\s+[\w.]+;\n?', re.M),
        replacement="",
        description="Remove C# using statements (Java imports generated separately)",
        priority=1,
    ),
]


# ─── VB6 → ReactJS Rules ─────────────────────────────────────────────────────

VB6_TO_REACT_RULES: list[TranslationRule] = [
    TranslationRule(
        name="sub_to_function",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'(?:Public|Private)?\s*Sub\s+(\w+)\s*\(([^)]*)\)', re.I),
        replacement=r'function \1(\2) {',
        description="Sub → function",
    ),
    TranslationRule(
        name="end_sub",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'^End Sub\s*$', re.M | re.I),
        replacement="}",
        description="End Sub → }",
    ),
    TranslationRule(
        name="function_to_function",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'(?:Public|Private)?\s*Function\s+(\w+)\s*\(([^)]*)\)\s+As\s+\w+', re.I),
        replacement=r'function \1(\2) {',
        description="Function...As Type → function",
    ),
    TranslationRule(
        name="end_function",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'^End Function\s*$', re.M | re.I),
        replacement="}",
        description="End Function → }",
    ),
    TranslationRule(
        name="dim_statement",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'Dim\s+(\w+)\s+As\s+\w+', re.I),
        replacement=r'let \1',
        description="Dim x As Type → let x",
    ),
    TranslationRule(
        name="if_then",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'\bIf\s+(.+)\s+Then\s*$', re.M | re.I),
        replacement=r'if (\1) {',
        description="If...Then → if (...) {",
    ),
    TranslationRule(
        name="else_clause",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'^Else\s*$', re.M | re.I),
        replacement="} else {",
        description="Else → } else {",
    ),
    TranslationRule(
        name="end_if",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'^End If\s*$', re.M | re.I),
        replacement="}",
        description="End If → }",
    ),
    TranslationRule(
        name="for_loop",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'For\s+(\w+)\s*=\s*(\S+)\s+To\s+(\S+)', re.I),
        replacement=r'for (let \1 = \2; \1 <= \3; \1++) {',
        description="For i = 0 To N → for loop",
    ),
    TranslationRule(
        name="next_statement",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'^Next\s*\w*\s*$', re.M | re.I),
        replacement="}",
        description="Next → }",
    ),
    TranslationRule(
        name="string_concat",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'\s*&\s*'),
        replacement=" + ",
        description="& (string concat) → +",
    ),
    TranslationRule(
        name="msgbox",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'MsgBox\s+', re.I),
        replacement=r'alert(',
        description="MsgBox → alert",
    ),
    TranslationRule(
        name="debug_print",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'Debug\.Print\s+', re.I),
        replacement="console.log(",
        description="Debug.Print → console.log",
    ),
    TranslationRule(
        name="vb_true_false",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'\bTrue\b'),
        replacement="true",
        description="True → true",
    ),
    TranslationRule(
        name="vb_false",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'\bFalse\b'),
        replacement="false",
        description="False → false",
    ),
    TranslationRule(
        name="vb_nothing",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r'\bNothing\b'),
        replacement="null",
        description="Nothing → null",
    ),
    TranslationRule(
        name="vb_comments",
        source_lang=SourceLanguage.VB6,
        target_lang=TargetLanguage.REACT_JS,
        pattern=re.compile(r"^'(.*)$", re.M),
        replacement=r'//\1',
        description="' comment → // comment",
    ),
]


# ─── Tibco BW → Spring Integration stubs ─────────────────────────────────────

TIBCO_TO_SPRING_RULES: list[TranslationRule] = [
    TranslationRule(
        name="http_receiver_stub",
        source_lang=SourceLanguage.TIBCO_BW,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'<pd:type>com\.tibco\.pe\.core\.HTTPReceiveEventSource</pd:type>', re.I),
        replacement="// @RestController endpoint (see generated stub)",
        description="TIBCO HTTPReceive → Spring @RestController stub",
    ),
    TranslationRule(
        name="publish_stub",
        source_lang=SourceLanguage.TIBCO_BW,
        target_lang=TargetLanguage.JAVA_SPRING,
        pattern=re.compile(r'<pd:type>com\.tibco\.pe\.core\.PublishToSubject</pd:type>', re.I),
        replacement="// kafkaTemplate.send(topic, message); (see generated stub)",
        description="TIBCO Publish → Kafka send stub",
    ),
]


# ─── Rule Engine ─────────────────────────────────────────────────────────────

class RuleEngine:
    def __init__(self, config: dict):
        self.config = config
        self._rules: dict[tuple[SourceLanguage, TargetLanguage], list[TranslationRule]] = {
            (SourceLanguage.CSHARP,    TargetLanguage.JAVA_SPRING): sorted(CSHARP_TO_JAVA_RULES, key=lambda r: r.priority),
            (SourceLanguage.ASPNET,    TargetLanguage.JAVA_SPRING): sorted(CSHARP_TO_JAVA_RULES, key=lambda r: r.priority),
            (SourceLanguage.VB6,       TargetLanguage.REACT_JS):    sorted(VB6_TO_REACT_RULES, key=lambda r: r.priority),
            (SourceLanguage.TIBCO_BW,  TargetLanguage.JAVA_SPRING): sorted(TIBCO_TO_SPRING_RULES, key=lambda r: r.priority),
            (SourceLanguage.WPF_XAML,  TargetLanguage.REACT_JS):    [],  # Handled by LLM
        }

    def convert(self, sf: SourceFile, target: TargetLanguage) -> ConversionResult:
        rules = self._rules.get((sf.language, target), [])
        if not rules:
            return ConversionResult(
                source_file=sf,
                target_language=target,
                status=ConversionStatus.PENDING,
                confidence=0.0,
            )

        code = sf.raw_content
        applied: list[str] = []

        for rule in rules:
            transformed, was_applied = rule.apply(code)
            if was_applied:
                code = transformed
                applied.append(rule.name)

        coverage = len(applied) / max(len(rules), 1)
        confidence = min(0.95, 0.4 + coverage * 0.55)

        return ConversionResult(
            source_file=sf,
            target_language=target,
            converted_code=code,
            status=ConversionStatus.RULE_APPLIED,
            confidence=confidence,
            rules_applied=applied,
        )

    def list_rules(self, source: SourceLanguage, target: TargetLanguage) -> list[str]:
        return [r.name for r in self._rules.get((source, target), [])]
