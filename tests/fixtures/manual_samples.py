"""Snippets used while validating the language validators by hand.

Every constant reproduces a real snippet used during manual validation of the
Python, JavaScript, CSS, and HTML validators. The automated tests import them so
that the hand-written checks and the regression suite stay aligned.

The snippets are intentionally small: they document exactly which constructs
must be detected and which ones are deliberately out of scope.
"""

from __future__ import annotations

#: Non-zero literal division by a value without a static guarantee.
MANUAL_PYTHON_DIVISION_BY_LEN = """\
def calc(lista):
    return 10 / len(lista)
"""

#: Name read without any binding or builtin.
MANUAL_PYTHON_UNDEFINED_NAME = """\
print(variavel_nao_definida)
"""

#: Call with mixed argument types; not detected (no type inference).
MANUAL_PYTHON_MIXED_CALL = """\
def soma(a, b):
    return a + b


soma("texto", 1)
"""

#: Index computed at runtime; not detected (only literal subscripts are checked).
MANUAL_PYTHON_DYNAMIC_INDEX = """\
lista = [1, 2]
i = 0
print(lista[i + 1])
"""

#: Literal division by zero.
MANUAL_PYTHON_DIVISION_BY_ZERO = """\
def calc():
    return 10 / 0
"""

#: Assignment where a comparison was probably intended.
MANUAL_JS_ASSIGNMENT_IN_CONDITION = """\
let x = 0;
if (x = 1) {
  console.log(x);
}
"""

#: Loop counter updated in the opposite direction of the condition.
MANUAL_JS_LOOP_WITHOUT_PROGRESS = """\
for (let i = 0; i < 10; i--) {
  console.log(i);
}
"""

#: Loose equality between literals of different types.
MANUAL_JS_LOOSE_EQUALITY = """\
if ("1" == 1) {
  console.log("mesmo valor");
}
"""

#: NaN compared with itself.
MANUAL_JS_NAN_COMPARISON = """\
const value = NaN;
if (value === NaN) {
  console.log(value);
}
"""

#: Invalid color and mistyped properties from a manual CSS review.
MANUAL_CSS_INVALID_VALUES = """\
.a {
  color: invalidcolor;
  background: notacolor;
  colour: red;
  widht: 10px;
}
"""

#: HTML document with the accessibility/metadata gaps reported by hand.
MANUAL_HTML_GAPS = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <img src="logo.png">
  <input type="text">
  <button></button>
  <a href="https://example.com" target="_blank">link</a>
</body>
</html>
"""
