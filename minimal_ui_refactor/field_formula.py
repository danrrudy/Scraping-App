"""Arithmetic over the editable sidebar fields.

User-defined buttons compute a value from the fields currently on screen and
write it into another field — for example ``Match = LMIG_Exp * 0.10``.

Expressions are parsed with :mod:`ast` and walked against an explicit
allow-list, never ``eval``. Only numbers, the editable fields, arithmetic
operators, and the functions in :data:`ALLOWED_FUNCTIONS` can appear;
attribute access, indexing, comparisons, and every other call are rejected.
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


#: The only callables a formula may use.
ALLOWED_FUNCTIONS = {
    "abs": abs,
    "max": max,
    "min": min,
    "round": _round,
}

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


def field_values(texts) -> dict[str, float | None]:
    """Turn ``{column: text}`` into ``{identifier: number or None}``."""
    return {
        variable_name(column): to_number(text)
        for column, text in texts.items()
        if variable_name(column)
    }


def evaluate(expression, values) -> float:
    """Evaluate ``expression`` against ``{identifier: number or None}``."""
    text = str(expression or "").strip()
    if not text:
        raise FormulaError("The formula is empty.")

    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Could not read the formula: {exc.msg}") from exc

    return _evaluate(tree.body, values)


def _evaluate(node, values) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError("Only numbers may appear in a formula.")
        return float(node.value)

    if isinstance(node, ast.Name):
        if node.id in values:
            value = values[node.id]
            if value is None:
                raise FormulaError(f"'{node.id}' is empty or is not a number.")
            return float(value)
        raise FormulaError(f"'{node.id}' is not one of the editable fields.")

    if isinstance(node, ast.BinOp):
        handler = _BINARY_OPERATORS.get(type(node.op))
        if handler is None:
            raise FormulaError(
                f"{type(node.op).__name__} is not allowed in a formula."
            )
        left = _evaluate(node.left, values)
        right = _evaluate(node.right, values)
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
        return float(handler(_evaluate(node.operand, values)))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
            allowed = ", ".join(sorted(ALLOWED_FUNCTIONS))
            raise FormulaError(f"Only these functions may be used: {allowed}.")
        if node.keywords:
            raise FormulaError("Formula functions do not take named arguments.")
        arguments = [_evaluate(argument, values) for argument in node.args]
        try:
            return float(ALLOWED_FUNCTIONS[node.func.id](*arguments))
        except TypeError as exc:
            raise FormulaError(f"{node.func.id}() got the wrong arguments.") from exc

    raise FormulaError(
        f"{type(node).__name__} is not allowed in a formula. "
        "Formulas may use the editable fields, numbers, and arithmetic only."
    )


def format_result(value, decimals: int = 2) -> str:
    """Render a computed value for a text field."""
    decimals = max(0, int(decimals))
    if decimals == 0:
        return str(int(round(value)))
    return f"{value:.{decimals}f}"


def validate(expression, columns) -> None:
    """Raise :class:`FormulaError` if ``expression`` cannot run over ``columns``.

    Checks the shape and the field names without needing real values, so the
    settings dialog can reject a bad formula at the point it is written.
    """
    probe = dict.fromkeys(variable_names(columns), 1.0)
    evaluate(expression, probe)
