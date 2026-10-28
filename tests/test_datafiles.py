"""v5.4 data files: CSV/TSV sniffing and queries, JSON/YAML/TOML/XML, SQLite read-only, logs, images, PDF text."""

import json
import sqlite3
import zipfile

import pytest

pytest.importorskip("pandas")

from automoto import datafiles as dfm  # noqa: E402
from automoto import policy, sandbox, tools  # noqa: E402

CSV = "Region;Product;Units;Price\nNorth;Widget;10;2.5\nSouth;Widget;4;2.5\nNorth;Gadget;3;10\nEast;Gadget;;10\nSouth;Gizmo;7;1.25\n"


@pytest.fixture
def ws():
    root = sandbox.root()
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def t():
    return tools.build(), tools.ToolContext()


def call(t, name, **kw):
    ok, out = tools.call(t[0][name], t[1], kw)
    assert ok, out
    return out


def test_sniff_encoding_and_delimiter(ws):
    (ws / "s.csv").write_text(CSV, encoding="utf-8")
    d = dfm.sniff_csv(ws / "s.csv")
    assert d["delimiter"] == ";" and d["header"] and d["encoding"] == "utf-8"
    (ws / "w.csv").write_bytes("Name,City\nJosé,Málaga\nZoë,Köln\n".encode("cp1252"))
    assert dfm.detect_encoding(ws / "w.csv") in ("cp1252", "windows-1252", "latin-1", "iso-8859-1", "cp1250")
    df, info = dfm.load_table("w.csv")
    assert df["Name"].tolist() == ["José", "Zoë"]
    (ws / "b.csv").write_bytes(b"\xef\xbb\xbfa,b\n1,2\n")
    df, _ = dfm.load_table("b.csv")
    assert list(df.columns) == ["a", "b"]
    (ws / "t.tsv").write_text("x\ty\n1\t2\n")
    assert dfm.sniff_csv(ws / "t.tsv")["delimiter"] == "\t"


def test_query_filter_group_sort(ws, t):
    (ws / "s.csv").write_text(CSV)
    df, _ = dfm.load_table("s.csv")
    r = dfm.query(df, filters=[{"column": "region", "op": "==", "value": "North"}])
    assert len(r) == 2
    r = dfm.query(df, filters=[{"column": "Units", "op": ">=", "value": "5"}], sort=["-Units"])
    assert r["Units"].tolist() == [10, 7]
    r = dfm.query(df, group_by=["Product"], aggregate={"Units": ["sum", "count"]}, sort=["Product"])
    assert r.to_dict("records")[0] == {"Product": "Gadget", "Units_sum": 3.0, "Units_count": 1}
    r = dfm.query(df, filters=[{"column": "Units", "op": "isnull"}])
    assert r["Region"].tolist() == ["East"]
    r = dfm.query(df, filters=[{"column": "Product", "op": "in", "value": "Gizmo,Gadget"}], columns=["Region"], dedupe=True)
    assert sorted(r["Region"]) == ["East", "North", "South"]
    with pytest.raises(dfm.DataError, match="no column"):
        dfm.query(df, filters=[{"column": "Nope", "op": "==", "value": 1}])
    with pytest.raises(dfm.DataError, match="unknown op"):
        dfm.query(df, filters=[{"column": "Units", "op": "__import__", "value": 1}])
    out = call(t, "data_query", path="s.csv", group_by=["Region"], aggregate={"Units": "sum"}, sort=["-Units_sum"],
               out="scratch/by_region.xlsx")
    assert "| North | 13.0 |" in out and "wrote scratch/by_region.xlsx" in out
    from openpyxl import load_workbook

    ws_ = load_workbook(ws / "scratch" / "by_region.xlsx").active
    assert ws_["A1"].value == "Region" and ws_["B2"].value == 13


def test_csv_injection_kept_as_text_in_xlsx(ws):
    (ws / "inj.csv").write_text('name,note\nbob,"=HYPERLINK(""http://evil"",""x"")"\nann,+cmd\n')
    df, _ = dfm.load_table("inj.csv")
    dfm.write_table(df, "inj.xlsx")
    with zipfile.ZipFile(ws / "inj.xlsx") as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet  # no formulas


def test_convert_tables_and_structured(ws, t):
    (ws / "s.csv").write_text(CSV)
    call(t, "data_convert", path="s.csv", out="scratch/s.json")
    rows = json.loads((ws / "scratch" / "s.json").read_text())
    assert rows[0]["Region"] == "North" and len(rows) == 5
    call(t, "data_convert", path="scratch/s.json", out="scratch/s.jsonl")
    assert len((ws / "scratch" / "s.jsonl").read_text().splitlines()) == 5
    call(t, "data_convert", path="scratch/s.jsonl", out="scratch/back.tsv")
    assert (ws / "scratch" / "back.tsv").read_text().startswith("Region\tProduct")
    (ws / "c.yaml").write_text("name: demo\nitems:\n  - id: 1\n    tags: [a, b]\n  - id: 2\n")
    call(t, "data_convert", path="c.yaml", out="scratch/c.toml")
    assert "name = \"demo\"" in (ws / "scratch" / "c.toml").read_text()
    call(t, "data_convert", path="c.yaml", out="scratch/items.csv", select="items")
    assert (ws / "scratch" / "items.csv").read_text().splitlines()[0].startswith("id")
    out = call(t, "data_read", path="c.yaml", select="items.*.id")
    assert json.loads(out) == [1, 2]


