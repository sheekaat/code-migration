"""Shared configuration loader and structured logger."""

from __future__ import annotations
import logging
import os
import sys
from pathlib import Path
from typing import Any
import yaml

try:
    from dotenv import load_dotenv
    # Load .env from current working directory or parent directories
    env_path = Path('.env')
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass


# ─── Config ──────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG: dict[str, Any] = {
    "llm": {
        "model": "gemini-2.0-flash",
        "max_tokens": 8000,
        "chunk_size": 300,
        "context_window": 4,
        "temperature": 0.1,
    },
    "conversion": {
        "confidence_threshold": 0.75,
        "rule_engine_first": True,
        "cache_patterns": True,
    },
    "analysis": {
        "complexity_red_threshold": 20,
        "complexity_amber_threshold": 10,
    },
    "output": {
        "base_dir": "./output",
        "generate_tests": True,
        "generate_ci": True,
    },
}


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    cfg = dict(_DEFAULT_CONFIG)
    config_path = Path(path)
    if config_path.exists():
        with open(config_path) as f:
            override = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, override)
    # Environment variable overrides
    if key := os.getenv("GEMINI_API_KEY"):
        cfg.setdefault("llm", {})["api_key"] = key
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ─── Logging ─────────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
