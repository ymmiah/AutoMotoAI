"""v5.4 archives: list/inspect/extract/create/repack and the malicious-archive defences."""

import gzip
import io
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

from automoto import archives, sandbox
from automoto.archives import ArchiveError


@pytest.fixture
def ws():
    root = sandbox.root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def make_zip(path: Path, files: dict, *, flag_utf8=True) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zi = zipfile.ZipInfo(name)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, data)
    return path


def make_tree(base: Path) -> Path:
    src = base / "my-plugin"
    (src / "inc").mkdir(parents=True)
    (src / "my-plugin.php").write_text("<?php\n/* Plugin Name: My */\n")
    (src / "inc" / "a.php").write_text("<?php // a\n")
    (src / ".git").mkdir()
    (src / ".git" / "HEAD").write_text("ref")
    (src / "node_modules" / "x").mkdir(parents=True)
    (src / "node_modules" / "x" / "i.js").write_text("1")
    (src / ".DS_Store").write_bytes(b"\0")
    (src / ".env").write_text("SECRET=1")
    return src


def test_safe_name_rules():
    assert archives.safe_name("a/b.txt") == ("a/b.txt", "")
    assert archives.safe_name("./a//b")[0] == "a/b"
    assert "traversal" in archives.safe_name("../evil")[1]
    assert "traversal" in archives.safe_name("a/../../evil")[1]
    assert "absolute" in archives.safe_name("/etc/passwd")[1]
    assert "absolute" in archives.safe_name("C:\\Windows\\x")[1]
    assert "traversal" in archives.safe_name("a\\..\\..\\x")[1]
    assert "NUL" in archives.safe_name("a\x00b")[1]
    assert "device" in archives.safe_name("dir/con.txt")[1]


def test_zip_roundtrip_and_tree(ws):
    z = make_zip(ws / "a.zip", {"top/readme.txt": "hi", "top/src/x.py": "print(1)\n"})
    rep = archives.inspect("a.zip")
    assert rep["safe"] and rep["format"] == "zip" and rep["files"] == 2 and rep["top_level"] == ["top"]
    assert "x.py" in archives.list_text("a.zip")
    r = archives.extract("a.zip", "out")
    assert r["files"] == 2 and (ws / "out" / "top" / "src" / "x.py").read_text() == "print(1)\n"
    r = archives.extract(str(z), "out2", strip_top=True)
    assert (ws / "out2" / "readme.txt").exists() and r["stripped_top_folder"] == "top"
    assert archives.read_member("a.zip", "top/readme.txt") == b"hi"
    with pytest.raises(ArchiveError, match="not empty"):
        archives.extract("a.zip", "out")
    archives.extract("a.zip", "out", overwrite=True)


def test_zip_slip_refused_and_nothing_written(ws):
    make_zip(ws / "evil.zip", {"ok.txt": "fine", "../../evil.txt": "pwned"})
    rep = archives.inspect("evil.zip")
    assert not rep["safe"] and "traversal" in " ".join(rep["problems"])
    with pytest.raises(ArchiveError, match="refusing"):
        archives.extract("evil.zip", "x")
    assert not (ws / "x").exists() and not (ws.parent / "evil.txt").exists()
    assert not list(ws.glob(".automoto-extract-*"))
    make_zip(ws / "abs.zip", {"/tmp/abs.txt": "x"})
    with pytest.raises(ArchiveError, match="absolute"):
        archives.extract("abs.zip", "y")


def test_tar_symlink_hardlink_and_device_refused(ws):
    t = ws / "links.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        data = b"hello"
        ti = tarfile.TarInfo("pkg/file.txt"); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
        sl = tarfile.TarInfo("pkg/link"); sl.type = tarfile.SYMTYPE; sl.linkname = "/etc/passwd"; tf.addfile(sl)
        hl = tarfile.TarInfo("pkg/hard"); hl.type = tarfile.LNKTYPE; hl.linkname = "/etc/shadow"; tf.addfile(hl)
    assert archives.inspect("links.tar.gz")["format"] == "tar"
    with pytest.raises(ArchiveError, match="link member"):
        archives.extract("links.tar.gz", "t")
    r = archives.extract("links.tar.gz", "t", skip_links=True)
    assert r["files"] == 1 and r["skipped_links"] == 2
    assert not (ws / "t" / "pkg" / "link").exists() and not (ws / "t" / "pkg" / "hard").exists()
    dev = ws / "dev.tar"
    with tarfile.open(dev, "w") as tf:
        d = tarfile.TarInfo("null"); d.type = tarfile.CHRTYPE; tf.addfile(d)
    with pytest.raises(ArchiveError, match="device"):
        archives.extract("dev.tar", "d")


