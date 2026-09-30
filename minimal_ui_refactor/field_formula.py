"""Arithmetic and text handling over the editable sidebar fields.

User-defined buttons compute a value from the fields currently on screen and
write it into another field — for example ``Match = LMIG_Exp * 0.10`` or
``Slug = snake(Gov & " " & FY)``.

A field is read as text and coerced to a number wherever the formula does
arithmetic, so the same expression language covers both jobs:

* numbers  — ``+ - * / // % **`` and :data:`ALLOWED_FUNCTIONS`
* text     — ``&`` joins (as in a spreadsheet) and :data:`TEXT_FUNCTIONS`
             cover case changes, replacement, and trimming

``+`` stays arithmetic even between two pieces of text; joining is always
written with ``&`` or ``concat()`` so a formula never silently changes meaning
because a scraped field happened to hold digits.

Expressions are parsed with :mod:`ast` and walked against an explicit
allow-list, never ``eval``. Only literals, the editable fields, the operators
above, and the allowed functions can appear; attribute access, indexing,
comparisons, and every other call are rejected.
"""

from __future__ import annotations

import ast
import operator
import re


class FormulaError(ValueError):
    """A formula could not be read or evaluated. The message is user-facing."""


def _round(value, digits=0):
    """``round`` for formulas: every value here is a float, including digits."""
    return round(float(value), int(digits))


#: Splits a value into words for the case-changing functions. Runs of letters
#: and digits are words, and so are the humps of an existing camelCase name,
#: so ``"LMIGExpTotal"`` and ``"lmig exp total"`` reduce to the same words.
_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def _words(text) -> list[str]:
    return _WORDS.findall(str(text))


def _camel(text):
    """``"total local exp"`` -> ``"totalLocalExp"``."""
    words = [word.lower() for word in _words(text)]
    if not words:
        return ""
    return words[0] + "".join(word.title() for word in words[1:])


def _pascal(text):
    """``"total local exp"`` -> ``"TotalLocalExp"``."""
    return "".join(word.lower().title() for word in _words(text))


def _snake(text):
    """``"Total Local Exp"`` -> ``"total_local_exp"``."""
    return "_".join(word.lower() for word in _words(text))


def _kebab(text):
    """``"Total Local Exp"`` -> ``"total-local-exp"``."""
    return "-".join(word.lower() for word in _words(text))


def _concat(*parts):
    """Join every argument end to end, exactly as ``&`` does."""
    return "".join(parts)


def _replace(text, old, new):
    """Swap every occurrence of ``old`` for ``new`` — ``replace(x, ",", "-")``."""
    if not old:
        raise FormulaError("replace() cannot search for an empty string.")
    return text.replace(old, new)


def _trim(text):
    """Drop leading and trailing whitespace."""
    return text.strip()


#: The callables that work on numbers. Their arguments are read as numbers.
ALLOWED_FUNCTIONS = {
    "abs": abs,
    "max": max,
    "min": min,
    "round": _round,
}

#: The callables that work on text. Their arguments are read as text, so a
#: number may be passed straight in: ``upper(Gov & " " & FY)``.
TEXT_FUNCTIONS = {
    "lower": str.lower,
    "upper": str.upper,
    "title": str.title,
    "sentence": str.capitalize,
    "camel": _camel,
    "pascal": _pascal,
    "snake": _snake,
    "kebab": _kebab,
    "trim": _trim,
    "replace": _replace,
    "concat": _concat,
}


def function_names() -> list[str]:
    """Every function a formula may call, for help text and error messages."""
    return sorted({*ALLOWED_FUNCTIONS, *TEXT_FUNCTIONS})


class FieldText(str):
    """One field's text, tagged with the name the formula knows it by.

    It is an ordinary string everywhere it is used; the name only exists so
    that a failed conversion can say *which* field was not a number.
    """

    name = ""

    def __new__(cls, text, name=""):
        instance = super().__new__(cls, "" if text is None else str(text))
        instance.name = str(name or "")
        return instance


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

#: Characters stripped from a scraped value before reading it as a number.
_NOISE = re.compile(r"[,\s$£€%]")


def variable_name(column) -> str:
    """The identifier a formula uses for a MID column.

    Column names may contain spaces and punctuation, which cannot appear in an
    expression, so each is reduced to a plain identifier: ``"LMIG Exp"`` and
    ``"LMIG_Exp"`` are both written ``LMIG_Exp``.
    """
    cleaned = re.sub(r"\W+", "_", str(column or "")).strip("_")
    if not cleaned:
        return ""
    if cleaned[0].isdigit():
        cleaned = f"n_{cleaned}"
    return cleaned


def variable_names(columns) -> dict[str, str]:
    """``{identifier: column}`` for every column that yields a usable name."""
    names = {}
    for column in columns:
        name = variable_name(column)
        if name and name not in names:
            names[name] = column
    return names


def to_number(text):
    """Read a number out of a scraped field value, or return ``None``.

    Tolerates the shapes numbers take in published documents: thousands
    separators, currency symbols, a trailing percent sign, and accounting-style
    negatives such as ``(1,234)``.
    """
    raw = str(text if text is not None else "").strip()
    if not raw:
        return None

    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]

    raw = _NOISE.sub("", raw)
    if raw.startswith("-"):
        negative = not negative
        raw = raw[1:]
    elif raw.startswith("+"):
        raw = raw[1:]

    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return -value if negative else value