def test_yaml_safe_load_and_xml_defused(ws, t):
    (ws / "evil.yaml").write_text("!!python/object/apply:os.system ['echo pwned']\n")
    ok, out = tools.call(t[0]["data_read"], t[1], {"path": "evil.yaml"})
    assert not ok and "invalid YAML" in out
    (ws / "bomb.xml").write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><x>&b;</x>')
    ok, out = tools.call(t[0]["data_read"], t[1], {"path": "bomb.xml"})
    assert not ok and "unsafe XML" in out
    (ws / "xxe.xml").write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')
    ok, out = tools.call(t[0]["data_read"], t[1], {"path": "xxe.xml"})
    assert not ok and "root:" not in out
    (ws / "ok.xml").write_text('<feed xmlns="http://www.w3.org/2005/Atom"><entry id="1"><title>A</title></entry>'
                               '<entry id="2"><title>B</title></entry></feed>')
    data = json.loads(call(t, "data_read", path="ok.xml"))
    assert [e["title"] for e in data["feed"]["entry"]] == ["A", "B"] and data["feed"]["entry"][0]["@id"] == "1"
    (ws / "p.toml").write_text('[tool.x]\nname = "y"\n')
    assert "tool" in call(t, "data_inspect", path="p.toml")


def test_sqlite_read_only(ws, t):
    db = ws / "shop.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE orders (id INTEGER, item TEXT, qty INTEGER)")
    con.executemany("INSERT INTO orders VALUES (?,?,?)", [(1, "pen", 3), (2, "ink", 1), (3, "pen", 2)])
    con.commit()
    con.close()
    assert "orders (3 rows)" in call(t, "sqlite_query", path="shop.sqlite")
    out = call(t, "sqlite_query", path="shop.sqlite", sql="SELECT item, SUM(qty) AS n FROM orders GROUP BY item ORDER BY n DESC",
               out="scratch/top.csv")
    assert "| pen | 5 |" in out and (ws / "scratch" / "top.csv").exists()
    for bad in ("DELETE FROM orders", "UPDATE orders SET qty=0", "DROP TABLE orders", "ATTACH DATABASE 'x.db' AS x",
                "SELECT 1; DROP TABLE orders", "PRAGMA writable_schema=1", "SELECT load_extension('x')",
                "WITH x AS (SELECT 1) DELETE FROM orders"):
        ok, msg = tools.call(t[0]["sqlite_query"], t[1], {"path": "shop.sqlite", "sql": bad})
        assert not ok, bad
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
    con.close()
    assert "orders" in call(t, "data_inspect", path="shop.sqlite")
    df, info = dfm.load_table("shop.sqlite", table="orders")
    assert len(df) == 3


def test_text_tail_grep_and_log_summary(ws, t):
    lines = [f"2026-10-28 10:{i // 60:02d}:{i % 60:02d} {'ERROR' if i % 10 == 0 else 'INFO'} request {i}" for i in range(500)]
    (ws / "app.log").write_text("\n".join(lines) + "\n")
    out = call(t, "text_search", path="app.log", pattern="error", context=1, max_matches=3)
    assert out.startswith("50 matching line(s) of 500") and "1: 2026" in out
    assert call(t, "text_tail", path="app.log", lines=2).splitlines() == lines[-2:]
    s = dfm.log_summary("app.log")
    assert s["levels"] == {"ERROR": 50, "INFO": 450} and s["first_timestamp"].startswith("2026-10-28 10:00")
    out = call(t, "text_search", path="app.log", pattern=r"request \d*5$", regex=True, max_matches=1)
    assert out.startswith("50 matching")
    assert "levels" in call(t, "data_inspect", path="app.log")


def test_image_info_and_bomb(ws, t):
    from PIL import Image

    im = Image.new("RGB", (64, 32))
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    exif.get_ifd(0x8825)[1] = "N"
    im.save(ws / "p.jpg", exif=exif.tobytes())
    info = json.loads(call(t, "image_info", path="p.jpg"))
    assert info["size"] == [64, 32] and info["exif"]["Make"] == "TestCam"
    assert "GPS" in info["exif"]


def test_pdf_text_and_markdown(ws, t):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(200, 200)
    with open(ws / "blank.pdf", "wb") as fh:
        w.write(fh)
    out = call(t, "pdf_text", path="blank.pdf")
    assert out.startswith("1 page(s)") and "scanned" in out
    (ws / "n.md").write_text("# Title\n\n## Part A\ntext\n```\n# not a heading\n```\n### Deep\n")
    out = call(t, "data_inspect", path="n.md")
    assert "Title" in out and "  Part A" in out and "not a heading" not in out


def test_limits_and_policy(ws, monkeypatch, t):
    (ws / "s.csv").write_text(CSV)
    monkeypatch.setenv("AUTOMOTO_DATA_MAX_ROWS", "2")
    df, info = dfm.load_table("s.csv")
    assert len(df) == 2 and info["truncated_at_rows"] == 2
    monkeypatch.setenv("AUTOMOTO_DATA_MAX_BYTES", "10")
    with pytest.raises(dfm.DataError, match="larger than"):
        dfm.load_table("s.csv")
    assert policy.classify("data_query", "safe", {"path": "s.csv"})[0] == "safe"
    assert policy.classify("data_query", "safe", {"path": "s.csv", "out": "r.xlsx"})[0] == "risky"
    assert policy.classify("data_query", "safe", {"path": "s.csv", "out": "scratch/r.xlsx"})[0] == "safe"
    assert policy.classify("data_inspect", "safe", {"path": "~/.ssh/id_rsa"})[0] == "blocked"
    assert policy.classify("data_convert", "risky", {"path": "s.csv", "out": "~/.bashrc"})[0] == "blocked"
