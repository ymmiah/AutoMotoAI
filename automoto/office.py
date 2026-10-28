"""Office documents (Word, Excel, PowerPoint, OpenDocument, PDF) with free tools only.

* Build and edit .docx / .xlsx / .pptx with python-docx, openpyxl and python-pptx (``office_build``).
* Read anything, convert, export PDF and recalculate formulas through **LibreOffice headless**.
  It runs with a throwaway profile: macros disabled, VBA not loaded, links never updated.
* Render PDF pages to PNG with ``pdftoppm`` so a vision model can review the layout.
* Lint documents for publication problems (``check``).

Office files are untrusted input. Before parsing, every package is checked for size, zip bombs and
DTD/ENTITY declarations (XXE). Macros are reported, never run, and external links are listed, never followed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from automoto import sandbox

MAX_FILE = 60 * 1024 * 1024          # bytes on disk
MAX_UNZIPPED = 400 * 1024 * 1024     # total uncompressed size of a package
MAX_ENTRIES = 10000
MAX_RATIO = 250                      # uncompressed / compressed, per entry over 1 MB
MAX_XML_SCAN = 25 * 1024 * 1024

WORD = {".docx", ".docm", ".dotx", ".doc", ".odt", ".rtf"}
CALC = {".xlsx", ".xlsm", ".xltx", ".xls", ".ods", ".csv"}
IMPRESS = {".pptx", ".pptm", ".potx", ".ppt", ".odp"}
OOXML = {".docx", ".docm", ".dotx", ".xlsx", ".xlsm", ".xltx", ".pptx", ".pptm", ".potx"}
ODF = {".odt", ".ods", ".odp"}
LEGACY = {".doc", ".xls", ".ppt", ".rtf"}


class OfficeError(ValueError):
    pass


# -- untrusted-file checks -------------------------------------------------------------
_DTD = re.compile(rb"<!(DOCTYPE|ENTITY)", re.I)


def inspect_file(p: Path) -> dict[str, Any]:
    """Size / zip-bomb / XXE checks. Returns facts (macros, external links). Raises OfficeError."""
    if not p.is_file():
        raise OfficeError(f"no such file: {p.name}")
    size = p.stat().st_size
    if size > MAX_FILE:
        raise OfficeError(f"{p.name} is {size // 1048576} MB - the limit is {MAX_FILE // 1048576} MB")
    info: dict[str, Any] = {"size": size, "macros": False, "external_links": []}
    ext = p.suffix.lower()
    if ext in OOXML | ODF:
        try:
            zf = zipfile.ZipFile(p)
        except zipfile.BadZipFile:
            raise OfficeError(f"{p.name} is not a valid {ext} file (bad zip)") from None
        with zf:
            entries = zf.infolist()
            if len(entries) > MAX_ENTRIES:
                raise OfficeError("too many parts in the package (possible zip bomb)")
            total = 0
            for e in entries:
                total += e.file_size
                if e.file_size > 1048576 and e.compress_size and e.file_size / e.compress_size > MAX_RATIO:
                    raise OfficeError(f"part {e.filename} expands {e.file_size // e.compress_size}x (possible zip bomb)")
                if e.filename.startswith("/") or ".." in Path(e.filename).parts:
                    raise OfficeError(f"unsafe part name {e.filename}")
            if total > MAX_UNZIPPED:
                raise OfficeError("package expands to more than 400 MB (possible zip bomb)")
            for e in entries:
                name = e.filename.lower()
                if "vbaproject" in name or name.endswith(".bin") and "macro" in name or name.startswith("basic/"):
                    info["macros"] = True
                if name.endswith((".xml", ".rels")) and e.file_size <= MAX_XML_SCAN:
                    data = zf.read(e)
                    if _DTD.search(data[:4096]) or b"<!ENTITY" in data:
                        raise OfficeError(f"{e.filename} declares a DTD/ENTITY - refused (XXE protection)")
                    if name.endswith(".rels") and b'TargetMode="External"' in data:
                        for m in re.finditer(rb'Target="([^"]+)"[^>]*TargetMode="External"|TargetMode="External"[^>]*Target="([^"]+)"', data):
                            t = (m.group(1) or m.group(2) or b"").decode("utf-8", "replace")
                            if t and t not in info["external_links"]:
                                info["external_links"].append(t[:300])
    elif ext in LEGACY:
        head = p.read_bytes()[: 8 * 1024 * 1024]
        info["macros"] = b"_VBA_PROJECT" in head or b"VBA\x00" in head or b"Macros" in head
    info["external_links"] = info["external_links"][:50]
    return info


def resolve_in(path: str) -> Path:
    p = sandbox.resolve(path, allow_outside=True)
    if not p.exists():
        raise OfficeError(f"no such file: {path}")
    return p


def resolve_out(path: str, exts: set[str] | None = None) -> Path:
    p = sandbox.resolve(path, allow_outside=True)
    if exts and p.suffix.lower() not in exts:
        raise OfficeError(f"{p.name}: expected one of {', '.join(sorted(exts))}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# -- LibreOffice headless (macros off, links off) -----------------------------------------
_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Filter/Import/VBA"><prop oor:name="Load" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Filter/Import/VBA"><prop oor:name="Executable" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Filter/Import/VBA"><prop oor:name="Load" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Filter/Import/VBA"><prop oor:name="Executable" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Impress/Filter/Import/VBA"><prop oor:name="Load" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Impress/Filter/Import/VBA"><prop oor:name="Executable" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Setup/Office"><prop oor:name="ooSetupInstCompleted" oor:op="fuse"><value>true</value></prop></item>
</oor:items>
"""

