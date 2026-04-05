"""
Tests for the self-healing accuracy engine.
"""

import pytest
from shared.models import (
    SourceFile, SourceLanguage, TargetLanguage,
    ConversionResult, ConversionStatus,
)
from accuracy.scorer import (
    AccuracyEngine, SyntaxScorer, SemanticScorer,
    StructuralScorer, BehavioralScorer, CoverageScorer,
    Dimension, ACCURACY_THRESHOLD,
)
from accuracy.analyser import (
    FailureAnalyser, RemediationStrategy, FailureCategory,
)
from accuracy.remediation import (
    apply_structural_fix, apply_syntax_fix, apply_annotation_rule,
)
from accuracy.knowledge_base import KnowledgeBase, LearnedRule, RuleExtractor


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def good_java():
    return """package com.company.app;

import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;

@RestController
@RequestMapping("/api/customer")
public class CustomerController {
    private final CustomerService service;

    public CustomerController(CustomerService service) {
        this.service = service;
    }

    @GetMapping("/{id}")
    public ResponseEntity<?> getById(@PathVariable int id) {
        return service.getById(id)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
    }
}"""


@pytest.fixture
def bad_java_missing_annotations():
    return """public class CustomerController {
    private CustomerService service;

    public Object getById(int id) {
        return service.getById(id);
    }
}"""


@pytest.fixture
def good_react():
    return """import React, { useState, useEffect } from 'react';

const CustomerForm: React.FC = () => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');

  useEffect(() => {
    // init
  }, []);

  const handleSave = async () => {
    await fetch('/api/customer', {
      method: 'POST',
      body: JSON.stringify({ name, email }),
    });
  };

  return (
    <div>
      <input value={name} onChange={e => setName(e.target.value)} />
      <button onClick={handleSave}>Save</button>
    </div>
  );
};

export default CustomerForm;"""


@pytest.fixture
def bad_react_missing_structure():
    return """const CustomerForm = () => {
  return <div>Hello</div>
}"""


@pytest.fixture
def csharp_source_with_api():
    return """[ApiController]
[Route("api/[controller]")]
public class CustomerController : ControllerBase
{
    [HttpGet("{id}")]
    public async Task<IActionResult> GetById([FromRoute] int id)
    {
        var customer = await _service.GetByIdAsync(id);
        return Ok(customer);
    }
}"""


@pytest.fixture
def vb6_form_source():
    return """Private Sub Form_Load()
    Dim name As String
    name = "World"
    MsgBox "Hello " & name
End Sub

Private Sub cmdSave_Click()
    txtName.Text = ""
End Sub"""


@pytest.fixture
def make_result():
    def _make(source_code, converted_code, source_lang, target_lang):
        sf = SourceFile(
            path="test_file",
            language=source_lang,
            raw_content=source_code,
        )
        return ConversionResult(
            source_file=sf,
            target_language=target_lang,
            converted_code=converted_code,
            status=ConversionStatus.LLM_CONVERTED,
            confidence=0.8,
        )
    return _make


# ─── SyntaxScorer ────────────────────────────────────────────────────────────

class TestSyntaxScorer:
    def test_good_java_passes(self, good_java):
        scorer = SyntaxScorer()
        ds = scorer.score(good_java, TargetLanguage.JAVA_SPRING)
        assert ds.score >= 80
        assert len(ds.issues) == 0

    def test_unbalanced_braces_penalised(self):
        scorer = SyntaxScorer()
        code = "public class Foo { public void bar() {"
        ds = scorer.score(code, TargetLanguage.JAVA_SPRING)
        assert ds.score < 80
        assert any("brace" in i.lower() for i in ds.issues)

    def test_missing_class_penalised(self):
        scorer = SyntaxScorer()
        code = "// just a comment\n@RestController"
        ds = scorer.score(code, TargetLanguage.JAVA_SPRING)
        assert ds.score < 90

    def test_good_react_passes(self, good_react):
        scorer = SyntaxScorer()
        ds = scorer.score(good_react, TargetLanguage.REACT_JS)
        assert ds.score >= 80

    def test_react_missing_export(self, bad_react_missing_structure):
        scorer = SyntaxScorer()
        ds = scorer.score(bad_react_missing_structure, TargetLanguage.REACT_JS)
        assert any("export" in i.lower() for i in ds.issues)


# ─── SemanticScorer ───────────────────────────────────────────────────────────

