"""Layer 3b — LLM Converter
Handles complex code conversion using the Gemini API.
Uses chunked processing, context anchoring, and pattern caching.
"""

from __future__ import annotations
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

from shared.models import (
    SourceFile, SourceLanguage, TargetLanguage,
    ConversionResult, ConversionStatus, ConversionChunk,
    ComplexityTier,
)
from shared.config import get_logger
from conversion.component_templates import get_conversion_template
from ingestion.file_type_registry import ComponentInfo

log = get_logger(__name__)


# ─── Conversion Manifest (shared context injected into every prompt) ──────────

_BASE_MANIFEST = """
# Conversion Manifest
You are converting legacy code to modern {target}. Follow these rules strictly:

## Naming Conventions
- Classes: PascalCase
- Methods/Variables: camelCase (Java) / camelCase (JS)
- Constants: UPPER_SNAKE_CASE
- Packages (Java): com.company.{{module}}

## Established Patterns
{established_patterns}

## Target Framework
{target_specifics}

## Output Rules
- Return ONLY the converted code, no explanation
- Preserve all comments (translated to target syntax)
- Add TODO comments for constructs that need manual review
- Maintain original logic exactly — do not simplify or optimize
"""

_JAVA_SPRING_SPECIFICS = """
- Spring Boot 3.x / Java 17
- Use @RestController, @Service, @Repository stereotypes
- Dependency injection via constructor (not @Autowired field injection)
- Use Optional<T> for nullable returns
- Exceptions: throw custom RuntimeException subclasses
- Persistence: Spring Data JPA with @Entity, @Repository
- Use Lombok @Data, @Builder, @NoArgsConstructor where appropriate

## Business Logic Translation Rules
- Preserve ALL business rules exactly — don't simplify conditional logic
- Convert all validation rules to bean validation annotations or explicit checks
- Maintain exact calculation logic — don't optimize or change math operations
- Preserve error handling flow — convert VB6 On Error to try/catch with same behavior
- Keep transaction boundaries — use @Transactional for atomic operations
- Preserve data access patterns — convert ADODB to JPA but keep query logic
"""

_REACT_SPECIFICS = """
- React 18 with functional components and hooks
- TypeScript preferred (use .tsx extension)
- State: useState / useReducer for local, Context API for shared
- Side effects: useEffect with proper dependency arrays
- Forms: controlled components (value + onChange)
- API calls: async/await with fetch or axios inside useEffect
- Styling: CSS modules or Tailwind utility classes
- No class components — functional only

## Business Logic Translation Rules
- Preserve ALL business rules exactly — don't simplify conditional logic
- Maintain exact calculation logic in event handlers
- Preserve form validation rules exactly
- Keep data transformation logic — don't optimize unless obvious
- Preserve conditional rendering logic based on state
- Maintain data flow patterns — convert VB6 data binding to React state
"""

_TARGET_SPECIFICS: dict[TargetLanguage, str] = {
    TargetLanguage.JAVA_SPRING: _JAVA_SPRING_SPECIFICS,
    TargetLanguage.REACT_JS:    _REACT_SPECIFICS,
}

_TARGET_NAMES: dict[TargetLanguage, str] = {
    TargetLanguage.JAVA_SPRING: "Java Spring Boot 3",
    TargetLanguage.REACT_JS:    "ReactJS 18 (TypeScript)",
}

