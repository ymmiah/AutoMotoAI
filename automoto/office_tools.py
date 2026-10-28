"""Agent tools for Word, Excel, PowerPoint and PDF (group ``office``)."""

from __future__ import annotations

import base64
import io
import json
from typing import Any

from automoto import config, office, sandbox
from automoto.tools import I, S, Tool, ToolContext, ToolFailed, _obj

DOCX = {".docx"}
XLSX = {".xlsx"}
PPTX = {".pptx"}
OBJ = {"type": "object"}


def _spec(spec: Any) -> dict[str, Any]:
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError as exc:
            raise ToolFailed(f"spec is not valid JSON: {exc}") from None
    if not isinstance(spec, dict):
        raise ToolFailed("spec must be a JSON object")
    return spec


def _wrap(fn):
    def inner(ctx: ToolContext, **kw: Any) -> str:
        try:
            return fn(ctx, **kw)
        except office.OfficeError as exc:
            raise ToolFailed(str(exc)) from None
        except ImportError as exc:
            raise ToolFailed(f"missing Python package ({exc.name}) - pip install -r requirements.txt (python-docx, openpyxl, python-pptx, pypdf)") from None
    return inner


@_wrap
def create_docx(ctx: ToolContext, path: str, spec: Any) -> str:
    from automoto import office_build

    return office_build.create_docx(_spec(spec), office.resolve_out(path, DOCX))


@_wrap
def create_xlsx(ctx: ToolContext, path: str, spec: Any) -> str:
    from automoto import office_build

    return office_build.create_xlsx(_spec(spec), office.resolve_out(path, XLSX))


@_wrap
def create_pptx(ctx: ToolContext, path: str, spec: Any) -> str:
    from automoto import office_build

    return office_build.create_pptx(_spec(spec), office.resolve_out(path, PPTX))


@_wrap
def read(ctx: ToolContext, path: str, sheet: str = "", max_rows: int = 60, max_chars: int = 20000) -> str:
    return office.read(path, max_chars=min(int(max_chars or 20000), 60000), sheet=sheet or None, max_rows=int(max_rows or 60))


@_wrap
def edit(ctx: ToolContext, path: str, replace: list | None = None, cells: dict | None = None,
         append: list | None = None, notes: dict | None = None) -> str:
    from automoto import office_build

    return office_build.edit(office.resolve_in(path), replace=replace, cells=cells, append=append, notes=notes)


@_wrap
def convert(ctx: ToolContext, path: str, to: str, out: str = "") -> str:
    return office.convert(path, to, out or None)


@_wrap
def recalc(ctx: ToolContext, path: str, save: bool = False) -> str:
    return office.recalc(path, save=bool(save))


@_wrap
def render(ctx: ToolContext, path: str, first: int = 1, last: int = 3, dpi: int = 80) -> str:
    pages = office.render(path, first or 1, last or 3, dpi or 80)
    return "rendered:\n" + "\n".join(sandbox.rel(p) for p in pages) + \
        "\nUse office_review to have a vision model critique the layout, or open the PNGs."


@_wrap
def check(ctx: ToolContext, path: str) -> str:
    from automoto import office_check

    return office_check.check(path)


REVIEW_PROMPT = (
    "You are a meticulous document designer reviewing rendered pages of a {kind}. For each page list concrete "
    "layout problems: text overflowing or cut off, overlapping elements, inconsistent fonts/sizes/colours, poor "
    "alignment or margins, orphan headings, tables or images split badly, low contrast, empty placeholders, "
    "crowded slides, missing page numbers or captions. Then give an overall verdict (publication-ready or not) "
    "and the 3 most important fixes. Be brief and specific; reference page numbers.")


