"""
Component-Specific Conversion Templates

Provides targeted conversion strategies for different component types.
Each template includes:
- Source pattern recognition
- Target structure generation
- Specific LLM prompts
- Validation rules
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

from ingestion.file_type_registry import ComponentType, FileCategory
from shared.models import SourceLanguage, TargetLanguage
from shared.config import get_logger

log = get_logger(__name__)


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


# ═══════════════════════════════════════════════════════════════════════════
# VB6 FORM → REACT COMPONENT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

VB6_FORM_TO_REACT = ConversionTemplate(
    name="VB6 Form to React Component",
    source_type=ComponentType.FORM,
    target_type="React Functional Component",
    prompt_template="""Convert this VB6 Form to a React 18 functional component with TypeScript.

## Source (VB6 Form)
```vb6
{source_content}
```

## Conversion Rules

### UI Structure
- Convert VB6 controls to React JSX:
  - TextBox → <input type="text">
  - ComboBox → <select> or react-select
  - ListBox → <select multiple> or custom list component
  - CommandButton → <button>
  - Label → <label> or <span>
  - CheckBox → <input type="checkbox">
  - OptionButton → <input type="radio">
  - Frame/Panel → <div> with CSS
  - PictureBox → <img> or <div> with background-image
  - DataGrid → HTML table or react-table
  - Timer → useEffect with setInterval

### State Management
- Form-level variables → useState hooks
- Module-level globals → Context API or props
- Control values → controlled components (value + onChange)
- Form_Load → useEffect with empty dependency array []

### Event Handlers
- _Click → onClick handler
- _Change → onChange handler
- _KeyPress → onKeyDown/onKeyUp
- _DblClick → onDoubleClick
- _GotFocus → onFocus
- _LostFocus → onBlur

### Data Access
- ADODB Recordset → fetch() or axios with useEffect
- Field references → state variables
- MoveFirst/MoveNext → array iteration

### Error Handling
- On Error GoTo → try/catch blocks
- Error labels → separate error handler functions

## Output Format
Return ONLY the complete React component code:
1. Imports (React, hooks, any libraries)
2. Interface definitions for props/state
3. Main component function
4. Event handler functions
5. useEffect for initialization
6. JSX return
7. Export statement

No markdown fences. No explanations.
""",
    validation_rules=[
        "Must use functional component (not class)",
        "Must have useState for state management",
        "Must handle all original event handlers",
        "Must convert ADODB to fetch/API calls",
        "Must convert On Error to try/catch",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# VB6 CLASS → JAVA SERVICE TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

VB6_CLASS_TO_JAVA_SERVICE = ConversionTemplate(
    name="VB6 Class to Java Service",
    source_type=ComponentType.CLASS,
    target_type="Spring Service",
    prompt_template="""Convert this VB6 Class to a Java Spring Boot 3 Service.

## Source (VB6 Class)
```vb6
{source_content}
```

## Conversion Rules

### Class Structure
- VB6 Class → @Service annotated class
- Private fields → private instance variables
- Property Get/Let/Set → getter/setter methods
- Public methods → public methods
- Private methods → private methods

### Business Logic
- Preserve ALL conditional logic exactly
- Keep exact calculation logic
- Maintain validation rules
- Preserve error handling flow

### Data Types
- Integer → int or Integer
- Long → long or Long
- Double → double or Double
- String → String
- Boolean → boolean
- Variant → Object or specific type
- Date → LocalDateTime or Date
- Currency → BigDecimal

### Data Access
- ADODB Recordset → Spring Data JPA Repository
- Connection → EntityManager or JdbcTemplate
- Recordset.Fields → Entity fields
- MoveFirst/MoveNext/EOF → Repository methods with List

### Error Handling
- On Error GoTo → try/catch/finally
- Err.Number → Exception types
- Err.Description → Exception message
- Resume Next → careful exception handling

### Annotations
- @Service on class
- @Transactional for database operations
- @Autowired or constructor injection for dependencies

## Output Format
Return ONLY the complete Java class:
1. Package declaration
2. Imports
3. Class declaration with @Service
4. Fields
5. Constructor (if dependencies)
6. Public methods
7. Private helper methods