PDF_OPTS = {"UseTaggedPDF": True, "ExportBookmarks": True, "ExportNotes": False, "EmbedStandardFonts": True,
            "ExportFormFields": False, "Quality": 90, "MaxImageResolution": 300, "ReduceImageResolution": True}


def soffice() -> str | None:
    from automoto import apps

    return apps.detect().get("libreoffice")


def lo_available() -> bool:
    return bool(soffice())


def _family(ext: str) -> str:
    ext = ext.lower()
    return "calc" if ext in CALC else "impress" if ext in IMPRESS else "writer"


def _filter_arg(fmt: str, src_ext: str, pdf_opts: dict[str, Any] | None) -> str:
    if fmt != "pdf":
        return fmt
    opts = {**PDF_OPTS, **(pdf_opts or {})}
    js = {k: {"type": "boolean" if isinstance(v, bool) else "long", "value": str(v).lower() if isinstance(v, bool) else str(v)}
          for k, v in opts.items()}
    return f"pdf:{_family(src_ext)}_pdf_Export:{json.dumps(js, separators=(',', ':'))}"


def lo_convert(src: Path, fmt: str, outdir: Path, *, timeout: int = 240, pdf_opts: dict[str, Any] | None = None) -> Path:
    """Convert ``src`` with LibreOffice headless into ``outdir``. ``fmt`` is an extension (pdf, docx, xlsx…)."""
    exe = soffice()
    if not exe:
        raise OfficeError("LibreOffice is not installed - get it free from https://www.libreoffice.org "
                          "(it is used for PDF export, legacy formats and formula recalculation)")
    inspect_file(src)
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="automoto-lo-") as tmp:
        prof = Path(tmp) / "profile"
        (prof / "user").mkdir(parents=True)
        (prof / "user" / "registrymodifications.xcu").write_text(_XCU, encoding="utf-8")
        # copy the input so LibreOffice never writes lock files next to the user's file
        work = Path(tmp) / ("in" + src.suffix.lower())
        shutil.copyfile(src, work)
        tmp_out = Path(tmp) / "out"
        argv = [exe, f"-env:UserInstallation={prof.as_uri()}", "--headless", "--invisible", "--norestore",
                "--nologo", "--nolockcheck", "--nodefault", "--convert-to", _filter_arg(fmt, src.suffix, pdf_opts),
                "--outdir", str(tmp_out), str(work)]
        kw: dict[str, Any] = {"start_new_session": True} if sys.platform != "win32" else {}
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=sandbox.clean_env(),
                               stdin=subprocess.DEVNULL, **kw)
        except subprocess.TimeoutExpired:
            raise OfficeError(f"LibreOffice timed out after {timeout}s converting {src.name}") from None
        ext = fmt.split(":", 1)[0]
        produced = tmp_out / f"in.{ext}"
        if not produced.exists():
            cands = list(tmp_out.glob("in.*")) if tmp_out.exists() else []
            if not cands:
                raise OfficeError(f"LibreOffice could not convert {src.name} to {ext}: {(r.stderr or r.stdout)[-400:]}")
            produced = cands[0]
        dest = outdir / f"{src.stem}.{produced.suffix.lstrip('.')}"
        if dest.resolve() == src.resolve():
            dest = outdir / f"{src.stem}.converted.{produced.suffix.lstrip('.')}"
        shutil.move(str(produced), dest)
        return dest


# -- reading ------------------------------------------------------------------------------------
def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f"\n[…{len(text) - n} more characters - read with a smaller scope]"


