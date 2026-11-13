"""Developer Studio V14: real frontend files, accessibility and inert browser preview."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest
from automoto import developer_frontend as fe, sandbox, server
from automoto.hosted import path_allowed

HEADERS={"X-AutoMoto-Token":server.SESSION_TOKEN}
BASE="/api/developer/studio/frontend"

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<script>window.__EXECUTED = 'unsafe';</script>
<link href="https://tracker.example/asset.css" rel="stylesheet"></head>
<body><main class="shell"><h1>Real responsive sample</h1>
<section class="card" id="dup">Preserved card layout</section>
<div id="dup">Duplicate</div>
<img src="https://tracker.example/bad.png">
<button onclick="alert(10)"></button>
<input id="unlabelled" placeholder="Unlabelled">
<a href="https://attacker.example/collect" target="_blank">External</a>
<a href="#dup">On-page</a>
<iframe src="https://attacker.example/frame"></iframe>
<svg onload="alert(1)"><image href="https://attacker.example/asset"></svg>
</main></body></html>"""

CSS = """
.card { display:grid; gap:12px; padding:16px; background-color:#eeeeee;
        background-image:url(https://tracker.example/bad.png); }
.shell { max-width:960px; margin:0 auto; }
@import url("https://tracker.example/steal.css");
@media (max-width:480px){.card{display:block}}
"""
@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_DATA_DIR",str(tmp_path/"home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE",str(tmp_path/"workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    root=sandbox.default_root()/"frontend-v14"
    (root/"src").mkdir(parents=True)
    (root/"dist").mkdir()
    (root/"index.html").write_text(HTML,encoding="utf-8")
    (root/"styles.css").write_text(CSS,encoding="utf-8")
    (root/"mobile.scss").write_text('@use "sass:math";\n.item{min-width:840px}',encoding="utf-8")
    (root/"src"/"App.tsx").write_text(
        "export default function App(){return <main><button onClick={()=>alert('x')}>Go</button></main>}",
        encoding="utf-8")
    (root/"src"/"Card.vue").write_text(
        "<template><div>{{ label }}</div></template><script>export default {}</script>",
        encoding="utf-8")
    (root/"src"/"Panel.svelte").write_text(
        "<script>let value=1;</script><h1>Panel</h1>",encoding="utf-8")
    (root/"dist"/"index.html").write_text(
        "<html lang='en'><head><meta name='viewport' content='width=device-width'>"
        "</head><body><h1>Built HTML structure</h1>"
        "<script>window.__BUILTJS=1</script></body></html>",encoding="utf-8")
    (root/"package.json").write_text(json.dumps({
        "name":"web-ui-v14-fixture","scripts":{"build":"vite build"},
        "dependencies":{"next":"^16.0.0","react":"^19.0.0",
                        "vue":"^3.0.0","svelte":"^5.0.0",
                        "@angular/core":"^20.0.0"}
    }),encoding="utf-8")
    (root/"vite.config.ts").write_text("export default {build:{}}",encoding="utf-8")
    yield TestClient(server.app),root


def get(client,root):
    return client.get(BASE+"/inspect",headers=HEADERS,params={"project":str(root)})


def post(client,endpoint,root,**kwargs):
    return client.post(BASE+"/"+endpoint,headers=HEADERS,
                       json={"project":str(root),**kwargs})


def test_framework_inventory_is_declared_not_verified(project):
    client,root=project
    snapshot={p.relative_to(root).as_posix():p.read_bytes()
              for p in root.rglob("*") if p.is_file()}
    r=get(client,root)
    assert r.status_code==200,r.text
    data=r.json()
    names={x["name"] for x in data["frameworks"]}
    assert {"Next.js","React","Vue","Angular","Svelte","Vite"} <= names
    assert data["build_script_available"] is True
    assert data["framework_rendered"] is False
    assert data["installed_framework_versions_verified"] is False
    assert data["no_execution"] is True
    assert data["no_network"] is True
    assert "src/App.tsx" in data["files"]
    assert "src/Card.vue" in data["files"]
    assert "src/Panel.svelte" in data["files"]
    assert "styles.css" in data["files"]
    assert "mobile.scss" in data["files"]
    assert snapshot=={p.relative_to(root).as_posix():p.read_bytes()
                      for p in root.rglob("*") if p.is_file()}


