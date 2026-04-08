"""
VB6 to Java Spring Boot Conversion Templates

Templates for converting VB6 Classes to Java Spring services.
"""

from ingestion.file_type_registry import ComponentType
from conversion.template_base import ConversionTemplate


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
- Property Get/Let/Set → getter/setter methods or use Lombok @Data
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
- Variant → Object or specific type (prefer specific)
- Date → LocalDateTime or Instant
- Currency → BigDecimal
- Byte → byte
- Single → float
- Currency → BigDecimal (for money calculations)

### Data Access
- ADODB Recordset → Spring Data JPA Repository
- Connection → EntityManager or JdbcTemplate
- Recordset.Fields → Entity fields
- MoveFirst/MoveNext/EOF → Repository methods returning List<Entity>
- AddNew → entity constructor + save
- Update → save
- Delete → deleteById

### Error Handling
- On Error GoTo → try/catch/finally blocks
- Err.Number → specific Exception types
- Err.Description → Exception message
- Resume Next → careful exception handling with logging
- RaiseError → throw new CustomException()

### Annotations
- @Service on class
- @Transactional for database operations
- @Autowired or constructor injection for dependencies
- @Slf4j for logging (Lombok)

### Java Naming Standards
- Class name: PascalCase (e.g., OrderService, CustomerManager)
- Method names: camelCase (e.g., processOrder, getCustomerById)
- Field names: camelCase
- Package: com.macys.service (lowercase, dot-separated)

### Lombok (recommended)
- @Slf4j for logging
- @RequiredArgsConstructor for constructor injection
- Use constructor injection instead of field injection

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave method bodies empty
- NEVER use "// Implementation here" or similar comments
- ALWAYS provide complete working implementations
- All imports must be explicit (no wildcard imports)
- All methods must have proper return statements

## Output Format
Return ONLY the complete Java class:
1. Package declaration: package com.macys.service;
2. Imports (org.springframework, lombok, java.time, java.math, etc.)
3. @Service @Slf4j class with PascalCase name
4. Private final fields for dependencies
5. Constructor with @Autowired for all dependencies
6. Public business methods with complete implementations
7. Private helper methods as needed

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must have @Service annotation",
        "Must use proper Java naming conventions (PascalCase class, camelCase methods)",
        "Must convert ADODB to JPA/Repository",
        "Must handle On Error as try/catch",
        "Must preserve all business logic exactly",
        "Must use constructor injection",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# VB6 FORM → JAVA UI SERVICE TEMPLATE (for forms that need backend logic)
# ═══════════════════════════════════════════════════════════════════════════

VB6_FORM_TO_JAVA_SERVICE = ConversionTemplate(
    name="VB6 Form to Java UI Service",
    source_type=ComponentType.FORM,
    target_type="Spring UI Service",
    prompt_template="""Convert this VB6 Form to a Java Spring Boot Service handling UI logic.

## Source (VB6 Form)
```vb6
{source_content}
```

## Conversion Rules

### Form Logic Conversion
- Form-level variables → Service fields
- Control event handlers → Service methods
- Form_Load initialization → @PostConstruct init method or constructor
- Form validation → Validation methods

### State Management
- Form state → State object or DTO
- User input handling → Input DTOs with validation
- Session variables → Session-scoped beans or cache

### Event Handlers as Methods
- _Click events → action methods
- _Change events → update methods with validation
- _Validate events → validation methods returning boolean

### Data Types
- VB6 types → Java types (Integer→int, String→String, etc.)
- Control values → DTO fields
- Arrays → List<T>

### Annotations
- @Service for business logic
- @Validated for input validation
- @SessionScope if session state needed

### Java Naming Standards
- Class name: PascalCase ending with Service (e.g., OrderEntryService)
- Method names: camelCase describing action (e.g., submitOrder, validateCustomer)
- Package: com.macys.service.ui or com.macys.service.workflow

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave method bodies empty
- ALWAYS provide complete working implementations

## Output Format
Return ONLY the complete Java service:
1. Package declaration
2. Imports
3. @Service class with PascalCase name
4. Private fields for state
5. Constructor with dependencies
6. Public methods for form actions
7. Private validation/helper methods

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must have @Service annotation",
        "Must use PascalCase class name ending with Service",
        "Must convert form events to service methods",
        "Must handle form validation",
        "Must use proper Java naming conventions",
    ],
)
