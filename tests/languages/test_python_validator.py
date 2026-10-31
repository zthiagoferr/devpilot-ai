"""Tests for the restricted Python syntax validator."""

from __future__ import annotations

from app.languages.base import ValidationContext
from app.languages.validators.python import PythonValidator
from tests.fixtures import manual_samples


def validate(source: str, context: ValidationContext | None = None):
    return PythonValidator().validate(source, context or ValidationContext())


def causes(result) -> list[str]:
    return [issue.cause for issue in result.issues]


def test_valid_python_syntax() -> None:
    result = validate(
        "def run(value):\n    return value + 1\n",
        ValidationContext(path="app/main.py"),
    )

    assert result.language == "python"
    assert result.issues == ()
    assert result.score == 100
    assert result.metadata["validator"]["name"] == "python_ast"


def test_python_syntax_error_has_line_and_column() -> None:
    result = validate(
        "def run(:\n    pass\n",
        ValidationContext(path="app/main.py"),
    )
    issues = result.issues

    assert len(issues) == 1
    assert issues[0].severity == "critical"
    assert issues[0].cause == "python_syntax"
    assert issues[0].line == 1
    assert issues[0].column is not None
    assert issues[0].file == "app/main.py"


def test_python_bom_is_tolerated() -> None:
    result = validate("\ufeffvalue = 1\n", ValidationContext())
    assert result.issues == ()


def test_python_source_is_parsed_not_executed() -> None:
    source = "import os\n\nos._exit(1)\n"
    result = validate(source, ValidationContext())
    assert result.issues == ()


def test_undefined_name_is_high() -> None:
    result = validate(
        manual_samples.MANUAL_PYTHON_UNDEFINED_NAME,
        ValidationContext(path="app/main.py"),
    )
    undefined = [issue for issue in result.issues if issue.cause == "undefined_name"]

    assert len(undefined) == 1
    assert undefined[0].severity == "high"
    assert "variavel_nao_definida" in undefined[0].message
    assert undefined[0].line == 1
    assert undefined[0].file == "app/main.py"


def test_undefined_name_ignores_late_bindings() -> None:
    source = (
        "def early():\n"
        "    return shared\n"
        "\n"
        "shared = 1\n"
    )
    result = validate(source)
    assert result.issues == ()


def test_undefined_name_accepts_builtins_params_and_comprehensions() -> None:
    source = (
        "import os\n"
        "\n"
        "from dataclasses import dataclass\n"
        "\n"
        "\n"
        "@dataclass\n"
        "class Item:\n"
        "    name: str\n"
        "\n"
        "\n"
        "def build(values, *args, **kwargs):\n"
        "    with open(os.devnull) as handle:\n"
        "        data = [item for item in values if item]\n"
        "        try:\n"
        "            return {key: handle for key in data}\n"
        "        except ValueError as error:\n"
        "            print(error, data, args, kwargs, len(data))\n"
        "            return {}\n"
    )
    result = validate(source)
    assert result.issues == ()


def test_undefined_name_is_disabled_for_star_imports() -> None:
    source = "from os.path import *\n\nprint(join('a', 'b'))\n"
    result = validate(source)
    assert "undefined_name" not in causes(result)


def test_undefined_name_respects_global_and_nonlocal() -> None:
    source = (
        "counter = 0\n"
        "\n"
        "\n"
        "def increment():\n"
        "    global counter\n"
        "    counter += 1\n"
        "\n"
        "\n"
        "def outer():\n"
        "    total = 1\n"
        "\n"
        "    def inner():\n"
        "        nonlocal total\n"
        "        total += 1\n"
        "\n"
        "    return inner\n"
    )
    result = validate(source)
    assert "undefined_name" not in causes(result)


def test_division_by_zero_is_high() -> None:
    result = validate(manual_samples.MANUAL_PYTHON_DIVISION_BY_ZERO)
    zero = [issue for issue in result.issues if issue.cause == "division_by_zero"]

    assert len(zero) == 1
    assert zero[0].severity == "high"
    assert zero[0].line == 2
    assert "'/'" in zero[0].message


