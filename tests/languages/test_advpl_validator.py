"""Tests for the heuristic ADVPL validator."""

from __future__ import annotations

from app.languages.base import ValidationContext
from app.languages.validators.advpl import AdvplValidator

VALID_ADVPL = (
    "User Function Foo()\n"
    "Local nValue := 1\n"
    "If nValue > 0\n"
    "  nValue := 2\n"
    "EndIf\n"
    "Return Nil\n"
)


def validate(source: str, context: ValidationContext | None = None):
    return AdvplValidator().validate(source, context or ValidationContext())


def causes(result) -> list[str]:
    return [issue.cause for issue in result.issues]


def test_valid_advpl_has_no_issues() -> None:
    result = validate(VALID_ADVPL)

    assert result.language == "advpl"
    assert result.issues == ()
    assert result.score == 100
    assert result.metadata["validator"]["name"] == "advpl_heuristic"
    assert result.metadata["validator"]["official"] is False


def test_balanced_control_structures_have_no_issues() -> None:
    source = (
        "User Function Foo()\n"
        "Do While nValue > 0\n"
        "  nValue -= 1\n"
        "EndDo\n"
        "Begin Sequence\n"
        "  For nI := 1 To 3\n"
        "    nValue += nI\n"
        "  Next nI\n"
        "End Sequence\n"
        "Do Case\n"
        "  Case nValue == 1\n"
        "    nValue := 2\n"
        "EndCase\n"
        "Return Nil\n"
    )
    result = validate(source)
    assert result.issues == ()


def test_missing_endif_is_high_with_line() -> None:
    source = (
        "User Function Foo()\n"
        "If nValue > 0\n"
        "  MsgInfo('positive')\n"
        "Return Nil\n"
    )
    result = validate(source)
    unclosed = [issue for issue in result.issues if issue.cause == "unclosed_block"]

    assert len(unclosed) == 1
    assert unclosed[0].severity == "high"
    assert unclosed[0].line == 2


def test_string_content_does_not_affect_structure() -> None:
    source = (
        "User Function Foo()\n"
        "MsgInfo('If EndIf Do While EndDo')\n"
        "Return Nil\n"
    )
    result = validate(source)
    assert result.issues == ()


def test_comment_content_does_not_affect_structure() -> None:
    source = (
        "User Function Foo()\n"
        "// EndIf EndDo EndCase\n"
        "/* If Begin Sequence */\n"
        "Return Nil\n"
    )
    result = validate(source)
    assert result.issues == ()


def test_unmatched_closer_is_high() -> None:
    source = "User Function Foo()\nEndIf\nReturn Nil\n"
    result = validate(source)
    unmatched = [issue for issue in result.issues if issue.cause == "unmatched_closer"]

    assert len(unmatched) == 1
    assert unmatched[0].severity == "high"
    assert unmatched[0].line == 2


def test_else_without_if_is_medium() -> None:
    source = "User Function Foo()\nElse\nReturn Nil\n"
    result = validate(source)
    orphan = [issue for issue in result.issues if issue.cause == "else_without_if"]
    assert len(orphan) == 1
    assert orphan[0].severity == "medium"


def test_unresolved_include_is_informational() -> None:
    source = '#Include "missing.ch"\nUser Function Foo()\nReturn Nil\n'
    result = validate(source)
    unresolved = [
        issue for issue in result.issues if issue.cause == "include_unresolved"
    ]

    assert len(unresolved) == 1
    assert unresolved[0].severity == "info"
    assert unresolved[0].line == 1


def test_resolved_include_is_silent() -> None:
    source = '#Include "totvs.ch"\nUser Function Foo()\nReturn Nil\n'
    context = ValidationContext(
        path="src/custom.prw",
        known_paths=frozenset({"src/totvs.ch"}),
    )
    result = validate(source, context)
    assert "include_unresolved" not in causes(result)


def test_bom_and_crlf_are_supported() -> None:
    source = (
        "\ufeffUser Function Foo()\r\n"
        "Local nValue := 1\r\n"
        "If nValue > 0\r\n"
        "  nValue := 2\r\n"
        "EndIf\r\n"
        "Return Nil\r\n"
    )
    result = validate(source)
    assert result.issues == ()