def test_zip_symlink_member_refused(ws):
    z = ws / "sl.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zi = zipfile.ZipInfo("link"); zi.create_system = 3; zi.external_attr = (0o120777 << 16)
        zf.writestr(zi, "/etc/passwd")
        zf.writestr("real.txt", "x")
    with pytest.raises(ArchiveError, match="link"):
        archives.extract("sl.zip", "s")
    assert archives.extract("sl.zip", "s", skip_links=True)["files"] == 1


def test_zip_bomb_limits(ws, monkeypatch):
    z = ws / "bomb.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("zeros.bin", b"\0" * (40 * 1024 * 1024))  # ~40 KB compressed, ratio ~1000:1
    rep = archives.inspect("bomb.zip")
    assert not rep["safe"] and "ratio" in " ".join(rep["problems"])
    with pytest.raises(ArchiveError, match="ratio"):
        archives.extract("bomb.zip", "b")
    monkeypatch.setenv("AUTOMOTO_ARCHIVE_MAX_FILES", "3")
    make_zip(ws / "many.zip", {f"f{i}.txt": "x" for i in range(10)})
    assert "entries" in " ".join(archives.inspect("many.zip")["problems"])
    monkeypatch.delenv("AUTOMOTO_ARCHIVE_MAX_FILES")
    monkeypatch.setenv("AUTOMOTO_ARCHIVE_MAX_UNPACKED", "1000")
    make_zip(ws / "big.zip", {"a.txt": "y" * 5000})
    with pytest.raises(ArchiveError, match="unpacks to"):
        archives.extract("big.zip", "g")


def test_lying_header_stopped_while_streaming(ws, monkeypatch):
    # a gzip has no trustworthy size: the streaming budget must stop it
    data = gzip.compress(b"A" * 300_000)
    (ws / "big.gz").write_bytes(data[:-4] + (10).to_bytes(4, "little"))  # ISIZE trailer lies: "10 bytes"
    assert archives.inspect("big.gz")["safe"]
    monkeypatch.setenv("AUTOMOTO_ARCHIVE_MAX_UNPACKED", "100000")
    with pytest.raises(ArchiveError, match="size limit"):
        archives.extract("big.gz", "gz")
    assert not (ws / "gz").exists()


def test_nested_archives_depth_and_bomb(ws, monkeypatch):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("deep.txt", "deep")
    mid = io.BytesIO()
    with zipfile.ZipFile(mid, "w") as zf:
        zf.writestr("inner.zip", inner.getvalue())
    with zipfile.ZipFile(ws / "outer.zip", "w") as zf:
        zf.writestr("mid.zip", mid.getvalue())
    rep = archives.inspect("outer.zip")
    assert rep["safe"] and len(rep["nested"]) == 2
    r = archives.extract("outer.zip", "n", nested=True)
    assert (ws / "n" / "mid.zip.d" / "inner.zip.d" / "deep.txt").read_text() == "deep"
    monkeypatch.setenv("AUTOMOTO_ARCHIVE_MAX_DEPTH", "1")
    assert not archives.inspect("outer.zip")["safe"]
    with pytest.raises(ArchiveError, match="nested"):
        archives.extract("outer.zip", "n2", nested=True)
    assert r["nested"]


