"""
Component-Specific Conversion Templates

Provides targeted conversion strategies for different component types.
Each template includes:
- Source pattern recognition
- Target structure generation
- Specific LLM prompts
- Validation rules

This module serves as the main entry point and aggregates templates from
language-specific modules.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

from ingestion.file_type_registry import ComponentType, FileCategory
from shared.models import SourceLanguage, TargetLanguage
from shared.config import get_logger

log = get_logger(__name__)


# Import base class from separate module to avoid circular imports
from conversion.template_base import ConversionTemplate


# Import templates from language-specific modules
from conversion.csharp_to_java_templates import (
    CSHARP_CONTROLLER_TO_JAVA,
    CSHARP_ENTITY_TO_JAVA,
    CSHARP_REPOSITORY_TO_JAVA,
    CSHARP_DTO_TO_JAVA,
)

from conversion.tibco_to_java_templates import (
    TIBCO_PROCESS_TO_SPRING,
    TIBCO_ACTIVITY_TO_SPRING,
)

from conversion.vb6_to_react_templates import (
    VB6_FORM_TO_REACT,
    VB6_MODULE_TO_JS,
)

from conversion.vb6_to_java_templates import (
    VB6_CLASS_TO_JAVA_SERVICE,
    VB6_FORM_TO_JAVA_SERVICE,
)


# Re-export all templates for backward compatibility
__all__ = [
    # Base class
    "ConversionTemplate",
    "TemplateRegistry",
    "registry",
    "get_conversion_template",
    # C# to Java
    "CSHARP_CONTROLLER_TO_JAVA",
    "CSHARP_ENTITY_TO_JAVA",
    "CSHARP_REPOSITORY_TO_JAVA",
    "CSHARP_DTO_TO_JAVA",
    # Tibco to Java
    "TIBCO_PROCESS_TO_SPRING",
    "TIBCO_ACTIVITY_TO_SPRING",
    # VB6 to React
    "VB6_FORM_TO_REACT",
    "VB6_MODULE_TO_JS",
    # VB6 to Java
    "VB6_CLASS_TO_JAVA_SERVICE",
    "VB6_FORM_TO_JAVA_SERVICE",
]


# ═══════════════════════════════════════════════════════════════════════════
# LEGACY TEMPLATES (kept for backward compatibility - now imported from modules)
# ═══════════════════════════════════════════════════════════════════════════

# These are now imported from language-specific modules above.

# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

class TemplateRegistry:
    """Registry of all conversion templates."""
    
    def __init__(self):
        self._templates: Dict[tuple, ConversionTemplate] = {
            # (SourceLanguage, ComponentType, TargetLanguage) -> Template
            
            # C# to Java
            (SourceLanguage.CSHARP, ComponentType.SERVICE, TargetLanguage.JAVA_SPRING): CSHARP_CONTROLLER_TO_JAVA,
            (SourceLanguage.CSHARP, ComponentType.CLASS, TargetLanguage.JAVA_SPRING): CSHARP_ENTITY_TO_JAVA,
            (SourceLanguage.CSHARP, ComponentType.DATA_ACCESS, TargetLanguage.JAVA_SPRING): CSHARP_REPOSITORY_TO_JAVA,
            (SourceLanguage.CSHARP, ComponentType.ENTITY, TargetLanguage.JAVA_SPRING): CSHARP_ENTITY_TO_JAVA,
            (SourceLanguage.CSHARP, ComponentType.INTERFACE, TargetLanguage.JAVA_SPRING): None,  # Direct conversion
            (SourceLanguage.CSHARP, ComponentType.ENUM, TargetLanguage.JAVA_SPRING): None,  # Direct conversion
            
            # Tibco BW to Java
            (SourceLanguage.TIBCO_BW, ComponentType.PROCESS, TargetLanguage.JAVA_SPRING): TIBCO_PROCESS_TO_SPRING,
            (SourceLanguage.TIBCO_BW, ComponentType.ACTIVITY, TargetLanguage.JAVA_SPRING): TIBCO_ACTIVITY_TO_SPRING,
            
            # VB6 to React
            (SourceLanguage.VB6, ComponentType.FORM, TargetLanguage.REACT_JS): VB6_FORM_TO_REACT,
            (SourceLanguage.VB6, ComponentType.MODULE, TargetLanguage.REACT_JS): VB6_MODULE_TO_JS,
            
            # VB6 to Java
            (SourceLanguage.VB6, ComponentType.CLASS, TargetLanguage.JAVA_SPRING): VB6_CLASS_TO_JAVA_SERVICE,
            (SourceLanguage.VB6, ComponentType.DATA_ACCESS, TargetLanguage.JAVA_SPRING): VB6_CLASS_TO_JAVA_SERVICE,
            (SourceLanguage.VB6, ComponentType.SERVICE, TargetLanguage.JAVA_SPRING): VB6_CLASS_TO_JAVA_SERVICE,
            (SourceLanguage.VB6, ComponentType.FORM, TargetLanguage.JAVA_SPRING): VB6_FORM_TO_JAVA_SERVICE,
        }
    
    def get_template(
        self,
        source_lang: SourceLanguage,
        component_type: ComponentType,
        target_lang: TargetLanguage,
    ) -> Optional[ConversionTemplate]:
        """Get the appropriate template for a conversion."""
        key = (source_lang, component_type, target_lang)
        template = self._templates.get(key)
        
        if template:
            return template
        
        # Try without specific component type (use CLASS as default)
        key_default = (source_lang, ComponentType.CLASS, target_lang)
        return self._templates.get(key_default)
    
    def register_template(
        self,
        source_lang: SourceLanguage,
        component_type: ComponentType,
        target_lang: TargetLanguage,
        template: ConversionTemplate,
    ):
        """Register a new template."""
        key = (source_lang, component_type, target_lang)
        self._templates[key] = template
        log.info(f"Registered template: {template.name}")


# Global registry instance
registry = TemplateRegistry()


def get_conversion_template(
    source_lang: SourceLanguage,
    component_type: ComponentType,
    target_lang: TargetLanguage,
) -> Optional[ConversionTemplate]:
    """Convenience function to get conversion template."""
    return registry.get_template(source_lang, component_type, target_lang)
