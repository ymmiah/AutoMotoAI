"""Local apps, service connectors, MCP catalog, skills requirements, edit/search tools."""

import json
import shutil
from pathlib import Path

import pytest

from automoto import apps, mcp_catalog, netguard, policy, sandbox, services, skills, tools


# -- local apps -------------------------------------------------------------------------
def test_catalog_has_requested_apps():
    for a in ("ffmpeg", "imagemagick", "inkscape", "libreoffice", "tectonic", "vscode", "git", "photoshop",
              "illustrator", "premiere", "autocad", "blender", "gimp"):
        assert a in apps.BY_ID
    assert all(a.status in ("live", "unit", "untested") for a in apps.CATALOG)


@pytest.mark.parametrize("app,args", [
    ("ffmpeg", ["-i", "http://evil.example/x.mp4", "out.mp4"]),
    ("ffmpeg", ["-f", "concat", "-safe", "0", "-i", "list.txt", "o.mp4"]),
    ("ffmpeg", ["-i", "in.mp4", "/etc/cron.d/x"]),
    ("ffmpeg", ["-i", "in.mp4", "-vf", "subtitles=/etc/passwd", "o.mp4"]),
    ("imagemagick", ["@/etc/passwd", "o.png"]),
    ("imagemagick", ["msl:evil.msl"]),
    ("git", ["-c", "core.sshCommand=sh", "fetch"]),
    ("git", ["clone", "--upload-pack=touch pwned", "x"]),
    ("git", ["config", "--global", "user.name", "x"]),
    ("vscode", ["--install-extension", "evil.ext"]),
    ("gh", ["auth", "token"]),
    ("npm", ["publish"]),
    ("docker", ["run", "--privileged", "alpine"]),
    ("tectonic", ["-Z", "shell-escape", "a.tex"]),
    ("libreoffice", ["macro:///Standard.Module1.Main"]),
])
def test_dangerous_app_args_refused(app, args):
    with pytest.raises(apps.AppError):
        apps.check_args(apps.BY_ID[app], args)
    assert policy.decide("run_app", "risky", {"app_id": app, "args": args}).action == "deny"


def test_app_args_touching_secrets_blocked_by_policy():
    d = policy.decide("run_app", "risky", {"app_id": "python", "args": ["-c", "print(open('.env').read())"]})
    assert d.action == "deny"


def test_normal_app_args_ask():
    d = policy.decide("run_app", "risky", {"app_id": "ffmpeg", "args": ["-i", "in.mp4", "-t", "5", "-vf",
                                                                         "scale=1280:-2", "scratch/out.mp4"]})
    assert d.action == "ask" and "FFmpeg" in d.reason


def test_app_tools_are_risky_and_listed():
    tl = tools.build()
    assert tl["list_apps"].level == "safe"
    for n in ("run_app", "open_in_app", "run_app_script"):
        assert tl[n].level == "risky"
    assert "run_app" not in tools.build(local_apps=False)


def test_missing_app_gives_clear_error():
    ok, out = tools.call(tools.build()["run_app"], tools.ToolContext(), {"app_id": "photoshop", "args": []})
    assert not ok and ("not installed" in out or "no supported command line" in out)


@pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
def test_script_routes_per_os(monkeypatch, os_name, tmp_path):
    monkeypatch.setattr(apps, "OS", os_name)
    s = tmp_path / "a.jsx"
    if os_name == "linux":
        with pytest.raises(apps.AppError):
            apps.script_argv(apps.BY_ID["photoshop"], "ps", s, None)
    else:
        argv = apps.script_argv(apps.BY_ID["photoshop"], "ps", s, None)
        assert argv[0] == ("powershell" if os_name == "windows" else "osascript")
        assert ("DoJavaScriptFile" in " ".join(argv)) == (os_name == "windows")
    if os_name != "windows":
        with pytest.raises(apps.AppError):
            apps.script_argv(apps.BY_ID["autocad"], "acad", tmp_path / "a.scr", tmp_path / "a.dwg")
    argv = apps.script_argv(apps.BY_ID["blender"], "blender", tmp_path / "b.py", None)
    assert argv[:2] == ["blender", "-b"] and "--python" in argv


