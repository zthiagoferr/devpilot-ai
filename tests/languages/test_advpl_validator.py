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

#: A realistic routine: resolved include, workarea safety, loop, and blocks.
REAL_ADVPL = (
    '#include "totvs.ch"\n'
    "\n"
    "/*/{Protheus.doc} ZTESTE\n"
    "Sample routine.\n"
    "@type user function\n"
    "@author Dev\n"
    "@since 01/01/2026\n"
    "/*/\n"
    "User Function ZTESTE()\n"
    'Local cAlias := "SA1"\n'
    "Local nTotal := 0\n"
    "Local aFields := {}\n"
    "Local lOk := .T.\n"
    "Local nI := 3\n"
    "\n"
    'DbSelectArea("SA1")\n'
    "DbSetOrder(1)\n"
    'If DbSeek("000001")\n'
    '  If RecLock("SA1", .F.)\n'
    '    SA1->A1_NOME := "Teste"\n'
    "    MsUnlock()\n"
    "  EndIf\n"
    "EndIf\n"
    "\n"
    "For nI := 1 To 3\n"
    "  nTotal += nI\n"
    "Next nI\n"
    "\n"
    "Return {cAlias, nTotal, aFields, lOk}\n"
)

REAL_ADVPL_PATHS = frozenset({"totvs.ch"})


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


def test_unclosed_parenthesis_is_high_with_line() -> None:
    source = (
        "User Function Foo()\n"
        "If (nX > 1\n"
        "  MsgInfo('positive')\n"
        "EndIf\n"
        "Return Nil\n"
    )
    result = validate(source)
    unbalanced = [
        issue for issue in result.issues if issue.cause == "unbalanced_parentheses"
    ]

    assert len(unbalanced) == 1
    assert unbalanced[0].severity == "high"
    assert unbalanced[0].line == 2


def test_unclosed_brace_is_high_with_line() -> None:
    source = (
        "User Function Foo()\n"
        "Local aValues := {1, 2\n"
        "Return Nil\n"
    )
    result = validate(source)
    unbalanced = [
        issue for issue in result.issues if issue.cause == "unbalanced_braces"
    ]

    assert len(unbalanced) == 1
    assert unbalanced[0].severity == "high"
    assert unbalanced[0].line == 2


def test_balanced_parentheses_and_braces_have_no_issue() -> None:
    source = (
        "User Function Foo()\n"
        "Local aValues := {1, 2, 3}\n"
        "If (nX > 1)\n"
        "  MsgInfo(Str(nX))\n"
        "EndIf\n"
        "Return Nil\n"
    )
    result = validate(source)

    assert "unbalanced_parentheses" not in causes(result)
    assert "unbalanced_braces" not in causes(result)


def test_delimiters_inside_strings_comments_and_directives_are_ignored() -> None:
    source = (
        '#Define MAX_VALUE(a, b) ((a) > (b))\n'
        "User Function Foo()\n"
        "// (\n"
        "/* { */\n"
        "MsgInfo('(')\n"
        "Return Nil\n"
    )
    result = validate(source)

    assert "unbalanced_parentheses" not in causes(result)
    assert "unbalanced_braces" not in causes(result)


def test_unmatched_closing_delimiter_is_high() -> None:
    result = validate("User Function Foo()\nReturn Nil)\n")

    unbalanced = [
        issue for issue in result.issues if issue.cause == "unbalanced_parentheses"
    ]
    assert len(unbalanced) == 1
    assert unbalanced[0].severity == "high"
    assert unbalanced[0].line == 2


def test_metadata_includes_protheus_version() -> None:
    result = validate(VALID_ADVPL, ValidationContext(protheus_version="12.1.2410"))
    validator = result.metadata["validator"]

    assert validator["protheus_version"] == "12.1.2410"
    assert "build tool is run" in validator["disclaimer"]


# --- Curated TOTVS rules (B2) -------------------------------------------


