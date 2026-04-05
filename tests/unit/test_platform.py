"""
Unit tests covering the core platform components.
Run with: pytest tests/ -v
"""

import pytest
from shared.models import (
    SourceFile, SourceLanguage, TargetLanguage,
    ComplexityTier, ArchitecturalPattern, WorkspaceManifest,
    DependencyGraph,
)
from analysis.engine import (
    CSharpParser, VB6Parser, TibcoBWParser, XAMLParser,
    classify_pattern, compute_complexity, build_dependency_graph,
)
from conversion.rule_engine.engine import RuleEngine
from validation.runner import SemanticDiff, SyntaxChecker


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def config():
    return {
        "analysis": {"complexity_red_threshold": 20, "complexity_amber_threshold": 10},
        "conversion": {"confidence_threshold": 0.75, "rule_engine_first": True},
        "llm": {"model": "claude-sonnet-4-20250514", "max_tokens": 8000, "chunk_size": 300},
    }


@pytest.fixture
def csharp_controller():
    return SourceFile(
        path="Controllers/CustomerController.cs",
        language=SourceLanguage.CSHARP,
        raw_content="""
using System;
using Microsoft.AspNetCore.Mvc;

[ApiController]
[Route("api/[controller]")]
public class CustomerController : ControllerBase
{
    private readonly ICustomerService _service;

    [HttpGet("{id}")]
    public async Task<IActionResult> GetById([FromRoute] int id)
    {
        var customer = await _service.GetByIdAsync(id);
        if (customer == null) return NotFound();
        return Ok(customer);
    }

    [HttpPost]
    public async Task<IActionResult> Create([FromBody] CustomerDto dto)
    {
        var result = await _service.CreateAsync(dto);
        return CreatedAtAction(nameof(GetById), new { id = result.Id }, result);
    }
}
""",
    )


@pytest.fixture
def vb6_form():
    return SourceFile(
        path="Forms/CustomerForm.frm",
        language=SourceLanguage.VB6,
        raw_content="""
Private Sub Form_Load()
    txtName.Text = ""
    Dim greeting As String
    greeting = "Hello" & " World"
    If True Then
        MsgBox "Loaded"
    End If
End Sub

Private Sub cmdSave_Click()
    Debug.Print "Saving..."
End Sub
""",
    )


@pytest.fixture
def tibco_process():
    return SourceFile(
        path="Processes/OrderProcess.bwp",
        language=SourceLanguage.TIBCO_BW,
        raw_content="""
<pd:ProcessDefinition xmlns:pd="http://xmlns.tibco.com/bw/process/2003">
  <pd:name>OrderProcess</pd:name>
  <activity name="ReceiveOrder" type="com.tibco.pe.core.HTTPReceiveEventSource"/>
  <activity name="PublishConfirmation" type="com.tibco.pe.core.PublishToSubject"/>
  <transition from="ReceiveOrder" to="PublishConfirmation"/>
</pd:ProcessDefinition>
""",
    )


# ─── Analysis Engine Tests ────────────────────────────────────────────────────

class TestCSharpParser:
    def test_parses_class(self, csharp_controller):
        parser = CSharpParser()
        uir = parser.parse(csharp_controller)
        assert uir.kind == "file"
        class_nodes = [n for n in uir.children if n.kind == "class"]
        assert any("CustomerController" in n.name for n in class_nodes)

    def test_parses_methods(self, csharp_controller):
        parser = CSharpParser()
        uir = parser.parse(csharp_controller)
        method_nodes = [n for n in uir.children if n.kind == "method"]
        method_names = [n.name for n in method_nodes]
        assert "GetById" in method_names
        assert "Create" in method_names

    def test_parses_imports(self, csharp_controller):
        parser = CSharpParser()
        uir = parser.parse(csharp_controller)
        imports = [n for n in uir.children if n.kind == "import"]
        assert len(imports) >= 2


class TestVB6Parser:
    def test_parses_subs(self, vb6_form):
        parser = VB6Parser()
        uir = parser.parse(vb6_form)
        methods = [n for n in uir.children if n.kind == "method"]
        names = [n.name for n in methods]
        assert "Form_Load" in names
        assert "cmdSave_Click" in names


