"""
Layer 6 — Output & Delivery
Writes converted files to disk, scaffolds project structure,
generates Maven POM / package.json, and produces migration report.
"""

from __future__ import annotations
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from output.file_splitter import FileSplitter, should_split_file
from output.dependency_analyzer import DependencyAnalyzer, generate_dynamic_pom
from shared.models import (
    WorkspaceManifest, ConversionResult, ConversionStatus,
    TargetLanguage, SourceLanguage,
)
from shared.config import get_logger

log = get_logger(__name__)


# ─── File Writers ─────────────────────────────────────────────────────────────

def _target_extension(target: TargetLanguage, source_path: str) -> str:
    if target == TargetLanguage.JAVA_SPRING:
        return ".java"
    # XAML → TSX, VB6 form → TSX, other → TS
    ext = Path(source_path).suffix.lower()
    if ext in (".xaml", ".frm"):
        return ".tsx"
    return ".ts"


def _target_path(result: ConversionResult, base_dir: Path) -> Path:
    if not result.source_file:
        return base_dir / "unknown.txt"
    src = Path(result.source_file.path)
    target = result.target_language
    ext = _target_extension(target, result.source_file.path)

    if target == TargetLanguage.JAVA_SPRING:
        # src/main/java/com/company/...
        java_pkg = src.with_suffix("").name
        return base_dir / "src" / "main" / "java" / "com" / "company" / "app" / f"{java_pkg}{ext}"
    else:
        # src/components/... or src/pages/...
        stem = src.stem
        folder = "components" if ext == ".tsx" else "services"
        return base_dir / "src" / folder / f"{stem}{ext}"


# ─── Maven POM Generator ──────────────────────────────────────────────────────

_POM_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>

  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.0</version>
    <relativePath/>
  </parent>

  <groupId>com.macys</groupId>
  <artifactId>{artifact_id}</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <name>{artifact_id}</name>
  <description>Auto-migrated from {source_lang}</description>

  <properties>
    <java.version>17</java.version>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-security</artifactId>
    </dependency>
    <dependency>
      <groupId>org.projectlombok</groupId>
      <artifactId>lombok</artifactId>
      <optional>true</optional>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-test</artifactId>
      <scope>test</scope>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""


# ─── package.json Generator ───────────────────────────────────────────────────

_PACKAGE_JSON_TEMPLATE = {
    "name": "{name}",
    "version": "1.0.0",
    "private": True,
    "description": "Auto-migrated from {source_lang} using Code Migration Platform",
    "dependencies": {
        "react": "^18.2.0",
        "react-dom": "^18.2.0",
        "react-router-dom": "^6.20.0",
        "axios": "^1.6.0",
        "typescript": "^5.3.0"
    },
    "devDependencies": {
        "@types/react": "^18.2.0",
        "@types/react-dom": "^18.2.0",
        "@vitejs/plugin-react": "^4.2.0",
        "vite": "^5.0.0",
        "vitest": "^1.0.0",
        "@testing-library/react": "^14.0.0"
    },
    "scripts": {
        "dev":   "vite",
        "build": "vite build",
        "test":  "vitest"
    }
}


# ─── GitHub Actions CI ────────────────────────────────────────────────────────

_JAVA_CI = """\
name: Java CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up JDK 17
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
      - name: Build with Maven
        run: mvn -B package --file pom.xml
      - name: Run tests
        run: mvn test
"""

_REACT_CI = """\
name: React CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Use Node.js 18
        uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'npm'
      - run: npm ci
      - run: npm run build
      - run: npm test
"""


# ─── Migration Report ─────────────────────────────────────────────────────────

