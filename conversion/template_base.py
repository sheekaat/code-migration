"""
Base Conversion Template Class

This module contains the base ConversionTemplate class to avoid circular imports.
"""

from __future__ import annotations
from typing import Dict, List, Optional

from ingestion.file_type_registry import ComponentType
from shared.models import SourceLanguage, TargetLanguage


class ConversionTemplate:
    """Base template for component conversion."""
    
    def __init__(
        self,
        name: str,
        source_type: ComponentType,
        target_type: str,
        prompt_template: str,
        validation_rules: List[str],
    ):
        self.name = name
        self.source_type = source_type
        self.target_type = target_type
        self.prompt_template = prompt_template
        self.validation_rules = validation_rules
    
    def build_prompt(
        self,
        source_content: str,
        source_lang: SourceLanguage,
        target_lang: TargetLanguage,
        context: Optional[Dict] = None,
    ) -> str:
        """Build conversion prompt with component-specific instructions."""
        context = context or {}
        
        return self.prompt_template.format(
            source_content=source_content,
            source_lang=source_lang.value,
            target_lang=target_lang.value,
            target_type=self.target_type,
            **context,
        )
