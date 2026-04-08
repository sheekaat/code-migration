"""
Dependency Analyzer for Dynamic POM Generation

Analyzes converted code to determine required Maven dependencies
and application.properties settings.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set, List, Dict, Optional
import re


@dataclass
class Dependency:
    """Maven dependency definition."""
    group_id: str
    artifact_id: str
    version: Optional[str] = None
    scope: Optional[str] = None
    optional: bool = False
    
    def to_xml(self) -> str:
        xml = f"""    <dependency>
      <groupId>{self.group_id}</groupId>
      <artifactId>{self.artifact_id}</artifactId>"""
        if self.version:
            xml += f"\n      <version>{self.version}</version>"
        if self.scope:
            xml += f"\n      <scope>{self.scope}</scope>"
        if self.optional:
            xml += "\n      <optional>true</optional>"
        xml += "\n    </dependency>"
        return xml


@dataclass
class ProjectRequirements:
    """Detected project requirements from code analysis."""
    # Core Spring
    needs_web: bool = False
    needs_webflux: bool = False
    needs_data_jpa: bool = False
    needs_data_jdbc: bool = False
    needs_security: bool = False
    needs_validation: bool = False
    needs_integration: bool = False
    needs_batch: bool = False
    needs_cache: bool = False
    needs_actuator: bool = False
    
    # Database
    database_type: str = "mysql"  # mysql, postgresql, oracle, h2
    needs_flyway: bool = False
    needs_liquibase: bool = False
    
    # Additional Libraries
    needs_lombok: bool = False
    needs_mapstruct: bool = False
    needs_swagger: bool = False
    needs_jackson: bool = False
    
    # Testing
    needs_testcontainers: bool = False
    
    # Custom properties
    custom_properties: Dict[str, str] = field(default_factory=dict)
    
    def get_dependencies(self) -> List[Dependency]:
        """Generate list of required Maven dependencies."""
        deps = []
        
        # Core Spring Boot Starters
        if self.needs_webflux:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-webflux"))
        elif self.needs_web:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-web"))
        
        if self.needs_data_jpa:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-data-jpa"))
        
        if self.needs_data_jdbc:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-data-jdbc"))
        
        if self.needs_security:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-security"))
            deps.append(Dependency("org.springframework.security", "spring-security-test", scope="test"))
        
        if self.needs_validation:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-validation"))
        
        if self.needs_integration:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-integration"))
            deps.append(Dependency("org.springframework.integration", "spring-integration-http"))
        
        if self.needs_batch:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-batch"))
        
        if self.needs_cache:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-cache"))
            deps.append(Dependency("com.github.ben-manes.caffeine", "caffeine"))
        
        if self.needs_actuator:
            deps.append(Dependency("org.springframework.boot", "spring-boot-starter-actuator"))
        
        # Database Drivers
        if self.database_type == "mysql":
            deps.append(Dependency("com.mysql", "mysql-connector-j", scope="runtime"))
        elif self.database_type == "postgresql":
            deps.append(Dependency("org.postgresql", "postgresql", scope="runtime"))
        elif self.database_type == "oracle":
            deps.append(Dependency("com.oracle.database.jdbc", "ojdbc11", scope="runtime"))
        elif self.database_type == "h2":
            deps.append(Dependency("com.h2database", "h2", scope="runtime"))
        
        # Migration Tools
        if self.needs_flyway:
            deps.append(Dependency("org.flywaydb", "flyway-core"))
        if self.needs_liquibase:
            deps.append(Dependency("org.liquibase", "liquibase-core"))
        
        # Utility Libraries
        if self.needs_lombok:
            deps.append(Dependency("org.projectlombok", "lombok", optional=True))
        
        if self.needs_mapstruct:
            deps.append(Dependency("org.mapstruct", "mapstruct", version="1.5.5.Final"))
            deps.append(Dependency("org.mapstruct", "mapstruct-processor", version="1.5.5.Final", scope="provided"))
        
        if self.needs_swagger:
            deps.append(Dependency("org.springdoc", "springdoc-openapi-starter-webmvc-ui", version="2.3.0"))
        
        # Testing
        deps.append(Dependency("org.springframework.boot", "spring-boot-starter-test", scope="test"))
        if self.needs_testcontainers:
            deps.append(Dependency("org.testcontainers", "junit-jupiter", scope="test"))
            if self.database_type in ["mysql", "postgresql"]:
                deps.append(Dependency("org.testcontainers", self.database_type, scope="test"))
        
        return deps
    
    def get_application_properties(self) -> str:
        """Generate application.properties content."""
        props = []
        
        # Application Info
        props.append("spring.application.name=migrated-app")
        props.append("server.port=8080")
        props.append("")
        
        # Database Configuration
        if self.needs_data_jpa or self.needs_data_jdbc:
            props.append("# Database Configuration")
            
            if self.database_type == "mysql":
                props.append("spring.datasource.url=jdbc:mysql://localhost:3306/migrated_db")
                props.append("spring.datasource.driver-class-name=com.mysql.cj.jdbc.Driver")
            elif self.database_type == "postgresql":
                props.append("spring.datasource.url=jdbc:postgresql://localhost:5432/migrated_db")
                props.append("spring.datasource.driver-class-name=org.postgresql.Driver")
            elif self.database_type == "oracle":
                props.append("spring.datasource.url=jdbc:oracle:thin:@localhost:1521:ORCL")
                props.append("spring.datasource.driver-class-name=oracle.jdbc.OracleDriver")
            elif self.database_type == "h2":
                props.append("spring.datasource.url=jdbc:h2:mem:testdb")
                props.append("spring.datasource.driver-class-name=org.h2.Driver")
            
            props.append("spring.datasource.username=${DB_USERNAME:root}")
            props.append("spring.datasource.password=${DB_PASSWORD:root}")
            props.append("")
            
            # JPA Configuration
            if self.needs_data_jpa:
                props.append("# JPA Configuration")
                props.append("spring.jpa.hibernate.ddl-auto=validate")
                props.append("spring.jpa.show-sql=true")
                
                if self.database_type == "mysql":
                    props.append("spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.MySQLDialect")
                elif self.database_type == "postgresql":
                    props.append("spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.PostgreSQLDialect")
                elif self.database_type == "oracle":
                    props.append("spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.OracleDialect")
                elif self.database_type == "h2":
                    props.append("spring.jpa.properties.hibernate.dialect=org.hibernate.dialect.H2Dialect")
                
                props.append("")
        
        # Migration Tools
        if self.needs_flyway:
            props.append("# Flyway Migration")
            props.append("spring.flyway.enabled=true")
            props.append("spring.flyway.locations=classpath:db/migration")
            props.append("")
        
        if self.needs_liquibase:
            props.append("# Liquibase Migration")
            props.append("spring.liquibase.enabled=true")
            props.append("spring.liquibase.change-log=classpath:db/changelog/db.changelog-master.yaml")
            props.append("")
        
        # Cache Configuration
        if self.needs_cache:
            props.append("# Cache Configuration")
            props.append("spring.cache.type=caffeine")
            props.append("spring.cache.caffeine.spec=maximumSize=1000,expireAfterWrite=10m")
            props.append("")
        
        # Actuator
        if self.needs_actuator:
            props.append("# Actuator Endpoints")
            props.append("management.endpoints.web.exposure.include=health,info,metrics")
            props.append("management.endpoint.health.show-details=when-authorized")
            props.append("")
        
        # Logging
        props.append("# Logging")
        props.append("logging.level.com.macys=INFO")
        if self.needs_security:
            props.append("logging.level.org.springframework.security=INFO")
        if self.needs_integration:
            props.append("logging.level.org.springframework.integration=INFO")
        props.append("")
        
        # Custom properties
        if self.custom_properties:
            props.append("# Custom Properties")
            for key, value in self.custom_properties.items():
                props.append(f"{key}={value}")
            props.append("")
        
        return "\n".join(props)


class DependencyAnalyzer:
    """Analyzes converted code to detect required dependencies."""
    
    # Pattern definitions for code analysis
    PATTERNS = {
        'needs_web': [
            r'@RestController',
            r'@Controller',
            r'@RequestMapping',
            r'@GetMapping',
            r'@PostMapping',
            r'@PutMapping',
            r'@DeleteMapping',
        ],
        'needs_webflux': [
            r'@RestController.*reactive',
            r'RouterFunction',
            r'Mono<',
            r'Flux<',
        ],
        'needs_data_jpa': [
            r'@Entity',
            r'@Table\(name',
            r'@Id',
            r'extends JpaRepository',
            r'JpaRepository<',
        ],
        'needs_data_jdbc': [
            r'JdbcTemplate',
            r'@JdbcRepository',
        ],
        'needs_security': [
            r'@EnableWebSecurity',
            r'@PreAuthorize',
            r'@Secured',
            r'SecurityFilterChain',
            r'AuthenticationManager',
        ],
        'needs_validation': [
            r'@Valid',
            r'@NotNull',
            r'@NotBlank',
            r'@Size\(',
            r'@Email',
            r'@Pattern',
        ],
        'needs_integration': [
            r'@EnableIntegration',
            r'IntegrationFlow',
            r'MessageChannel',
            r'@ServiceActivator',
        ],
        'needs_batch': [
            r'@EnableBatchProcessing',
            r'JobBuilder',
            r'StepBuilder',
        ],
        'needs_cache': [
            r'@EnableCaching',
            r'@Cacheable',
            r'@CacheEvict',
            r'@CachePut',
        ],
        'needs_lombok': [
            r'@Slf4j',
            r'@Log4j2',
            r'@Data',
            r'@Getter',
            r'@Setter',
            r'@NoArgsConstructor',
            r'@AllArgsConstructor',
            r'@Builder',
        ],
        'needs_mapstruct': [
            r'@Mapper',
            r'Mappers\.getMapper',
        ],
        'needs_swagger': [
            r'@OpenAPIDefinition',
            r'@Operation',
            r'@Tag\(name',
        ],
        'needs_flyway': [
            r'db/migration',
        ],
        'needs_liquibase': [
            r'db/changelog',
        ],
    }
    
    DATABASE_PATTERNS = {
        'mysql': [r'MySQLDialect', r'mysql://', r'com\.mysql'],
        'postgresql': [r'PostgreSQLDialect', r'postgresql://', r'org\.postgresql'],
        'oracle': [r'OracleDialect', r'oracle:thin', r'OracleDriver'],
        'h2': [r'H2Dialect', r'h2:mem', r'org\.h2'],
    }
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.requirements = ProjectRequirements()
    
    def analyze_project(self) -> ProjectRequirements:
        """Analyze all Java files in output directory."""
        java_files = list(self.output_dir.rglob("*.java"))
        properties_files = list(self.output_dir.rglob("*.properties"))
        yaml_files = list(self.output_dir.rglob("*.yml")) + list(self.output_dir.rglob("*.yaml"))
        
        # Analyze Java source files
        for java_file in java_files:
            try:
                content = java_file.read_text(encoding='utf-8')
                self._analyze_java_file(content)
            except Exception as e:
                print(f"Warning: Could not analyze {java_file}: {e}")
        
        # Check for migration scripts
        for prop_file in properties_files + yaml_files:
            try:
                content = prop_file.read_text(encoding='utf-8')
                self._analyze_config_file(content)
            except Exception as e:
                print(f"Warning: Could not analyze {prop_file}: {e}")
        
        # Check for migration directories
        if (self.output_dir / "src" / "main" / "resources" / "db" / "migration").exists():
            self.requirements.needs_flyway = True
        if (self.output_dir / "src" / "main" / "resources" / "db" / "changelog").exists():
            self.requirements.needs_liquibase = True
        
        return self.requirements
    
    def _analyze_java_file(self, content: str) -> None:
        """Analyze a single Java file content."""
        for feature, patterns in self.PATTERNS.items():
            if any(re.search(pattern, content) for pattern in patterns):
                setattr(self.requirements, feature, True)
        
        # Detect database type
        for db_type, patterns in self.DATABASE_PATTERNS.items():
            if any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns):
                self.requirements.database_type = db_type
                break
    
    def _analyze_config_file(self, content: str) -> None:
        """Analyze configuration file content."""
        if 'flyway' in content.lower():
            self.requirements.needs_flyway = True
        if 'liquibase' in content.lower():
            self.requirements.needs_liquibase = True
        if 'testcontainers' in content.lower():
            self.requirements.needs_testcontainers = True


def generate_dynamic_pom(requirements: ProjectRequirements, artifact_id: str, source_lang: str) -> str:
    """Generate a dynamic pom.xml based on detected requirements."""
    deps_xml = "\n".join([dep.to_xml() for dep in requirements.get_dependencies()])
    
    pom = f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>

  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.0</version>
    <relativePath/>
  </parent>

  <groupId>com.macys</groupId>
  <artifactId>{artifact_id}</artifactId>
  <version>1.0.0-SNAPSHOT</version>
  <name>{artifact_id}</name>
  <description>Auto-migrated from {source_lang} using Code Migration Platform</description>

  <properties>
    <java.version>17</java.version>
    <mapstruct.version>1.5.5.Final</mapstruct.version>
    <springdoc.version>2.3.0</springdoc.version>
  </properties>

  <dependencies>
{deps_xml}
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
        <configuration>
          <excludes>
            <exclude>
              <groupId>org.projectlombok</groupId>
              <artifactId>lombok</artifactId>
            </exclude>
          </excludes>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
"""
    return pom