def test_modulo_by_zero_is_high() -> None:
    result = validate("value = 10 % 0\n")
    zero = [issue for issue in result.issues if issue.cause == "division_by_zero"]

    assert len(zero) == 1
    assert zero[0].severity == "high"
    assert "'%'" in zero[0].message


def test_floor_division_by_zero_is_high() -> None:
    result = validate("value = 10 // 0\n")
    zero = [issue for issue in result.issues if issue.cause == "division_by_zero"]

    assert len(zero) == 1
    assert zero[0].severity == "high"
    assert zero[0].line == 1
    assert "'//'" in zero[0].message


def test_floor_division_by_runtime_value_is_not_reported() -> None:
    result = validate("values = [1, 2]\nresult = 10 // len(values)\n")
    assert "division_by_zero" not in causes(result)


def test_division_by_runtime_length_is_not_reported() -> None:
    result = validate(manual_samples.MANUAL_PYTHON_DIVISION_BY_LEN)
    assert "division_by_zero" not in causes(result)


def test_incompatible_operand_types_is_medium() -> None:
    result = validate('total = "total: " + 1\n')
    incompatible = [
        issue for issue in result.issues if issue.cause == "incompatible_operand_types"
    ]

    assert len(incompatible) == 1
    assert incompatible[0].severity == "medium"
    assert "str" in incompatible[0].message
    assert "number" in incompatible[0].message


def test_same_type_constant_operations_are_not_reported() -> None:
    result = validate('texto = "a" + "b"\nnumero = 1 + 2\n')
    assert "incompatible_operand_types" not in causes(result)


def test_index_out_of_range_is_medium() -> None:
    result = validate("values = [10, 20]\nprint([10, 20][5])\n")
    out_of_range = [
        issue for issue in result.issues if issue.cause == "index_out_of_range"
    ]

    assert len(out_of_range) == 1
    assert out_of_range[0].severity == "medium"
    assert out_of_range[0].line == 2


def test_dynamic_index_is_not_reported() -> None:
    result = validate(manual_samples.MANUAL_PYTHON_DYNAMIC_INDEX)
    assert "index_out_of_range" not in causes(result)


def test_negative_and_valid_literal_indexes_are_not_reported() -> None:
    result = validate("print([1, 2][1])\nprint([1, 2][-1])\n")
    assert "index_out_of_range" not in causes(result)


def test_break_and_continue_outside_loops_are_reported() -> None:
    result = validate("break\ncontinue\n")
    result_causes = causes(result)

    assert "break_outside_loop" in result_causes
    assert "continue_outside_loop" in result_causes


def test_return_outside_function_is_reported() -> None:
    result = validate("return 1\n")
    outside = [
        issue for issue in result.issues if issue.cause == "return_outside_function"
    ]

    assert len(outside) == 1
    assert outside[0].severity == "medium"


def test_break_inside_loop_and_return_inside_function_are_silent() -> None:
    source = (
        "def scan(values):\n"
        "    for value in values:\n"
        "        if not value:\n"
        "            continue\n"
        "        if value > 10:\n"
        "            break\n"
        "    return None\n"
    )
    result = validate(source)
    assert result.issues == ()


def test_duplicate_dict_key_is_low() -> None:
    result = validate('data = {"a": 1, "a": 2}\n')
    duplicate = [
        issue for issue in result.issues if issue.cause == "duplicate_dict_key"
    ]

    assert len(duplicate) == 1
    assert duplicate[0].severity == "low"


def test_mixed_argument_call_is_not_reported() -> None:
    result = validate(manual_samples.MANUAL_PYTHON_MIXED_CALL)
    assert result.issues == ()


def test_coverage_metadata_matches_declared_checks() -> None:
    result = validate("value = 1\n")

    coverage = result.metadata["coverage"]
    assert coverage["checks"] == [
        "syntax",
        "undefined_names",
        "constant_operations",
        "literals",
        # Added for coherence: the implemented break/continue/return checks
        # were already reported but missing from the declared coverage.
        "control_flow",
    ]
    assert coverage["limitations"]


def test_syntax_error_score_is_graded_not_binary() -> None:
    """The validator grades issues; ``CodeAgent`` keeps its legacy 0/100 contract."""
    result = validate("def run(:\n    pass\n")

    assert result.issues[0].severity == "critical"
    assert result.score == 50