# Source-specific conversion instructions
_SOURCE_HINTS: dict[SourceLanguage, str] = {
    SourceLanguage.VB6: """
## VB6 Specific Instructions
- VB6 forms → React functional components
- Form_Load → useEffect([], init)
- Global variables → useState or useContext
- ADODB Recordset → fetch() API calls to backend (keep query logic exact)
- VB6 error handling (On Error GoTo) → try/catch with EXACT same behavior
- MsgBox → custom Modal component or window.alert
- COM object calls → REST API calls (add TODO markers)

## Business Logic Preservation (CRITICAL)
- Preserve ALL If/Then/Else logic exactly — don't simplify
- Keep For/While loop boundaries and step values exact
- Preserve ALL variable assignments and calculations
- Maintain ADODB Recordset operations (MoveFirst, MoveNext, EOF) in converted form
- Keep transaction begin/commit/rollback logic
- Preserve ALL validation checks (field length, required, format)
- Convert Date type to proper date handling (not string)
- Maintain Currency/Decimal precision in calculations
""",
    SourceLanguage.CSHARP: """
## C# Specific Instructions
- Using statements → Java imports (map namespaces)
- Properties (get/set) → Java getters/setters or Lombok
- Events/delegates → Spring ApplicationEvent or callbacks
- LINQ → Java Stream API
- async/await → CompletableFuture
- IDisposable/using → try-with-resources
""",
    SourceLanguage.TIBCO_BW: """
## Tibco BW Specific Instructions
- Process activities → Spring Integration flows or @Service methods
- HTTP Receiver → @RestController with @PostMapping
- Publish to Subject → KafkaTemplate.send() or Spring Events
- Call Process → service method invocation
- Map activity → data transformation method
- JDBC Query → Spring Data JPA repository call
- Log activity → SLF4J logger.info/error
""",
    SourceLanguage.WPF_XAML: """
## WPF/XAML Specific Instructions
- XAML → JSX (React component return value)
- Data bindings → React state + props
- INotifyPropertyChanged → useState hook
- ICommand → event handler functions (onClick, onChange)
- DataGrid → HTML table or React table library
- ResourceDictionary → CSS variables or theme context
- Converters → pure functions
- Styles/Templates → CSS classes or inline styles
""",
}


# ─── Pattern Cache ────────────────────────────────────────────────────────────

@dataclass
class PatternCache:
    """Stores converted patterns to avoid repeated LLM calls."""
    _cache: dict[str, str] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def _key(self, code: str, source: SourceLanguage, target: TargetLanguage) -> str:
        h = hashlib.md5(f"{source.value}:{target.value}:{code}".encode()).hexdigest()
        return h

    def get(self, code: str, source: SourceLanguage, target: TargetLanguage) -> Optional[str]:
        k = self._key(code, source, target)
        if k in self._cache:
            self.hits += 1
            return self._cache[k]
        self.misses += 1
        return None

    def set(self, code: str, source: SourceLanguage, target: TargetLanguage, result: str) -> None:
        k = self._key(code, source, target)
        self._cache[k] = result

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


# ─── LLM Converter ───────────────────────────────────────────────────────────

