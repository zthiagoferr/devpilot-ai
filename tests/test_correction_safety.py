"""Safety checks applied to AI correction text."""

from __future__ import annotations

import pytest

from app.services.correction_errors import CorrectionSafetyError
from app.services.correction_safety import (
    assert_no_execution_claims,
    detect_unverified_totvs_usage,
)


@pytest.mark.parametrize(
    "text",
    [
        "The corrected file compiles successfully.",
        "Now it compiles.",
        "This code compiles.",
        "O arquivo compila corretamente.",
        "O código executa com sucesso.",
        "The program runs successfully.",
        "O teste rodou sem erros.",
        "O código foi executado com sucesso.",
        "O código executou com sucesso.",
    ],
)
def test_success_claims_are_rejected(text: str) -> None:
    with pytest.raises(CorrectionSafetyError):
        assert_no_execution_claims(text)


@pytest.mark.parametrize(
    "text",
    [
        "The corrected file does not compile because a symbol is missing.",
        "It does not run successfully in this environment.",
        "Este arquivo não compila ainda.",
        "O código não executa com sucesso.",
        "Não rodou localmente.",
        "No code was executed by this service.",
        "The explanation mentions compilation only as a caution.",
    ],
)
def test_explicit_negations_are_allowed(text: str) -> None:
    assert_no_execution_claims(text)


def test_empty_text_is_allowed() -> None:
    assert_no_execution_claims("")


def test_new_totvs_identifiers_without_version_are_reported() -> None:
    original = "User Function Teste()\n    FWInit()\nReturn Nil\n"
    corrected = (
        "User Function Teste()\n"
        "    FWInit()\n"
        "    FWNovoRecurso()\n"
        "    MsExecAuto()\n"
        "Return Nil\n"
    )

    issues = detect_unverified_totvs_usage(
        original,
        corrected,
        "Added the required call.",
        protheus_version=None,
    )

    codes = sorted(issue.code for issue in issues)
    assert codes == ["FWNovoRecurso", "MsExecAuto"]
    assert all(issue.severity == "low" for issue in issues)
    assert all(issue.cause == "unverified_totvs_api" for issue in issues)
    assert all(issue.origin == "ai" for issue in issues)


def test_existing_totvs_identifiers_are_not_reported() -> None:
    source = "User Function Teste()\n    FWInit()\nReturn Nil\n"

    issues = detect_unverified_totvs_usage(
        source,
        source + "\n// unchanged\n",
        "",
        protheus_version=None,
    )

    assert issues == []


def test_version_suppresses_unverified_totvs_issues() -> None:
    issues = detect_unverified_totvs_usage(
        "User Function Teste()\nReturn Nil\n",
        "User Function Teste()\n    FWNovoRecurso()\nReturn Nil\n",
        "",
        protheus_version="12.1.2410",
    )

    assert issues == []
