"""V2 offline spreadsheet calculation engine.

A bounded, purpose-written parser evaluates a conservative Excel-like subset.
It never invokes Python eval/exec, OS/network APIs, UDFs, volatile functions,
external workbooks, macros or user-provided code. Original cell text is not
mutated. Intended to serve small owner-controlled workbook previews, not
financial accounting or a drop-in Excel engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from typing import Any

MAX_FORMULA_LENGTH = 300
MAX_FORMULAS = 500
MAX_AST_NODES = 200
MAX_DEPTH = 60
MAX_EVAL_STEPS = 30_000
MAX_ABS = Decimal("1000000000000")
_TOKEN = re.compile(
    r'\s*(?:(?P<num>[0-9]+(?:\.[0-9]+)?)|'
    r'(?P<text>"(?:[^"]|"")*")|'
    r'(?P<word>[A-Za-z_][A-Za-z_0-9]*)|'
    r'(?P<op><>|<=|>=|[+\-*/^(),:=<>]))',
    re.ASCII,
)
_REF = re.compile(r"^([A-Za-z]+)([1-9][0-9]*)$", re.ASCII)
_FUNCTIONS = frozenset(("SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "IF"))
_PRECEDENCE = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1,
               "+": 2, "-": 2, "*": 3, "/": 3, "^": 4}


@dataclass
class FormulaError(Exception):
    code: str
    detail: str

    def __str__(self):
        return self.code


def _ref(raw: str) -> tuple[int, int]:
    m = _REF.fullmatch(raw)
    if not m:
        raise FormulaError("#NAME?", "Unknown identifier or function.")
    col = 0
    for letter in m.group(1).upper():
        col = col * 26 + ord(letter) - ord("A") + 1
        if col > 16:
            raise FormulaError("#REF!", "Cell references must be in columns A–P.")
    row = int(m.group(2))
    if not 1 <= row <= 100:
        raise FormulaError("#REF!", "Cell references must be in rows 1–100.")
    return row - 1, col - 1


def _label(row: int, col: int) -> str:
    return f"{chr(65 + col)}{row + 1}"


class Parser:
    def __init__(self, source: str):
        if not source.startswith("=") or len(source) > MAX_FORMULA_LENGTH:
            raise FormulaError("#PARSE!", "Formula must begin with = and be at most 300 characters.")
        self.tokens: list[tuple[str, str]] = []
        pos = 1
        while pos < len(source):
            if not source[pos:].strip():
                break
            match = _TOKEN.match(source, pos)
            if not match or match.end() <= pos:
                raise FormulaError("#PARSE!", "Formula contains unsupported syntax.")
            token_type = match.lastgroup
            value = match.group(token_type)
            self.tokens.append((token_type, value))
            if len(self.tokens) > MAX_AST_NODES:
                raise FormulaError("#LIMIT!", "Formula has too many tokens.")
            pos = match.end()
        self.pos = 0
        self.node_count = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos][1] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        if self.pos >= len(self.tokens):
            raise FormulaError("#PARSE!", "Formula ended unexpectedly.")
        value = self.tokens[self.pos]
        self.pos += 1
        return value

    def expect(self, value: str):
        if self.peek() != value:
            raise FormulaError("#PARSE!", "Expected " + value + " in formula.")
        self.take()

    def node(self, *parts):
        self.node_count += 1
        if self.node_count > MAX_AST_NODES:
            raise FormulaError("#LIMIT!", "Formula exceeds complexity limit.")
        return parts

    def parse(self):
        root = self.expression(0, 0)
        if self.peek() is not None:
            raise FormulaError("#PARSE!", "Unexpected trailing formula input.")
        return root

    def expression(self, min_priority: int, depth: int):
        if depth > MAX_DEPTH:
            raise FormulaError("#LIMIT!", "Formula nesting is too deep.")
        kind, word = self.take()
        if word in ("+", "-"):
            left = self.node("unary", word, self.expression(4, depth + 1))
        elif word == "(":
            left = self.expression(0, depth + 1)
            self.expect(")")
        elif kind == "num":
            try:
                left = self.node("number", Decimal(word))
            except InvalidOperation:
                raise FormulaError("#NUM!", "Invalid numeric literal.") from None
        elif kind == "text":
            left = self.node("text", word[1:-1].replace('""', '"'))
        elif kind == "word":
            upper = word.upper()
            if self.peek() == "(":
                self.take()
                args = []
                if self.peek() != ")":
                    while True:
                        if len(args) >= 20:
                            raise FormulaError("#LIMIT!", "Too many function arguments.")
                        args.append(self.expression(0, depth + 1))
                        if self.peek() != ",":
                            break
                        self.take()
                self.expect(")")
                if upper not in _FUNCTIONS:
                    raise FormulaError("#NAME?", "Unsupported spreadsheet function.")
                if upper == "IF" and len(args) != 3:
                    raise FormulaError("#PARSE!", "IF requires three arguments.")
                if upper != "IF" and not args:
                    raise FormulaError("#PARSE!", "Aggregate needs an argument.")
                left = self.node("call", upper, args)
            elif upper in ("TRUE", "FALSE"):
                left = self.node("bool", upper == "TRUE")
            else:
                _ref(word)  # validate early; no named ranges in v2
                left = self.node("ref", upper)
                if self.peek() == ":":
                    self.take()
                    ref_kind, finish = self.take()
                    if ref_kind != "word":
                        raise FormulaError("#PARSE!", "A range needs two cell references.")
                    _ref(finish)
                    left = self.node("range", upper, finish.upper())
        else:
            raise FormulaError("#PARSE!", "Expected a number, cell, or supported function.")
        while (symbol := self.peek()) in _PRECEDENCE and _PRECEDENCE[symbol] >= min_priority:
            self.take()
            priority = _PRECEDENCE[symbol]
            # Exponentiation is right-associative; other operators are left-associative.
            right = self.expression(priority if symbol == "^" else priority + 1, depth + 1)
            left = self.node("binary", symbol, left, right)
        return left


def _within(value: Decimal) -> Decimal:
    if not value.is_finite() or abs(value) > MAX_ABS:
        raise FormulaError("#NUM!", "Calculated value is outside the supported range.")
    return value


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, (int, float)):
        return _within(Decimal(str(value)))
    raise FormulaError("#VALUE!", "An arithmetic operand is not a number.")


def _display(value: Any) -> str | bool | None:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise FormulaError("#NUM!", "Non-finite result.")
        return format(value.normalize(), "f") if value else "0"
    return value


def _value_truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    if isinstance(value, (Decimal, int, float)):
        return bool(value)
    raise FormulaError("#VALUE!", "IF condition must be a boolean or numeric value.")


def _range_cells(first: str, last: str) -> list[tuple[int, int]]:
    a, b = _ref(first), _ref(last)
    if a[0] > b[0] or a[1] > b[1]:
        raise FormulaError("#REF!", "Ranges must run top-left to bottom-right.")
    return [(row, col) for row in range(a[0], b[0] + 1)
            for col in range(a[1], b[1] + 1)]


def _dependencies(node: tuple) -> set[tuple[int, int]]:
    kind = node[0]
    if kind == "ref":
        return {_ref(node[1])}
    if kind == "range":
        return set(_range_cells(node[1], node[2]))
    if kind == "unary":
        return _dependencies(node[2])
    if kind == "binary":
        return _dependencies(node[2]) | _dependencies(node[3])
    if kind == "call":
        result: set[tuple[int, int]] = set()
        for arg in node[2]:
            result.update(_dependencies(arg))
        return result
    return set()


def calculate(workbook: dict[str, Any]) -> dict[str, Any]:
    """Compute limited, same-sheet formulas. Read-only; never save or execute code."""
    if workbook.get("calculation_mode", "literal") != "formulas":
        return {"mode": "literal", "formula_count": 0, "results": [], "errors": [],
                "limitations": "Legacy/literal workbooks never evaluate =-prefixed text."}
    sheets = workbook["sheets"]
    expressions: dict[tuple[int, int, int], tuple] = {}
    parsing_errors: dict[tuple[int, int, int], FormulaError] = {}
    for sheet_index, sheet in enumerate(sheets):
        for row_index, row in enumerate(sheet["rows"]):
            for col_index, raw in enumerate(row):
                if not isinstance(raw, str) or not raw.startswith("="):
                    continue
                key = (sheet_index, row_index, col_index)
                if len(expressions) + len(parsing_errors) >= MAX_FORMULAS:
                    raise FormulaError("#LIMIT!", "V2 supports at most 500 formulas per workbook.")
                try:
                    expressions[key] = Parser(raw).parse()
                except FormulaError as exc:
                    parsing_errors[key] = exc
    memo: dict[tuple[int, int, int], Any] = {}
    busy: set[tuple[int, int, int]] = set()
    steps = 0

    def evaluate_cell(key: tuple[int, int, int], depth: int) -> Any:
        nonlocal steps
        steps += 1
        if steps > MAX_EVAL_STEPS or depth > MAX_DEPTH:
            raise FormulaError("#LIMIT!", "Formula evaluation exceeded resource limits.")
        if key in memo:
            value = memo[key]
            if isinstance(value, FormulaError):
                raise value
            return value
        if key in busy:
            raise FormulaError("#CYCLE!", "Circular cell dependency detected.")
        sheet_id, row_id, col_id = key
        rows = sheets[sheet_id]["rows"]
        raw = rows[row_id][col_id] if row_id < len(rows) and col_id < len(rows[row_id]) else None
        if key not in expressions and key not in parsing_errors:
            return raw
        if key in parsing_errors:
            raise parsing_errors[key]
        busy.add(key)
        try:
            value = evaluate(expressions[key], sheet_id, depth + 1)
            memo[key] = value
            return value
        except FormulaError as exc:
            memo[key] = exc
            raise
        finally:
            busy.remove(key)

    def evaluate(node: tuple, sheet_id: int, depth: int) -> Any:
        nonlocal steps
        steps += 1
        if steps > MAX_EVAL_STEPS or depth > MAX_DEPTH:
            raise FormulaError("#LIMIT!", "Formula evaluation exceeded resource limits.")
        kind = node[0]
        if kind in ("number", "text", "bool"):
            return node[1]
        if kind == "ref":
            row_id, col_id = _ref(node[1])
            return evaluate_cell((sheet_id, row_id, col_id), depth + 1)
        if kind == "range":
            raise FormulaError("#VALUE!", "Cell ranges can only appear inside aggregate functions.")
        if kind == "unary":
            value = _decimal(evaluate(node[2], sheet_id, depth + 1))
            return _within(value if node[1] == "+" else -value)
        if kind == "binary":
            op = node[1]
            left = evaluate(node[2], sheet_id, depth + 1)
            right = evaluate(node[3], sheet_id, depth + 1)
            if op in ("=", "<>", "<", ">", "<=", ">="):
                if isinstance(left, str) and isinstance(right, str):
                    a, b = left.casefold(), right.casefold()
                else:
                    a, b = _decimal(left), _decimal(right)
                return {"=": a == b, "<>": a != b, "<": a < b,
                        ">": a > b, "<=": a <= b, ">=": a >= b}[op]
            a, b = _decimal(left), _decimal(right)
            with localcontext() as ctx:
                ctx.prec = 28
                try:
                    if op == "+": return _within(a + b)
                    if op == "-": return _within(a - b)
                    if op == "*": return _within(a * b)
                    if op == "/":
                        if not b: raise FormulaError("#DIV/0!", "Cannot divide by zero.")
                        return _within(a / b)
                    if op == "^":
                        if b != b.to_integral_value() or abs(b) > 12:
                            raise FormulaError("#NUM!", "Power must use a small integer exponent.")
                        return _within(a ** int(b))
                except (InvalidOperation, OverflowError, DivisionByZero):
                    raise FormulaError("#NUM!", "Invalid numeric operation.") from None
            raise FormulaError("#PARSE!", "Unknown operator.")
        if kind == "call":
            function, args = node[1], node[2]
            if function == "IF":
                condition = evaluate(args[0], sheet_id, depth + 1)
                return evaluate(args[1] if _value_truth(condition) else args[2], sheet_id, depth + 1)
            flattened: list[Any] = []
            for argument in args:
                if argument[0] == "range":
                    for row_id, col_id in _range_cells(argument[1], argument[2]):
                        flattened.append(evaluate_cell((sheet_id, row_id, col_id), depth + 1))
                else:
                    flattened.append(evaluate(argument, sheet_id, depth + 1))
            if function == "COUNTA":
                return Decimal(sum(value is not None and value != "" for value in flattened))
            nums: list[Decimal] = []
            for value in flattened:
                if isinstance(value, bool) or value is None or value == "":
                    continue
                if isinstance(value, (Decimal, int, float)):
                    nums.append(_decimal(value))
                # Text stored in a referenced cell or range is not silently coerced.
            if function == "COUNT":
                return Decimal(len(nums))
            if function == "SUM":
                return _within(sum(nums, Decimal(0)))
            if function == "AVERAGE":
                if not nums: raise FormulaError("#DIV/0!", "No numeric values to average.")
                return _within(sum(nums, Decimal(0)) / len(nums))
            if function == "MIN":
                if not nums: raise FormulaError("#VALUE!", "MIN requires numeric data.")
                return _within(min(nums))
            if function == "MAX":
                if not nums: raise FormulaError("#VALUE!", "MAX requires numeric data.")
                return _within(max(nums))
        raise FormulaError("#NAME?", "Unsupported formula element.")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for key in sorted(set(expressions) | set(parsing_errors)):
        sheet_id, row, col = key
        entry: dict[str, Any] = {"sheet": sheets[sheet_id]["name"], "cell": _label(row, col)}
        try:
            entry["value"] = _display(evaluate_cell(key, 0))
            entry["dependencies"] = (
                sorted(_label(r, c) for r, c in _dependencies(expressions[key]))
                if key in expressions else []
            )
        except FormulaError as exc:
            entry["value"] = exc.code
            entry["error"] = exc.code
            errors.append({"sheet": entry["sheet"], "cell": entry["cell"],
                           "code": exc.code, "detail": exc.detail})
        results.append(entry)
    return {"mode": "formulas", "formula_count": len(results), "results": results,
            "errors": errors, "limits": {"max_formulas": MAX_FORMULAS,
                                       "max_formula_characters": MAX_FORMULA_LENGTH},
            "limitations": "Same-sheet formulas only; no external workbook links, macros, "
                           "volatile functions, named ranges or full Excel compatibility. "
                           "XLSX recalculation occurs in a compatible spreadsheet application."}