def test_realistic_advpl_routine_has_no_findings() -> None:
    context = ValidationContext(
        path="src/zteste.prw",
        known_paths=REAL_ADVPL_PATHS,
    )
    result = validate(REAL_ADVPL, context)

    assert result.issues == ()
    assert result.score == 100


def test_undeclared_variable_is_medium_with_line() -> None:
    source = (
        "User Function Foo()\n"
        'Local cName := "x"\n'
        "If nCount > 0\n"
        '  cName := "y"\n'
        "EndIf\n"
        "Return cName\n"
    )
    result = validate(source)
    undeclared = [
        issue for issue in result.issues if issue.cause == "undeclared_variable"
    ]

    assert len(undeclared) == 1
    assert undeclared[0].severity == "medium"
    assert undeclared[0].line == 3
    assert "nCount" in undeclared[0].message


def test_undeclared_variable_is_skipped_when_includes_may_declare_it() -> None:
    source = (
        '#include "totvs.ch"\n'
        "User Function Foo()\n"
        'If cEmpAnt == "01"\n'
        "  nValue := 1\n"
        "EndIf\n"
        "Return Nil\n"
    )
    context = ValidationContext(known_paths=REAL_ADVPL_PATHS)
    result = validate(source, context)

    assert "undeclared_variable" not in causes(result)
    assert result.issues == ()


def test_undeclared_variable_ignores_params_defaults_calls_and_catch() -> None:
    source = (
        "User Function Foo(cParam)\n"
        "Local nTotal := 0\n"
        "Default nMissing := 0\n"
        "For nI := 1 To 3\n"
        "  nTotal += Calculate(nI) + Len(cParam)\n"
        "Next nI\n"
        "Try\n"
        "  nTotal += 1\n"
        "Catch oError\n"
        "  MsgInfo(oError:Description)\n"
        "EndTry\n"
        "Return nTotal\n"
    )
    result = validate(source)

    assert "undeclared_variable" not in causes(result)


def test_undeclared_variable_ignores_function_calls_with_prefix() -> None:
    source = (
        "User Function Foo()\n"
        "Local nValue := 1\n"
        "Return cValToChar(nValue)\n"
    )
    result = validate(source)

    assert "undeclared_variable" not in causes(result)


def test_deprecated_apis_report_curated_replacements() -> None:
    source = (
        "User Function Foo()\n"
        "Local aStruct := {}\n"
        'MSCREATE("TMP", aStruct)\n'
        'ConOut("processing")\n'
        "Return Nil\n"
    )
    result = validate(source)
    deprecated = [issue for issue in result.issues if issue.cause == "deprecated_api"]

    assert len(deprecated) == 2
    by_rule = {issue.rule_id: issue for issue in deprecated}
    assert by_rule["CA1000"].severity == "medium"
    assert "MSCREATE" in by_rule["CA1000"].message
    assert "FWTemporaryTable" in by_rule["CA1000"].message
    assert by_rule["CA1004"].severity == "low"
    assert "FWLogMsg" in by_rule["CA1004"].message


def test_modern_replacements_do_not_trigger_deprecated_api() -> None:
    source = (
        "User Function Foo()\n"
        'Local oTemp := FWTemporaryTable():New("TMP")\n'
        'FWLogMsg("INFO", , "APP", "Foo", , , "processing", , , )\n'
        "Return Nil\n"
    )
    result = validate(source)

    assert "deprecated_api" not in causes(result)
    assert result.issues == ()


def test_obsolete_includes_are_medium() -> None:
    source = (
        '#include "protheus.ch"\n'
        '#include "ap5mail.ch"\n'
        '#include "RWMake.ch"\n'
    )
    result = validate(source)
    obsolete = [issue for issue in result.issues if issue.cause == "obsolete_include"]

    assert len(obsolete) == 3
    assert all(issue.severity == "medium" for issue in obsolete)
    assert [issue.line for issue in obsolete] == [1, 2, 3]
    assert "totvs.ch" in obsolete[0].message
    assert "TMailMessage()" in obsolete[1].message
    assert "totvs.ch" in obsolete[2].message