def field_values(texts) -> dict[str, FieldText]:
    """Turn ``{column: text}`` into ``{identifier: FieldText}``.

    Every field arrives as text; arithmetic converts on demand, so the one
    mapping serves a numeric formula and a text formula alike.
    """
    values = {}
    for column, text in texts.items():
        name = variable_name(column)
        if name:
            values[name] = FieldText(text, name)
    return values


def evaluate(expression, values) -> float | str:
    """Evaluate ``expression`` against ``{identifier: text}``.

    Returns a float for an arithmetic formula and a string for a text one.
    """
    text = str(expression or "").strip()
    if not text:
        raise FormulaError("The formula is empty.")

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Could not read the formula: {exc.msg}") from exc

    return _evaluate(tree.body, values)


def _describe(node) -> str:
    """How to refer to ``node`` in an error message."""
    if isinstance(node, ast.Name):
        return f"'{node.id}'"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return f"{node.func.id}()"
    return "that value"


def _number_to_text(value) -> str:
    """Render a computed number for use inside a text formula."""
    value = float(value)
    return str(int(value)) if value.is_integer() else repr(value)


def _as_number(node, values) -> float:
    """Evaluate ``node`` and read the result as a number."""
    value = _evaluate(node, values)
    if not isinstance(value, str):
        return float(value)

    number = to_number(value)
    if number is not None:
        return number
    if isinstance(node, ast.Name):
        raise FormulaError(f"'{node.id}' is empty or is not a number.")
    raise FormulaError(
        f"Only numbers can be used here, but {_describe(node)} is text. "
        "Use & or concat() to join text."
    )


def _as_text(node, values) -> str:
    """Evaluate ``node`` and read the result as text."""
    value = _evaluate(node, values)
    if isinstance(value, str):
        # Drop the FieldText tag; past this point it is an ordinary string.
        return str(value)
    return _number_to_text(value)


def _evaluate(node, values) -> float | str:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError("Only numbers and quoted text may appear in a formula.")
        return float(node.value)

    if isinstance(node, ast.Name):
        if node.id in values:
            return values[node.id]
        raise FormulaError(f"'{node.id}' is not one of the editable fields.")

    if isinstance(node, ast.BinOp):
        # "&" joins text, as it does in a spreadsheet; everything else is
        # arithmetic, including "+" between two pieces of text.
        if isinstance(node.op, ast.BitAnd):
            return _as_text(node.left, values) + _as_text(node.right, values)

        handler = _BINARY_OPERATORS.get(type(node.op))
        if handler is None:
            raise FormulaError(
                f"{type(node.op).__name__} is not allowed in a formula."
            )
        left = _as_number(node.left, values)
        right = _as_number(node.right, values)
        try:
            return float(handler(left, right))
        except ZeroDivisionError:
            raise FormulaError("The formula divides by zero.") from None
        except (OverflowError, ValueError) as exc:
            raise FormulaError(f"The formula could not be computed: {exc}") from exc

    if isinstance(node, ast.UnaryOp):
        handler = _UNARY_OPERATORS.get(type(node.op))
        if handler is None:
            raise FormulaError(
                f"{type(node.op).__name__} is not allowed in a formula."
            )
        return float(handler(_as_number(node.operand, values)))

    if isinstance(node, ast.Call):
        return _call(node, values)

    raise FormulaError(
        f"{type(node).__name__} is not allowed in a formula. "
        "Formulas may use the editable fields, numbers, quoted text, "
        "arithmetic, & and the allowed functions only."
    )


def _call(node, values) -> float | str:
    """Run one allowed function, reading its arguments the way it expects."""
    name = node.func.id if isinstance(node.func, ast.Name) else None
    if name not in ALLOWED_FUNCTIONS and name not in TEXT_FUNCTIONS:
        allowed = ", ".join(function_names())
        raise FormulaError(f"Only these functions may be used: {allowed}.")
    if node.keywords:
        raise FormulaError("Formula functions do not take named arguments.")

    if name in TEXT_FUNCTIONS:
        arguments = [_as_text(argument, values) for argument in node.args]
        try:
            return str(TEXT_FUNCTIONS[name](*arguments))
        except TypeError as exc:
            raise FormulaError(f"{name}() got the wrong arguments.") from exc

    arguments = [_as_number(argument, values) for argument in node.args]
    try:
        return float(ALLOWED_FUNCTIONS[name](*arguments))
    except TypeError as exc:
        raise FormulaError(f"{name}() got the wrong arguments.") from exc


def format_result(value, decimals: int = 2) -> str:
    """Render a computed value for a text field.

    A text result is already final; only a number takes the button's decimals.
    """
    if isinstance(value, str):
        return str(value)
    decimals = max(0, int(decimals))
    if decimals == 0:
        return str(int(round(value)))
    return f"{value:.{decimals}f}"


def validate(expression, columns) -> None:
    """Raise :class:`FormulaError` if ``expression`` cannot run over ``columns``.

    Checks the shape and the field names without needing real values, so the
    settings dialog can reject a bad formula at the point it is written.
    """
    probe = {name: FieldText("1", name) for name in variable_names(columns)}
    evaluate(expression, probe)
