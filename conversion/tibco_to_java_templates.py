"""
Tibco BW to Java Spring Integration Conversion Templates

Templates for converting Tibco BW processes to Spring Integration flows.
"""

from ingestion.file_type_registry import ComponentType
from conversion.template_base import ConversionTemplate


# ═══════════════════════════════════════════════════════════════════════════
# TIBCO BW PROCESS → SPRING INTEGRATION FLOW TEMPLATE
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

### Java Naming Standards
- Class name: PascalCase ending with Flow (e.g., OrderProcessingFlow)
- Package: com.macys.integration (lowercase, dot-separated)

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave bean definitions incomplete
- ALWAYS provide complete working implementations
- All imports must be explicit (no wildcard imports)

## Output Format
Return ONLY the complete Spring Integration configuration:
1. Package declaration: package com.macys.integration;
2. Imports (spring.integration, spring.integration.http, etc.)
3. @Configuration @EnableIntegration class
4. MessageChannel beans
5. IntegrationFlow beans with:
   - Source (HTTP inbound, etc.)
   - Transformers
   - Routers
   - Service activators
6. Error handling

No markdown fences. No explanations. NO PLACEHOLDERS.
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
# TIBCO BW ACTIVITY → SPRING COMPONENT TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

TIBCO_ACTIVITY_TO_SPRING = ConversionTemplate(
    name="Tibco Activity to Spring Component",
    source_type=ComponentType.ACTIVITY,
    target_type="Spring Service Component",
    prompt_template="""Convert this Tibco BW Activity/Subprocess to a Spring Service Component.

## Source (Tibco Activity)
```xml
{source_content}
```

## Conversion Rules

### Activity Types
- JDBC Activities → Service method with JdbcTemplate
- HTTP Activities → Service method with RestTemplate/WebClient
- Java Activities → Direct Java method implementation
- XSLT Transform → Transformer bean
- Parse/Render XML → JAXB or Jackson parsing

### Service Structure
- @Service annotated class
- @Autowired dependencies (JdbcTemplate, RestTemplate, etc.)
- Individual methods for each activity

### Error Handling
- Try-catch blocks for exception handling
- Custom exceptions for business errors
- Logging with SLF4J

### Java Naming Standards
- Class name: PascalCase ending with Service (e.g., OrderService)
- Method names: camelCase (e.g., processOrder, fetchCustomer)
- Package: com.macys.service (lowercase, dot-separated)

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave method bodies empty
- ALWAYS provide complete working implementations
- All imports must be explicit (no wildcard imports)

## Output Format
Return ONLY the complete Spring Service:
1. Package declaration: package com.macys.service;
2. Imports (org.springframework.stereotype, org.springframework.jdbc, etc.)
3. @Service class with PascalCase name
4. @Autowired fields for dependencies
5. Public methods implementing activity logic
6. Private helper methods as needed

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must have @Service annotation",
        "Must use PascalCase class name ending with Service",
        "Must use camelCase method names",
        "Must use lowercase package names",
    ],
)