def test_jsx_path_quoting_on_windows(monkeypatch):
    monkeypatch.setattr(apps, "OS", "windows")
    argv = apps.script_argv(apps.BY_ID["illustrator"], "ai", Path("C:/x/it's.jsx"), None)
    assert "it''s.jsx" in argv[-1]  # PowerShell single-quote escaping


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_ffmpeg_live():
    out = apps.run_app("ffmpeg", ["-hide_banner", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
                                  "-y", "scratch/t.mp4"], timeout=60)
    assert out.startswith("[FFmpeg] exit 0") and (sandbox.root() / "scratch" / "t.mp4").stat().st_size > 0


# -- services ---------------------------------------------------------------------------
@pytest.mark.parametrize("args,level", [
    ({"service": "github", "path": "/repos/a/b"}, "safe"),
    ({"service": "github", "path": "/repos/a/b/issues", "method": "POST"}, "risky"),
    ({"service": "github", "path": "/repos/a/b", "method": "DELETE"}, "blocked"),
    ({"service": "github", "path": "/repos/a/b/actions/secrets"}, "blocked"),
    ({"service": "github", "path": "/repos/a/b/hooks"}, "blocked"),
    ({"service": "github", "path": "/repos/a/b/collaborators/x", "method": "PUT"}, "blocked"),
    ({"service": "gitlab", "path": "/projects/1/variables"}, "blocked"),
    ({"service": "vercel", "path": "/v9/projects/p/env"}, "blocked"),
    ({"service": "github", "path": "https://evil.example/x"}, "blocked"),
    ({"service": "github", "path": "/repos/../../x"}, "blocked"),
    ({"service": "github", "path": "//evil.example/x"}, "safe"),  # still sent to api.github.com (see below)
    ({"service": "nope", "path": "/"}, "blocked"),
])
def test_service_classification(args, level):
    assert services.classify(args)[0] == level


def test_service_call_uses_fixed_host_and_redacts_token(monkeypatch):
    seen = {}

    def fake(url, method="GET", data=None, headers=None, timeout=20):
        seen.update(url=url, headers=headers)
        return netguard.Response(url, 200, "application/json", json.dumps({"echo": "tok-123"}).encode())

    monkeypatch.setattr(netguard, "request", fake)
    monkeypatch.setenv("GITHUB_TOKEN", "tok-123")
    out = services.call("github", "GET", "//evil.example/x", {"per_page": 1})
    assert seen["url"].startswith("https://api.github.com//evil.example/x")
    assert seen["headers"]["Authorization"] == "Bearer tok-123"
    assert "tok-123" not in out and "[redacted]" in out


def test_service_needs_token_for_writes(monkeypatch):
    with pytest.raises(services.ServiceError):
        services.call("github", "POST", "/repos/a/b/issues", body={"title": "x"})
    with pytest.raises(services.ServiceError):
        services.call("vercel", "GET", "/v9/projects")


def test_service_byok_key_from_context(monkeypatch):
    seen = {}
    monkeypatch.setattr(netguard, "request", lambda url, **kw: seen.update(kw) or netguard.Response(url, 200, "", b"{}"))
    tl = tools.build()
    ctx = tools.ToolContext()
    ctx.keys = {"figma": "fig-1"}
    ok, out = tools.call(tl["service_api"], ctx, {"service": "figma", "path": "/v1/files/K"})
    assert ok and seen["headers"]["X-Figma-Token"] == "fig-1"


def test_services_status_never_shows_values(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "v-secret")
    st = services.status_list()
    assert "v-secret" not in json.dumps(st) and any(s["id"] == "vercel" and s["configured"] for s in st)