class TestSemanticScorer:
    def test_good_java_passes(self, csharp_source_with_api, good_java):
        scorer = SemanticScorer()
        ds = scorer.score(csharp_source_with_api, good_java, TargetLanguage.JAVA_SPRING)
        assert ds.score >= 80

    def test_missing_getmapping_caught(self, csharp_source_with_api, bad_java_missing_annotations):
        scorer = SemanticScorer()
        ds = scorer.score(
            csharp_source_with_api, bad_java_missing_annotations, TargetLanguage.JAVA_SPRING
        )
        issues_text = " ".join(ds.issues)
        assert "GetMapping" in issues_text or ds.score < 80

    def test_high_todo_penalised(self):
        scorer = SemanticScorer()
        code = "\n".join([f"// TODO: fix {i}" for i in range(60)])
        ds = scorer.score("source", code, TargetLanguage.JAVA_SPRING)
        assert ds.score <= 60
        assert any("TODO" in i for i in ds.issues)

    def test_vb6_form_load_mapped_to_useeffect(self, vb6_form_source, good_react):
        scorer = SemanticScorer()
        ds = scorer.score(vb6_form_source, good_react, TargetLanguage.REACT_JS)
        assert ds.score >= 70


# ─── StructuralScorer ─────────────────────────────────────────────────────────

class TestStructuralScorer:
    def test_good_java_passes(self, good_java):
        scorer = StructuralScorer()
        ds = scorer.score(good_java, TargetLanguage.JAVA_SPRING)
        assert ds.score >= 80

    def test_missing_package_penalised(self, bad_java_missing_annotations):
        scorer = StructuralScorer()
        ds = scorer.score(bad_java_missing_annotations, TargetLanguage.JAVA_SPRING)
        assert any("package" in i.lower() for i in ds.issues)

    def test_missing_stereotype_penalised(self, bad_java_missing_annotations):
        scorer = StructuralScorer()
        ds = scorer.score(bad_java_missing_annotations, TargetLanguage.JAVA_SPRING)
        assert any("stereotype" in i.lower() or "annotation" in i.lower() for i in ds.issues)

    def test_good_react_passes(self, good_react):
        scorer = StructuralScorer()
        ds = scorer.score(good_react, TargetLanguage.REACT_JS)
        assert ds.score >= 80

    def test_react_missing_import_caught(self, bad_react_missing_structure):
        scorer = StructuralScorer()
        ds = scorer.score(bad_react_missing_structure, TargetLanguage.REACT_JS)
        assert any("React" in i for i in ds.issues)


# ─── AccuracyEngine (full scoring) ───────────────────────────────────────────

class TestAccuracyEngine:
    def test_good_java_passes_threshold(self, csharp_source_with_api, good_java, make_result):
        engine = AccuracyEngine()
        result = make_result(
            csharp_source_with_api, good_java,
            SourceLanguage.CSHARP, TargetLanguage.JAVA_SPRING,
        )
        report = engine.score(result)
        assert report.overall_score >= ACCURACY_THRESHOLD
        assert report.passed is True

    def test_bad_java_fails_threshold(self, csharp_source_with_api, bad_java_missing_annotations, make_result):
        engine = AccuracyEngine()
        result = make_result(
            csharp_source_with_api, bad_java_missing_annotations,
            SourceLanguage.CSHARP, TargetLanguage.JAVA_SPRING,
        )
        report = engine.score(result)
        assert report.passed is False

    def test_good_react_passes_threshold(self, vb6_form_source, good_react, make_result):
        engine = AccuracyEngine()
        result = make_result(
            vb6_form_source, good_react,
            SourceLanguage.VB6, TargetLanguage.REACT_JS,
        )
        report = engine.score(result)
        assert report.overall_score >= 70   # Should be close or above

    def test_report_has_all_dimensions(self, csharp_source_with_api, good_java, make_result):
        engine = AccuracyEngine()
        result = make_result(
            csharp_source_with_api, good_java,
            SourceLanguage.CSHARP, TargetLanguage.JAVA_SPRING,
        )
        report = engine.score(result)
        assert set(report.dimension_scores.keys()) == set(Dimension)

    def test_failed_dimensions_reported(self, csharp_source_with_api, bad_java_missing_annotations, make_result):
        engine = AccuracyEngine()
        result = make_result(
            csharp_source_with_api, bad_java_missing_annotations,
            SourceLanguage.CSHARP, TargetLanguage.JAVA_SPRING,
        )
        report = engine.score(result)
        assert len(report.failed_dimensions()) > 0


# ─── FailureAnalyser ─────────────────────────────────────────────────────────

