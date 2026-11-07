"""Spreadsheet v3: bounded, declarative cell formatting and Excel validation.

Formatting is metadata only: no macros, formulas as validation rules, external
links or executable style expressions. Legacy workbook rows remain unchanged.
"""
from __future__ import annotations

import math
import re
from typing import Any, Literal

from fastapi import HTTPException
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import BaseModel, ConfigDict, Field, model_validator

COLUMN = re.compile(r"^[A-P]$")
CELL = re.compile(r"^([A-P])(100|[1-9][0-9]?)$")
COLOUR = r"^#[0-9A-Fa-f]{6}$"
FORMAT_MAP = {
    "general": "General",
    "number": "#,##0.00",
    "integer": "#,##0",
    "gbp": '"£"#,##0.00',
    "usd": '"$"#,##0.00',
    "eur": '"€"#,##0.00',
    "percent": "0.00%",
}
MAX_STYLES = 500


class CellFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bold: bool = False
    italic: bool = False
    align: Literal["left", "center", "right"] = "left"
    fill: str = Field("#FFFFFF", pattern=COLOUR)
    color: str = Field("#1E293B", pattern=COLOUR)
    number_format: Literal["general", "number", "integer", "gbp", "usd", "eur", "percent"] = "general"


class ColumnValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(..., pattern=r"^[A-P]$")
    kind: Literal["list", "whole", "decimal"]
    options: list[str] = Field(default_factory=list, max_length=10)
    min_value: float | None = Field(None, ge=-1e9, le=1e9, allow_inf_nan=False)
    max_value: float | None = Field(None, ge=-1e9, le=1e9, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_definition(self):
        if self.kind == "list":
            if not self.options or self.min_value is not None or self.max_value is not None:
                raise ValueError("List validation needs choices and no numeric bounds.")
            if any(not item or len(item) > 40 or re.search(r'[,=\r\n"]', item)
                   for item in self.options):
                raise ValueError("List choices must be short, non-empty, and contain no commas or formulas.")
            if len(set(self.options)) != len(self.options) or len(",".join(self.options)) > 240:
                raise ValueError("List choices must be unique and fit inside an Excel validation.")
        else:
            if self.options or self.min_value is None or self.max_value is None or self.min_value > self.max_value:
                raise ValueError("Numeric validation requires ordered min/max values.")
            if self.kind == "whole" and (not self.min_value.is_integer() or not self.max_value.is_integer()):
                raise ValueError("Whole-number validation bounds must be integers.")
        return self


def normalise_metadata(sheet: Any, rows: list[list[Any]]) -> dict[str, Any]:
    """Validate and copy only metadata explicitly supplied by the caller."""
    fields = sheet.model_fields_set
    result: dict[str, Any] = {}
    if "cell_styles" in fields:
        for address in sheet.cell_styles:
            if not CELL.fullmatch(address):
                raise HTTPException(422, "Styles require an A1:P100 cell address.")
        result["cell_styles"] = {key: value.model_dump() for key, value in sheet.cell_styles.items()}
    if "freeze" in fields:
        result["freeze"] = sheet.freeze
    if "filter_enabled" in fields:
        result["filter_enabled"] = sheet.filter_enabled
    if "column_widths" in fields:
        if any(not COLUMN.fullmatch(key) for key in sheet.column_widths):
            raise HTTPException(422, "Widths require a column A–P.")
        result["column_widths"] = dict(sheet.column_widths)
    if "validations" in fields:
        seen = set()
        for rule in sheet.validations:
            if rule.column in seen:
                raise HTTPException(422, "One validation rule per column is allowed.")
            seen.add(rule.column)
            index = ord(rule.column) - 65
            for row in rows[1:]:  # First row is always the heading, not validated.
                if index >= len(row) or row[index] is None or row[index] == "":
                    continue
                value = row[index]
                if isinstance(value, str) and value.startswith("="):
                    raise HTTPException(422, f"Formulas are not permitted in validated column {rule.column}.")
                if rule.kind == "list" and str(value) not in rule.options:
                    raise HTTPException(422, f"Column {rule.column} contains a value outside its permitted list.")
                if rule.kind != "list":
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise HTTPException(422, f"Column {rule.column} requires numeric values.")
                    if rule.kind == "whole" and not float(value).is_integer():
                        raise HTTPException(422, f"Column {rule.column} requires whole numbers.")
                    if not rule.min_value <= value <= rule.max_value:
                        raise HTTPException(422, f"Column {rule.column} is outside its numeric validation limits.")
        result["validations"] = [rule.model_dump() for rule in sheet.validations]
    return result


def apply_formatting(ws: Any, sheet: dict[str, Any]) -> None:
    for address, style in sheet.get("cell_styles", {}).items():
        c = ws[address]
        c.font = Font(name="Aptos", size=11, bold=style["bold"], italic=style["italic"],
                      color=style["color"][1:])
        c.fill = PatternFill("solid", fgColor=style["fill"][1:])
        c.alignment = Alignment(horizontal=style["align"], vertical="center", wrap_text=True)
        c.number_format = FORMAT_MAP[style["number_format"]]
    freeze = sheet.get("freeze")
    if freeze is not None:
        ws.freeze_panes = {"none": None, "row": "A2", "column": "B1", "both": "B2"}[freeze]
    if "filter_enabled" in sheet:
        ws.auto_filter.ref = None
        if sheet["filter_enabled"] and sheet["rows"]:
            width = max((len(row) for row in sheet["rows"]), default=1)
            if width:
                ws.auto_filter.ref = f"A1:{chr(64+width)}{len(sheet['rows'])}"
    for letter, width in sheet.get("column_widths", {}).items():
        ws.column_dimensions[letter].width = width
    for rule in sheet.get("validations", []):
        kind = rule["kind"]
        if kind == "list":
            validation = DataValidation(type="list", formula1='"' + ",".join(rule["options"]) + '"',
                                        allow_blank=True)
        else:
            validation = DataValidation(type=kind, operator="between",
                                        formula1=str(rule["min_value"]), formula2=str(rule["max_value"]),
                                        allow_blank=True)
        validation.showErrorMessage = True
        validation.error = "Enter a value that meets the column rule."
        validation.errorTitle = "Invalid worksheet value"
        ws.add_data_validation(validation)
        validation.add(f"{rule['column']}2:{rule['column']}100")


def import_cell_style(cell: Any, warnings: set[str]) -> dict[str, Any] | None:
    """Safely extract visible bounded styles; unsupported Excel styles are never copied raw."""
    if not getattr(cell, "has_style", False):
        return None
    result = CellFormat().model_dump()
    result["bold"] = bool(cell.font.bold)
    result["italic"] = bool(cell.font.italic)
    if cell.alignment.horizontal in ("left", "center", "right"):
        result["align"] = cell.alignment.horizontal
    for key, obj in (("fill", cell.fill.fgColor), ("color", cell.font.color)):
        if obj is not None and obj.type == "rgb" and isinstance(obj.rgb, str) and len(obj.rgb) == 8:
            result[key] = "#" + obj.rgb[-6:].upper()
    for identifier, number_format in FORMAT_MAP.items():
        if cell.number_format == number_format:
            result["number_format"] = identifier
            break
    else:
        if cell.number_format not in ("General", "0"):
            warnings.add("Some custom Excel number formats were not imported.")
    return result if result != CellFormat().model_dump() else None
