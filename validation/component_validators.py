"""
Component-Specific Validation Rules

Provides validation rules tailored to specific component types.
Each component type has unique requirements that must be validated.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable
from enum import Enum
import re

from ingestion.file_type_registry import ComponentType
from shared.models import TargetLanguage
from shared.config import get_logger

log = get_logger(__name__)


@dataclass
class ValidationRule:
    """A single validation rule."""
    name: str
    description: str
    check: Callable[[str], bool]  # Function that returns True if passed
    severity: str = "error"  # error, warning
    suggestion: str = ""


@dataclass
class ComponentValidationSuite:
    """Collection of validation rules for a component type."""
    component_type: ComponentType
    target_language: TargetLanguage
    rules: List[ValidationRule]
    
    def validate(self, code: str) -> List[Dict]:
        """Run all validation rules and return failures."""
        failures = []
        for rule in self.rules:
            if not rule.check(code):
                failures.append({
                    "rule": rule.name,
                    "description": rule.description,
                    "severity": rule.severity,
                    "suggestion": rule.suggestion,
                })
        return failures


# ═══════════════════════════════════════════════════════════════════════════
# REACT COMPONENT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

REACT_COMPONENT_RULES = ComponentValidationSuite(
    component_type=ComponentType.FORM,
    target_language=TargetLanguage.REACT_JS,
    rules=[
        ValidationRule(
            name="react_import",
            description="Must import React",
            check=lambda c: "import React" in c or "from 'react'" in c or "from \"react\"" in c,
            suggestion="Add: import React, { useState, useEffect } from 'react';",
        ),
        ValidationRule(
            name="functional_component",
            description="Must use functional component (not class)",
            check=lambda c: "class " not in c or "extends Component" not in c,
            suggestion="Convert class component to functional component with hooks",
        ),
        ValidationRule(
            name="export_default",
            description="Must have export default",
            check=lambda c: "export default" in c,
            suggestion="Add: export default ComponentName;",
        ),
        ValidationRule(
            name="jsx_return",
            description="Must return JSX",
            check=lambda c: "return (" in c and ("<" in c or "</" in c),
            suggestion="Ensure component returns JSX elements",
        ),
        ValidationRule(
            name="useState_for_state",
            description="Should use useState for stateful variables",
            check=lambda c: "useState" in c or "this.state" not in c,
            severity="warning",
            suggestion="Consider using useState hook for component state",
        ),
        ValidationRule(
            name="event_handlers",
            description="Should have proper event handler bindings",
            check=lambda c: "onClick={" in c or "onChange={" in c or "onSubmit={" in c or "=>" not in c,
            severity="warning",
            suggestion="Ensure event handlers are properly bound: onClick={handleClick}",
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# JAVA SPRING SERVICE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

JAVA_SERVICE_RULES = ComponentValidationSuite(
    component_type=ComponentType.SERVICE,
    target_language=TargetLanguage.JAVA_SPRING,
    rules=[
        ValidationRule(
            name="service_annotation",
            description="Must have @Service annotation",
            check=lambda c: "@Service" in c,
            suggestion="Add @Service annotation to the class",
        ),
        ValidationRule(
            name="package_declaration",
            description="Must have package declaration",
            check=lambda c: re.search(r'^package\s+\w+', c, re.MULTILINE) is not None,
            suggestion="Add package declaration: package com.company.service;",
        ),
        ValidationRule(
            name="class_declaration",
            description="Must have public class declaration",
            check=lambda c: re.search(r'public\s+class\s+\w+', c) is not None,
            suggestion="Add public class declaration",
        ),
        ValidationRule(
            name="transactional_boundary",
            description="Database operations should have @Transactional",
            check=lambda c: "@Transactional" in c or not re.search(r'(save|update|delete|insert)', c, re.IGNORECASE),
            severity="warning",
            suggestion="Add @Transactional to methods that modify data",
        ),
        ValidationRule(
            name="autowired_constructor",
            description="Should use constructor injection",
            check=lambda c: "@Autowired" in c or re.search(r'public\s+\w+\([^)]*\w+\s+\w+[^)]*\)', c) is not None,
            severity="warning",
            suggestion="Use constructor injection for dependencies",
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# JAVA SPRING CONTROLLER VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

JAVA_CONTROLLER_RULES = ComponentValidationSuite(
    component_type=ComponentType.FORM,  # Forms map to controllers
    target_language=TargetLanguage.JAVA_SPRING,
    rules=[
        ValidationRule(
            name="rest_controller_annotation",
            description="Must have @RestController annotation",
            check=lambda c: "@RestController" in c,
            suggestion="Add @RestController annotation",
        ),
        ValidationRule(
            name="request_mapping",
            description="Should have @RequestMapping on class or methods",
            check=lambda c: "@RequestMapping" in c or "@GetMapping" in c or "@PostMapping" in c,
            severity="warning",
            suggestion="Add @RequestMapping or HTTP method annotations",
        ),
        ValidationRule(
            name="response_entity",
            description="Should return ResponseEntity",
            check=lambda c: "ResponseEntity" in c or "void" in c,
            severity="warning",
            suggestion="Consider returning ResponseEntity<T> for proper HTTP responses",
        ),
        ValidationRule(
            name="path_variable_mapping",
            description="Should use @PathVariable for route parameters",
            check=lambda c: "@PathVariable" in c or "{" not in c,
            severity="warning",
            suggestion="Use @PathVariable for path parameters in URL",
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# JAVA SPRING REPOSITORY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

JAVA_REPOSITORY_RULES = ComponentValidationSuite(
    component_type=ComponentType.DATA_ACCESS,
    target_language=TargetLanguage.JAVA_SPRING,
    rules=[
        ValidationRule(
            name="repository_annotation",
            description="Must have @Repository annotation",
            check=lambda c: "@Repository" in c,
            suggestion="Add @Repository annotation",
        ),
        ValidationRule(
            name="extends_jpa_repository",
            description="Should extend JpaRepository or similar",
            check=lambda c: "extends" in c and ("JpaRepository" in c or "CrudRepository" in c),
            severity="warning",
            suggestion="Extend JpaRepository<Entity, ID> for standard CRUD",
        ),
        ValidationRule(
            name="query_annotations",
            description="Custom queries should use @Query",
            check=lambda c: "@Query" in c or "SELECT" not in c.upper(),
            severity="warning",
            suggestion="Use @Query annotation for custom JPQL/SQL queries",
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# JAVA ENTITY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

JAVA_ENTITY_RULES = ComponentValidationSuite(
    component_type=ComponentType.ENTITY,
    target_language=TargetLanguage.JAVA_SPRING,
    rules=[
        ValidationRule(
            name="entity_annotation",
            description="Must have @Entity annotation",
            check=lambda c: "@Entity" in c,
            suggestion="Add @Entity annotation",
        ),
        ValidationRule(
            name="id_annotation",
            description="Must have @Id field",
            check=lambda c: "@Id" in c,
            suggestion="Add @Id annotation to primary key field",
        ),
        ValidationRule(
            name="table_annotation",
            description="Should have @Table annotation",
            check=lambda c: "@Table" in c,
            severity="warning",
            suggestion="Add @Table(name=\"table_name\") for explicit table mapping",
        ),
        ValidationRule(
            name="column_annotations",
            description="Should have @Column on fields",
            check=lambda c: "@Column" in c,
            severity="warning",
            suggestion="Use @Column for field-level configuration",
        ),
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

class ComponentValidationRegistry:
    """Registry of validation suites for component types."""
    
    def __init__(self):
        self._suites: Dict[tuple, ComponentValidationSuite] = {
            # React
            (ComponentType.FORM, TargetLanguage.REACT_JS): REACT_COMPONENT_RULES,
            (ComponentType.USER_CONTROL, TargetLanguage.REACT_JS): REACT_COMPONENT_RULES,
            (ComponentType.DIALOG, TargetLanguage.REACT_JS): REACT_COMPONENT_RULES,
            
            # Java Services
            (ComponentType.SERVICE, TargetLanguage.JAVA_SPRING): JAVA_SERVICE_RULES,
            (ComponentType.CLASS, TargetLanguage.JAVA_SPRING): JAVA_SERVICE_RULES,
            
            # Java Controllers
            (ComponentType.FORM, TargetLanguage.JAVA_SPRING): JAVA_CONTROLLER_RULES,
            
            # Java Repositories
            (ComponentType.DATA_ACCESS, TargetLanguage.JAVA_SPRING): JAVA_REPOSITORY_RULES,
            
            # Java Entities
            (ComponentType.ENTITY, TargetLanguage.JAVA_SPRING): JAVA_ENTITY_RULES,
        }
    
    def get_validation_suite(
        self,
        component_type: ComponentType,
        target_lang: TargetLanguage,
    ) -> Optional[ComponentValidationSuite]:
        """Get validation suite for component type and target."""
        suite = self._suites.get((component_type, target_lang))
        
        # Fall back to generic rules if specific not found
        if not suite and target_lang == TargetLanguage.JAVA_SPRING:
            return JAVA_SERVICE_RULES
        if not suite and target_lang == TargetLanguage.REACT_JS:
            return REACT_COMPONENT_RULES
            
        return suite
    
    def validate_component(
        self,
        component_type: ComponentType,
        target_lang: TargetLanguage,
        code: str,
    ) -> List[Dict]:
        """Validate a component and return all failures."""
        suite = self.get_validation_suite(component_type, target_lang)
        if suite:
            return suite.validate(code)
        return []
    
    def register_suite(
        self,
        component_type: ComponentType,
        target_lang: TargetLanguage,
        suite: ComponentValidationSuite,
    ):
        """Register a new validation suite."""
        self._suites[(component_type, target_lang)] = suite
        log.info(f"Registered validation suite for {component_type.name} -> {target_lang.value}")


# Global registry
validation_registry = ComponentValidationRegistry()


def validate_component(
    component_type: ComponentType,
    target_lang: TargetLanguage,
    code: str,
) -> List[Dict]:
    """Convenience function to validate a component."""
    return validation_registry.validate_component(component_type, target_lang, code)