def _build_report(manifest: WorkspaceManifest, reports: list) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    total = len(manifest.conversion_results)
    approved = sum(1 for r in manifest.conversion_results if r.validation_passed)
    needs_review = sum(1 for r in manifest.conversion_results if r.status == ConversionStatus.NEEDS_REVIEW)
    failed = sum(1 for r in manifest.conversion_results if r.status == ConversionStatus.FAILED)

    lines = [
        f"# Migration Report",
        f"Generated: {now}",
        f"",
        f"## Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Source repo | `{manifest.repo_path}` |",
        f"| Source language | {manifest.source_language.value if manifest.source_language else 'mixed'} |",
        f"| Target language | {manifest.target_language.value if manifest.target_language else 'N/A'} |",
        f"| Total files | {total} |",
        f"| Validated ✅ | {approved} ({100*approved//max(total,1)}%) |",
        f"| Needs review ⚠️ | {needs_review} |",
        f"| Failed ❌ | {failed} |",
        f"",
        f"## Complexity Distribution",
    ]

    if "analysis" in manifest.stats:
        tiers = manifest.stats["analysis"].get("complexity_tiers", {})
        for tier, count in tiers.items():
            lines.append(f"- {tier.upper()}: {count} files")

    lines += [
        "",
        "## Files Needing Review",
        "",
    ]

    for r in manifest.conversion_results:
        if r.status == ConversionStatus.NEEDS_REVIEW:
            sf_path = r.source_file.path if r.source_file else "unknown"
            lines.append(f"- `{sf_path}` — confidence: {r.confidence:.0%}")

    if "llm" in manifest.stats:
        llm = manifest.stats["llm"]
        lines += [
            "",
            "## LLM Usage",
            f"- Total tokens used: {llm.get('total_tokens_used', 0):,}",
            f"- Pattern cache hit rate: {llm.get('cache_hit_rate', '0%')}",
        ]

    lines += [
        "",
        "## Next Steps",
        "1. Review all files marked ⚠️ Needs Review in the dashboard",
        "2. Run `mvn test` (Java) or `npm test` (React) to verify converted logic",
        "3. Address all `// TODO: Manual review required` comments",
        "4. Review security configuration (auth, CORS, secrets)",
        "5. Performance test critical service paths",
    ]

    return "\n".join(lines)


# ─── Output Generator ─────────────────────────────────────────────────────────