class TestFailureAnalyser:
    def test_annotation_failure_routed_to_add_rule(self, csharp_source_with_api, bad_java_missing_annotations, make_result):
        engine = AccuracyEngine()
        analyser = FailureAnalyser()
        result = make_result(
            csharp_source_with_api, bad_java_missing_annotations,
            SourceLanguage.CSHARP, TargetLanguage.JAVA_SPRING,
        )
        report = engine.score(result)
        analysis = analyser.analyse(report)
        strategies = analysis.strategies_needed()
        assert any(s in (
            RemediationStrategy.ADD_RULE,
            RemediationStrategy.STRUCTURAL_FIX,
            RemediationStrategy.LLM_PATCH,
        ) for s in strategies)

    def test_complex_logic_escalated(self):
        from accuracy.scorer import AccuracyReport
        from accuracy.analyser import FailureAnalysis
        report = AccuracyReport(result_id="x", file_path="x.cs")
        report.dimension_scores = {}
        report.overall_score = 40.0
        report.all_issues = []
        from accuracy.scorer import Dimension, DimensionScore, DIMENSION_WEIGHTS
        report.dimension_scores[Dimension.BEHAVIORAL] = DimensionScore(
            dimension=Dimension.BEHAVIORAL,
            score=25.0,
            weight=DIMENSION_WEIGHTS[Dimension.BEHAVIORAL],
            issues=["Critical behavioral gap"],
        )
        report.dimension_scores[Dimension.SYNTAX] = DimensionScore(
            dimension=Dimension.SYNTAX, score=90.0,
            weight=DIMENSION_WEIGHTS[Dimension.SYNTAX],
        )
        report.dimension_scores[Dimension.SEMANTIC] = DimensionScore(
            dimension=Dimension.SEMANTIC, score=40.0,
            weight=DIMENSION_WEIGHTS[Dimension.SEMANTIC],
        )
        report.dimension_scores[Dimension.STRUCTURAL] = DimensionScore(
            dimension=Dimension.STRUCTURAL, score=70.0,
            weight=DIMENSION_WEIGHTS[Dimension.STRUCTURAL],
        )
        report.dimension_scores[Dimension.COVERAGE] = DimensionScore(
            dimension=Dimension.COVERAGE, score=80.0,
            weight=DIMENSION_WEIGHTS[Dimension.COVERAGE],
        )
        report.all_issues = ["Critical behavioral gap"]

        analyser = FailureAnalyser()
        analysis = analyser.analyse(report)
        assert RemediationStrategy.HUMAN_REVIEW in analysis.strategies_needed()


# ─── Structural Fix ───────────────────────────────────────────────────────────

class TestStructuralFix:
    def test_adds_react_import(self):
        code = "const Foo = () => <div>Hi</div>;"
        fixed = apply_structural_fix(code, TargetLanguage.REACT_JS, [])
        assert "import React" in fixed

    def test_adds_default_export(self):
        code = "import React from 'react';\nconst Foo = () => <div/>;  "
        fixed = apply_structural_fix(code, TargetLanguage.REACT_JS, [])
        assert "export default Foo" in fixed

    def test_adds_java_package(self):
        code = "public class Foo {}"
        fixed = apply_structural_fix(code, TargetLanguage.JAVA_SPRING, [])
        assert "package com.company.app" in fixed

    def test_adds_spring_imports(self):
        code = "package com.company.app;\n\npublic class Foo {}"
        fixed = apply_structural_fix(code, TargetLanguage.JAVA_SPRING, [])
        assert "import org.springframework" in fixed

    def test_idempotent_react_import(self, good_react):
        fixed = apply_structural_fix(good_react, TargetLanguage.REACT_JS, [])
        assert fixed.count("import React") == 1

    def test_idempotent_package(self, good_java):
        fixed = apply_structural_fix(good_java, TargetLanguage.JAVA_SPRING, [])
        assert fixed.count("package com.company") == 1


# ─── Syntax Fix ───────────────────────────────────────────────────────────────

class TestSyntaxFix:
    def test_closes_unbalanced_braces(self):
        code = "public class Foo { public void bar() {"
        fixed = apply_syntax_fix(code, TargetLanguage.JAVA_SPRING)
        assert fixed.count("{") == fixed.count("}")

    def test_does_not_break_balanced_code(self, good_java):
        fixed = apply_syntax_fix(good_java, TargetLanguage.JAVA_SPRING)
        assert fixed.count("{") == fixed.count("}")


# ─── Knowledge Base ───────────────────────────────────────────────────────────

class TestKnowledgeBase:
    def test_add_and_apply_rule(self):
        kb = KnowledgeBase()
        rule = LearnedRule(
            id="test_rule_001",
            source_lang="vb6",
            target_lang="react_js",
            issue_pattern="Missing React import",
            source_pattern=".*",
            replacement="import React from 'react';\n",
            repair_type="prepend",
        )
        kb.add_rule(rule)
        code = "const Foo = () => <div/>"
        patched, applied = kb.apply_learned_rules(
            code, SourceLanguage.VB6, TargetLanguage.REACT_JS
        )
        assert "test_rule_001" in applied
        assert "import React" in patched

    def test_deduplication(self):
        kb = KnowledgeBase()
        rule = LearnedRule(
            id="dup_rule",
            source_lang="csharp", target_lang="java_spring",
            issue_pattern="test", source_pattern="x", replacement="y",
            repair_type="regex_replace",
        )
        kb.add_rule(rule)
        kb.add_rule(rule)
        assert len(kb.rules) == 1

    def test_rule_extractor_prepend(self):
        extractor = RuleExtractor()
        original  = "public class Foo {}"
        corrected = "package com.x;\n\npublic class Foo {}"
        rule = extractor.extract_from_correction(
            SourceLanguage.CSHARP, TargetLanguage.JAVA_SPRING,
            "Missing package", original, corrected,
        )
        assert rule is not None
        assert rule.repair_type == "prepend"
        assert "package" in rule.replacement