class TestTibcoBWParser:
    def test_parses_activities(self, tibco_process):
        parser = TibcoBWParser()
        uir = parser.parse(tibco_process)
        activities = [n for n in uir.children if n.kind == "activity"]
        assert len(activities) >= 2

    def test_parses_transitions(self, tibco_process):
        parser = TibcoBWParser()
        uir = parser.parse(tibco_process)
        transitions = [n for n in uir.children if n.kind == "transition"]
        assert len(transitions) >= 1


class TestPatternClassifier:
    def test_controller_pattern(self, csharp_controller):
        pattern = classify_pattern(csharp_controller)
        assert pattern == ArchitecturalPattern.CONTROLLER

    def test_form_pattern(self, vb6_form):
        pattern = classify_pattern(vb6_form)
        assert pattern == ArchitecturalPattern.UI_FORM

    def test_pubsub_pattern(self, tibco_process):
        pattern = classify_pattern(tibco_process)
        assert pattern == ArchitecturalPattern.PUBSUB


class TestComplexityScorer:
    def test_simple_file_is_green(self, config):
        sf = SourceFile(
            path="test.cs",
            language=SourceLanguage.CSHARP,
            raw_content="public class Foo { public string Name { get; set; } }",
        )
        score, tier = compute_complexity(sf, config)
        assert tier == ComplexityTier.GREEN

    def test_complex_file_is_red(self, config):
        sf = SourceFile(
            path="complex.cs",
            language=SourceLanguage.CSHARP,
            raw_content=" if ".join(["x = 1"] * 25),
        )
        score, tier = compute_complexity(sf, config)
        assert tier in (ComplexityTier.AMBER, ComplexityTier.RED)


class TestDependencyGraph:
    def test_build_graph(self):
        f1 = SourceFile(path="a.cs", language=SourceLanguage.CSHARP,
                        raw_content="using MyApp.Services;\nclass A {}")
        f2 = SourceFile(path="services/MyApp/Services/OrderService.cs",
                        language=SourceLanguage.CSHARP,
                        raw_content="class OrderService {}")
        graph = build_dependency_graph([f1, f2])
        assert "a.cs" in graph.nodes
        order = graph.topological_order()
        assert len(order) == 2

    def test_topological_order_leaves_first(self):
        root = SourceFile(path="root.cs", language=SourceLanguage.CSHARP,
                          raw_content="using MyApp.Leaf;")
        leaf = SourceFile(path="leaf.cs", language=SourceLanguage.CSHARP,
                          raw_content="class Leaf {}")
        graph = DependencyGraph()
        graph.add_file(root)
        graph.add_file(leaf)
        graph.add_dependency("root.cs", "leaf.cs")
        order = graph.topological_order()
        assert order.index("leaf.cs") < order.index("root.cs")


# ─── Rule Engine Tests ────────────────────────────────────────────────────────

class TestRuleEngine:
    def test_csharp_annotations(self, config, csharp_controller):
        engine = RuleEngine(config)
        result = engine.convert(csharp_controller, TargetLanguage.JAVA_SPRING)
        assert "@RestController" in result.converted_code
        assert "@GetMapping" in result.converted_code
        assert "[HttpPost]" in result.converted_code or "@PostMapping" in result.converted_code

    def test_csharp_from_body(self, config, csharp_controller):
        engine = RuleEngine(config)
        result = engine.convert(csharp_controller, TargetLanguage.JAVA_SPRING)
        assert "@RequestBody" in result.converted_code
        assert "[FromBody]" not in result.converted_code

    def test_csharp_from_route(self, config, csharp_controller):
        engine = RuleEngine(config)
        result = engine.convert(csharp_controller, TargetLanguage.JAVA_SPRING)
        assert "@PathVariable" in result.converted_code

    def test_vb6_sub_to_function(self, config, vb6_form):
        engine = RuleEngine(config)
        result = engine.convert(vb6_form, TargetLanguage.REACT_JS)
        assert "function Form_Load" in result.converted_code
        assert "function cmdSave_Click" in result.converted_code

    def test_vb6_if_then(self, config, vb6_form):
        engine = RuleEngine(config)
        result = engine.convert(vb6_form, TargetLanguage.REACT_JS)
        assert "if (" in result.converted_code

    def test_vb6_string_concat(self, config, vb6_form):
        engine = RuleEngine(config)
        result = engine.convert(vb6_form, TargetLanguage.REACT_JS)
        assert " + " in result.converted_code

    def test_vb6_msgbox(self, config, vb6_form):
        engine = RuleEngine(config)
        result = engine.convert(vb6_form, TargetLanguage.REACT_JS)
        assert "alert(" in result.converted_code
        assert "MsgBox" not in result.converted_code

    def test_csharp_linq(self, config):
        sf = SourceFile(
            path="service.cs", language=SourceLanguage.CSHARP,
            raw_content="var x = list.Where(i => i.Active).Select(i => i.Name).ToList();",
        )
        engine = RuleEngine(config)
        result = engine.convert(sf, TargetLanguage.JAVA_SPRING)
        assert ".stream().filter(" in result.converted_code
        assert ".collect(Collectors.toList())" in result.converted_code

    def test_type_mapping_string(self, config):
        sf = SourceFile(
            path="dto.cs", language=SourceLanguage.CSHARP,
            raw_content="public string Name { get; set; }\npublic bool Active { get; set; }",
        )
        engine = RuleEngine(config)
        result = engine.convert(sf, TargetLanguage.JAVA_SPRING)
        assert "String" in result.converted_code
        assert "boolean" in result.converted_code

    def test_confidence_increases_with_matches(self, config, csharp_controller):
        engine = RuleEngine(config)
        result = engine.convert(csharp_controller, TargetLanguage.JAVA_SPRING)
        assert result.confidence > 0.5
        assert len(result.rules_applied) > 3