def test_protheus_include_keeps_the_skill_severity() -> None:
    """The bundled TOTVS skills list ``protheus.ch`` as an obsolete include.

    Both ``code-review/SKILL.md`` ("Obsolete Include Directives") and
    ``refactor/SKILL.md`` ("Replace Obsolete Includes") name ``protheus.ch`` as
    replaced by ``totvs.ch``; the medium severity mirrors that guidance.
    """
    source = '#include "protheus.ch"\nUser Function Foo()\nReturn Nil\n'
    result = validate(source)

    obsolete = [issue for issue in result.issues if issue.cause == "obsolete_include"]
    assert len(obsolete) == 1
    assert obsolete[0].severity == "medium"
    assert "totvs.ch" in obsolete[0].message


def test_totvs_include_is_not_obsolete() -> None:
    source = '#include "totvs.ch"\nUser Function Foo()\nReturn Nil\n'
    context = ValidationContext(known_paths=REAL_ADVPL_PATHS)
    result = validate(source, context)

    assert "obsolete_include" not in causes(result)
    assert result.issues == ()


def test_uppercase_include_directive_is_low() -> None:
    source = '#INCLUDE "TOTVS.CH"\nUser Function Foo()\nReturn Nil\n'
    result = validate(source)
    case = [
        issue for issue in result.issues if issue.cause == "include_case_convention"
    ]

    assert len(case) == 1
    assert case[0].severity == "low"
    assert case[0].rule_id == "CA3001"


def test_lowercase_include_directive_has_no_case_finding() -> None:
    source = '#include "totvs.ch"\nUser Function Foo()\nReturn Nil\n'
    context = ValidationContext(known_paths=REAL_ADVPL_PATHS)
    result = validate(source, context)

    assert "include_case_convention" not in causes(result)


def test_api_call_inside_loop_is_medium() -> None:
    source = (
        "User Function Foo()\n"
        "Local nI := 0\n"
        "For nI := 1 To 3\n"
        '  MsgInfo(GetMV("MV_X"))\n'
        "Next nI\n"
        "Return Nil\n"
    )
    result = validate(source)
    loops = [issue for issue in result.issues if issue.cause == "api_in_loop"]

    assert len(loops) == 1
    assert loops[0].severity == "medium"
    assert loops[0].rule_id == "CA1003"
    assert loops[0].line == 4


def test_cached_api_call_outside_loop_has_no_finding() -> None:
    source = (
        "User Function Foo()\n"
        'Local cParam := GetMV("MV_X")\n'
        "Local nI := 0\n"
        "For nI := 1 To 3\n"
        "  MsgInfo(cParam)\n"
        "Next nI\n"
        "Return Nil\n"
    )
    result = validate(source)

    assert "api_in_loop" not in causes(result)


def test_api_call_in_for_header_is_not_a_loop_body_call() -> None:
    source = (
        "User Function Foo()\n"
        "Local nI := 0\n"
        'Local cType := ""\n'
        'For nI := 1 To Max(1, Len(Type("N")))\n'
        "  cType += Str(nI)\n"
        "Next nI\n"
        "Return cType\n"
    )
    result = validate(source)

    assert "api_in_loop" not in causes(result)


def test_api_call_in_while_header_is_reported() -> None:
    source = (
        "User Function Foo()\n"
        "Local nI := 0\n"
        'While GetMV("MV_X") == "1"\n'
        "  nI += 1\n"
        "EndDo\n"
        "Return nI\n"
    )
    result = validate(source)
    loops = [issue for issue in result.issues if issue.cause == "api_in_loop"]

    assert len(loops) == 1


