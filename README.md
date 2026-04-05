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
│  Layer 3: Conversion Core (Rules + LLM) │
│  Layer 4: Automated Validation          │
│  Layer 5: Human Review UI               │
│  Layer 6: Output & Delivery             │
└─────────────────────────────────────────┘
```

## Project Layout

```
code-migration-platform/
├── ingestion/          # Repo crawlers and file parsers
├── analysis/           # AST parsing, dependency graph, pattern classification
├── conversion/
│   ├── rule_engine/    # Deterministic pattern-based translation rules
│   └── llm_converter/  # Claude API-powered conversion for complex logic
├── validation/         # Compile checks, test runners, semantic diff
├── review-ui/          # React dashboard for human review
├── output/             # Report generation and project scaffolding
├── orchestration/      # Workflow DAG (Airflow-compatible)
├── shared/             # Common models, config, logging
├── tests/              # Unit and integration tests
└── docs/               # Architecture docs and runbooks
```

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker (optional, for full stack)
- A Google Gemini API key

### Install

```bash
# Python backend
pip install -r requirements.txt

# Review UI
cd review-ui && npm install

# Copy and configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### Run a migration

```bash
# Analyze a repository
python -m ingestion.crawler --repo /path/to/legacy-repo --output ./workspace

# Run analysis
python -m analysis.pipeline --workspace ./workspace

# Execute conversion
python -m conversion.pipeline --workspace ./workspace --strategy auto

# Validate output
python -m validation.runner --workspace ./workspace

# Launch review UI
cd review-ui && npm start
```

### Docker (full stack)

```bash
docker-compose up
# Review UI: http://localhost:3000
# API:       http://localhost:8000
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

## Recent Updates

### File Splitter (Auto-generated Classes)
The platform now automatically splits multi-class files into separate files based on file path comments in the LLM output. When converting single files containing multiple classes, the output is automatically separated into proper directory structures (e.g., `com/company/entity/Entity.java`).

### LLM Provider
- **Current:** Google Gemini API (`gemini-2.5-flash`)
- **Previous:** Anthropic Claude (legacy support available)
- Environment variable: `GEMINI_API_KEY`

### Environment Configuration
- Uses `python-dotenv` for `.env` file loading
- UTF-8 encoding enforced for all file operations