# ─── Validation Tests ────────────────────────────────────────────────────────

class TestSemanticDiff:
    def test_detects_missing_rest_controller(self):
        diff = SemanticDiff()
        source = "[ApiController] public class Foo : ControllerBase {}"
        converted = "public class Foo {}"
        issues = diff.diff(source, converted, TargetLanguage.JAVA_SPRING)
        assert any("RestController" in i for i in issues)

    def test_detects_missing_react_import(self):
        diff = SemanticDiff()
        source = "Form_Load"
        converted = "const App = () => <div>Hello</div>;"
        issues = diff.diff(source, converted, TargetLanguage.REACT_JS)
        assert any("React" in i for i in issues)

    def test_detects_high_todo_density(self):
        diff = SemanticDiff()
        converted = "\n".join([f"// TODO: fix line {i}" for i in range(50)])
        issues = diff.diff("source", converted, TargetLanguage.JAVA_SPRING)
        assert any("TODO" in i for i in issues)

    def test_clean_java_passes(self):
        diff = SemanticDiff()
        source = "public class Foo {}"
        converted = """
import org.springframework.stereotype.Service;

@Service
public class FooService {
    public String greet() { return "hello"; }
}
"""
        issues = diff.diff(source, converted, TargetLanguage.JAVA_SPRING)
        assert len(issues) == 0


class TestSyntaxChecker:
    def test_unbalanced_braces(self):
        checker = SyntaxChecker()
        code = "public class Foo { public void bar() { void baz() { "
        errors = checker.check_java(code)
        assert len(errors) > 0

    def test_balanced_java_passes(self):
        checker = SyntaxChecker()
        code = "public class Foo { public void bar() { System.out.println(\"hi\"); } }"
        errors = checker.check_java(code)
        assert len(errors) == 0

    def test_react_missing_keywords(self):
        checker = SyntaxChecker()
        errors = checker.check_javascript("// just a comment")
        assert len(errors) > 0


# ─── Workspace model Tests ────────────────────────────────────────────────────

class TestWorkspaceManifest:
    def test_get_file_by_path(self):
        sf = SourceFile(path="foo/bar.cs", language=SourceLanguage.CSHARP)
        manifest = WorkspaceManifest(files=[sf])
        found = manifest.get_file_by_path("foo/bar.cs")
        assert found is not None
        assert found.path == "foo/bar.cs"

    def test_summary(self):
        files = [
            SourceFile(path="a.cs", language=SourceLanguage.CSHARP,
                       complexity_tier=ComplexityTier.GREEN),
            SourceFile(path="b.cs", language=SourceLanguage.CSHARP,
                       complexity_tier=ComplexityTier.RED),
        ]
        manifest = WorkspaceManifest(files=files)
        summary = manifest.summary()
        assert summary["total_files"] == 2