def test_ui_call_inside_transaction_is_medium() -> None:
    source = (
        "User Function Foo()\n"
        "Begin Transaction\n"
        '  MsgAlert("error")\n'
        "End Transaction\n"
        "Return Nil\n"
    )
    result = validate(source)
    ui = [issue for issue in result.issues if issue.cause == "ui_call_in_transaction"]

    assert len(ui) == 1
    assert ui[0].severity == "medium"
    assert ui[0].rule_id == "CA1002"
    assert ui[0].line == 3
    # ``End Transaction`` must not be read as a bare ``End`` block closer.
    assert "unmatched_closer" not in causes(result)


def test_ui_call_after_transaction_has_no_finding() -> None:
    source = (
        "User Function Foo()\n"
        "Begin Transaction\n"
        "  DbSelectArea(\"SA1\")\n"
        "End Transaction\n"
        'MsgAlert("done")\n'
        "Return Nil\n"
    )
    result = validate(source)

    assert "ui_call_in_transaction" not in causes(result)


def test_ui_call_in_unbalanced_transaction_is_not_reported() -> None:
    source = (
        "User Function Foo()\n"
        "Begin Transaction\n"
        '  MsgAlert("error")\n'
        "Return Nil\n"
    )
    result = validate(source)

    assert "ui_call_in_transaction" not in causes(result)


def test_direct_sx_table_access_is_reported() -> None:
    source = (
        "User Function Foo()\n"
        'DbSelectArea("SX3")\n'
        'DbSelectArea("SE5")\n'
        "Return Nil\n"
    )
    result = validate(source)
    metadata = [
        issue for issue in result.issues if issue.cause == "direct_metadata_access"
    ]

    assert len(metadata) == 2
    by_rule = {issue.rule_id: issue for issue in metadata}
    assert by_rule["CA2004"].severity == "high"
    assert by_rule["CA2021"].severity == "medium"


def test_non_system_tables_and_dynamic_aliases_are_ignored() -> None:
    source = (
        "User Function Foo()\n"
        'DbSelectArea("SA1")\n'
        "DbSelectArea(cAlias)\n"
        "Return Nil\n"
    )
    result = validate(source)

    assert "direct_metadata_access" not in causes(result)


def test_sx_table_names_inside_strings_and_comments_are_ignored() -> None:
    source = (
        "User Function Foo()\n"
        "Local cCmd := 'DbSelectArea(\"SX3\")'\n"
        '// DbSelectArea("SX3")\n'
        "Return cCmd\n"
    )
    result = validate(source)

    assert "direct_metadata_access" not in causes(result)


def test_naming_convention_is_informational_for_literal_declarations() -> None:
    source = (
        "User Function Foo()\n"
        "Local total := 1\n"
        "Return total\n"
    )
    result = validate(source)
    naming = [issue for issue in result.issues if issue.cause == "naming_convention"]

    assert len(naming) == 1
    assert naming[0].severity == "info"
    assert naming[0].line == 2
    assert result.score == 100


def test_naming_convention_accepts_prefixed_declarations() -> None:
    source = (
        "User Function Foo()\n"
        "Local nTotal := 1\n"
        'Local cName := "x"\n'
        "Local lOk := .T.\n"
        "Local aItems := {}\n"
        "Return Nil\n"
    )
    result = validate(source)

    assert "naming_convention" not in causes(result)
    assert result.issues == ()


def test_naming_convention_requires_a_literal_initializer() -> None:
    source = (
        "User Function Foo()\n"
        "Local total as Numeric\n"
        "Local value := CalcValue()\n"
        "Return Nil\n"
    )
    result = validate(source)

    assert "naming_convention" not in causes(result)