class OutputGenerator:
    def __init__(self, config: dict):
        self.config = config
        self.base_dir = Path(config.get("output", {}).get("base_dir", "./output"))
        self.gen_tests = config.get("output", {}).get("generate_tests", True)
        self.gen_ci    = config.get("output", {}).get("generate_ci", True)

    def generate(self, manifest: WorkspaceManifest, validation_reports: list) -> str:
        out_dir = self.base_dir / f"migration_{manifest.id[:8]}"
        out_dir.mkdir(parents=True, exist_ok=True)

        target = manifest.target_language
        self._write_converted_files(manifest, out_dir)
        self._write_project_scaffold(manifest, out_dir, target)
        if self.gen_ci:
            self._write_ci(out_dir, target)
        report_path = out_dir / "MIGRATION_REPORT.md"
        report_path.write_text(_build_report(manifest, validation_reports), encoding="utf-8")

        log.info("Output written to %s", out_dir)
        return str(out_dir)

    def _write_converted_files(self, manifest: WorkspaceManifest, out_dir: Path) -> None:
        written = 0
        splitter = FileSplitter()
        
        for result in manifest.conversion_results:
            if not result.converted_code:
                continue
            
            # Determine target language
            target = result.target_language or manifest.target_language
            language = target.value if target else "java"
            
            # Check if content needs splitting (multiple classes or file markers)
            if should_split_file(result.converted_code, language):
                log.info("Detected multi-file content, splitting...")
                
                # Determine base path for Java package structure
                base_path = self._determine_base_path(result, manifest)
                
                segments = splitter.intelligent_split(
                    result.converted_code,
                    base_path=base_path,
                    language=language
                )
                if segments:
                    # Write split files
                    written_paths = splitter.write_segments(out_dir / "src", segments)
                    written += len(written_paths)
                    log.info("Split into %d files", len(written_paths))
                    continue
            
            # Default: write as single file
            dest = _target_path(result, out_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(result.converted_code, encoding="utf-8")
            written += 1
            
        log.info("Wrote %d converted files", written)
    
    def _determine_base_path(self, result, manifest) -> str:
        """
        Determine the base path for Java package structure.
        
        Uses source directory structure + detected component type for intelligent
        package organization. Ensures standard Spring Boot package conventions.
        
        Package mapping:
        - Controllers → com/company/controller
        - Services → com/company/service
        - Entities → com/company/entity
        - Repositories → com/company/repository
        - DTOs → com/company/dto
        - Utils → com/company/util
        - Config → com/company/config
        """
        if not result.source_file:
            return "com/company/app"
        
        src_path = Path(result.source_file.path)
        stem = src_path.stem.lower()
        
        # Comprehensive keyword mapping
        path_keywords = {
            'controller': 'controller',
            'controllers': 'controller',
            'ctrl': 'controller',
            'service': 'service',
            'services': 'service',
            'svc': 'service',
            'business': 'service',
            'bll': 'service',
            'entity': 'entity',
            'entities': 'entity',
            'model': 'entity',
            'models': 'entity',
            'domain': 'entity',
            'repository': 'repository',
            'repositories': 'repository',
            'repo': 'repository',
            'dao': 'repository',
            'dal': 'repository',
            'data': 'repository',
            'dto': 'dto',
            'dtos': 'dto',
            'viewmodel': 'dto',
            'vm': 'dto',
            'request': 'dto',
            'response': 'dto',
            'util': 'util',
            'utils': 'util',
            'helper': 'util',
            'helpers': 'util',
            'common': 'common',
            'shared': 'common',
            'config': 'config',
            'configuration': 'config',
            'settings': 'config',
        }
        
        # Check for component type info from file_type_registry
        detected_type = getattr(result.source_file, 'detected_component_type', None)
        
        type_package_map = {
            'CONTROLLER': 'controller',
            'SERVICE': 'service',
            'ENTITY': 'entity',
            'REPOSITORY': 'repository',
            'DATA_ACCESS': 'repository',
            'CLASS': 'util',
            'MODULE': 'util',
            'INTERFACE': 'common',
            'ENUM': 'common',
        }
        
        if detected_type and detected_type in type_package_map:
            return f"com/macys/{type_package_map[detected_type]}"
        
        # Check each path component against keywords
        for part in src_path.parts:
            part_lower = part.lower()
            if part_lower in path_keywords:
                return f"com/macys/{path_keywords[part_lower]}"
        
        # Check filename stem for keywords
        for keyword, pkg in path_keywords.items():
            if keyword in stem:
                return f"com/macys/{pkg}"
        
        # Filename suffix checks
        if stem.endswith('controller'):
            return "com/macys/controller"
        elif stem.endswith('service') or stem.endswith('svc'):
            return "com/macys/service"
        elif stem.endswith('repository') or stem.endswith('repo') or stem.endswith('dao'):
            return "com/macys/repository"
        elif stem.endswith('dto') or stem.endswith('request') or stem.endswith('response'):
            return "com/macys/dto"
        
        # Final fallback - use directory name if meaningful
        parent = src_path.parent.name.lower()
        if parent in path_keywords:
            return f"com/macys/{path_keywords[parent]}"
        
        return "com/macys/app"

    def _detect_main_package(self, out_dir: Path) -> Optional[str]:
        """Detect the main package from converted Java files."""
        java_dir = out_dir / "src" / "main" / "java"
        if not java_dir.exists():
            return None
        
        # Find all package declarations
        packages = set()
        for java_file in java_dir.rglob("*.java"):
            try:
                content = java_file.read_text(encoding='utf-8', errors='ignore')
                match = re.search(r'package\s+([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\s*;', content)
                if match:
                    pkg = match.group(1)
                    # Convert dots to path separators
                    pkg_path = pkg.replace('.', '/')
                    packages.add(pkg_path)
            except Exception:
                continue
        
        if not packages:
            return None
        
        # Find common prefix
        pkg_list = sorted(packages)
        if len(pkg_list) == 1:
            return pkg_list[0]
        
        # Find longest common prefix
        first = pkg_list[0].split('/')
        common = []
        for i, part in enumerate(first):
            if all(pkg.split('/')[i] == part if i < len(pkg.split('/')) else False for pkg in pkg_list):
                common.append(part)
            else:
                break
        
        return '/'.join(common) if common else None

    def _write_project_scaffold(
        self,
        manifest: WorkspaceManifest,
        out_dir: Path,
        target: Optional[TargetLanguage],
    ) -> None:
        name = Path(manifest.repo_path).name or "migrated-app"
        src_lang = manifest.source_language.value if manifest.source_language else "legacy"

        if target == TargetLanguage.JAVA_SPRING:
            # Analyze converted code to determine required dependencies
            analyzer = DependencyAnalyzer(out_dir)
            requirements = analyzer.analyze_project()
            
            # Generate dynamic POM with detected dependencies
            pom = generate_dynamic_pom(requirements, name, src_lang)
            (out_dir / "pom.xml").write_text(pom)
            
            # Spring Boot main class (dynamic package based on detected structure)
            main_pkg = self._detect_main_package(out_dir) or "com/macys/app"
            main_java = out_dir / "src" / "main" / "java" / Path(main_pkg)
            main_java.mkdir(parents=True, exist_ok=True)
            pkg_name = main_pkg.replace('/', '.')
            (main_java / "Application.java").write_text(
                f"package {pkg_name};\n\n"
                f"import org.springframework.boot.SpringApplication;\n"
                f"import org.springframework.boot.autoconfigure.SpringBootApplication;\n\n"
                f"@SpringBootApplication\n"
                f"public class Application {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        SpringApplication.run(Application.class, args);\n"
                f"    }}\n"
                f"}}\n"
            )
            
            # Generate dynamic application.properties
            resources = out_dir / "src" / "main" / "resources"
            resources.mkdir(parents=True, exist_ok=True)
            (resources / "application.properties").write_text(requirements.get_application_properties())
        elif target == TargetLanguage.REACT_JS:
            pkg = json.loads(
                json.dumps(_PACKAGE_JSON_TEMPLATE)
                .replace('"{name}"', f'"{name}"')
                .replace('"{source_lang}"', f'"{src_lang}"')
            )
            (out_dir / "package.json").write_text(json.dumps(pkg, indent=2))
            (out_dir / "tsconfig.json").write_text(json.dumps({
                "compilerOptions": {
                    "target": "ES2020", "lib": ["DOM", "ES2020"],
                    "jsx": "react-jsx", "module": "ESNext",
                    "moduleResolution": "bundler", "strict": True,
                    "outDir": "dist",
                },
                "include": ["src"],
            }, indent=2))
            # App entry
            src_dir = out_dir / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / "App.tsx").write_text(
                "import React from 'react';\n\n"
                "const App: React.FC = () => {\n"
                "  return (\n"
                "    <div className=\"app\">\n"
                "      <h1>Migrated Application</h1>\n"
                "      {/* TODO: Add routing and component imports */}\n"
                "    </div>\n"
                "  );\n"
                "};\n\n"
                "export default App;\n"
            )
            (src_dir / "main.tsx").write_text(
                "import React from 'react';\n"
                "import ReactDOM from 'react-dom/client';\n"
                "import App from './App';\n\n"
                "ReactDOM.createRoot(document.getElementById('root')!).render(\n"
                "  <React.StrictMode>\n"
                "    <App />\n"
                "  </React.StrictMode>\n"
                ");\n"
            )

    def _write_ci(self, out_dir: Path, target: Optional[TargetLanguage]) -> None:
        ci_dir = out_dir / ".github" / "workflows"
        ci_dir.mkdir(parents=True, exist_ok=True)
        if target == TargetLanguage.JAVA_SPRING:
            (ci_dir / "ci.yml").write_text(_JAVA_CI)
        elif target == TargetLanguage.REACT_JS:
            (ci_dir / "ci.yml").write_text(_REACT_CI)