def read(path: str, max_chars: int = 20000, sheet: str | None = None, max_rows: int = 60) -> str:
    p = resolve_in(path)
    ext = p.suffix.lower()
    if ext in (".txt", ".md", ".csv", ".tsv"):
        if p.stat().st_size > MAX_FILE:
            raise OfficeError("file too large")
        return _clip(p.read_text(encoding="utf-8", errors="replace"), max_chars)
    if ext == ".pdf":
        return _clip(_read_pdf(p), max_chars)
    info = inspect_file(p)
    notes = []
    if info["macros"]:
        notes.append("⚠ this file contains macros - they were NOT run and are ignored")
    if info["external_links"]:
        notes.append("external links (not followed): " + ", ".join(info["external_links"][:10]))
    if ext in LEGACY | ODF | {".docm", ".xlsm", ".pptm", ".dotx", ".xltx", ".potx"}:
        target = {"writer": "docx", "calc": "xlsx", "impress": "pptx"}[_family(ext)]
        with tempfile.TemporaryDirectory(prefix="automoto-read-") as tmp:
            conv = lo_convert(p, target, Path(tmp))
            body = _read_modern(conv, max_rows=max_rows, sheet=sheet)
        notes.append(f"(converted from {ext} with LibreOffice for reading)")
    else:
        body = _read_modern(p, max_rows=max_rows, sheet=sheet)
    return _clip("\n".join(notes + [body]) if notes else body, max_chars)


def _read_modern(p: Path, *, max_rows: int, sheet: str | None) -> str:
    ext = p.suffix.lower()
    if ext in (".docx", ".docm", ".dotx"):
        return read_docx(p)
    if ext in (".xlsx", ".xlsm", ".xltx"):
        return read_xlsx(p, max_rows=max_rows, sheet=sheet)
    if ext in (".pptx", ".pptm", ".potx"):
        return read_pptx(p)
    raise OfficeError(f"can't read {ext} files")


def _read_pdf(p: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        if shutil.which("pdftotext"):
            r = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, timeout=120)
            return r.stdout
        raise OfficeError("install pypdf (pip install pypdf) to read PDFs") from None
    reader = PdfReader(str(p))
    out = [f"PDF: {len(reader.pages)} page(s)"]
    for i, page in enumerate(reader.pages[:200], 1):
        out.append(f"\n--- page {i} ---\n{(page.extract_text() or '').strip()}")
    return "\n".join(out)


def read_docx(p: Path) -> str:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(p))
    out: list[str] = []
    cp = d.core_properties
    if cp.title or cp.author:
        out.append(f"[title: {cp.title or '-'} · author: {cp.author or '-'}]")
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(el, d)
            t = para.text.strip()
            sty = (para.style.name if para.style is not None else "") or ""
            if el.xpath(".//w:drawing"):
                out.append("[image]")
            if not t:
                continue
            m = re.match(r"Heading (\d)", sty)
            if m:
                out.append("#" * int(m.group(1)) + " " + t)
            elif sty == "Title":
                out.append("# " + t)
            elif sty.startswith("List Number"):
                out.append("1. " + t)
            elif sty.startswith("List"):
                out.append("- " + t)
            else:
                out.append(t)
        elif tag == "tbl":
            tbl = Table(el, d)
            for i, row in enumerate(tbl.rows):
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                out.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    out.append("|" + "---|" * len(cells))
            out.append("")
    sec = d.sections[0]
    hdr = " ".join(x.text for x in sec.header.paragraphs if x.text.strip())
    if hdr:
        out.insert(0, f"[header: {hdr}]")
    try:
        comments = list(d.comments)
    except Exception:
        comments = []
    for c in comments[:50]:
        out.append(f"[comment by {c.author}: {c.text}]")
    return "\n".join(out)