def contact_sheet(pngs: list, max_width: int = 1800) -> bytes:
    """Tile rendered pages into ONE labelled image (many vision models accept a single image per prompt)."""
    from PIL import Image, ImageDraw

    ims = [Image.open(p).convert("RGB") for p in pngs]
    try:
        cols = 1 if len(ims) == 1 else 2 if len(ims) <= 4 else 3
        cell_w = max_width // cols
        scaled = [im.resize((cell_w - 16, max(1, int(im.height * (cell_w - 16) / im.width)))) for im in ims]
        cell_h = max(im.height for im in scaled) + 40
        rows = -(-len(scaled) // cols)
        sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), (200, 200, 200))
        d = ImageDraw.Draw(sheet)
        for k, im in enumerate(scaled):
            x, y = (k % cols) * cell_w + 8, (k // cols) * cell_h + 32
            sheet.paste(im, (x, y))
            d.text((x, y - 24), f"Page {k + 1}", fill=(0, 0, 0))
        buf = io.BytesIO()
        sheet.save(buf, "JPEG", quality=85, optimize=True)  # small enough for every provider's image limit
        return buf.getvalue()
    finally:
        for im in ims:
            im.close()


@_wrap
def review(ctx: ToolContext, path: str, pages: int = 4, focus: str = "") -> str:
    from automoto import router

    pngs = office.render(path, 1, max(1, min(int(pages or 4), 6)), 70)
    ext = office.resolve_in(path).suffix.lower()
    kind = "slide deck" if ext in office.IMPRESS else "spreadsheet" if ext in office.CALC else "document"
    prompt = REVIEW_PROMPT.format(kind=kind) + f" The image shows {len(pngs)} page(s), labelled 'Page n'." + \
        (f" Focus: {focus}" if focus else "")
    img = base64.b64encode(contact_sheet(pngs)).decode()
    parts: list[dict[str, Any]] = [{"type": "text", "text": prompt},
                                   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + img}}]
    ans = router.ask([{"role": "user", "content": parts}], need_vision=True, keys=ctx.keys or None,
                     task_hint="review the layout of rendered document pages", careful=True,
                     max_tokens=max(4000, config.max_tokens()))
    fell = [f"{t.get('model')}: {t.get('error', '')[:80]}" for t in getattr(ans, "tried", []) or [] if not t.get("ok")]
    note = f" [fell back after: {'; '.join(fell)}]" if fell else ""
    return (f"layout review of {len(pngs)} page(s) by {getattr(ans, 'model', 'vision model')}{note} "
            f"(advisory - vision models can be wrong; confirm with office_check / office_read):\n{ans.text}")


SPEC_DOCX = ("JSON spec: {properties:{title,author}, header, footer, page:{size:'A4'|'letter', margins_cm, orientation}, "
             "theme:{font, heading_font, size, heading_color, justify}, page_numbers:true, blocks:[...]} where each block is "
             "{type:'title_page', title, subtitle, author, student_id, course, module, institution, supervisor, date, word_count} | "
             "{type:'toc', levels} | {type:'heading', level, text} | {type:'paragraph', text, align, comment} (inline **bold**, "
             "*italic*, `code`, [link](https://…)) | {type:'bullets'|'numbered', items:['a', ['nested', 1]]} | {type:'quote', text} | "
             "{type:'table', caption, rows:[[header…],[…]], style, source} | {type:'image', path, caption, alt, width_cm} | "
             "{type:'page_break'} | {type:'references', items:[{authors:['Surname, A.'], year, title, journal, volume, issue, pages, "
             "doi, publisher, place, edition, url, accessed, type:'book'|'journal'|'web'}]} (Harvard, sorted). "
             "A TOC gets real page numbers automatically when LibreOffice is installed.")
SPEC_XLSX = ("JSON spec: {properties:{title,author}, theme:{header_fill, font}, sheets:[{name, rows:[[…]] (strings starting "
             "with = are formulas), start:'A1', header:true, number_formats:{'B2:D20':'£#,##0.00'}, bold:['A20:D20'], "
             "col_widths:'auto'|{A:20}, freeze:'A2', autofilter:true, conditional:[{type:'color_scale'|'data_bar'|'cell_is'|'formula', "
             "range, operator, values, formula}], validation:[{range, values:[…]}], charts:[{type:'column'|'bar'|'line'|'pie'|'scatter', "
             "data:'B1:C13' (row 1 = series names), categories:'A2:A13', title, x_title, y_title, anchor:'F2'}], tab_color, landscape}], "
             "names:[{name, ref:'Sheet!$B$2'}]}. Then run office_recalc to verify every formula.")
