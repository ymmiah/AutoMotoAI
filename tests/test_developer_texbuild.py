"""V11: TeX build consent, bounded real subprocess, ephemeral PDF and SyncTeX."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from automoto import developer_adapters as adapters
from automoto import developer_texbuild as tex
from automoto import sandbox, server
from automoto.hosted import path_allowed

BASE = "/api/developer/studio/texbuild"
H = {"X-AutoMoto-Token": server.SESSION_TOKEN}

FAKE_ENGINE = r'''
import gzip, os, sys, time
from pathlib import Path
mode, output_path, main_path = sys.argv[1:4]
output = Path(output_path)
output.mkdir(parents=True, exist_ok=True)
if mode == "timeout":
    time.sleep(30)
    raise SystemExit(7)
if mode == "flood":
    print("A"*100000, flush=True)
    time.sleep(30)
    raise SystemExit(7)
if mode == "fail":
    print("! LaTeX Error: Synthetic compiler failure", flush=True)
    print("l.5 bad source", flush=True)
    raise SystemExit(9)
name = Path(main_path).stem
(output / (name+".pdf")).write_bytes(
    b"%PDF-1.4\n1 0 obj\n<</Type/Catalog>>\nendobj\n%%EOF\n")
body = ("SyncTeX Version:1\n"
        "Input:1:"+str(Path.cwd()/main_path)+"\n"
        "Input:2:"+str(Path.cwd()/"chapters"/"intro.tex")+"\n"
        "Content:\n{1\n[1,4:120,240:20,10,0\n}\n"
        "{2\n[2,1:200,300:20,10,0\n}\nPostamble:\n")
(output / (name+".synctex.gz")).write_bytes(gzip.compress(body.encode("utf-8")))
print("LaTeX Warning: Synthetic cross-reference warning", flush=True)
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_DATA_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v11-report"
    (root / "chapters").mkdir(parents=True)
    (root / "figures").mkdir()
    (root / "main.tex").write_text(
        "\\documentclass{report}\n"
        "\\begin{document}\n"
        "\\chapter{Summary}\\label{chap:summary}\n"
        "\\input{chapters/intro}\n"
        "\\begin{table}\\caption{Observed values}\\end{table}\n"
        "\\includegraphics{figures/plot}\n"
        "\\bibliography{sources}\n"
        "\\end{document}\n", encoding="utf-8")
    (root / "chapters" / "intro.tex").write_text(
        "\\section{Introduction}\\label{sec:intro}\n"
        "See \\ref{chap:summary}.\n", encoding="utf-8")
    (root / "sources.bib").write_text(
        "@article{sample2026, author={Miah, A}, title={Real local data},year={2026}}\n",
        encoding="utf-8")
    (root / "figures" / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\nsmall-fixture")
    fake = tmp_path / "fake-tex.py"
    fake.write_text(FAKE_ENGINE, encoding="utf-8")
    exe = str(Path(sys.executable).resolve())
    sha = hashlib.sha256(Path(exe).read_bytes()).hexdigest()
    def fake_engines(_root):
        return [{"name": n, "status": "installed_not_executed",
                 "executable": exe, "sha256": sha, "size_bytes": Path(exe).stat().st_size}
                for n in ("tectonic", "latexmk")]
    monkeypatch.setattr(tex, "_engines", fake_engines)
    monkeypatch.setattr(tex, "_command", lambda engine, executable, main, output:
                        [executable, "-u", str(fake), "success", str(output), main])
    with tex.PREVIEW_LOCK:
        tex.PREVIEWS.clear()
    yield TestClient(server.app), root, tmp_path, fake, exe, sha
    with tex.PREVIEW_LOCK:
        tex.PREVIEWS.clear()


def trust(client, root, value=True):
    response = client.post("/api/developer/studio/trust", headers=H,
                           json={"project": str(root), "trusted": value, "confirmed": True})
    assert response.status_code == 200, response.text


def post(client, endpoint, root, **values):
    return client.post(BASE+"/"+endpoint, headers=H,
                       json={"project": str(root), **values})


def build(client, root, exe, sha, **opts):
    return post(client, "build", root, main="main.tex", engine=opts.pop("engine","tectonic"),
                expected_executable=exe, expected_sha256=sha, confirmed=True,
                acknowledge_external_process_risk=True, **opts)


def test_engines_are_inspected_but_not_executed(project):
    client, root, _, fake, exe, sha = project
    resp = client.get(BASE+"/engines", headers=H, params={"project": str(root)})
    assert resp.status_code == 200
    data = resp.json()
    assert {x["name"] for x in data["engines"]} == {"tectonic", "latexmk"}
    assert all(x["status"]=="installed_not_executed" for x in data["engines"])
    assert data["auto_execute"] is False
    assert data["platform_sandbox"] is False
    assert not list(root.glob("*.pdf"))


def test_nontrusted_project_and_missing_approval_cannot_run(project):
    client, root, _, fake, exe, sha = project
    assert build(client, root, exe, sha).status_code == 403
    trust(client, root)
    request={"project": str(root), "main":"main.tex", "engine":"tectonic",
             "expected_executable":exe,"expected_sha256":sha}
    assert client.post(BASE+"/build", headers=H, json=request).status_code == 422
    assert client.post(BASE+"/build", headers=H,
                       json={**request,"confirmed":False,
                             "acknowledge_external_process_risk":True}).status_code == 422
    assert client.post(BASE+"/build", headers=H,
                       json={**request,"confirmed":True,
                             "acknowledge_external_process_risk":False}).status_code == 422
    assert not list(root.rglob("*.pdf"))


@pytest.mark.parametrize("engine", ["tectonic", "latexmk"])
def test_real_subprocess_build_snapshot_pdf_and_synctex(project, engine):
    client, root, _, _, exe, sha = project
    trust(client, root)
    originals={p.relative_to(root).as_posix():p.read_bytes()
               for p in root.rglob("*") if p.is_file()}
    reply=build(client, root, exe, sha, engine=engine)
    assert reply.status_code==200,reply.text
    result=reply.json()
    assert result["pdf_ready"] is True
    assert result["status"]=="completed"
    assert result["compiler"]==engine
    assert result["explicit_approval"] is True
    assert result["platform_sandbox"] is False
    assert result["synctex_available"] is True
    assert result["synctex_records"]==2
    assert len(result["figures"])==1
    assert len(result["table_locations"])==1
    assert result["input_file_count"]==4
    assert len(result["source_hash"])==64
    assert any(d["severity"]=="warning" for d in result["diagnostics"])
    data=post(client,"preview",root,build_id=result["build_id"])
    assert data.status_code==200,data.text
    pdf=base64.b64decode(data.json()["pdf_base64"])
    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf[-2048:]
    assert data.json()["pdf_sha256"] == hashlib.sha256(pdf).hexdigest()
    forward=post(client,"sync/source-to-pdf",root,build_id=result["build_id"],
                 path="chapters/intro.tex",line=1)
    assert forward.status_code==200,forward.text
    assert forward.json()["page"]==2
    assert forward.json()["exact_line_match"] is True
    reverse=post(client,"sync/page-to-source",root,build_id=result["build_id"],page=2)
    assert reverse.status_code==200,reverse.text
    assert reverse.json()["path"]=="chapters/intro.tex"
    assert reverse.json()["line"]==1
    assert reverse.json()["approximate_page_to_source"] is True
    assert originals=={p.relative_to(root).as_posix():p.read_bytes()
                       for p in root.rglob("*") if p.is_file()}
    assert not list(root.rglob("*.pdf"))


def test_compiler_sha_and_path_revalidated_before_any_subprocess(project, monkeypatch):
    client, root, _, _, exe, sha = project
    trust(client,root)
    assert build(client,root,exe,"0"*64).status_code==409
    assert build(client,root,exe+"-changed",sha).status_code==409
    real=adapters._fingerprint
    def changed(executable,workspace):
        result=real(executable,workspace)
        result["sha256"]="f"*64
        return result
    monkeypatch.setattr(adapters,"_fingerprint",changed)
    assert build(client,root,exe,sha).status_code==409


def test_shell_escape_macro_and_unsafe_image_rejected(project):
    client,root,_,_,exe,sha=project
    trust(client,root)
    main=root/"main.tex"
    original=main.read_text(encoding="utf-8")
    main.write_text(original+"\\immediate\\write18{touch /tmp/unsafe}\n",encoding="utf-8")
    assert build(client,root,exe,sha).status_code==422
    main.write_text(original.replace("figures/plot","../../private"),encoding="utf-8")
    assert build(client,root,exe,sha).status_code==409
    main.write_text(original.replace("figures/plot","figures/evil"),encoding="utf-8")
    link=root/"figures"/"evil.png"
    try:
        link.symlink_to(root/"figures"/"plot.png")
        assert build(client,root,exe,sha).status_code==409
    except (OSError,NotImplementedError):
        pass


def test_compilation_refused_on_missing_source_and_incomplete_graph(project,monkeypatch):
    client,root,_,_,exe,sha=project
    trust(client,root)
    (root/"chapters"/"intro.tex").unlink()
    assert build(client,root,exe,sha).status_code==409
    (root/"chapters"/"intro.tex").write_text("\\section{Ok}\n",encoding="utf-8")
    monkeypatch.setattr(tex.latex,"MAX_FILES",1)
    assert build(client,root,exe,sha).status_code==409


def test_snapshot_unsaved_buffer_without_modifying_project(project):
    client,root,_,_,exe,sha=project
    trust(client,root)
    before=(root/"chapters"/"intro.tex").read_bytes()
    updated="\\section{Unsaved}\\label{sec:unsaved}\n"
    result=build(client,root,exe,sha,active_path="chapters/intro.tex",
                 active_text=updated)
    assert result.status_code==200,result.text
    assert result.json()["pdf_ready"] is True
    assert (root/"chapters"/"intro.tex").read_bytes()==before


@pytest.mark.parametrize("mode,expected", [("timeout","timeout"),("flood","output_limit"),
                                            ("fail","failed")])
def test_bounded_process_failure_and_cleanup(project,monkeypatch,mode,expected):
    client,root,_,fake,exe,sha=project
    trust(client,root)
    monkeypatch.setattr(tex,"MAX_RUN_SECONDS",0.25)
    monkeypatch.setattr(tex,"_command",lambda engine,executable,main,out:
                        [executable,"-u",str(fake),mode,str(out),main])
    r=build(client,root,exe,sha)
    assert r.status_code==200,r.text
    body=r.json()
    assert body["status"]==expected
    assert body["pdf_ready"] is False
    assert "build_id" not in body
    if mode=="fail":
        assert body["exit_code"]==9
        assert any("Synthetic compiler failure" in x["message"]
                   for x in body["diagnostics"])


def test_invalid_pdf_rejected_without_caching(project,monkeypatch):
    client,root,_,fake,exe,sha=project
    trust(client,root)
    script=Path(fake).with_name("malformed.py")
    script.write_text('import sys\nfrom pathlib import Path\nout=Path(sys.argv[1]);out.mkdir(exist_ok=True)\n'
                      '(out/"main.pdf").write_bytes(b"not a pdf")\n',encoding="utf-8")
    monkeypatch.setattr(tex,"_command",lambda engine,executable,main,out:
                        [executable,str(script),str(out)])
    r=build(client,root,exe,sha)
    assert r.status_code==200,r.text
    assert r.json()["status"]=="invalid_pdf"
    assert r.json()["pdf_ready"] is False


def test_preview_revocation_project_binding_and_ttl(project,monkeypatch):
    client,root,tmp,fake,exe,sha=project
    trust(client,root)
    result=build(client,root,exe,sha).json()
    build_id=result["build_id"]
    assert post(client,"preview",root,build_id=build_id).status_code==200
    trust(client,root,False)
    assert post(client,"preview",root,build_id=build_id).status_code==403
    trust(client,root,True)
    other=root.parent/"other-v11"
    other.mkdir()
    trust(client,other,True)
    assert post(client,"preview",other,build_id=build_id).status_code==403
    monkeypatch.setattr(tex,"PREVIEW_TTL",-1)
    assert post(client,"preview",root,build_id=build_id).status_code==410


def test_synctex_rejects_external_source_tags_and_gzip_bombs(project):
    client,root,tmp,_,_,_=project
    stage=tmp/"build"/"sources"
    stage.mkdir(parents=True)
    legit=stage/"main.tex"
    legit.write_text("Example",encoding="utf-8")
    text=("SyncTeX Version:1\nInput:1:"+str(legit)+"\n"
          "Input:3:/etc/passwd\nContent:\n{1\n"
          "[1,5:12,30:1,2,3\n[3,8:11,22:1,2,3\n}\nPostamble:\n")
    pins=tex._synctex(gzip.compress(text.encode()),stage,{"main.tex"})
    assert pins==[{"path":"main.tex","line":5,"page":1,"x_sp":12,"y_sp":30}]
    monkeybytes=gzip.compress(b"x"*(tex.MAX_SYNCTEX_EXPANDED+3))
    assert tex._synctex(monkeybytes,stage,{"main.tex"})==[]


def test_fixed_engine_argv_untrusted_offline_and_shell_escape_disabled():
    t=tex._command("tectonic","/usr/bin/tectonic","main.tex",Path("/tmp/safe-output"))
    assert t[1:] == ["--untrusted","--only-cached","--synctex","--keep-logs",
                     "--outdir","/tmp/safe-output","main.tex"]
    assert "-shell-escape" not in t
    l=tex._command("latexmk","/usr/bin/latexmk","main.tex",Path("/tmp/safe-output"))
    assert "-norc" in l
    assert "-pdf" in l
    assert any("-no-shell-escape" in x for x in l)
    assert "main.tex"==l[-1]
    assert "-pvc" not in l


def test_hosted_routes_default_denied_and_never_execute_automatically(project):
    client,root,_,_,exe,sha=project
    for path in ("build","preview","sync/source-to-pdf","sync/page-to-source"):
        assert path_allowed("POST",BASE+"/"+path) is False
    assert path_allowed("GET",BASE+"/engines") is False
    assert client.get(BASE+"/engines",params={"project":str(root)}).status_code==403
    assert client.post(BASE+"/build",json={"project":str(root),"main":"main.tex",
                "engine":"tectonic","expected_sha256":sha,"expected_executable":exe,
                "confirmed":True,"acknowledge_external_process_risk":True}).status_code==403


def test_snapshot_limits_and_figure_type_check(project,monkeypatch):
    client,root,_,_,exe,sha=project
    trust(client,root)
    monkeypatch.setattr(tex,"MAX_INPUT_BYTES",5)
    assert build(client,root,exe,sha).status_code==413
    monkeypatch.setattr(tex,"MAX_INPUT_BYTES",10*1024*1024)
    (root/"figures"/"plot.png").write_bytes(b"not an image")
    assert build(client,root,exe,sha).status_code==422