def test_encrypted_zip_needs_password(ws):
    # ZipCrypto archive made by 7-Zip/zip CLI when present, otherwise a hand-flagged member
    z = ws / "enc.zip"
    if shutil.which("zip"):
        (ws / "secret.txt").write_text("top secret")
        import subprocess
        subprocess.run(["zip", "-q", "-P", "pw123", str(z), "secret.txt"], cwd=ws, check=True)
        (ws / "secret.txt").unlink()
    elif shutil.which("7zz") or shutil.which("7z"):
        (ws / "secret.txt").write_text("top secret")
        import subprocess
        subprocess.run([shutil.which("7zz") or shutil.which("7z"), "a", "-tzip", "-ppw123", "-mem=ZipCrypto", str(z),
                        "secret.txt"], cwd=ws, check=True, capture_output=True)
        (ws / "secret.txt").unlink()
    else:
        pytest.skip("no zip/7z CLI to make an encrypted zip")
    assert archives.inspect("enc.zip")["encrypted"] == 1
    with pytest.raises(ArchiveError, match="password-protected"):
        archives.extract("enc.zip", "e")
    with pytest.raises(ArchiveError, match="password"):
        archives.extract("enc.zip", "e", password="wrong")
    # ZipCrypto lets ~1/256 wrong passwords past its check byte; those must still say "wrong password"
    for i in range(600):
        with pytest.raises(ArchiveError, match="wrong password"):
            archives.extract("enc.zip", f"e{i % 3}", password=f"nope-{i}")
    assert not (ws / "e").exists()
    archives.extract("enc.zip", "e", password="pw123")
    assert (ws / "e" / "secret.txt").read_text() == "top secret"


def test_cp437_name_redecoded_as_utf8(ws):
    z = ws / "names.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zi = zipfile.ZipInfo("café.txt")
        zi.create_system = 3  # same header bytes on every OS
        zf.writestr(zi, "x")
    raw = z.read_bytes()
    # clear the UTF-8 flag (general purpose bit 11) in local + central headers -> legacy tool behaviour
    raw = raw.replace(b"PK\x03\x04\x14\x00\x00\x08", b"PK\x03\x04\x14\x00\x00\x00")
    raw = raw.replace(b"PK\x01\x02\x14\x03\x14\x00\x00\x08", b"PK\x01\x02\x14\x03\x14\x00\x00\x00")
    z.write_bytes(raw)
    fmt, ms, notes = archives.members("names.zip")
    assert ms[0].name == "café.txt" and notes.get("names_redecoded_utf8") == 1


def test_outside_sandbox_refused(ws, tmp_path):
    make_zip(ws / "a.zip", {"x.txt": "1"})
    with pytest.raises(sandbox.SandboxError):
        archives.extract("a.zip", str(tmp_path / "elsewhere"))
    with pytest.raises(sandbox.SandboxError):
        archives.create([str(ws)], str(tmp_path / "o.zip"))


def test_create_excludes_and_deterministic(ws):
    src = make_tree(ws)
    r1 = archives.create(["my-plugin"], "dist/a.zip")
    names = zipfile.ZipFile(ws / "dist" / "a.zip").namelist()
    assert "my-plugin/my-plugin.php" in names and "my-plugin/inc/a.php" in names
    assert not any(x in n for n in names for x in (".git", "node_modules", ".DS_Store", ".env"))
    assert r1["skipped_count"] >= 4
    (src / "my-plugin.php").touch()
    r2 = archives.create(["my-plugin"], "dist/b.zip")
    assert r1["sha256"] == r2["sha256"]  # same bytes regardless of mtimes
    for info in zipfile.ZipFile(ws / "dist" / "b.zip").infolist():
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
    archives.create(["my-plugin"], "dist/flat.zip", root_name="")
    assert "my-plugin.php" in zipfile.ZipFile(ws / "dist" / "flat.zip").namelist()
    archives.create(["my-plugin"], "dist/renamed.tar.gz", root_name="renamed")
    t1 = (ws / "dist" / "renamed.tar.gz").read_bytes()
    archives.create(["my-plugin"], "dist/renamed.tar.gz", root_name="renamed")
    assert (ws / "dist" / "renamed.tar.gz").read_bytes() == t1
    with tarfile.open(ws / "dist" / "renamed.tar.gz") as tf:
        assert "renamed/inc/a.php" in tf.getnames()
        assert all(m.uid == 0 and m.mtime == 315532800 for m in tf.getmembers())
    archives.create(["my-plugin"], "dist/c.zip", exclude=["inc"])
    assert not any("inc/" in n for n in zipfile.ZipFile(ws / "dist" / "c.zip").namelist())