SPEC_PPTX = ("JSON spec: {aspect:'16:9', theme:{primary, accent, text, background, font, heading_font}, footer, slide_numbers:true, "
             "slides:[{layout:'title'|'section'|'bullets'|'two_content'|'comparison'|'image'|'table'|'chart'|'statement'|'quote', "
             "title, subtitle, bullets:['point', ['sub-point', 1]], left, right, left_title, right_title, right_image, image, caption, "
             "alt, rows:[[…]], chart:{type:'column'|'bar'|'line'|'pie'|'stacked', categories, series:[{name, values}], number_format}, "
             "text, attribution, notes:'speaker notes'}]}. Keep 3-6 bullets per slide, one idea per slide; put detail in notes.")

TOOLS: list[Tool] = [
    Tool("office_create_docx", "Create a Word .docx (reports, essays, letters) with real heading styles, title page, TOC, "
         "tables, images with captions, page numbers and Harvard references. " + SPEC_DOCX,
         _obj({"path": {**S, "description": "output .docx path"}, "spec": OBJ}, ["path", "spec"]), "risky", create_docx, "office"),
    Tool("office_create_xlsx", "Create an Excel .xlsx with formulas, number formats, conditional formatting, validation, "
         "frozen panes and charts. " + SPEC_XLSX,
         _obj({"path": S, "spec": OBJ}, ["path", "spec"]), "risky", create_xlsx, "office"),
    Tool("office_create_pptx", "Create a PowerPoint .pptx with a consistent theme, layouts, images, tables, charts and "
         "speaker notes. " + SPEC_PPTX,
         _obj({"path": S, "spec": OBJ}, ["path", "spec"]), "risky", create_pptx, "office"),
    Tool("office_read", "Read a Word/Excel/PowerPoint/PDF/OpenDocument file (also legacy .doc/.xls/.ppt via LibreOffice) "
         "as text: headings, tables, cell values and formulas, slides and notes. Macros are never run.",
         _obj({"path": S, "sheet": S, "max_rows": I, "max_chars": I}, ["path"]), "safe", read, "office"),
    Tool("office_edit", "Edit an existing .docx/.xlsx/.pptx in place: replace:[{old,new}] text (keeps formatting), "
         "cells:{'Sheet!B2': 42 or '=SUM(…)'} for Excel, append:[docx blocks] to add content to Word, "
         "notes:{'3':'speaker notes'} for slides.",
         _obj({"path": S, "replace": {"type": "array", "items": OBJ}, "cells": OBJ, "append": {"type": "array", "items": OBJ},
               "notes": OBJ}, ["path"]), "risky", edit, "office"),
    Tool("office_convert", "Convert between formats with LibreOffice headless (macros disabled): to pdf (tagged, fonts embedded), "
         "docx, xlsx, pptx, odt, ods, odp, html, txt, csv, rtf, md. Markdown → docx/pdf supported.",
         _obj({"path": S, "to": S, "out": {**S, "description": "output path (default: next to the input)"}}, ["path", "to"]),
         "risky", convert, "office"),
    Tool("office_recalc", "Recalculate every formula in a spreadsheet with LibreOffice and report values and errors "
         "(#REF!, #DIV/0!…). save=true writes name.recalc.xlsx with cached values filled in.",
         _obj({"path": S, "save": {"type": "boolean"}}, ["path"]), "safe", recalc, "office"),
    Tool("office_render", "Render pages/slides of a document or PDF to PNG images (in scratch/renders/) to look at the layout.",
         _obj({"path": S, "first": I, "last": I, "dpi": I}, ["path"]), "safe", render, "office"),
    Tool("office_check", "Publication lint for docx/xlsx/pptx/pdf: heading hierarchy, alt text, TOC/cross-reference problems, "
         "formula errors, empty placeholders, slide text overflow, small fonts, fonts embedded, tagged PDF.",
         _obj({"path": S}, ["path"]), "safe", check, "office"),
    Tool("office_review", "Render the first pages and ask a vision model to critique the layout (overflow, alignment, "
         "consistency). Use after office_check before calling something publication-ready.",
         _obj({"path": S, "pages": I, "focus": S}, ["path"]), "safe", review, "office"),
]
