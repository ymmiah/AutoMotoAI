"""Real sample files for the scenarios (made with the same libraries users' files come from)."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from automoto import tools as tools_mod
from automoto.memory import Memory


def _pdf(path: Path, pages: list[list[str]]) -> None:
    """A small, valid, text-based PDF (no extra dependency)."""
    objs: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    font_id = 3
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for lines in pages:
        ops = ["BT", "/F1 14 Tf", "72 760 Td", "18 TL"]
        for ln in lines:
            ops.append("(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_id = len(objs)
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 %d 0 R >> >> "
                    b"/Contents %d 0 R >>" % (font_id, content_id))
        kids.append(len(objs))
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))


PLUGIN_MAIN = """<?php
/**
 * Plugin Name: Hello Banner
 * Description: Shows a friendly banner.
 * Version: 1.0.0
 * Author: Demo
 * License: GPL-2.0-or-later
 * Text Domain: hello-banner
 */

function hello_banner_render() {
    echo '<div class="hello-banner">' . esc_html__( 'Hello!', 'hello-banner' ) . '</div>';
}
add_action( 'wp_footer', 'hello_banner_render' );
"""
PLUGIN_README = """=== Hello Banner ===
Contributors: demo
Requires at least: 6.0
Tested up to: 6.6
Stable tag: 1.0.0
License: GPLv2 or later

Shows a friendly banner.

== Changelog ==
= 1.0.0 =
* First release.
"""
BUGGY = '''def average(values):
    """Mean of a list of numbers."""
    return sum(values) / (len(values) - 1)


def safe_div(a, b):
    return a / b
'''
BUGGY_TEST = '''from calc import average


def test_average():
    assert average([2, 4, 6]) == 4
'''


def make(root: Path) -> dict[str, str]:
    """Create every sample under ``root/uploads``; returns name -> workspace path."""
    up = root / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    t = tools_mod.build()
    ctx = tools_mod.ToolContext(memory=Memory(), skills={})

    def tool(name: str, **args) -> None:
        ok, out = tools_mod.call(t[name], ctx, args)
        if not ok:
            raise RuntimeError(f"fixture {name}: {out}")

    tool("office_create_pptx", path="uploads/deck.pptx", spec={"slides": [
        {"layout": "title", "title": "Project Phoenix", "subtitle": "Quarterly update"},
        {"layout": "bullets", "title": "Timeline", "bullets": ["Design done in May", "Beta in July", "Launch in October"],
         "notes": "Stress the October launch."},
        {"layout": "bullets", "title": "Risks", "bullets": ["Supplier delays", "Hiring two engineers"]}]})
    tool("office_create_docx", path="uploads/report.docx", spec={"properties": {"title": "Sales Report"}, "blocks": [
        {"type": "heading", "level": 1, "text": "Introduction"},
        {"type": "paragraph", "text": "This report covers the third quarter. Sales grew 12% in Q3."},
        {"type": "heading", "level": 1, "text": "Findings"},
        {"type": "table", "caption": "Sales by region", "rows": [["Region", "Sales"], ["North", "120"], ["South", "95"]]},
        {"type": "paragraph", "text": "The North region performed best."}]})
    tool("office_create_xlsx", path="uploads/budget.xlsx", spec={"sheets": [{"name": "Budget", "rows": [
        ["Item", "Cost"], ["Rent", 800], ["Food", 250], ["Travel", 120], ["Total", "=SUM(B2:B4)"]], "header": True}]})
    (up / "sales.csv").write_text(
        "Region,Product,Units,Price,Date\n"
        "North,Widget,10,2.5,2026-01-05\nSouth,Widget,4,2.5,2026-01-09\nNorth,Gadget,3,10,2026-02-01\n"
        "East,Widget,7,2.5,2026-02-11\nSouth,Gadget,6,10,2026-02-20\nNorth,Widget,12,2.5,2026-03-03\n"
        "East,Gadget,2,10,2026-03-15\nSouth,Widget,9,2.5,2026-03-28\nNorth,Widget,10,2.5,2026-01-05\n", encoding="utf-8")
    (up / "people.json").write_text(json.dumps({"users": [{"name": "Ann", "age": 31, "city": "Leeds"},
                                                          {"name": "Bilal", "age": 27, "city": "Birmingham"},
                                                          {"name": "Chen", "age": 35, "city": "London"}]}, indent=2),
                                    encoding="utf-8")
    (up / "config.yaml").write_text("app:\n  name: shop\n  debug: true\n  port: 8080\n", encoding="utf-8")
    _pdf(up / "paper.pdf", [["Climate and Cities", "Urban trees cut summer heat by up to 5 degrees."],
                            ["Conclusion", "Cities should plant more trees near schools."]])
    from PIL import Image

    Image.new("RGB", (1600, 900), (40, 90, 160)).save(up / "photo.png")
    with zipfile.ZipFile(up / "project.zip", "w") as z:
        z.writestr("project/README.md", "# Demo project\n\nRun `python src/app.py`.\n")
        z.writestr("project/src/app.py", "print('hello from the demo app')\n")
    with zipfile.ZipFile(up / "hello-banner.zip", "w") as z:
        z.writestr("hello-banner/hello-banner.php", PLUGIN_MAIN)
        z.writestr("hello-banner/readme.txt", PLUGIN_README)
        z.writestr("hello-banner/includes/helper.php", "<?php\nfunction hello_banner_helper() { return 1; }\n")
    code = root / "uploads" / "calc"
    code.mkdir(exist_ok=True)
    (code / "calc.py").write_text(BUGGY, encoding="utf-8")
    (code / "test_calc.py").write_text(BUGGY_TEST, encoding="utf-8")
    lines = []
    for i in range(1, 501):
        lvl = "ERROR" if i % 97 == 0 else "INFO"
        msg = "database timeout after 30s" if lvl == "ERROR" else f"request {i} served in {i % 40} ms"
        lines.append(f"2026-10-28 10:{i // 60:02d}:{i % 60:02d} {lvl} {msg}")
    (up / "app.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    db = sqlite3.connect(up / "shop.sqlite")
    db.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT, total REAL)")
    db.executemany("INSERT INTO orders (customer, total) VALUES (?, ?)", [("Ann", 20.5), ("Bilal", 99.0), ("Ann", 5.0)])
    db.commit()
    db.close()
    (up / "notes.md").write_text("# Meeting notes\n\n- Ship the beta on Friday\n- Yasin owns the release\n", encoding="utf-8")
    (up / "feed.xml").write_text("<feed><item><title>One</title></item><item><title>Two</title></item></feed>",
                                 encoding="utf-8")
    return {p.name: f"uploads/{p.relative_to(up).as_posix()}" for p in up.rglob("*") if p.is_file()}
