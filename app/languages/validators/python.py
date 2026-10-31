"""Static Python validator used for post-correction checks.

This validator parses with :mod:`ast` only. It does not compile, import, or
execute the analyzed source, and it does not replace the ``CodeAgent``. Besides
syntax errors, it performs a deliberately conservative set of AST checks:

* names read without any binding in scope (``undefined_name``);
* division, floor division, and modulo by a literal zero
  (``division_by_zero``);
* addition of two incompatible literal constants
  (``incompatible_operand_types``);
* a literal subscript beyond the end of a literal list/tuple
  (``index_out_of_range``);
* ``break``/``continue`` outside a loop and ``return`` outside a function;
* duplicate literal keys in a dictionary.

The scope analysis intentionally prefers false negatives over false positives:
a name is only reported when it is not bound anywhere in the module and is not
a builtin. Dynamic behavior (``exec``, star imports, metaprogramming) is not
modeled.

Relationship with the legacy ``CodeAgent``
(:mod:`app.agents.code_agent`): that agent keeps its original binary contract
(``score`` 0 when ``ast.parse`` fails, 100 otherwise, ignoring every semantic
finding). This validator deliberately does **not** change that contract. For the
same input it returns a graded score (``100`` minus per-severity weights), so a
syntax error is ``critical`` and scores ``50`` rather than ``0``, and the extra
checks listed above can lower the score further. Consumers that need the legacy
0/100 behavior must keep using ``CodeAgent``.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass

from app.languages.base import (
    Detection,
    LanguageIssue,
    ValidationContext,
    ValidationResult,
    compute_score,
)

#: Deterministic checks implemented by this validator and what it does not cover.
COVERAGE: dict[str, list[str]] = {
    "checks": [
        "syntax",
        "undefined_names",
        "constant_operations",
        "literals",
        "control_flow",
    ],
    "limitations": [
        "Heuristic static analysis; no runtime or type inference beyond literals; "
        "may miss dynamic behavior",
        "No imports, types, or external modules are resolved",
        "No code is compiled, imported, or executed",
    ],
}

#: Module-level names Python provides (plus interpreter-provided dunders).
_BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins)) | frozenset(
    {
        "__name__",
        "__file__",
        "__doc__",
        "__package__",
        "__spec__",
        "__loader__",
        "__builtins__",
        "__class__",
        "__annotations__",
        "__module__",
        "__qualname__",
        "__dict__",
        "__slots__",
        "__weakref__",
        "__debug__",
    }
)


@dataclass(slots=True)
class _Scope:
    """One lexical scope and the names bound in it."""

    kind: str
    parent: "_Scope | None"
    bindings: set[str]
    globals: set[str]
    nonlocals: set[str]


def _new_scope(kind: str, parent: _Scope | None) -> _Scope:
    return _Scope(kind=kind, parent=parent, bindings=set(), globals=set(), nonlocals=set())


def _all_arguments(arguments: ast.arguments) -> list[ast.arg]:
    found = list(arguments.posonlyargs) + list(arguments.args)
    if arguments.vararg is not None:
        found.append(arguments.vararg)
    found.extend(arguments.kwonlyargs)
    if arguments.kwarg is not None:
        found.append(arguments.kwarg)
    return found


class _BindingCollector(ast.NodeVisitor):
    """Collect every name binding per lexical scope (no loads are resolved)."""

    def __init__(self) -> None:
        self.module = _new_scope("module", None)
        self.scopes: dict[int, _Scope] = {}
        self.has_star_import = False
        self._stack: list[_Scope] = [self.module]

    @property
    def current(self) -> _Scope:
        return self._stack[-1]

    def _bind(self, name: str | None) -> None:
        if name:
            self.current.bindings.add(name)

    def _bind_target(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Name):
            self._bind(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                self._bind_target(element)
        elif isinstance(node, ast.Starred):
            self._bind_target(node.value)

    def visit_Module(self, node: ast.Module) -> None:
        for statement in node.body:
            self.visit(statement)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._bind(node.name)
        scope = _new_scope("function", self.current)
        self.scopes[id(node)] = scope
        for argument in _all_arguments(node.args):
            scope.bindings.add(argument.arg)
        for parameter in getattr(node, "type_params", ()) or ():
            name = getattr(parameter, "name", None)
            if isinstance(name, str):
                scope.bindings.add(name)
        self._stack.append(scope)
        for statement in node.body:
            self.visit(statement)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._bind(node.name)
        scope = _new_scope("class", self.current)
        self.scopes[id(node)] = scope
        self._stack.append(scope)
        for statement in node.body:
            self.visit(statement)
        self._stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        scope = _new_scope("function", self.current)
        self.scopes[id(node)] = scope
        for argument in _all_arguments(node.args):
            scope.bindings.add(argument.arg)
        self._stack.append(scope)
        self.visit(node.body)
        self._stack.pop()

    def _visit_comprehension(self, node: ast.AST, values: list[ast.AST]) -> None:
        scope = _new_scope("comprehension", self.current)
        self.scopes[id(node)] = scope
        self._stack.append(scope)
        for generator in node.generators:  # type: ignore[attr-defined]
            self.visit(generator.iter)
            self._bind_target(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        for value in values:
            self.visit(value)
        self._stack.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, [node.elt])

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, [node.elt])

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, [node.elt])

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, [node.key, node.value])

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self._bind_target(node.target)
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    def visit_For(self, node: ast.For) -> None:
        self._visit_for(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_for(node)

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars)
        for statement in node.body:
            self.visit(statement)

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._bind(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._bind(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                self.has_star_import = True
            else:
                self._bind(alias.asname or alias.name)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._bind_target(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        self._bind_target(node.target)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self._bind_target(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_target(node.target)

    def visit_Global(self, node: ast.Global) -> None:
        self.current.globals.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.current.nonlocals.update(node.names)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.pattern is not None:
            self.visit(node.pattern)
        self._bind(node.name)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        self._bind(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        self._bind(node.rest)

    def visit_TypeAlias(self, node: ast.AST) -> None:
        name = getattr(node, "name", None)
        if isinstance(name, ast.Name):
            self._bind(name.id)
        value = getattr(node, "value", None)
        if isinstance(value, ast.AST):
            self.visit(value)


class _UndefinedNameChecker(ast.NodeVisitor):
    """Report ``Name`` loads that no lexical scope or builtin can resolve."""

    def __init__(self, collector: _BindingCollector) -> None:
        self.module = collector.module
        self.scopes = collector.scopes
        self.all_bound = set(self.module.bindings)
        for scope in self.scopes.values():
            self.all_bound |= scope.bindings
        self._stack: list[_Scope] = [self.module]
        self.issues: list[tuple[str, int, int]] = []

    def _resolves(self, name: str) -> bool:
        for scope in reversed(self._stack):
            if name in scope.bindings:
                return True
            if name in scope.globals:
                return name in self.module.bindings
        return False

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load) or node.id in _BUILTIN_NAMES:
            return
        if self._resolves(node.id) or node.id in self.all_bound:
            return
        self.issues.append(
            (
                f"Name '{node.id}' is used but not defined in an enclosing scope.",
                node.lineno,
                node.col_offset + 1,
            )
        )

    def _visit_defaults(self, arguments: ast.arguments) -> None:
        for default in arguments.defaults:
            self.visit(default)
        for default in arguments.kw_defaults:
            if default is not None:
                self.visit(default)
        for argument in _all_arguments(arguments):
            if argument.annotation is not None:
                self.visit(argument.annotation)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_defaults(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        scope = self.scopes.get(id(node))
        if scope is None:
            for statement in node.body:
                self.visit(statement)
            return
        self._stack.append(scope)
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        scope = self.scopes.get(id(node))
        if scope is None:
            for statement in node.body:
                self.visit(statement)
            return
        self._stack.append(scope)
        try:
            for statement in node.body:
                self.visit(statement)
        finally:
            self._stack.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_defaults(node.args)
        scope = self.scopes.get(id(node))
        if scope is None:
            self.visit(node.body)
            return
        self._stack.append(scope)
        try:
            self.visit(node.body)
        finally:
            self._stack.pop()

    def _visit_comprehension(self, node: ast.AST, values: list[ast.AST]) -> None:
        scope = self.scopes.get(id(node))
        if scope is None:
            self.generic_visit(node)
            return
        self._stack.append(scope)
        try:
            for generator in node.generators:  # type: ignore[attr-defined]
                self.visit(generator.iter)
                self.visit(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)
            for value in values:
                self.visit(value)
        finally:
            self._stack.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, [node.elt])

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, [node.elt])

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, [node.elt])

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, [node.key, node.value])


def _is_literal_zero(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value == 0
    )


def _literal_kind(value: object) -> str | None:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "none"
    if isinstance(value, bytes):
        return "bytes"
    return None


class _ConstantChecker(ast.NodeVisitor):
    """Deterministic checks that need no type inference beyond literals."""

    def __init__(self) -> None:
        self.issues: list[tuple[str, str, int, int]] = []
        self.loop_depth = 0
        self.function_depth = 0

    def _add(self, severity: str, message: str, cause: str, node: ast.AST) -> None:
        self.issues.append(
            (severity, message, cause, node.lineno, node.col_offset + 1)
        )

    def _visit_function(self, node: ast.AST) -> None:
        previous_loop = self.loop_depth
        self.loop_depth = 0
        self.function_depth += 1
        self.generic_visit(node)
        self.function_depth -= 1
        self.loop_depth = previous_loop

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_function(node)

    def _visit_loop(self, node: ast.AST) -> None:
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_loop(node)

    def visit_Break(self, node: ast.Break) -> None:
        if self.loop_depth == 0:
            self._add(
                "medium",
                "Break statement outside a loop.",
                "break_outside_loop",
                node,
            )

    def visit_Continue(self, node: ast.Continue) -> None:
        if self.loop_depth == 0:
            self._add(
                "medium",
                "Continue statement outside a loop.",
                "continue_outside_loop",
                node,
            )

    def visit_Return(self, node: ast.Return) -> None:
        if self.function_depth == 0:
            self._add(
                "medium",
                "Return statement outside a function.",
                "return_outside_function",
                node,
            )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            right = node.right
            if isinstance(right, ast.Constant) and _is_literal_zero(right.value):
                operator = {
                    ast.Div: "/",
                    ast.FloorDiv: "//",
                    ast.Mod: "%",
                }[type(node.op)]
                self._add(
                    "high",
                    f"Division by zero using the '{operator}' operator.",
                    "division_by_zero",
                    node,
                )

        if isinstance(node.op, ast.Add):
            left = node.left
            right = node.right
            if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
                left_kind = _literal_kind(left.value)
                right_kind = _literal_kind(right.value)
                if {left_kind, right_kind} == {"str", "number"}:
                    self._add(
                        "medium",
                        (
                            f"Cannot add a {left_kind} literal and a "
                            f"{right_kind} literal."
                        ),
                        "incompatible_operand_types",
                        node,
                    )

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        container = node.value
        if isinstance(container, (ast.List, ast.Tuple)) and not any(
            isinstance(element, ast.Starred) for element in container.elts
        ):
            index = node.slice
            if (
                isinstance(index, ast.Constant)
                and isinstance(index.value, int)
                and not isinstance(index.value, bool)
                and index.value >= len(container.elts)
            ):
                self._add(
                    "medium",
                    (
                        f"Index {index.value} is out of range for a literal of "
                        f"length {len(container.elts)}."
                    ),
                    "index_out_of_range",
                    node,
                )
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        seen: set[object] = set()
        for key in node.keys:
            if not isinstance(key, ast.Constant):
                continue
            try:
                hash(key.value)
            except TypeError:
                continue
            if key.value in seen:
                self._add(
                    "low",
                    f"Duplicate key {key.value!r} in a dictionary literal.",
                    "duplicate_dict_key",
                    key,
                )
            else:
                seen.add(key.value)
        self.generic_visit(node)


class PythonValidator:
    """Check Python syntax and a curated set of static AST defects."""

    language = "python"
    coverage = COVERAGE

    def __init__(self, detection: Detection | None = None) -> None:
        self._detection = detection

    def validate(
        self,
        source: str,
        context: ValidationContext | None = None,
    ) -> ValidationResult:
        """Return deterministic findings for ``source`` without executing it."""
        context = context or ValidationContext()
        text = source[1:] if source.startswith("\ufeff") else source
        issues: list[LanguageIssue] = []

        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            issues.append(
                LanguageIssue(
                    severity="critical",
                    message=f"Python syntax error: {exc.msg}",
                    cause="python_syntax",
                    file=context.path,
                    line=exc.lineno,
                    column=exc.offset,
                    language=self.language,
                )
            )
            tree = None
        except (ValueError, TypeError) as exc:
            issues.append(
                LanguageIssue(
                    severity="critical",
                    message=f"Python source could not be parsed: {type(exc).__name__}.",
                    cause="python_syntax",
                    file=context.path,
                    language=self.language,
                )
            )
            tree = None

        if tree is not None:
            issues.extend(self._semantic_issues(tree, context))

        detection = self._detection or Detection(
            language="python",
            source="extension",
            confidence=0.99,
            reason="python_validator",
            candidates=(("python", 0.99),),
        )
        issue_tuple = tuple(issues)
        if not issue_tuple:
            summary = "Python static analysis found no issues."
        elif any(issue.cause == "python_syntax" for issue in issue_tuple):
            summary = "Python syntax parsing reported an error."
        else:
            summary = (
                f"Python static analysis reported {len(issue_tuple)} issue(s)."
            )
        return ValidationResult(
            language=self.language,
            detection=detection,
            issues=issue_tuple,
            score=compute_score(issue_tuple),
            summary=summary,
            metadata={
                "validator": {
                    "name": "python_ast",
                    "official": False,
                    "disclaimer": (
                        "Static analysis with the standard library AST. "
                        "No code is compiled or executed."
                    ),
                },
                "coverage": dict(COVERAGE),
            },
        )

    def _semantic_issues(
        self,
        tree: ast.Module,
        context: ValidationContext,
    ) -> list[LanguageIssue]:
        collector = _BindingCollector()
        collector.visit(tree)

        issues: list[LanguageIssue] = []

        # A star import can inject arbitrary names into the module namespace;
        # resolving names would then be guesswork, so the check is skipped.
        if not collector.has_star_import:
            checker = _UndefinedNameChecker(collector)
            checker.visit(tree)
            for message, line, column in checker.issues:
                issues.append(
                    LanguageIssue(
                        severity="high",
                        message=message,
                        cause="undefined_name",
                        file=context.path,
                        line=line,
                        column=column,
                        language=self.language,
                    )
                )

        constants = _ConstantChecker()
        constants.visit(tree)
        for severity, message, cause, line, column in constants.issues:
            issues.append(
                LanguageIssue(
                    severity=severity,  # type: ignore[arg-type]
                    message=message,
                    cause=cause,
                    file=context.path,
                    line=line,
                    column=column,
                    language=self.language,
                )
            )

        issues.sort(key=lambda item: (item.line or 0, item.column or 0))
        return issues