def read_xlsx(p: Path, *, max_rows: int = 60, sheet: str | None = None) -> str:
    import openpyxl

    wb_f = openpyxl.load_workbook(str(p), data_only=False, keep_links=False, keep_vba=False)
    wb_v = openpyxl.load_workbook(str(p), data_only=True, keep_links=False, keep_vba=False)
    out = [f"Workbook: sheets {', '.join(wb_f.sheetnames)}"]
    names = [sheet] if sheet else wb_f.sheetnames
    for name in names:
        if name not in wb_f.sheetnames:
            raise OfficeError(f"no sheet '{name}'")
        ws, wv = wb_f[name], wb_v[name]
        out.append(f"\n## {name} ({ws.max_row} rows × {ws.max_column} cols, used {ws.dimensions})")
        for r_i, (rf, rv) in enumerate(zip(ws.iter_rows(max_row=min(ws.max_row, max_rows)),
                                          wv.iter_rows(max_row=min(ws.max_row, max_rows))), 1):
            cells = []
            for cf, cv in zip(rf, rv):
                if cf.value is None:
                    cells.append("")
                elif isinstance(cf.value, str) and cf.value.startswith("="):
                    cells.append(f"{cf.value} → {cv.value if cv.value is not None else '?'}")
                else:
                    cells.append(str(cf.value))
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                out.append(f"{r_i}: " + " | ".join(cells))
        if ws.max_row > max_rows:
            out.append(f"[… {ws.max_row - max_rows} more rows]")
        charts = len(getattr(ws, "_charts", []))
        if charts:
            out.append(f"[{charts} chart(s)]")
    try:
        import pandas as pd  # optional: quick column summary

        df = pd.read_excel(str(p), sheet_name=names[0], nrows=5000)
        out.append(f"\n[pandas: {names[0]} has {len(df)} data rows; columns: {', '.join(map(str, df.columns[:30]))}]")
    except Exception:
        pass
    return "\n".join(out)


def read_pptx(p: Path) -> str:
    import pptx

    prs = pptx.Presentation(str(p))
    out = [f"Presentation: {len(prs.slides)} slide(s), {prs.slide_width.inches:.2f}×{prs.slide_height.inches:.2f} in"]
    for i, s in enumerate(prs.slides, 1):
        title = s.shapes.title.text_frame.text.strip() if s.shapes.title is not None and s.shapes.title.has_text_frame else ""
        out.append(f"\n## Slide {i}: {title or '(no title)'}")
        for sh in s.shapes:
            if sh == s.shapes.title:
                continue
            if sh.has_text_frame and sh.text_frame.text.strip():
                for para in sh.text_frame.paragraphs:
                    if para.text.strip():
                        out.append("  " * para.level + "- " + para.text.strip())
            elif sh.shape_type == 13:
                out.append("[picture]")
            elif getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    out.append("| " + " | ".join(c.text for c in row.cells) + " |")
            elif getattr(sh, "has_chart", False) and sh.has_chart:
                out.append(f"[chart: {sh.chart.chart_type}]")
        if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
            out.append("Notes: " + s.notes_slide.notes_text_frame.text.strip())
    return "\n".join(out)


# -- convert / export / recalc / render ---------------------------------------------------------
CONVERT_TO = {"pdf", "docx", "xlsx", "pptx", "odt", "ods", "odp", "html", "txt", "csv", "md", "rtf"}


def default_output(src: Path, to: str, out: str | None) -> Path:
    if out:
        return sandbox.resolve(out, allow_outside=True)
    return src.with_suffix("." + to)


def convert(path: str, to: str, out: str | None = None, pdf_opts: dict[str, Any] | None = None) -> str:
    to = to.lower().lstrip(".")
    if to not in CONVERT_TO:
        raise OfficeError(f"can't convert to {to}. Options: {', '.join(sorted(CONVERT_TO))}")
    src = resolve_in(path)
    dest = default_output(src, to, out)
    if dest.suffix.lower() != "." + to:
        raise OfficeError(f"output must end with .{to}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if to == "md":
        if shutil.which("pandoc") and ext == ".docx":
            subprocess.run(["pandoc", str(src), "-t", "gfm", "-o", str(dest)], check=True, timeout=120,
                           env=sandbox.clean_env())
        else:
            dest.write_text(read(str(src), max_chars=2_000_000), encoding="utf-8")
        return f"wrote {sandbox.rel(dest)}"
    if ext == ".md" and to == "docx":
        if shutil.which("pandoc"):
            subprocess.run(["pandoc", str(src), "-o", str(dest)], check=True, timeout=120, env=sandbox.clean_env())
        else:
            from automoto import office_build

            office_build.build_docx(office_build.markdown_to_spec(src.read_text(encoding="utf-8")), dest)
        return f"wrote {sandbox.rel(dest)}"
    if ext == ".md":
        with tempfile.TemporaryDirectory(prefix="automoto-md-") as tmp:
            from automoto import office_build

            mid = Path(tmp) / (src.stem + ".docx")
            office_build.build_docx(office_build.markdown_to_spec(src.read_text(encoding="utf-8")), mid)
            res = lo_convert(mid, to, Path(tmp) / "o", pdf_opts=pdf_opts)
            shutil.move(str(res), dest)
        return f"wrote {sandbox.rel(dest)}" + (_pdf_summary(dest) if to == "pdf" else "")
    with tempfile.TemporaryDirectory(prefix="automoto-conv-") as tmp:
        res = lo_convert(src, to, Path(tmp), pdf_opts=pdf_opts)
        shutil.move(str(res), dest)
    return f"wrote {sandbox.rel(dest)}" + (_pdf_summary(dest) if to == "pdf" else "")


def _pdf_summary(pdf: Path) -> str:
    info = pdf_info(pdf)
    return f" ({info.get('Pages', '?')} page(s), tagged: {info.get('Tagged', '?')})"


def pdf_info(pdf: Path) -> dict[str, str]:
    if not shutil.which("pdfinfo"):
        return {}
    r = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=60)
    return {k.strip(): v.strip() for k, v in (ln.split(":", 1) for ln in r.stdout.splitlines() if ":" in ln)}