def test_sanitised_html_preview_no_script_network_event_or_remote_asset(project):
    client,root=project
    r=post(client,"preview",root,path="index.html",stylesheet="styles.css")
    assert r.status_code==200,r.text
    data=r.json()
    source=data["srcdoc"]
    assert "Real responsive sample" in source
    assert "Preserved card layout" in source
    assert '<meta http-equiv="Content-Security-Policy"' in source
    assert "default-src" in source and "script-src" in source
    assert data["iframe_sandbox_attribute"]==""
    assert data["source_javascript_executed"] is False
    assert data["external_assets_loaded"] is False
    assert data["sanitised_static_only"] is True
    assert data["preview_viewports"]==[375,768,1440]
    for hostile in ("window.__EXECUTED", "onclick=", "onload=", "<script",
                    "<iframe", "https://tracker.example", "https://attacker.example",
                    "<svg", "<form", "<link", "@import", "background-image:"):
        assert hostile not in source,hostile
    assert ".card{display:grid;gap:12px;padding:16px;background-color:#eeeeee}" in source
    assert data["rejected_unsafe_or_unsupported_css_declarations"]>=1
    assert data["omitted_html_elements"]>=3
    assert data["source_sha256"]==hashlib.sha256((root/"index.html").read_bytes()).hexdigest()


def test_accessibility_findings_actual_html_and_htmlparser_void_tag(project):
    client,root=project
    r=post(client,"audit",root,path="index.html")
    assert r.status_code==200,r.text
    by_code={x["code"] for x in r.json()["issues"]}
    assert {"image-alt","button-name","input-name","duplicate-id"} <= by_code
    assert "document-language" not in by_code
    assert "viewport" not in by_code
    assert "heading-h1" not in by_code
    assert r.json()["actual_render_and_wcag_verified"] is False
    # Regression: <meta> and <link> are void tags and must not suppress body.
    preview=post(client,"preview",root,path="index.html")
    assert preview.status_code==200
    assert "Real responsive sample" in preview.json()["srcdoc"]


def test_lexical_component_audit_does_not_claim_dom_a11y(project):
    client,root=project
    for path in ("src/App.tsx","src/Card.vue","src/Panel.svelte"):
        r=post(client,"audit",root,path=path)
        assert r.status_code==200,r.text
        assert r.json()["static_only"] is True
        assert r.json()["actual_render_and_wcag_verified"] is False
        assert "dynamic framework syntax" in " ".join(r.json()["limitations"])
        assert r.json()["source_files_modified"] is False
        assert post(client,"preview",root,path=path).status_code==422


def test_generated_html_allowed_only_exact_known_index_and_not_executed(project):
    client,root=project
    r=post(client,"preview",root,path="dist/index.html")
    assert r.status_code==200,r.text
    assert "Built HTML structure" in r.json()["srcdoc"]
    assert "window.__BUILTJS" not in r.json()["srcdoc"]
    (root/"dist"/"secrets.html").write_text("<h1>should not be copied</h1>")
    assert post(client,"preview",root,path="dist/secrets.html").status_code==403


def test_stylesheet_must_be_project_local_css_not_scss_or_remote(project):
    client,root=project
    assert post(client,"preview",root,path="index.html",
                stylesheet="mobile.scss").status_code==422
    assert post(client,"preview",root,path="index.html",
                stylesheet="../../outside.css").status_code in (403,422)
    assert post(client,"preview",root,path="index.html",
                stylesheet="https://example.com/remote.css").status_code in (403,422)


def test_css_and_scss_audit_warn_not_certify_responsiveness(project):
    client,root=project
    css=post(client,"audit",root,path="styles.css")
    assert css.status_code==200
    assert any(x["code"]=="remote-resource-risk" for x in css.json()["issues"])
    scss=post(client,"audit",root,path="mobile.scss")
    assert scss.status_code==200
    assert any(x["code"]=="fixed-min-width" for x in scss.json()["issues"])
    assert any("SCSS requires" in x for x in scss.json()["limitations"])