def test_private_declaration_is_low() -> None:
    source = "Private cGlobal as char\nUser Function Foo()\nReturn Nil\n"
    result = validate(source)
    globals_ = [issue for issue in result.issues if issue.cause == "global_variable"]

    assert len(globals_) == 1
    assert globals_[0].severity == "low"
    assert globals_[0].line == 1


def test_missing_return_and_duplicate_function() -> None:
    source = (
        "User Function Foo()\n"
        "Local nValue := 1\n"
        "User Function Foo()\n"
        "Return Nil\n"
    )
    result = validate(source)
    assert "missing_return" in causes(result)
    assert "duplicate_function" in causes(result)


def test_return_outside_function_is_medium() -> None:
    result = validate("Return Nil\n")
    outside = [
        issue for issue in result.issues if issue.cause == "return_outside_function"
    ]
    assert len(outside) == 1
    assert outside[0].severity == "medium"


def test_duplicate_define_with_different_value() -> None:
    source = "#Define MAX_VALUE 10\n#Define MAX_VALUE 20\n"
    result = validate(source)
    duplicates = [issue for issue in result.issues if issue.cause == "duplicate_define"]

    assert len(duplicates) == 1
    assert duplicates[0].severity == "medium"
    assert duplicates[0].line == 2


def test_unbalanced_ifdef() -> None:
    result = validate("#Ifdef FEATURE\n")
    unbalanced = [issue for issue in result.issues if issue.cause == "unbalanced_ifdef"]

    assert len(unbalanced) == 1
    assert unbalanced[0].severity == "medium"


def test_hash_if_expression_is_balanced_like_ifdef() -> None:
    source = (
        "#If __lVersion >= 12\n"
        "#Define NOVO_RECURSO .T.\n"
        "#Else\n"
        "#Define NOVO_RECURSO .F.\n"
        "#Endif\n"
        "User Function Foo()\n"
        "Return Nil\n"
    )
    result = validate(source)

    assert "unbalanced_ifdef" not in causes(result)


def test_hash_ifdef_and_ifndef_remain_balanced() -> None:
    source = (
        "#Ifdef FEATURE\n"
        "#Define A 1\n"
        "#Else\n"
        "#Define A 2\n"
        "#Endif\n"
        "#Ifndef DISABLED\n"
        "#Define B 1\n"
        "#Endif\n"
    )
    result = validate(source)

    assert "unbalanced_ifdef" not in causes(result)


def test_orphan_endif_after_expression_if_is_medium() -> None:
    result = validate("#Endif\n")
    unbalanced = [issue for issue in result.issues if issue.cause == "unbalanced_ifdef"]

    assert len(unbalanced) == 1
    assert unbalanced[0].severity == "medium"


def test_unterminated_string_is_medium() -> None:
    source = "User Function Foo()\nLocal cText := 'unterminated\nReturn Nil\n"
    result = validate(source)
    unterminated = [
        issue for issue in result.issues if issue.cause == "unterminated_string"
    ]

    assert len(unterminated) == 1
    assert unterminated[0].severity == "medium"
    assert unterminated[0].line == 2


def test_default_outside_function_is_info() -> None:
    result = validate("Default nValue := 1\n")
    defaults = [
        issue for issue in result.issues if issue.cause == "default_outside_function"
    ]
    assert len(defaults) == 1
    assert defaults[0].severity == "info"


def test_heuristic_issues_avoid_compilation_and_execution_claims() -> None:
    source = (
        "#Include \"missing.ch\"\n"
        "Private cGlobal as char\n"
        "User Function Foo()\n"
        "If nValue > 0\n"
        "Return Nil\n"
    )
    result = validate(source)
    messages = " ".join(issue.message.lower() for issue in result.issues)

    assert "compil" not in messages
    assert "execut" not in messages
    assert "runs successfully" not in messages
    assert all(issue.analysis_kind == "heuristic_validation" for issue in result.issues)


def test_metadata_includes_protheus_version() -> None:
    result = validate(VALID_ADVPL, ValidationContext(protheus_version="12.1.2410"))
    validator = result.metadata["validator"]

    assert validator["protheus_version"] == "12.1.2410"
    assert "build tool is run" in validator["disclaimer"]