class LLMConverter:
    def __init__(self, config: dict):
        self.config = config
        self.cache = PatternCache()
        self.established_patterns: list[str] = []
        self.total_tokens = 0

        llm_cfg = config.get("llm", {})
        self.model = llm_cfg.get("model", "gemini-2.5-flash")
        self.max_tokens = llm_cfg.get("max_tokens", 8000)
        self.chunk_size = llm_cfg.get("chunk_size", 300)    # lines
        self.context_window = llm_cfg.get("context_window", 4)
        self.temperature = llm_cfg.get("temperature", 0.1)

        self.client = None
        self.model_instance = None

        if HAS_GEMINI:
            api_key = llm_cfg.get("api_key") or ""
            log.info("Gemini API key present: %s", bool(api_key))
            if api_key:
                try:
                    genai.configure(api_key=api_key)
                    self.model_instance = genai.GenerativeModel(self.model)
                    log.info("Gemini client initialized successfully with model: %s", self.model)
                except Exception as e:
                    log.error("Failed to initialize Gemini client: %s", e)
        else:
            log.warning("google.generativeai not installed")

    def convert(
        self,
        sf: SourceFile,
        target: TargetLanguage,
        prior_result: Optional[ConversionResult] = None,
        component_info: Optional[ComponentInfo] = None,
    ) -> ConversionResult:
        """
        Convert a source file using the LLM.
        If prior_result exists (from rule engine), refines it instead.
        If component_info exists, uses component-specific template.
        """
        source_code = prior_result.converted_code if (
            prior_result and prior_result.converted_code
        ) else sf.raw_content

        # Check cache for small / repeated files
        cached = self.cache.get(source_code, sf.language, target)
        if cached:
            log.info("Cache hit for %s", sf.path)
            return ConversionResult(
                source_file=sf,
                target_language=target,
                converted_code=cached,
                status=ConversionStatus.LLM_CONVERTED,
                confidence=0.92,
            )

        chunks = self._split_into_chunks(source_code)
        log.info("Converting %s: %d chunk(s)", sf.path, len(chunks))

        converted_parts: list[str] = []
        context_summary = ""
        total_tokens = 0
        confidence_scores: list[float] = []

        for idx, chunk in enumerate(chunks):
            converted, tokens, confidence = self._convert_chunk(
                chunk=chunk,
                chunk_index=idx,
                total_chunks=len(chunks),
                source_file=sf,
                target=target,
                context_summary=context_summary,
                component_info=component_info,
            )
            converted_parts.append(converted)
            total_tokens += tokens
            confidence_scores.append(confidence)

            # Update rolling context summary (compact, not full code)
            context_summary = self._summarise_chunk(converted, idx)

        full_converted = "\n\n".join(converted_parts)
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.5

        self.cache.set(source_code, sf.language, target, full_converted)
        self.total_tokens += total_tokens

        return ConversionResult(
            source_file=sf,
            target_language=target,
            converted_code=full_converted,
            status=ConversionStatus.LLM_CONVERTED,
            confidence=avg_confidence,
            llm_chunks_used=len(chunks),
            total_tokens=total_tokens,
        )

    def _split_into_chunks(self, code: str) -> list[str]:
        lines = code.splitlines()
        if len(lines) <= self.chunk_size:
            return [code]
        chunks = []
        for i in range(0, len(lines), self.chunk_size):
            chunks.append("\n".join(lines[i : i + self.chunk_size]))
        return chunks

    def _build_manifest(self, sf: SourceFile, target: TargetLanguage) -> str:
        patterns_text = "\n".join(
            f"- {p}" for p in self.established_patterns[-10:]  # Last 10 patterns
        ) or "None established yet — establish conventions from this file."

        return _BASE_MANIFEST.format(
            target=_TARGET_NAMES.get(target, target.value),
            established_patterns=patterns_text,
            target_specifics=_TARGET_SPECIFICS.get(target, ""),
        ) + _SOURCE_HINTS.get(sf.language, "")

    def _build_generic_prompt(
        self,
        chunk: str,
        chunk_index: int,
        total_chunks: int,
        source_file: SourceFile,
        target: TargetLanguage,
        context_summary: str,
    ) -> str:
        """Build a generic conversion prompt when no component template is available."""
        manifest = self._build_manifest(source_file, target)
        source_hint = f"Source language: {source_file.language.value}"
        target_hint  = f"Target: {_TARGET_NAMES.get(target, target.value)}"

        context_block = ""
        if context_summary:
            context_block = f"\n## Context from previous chunks\n{context_summary}\n"

        progress = f"Chunk {chunk_index + 1} of {total_chunks}" if total_chunks > 1 else "Full file"

        return f"""{manifest}
{context_block}
## Source Code ({progress})
```{source_file.language.value}
{chunk}
```

Convert the above {source_hint} snippet to {target_hint}.
Return ONLY the converted code. No explanation. No markdown fences.
If the source contains multiple classes/components that should be in separate files, 
add a comment at the start of each section indicating the file path:
  // com/company/entity/Entity.java (for Java)
  // src/components/Button.tsx (for React)

Each public class should be in its own file.
"""

    def _convert_chunk(
        self,
        chunk: str,
        chunk_index: int,
        total_chunks: int,
        source_file: SourceFile,
        target: TargetLanguage,
        context_summary: str,
        component_info: Optional[ComponentInfo] = None,
    ) -> tuple[str, int, float]:
        """Returns (converted_code, tokens_used, confidence)."""
        
        # Try to use component-specific template first
        template = None
        if component_info:
            template = get_conversion_template(
                source_file.language,
                component_info.type,
                target,
            )
            if template:
                log.debug("Using component template: %s", template.name)
        
        if template:
            # Use component-specific prompt
            prompt = template.build_prompt(
                source_content=chunk,
                source_lang=source_file.language,
                target_lang=target,
                context={
                    "chunk_index": chunk_index + 1,
                    "total_chunks": total_chunks,
                    "context_summary": context_summary,
                }
            )
        else:
            # Fall back to generic prompt
            prompt = self._build_generic_prompt(
                chunk, chunk_index, total_chunks, source_file, target, context_summary
            )

        if not self.model_instance:
            log.warning("No Gemini client configured. Returning stub for %s", source_file.path)
            stub = self._generate_stub(chunk, source_file, target)
            return stub, 0, 0.3

        try:
            response = self.model_instance.generate_content(prompt)
            converted = response.text
            # Estimate tokens (Gemini doesn't provide exact counts in same way)
            tokens = len(prompt.split()) + len(converted.split())
            confidence = self._estimate_confidence(converted)
            log.info(
                "Chunk %d/%d converted. Est. tokens: %d. Confidence: %.2f",
                chunk_index + 1, total_chunks, tokens, confidence,
            )
            return converted, tokens, confidence
        except Exception as e:
            log.error("Gemini conversion failed for %s chunk %d: %s", source_file.path, chunk_index, e)
            stub = self._generate_stub(chunk, source_file, target)
            return stub, 0, 0.1

    def _summarise_chunk(self, converted: str, idx: int) -> str:
        """Compact summary of a converted chunk for context anchoring."""
        lines = converted.splitlines()
        # Extract class/method signatures only (first 15 lines max)
        sig_lines = [
            l for l in lines[:60]
            if any(kw in l for kw in [
                "class ", "public ", "function ", "const ", "interface ",
                "@", "import ", "export ",
            ])
        ][:15]
        summary = "\n".join(sig_lines)
        return f"[Chunk {idx}]\n{summary}"

    def _estimate_confidence(self, code: str) -> float:
        """Heuristic confidence score based on TODO count and code structure."""
        todos = code.count("TODO")
        lines = max(code.count("\n"), 1)
        todo_ratio = todos / lines
        if todo_ratio > 0.1:
            return 0.5
        if todo_ratio > 0.05:
            return 0.7
        return 0.9

    def _generate_stub(self, chunk: str, sf: SourceFile, target: TargetLanguage) -> str:
        """Fallback stub when LLM is unavailable."""
        if target == TargetLanguage.JAVA_SPRING:
            return (
                f"// AUTO-GENERATED STUB — LLM conversion required\n"
                f"// Source: {sf.path} ({sf.language.value})\n"
                f"// TODO: Replace this stub with actual converted code\n\n"
                f"public class {_class_name_from_path(sf.path)} {{\n"
                f"    // TODO: Implement conversion of:\n"
                + "\n".join(f"    // {l}" for l in chunk.splitlines()[:20])
                + "\n}"
            )
        else:
            return (
                f"// AUTO-GENERATED STUB — LLM conversion required\n"
                f"// Source: {sf.path} ({sf.language.value})\n"
                f"// TODO: Replace this stub with actual converted code\n\n"
                f"import React from 'react';\n\n"
                f"const {_class_name_from_path(sf.path)}: React.FC = () => {{\n"
                f"  // TODO: Implement conversion of:\n"
                + "\n".join(f"  // {l}" for l in chunk.splitlines()[:20])
                + "\n  return <div>TODO</div>;\n};\n\nexport default "
                + _class_name_from_path(sf.path) + ";"
            )

    def stats(self) -> dict:
        return {
            "total_tokens_used": self.total_tokens,
            "cache_hit_rate": f"{self.cache.hit_rate:.1%}",
            "cache_hits": self.cache.hits,
            "cache_misses": self.cache.misses,
        }


def _class_name_from_path(path: str) -> str:
    import os
    base = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[^a-zA-Z0-9]", "", base.title()) or "ConvertedClass"