def test_html_injection_nesting_css_data_and_invalid_sources_fail_closed(project):
    client,root=project
    (root/"index.html").write_text(
        '<html lang=en><head><meta name=viewport content="width=device-width"></head>'
        '<body><script>alert(1)<div>LEAK</div></script>'
        '<div class="safe">Visible</div>'
        '<img src=x onerror="alert(9)" alt="hello &quot; evil">'
        '<a href="javascript:alert(2)" onclick="bad()">Click</a>'
        '<style>body{background:url(https://bad.test)}</style>'
        '<h1>Heading</h1></body></html>',encoding="utf-8")
    out=post(client,"preview",root,path="index.html")
    assert out.status_code==200,out.text
    content=out.json()["srcdoc"]
    assert "Visible" in content and "Heading" in content
    assert "LEAK" not in content
    assert "javascript:alert" not in content
    assert "onerror" not in content and "onclick" not in content
    assert "https://bad.test" not in content
    assert "hello &quot; evil" in content
    assert post(client,"preview",root,path=".env").status_code in (403,422)
    (root/"index.html").write_bytes(b"not\x00html")
    assert post(client,"preview",root,path="index.html").status_code==413


def test_symlinks_and_oversized_html_cannot_be_previewed(project,tmp_path):
    client,root=project
    external=tmp_path/"private.html"
    external.write_text("<h1>Outside Project</h1>")
    link=root/"src"/"linked.html"
    try:
        link.symlink_to(external)
    except (OSError,NotImplementedError):
        pytest.skip("Symlink creation denied by OS")
    assert post(client,"preview",root,path="src/linked.html").status_code in (403,422)
    (root/"index.html").write_text("x"*(fe.MAX_BYTES+1))
    assert post(client,"preview",root,path="index.html").status_code==413



def test_built_html_directory_and_file_links_refused(project,tmp_path):
    client,root=project
    target=tmp_path/"other-index.html"
    target.write_text("<h1>EXTERNAL PRIVATE DATA</h1>",encoding="utf-8")
    built=root/"dist"/"index.html"
    built.unlink()
    try:
        built.symlink_to(target)
    except (OSError,NotImplementedError):
        pytest.skip("Symlink creation unsupported on this runner")
    r=post(client,"preview",root,path="dist/index.html")
    assert r.status_code==403
    assert "EXTERNAL PRIVATE DATA" not in r.text
    built.unlink()
    folder=root/"dist"
    folder.rmdir()
    try:
        folder.symlink_to(tmp_path,target_is_directory=True)
    except (OSError,NotImplementedError):
        pytest.skip("Linked directory unsupported on this runner")
    assert post(client,"preview",root,path="dist/index.html").status_code==403


def test_preview_css_fail_closed_on_active_functions():
    css='''.tile{display:grid;position:fixed;
    background:url(https://evil.example/x);
    color:expression(alert(1));font-size:16px;
    background-color:#f7f7f7;--data:"url(https://evil.example)"}
    @import url(https://evil.example/from.css);'''
    result,dropped=fe._css_preview(css)
    assert ".tile{" in result
    assert "display:grid" in result
    assert "font-size:16px" in result
    assert "background-color:#f7f7f7" in result
    assert "https://" not in result
    assert "position:fixed" not in result
    assert "expression" not in result
    assert dropped>=3


def test_scanner_is_bounded_and_csp_sandbox_never_loosens():
    assert "default-src 'none'" in fe.CSP
    assert "script-src 'none'" in fe.CSP
    assert "connect-src 'none'" in fe.CSP
    assert "form-action 'none'" in fe.CSP
    assert "img-src 'none'" in fe.CSP
    assert fe._css_preview("div{background:url(http://evil);display:grid;}")[0]=="div{display:grid}"
    assert fe._css_preview("@import url(http://evil);")[0]==""
    assert fe._css_preview(".tile{display:flex;color:rgb(10,10,10)}")[0].startswith(".tile{")


def test_authentication_and_hosted_mode_default_denied(project):
    client,root=project
    assert not path_allowed("GET",BASE+"/inspect")
    assert not path_allowed("POST",BASE+"/preview")
    assert not path_allowed("POST",BASE+"/audit")
    assert client.get(BASE+"/inspect",params={"project":str(root)}).status_code==403
    assert client.post(BASE+"/audit",
       json={"project":str(root),"path":"index.html"}).status_code==403
    assert client.post(BASE+"/preview",
       json={"project":str(root),"path":"index.html"}).status_code==403
