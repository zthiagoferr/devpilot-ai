"""Unified diff and export-name helpers."""

from __future__ import annotations

from app.services.correction_diff import (
    build_unified_diff,
    export_filename,
    iter_added_lines,
)


def test_unified_diff_contains_standard_markers() -> None:
    original = "def total(items):\n    return 0\n"
    corrected = "def total(items):\n    return sum(items)\n"

    diff = build_unified_diff(original, corrected, "src/app.py")

    assert "--- a/src/app.py" in diff
    assert "+++ b/src/app.py" in diff
    assert "@@" in diff
    assert "-    return 0" in diff
    assert "+    return sum(items)" in diff


def test_diff_uses_generic_labels_without_a_path() -> None:
    diff = build_unified_diff("a\n", "b\n")

    assert "--- a/source" in diff
    assert "+++ b/source" in diff


def test_diff_handles_missing_trailing_newline() -> None:
    diff = build_unified_diff("a = 1", "a = 2")

    assert "-a = 1" in diff
    assert "+a = 2" in diff


def test_diff_of_identical_content_is_empty() -> None:
    assert build_unified_diff("x = 1\n", "x = 1\n", "x.py") == ""


def test_iter_added_lines_ignores_headers_and_removals() -> None:
    diff = build_unified_diff(
        "a = 1\nb = 2\n",
        "a = 1\nc = 3\n",
        "src/app.py",
    )

    assert iter_added_lines(diff) == ["c = 3"]


def test_iter_added_lines_of_an_empty_diff_is_empty() -> None:
    assert iter_added_lines("") == []


def test_export_filename_uses_language_extension() -> None:
    assert export_filename("src/app.py", "python") == "app.py"
    assert export_filename("src/app.prw", "advpl") == "app.prw"
    assert export_filename("index.html", "html") == "index.html"
    assert export_filename("styles.css", "css") == "styles.css"
    assert export_filename("main.js", "javascript") == "main.js"


def test_export_filename_uses_suffix_override() -> None:
    assert export_filename("src/app.py", "python", "diff") == "app.diff"
    assert export_filename("src/app.py", "python", ".json") == "app.json"


def test_export_filename_strips_directories_and_control_characters() -> None:
    assert export_filename("../../etc/passwd", "python") == "passwd.py"
    assert export_filename("..\\..\\windows\\system32\\cmd.exe", "python") == "cmd.py"
    assert export_filename("weird\x00name.py", "python") == "weirdname.py"
    assert export_filename("bad\nname.py", "python") == "badname.py"


def test_export_filename_falls_back_to_a_safe_name() -> None:
    assert export_filename(None, None) == "correction.txt"
    assert export_filename("   ", "unknown-language") == "correction.txt"
    assert export_filename("/", "python") == "correction.py"
