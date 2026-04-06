# Code Migration Platform

[![vibe coded](https://img.shields.io/badge/vibe-coded-orange)](https://www.youtube.com/watch?v=ZvzMMcKHUGI)

An automated, AI-powered codebase conversion platform supporting:

| Source | Target |
|--------|--------|
| Tibco BW (.bwp, .process) | Java Spring Boot |
| VB6 (.vbp, .frm, .cls) | ReactJS |
| C# / ASP.NET (.cs, .csproj) | Java Spring Boot |
| WPF / XAML (.xaml, .xaml.cs) | ReactJS |

---

## Architecture

```
┌─────────────────────────────────────────┐
│  Layer 1: Source Ingestion              │
│  Layer 2: Analysis Engine (AST + Graph) │
│  Layer 3: Conversion Core (Rules + LLM)   │
│  Layer 4: Automated Validation            │
│  Layer 5: Self-Healing Accuracy Loop    │
│  Layer 6: Output & Delivery             │
└─────────────────────────────────────────┘
```

### Key Features

- **File Type & Component Detection**: Automatically detects VB6 Forms/Classes, C# Controllers/Entities, Tibco Processes
- **Component-Specific Templates**: Tailored conversion prompts for each component type
- **Skip Patterns**: Exclude files/folders using glob patterns (e.g., `*Test*`, `Migrations/`)
- **Streaming Pipeline**: Memory-efficient processing for large repositories
- **Self-Healing Accuracy**: Iterative validation and auto-remediation


## Project Layout

```
code-migration-platform/
├── ingestion/              # Repo crawlers and file parsers
│   ├── crawler.py         # Repository walking with skip patterns
│   └── file_type_registry.py  # Component detection & classification
├── analysis/               # AST parsing, dependency graph, complexity analysis
├── conversion/
│   ├── rule_engine/        # Deterministic pattern-based translation
│   ├── llm_converter/       # Gemini API-powered conversion
│   ├── component_templates.py  # Component-specific LLM prompts
│   └── streaming_pipeline.py   # Memory-efficient streaming conversion
├── validation/             # Compile checks, semantic diff
│   ├── runner.py          # Validation orchestration
│   └── component_validators.py # Component-specific validation rules
├── accuracy/             # Self-healing accuracy loop
│   ├── loop.py            # Iterative accuracy improvement
│   ├── analyser.py        # Failure analysis
│   ├── remediation.py     # Auto-fix strategies
│   └── file_type_knowledge.py  # Learned patterns database
├── web_ui/                 # Flask web interface
├── output/                 # Report generation and project scaffolding
├── orchestration/          # End-to-end workflow orchestration
├── shared/                 # Common models, config, logging
├── tests/                  # Unit and integration tests
└── docs/                   # Architecture docs and runbooks
```

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (optional)
- A Google Gemini API key

### Install

```bash
# Python backend
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### Run via Web UI (Recommended)

```bash
# Start the web interface
py web_ui/app.py

# Open http://localhost:5000
# - Upload ZIP file with source code
# - Select target language
# - Watch real-time progress console
# - Download converted output
```

### Run via CLI

```bash
# Analyze a repository
python -m ingestion.crawler --repo /path/to/legacy-repo --output ./workspace

# Run analysis
python -m analysis.pipeline --workspace ./workspace

# Execute conversion
python -m conversion.pipeline --workspace ./workspace --strategy auto

# Validate output
python -m validation.runner --workspace ./workspace
```

### Docker (optional)

```bash
docker-compose up
# Web UI: http://localhost:5000
```

---

## Configuration

All config lives in `config.yaml`. Key settings:

```yaml
llm:
  model: gemini-2.5-flash
  api_key: ${GEMINI_API_KEY}
  max_tokens: 8000
  chunk_size: 300        # lines per conversion chunk
  context_window: 4      # previous chunks to include as context
```

conversion:
  confidence_threshold: 0.75   # below this → human review required
  rule_engine_first: true      # always try rules before LLM

analysis:
  complexity_red_threshold: 20   # cyclomatic complexity
  complexity_amber_threshold: 10
```

---

## Language Support Matrix

| Source | Parser | Rule Coverage | LLM Required |
|--------|--------|---------------|--------------|
| C# / ASP.NET | Roslyn-inspired regex+AST | ~65% | ~35% |
| WPF / XAML | XML + .cs parser | ~55% | ~45% |
| VB6 | Custom VB6 parser | ~50% | ~50% |
| Tibco BW | XML process parser | ~60% | ~40% |

---

## Component Detection

The platform automatically detects and classifies components for tailored conversion:

| Source Component | Detection | Target Conversion |
|------------------|-----------|-------------------|
| VB6 Form (.frm) | `Begin VB.Form` patterns | React Component (hooks, event handlers) |
| VB6 Class (.cls) | `Attribute VB_Name` + methods | Java Spring Service (DI, @Transactional) |
| C# Controller | Inherits ControllerBase, [Route] | @RestController with @RequestMapping |
| C# Entity | POCO with properties | @Entity with JPA annotations |
| Tibco Process | .bwp/.process XML | Spring Integration flows |
| C# Repository | Data access patterns | @Repository extends JpaRepository |

Component-specific templates guide the LLM for higher quality conversions with idiomatic target patterns.

---

## Recent Updates

### Enhanced Accuracy Engine (New)
Self-healing accuracy loop with per-dimension targeting for higher conversion quality:
- **Rule-based pre-fixes**: Auto-fix structural issues (annotations, imports, exports) before LLM calls
- **Per-dimension targeting**: Analyzes failures by dimension (syntax, semantic, structural, behavioral, coverage) and applies targeted LLM prompts
- **Iterative remediation**: Up to 3 accuracy passes with cheap fixes first (rules → targeted patch → full retry)
- **85% accuracy threshold**: Files scoring below threshold automatically enter remediation loop

```
Execution order (cheapest first):
1. Extended structural fixes (free) - @RestController, @Service, React imports
2. Syntax fixes (free) - brace balancing, semicolons
3. Per-dimension targeted LLM patch (cheap, surgical)
4. Standard LLM patch (moderate)
5. Full LLM retry (expensive, last resort)
6. Human review flag
```

### Web UI (New)
Simple Flask-based web interface for code migration:
- Upload ZIP file containing source code
- Select target language (Java Spring / ReactJS)
- **Skip Patterns** (optional): Exclude files/folders using glob patterns:
  - `*Test*` - skips any file/folder containing "Test"
  - `*.spec.cs` - skips C# test files
  - `Migrations/` - skips entire Migrations folder
  - Multiple patterns: `*Test*, *.spec.cs, Migrations/`
- Real-time progress console showing migration stages
- Download converted output as ZIP

```bash
# Run the web UI
py web_ui/app.py
# Open http://localhost:5000
```

### Streaming Pipeline
Memory-efficient conversion for large repositories:
- Processes files one at a time (reduces memory usage)
- Writes output immediately after each file conversion
- Detailed per-file timing and progress logging
- Graceful error handling - continues on individual file failures

### File Splitter (Auto-generated Classes)
The platform intelligently handles multi-class files during Java conversion:

**Two splitting strategies:**
1. **Explicit path markers** — Detects comments like `// com/company/entity/Customer.java` in LLM output
2. **Intelligent class detection** — Automatically detects multiple `public class` declarations and splits each into its own properly named file

**Intelligent package naming:**
- Files are organized by component type:
  - Controllers → `com/company/controller/OrderController.java`
  - Services → `com/company/service/OrderService.java`
  - Entities → `com/company/entity/Customer.java`
  - Repositories → `com/company/repository/CustomerRepository.java`
- Package declarations are auto-generated: `package com.company.entity;`

This ensures converted Java code follows standard Spring Boot project structure with proper package organization.

### LLM Provider
- **Current:** Google Gemini API (`gemini-2.5-flash`)
- **Previous:** Anthropic Claude (legacy support available)
- Environment variable: `GEMINI_API_KEY`

### Environment Configuration
- Uses `python-dotenv` for `.env` file loading
- UTF-8 encoding enforced for all file operations