def test_create_skips_symlinks(ws):
    src = ws / "s"
    src.mkdir()
    (src / "a.txt").write_text("a")
    try:
        (src / "link").symlink_to("/etc/passwd")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    r = archives.create(["s"], "s.zip")
    assert zipfile.ZipFile(ws / "s.zip").namelist() == ["s/", "s/a.txt"] and r["skipped_count"] == 1


@pytest.mark.parametrize("ext", [".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".zip"])
def test_all_formats_roundtrip(ws, ext):
    make_tree(ws)
    archives.create(["my-plugin"], "pkg" + ext)
    archives.extract("pkg" + ext, "u" + ext.replace(".", "_"))
    assert (ws / ("u" + ext.replace(".", "_")) / "my-plugin" / "inc" / "a.php").exists()


@pytest.mark.parametrize("ext", [".gz", ".bz2", ".xz"])
def test_single_file_compression(ws, ext):
    (ws / "log.txt").write_text("line\n" * 100)
    archives.create(["log.txt"], "log.txt" + ext)
    assert archives.inspect("log.txt" + ext)["format"] == ext[1:]
    archives.extract("log.txt" + ext, "lg")
    assert (ws / "lg" / "log.txt").read_text() == "line\n" * 100
    with pytest.raises(ArchiveError, match="one file"):
        archives.create(["log.txt", "log.txt" + ext], "two" + ext)


def test_repack_keeps_or_renames_top_and_cleans(ws):
    with zipfile.ZipFile(ws / "mac.zip", "w") as zf:
        zf.writestr("plugin/plugin.php", "<?php")
        zf.writestr("plugin/.DS_Store", "x")
        zf.writestr("__MACOSX/plugin/._plugin.php", "x")
    r = archives.repack("mac.zip", "clean.zip")
    assert zipfile.ZipFile(ws / "clean.zip").namelist() == ["plugin/", "plugin/plugin.php"]
    archives.repack("mac.zip", "renamed.tar.xz", root_name="new-name")
    with tarfile.open(ws / "renamed.tar.xz") as tf:
        assert "new-name/plugin.php" in tf.getnames()
    assert r["format"] == "zip"
    with pytest.raises(ArchiveError, match="7z|not supported"):
        archives.repack("mac.zip", "x.7z")


def test_not_an_archive(ws):
    (ws / "x.zip").write_text("not a zip")
    with pytest.raises(ArchiveError, match="not a recognised archive"):
        archives.inspect("x.zip")


seven = shutil.which("7zz") or shutil.which("7z")


@pytest.mark.skipif(not seven, reason="7-Zip CLI not installed")
def test_7z_read_and_extract(ws, monkeypatch):
    import subprocess
    make_tree(ws)
    subprocess.run([seven, "a", str(ws / "p.7z"), "my-plugin/my-plugin.php", "my-plugin/inc"], cwd=ws, check=True,
                   capture_output=True)
    rep = archives.inspect("p.7z")
    assert rep["format"] == "7z" and rep["files"] == 2
    archives.extract("p.7z", "sz")
    assert (ws / "sz" / "my-plugin" / "inc" / "a.php").exists()
    assert archives.read_member("p.7z", "my-plugin/my-plugin.php").startswith(b"<?php")


def test_tools_policy_and_masking(ws):
    from automoto import loop, policy, tools

    t = tools.build()
    for name in ("archive_list", "archive_inspect", "archive_read", "archive_extract", "archive_create",
                 "archive_repack", "download_file"):
        assert name in t
    make_zip(ws / "a.zip", {"top/readme.txt": "hello"})
    ctx = tools.ToolContext()
    ok, out = tools.call(t["archive_list"], ctx, {"path": "a.zip"})
    assert ok and "readme.txt" in out
    ok, out = tools.call(t["archive_read"], ctx, {"path": "a.zip", "member": "top/readme.txt"})
    assert ok and out == "hello"
    ok, out = tools.call(t["archive_extract"], ctx, {"path": "a.zip", "dest": "scratch/x"})
    assert ok and (ws / "scratch" / "x" / "top" / "readme.txt").exists()
    ok, out = tools.call(t["archive_create"], ctx, {"sources": "scratch/x/top", "out": "scratch/y.zip"})
    assert ok and "1 files" in out
    make_zip(ws / "evil.zip", {"../x": "1"})
    ok, out = tools.call(t["archive_extract"], ctx, {"path": "evil.zip", "dest": "scratch/e"})
    assert not ok and "traversal" in out
    assert policy.classify("archive_list", "safe", {"path": "a.zip"})[0] == "safe"
    assert policy.classify("archive_extract", "risky", {"path": "a.zip", "dest": "scratch/z"})[0] == "safe"
    assert policy.classify("archive_extract", "risky", {"path": "a.zip", "dest": "out"})[0] == "risky"
    assert policy.classify("archive_create", "risky", {"sources": ["~/.ssh"], "out": "k.zip"})[0] == "blocked"
    assert policy.classify("download_file", "risky", {"url": "http://127.0.0.1/x.zip"})[0] == "blocked"
    assert policy.classify("download_file", "risky", {"url": "http://169.254.169.254/latest"})[0] == "blocked"
    ok, out = tools.call(t["download_file"], ctx, {"url": "http://10.0.0.1/a.zip"})
    assert not ok and "blocked" in out
    assert loop.mask_args({"path": "a", "password": "pw"}) == {"path": "a", "password": "••••••"}
    assert "download_file" in loop.TAINTING_TOOLS and "archive_read" in loop.UNTRUSTED_TOOLS


def test_download_file_saves_and_checks(ws, monkeypatch):
    from automoto import archive_tools, netguard, tools

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("p/p.php", "<?php")
    monkeypatch.setattr(netguard, "request", lambda url, **kw: netguard.Response(url, 200, "application/zip", buf.getvalue()))
    out = archive_tools.download_file(tools.ToolContext(), "https://downloads.example.org/p.1.0.zip")
    assert "downloads/p.1.0.zip" in out and "archive check: safe" in out
    assert (ws / "downloads" / "p.1.0.zip").read_bytes() == buf.getvalue()
    monkeypatch.setattr(netguard, "request", lambda url, **kw: netguard.Response(url, 200, "x", b"x" * (2 * 1024 * 1024 + 2)))
    with pytest.raises(tools.ToolFailed, match="larger than"):
        archive_tools.download_file(tools.ToolContext(), "https://e.org/big.bin", max_mb=2)


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from automoto import server

    return TestClient(server.app), {"X-AutoMoto-Token": server.SESSION_TOKEN}


def _b64(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode()


def test_server_upload_inspect_extract_pack(client, ws):
    c, H = client
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello-dolly/hello.php", "<?php\n/* Plugin Name: Hello */\n")
        zf.writestr("hello-dolly/readme.txt", "=== Hello ===\n")
        zf.writestr("__MACOSX/hello-dolly/._hello.php", "x")
    r = c.post("/api/files/upload", json={"name": "hello-dolly.zip", "data": _b64(buf.getvalue())}, headers=H)
    assert r.status_code == 200, r.text
    assert any("zip archive, 3 file(s)" in n for n in r.json()["notes"])
    lst = c.get("/api/files?dir=uploads", headers=H).json()["items"]
    assert lst[0]["view"] == "archive"
    v = c.get("/api/files/inspect", params={"path": "uploads/hello-dolly.zip"}, headers=H).json()
    assert v["kind"] == "archive" and v["report"]["safe"] and any(e["name"] == "hello-dolly/hello.php" for e in v["entries"])
    r = c.post("/api/files/archive", json={"action": "extract", "path": "uploads/hello-dolly.zip"}, headers=H)
    assert r.status_code == 200 and r.json()["path"] == "uploads/hello-dolly"
    assert (ws / "uploads" / "hello-dolly" / "hello-dolly" / "hello.php").exists()
    r = c.post("/api/files/archive", json={"action": "repack", "path": "uploads/hello-dolly.zip"}, headers=H)
    assert r.status_code == 200 and r.json()["path"] == "uploads/hello-dolly-repacked.zip"
    assert zipfile.ZipFile(ws / "uploads" / "hello-dolly-repacked.zip").namelist() == [
        "hello-dolly/", "hello-dolly/hello.php", "hello-dolly/readme.txt"]
    r = c.post("/api/files/archive", json={"action": "pack", "path": "uploads/hello-dolly/hello-dolly"}, headers=H)
    assert r.status_code == 200 and r.json()["path"] == "uploads/hello-dolly/hello-dolly.zip"
    assert c.post("/api/files/archive", json={"action": "pack", "path": "."}, headers=H).status_code == 400
    assert c.post("/api/files/archive", json={"action": "rm", "path": "x"}, headers=H).status_code == 422
    assert c.post("/api/files/archive", json={"action": "extract", "path": "../../x.zip"}, headers=H).status_code == 400


def test_server_refuses_unsafe_archive_and_previews_csv(client, ws):
    c, H = client
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.php", "<?php")
    r = c.post("/api/files/upload", json={"name": "evil.zip", "data": _b64(buf.getvalue())}, headers=H)
    assert r.status_code == 400 and "unsafe archive" in r.text
    assert not list((ws / "uploads").glob("*evil*")) if (ws / "uploads").exists() else True
    pytest.importorskip("pandas")
    r = c.post("/api/files/upload", json={"name": "sales.csv", "data": _b64(b"region;units\nNorth;3\nSouth;4\n")}, headers=H)
    assert r.status_code == 200
    v = c.get("/api/files/inspect", params={"path": "uploads/sales.csv"}, headers=H).json()
    assert v["kind"] == "table" and v["columns"] == ["region", "units"] and v["rows"][1] == ["South", "4"]
    assert v["info"]["delimiter"] == ";" and v["total_rows"] == 2
    (ws / "conf.yaml").write_text("a:\n  b: 1\n")
    assert "b: int" in " ".join(c.get("/api/files/inspect", params={"path": "conf.yaml"}, headers=H).json()["outline"])
    assert c.get("/api/files/inspect", params={"path": "uploads/sales.csv"}, headers={"X-AutoMoto-Token": "x"}).status_code == 403


def test_download_has_a_total_deadline(monkeypatch):
    """A server that trickles bytes must not hang the agent: the whole request has a deadline."""
    import time as _t
    from automoto import netguard

    class Slow:
        status = 200

        def getheader(self, k, d=None):
            return "application/zip" if k == "Content-Type" else d

        def read(self, n):
            _t.sleep(0.05)
            return b"x"

    class Conn:
        def __init__(self, *a):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Slow()

        def close(self):
            pass

    monkeypatch.setattr(netguard, "check_url", lambda u: (__import__("urllib.parse").parse.urlsplit(u), "93.184.216.34"))
    monkeypatch.setattr(netguard, "_PinnedHTTPS", Conn)
    with pytest.raises(netguard.BlockedURL, match="too long"):
        netguard.request("https://example.org/a.zip", timeout=5, total_timeout=0.3)


def test_slow_download_is_retried_on_a_fresh_connection(ws, monkeypatch):
    from automoto import archive_tools, netguard
    calls = []

    def fake(url, **kw):
        calls.append(kw.get("min_rate"))
        if len(calls) < 3:
            raise netguard.SlowResponse("too slow (10 KB in 16s)")
        return netguard.Response(url, 200, "application/zip", b"hello")

    monkeypatch.setattr(netguard, "request", fake)
    out = archive_tools.download_file(None, "https://example.org/x.bin", "downloads/x.bin")
    assert "saved downloads/x.bin" in out and len(calls) == 3 and all(calls)
    calls.clear()
    monkeypatch.setattr(netguard, "request", lambda url, **kw: (_ for _ in ()).throw(netguard.SlowResponse("slow")))
    with pytest.raises(Exception, match="3 tries"):
        archive_tools.download_file(None, "https://example.org/x.bin", "downloads/y.bin")
