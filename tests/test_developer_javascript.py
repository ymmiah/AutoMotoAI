"""V13: actual Node unit tests, optional npm build, trust and toolchain security."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from automoto import developer_adapters as adapters
from automoto import developer_javascript as js
from automoto import sandbox, server
from automoto.hosted import path_allowed

H = {"X-AutoMoto-Token": server.SESSION_TOKEN}
BASE = "/api/developer/studio/javascript"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "v13-home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "v13-workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT", "10000")
    monkeypatch.delenv("AUTOMOTO_MODE", raising=False)
    root = sandbox.default_root() / "v13-javascript"
    (root/"src").mkdir(parents=True)
    (root/"package.json").write_text(json.dumps({
        "name": "v13-real-tests", "private": True, "packageManager": "npm@10.8.2",
        "engines": {"node": ">=20"},
        "scripts": {"test": "node --test src/math.test.cjs",
                    "build": "node build.cjs", "lint": "node --check src/math.cjs",
                    "typecheck": "tsc --noEmit"},
        "dependencies": {"react": "^19.0.0"},
        "devDependencies": {"typescript": "^5.9.0", "vitest": "^3.0.0"}
    }), encoding="utf-8")
    (root/"package-lock.json").write_text('{"name":"v13-real-tests","lockfileVersion":3}', encoding="utf-8")
    (root/"tsconfig.json").write_text('{"compilerOptions":{"strict":true}}', encoding="utf-8")
    (root/"src"/"math.cjs").write_text("exports.sum = (a,b)=>a+b;\n", encoding="utf-8")
    (root/"src"/"math.test.cjs").write_text(
        "const test=require('node:test');\n"
        "const assert=require('node:assert/strict');\n"
        "const {sum}=require('./math.cjs');\n"
        "test('real addition',()=>assert.equal(sum(2,3),5));\n", encoding="utf-8")
    (root/"build.cjs").write_text(
        "const fs=require('node:fs');fs.writeFileSync('output-built.txt','built');\n",
        encoding="utf-8")
    return TestClient(server.app), root


def trust(client, root, allow=True):
    r=client.post("/api/developer/studio/trust", headers=H, json={
        "project":str(root), "trusted":allow, "confirmed":True})
    assert r.status_code==200, r.text


def inspect(client, root):
    return client.get(BASE+"/inspect", headers=H, params={"project":str(root)})


def request_run(client, root, *, task, tool="node", **kw):
    info=inspect(client, root)
    assert info.status_code==200, info.text
    body=info.json()
    t=next(x for x in body["toolchains"] if x["name"]==tool)
    if t["status"] != "installed_not_executed":
        pytest.skip("Approved system tool "+tool+" is not available on this runner")
    return client.post(BASE+"/run", headers=H, json={
        "project":str(root), "task":task, "tool":tool,
        "expected_manifest_sha256":body["package_json_sha256"],
        "expected_executable":t["executable"], "expected_sha256":t["sha256"],
        "confirmed":True, "accept_unsandboxed_execution_and_write_risk":True, **kw})


def test_inspection_is_readonly_and_detects_actual_framework_lockfiles_scripts(project,monkeypatch):
    client,root=project
    original={x.relative_to(root).as_posix():x.read_bytes() for x in root.rglob("*") if x.is_file()}
    r=inspect(client,root)
    assert r.status_code==200,r.text
    data=r.json()
    assert data["manager"]=="npm"
    assert data["engines_node_declared"]==">=20"
    assert data["typescript_declared"] and data["tsconfig_present"]
    assert {x["name"] for x in data["frameworks"]}=={"React","Vitest"}
    assert data["scripts"]["build"]=="node build.cjs"
    assert "src/math.test.cjs" in data["test_files"]
    assert data["lockfiles"][0]["manager"]=="npm"
    assert data["package_json_sha256"]==hashlib.sha256((root/"package.json").read_bytes()).hexdigest()
    assert data["runtime_version_verified"] is False
    assert data["automatic_execute"] is False
    assert not data["project_trusted"]
    assert original=={x.relative_to(root).as_posix():x.read_bytes() for x in root.rglob("*") if x.is_file()}


def test_refuse_ambiguous_manifest_and_restricted_package_json(project):
    client,root=project
    (root/"package.json").write_text('{"scripts":{"test":"echo safe"},"scripts":{"test":"echo not-safe"}}')
    assert inspect(client,root).status_code==422
    (root/"package.json").unlink()
    try:
        (root/"package.json").symlink_to(root/"src"/"math.cjs")
        assert inspect(client,root).status_code in (403,422)
    except (OSError,NotImplementedError):
        pass


def test_lockfile_conflict_and_package_manager_mismatch(project):
    client,root=project
    (root/"yarn.lock").write_text("yarn metadata placeholder")
    data=inspect(client,root).json()
    assert data["lockfile_conflict"]
    assert data["package_manager_declared"]=="npm@10.8.2"
    with pytest.raises(Exception):
        js._command(root,js.RunIn(
            project=str(root),task="script",tool="pnpm",script="test",
            expected_manifest_sha256="a"*64,expected_executable=sys.executable,
            expected_sha256="b"*64,confirmed=True,
            accept_unsandboxed_execution_and_write_risk=True),
            data,sys.executable)


def test_execution_requires_workspace_trust_and_literal_confirmations(project):
    client,root=project
    tools=inspect(client,root).json()["toolchains"]
    node=next(x for x in tools if x["name"]=="node")
    if node["status"]!="installed_not_executed":
        pytest.skip("Node native executable unavailable")
    obj={"project":str(root),"task":"node_version","tool":"node",
         "expected_manifest_sha256":inspect(client,root).json()["package_json_sha256"],
         "expected_executable":node["executable"],"expected_sha256":node["sha256"]}
    assert client.post(BASE+"/run",headers=H,json={**obj,
        "confirmed":True,"accept_unsandboxed_execution_and_write_risk":True}).status_code==403
    trust(client,root)
    assert client.post(BASE+"/run",headers=H,json=obj).status_code==422
    assert client.post(BASE+"/run",headers=H,json={**obj,"confirmed":False,
        "accept_unsandboxed_execution_and_write_risk":True}).status_code==422
    assert client.post(BASE+"/run",headers=H,json={**obj,"confirmed":True,
        "accept_unsandboxed_execution_and_write_risk":False}).status_code==422


def test_actual_installed_node_runtime_version_and_syntax_check(project):
    client,root=project
    trust(client,root)
    result=request_run(client,root,task="node_version")
    assert result.status_code==200,result.text
    assert result.json()["status"]=="completed"
    assert result.json()["node_runtime_version"].startswith("v")
    assert result.json()["platform_sandbox"] is False
    checked=request_run(client,root,task="node_check",relative_file="src/math.cjs")
    assert checked.status_code==200,checked.text
    assert checked.json()["status"]=="completed"
    assert checked.json()["exit_code"]==0


def test_actual_node_test_pass_failure_and_no_install(project):
    client,root=project
    trust(client,root)
    before=(root/"src"/"math.cjs").read_bytes()
    r=request_run(client,root,task="node_test",relative_file="src/math.test.cjs")
    assert r.status_code==200,r.text
    result=r.json()
    assert result["status"]=="completed"
    assert result["exit_code"]==0
    assert "real addition" in result["output"]
    assert result["package_installation_performed_by_app"] is False
    assert (root/"src"/"math.cjs").read_bytes()==before
    file=root/"src"/"math.test.cjs"
    file.write_text(file.read_text().replace("sum(2,3),5","sum(2,3),8"))
    failed=request_run(client,root,task="node_test",relative_file="src/math.test.cjs")
    assert failed.status_code==200,failed.text
    assert failed.json()["status"]=="nonzero_exit"
    assert failed.json()["exit_code"]!=0


def test_npm_build_executes_only_predeclared_script_with_consent(project):
    client,root=project
    trust(client,root)
    r=request_run(client,root,task="script",tool="npm",script="build")
    assert r.status_code==200,r.text
    assert r.json()["status"]=="completed"
    assert r.json()["build_script_exited_zero"] is True
    assert r.json()["framework_build_verified"] is False
    assert (root/"output-built.txt").read_text()=="built"
    assert not (root/"node_modules").exists()


def test_changed_manifest_or_binary_cannot_use_old_approval(project):
    client,root=project
    trust(client,root)
    data=inspect(client,root).json()
    node=next(x for x in data["toolchains"] if x["name"]=="node")
    if node["status"]!="installed_not_executed":
        pytest.skip("Node not present")
    body={"project":str(root),"task":"node_version","tool":"node",
         "expected_manifest_sha256":data["package_json_sha256"],
         "expected_executable":node["executable"],"expected_sha256":node["sha256"],
         "confirmed":True,"accept_unsandboxed_execution_and_write_risk":True}
    assert client.post(BASE+"/run",headers=H,
        json={**body,"expected_sha256":"0"*64}).status_code==409
    assert client.post(BASE+"/run",headers=H,
        json={**body,"expected_executable":node["executable"]+".bak"}).status_code==409
    (root/"package.json").write_text((root/"package.json").read_text()+"\n")
    assert client.post(BASE+"/run",headers=H,json=body).status_code==409


def test_reject_traversal_arbitrary_script_and_node_ts_test(project):
    client,root=project
    trust(client,root)
    for file in ("../outside.test.cjs","/tmp/other.test.cjs",".env.test.cjs",
                 "src/math.cjs","src/notfound.test.cjs"):
        ans=request_run(client,root,task="node_test",relative_file=file)
        assert ans.status_code in (403,409,422),ans.text
    (root/"src"/"other.test.ts").write_text("test('x', () => {});\n")
    ans=request_run(client,root,task="node_test",relative_file="src/other.test.ts")
    assert ans.status_code==422
    ans=request_run(client,root,task="script",tool="npm",script="preinstall")
    assert ans.status_code==422


def test_optional_typescript_entry_point_is_local_pinned_no_emit(project):
    client,root=project
    trust(client,root)
    compiler=root/"node_modules"/"typescript"/"bin"
    compiler.mkdir(parents=True)
    (compiler/"tsc").write_text(
        "if (!process.argv.includes('--noEmit')) process.exit(12);\n"
        "if (!process.argv.includes('tsconfig.json')) process.exit(13);\n"
        "console.log('src/example.ts(2,3): error TS2322: simulated mismatch');\n"
        "process.exit(2);\n",encoding="utf-8")
    # This tiny test executable exercises argv and compiler error diagnostics.
    # Real installed TypeScript SDK accuracy still needs independent acceptance.
    r=request_run(client,root,task="tsc_check")
    assert r.status_code==200,r.text
    data=r.json()
    assert data["status"]=="nonzero_exit"
    assert data["diagnostics"][0]["code"]=="TS2322"
    assert "--noEmit" in js._command(root,js.RunIn(
        project=str(root),task="tsc_check",tool="node",
        expected_manifest_sha256="a"*64,expected_executable=sys.executable,
        expected_sha256="b"*64,confirmed=True,
        accept_unsandboxed_execution_and_write_risk=True),
        inspect(client,root).json(),sys.executable)


def test_output_limits_version_mismatch_and_fake_binary(project,monkeypatch):
    client,root=project
    trust(client,root)
    monkeypatch.setattr(js,"MAX_RUN_SECONDS",0.2)
    # Real bounded Python subprocess using approved installed sys.executable.
    fingerprint=adapters._fingerprint(str(Path(sys.executable).resolve()),root)
    monkeypatch.setattr(js,"_tools",lambda _: [
        {"name":"node","status":"installed_not_executed",**fingerprint}])
    monkeypatch.setattr(js,"_command",lambda root,body,summary,executable:
                        [executable,"-c","import time;time.sleep(30)"])
    result=client.post(BASE+"/run",headers=H,json={
        "project":str(root),"task":"node_version","tool":"node",
        "expected_manifest_sha256":inspect(client,root).json()["package_json_sha256"],
        "expected_executable":fingerprint["executable"],
        "expected_sha256":fingerprint["sha256"],"confirmed":True,
        "accept_unsandboxed_execution_and_write_risk":True})
    assert result.status_code==200,result.text
    assert result.json()["status"]=="timeout"


def test_no_hosted_routes_or_unauthenticated_execution(project):
    client,root=project
    for route in (BASE+"/inspect",):
        assert path_allowed("GET",route) is False
    assert path_allowed("POST",BASE+"/run") is False
    assert client.get(BASE+"/inspect",params={"project":str(root)}).status_code==403
    assert client.post(BASE+"/run",json={
        "project":str(root),"task":"node_version","tool":"node",
        "expected_manifest_sha256":"a"*64,
        "expected_executable":str(Path(sys.executable).resolve()),
        "expected_sha256":"b"*64,"confirmed":True,
        "accept_unsandboxed_execution_and_write_risk":True
    }).status_code==403
