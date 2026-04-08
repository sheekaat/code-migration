"""
C# to Java Spring Boot Conversion Templates

Templates for converting C# code to Java Spring Boot:
- Controllers → @RestController
- Entities → @Entity (JPA)
- Services, Repositories, DTOs
"""

from ingestion.file_type_registry import ComponentType
from conversion.template_base import ConversionTemplate


# ═══════════════════════════════════════════════════════════════════════════
# C# CONTROLLER → JAVA RESTCONTROLLER TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

CSHARP_CONTROLLER_TO_JAVA = ConversionTemplate(
    name="C# Controller to Java Controller",
    source_type=ComponentType.SERVICE,
    target_type="Spring RestController",
    prompt_template="""Convert this C# Controller to a Java Spring Boot 3 RestController.

## Source (C# Controller)
```csharp
{source_content}
```

## Conversion Rules

### CRITICAL: Preserve API Endpoint URLs
- MUST keep the EXACT same URL paths from C# routes
- Example: [Route("api/users/{id}")] → @GetMapping("/api/users/{id}")
- Concatenate parent Route prefix with action route template
- Do NOT change URL patterns - backward compatibility is essential

### Class Structure
- Controller class → @RestController
- Route attributes → @RequestMapping on class (if base path)
- Action methods → @GetMapping/@PostMapping/@PutMapping/@DeleteMapping with FULL path
- Route parameters → @PathVariable with exact parameter names
- Query parameters → @RequestParam with exact parameter names
- Body parameters → @RequestBody

### Dependency Injection
- Constructor injection → Spring constructor injection
- Service dependencies → @Autowired fields or constructor params

### Return Types
- IActionResult → ResponseEntity<T>
- ViewResult → ResponseEntity with body
- JsonResult → ResponseEntity with JSON body
- FileResult → ResponseEntity with Resource

### HTTP Methods (with FULL path preservation)
- [HttpGet("path")] → @GetMapping("/full/path")
- [HttpPost("path")] → @PostMapping("/full/path")
- [HttpPut("path")] → @PutMapping("/full/path")
- [HttpDelete("path")] → @DeleteMapping("/full/path")

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

### Java Naming Standards
- Class name: PascalCase ending with Controller (e.g., UserController)
- Method names: camelCase (e.g., getUserById)
- Package: com.macys.controller (use lowercase, dot-separated)

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave method bodies empty
- NEVER use "// Implementation here" or similar comments
- ALWAYS provide complete working implementations
- If you don't know the exact implementation, provide the most reasonable Spring Boot equivalent
- All imports must be explicit (no wildcard imports)
- All generic types must be properly specified (no raw types)
- All methods must have return statements matching declared return type
- All exception handling must use proper Spring Boot patterns (@ExceptionHandler or try-catch)
- Constructor injection is MANDATORY for all dependencies

## Output Format
Return ONLY the complete Java controller:
1. Package declaration: package com.macys.controller;
2. Imports (spring.web.bind.annotation, org.springframework.http.*, etc.)
3. @RestController class with PascalCase name
4. @RequestMapping base path (if applicable)
5. Private final fields for dependencies with proper types
6. Constructor with @Autowired for all dependencies
7. Complete endpoint methods with EXACT URL paths from C#
8. Proper ResponseEntity returns (no void methods unless truly void)
9. Complete method bodies with actual implementation logic

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must have @RestController annotation",
        "Must use @GetMapping/@PostMapping with full paths",
        "Must preserve original API URL patterns exactly",
        "Must use ResponseEntity for responses",
        "Must use PascalCase class name ending with Controller",
        "Must use camelCase method names",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# C# ENTITY → JAVA JPA ENTITY TEMPLATE
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

### CRITICAL: Java Naming Standards
- Class name: PascalCase (e.g., CustomerOrder, UserProfile)
- Field names: camelCase (e.g., firstName, orderDate)
- Package: com.macys.entity (lowercase, singular)
- Table name: snake_case matching database table (use @Table(name="..."))
- Column names: snake_case matching database columns (use @Column(name="..."))

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
- Auto-properties with private setter → @Column(updatable=false) or custom setter

### Data Types
- int → int or Integer
- long → long or Long
- string → String
- bool → boolean
- DateTime → LocalDateTime
- decimal → BigDecimal
- Guid → UUID
- byte[] → byte[] or Blob
- Nullable<T> → Optional<T> or boxed type

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

### Table/Column Name Preservation
- If C# entity maps to specific database table, use @Table(name="exact_table_name")
- If C# property maps to specific column, use @Column(name="exact_column_name")
- Preserve exact database naming for backward compatibility

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave field definitions incomplete
- NEVER skip relationship annotations
- ALWAYS provide complete entity with ALL fields from C#
- If unsure about a field type, use the most reasonable Java equivalent
- All imports must be explicit (no wildcard imports)
- Use proper generic types for collections (List<Entity>, not raw List)
- Always provide proper constructors (default + all-args recommended)
- Include proper equals/hashCode implementations (Lombok @Data handles this)

## Output Format
Return ONLY the complete Java entity:
1. Package declaration: package com.macys.entity;
2. Imports (javax.persistence, lombok if used, java.time.*, etc.)
3. @Entity @Table(name="...") class with PascalCase name matching the C# entity
4. @Id @GeneratedValue primary key field
5. ALL fields with proper JPA annotations (@Column, @ManyToOne, etc.)
6. Relationship annotations with proper mappedBy and cascade settings
7. Constructors (no-arg + all-args) - use Lombok @NoArgsConstructor @AllArgsConstructor
8. Getters/setters (or use Lombok @Data/@Getter/@Setter)

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must have @Entity annotation",
        "Must have @Id field",
        "Must convert DataAnnotations to JPA annotations",
        "Must use proper relationship mappings",
        "Must use PascalCase class names",
        "Must use camelCase field names",
        "Must use lowercase package names",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# C# REPOSITORY → JAVA REPOSITORY TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

CSHARP_REPOSITORY_TO_JAVA = ConversionTemplate(
    name="C# Repository to Java Repository",
    source_type=ComponentType.DATA_ACCESS,
    target_type="Spring Data Repository",
    prompt_template="""Convert this C# Repository/Data Access to a Java Spring Data JPA Repository.

## Source (C# Repository)
```csharp
{source_content}
```

## Conversion Rules

### Interface Structure
- Repository interface → extends JpaRepository<Entity, ID>
- @Repository annotation on the interface

### Method Naming
- GetById → findById (returns Optional<Entity>)
- GetAll → findAll (returns List<Entity>)
- Add/Insert → save (returns Entity)
- Update → save (returns Entity)
- Delete/Remove → deleteById (returns void)
- FindByXxx → findByXxx (Spring Data JPA query methods)

### Query Methods
- Use Spring Data JPA method naming conventions
- @Query for complex JPQL queries
- @Modifying for update/delete operations

### Java Naming Standards
- Interface name: PascalCase ending with Repository (e.g., UserRepository)
- Package: com.macys.repository (lowercase, dot-separated)

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave method bodies empty
- ALWAYS provide complete working interface definitions
- All imports must be explicit (no wildcard imports)

## Output Format
Return ONLY the complete Java repository:
1. Package declaration: package com.macys.repository;
2. Imports (org.springframework.data.jpa.repository, org.springframework.stereotype, etc.)
3. @Repository interface extending JpaRepository<Entity, ID>
4. Query methods using Spring Data JPA conventions
5. @Query annotations for complex queries

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must have @Repository annotation",
        "Must extend JpaRepository<Entity, ID>",
        "Must use PascalCase interface name ending with Repository",
        "Must use lowercase package names",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# C# DTO → JAVA DTO/RECORD TEMPLATE
# ═══════════════════════════════════════════════════════════════════════════

CSHARP_DTO_TO_JAVA = ConversionTemplate(
    name="C# DTO to Java DTO",
    source_type=ComponentType.CLASS,
    target_type="Java DTO/Record",
    prompt_template="""Convert this C# DTO/ViewModel to a Java DTO or Record.

## Source (C# DTO/ViewModel)
```csharp
{source_content}
```

## Conversion Rules

### Structure Options
- Record (Java 14+) for immutable DTOs
- Class with Lombok @Data for mutable DTOs
- Validation annotations with Jakarta Validation

### Validation
- [Required] → @NotNull or @NotBlank
- [StringLength] → @Size
- [Range] → @Min/@Max
- [EmailAddress] → @Email
- [DataType] → appropriate Java type

### Java Naming Standards
- Class/Record name: PascalCase (e.g., UserRequestDto, OrderResponseDto)
- Field names: camelCase (e.g., firstName, orderDate)
- Package: com.macys.dto (lowercase, dot-separated)

### CRITICAL: Compilable Code Requirements
- NEVER use TODO comments or placeholder code
- NEVER leave field definitions incomplete
- ALWAYS provide complete working class/record with ALL fields from C#

## Output Format
Return ONLY the complete Java DTO:
1. Package declaration: package com.macys.dto;
2. Imports (lombok if used, jakarta.validation if used, etc.)
3. public record or @Data class with PascalCase name
4. ALL fields with proper validation annotations
5. Constructors (for class) or compact canonical constructor (for record)

No markdown fences. No explanations. NO PLACEHOLDERS.
""",
    validation_rules=[
        "Must use PascalCase class/record name",
        "Must use camelCase field names",
        "Must use lowercase package names",
        "Must include validation annotations matching DataAnnotations",
    ],
)