def pdf_fonts(pdf: Path) -> list[dict[str, str]]:
    if not shutil.which("pdffonts"):
        return []
    r = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True, timeout=60)
    rows = []
    for ln in r.stdout.splitlines()[2:]:
        parts = ln.split()
        if len(parts) >= 7:
            # name type... encoding emb sub uni object ID
            rows.append({"name": parts[0], "emb": parts[-5], "sub": parts[-4]})
    return rows


ERROR_LITERALS = {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NULL!", "#NUM!"}


def recalc(path: str, save: bool = False) -> str:
    """Recalculate every formula with LibreOffice and report values and errors."""
    import openpyxl

    src = resolve_in(path)
    if src.suffix.lower() not in (".xlsx", ".xlsm", ".ods", ".xls"):
        raise OfficeError("recalc works on spreadsheets (.xlsx, .xls, .ods)")
    with tempfile.TemporaryDirectory(prefix="automoto-recalc-") as tmp:
        res = lo_convert(src, "xlsx", Path(tmp))
        import warnings

        with warnings.catch_warnings():  # LibreOffice writes extensions openpyxl doesn't model; values are fine
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(str(res), data_only=True, keep_links=False)
        formulas = openpyxl.load_workbook(str(src), data_only=False, keep_links=False) if src.suffix.lower() == ".xlsx" else None
        errors: list[str] = []
        sample: list[str] = []
        n = 0
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    f = None
                    if formulas is not None and ws.title in formulas.sheetnames:
                        f = formulas[ws.title][c.coordinate].value
                    if isinstance(f, str) and f.startswith("="):
                        n += 1
                        if len(sample) < 40:
                            sample.append(f"{ws.title}!{c.coordinate} {f} = {c.value}")
                    if isinstance(c.value, str) and c.value in ERROR_LITERALS:
                        errors.append(f"{ws.title}!{c.coordinate} {c.value}" + (f" ({f})" if f else ""))
        saved = ""
        if save:
            dest = src.with_name(src.stem + ".recalc.xlsx")
            shutil.copyfile(res, dest)
            saved = f"\nsaved recalculated copy (cached values filled in): {sandbox.rel(dest)}"
    head = f"recalculated {n} formula(s) with LibreOffice; {len(errors)} error(s)"
    body = "\n".join(sample)
    errs = ("\nERRORS - fix these formulas:\n" + "\n".join(errors[:60])) if errors else ""
    return f"{head}{errs}\n{body}{saved}"


def render(path: str, first: int = 1, last: int = 3, dpi: int = 80, out_dir: str | None = None) -> list[Path]:
    """Render pages to PNG (converting to PDF first if needed). Returns the PNG paths."""
    if not shutil.which("pdftoppm"):
        raise OfficeError("pdftoppm (poppler-utils) is not installed - needed to render pages")
    src = resolve_in(path)
    first, last = max(1, int(first)), max(1, int(last))
    if last - first > 40:
        raise OfficeError("render at most 40 pages at a time")
    dpi = max(30, min(int(dpi), 200))
    outd = sandbox.resolve(out_dir, allow_outside=True) if out_dir else sandbox.root() / "scratch" / "renders" / src.stem
    outd.mkdir(parents=True, exist_ok=True)
    for old in outd.glob("page-*.png"):
        old.unlink()
    with tempfile.TemporaryDirectory(prefix="automoto-render-") as tmp:
        pdf = src if src.suffix.lower() == ".pdf" else lo_convert(src, "pdf", Path(tmp))
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(first), "-l", str(last), str(pdf),
                        str(outd / "page")], capture_output=True, timeout=180, check=False)
    pages = sorted(outd.glob("page-*.png"))
    if not pages:
        raise OfficeError("no pages rendered")
    return pages
