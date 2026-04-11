"""
Method-Based Conversion Strategy

Extracts individual methods from C# source, converts each separately,
then reassembles into complete Java class.
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Dict
from pathlib import Path

from shared.models import SourceFile, TargetLanguage, ConversionResult, ConversionStatus
from shared.config import get_logger
from conversion.llm_converter.converter import LLMConverter

log = get_logger(__name__)

# Global to track LLM log file for this session
_llm_log_file = None

def _init_llm_log(output_dir: str):
    """Initialize LLM debug log file."""
    global _llm_log_file
    import os
    from datetime import datetime
    log_dir = os.path.join(output_dir, 'llm_logs')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    _llm_log_file = os.path.join(log_dir, f'llm_interactions_{timestamp}.txt')
    with open(_llm_log_file, 'w', encoding='utf-8') as f:
        f.write(f"LLM Interaction Log - {timestamp}\n")
        f.write("=" * 80 + "\n\n")
    log.info(f"LLM interactions will be logged to: {_llm_log_file}")

def _log_llm_interaction(method_name: str, prompt: str, response: str, cleaned: str):
    """Write full prompt and response to log file."""
    global _llm_log_file
    if not _llm_log_file:
        return
    
    from datetime import datetime
    with open(_llm_log_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*80}\n")
        f.write(f"METHOD: {method_name} at {datetime.now().isoformat()}\n")
        f.write(f"{'='*80}\n\n")
        
        f.write(f"--- FULL PROMPT SENT TO LLM ({len(prompt)} chars) ---\n")
        f.write(prompt)
        f.write(f"\n\n--- RAW LLM RESPONSE ({len(response)} chars) ---\n")
        f.write(response)
        f.write(f"\n\n--- AFTER CLEANUP ({len(cleaned)} chars) ---\n")
        f.write(cleaned)
        f.write(f"\n{'='*80}\n\n")

def _log_dependency_graph(manifest):
    """Log dependency graph to LLM log file."""
    global _llm_log_file
    if not _llm_log_file or not manifest.dependency_graph:
        return
    
    with open(_llm_log_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*80}\n")
        f.write("DEPENDENCY GRAPH\n")
        f.write(f"{'='*80}\n\n")
        f.write(f"Total files: {len(manifest.files)}\n")
        f.write(f"Total dependencies: {sum(len(deps) for deps in manifest.dependency_graph.edges.values())}\n\n")
        
        f.write("FILE DEPENDENCIES (leaf files have 0 dependencies):\n")
        f.write("-" * 60 + "\n")
        
        # Sort by number of dependencies (leaves first)
        sorted_files = sorted(
            manifest.dependency_graph.edges.items(),
            key=lambda x: len(x[1])
        )
        
        for path, deps in sorted_files:
            dep_count = len(deps)
            if deps:
                dep_names = [str(Path(d).name) for d in deps[:5]]
                dep_str = ", ".join(dep_names)
                if len(deps) > 5:
                    dep_str += f" (+{len(deps)-5} more)"
                f.write(f"{Path(path).name}: {dep_count} deps -> {dep_str}\n")
            else:
                f.write(f"{Path(path).name}: 0 deps (LEAF)\n")
        
        f.write(f"\n{'='*80}\n\n")


@dataclass
class MethodInfo:
    """Represents a method from source code."""
    name: str
    signature: str  # public void MethodName(params)
    body: str  # Full method body with braces
    access: str  # public/private/protected
    return_type: str
    is_static: bool = False
    start_line: int = 0
    end_line: int = 0


class MethodExtractor:
    """Extracts methods from C# source code."""
    
    # Regex to find C# methods - handles brace on same line or next line
    METHOD_PATTERN = re.compile(
        r'(public|private|protected|internal)\s+'  # access modifier
        r'(static\s+)?'  # optional static
        r'(async\s+)?'  # optional async
        r'(\w+(?:<[^>]+>)?)\s+'  # return type (handles generics like Task<T>)
        r'(\w+)\s*'  # method name
        r'\(([^)]*)\)\s*'  # parameters
        r'(\{|;)',  # opening brace OR semicolon (for interfaces/abstract)
        re.MULTILINE
    )
    
    def extract_methods(self, source: str) -> List[MethodInfo]:
        """Extract all methods from C# source."""
        methods = []
        lines = source.split('\n')
        
        for match in self.METHOD_PATTERN.finditer(source):
            access = match.group(1)
            is_static = bool(match.group(2))
            return_type = match.group(4)
            name = match.group(5)
            params = match.group(6)
            terminator = match.group(7)  # '{' or ';'
            
            # Handle interface/abstract methods (end with semicolon) vs concrete methods (end with '{')
            if terminator == ';':
                # Abstract/interface method - no body, but we still need to convert the signature
                # For now, add as empty method that LLM will need to implement
                body = "// Abstract method - implement logic based on method name and parameters"
                method_start_line = source[:match.start()].count('\n') + 1
                method_end_line = method_start_line  # No body lines
            else:
                # Find the opening brace position - search from match start through entire source
                # The '{' should be somewhere after the method signature
                brace_pos = source.find('{', match.start())
                
                if brace_pos == -1 or brace_pos > match.end() + 10:  # Should be near the match end
                    log.warning(f"Could not find opening brace for method {name} near match end")
                    continue
                
                # Find the matching closing brace for this method
                brace_count = 1
                pos = brace_pos + 1
                method_start_line = source[:brace_pos].count('\n') + 1
                
                while brace_count > 0 and pos < len(source):
                    if source[pos] == '{':
                        brace_count += 1
                    elif source[pos] == '}':
                        brace_count -= 1
                    pos += 1
                
                method_end_line = source[:pos].count('\n') + 1
                body = source[brace_pos+1:pos-1]  # Extract body content (without braces)
                
                # Always log extraction details for debugging
                log.info(f"    Extracted {name}: {len(body)} chars, lines {method_start_line}-{method_end_line}")
                if len(body) < 50:
                    log.warning(f"    SHORT BODY for {name}: content={repr(body)}")
                    # DEBUG: Show the match position and brace position
                    log.debug(f"      match.start={match.start()}, match.end={match.end()}, brace_pos={brace_pos}")
                    log.debug(f"      First 200 chars after brace: {repr(source[brace_pos:brace_pos+200])}")
                    # DEBUG: Show the match position and brace position
                    log.debug(f"      match.start={match.start()}, match.end={match.end()}, brace_pos={brace_pos}")
                    log.debug(f"      First 200 chars after brace: {repr(source[brace_pos:brace_pos+200])}")
            
            # Use already-calculated line numbers
            start_line = method_start_line
            end_line = method_end_line
            
            methods.append(MethodInfo(
                name=name,
                signature=f"{access} {'static ' if is_static else ''}{return_type} {name}({params})",
                body=body,
                access=access,
                return_type=return_type,
                is_static=is_static,
                start_line=start_line,
                end_line=end_line
            ))
        
        log.info(f"Extracted {len(methods)} methods from source")
        for m in methods:
            log.debug(f"  - {m.signature} ({m.end_line - m.start_line} lines)")
        
        return methods


