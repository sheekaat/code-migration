"""
Layer 1 — Source Ingestion
Crawls a repository, discovers source files, classifies language,
reads content, and builds the initial WorkspaceManifest.
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional

from shared.models import (
    SourceFile, SourceLanguage, TargetLanguage,
    WorkspaceManifest, ComplexityTier,
)
from shared.config import get_logger

log = get_logger(__name__)

# File extension → SourceLanguage
_EXT_MAP: dict[str, SourceLanguage] = {
    ".cs":      SourceLanguage.CSHARP,
    ".vb":      SourceLanguage.VB6,
    ".vbp":     SourceLanguage.VB6,
    ".frm":     SourceLanguage.VB6,
    ".cls":     SourceLanguage.VB6,
    ".bas":     SourceLanguage.VB6,
    ".bwp":     SourceLanguage.TIBCO_BW,
    ".process": SourceLanguage.TIBCO_BW,
    ".module":  SourceLanguage.TIBCO_BW,
    ".xaml":    SourceLanguage.WPF_XAML,
    ".aspx":    SourceLanguage.ASPNET,
    ".ascx":    SourceLanguage.ASPNET,
}

_IGNORE_DIRS = {
    ".git", ".svn", "node_modules", "bin", "obj",
    "packages", ".vs", "__pycache__", "dist", "build",
}

_SOURCE_LANGUAGE_TARGETS: dict[SourceLanguage, TargetLanguage] = {
    SourceLanguage.CSHARP:    TargetLanguage.JAVA_SPRING,
    SourceLanguage.ASPNET:    TargetLanguage.JAVA_SPRING,
    SourceLanguage.WPF_XAML:  TargetLanguage.REACT_JS,
    SourceLanguage.VB6:       TargetLanguage.REACT_JS,
    SourceLanguage.TIBCO_BW:  TargetLanguage.JAVA_SPRING,
}


class RepoCrawler:
    """Walks a repository and produces a WorkspaceManifest."""

    def __init__(self, repo_path: str, target_language: Optional[TargetLanguage] = None):
        self.repo_path = Path(repo_path).resolve()
        self.target_language = target_language

    def crawl(self) -> WorkspaceManifest:
        log.info("Crawling repo: %s", self.repo_path)
        files: list[SourceFile] = []

        for root, dirs, filenames in os.walk(self.repo_path):
            # Prune ignored directories in-place
            dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
            for fname in filenames:
                fpath = Path(root) / fname
                sf = self._process_file(fpath)
                if sf:
                    files.append(sf)

        dominant_lang = _dominant_language(files)
        target = self.target_language or (
            _SOURCE_LANGUAGE_TARGETS.get(dominant_lang) if dominant_lang else None
        )

        manifest = WorkspaceManifest(
            repo_path=str(self.repo_path),
            source_language=dominant_lang,
            target_language=target,
            files=files,
        )
        manifest.stats["ingestion"] = {
            "total_files": len(files),
            "by_language": _count_by_language(files),
            "total_lines": sum(f.line_count for f in files),
        }
        log.info(
            "Ingested %d files. Dominant language: %s → %s",
            len(files), dominant_lang, target,
        )
        return manifest

    def _process_file(self, path: Path) -> Optional[SourceFile]:
        ext = path.suffix.lower()
        lang = _EXT_MAP.get(ext)
        if lang is None:
            return None
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            log.warning("Could not read %s: %s", path, e)
            return None

        lines = raw.splitlines()
        rel_path = str(path.relative_to(self.repo_path))
        return SourceFile(
            path=rel_path,
            language=lang,
            raw_content=raw,
            line_count=len(lines),
            char_count=len(raw),
        )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _dominant_language(files: list[SourceFile]) -> Optional[SourceLanguage]:
    counts: dict[SourceLanguage, int] = {}
    for f in files:
        if f.language:
            counts[f.language] = counts.get(f.language, 0) + 1
    return max(counts, key=counts.__getitem__) if counts else None


def _count_by_language(files: list[SourceFile]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in files:
        k = f.language.value if f.language else "unknown"
        counts[k] = counts.get(k, 0) + 1
    return counts


# ─── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Ingest a legacy repository")
    parser.add_argument("--repo", required=True, help="Path to legacy repo")
    parser.add_argument("--target", choices=[t.value for t in TargetLanguage])
    args = parser.parse_args()

    target = TargetLanguage(args.target) if args.target else None
    crawler = RepoCrawler(args.repo, target_language=target)
    manifest = crawler.crawl()
    print(json.dumps(manifest.stats, indent=2))