No markdown fences. No explanations.
""",
    validation_rules=[
        "Must have @Service annotation",
        "Must use proper Java naming conventions",
        "Must convert ADODB to JPA/Repository",
        "Must handle On Error as try/catch",
        "Must preserve all business logic",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# C# CONTROLLER → JAVA CONTROLLER TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

CSHARP_CONTROLLER_TO_JAVA = ConversionTemplate(
    name="C# Controller to Java Controller",
    source_type=ComponentType.SERVICE,  # In C#, controllers are often detected as service-like
    target_type="Spring RestController",
    prompt_template="""Convert this C# Controller to a Java Spring Boot 3 RestController.

## Source (C# Controller)
```csharp
{source_content}
```

## Conversion Rules

### Class Structure
- Controller class → @RestController
- Route attributes → @RequestMapping on class
- Action methods → @GetMapping/@PostMapping/etc.
- Route parameters → @PathVariable or @RequestParam
- Body parameters → @RequestBody

### Dependency Injection
- Constructor injection → Spring constructor injection
- Service dependencies → @Autowired fields or constructor params

### Return Types
- IActionResult → ResponseEntity<T>
- ViewResult → ResponseEntity with body
- JsonResult → ResponseEntity with JSON body
- FileResult → ResponseEntity with Resource

### HTTP Methods
- HttpGet → @GetMapping
- HttpPost → @PostMapping
- HttpPut → @PutMapping
- HttpDelete → @DeleteMapping

### Model Binding
- [FromBody] → @RequestBody
- [FromQuery] → @RequestParam
- [FromRoute] → @PathVariable
- [FromHeader] → @RequestHeader

### Validation
- DataAnnotations → Jakarta Validation (javax.validation)
- ModelState.IsValid → @Valid with BindingResult

### Async
- async Task<T> → CompletableFuture<T> or just T (Spring handles async)

## Output Format
Return ONLY the complete Java controller:
1. Package declaration
2. Imports (spring.web.bind.annotation, etc.)
3. @RestController class
4. @RequestMapping base path
5. Constructor with dependencies
6. Endpoint methods with proper annotations
7. ResponseEntity returns

No markdown fences. No explanations.
""",
    validation_rules=[
        "Must have @RestController annotation",
        "Must use @GetMapping/@PostMapping for endpoints",
        "Must use ResponseEntity for responses",
        "Must convert async/await properly",
        "Must preserve all route parameters",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# C# ENTITY → JAVA ENTITY TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

CSHARP_ENTITY_TO_JAVA = ConversionTemplate(
    name="C# Entity to Java Entity",
    source_type=ComponentType.ENTITY,
    target_type="JPA Entity",
    prompt_template="""Convert this C# Entity to a Java JPA Entity.

## Source (C# Entity/Model)
```csharp
{source_content}
```

## Conversion Rules

### Class Structure
- public class → @Entity public class
- Inherit from base → extend or embed

### Fields
- Properties → private fields with getters/setters
- [Key] → @Id
- [DatabaseGenerated] → @GeneratedValue
- [Required] → @Column(nullable=false)
- [MaxLength] → @Column(length=X)
- [ForeignKey] → @ManyToOne/@OneToMany with @JoinColumn
- [NotMapped] → @Transient

### Data Types
- int → int or Integer
- long → long or Long
- string → String
- bool → boolean
- DateTime → LocalDateTime
- decimal → BigDecimal
- Guid → UUID
- byte[] → byte[] or Blob

### Relationships
- ICollection<T> → List<T> or Set<T>
- One-to-many → @OneToMany with mappedBy
- Many-to-one → @ManyToOne with @JoinColumn
- Many-to-many → @ManyToMany with @JoinTable

### Lombok (optional but recommended)
- @Data for getters/setters/equals/hashCode
- @NoArgsConstructor
- @AllArgsConstructor
- @Builder for builder pattern

## Output Format
Return ONLY the complete Java entity:
1. Package declaration
2. Imports (javax.persistence, lombok if used)
3. @Entity class
4. @Id @GeneratedValue primary key
5. Fields with @Column annotations
6. Relationship annotations
7. Getters/setters (or @Data)

