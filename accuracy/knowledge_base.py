"""
Accuracy Engine — Knowledge Base
Persists learned corrections as new rules that improve all future conversions.
This is the "gets smarter over time" component.
"""

from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from shared.models import SourceLanguage, TargetLanguage
from shared.config import get_logger

log = get_logger(__name__)

_KB_FILE = Path("./accuracy_knowledge_base.json")


@dataclass
class LearnedRule:
    """A correction pattern that was found during accuracy remediation."""
    id: str
    source_lang: str
    target_lang: str
    issue_pattern: str          # what issue text triggers this rule
    source_pattern: str         # regex to match in source code
    replacement: str            # what to replace/prepend/append
    repair_type: str            # "prepend" | "append" | "regex_replace"
    confidence: float = 1.0
    applied_count: int = 0
    created_at: float = field(default_factory=time.time)
    description: str = ""


@dataclass
class KnowledgeBase:
    rules: list[LearnedRule] = field(default_factory=list)
    correction_history: list[dict] = field(default_factory=list)

    def add_rule(self, rule: LearnedRule) -> None:
        # De-duplicate by source_pattern + target_lang
        existing_ids = {
            (r.source_pattern, r.target_lang)
            for r in self.rules
        }
        if (rule.source_pattern, rule.target_lang) not in existing_ids:
            self.rules.append(rule)
            log.info("Knowledge base: new rule '%s' added", rule.id)
        else:
            log.debug("Rule already exists, skipping: %s", rule.id)

    def record_correction(
        self,
        file_path: str,
        issue: str,
        before_score: float,
        after_score: float,
        strategy: str,
    ) -> None:
        self.correction_history.append({
            "file": file_path,
            "issue": issue,
            "before": before_score,
            "after": after_score,
            "strategy": strategy,
            "ts": time.time(),
        })

    def apply_learned_rules(
        self,
        code: str,
        source_lang: SourceLanguage,
        target_lang: TargetLanguage,
    ) -> tuple[str, list[str]]:
        """
        Apply all learned rules matching this language pair.
        Returns (patched_code, list_of_rules_applied).
        """
        applied: list[str] = []
        for rule in self.rules:
            if rule.source_lang != source_lang.value:
                continue
            if rule.target_lang != target_lang.value:
                continue
            original = code
            try:
                if rule.repair_type == "prepend":
                    if rule.replacement not in code:
                        code = rule.replacement + code
                        applied.append(rule.id)
                elif rule.repair_type == "append":
                    if rule.replacement not in code:
                        code = code.rstrip() + "\n" + rule.replacement + "\n"
                        applied.append(rule.id)
                elif rule.repair_type == "regex_replace":
                    new_code = re.sub(rule.source_pattern, rule.replacement, code)
                    if new_code != code:
                        code = new_code
                        applied.append(rule.id)
            except re.error as e:
                log.warning("Bad rule pattern '%s': %s", rule.id, e)
            if code != original:
                rule.applied_count += 1
        return code, applied

    def save(self, path: Path = _KB_FILE) -> None:
        data = {
            "rules": [asdict(r) for r in self.rules],
            "history_count": len(self.correction_history),
            "last_corrections": self.correction_history[-20:],
        }
        path.write_text(json.dumps(data, indent=2))
        log.debug("Knowledge base saved: %d rules", len(self.rules))

    @classmethod
    def load(cls, path: Path = _KB_FILE) -> "KnowledgeBase":
        kb = cls()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for r in data.get("rules", []):
                    kb.rules.append(LearnedRule(**r))
                kb.correction_history = data.get("last_corrections", [])
                log.info("Knowledge base loaded: %d rules", len(kb.rules))
            except Exception as e:
                log.warning("Could not load knowledge base: %s", e)
        return kb

    def stats(self) -> dict:
        return {
            "total_rules": len(self.rules),
            "total_corrections": len(self.correction_history),
            "most_applied": sorted(
                self.rules, key=lambda r: r.applied_count, reverse=True
            )[:5] if self.rules else [],
        }


# ─── Rule Extractor ───────────────────────────────────────────────────────────

class RuleExtractor:
    """
    When a human or the system corrects a conversion,
    extract a reusable rule from the correction.
    """

    def extract_from_correction(
        self,
        source_lang: SourceLanguage,
        target_lang: TargetLanguage,
        issue_description: str,
        original_code: str,
        corrected_code: str,
    ) -> Optional[LearnedRule]:
        """
        Diff original vs corrected and try to extract a generalizable rule.
        Currently handles: missing prepends and simple token substitutions.
        """
        orig_lines = set(original_code.splitlines())
        corr_lines = set(corrected_code.splitlines())

        added_lines = [l for l in corr_lines if l not in orig_lines]
        removed_lines = [l for l in orig_lines if l not in corr_lines]

        # Case 1: Pure prepend (e.g. adding "import React" or "package com.x")
        if added_lines and not removed_lines:
            addition = "\n".join(added_lines[:3])  # take first 3 added lines
            if len(addition) < 200:
                rule_id = f"learned_{source_lang.value}_{hash(addition) & 0xFFFF:04x}"
                return LearnedRule(
                    id=rule_id,
                    source_lang=source_lang.value,
                    target_lang=target_lang.value,
                    issue_pattern=issue_description[:80],
                    source_pattern=".*",
                    replacement=addition + "\n",
                    repair_type="prepend",
                    description=f"Auto-learned: prepend '{addition[:50]}...'",
                )

        # Case 2: Simple token swap (1:1 replacement)
        if len(removed_lines) == 1 and len(added_lines) == 1:
            old_tok = removed_lines[0].strip()
            new_tok = added_lines[0].strip()
            if old_tok and new_tok and len(old_tok) < 100:
                rule_id = f"learned_swap_{hash(old_tok) & 0xFFFF:04x}"
                return LearnedRule(
                    id=rule_id,
                    source_lang=source_lang.value,
                    target_lang=target_lang.value,
                    issue_pattern=issue_description[:80],
                    source_pattern=re.escape(old_tok),
                    replacement=new_tok,
                    repair_type="regex_replace",
                    description=f"Auto-learned swap: '{old_tok[:40]}' → '{new_tok[:40]}'",
                )

        return None   # too complex to auto-extract