def test_new_rules_never_claim_compilation_or_execution() -> None:
    source = (
        '#INCLUDE "TOTVS.CH"\n'
        '#include "protheus.ch"\n'
        "User Function Foo()\n"
        "Local total := 1\n"
        'MSCREATE("TMP", {})\n'
        'ConOut("processing")\n'
        "For nI := 1 To 2\n"
        '  MsgInfo(GetMV("MV_X"))\n'
        "Next nI\n"
        "Begin Transaction\n"
        '  MsgAlert("error")\n'
        "End Transaction\n"
        'DbSelectArea("SX3")\n'
        "Return Nil\n"
    )
    result = validate(source)
    messages = " ".join(issue.message.lower() for issue in result.issues)

    assert "compil" not in messages
    assert "execut" not in messages
    assert all(
        issue.analysis_kind == "heuristic_validation" for issue in result.issues
    )
    causes_found = set(causes(result))
    assert {
        "deprecated_api",
        "obsolete_include",
        "include_case_convention",
        "api_in_loop",
        "ui_call_in_transaction",
        "direct_metadata_access",
        "naming_convention",
    } <= causes_found


def test_coverage_declares_the_new_checks() -> None:
    coverage = AdvplValidator().coverage
    checks = set(coverage["checks"])

    assert {
        "variable_scope",
        "deprecated_apis",
        "loop_apis",
        "transaction_ui",
        "metadata_access",
        "naming_convention",
    } <= checks
    assert any("not a compiler" in item for item in coverage["limitations"])


def test_define_names_are_treated_as_declared_symbols() -> None:
    source = (
        '#Define cSep ";"\n'
        "User Function Foo()\n"
        'Local cName := "a" + cSep\n'
        "Return cName\n"
    )
    result = validate(source)

    assert "undeclared_variable" not in causes(result)
    assert result.issues == ()


def test_define_does_not_mask_truly_undeclared_variables() -> None:
    source = (
        '#Define cSep ";"\n'
        "User Function Foo()\n"
        'Local cName := "a" + cSep\n'
        "If nCount > 0\n"
        '  cName := "b"\n'
        "EndIf\n"
        "Return cName\n"
    )
    result = validate(source)
    undeclared = [
        issue for issue in result.issues if issue.cause == "undeclared_variable"
    ]

    assert len(undeclared) == 1
    assert "nCount" in undeclared[0].message


def test_dbcreate_is_reported_as_deprecated_isam_driver() -> None:
    source = (
        "User Function Foo()\n"
        "Local aStruct := {}\n"
        'DbCreate("TMP", aStruct)\n'
        "Return Nil\n"
    )
    result = validate(source)
    deprecated = [issue for issue in result.issues if issue.cause == "deprecated_api"]

    assert len(deprecated) == 1
    assert deprecated[0].severity == "medium"
    assert deprecated[0].rule_id == "CA1000"
    assert "DBCREATE" in deprecated[0].message
    assert "FWTemporaryTable" in deprecated[0].message
    assert deprecated[0].line == 3


def test_deprecated_isam_apis_are_reported_together() -> None:
    source = (
        "User Function Foo()\n"
        "Local aStruct := {}\n"
        'MSCREATE("TMP", aStruct)\n'
        'DbCreate("TMP2", aStruct)\n'
        "Return Nil\n"
    )
    result = validate(source)
    deprecated = [issue for issue in result.issues if issue.cause == "deprecated_api"]

    assert len(deprecated) == 2
    assert {issue.rule_id for issue in deprecated} == {"CA1000"}
    assert all(issue.severity == "medium" for issue in deprecated)


def test_naming_convention_reports_continuation_line_position() -> None:
    source = (
        "User Function Foo()\n"
        "Local nOk := 1, total := 2 ;\n"
        "   , other := 3\n"
        "Return Nil\n"
    )
    result = validate(source)
    naming = [issue for issue in result.issues if issue.cause == "naming_convention"]

    assert [(issue.line, issue.column) for issue in naming] == [(2, 17), (3, 6)]


def test_coverage_documents_transaction_and_preprocessor_blind_spots() -> None:
    limitations = " ".join(AdvplValidator().coverage["limitations"])

    assert "Unbalanced Begin/End Transaction is not detected" in limitations
    assert "#xCommand/#xTranslate" in limitations