No markdown fences. No explanations.
""",
    validation_rules=[
        "Must have @Entity annotation",
        "Must have @Id field",
        "Must convert DataAnnotations to JPA annotations",
        "Must use proper relationship mappings",
        "Must use Java naming conventions",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# TIBCO PROCESS → SPRING INTEGRATION TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

TIBCO_PROCESS_TO_SPRING = ConversionTemplate(
    name="Tibco Process to Spring Integration",
    source_type=ComponentType.PROCESS,
    target_type="Spring Integration Flow",
    prompt_template="""Convert this Tibco BW Process to a Spring Integration flow.

## Source (Tibco Process)
```xml
{source_content}
```

## Conversion Rules

### Process Structure
- process → @Configuration class with IntegrationFlow beans
- activities → channel handlers/transformers
- transitions → MessageChannels with routing

### Activity Mappings
- HTTP Receiver → @ServiceActivator with Http.inboundGateway
- JDBC Query → JdbcTemplate query or Repository call
- Mapper → Transformer
- Publish to Subject → MessageChannel send
- Call Process → Service method invocation
- Log → Logger.info/debug
- Assign → Message header manipulation

### Data Handling
- process variables → Message headers or payload
- XPath mappings → SpEL expressions or custom transformers
- schema references → DTO classes

### Error Handling
- Catch activities → ErrorChannel handlers
- Transition on error → @Router with exception type routing

### Configuration
- @Configuration class
- @EnableIntegration
- IntegrationFlow bean definitions
- MessageChannel bean definitions

## Output Format
Return ONLY the complete Spring Integration configuration:
1. Package declaration
2. Imports (spring.integration, etc.)
3. @Configuration @EnableIntegration class
4. MessageChannel beans
5. IntegrationFlow beans with:
   - Source (HTTP inbound, etc.)
   - Transformers
   - Routers
   - Service activators
6. Error handling

No markdown fences. No explanations.
""",
    validation_rules=[
        "Must use @Configuration and @EnableIntegration",
        "Must define IntegrationFlow beans",
        "Must map HTTP Receiver to inbound gateway",
        "Must convert JDBC to JdbcTemplate or Repository",
        "Must handle process variables properly",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# TEMPLATE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

class TemplateRegistry:
    """Registry of all conversion templates."""
    
    def __init__(self):
        self._templates: Dict[tuple, ConversionTemplate] = {
            # (SourceLanguage, ComponentType, TargetLanguage) -> Template
            (SourceLanguage.VB6, ComponentType.FORM, TargetLanguage.REACT_JS): VB6_FORM_TO_REACT,
            (SourceLanguage.VB6, ComponentType.CLASS, TargetLanguage.JAVA_SPRING): VB6_CLASS_TO_JAVA_SERVICE,
            (SourceLanguage.VB6, ComponentType.DATA_ACCESS, TargetLanguage.JAVA_SPRING): VB6_CLASS_TO_JAVA_SERVICE,
            (SourceLanguage.VB6, ComponentType.SERVICE, TargetLanguage.JAVA_SPRING): VB6_CLASS_TO_JAVA_SERVICE,
            (SourceLanguage.VB6, ComponentType.MODULE, TargetLanguage.JAVA_SPRING): VB6_CLASS_TO_JAVA_SERVICE,
            
            (SourceLanguage.CSHARP, ComponentType.SERVICE, TargetLanguage.JAVA_SPRING): CSHARP_CONTROLLER_TO_JAVA,
            (SourceLanguage.CSHARP, ComponentType.CLASS, TargetLanguage.JAVA_SPRING): CSHARP_ENTITY_TO_JAVA,
            (SourceLanguage.CSHARP, ComponentType.DATA_ACCESS, TargetLanguage.JAVA_SPRING): CSHARP_ENTITY_TO_JAVA,
            (SourceLanguage.CSHARP, ComponentType.INTERFACE, TargetLanguage.JAVA_SPRING): None,  # Direct conversion
            (SourceLanguage.CSHARP, ComponentType.ENUM, TargetLanguage.JAVA_SPRING): None,  # Direct conversion
            
            (SourceLanguage.TIBCO_BW, ComponentType.PROCESS, TargetLanguage.JAVA_SPRING): TIBCO_PROCESS_TO_SPRING,
            (SourceLanguage.TIBCO_BW, ComponentType.ACTIVITY, TargetLanguage.JAVA_SPRING): TIBCO_PROCESS_TO_SPRING,
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