class MethodBasedConverter:
    """Converts code by extracting and converting methods individually."""
    
    def __init__(self, llm_converter: LLMConverter):
        self.llm = llm_converter
        self.extractor = MethodExtractor()
    
    def convert_file(
        self,
        sf: SourceFile,
        target: TargetLanguage,
        class_template: str = None,
        output_dir: str = None
    ) -> ConversionResult:
        """
        Convert a file using method-based strategy.
        
        1. Extract methods from source
        2. Convert each method individually
        3. Reassemble into Java class
        """
        log.info(f"Method-based conversion: {sf.path}")
        
        # Step 1: Extract methods and class context
        methods = self.extractor.extract_methods(sf.raw_content)
        
        if not methods:
            log.warning("No methods found, falling back to full-file conversion")
            # Log fallback conversion to LLM log
            _log_llm_interaction(f"[FALLBACK] {sf.path}", "FULL FILE CONVERSION - NO METHODS EXTRACTED", 
                                 f"File has no extractable methods. Raw content length: {len(sf.raw_content)}", 
                                 "Falling back to full-file LLM conversion")
            result = self.llm.convert(sf, target)
            # CRITICAL: Fix package and class name in fallback output
            correct_package = self._determine_package(sf)
            correct_class = Path(sf.path).stem
            result.converted_code = self._fix_package_and_class(result.converted_code, correct_package, correct_class)
            return result
        
        # Extract class-level context (fields, constructor, other methods)
        class_context = self._extract_class_context(sf.raw_content, methods)
        log.info(f"  Class context: {len(class_context['fields'])} fields, {len(class_context['other_methods'])} other methods")
        log.info(f"  Class name: {class_context['class_name']}")
        if class_context['fields']:
            log.info(f"  Fields detected:")
            for f in class_context['fields'][:5]:  # Show first 5
                log.info(f"    - {f['type']} _{f['name']} ({f['access']})")
        if class_context['other_methods']:
            log.info(f"  Other methods for reference:")
            for m in class_context['other_methods'][:3]:  # Show first 3
                log.info(f"    - {m['name']}")
        
        # Step 2: Convert each method with full context
        converted_methods = []
        for method in methods:
            log.info(f"  Converting method: {method.name}")
            log.debug(f"    Method body ({len(method.body)} chars): {method.body[:200]}...")
            
            # Build focused prompt with class context
            prompt = self._build_method_prompt(method, sf, class_context)
            
            try:
                converted = self._convert_single_method(prompt, method, output_dir)
                if converted:
                    converted_methods.append((method.name, converted))
                    log.info(f"    ✓ Converted: {method.name} ({len(converted)} chars)")
                else:
                    log.error(f"    Failed: {method.name}")
            except Exception as e:
                log.error(f"    Error converting {method.name}: {e}")
        
        # Step 3: Reassemble into Java class
        # IMPORTANT: Preserve original C# class name (e.g., ICustomerRepository, not CustomerRepository)
        original_class_name = Path(sf.path).stem
        log.info(f"  Using original class name: {original_class_name}")
        if converted_methods:
            # Build the full Java class
            package = self._determine_package(sf)
            imports = self._determine_imports(sf)
            full_class = self._reassemble_class(
                original_class_name,
                converted_methods,
                package,
                imports,
                sf
            )
            
            from shared.models import ConversionResult, ConversionStatus
            return ConversionResult(
                source_file=sf,
                target_language=target,
                converted_code=full_class,
                status=ConversionStatus.LLM_CONVERTED,
                confidence=0.90,
                llm_chunks_used=len(converted_methods),
            )
        else:
            return ConversionResult(
                source_file=sf,
                target_language=target,
                converted_code="",
                status=ConversionStatus.FAILED,
                confidence=0.0,
                review_notes="No methods could be converted"
            )
    
    def _extract_class_context(self, source: str, methods: List[MethodInfo]) -> Dict:
        """Extract class-level context: fields, constructor, other method signatures."""
        context = {
            'fields': [],
            'constructor': None,
            'other_methods': [],
            'class_name': None
        }
        
        # Extract class name
        class_match = re.search(r'(?:public|internal|private)?\s*class\s+(\w+)', source)
        if class_match:
            context['class_name'] = class_match.group(1)
        
        # Extract fields (private/protected readonly variables)
        field_pattern = re.compile(
            r'(private|protected|public|internal)\s+'
            r'(readonly\s+)?'
            r'(static\s+)?'
            r'(\w+(?:<[^>]+>)?)\s+'
            r'_(\w+)\s*;',
            re.MULTILINE
        )
        for match in field_pattern.finditer(source):
            access = match.group(1)
            readonly = match.group(2) or ''
            static = match.group(3) or ''
            type_name = match.group(4)
            field_name = match.group(5)
            context['fields'].append({
                'access': access,
                'readonly': bool(readonly),
                'static': bool(static),
                'type': type_name,
                'name': field_name
            })
        
        # Extract constructor
        ctor_pattern = re.compile(
            r'(public|private|protected|internal)\s+'
            r'(\w+)\s*\(([^)]*)\)\s*\{',
            re.MULTILINE
        )
        for match in ctor_pattern.finditer(source):
            if match.group(2) == context['class_name']:
                context['constructor'] = {
                    'access': match.group(1),
                    'params': match.group(3)
                }
                break
        
        # Extract other method signatures (just names and params for context)
        method_names = {m.name for m in methods}
        for match in self.extractor.METHOD_PATTERN.finditer(source):
            name = match.group(5)
            if name not in method_names and name != context['class_name']:
                context['other_methods'].append({
                    'name': name,
                    'signature': f"{match.group(1)} {match.group(4)} {name}({match.group(6)})"
                })
        
        return context
    
    def _fix_package_and_class(self, code: str, correct_package: str, correct_class: str) -> str:
        """Fix package declaration and class name in LLM output."""
        # Fix package declaration
        code = re.sub(r'package\s+[\w.]+;', f'package {correct_package};', code)
        # Fix class name (preserve any extends/implements)
        code = re.sub(r'(public\s+(?:class|interface)\s+)\w+', r'\1' + correct_class, code)
        # Remove LLM-generated file markers
        code = re.sub(r'^//\s*com[/\w]+/\w+\.java\s*\n?', '', code, flags=re.MULTILINE)
        return code
    
    def _clean_method_output(self, converted: str, output_dir: str = None) -> str:
        """Minimal cleanup - extract config, remove class wrappers only."""
        import os
        
        # Extract and save config properties if output_dir provided
        if output_dir:
            self._extract_and_save_config(converted, output_dir)
        
        # Remove class-level wrappers (imports, package, annotations, class decl)
        converted = re.sub(r'^\s*import\s+[^;]+;\s*$', '', converted, flags=re.MULTILINE)
        converted = re.sub(r'^\s*package\s+[^;]+;\s*$', '', converted, flags=re.MULTILINE)
        converted = re.sub(r'^\s*@(?:Service|Slf4j|Component)\s*$', '', converted, flags=re.MULTILINE)
        converted = re.sub(r'^\s*public\s+class\s+\w+\s*\{?\s*$', '', converted, flags=re.MULTILINE)
        converted = re.sub(r'^\s*class\s+\w+\s*\{?\s*$', '', converted, flags=re.MULTILINE)
        
        # DON'T remove trailing brace - it's needed for methods!
        # Only remove class-level closing brace if it exists at very start of trimmed content
        # Check if the content STARTS with just a brace (after stripping)
        stripped = converted.lstrip()
        if stripped.startswith('}'):
            # Remove only the first line if it's just a brace
            lines = converted.split('\n')
            if lines and lines[0].strip() == '}':
                converted = '\n'.join(lines[1:])
        
        # Remove config comments from Java file (they go to config files)
        converted = re.sub(r'^\s*//\s*(?:Add to |#).*?(?:application\.properties|pom\.xml|server\.port|spring\.|logging\.|app\.).*$', '', converted, flags=re.MULTILINE | re.IGNORECASE)
        converted = re.sub(r'^\s*<!--\s*Add to pom\.xml.*?-->', '', converted, flags=re.MULTILINE | re.IGNORECASE)
        
        # Basic formatting only
        converted = re.sub(r'\n{3,}', '\n\n', converted)
        
        return converted.strip()
    
    def _extract_and_save_config(self, converted: str, output_dir: str):
        """Extract config comments and write to actual config files."""
        import os
        
        # Extract application.properties entries
        app_props = []
        for match in re.finditer(r'//\s*#?\s*(server\.port|spring\.|logging\.|app\.)[^=]*=.*', converted, re.IGNORECASE):
            prop = match.group(0).replace('//', '').strip()
            if prop.startswith('#'):
                prop = prop[1:].strip()
            app_props.append(prop)
        
        # Extract pom.xml entries
        pom_deps = []
        for match in re.finditer(r'<!--\s*(<dependency>.*?</dependency>)\s*-->', converted, re.DOTALL | re.IGNORECASE):
            pom_deps.append(match.group(1))
        
        # Write to files if found
        if app_props:
            props_path = os.path.join(output_dir, 'src', 'main', 'resources', 'application.properties')
            os.makedirs(os.path.dirname(props_path), exist_ok=True)
            with open(props_path, 'a', encoding='utf-8') as f:
                f.write('\n'.join(app_props) + '\n')
            log.info(f"  Extracted {len(app_props)} properties to application.properties")
        
        if pom_deps:
            pom_path = os.path.join(output_dir, 'pom.xml')
            # Note: pom.xml needs to be merged carefully - just log for now
    def _build_method_prompt(self, method: MethodInfo, sf: SourceFile, class_context: dict) -> str:
        """Build focused prompt for single method conversion with class context."""
        
        # Extract dependencies from fields for constructor injection
        # FILTER: Skip self-references (class depending on itself)
        class_name = class_context['class_name']
        deps = []
        for field in class_context['fields']:
            field_type = field['type']
            # Skip if field type is same as class name (self-dependency)
            if field_type == class_name or field_type == class_name + 'Repository':
                log.warning(f"  Skipping self-dependency: {field_type} {field['name']}")
                continue
            # Map field types to Java types and add imports
            if 'Repository' in field_type:
                deps.append(f"{field_type} {field['name']}")
            elif 'Service' in field_type:
                deps.append(f"{field_type} {field['name']}")
            # Add more mappings as needed
        
        # Build fields section
        fields_str = ""
        if class_context['fields']:
            fields_str = "## CLASS FIELDS (convert these to Java private final):\n"
            for f in class_context['fields']:
                fields_str += f"// C#: {f['access']} {f['type']} _{f['name']}\n"
        
        # Build other methods section
        other_methods_str = ""
        if class_context['other_methods']:
            other_methods_str = "## OTHER METHODS IN CLASS (for reference):\n"
            for m in class_context['other_methods'][:5]:  # Limit to 5
                other_methods_str += f"// {m['signature']}\n"
        
        return f"""Convert this C# method to Java Spring Boot method.

## CLASS CONTEXT:
Class Name: {class_context['class_name'] or 'Unknown'}
{fields_str}
{other_methods_str}

## THE C# METHOD TO CONVERT:
```csharp
{method.signature}
{{
{method.body}
}}
```

## CRITICAL RULES:
1. Convert EVERY line of the method above - DO NOT skip any logic
2. Use class fields like `this.orderRepository` (already injected)
3. Call other methods directly like `processSingleOrder(order)`
4. Convert C# `_log.Info()` to Java `log.info()`
5. Convert C# `DateTime.Now` to Java `LocalDateTime.now()`
6. Convert C# `async Task` to Java `@Async` + `CompletableFuture`
7. Convert C# `try-catch` to Java `try-catch` with proper exception handling
8. Use Java 17 features (var, pattern matching, etc.)
9. ADD @Transactional annotation for methods that write data (save, update, delete)
10. NEVER output class declaration, imports, or package - ONLY the method
11. Output ONLY the converted method body, nothing else
12. NEVER say "logic was not provided" - convert what you see
13. NEVER add comments about "assuming fields exist" - they DO exist in the class
14. NEVER generate additional classes - only convert the single method above
15. External dependencies will be provided separately - do NOT implement them here
16. NEVER change the class name - preserve it exactly from C#
17. The class MUST be named exactly: {class_name}
- NEVER output class declaration - ONLY output the method
- NEVER output imports - just the method

Return ONLY the Java method code. NO class wrapper. NO imports. NO explanations.
"""
    
    def _convert_single_method(
        self,
        prompt: str,
        method: MethodInfo,
        output_dir: str = None
    ) -> Optional[str]:
        """Convert a single method using LLM."""
        try:
            import google.generativeai as genai
            
            # LOG to console (brief) and file (full)
            log.info(f"[LLM] Converting {method.name}: prompt={len(prompt)} chars, body={len(method.body)} chars")
            
            model = genai.GenerativeModel(self.llm.model)
            response = model.generate_content(prompt)
            
            if response and response.text:
                raw_response = response.text.strip()
                
                # Clean up the response
                converted = raw_response
                converted = re.sub(r'^```java\s*', '', converted)
                converted = re.sub(r'```\s*$', '', converted)
                converted = converted.strip()
                
                # Apply full cleanup with output_dir for config extraction
                cleaned = self._clean_method_output(converted, output_dir)
                
                # LOG FULL to file
                _log_llm_interaction(method.name, prompt, raw_response, cleaned)
                
                # Validate braces are balanced
                open_count = cleaned.count('{')
                close_count = cleaned.count('}')
                if open_count != close_count:
                    log.warning(f"[LLM] Brace mismatch in {method.name}: {open_count} open, {close_count} close")
                    # Try to fix by adding missing closing braces
                    missing = open_count - close_count
                    if missing > 0:
                        cleaned = cleaned + ('\n}' * missing)
                        log.info(f"[LLM] Added {missing} closing brace(s) to {method.name}")
                
                # Simple check for empty methods only
                if len(cleaned.strip()) < 50:
                    log.warning(f"[LLM] Very short output for {method.name}: {len(cleaned)} chars")
                else:
                    log.info(f"[LLM] ✓ {method.name} converted ({len(cleaned)} chars)")
                
                return cleaned
            
            log.error(f"[LLM] Empty response for {method.name}")
            return None
        except Exception as e:
            log.error(f"[LLM] Conversion failed for {method.name}: {e}")
            return None
    
        
        # LOG to console (brief) and file (full)
        log.info(f"[LLM] Converting {method.name}: prompt={len(prompt)} chars, body={len(method.body)} chars")
        
        model = genai.GenerativeModel(self.llm.model)
        response = model.generate_content(prompt)
        
        if response and response.text:
            raw_response = response.text.strip()
            class_lines.append("    // Dependencies")
            for dep in deps:
                class_lines.append(f"    private final {dep};")
            class_lines.append("")
            
            # Constructor
            class_lines.append(f"    public {class_name}({', '.join(deps)}) {{")
            for dep in deps:
                var_name = dep.split()[1].lower() + dep.split()[0].replace("Repository", "").replace("Service", "")
                class_lines.append(f"        this.{var_name} = {var_name};")
            class_lines.append("    }")
            class_lines.append("")
        
        # Add converted methods (cleaned up)
        for method_name, method_code in methods:
            # AGGRESSIVE: Remove import statements anywhere in method code
            method_code = re.sub(r'import\s+[^;]+;\s*\n?', '', method_code)
            # AGGRESSIVE: Remove package declarations
            method_code = re.sub(r'package\s+[^;]+;\s*\n?', '', method_code)
            # AGGRESSIVE: Remove class-level annotations anywhere in code
            method_code = re.sub(r'@(?:Service|Slf4j|Transactional|Repository|Component)\s*\n?', '', method_code)
            # CRITICAL: Replace any wrong class names with correct one
            method_code = re.sub(r'class\s+\w+', f'class {class_name}', method_code)
            # Clean up empty lines created by removals
            method_code = re.sub(r'\n{3,}', '\n\n', method_code)
            method_code = method_code.strip()
            
            # Ensure method has proper indentation
            lines = method_code.split('\n')
            indented_lines = []
            for line in lines:
                if line.strip():
                    indented_lines.append('    ' + line)
                else:
                    indented_lines.append(line)
            
            class_lines.extend(indented_lines)
            class_lines.append("")
        
        # Close class
        class_lines.append("}")
        
        return '\n'.join(import_lines + class_lines)
    
    def _reassemble_class(
        self,
        class_name: str,
        methods: List[tuple],
        package: str,
        imports: List[str],
        sf: 'SourceFile'
    ) -> str:
        """Reassemble converted methods into Java class."""
        
        # Determine class annotation based on type
        if 'repository' in class_name.lower():
            class_annotations = ["@Repository"]
            stereotype_import = "import org.springframework.stereotype.Repository;"
        else:
            class_annotations = ["@Service", "@Slf4j"]
            stereotype_import = "import org.springframework.stereotype.Service;"
        
        # Build imports
        import_lines = [
            f"package {package};",
            "",
            stereotype_import,
            "import org.springframework.transaction.annotation.Transactional;",
            "import lombok.extern.slf4j.Slf4j;",
        ]
        
        # Add dynamic imports based on method content
        for _, method_code in methods:
            if 'CompletableFuture' in method_code:
                import_lines.append("import java.util.concurrent.CompletableFuture;")
            if 'Stream' in method_code:
                import_lines.append("import java.util.stream.Collectors;")
        
        import_lines.append("")
        
        # Add constructor with dependencies (extracted from original C# code)
        deps = self._infer_dependencies(methods, class_name, sf.raw_content)
        if deps:
            import_lines.append("import org.slf4j.Logger;")
            import_lines.append("import org.slf4j.LoggerFactory;")
            import_lines.append("")
        
        # Build class
        class_lines = class_annotations + [
            f"public class {class_name} {{",
            "",
        ]
        
        if deps:
            class_lines.append("    // Dependencies")
            for dep in deps:
                class_lines.append(f"    private final {dep};")
            class_lines.append("")
            
            # Constructor
            class_lines.append(f"    public {class_name}({', '.join(deps)}) {{")
            for dep in deps:
                var_name = dep.split()[1]
                class_lines.append(f"        this.{var_name} = {var_name};")
            class_lines.append("    }")
            class_lines.append("")
        
        # Add methods
        for method_name, method_code in methods:
            # AGGRESSIVE: Remove import statements anywhere in method code
            method_code = re.sub(r'import\s+[^;]+;\s*\n?', '', method_code)
            # AGGRESSIVE: Remove package declarations
            method_code = re.sub(r'package\s+[^;]+;\s*\n?', '', method_code)
            # AGGRESSIVE: Remove class-level annotations anywhere in code
            method_code = re.sub(r'@(?:Service|Slf4j|Transactional|Repository|Component)\s*\n?', '', method_code)
            # CRITICAL: Replace any wrong class names with correct one
            method_code = re.sub(r'class\s+\w+', f'class {class_name}', method_code)
            # Clean up empty lines created by removals
            method_code = re.sub(r'\n{3,}', '\n\n', method_code)
            method_code = method_code.strip()
            
            # Ensure method has proper indentation
            lines = method_code.split('\n')
            indented_lines = []
            for line in lines:
                if line.strip():
                    indented_lines.append('    ' + line)
                else:
                    indented_lines.append(line)
            
            class_lines.extend(indented_lines)
            class_lines.append("")
        
        # Close class
        class_lines.append("}")
        
        return '\n'.join(import_lines + class_lines)
    
    def _determine_package(self, sf: SourceFile) -> str:
        """Determine Java package from source file path - dynamic domain."""
        path = Path(sf.path)
        stem = path.stem.lower()
        
        # Extract domain from folder structure (e.g., LegacyOrderService -> order)
        # Dynamically extract domain by removing common suffixes/prefixes
        parts = path.parts
        domain = None
        suffixes_to_remove = ['service', 'core', 'legacy', 'host', 'api', 'web', 'app', 'system', 'platform']
        prefixes_to_remove = ['legacy', 'core']
        
        for part in parts:
            part_lower = part.lower()
            # Skip common non-domain folders
            if part_lower in ('src', 'main', 'java', 'com', 'macys', 'mst', 'input', 'output', 'conversion', 'shared', 'models', 'repositories', 'services', 'controllers', 'helpers'):
                continue
            
            # Clean the part to extract domain
            cleaned = part_lower
            for prefix in prefixes_to_remove:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):]
            for suffix in suffixes_to_remove:
                if cleaned.endswith(suffix):
                    cleaned = cleaned[:-len(suffix)]
            
            # If we have a meaningful name left, use it as domain
            if cleaned and len(cleaned) > 2:
                domain = cleaned
                break
        
        if not domain:
            domain = "shared"  # Default fallback
        
        # Determine type folder based on filename
        if 'repository' in stem:
            type_folder = "repository"
        elif 'service' in stem:
            type_folder = "service"
        elif 'helper' in stem:
            type_folder = "helper"
        elif 'controller' in stem:
            type_folder = "controller"
        else:
            type_folder = "model"
        
        # Extract subdomain from class name by removing type suffixes
        import re
        type_suffixes = [
            'Controller', 'Service', 'Repository', 'Repo', 'Dao', 'Impl',
            'Entity', 'Model', 'Dto', 'DTO', 'Request', 'Response',
            'Validator', 'Config', 'Configuration', 'Util', 'Helper',
            'Exception', 'Handler', 'Mapper', 'Factory', 'Host', 'Processing'
        ]
        
        subdomain = path.stem
        for suffix in type_suffixes:
            if subdomain.endswith(suffix):
                subdomain = subdomain[:-len(suffix)]
                break
        subdomain = re.sub(r'([a-z])([A-Z])', r'\1\2', subdomain).lower()
        subdomain = re.sub(r'[^a-z0-9]', '', subdomain)
        
        return f"com.macys.mst.{domain}.{type_folder}.{subdomain}"
    
    def _determine_imports(self, sf: SourceFile, target: TargetLanguage = None) -> List[str]:
        """Determine required imports based on source analysis."""
        imports = []
        content = sf.raw_content
        
        if 'DateTime' in content:
            imports.append("java.time.LocalDateTime")
        if 'List<' in content:
            imports.append("java.util.List")
        if 'Dictionary' in content or 'IDictionary' in content:
            imports.append("java.util.Map")
        if 'async' in content or 'await' in content:
            imports.append("java.util.concurrent.CompletableFuture")
        
        return imports
    
    def _infer_dependencies(self, methods: List[tuple], class_name: str = None, 
                            original_code: str = "") -> List[str]:
        """Infer required dependencies from original C# code (not converted Java code)."""
        import re
        deps = {}  # Use dict to track by normalized key to prevent duplicates
        
        if original_code:
            # Extract ACTUAL field types from C# code
            # Pattern: TypeName fieldName; or TypeName _fieldName;
            field_patterns = [
                # private OrderProcessingService _orderService;
                # public ICustomerRepository customerRepository;
                (r'(?:private|public|protected|internal)\s+(\w+)\s+_?(\w+)(?:Repository|Service)\s*;',
                 lambda m: (m.group(1), f"{m.group(2).lower()}{m.group(1).replace('I', '')}")),
                # readonly fields: private readonly OrderProcessingService _orderService;
                (r'(?:private|public|protected|internal)\s+readonly\s+(\w+)\s+_?(\w+)(?:Repository|Service)\s*;',
                 lambda m: (m.group(1), f"{m.group(2).lower()}{m.group(1).replace('I', '')}")),
            ]
            
            for pattern, extractor in field_patterns:
                for match in re.finditer(pattern, original_code, re.IGNORECASE):
                    actual_type, field_name = extractor(match)
                    
                    # Skip self-dependency
                    if class_name and actual_type == class_name:
                        continue
                    
                    # Normalize field name (camelCase)
                    field_name = re.sub(r'^_', '', field_name)  # Remove leading underscore
                    if not field_name[0].islower():
                        field_name = field_name[0].lower() + field_name[1:]
                    
                    dep = f"{actual_type} {field_name}"
                    deps[field_name.lower()] = dep
        
        # Always add logger (single, consistent declaration)
        deps['log'] = "Logger log"
        
        return sorted(deps.values())