# -- MCP catalog ------------------------------------------------------------------------
def test_catalog_enable_writes_placeholders_not_secrets(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    mcp_catalog.enable("github")
    raw = mcp_catalog._file().read_text()
    assert "gh-secret" not in raw and "${GITHUB_TOKEN}" in raw
    assert mcp_catalog.expand("${GITHUB_TOKEN}") == "gh-secret"
    assert any(c["id"] == "github" and c["enabled"] for c in mcp_catalog.listing())
    assert mcp_catalog.disable("github") and not mcp_catalog.disable("github")
    with pytest.raises(KeyError):
        mcp_catalog.enable("nope")


def test_catalog_covers_requested_services():
    ids = {c.id for c in mcp_catalog.CATALOG}
    assert {"github", "gitlab", "notion", "figma", "canva", "vercel", "google-drive", "onedrive", "zotero"} <= ids


# -- skills -----------------------------------------------------------------------------
REQUESTED = ["web-design", "graphic-design", "video-editing", "audio-editing", "bug-fixing", "linux-terminal",
             "coding-python", "coding-javascript", "html-css", "latex", "go", "algorithms", "cross-platform-apps",
             "vscode", "photoshop", "illustrator", "premiere-pro", "autocad", "canva", "google-drive", "onedrive",
             "github", "gitlab", "notion", "figma", "vercel", "zotero", "online-shopping", "travel-booking"]


def test_bundled_skills_present_with_metadata():
    found = skills.discover()
    tool_names = set(tools.build(desktop=True))
    for name in REQUESTED:
        s = found[name]
        assert s.meta.get("status") in ("live", "unit", "untested"), name
        assert len(s.body()) > 200, name
        for t in s.needs("tools"):
            assert t in tool_names, (name, t)  # skills only name tools that exist
        for a in s.needs("apps") + s.needs("optional_apps"):
            for alt in a.split("|"):
                assert alt.strip() in apps.BY_ID, (name, alt)


def test_skill_requirements_reflect_machine(monkeypatch):
    monkeypatch.setattr(apps, "detect", lambda refresh=False: {"ffmpeg": "/x/ffmpeg"})
    found = skills.discover()
    assert not found["video-editing"].requirements()["ready"]  # ffprobe missing
    monkeypatch.setattr(apps, "detect", lambda refresh=False: {"ffmpeg": "/x", "ffprobe": "/y"})
    assert found["video-editing"].requirements()["ready"]
    assert not found["canva"].requirements()["ready"]  # connector-only, not enabled
    mcp_catalog.enable("canva")
    assert found["canva"].requirements()["ready"]


def test_shopping_and_booking_skills_never_buy():
    found = skills.discover()
    for n in ("online-shopping", "travel-booking"):
        body = found[n].body().lower()
        assert "never" in body and ("buy" in body or "book" in body)


# -- edit_file / search_files -----------------------------------------------------------
def test_edit_file_exact_unique_replace():
    tl, ctx = tools.build(), tools.ToolContext()
    tools.call(tl["write_file"], ctx, {"path": "scratch/a.py", "content": "x = 1\ny = 1\nx = 1\n"})
    ok, out = tools.call(tl["edit_file"], ctx, {"path": "scratch/a.py", "old": "x = 1", "new": "x = 2"})
    assert not ok and "2" in out  # ambiguous
    ok, _ = tools.call(tl["edit_file"], ctx, {"path": "scratch/a.py", "old": "y = 1", "new": "y = 3"})
    assert ok and "y = 3" in (sandbox.root() / "scratch/a.py").read_text()
    ok, _ = tools.call(tl["edit_file"], ctx, {"path": "scratch/a.py", "old": "x = 1", "new": "x = 9", "count": 0})
    assert ok and (sandbox.root() / "scratch/a.py").read_text().count("x = 9") == 2
    ok, out = tools.call(tl["edit_file"], ctx, {"path": "scratch/a.py", "old": "zzz", "new": "q"})
    assert not ok


def test_search_files_skips_secrets():
    tl, ctx = tools.build(), tools.ToolContext()
    (sandbox.root() / "proj").mkdir(parents=True, exist_ok=True)
    (sandbox.root() / "proj" / "main.py").write_text("API = load()\n")
    (sandbox.root() / "proj" / ".env").write_text("API=secret\n")
    ok, out = tools.call(tl["search_files"], ctx, {"pattern": "API", "path": "proj"})
    assert ok and "main.py" in out and "secret" not in out
