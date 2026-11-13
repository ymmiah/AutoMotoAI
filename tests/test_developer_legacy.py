"""V32 legacy language evidence, consent, source preservation and real compilers."""
import hashlib
import os
from pathlib import Path
import shutil
import sys

import pytest
from fastapi.testclient import TestClient

from automoto import developer_legacy as legacy
from automoto import sandbox, server

BASE="/api/developer/studio/legacy"
AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}
SAMPLES=Path(__file__).parent/"fixtures"/"v32-legacy"

@pytest.fixture
def project(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE",str(tmp_path/"workspace"))
    monkeypatch.setenv("AUTOMOTO_RATE_LIMIT","10000")
    monkeypatch.delenv("AUTOMOTO_MODE",raising=False)
    root=sandbox.default_root()/"v32-legacy"
    shutil.copytree(SAMPLES,root)
    return TestClient(server.app),root

def inspect(client,root):
    return client.get(BASE+"/inspect",params={"project":str(root)},headers=AUTH)

def trust(client,root):
    response=client.post("/api/developer/studio/trust",headers=AUTH,
                         json={"project":str(root),"trusted":True,"confirmed":True})
    assert response.status_code==200,response.text

def original(root):
    return {p.relative_to(root).as_posix():p.read_bytes()
            for p in root.rglob("*") if p.is_file()}

def payload(client,root,task,tool):
    data=inspect(client,root).json()
    entry=next(t for t in data["toolchains"]
               if t["name"]==tool and t["status"]=="installed_not_executed")
    return {"project":str(root),"task":task,"tool":tool,
            "expected_inventory_sha256":data["inventory_sha256"],
            "expected_toolchain_sha256":data["toolchain_sha256"],
            "expected_executable":entry["executable"],
            "expected_sha256":entry["sha256"],
            "confirmed":True,"accept_unsandboxed_compiler_and_network_risk":True}

def test_inert_seven_source_types_and_manifests(project):
    client,root=project
    before=original(root)
    response=inspect(client,root)
    assert response.status_code==200,response.text
    data=response.json()
    assert data["language_counts"]=={
        "fortran":1,"cobol":1,"ada":1,"pascal":1,
        "assembly":1,"visual_basic":1,"vbscript":1}
    assert {"fpm.toml","alire.toml","legacy.gpr","legacy.vbproj","Makefile"}<=set(data["manifests"])
    assert all(not m["evaluated"] for m in data["manifests"].values())
    assert len(data["files"])==7
    assert all(not f["executed"] for f in data["files"])
    assert sum(f["canonical_fixture"] for f in data["files"])==5
    assert data["source_executed"] is False
    assert data["packages_installed"] is False
    assert data["deployment_started"] is False
    assert data["central_agent_studio"]=="developer"
    assert before==original(root)

def test_unsafe_manifest_not_evaluated(project,tmp_path):
    client,root=project
    danger=tmp_path/"unsafe-output"
    (root/"Makefile").write_text("all:\n\ttouch "+str(danger)+"\n")
    before=original(root)
    response=inspect(client,root)
    assert response.status_code==200,response.text
    assert not danger.exists()
    assert before==original(root)

def test_source_and_manifest_drift(project):
    client,root=project
    first=inspect(client,root).json()["inventory_sha256"]
    (root/"test/v32_fixture.f90").write_text("program changed\nend program\n")
    second=inspect(client,root).json()["inventory_sha256"]
    assert first!=second
    (root/"alire.toml").write_text('name = "changed"\n')
    assert inspect(client,root).json()["inventory_sha256"]!=second

@pytest.mark.parametrize("name",["fpm.toml","alire.toml","legacy.gpr","legacy.vbproj",
    "Makefile","test/v32_fixture.f90","test/v32_fixture.cob","test/v32_fixture.adb",
    "test/v32_fixture.pas","test/v32_fixture.asm"])
def test_linked_control_files_denied(project,tmp_path,name):
    client,root=project
    path=root/name
    path.unlink()
    outside=tmp_path/"outside"
    outside.write_text("external")
    try:path.symlink_to(outside)
    except (OSError,NotImplementedError):pytest.skip("Symlinks unavailable")
    assert inspect(client,root).status_code==403

def test_auth_hosted_mode(project,monkeypatch):
    client,root=project
    assert client.get(BASE+"/inspect",params={"project":str(root)}).status_code in (401,403)
    monkeypatch.setenv("AUTOMOTO_MODE","multiuser")
    assert inspect(client,root).status_code in (401,403,404)

@pytest.mark.parametrize("task,tool,args",[
    ("fortran_compile","gfortran",["-c","test/v32_fixture.f90","-o","v32.o"]),
    ("cobol_compile","cobc",["-c","test/v32_fixture.cob","-o","v32.o"]),
    ("ada_compile","gnatmake",["-c","test/v32_fixture.adb"]),
    ("pascal_compile","fpc",["-Cn","test/v32_fixture.pas"]),
    ("assembly_compile","nasm",["-f","elf64","test/v32_fixture.asm","-o","v32.o"]),
])
def test_fixed_compiler_args(project,task,tool,args):
    client,root=project
    data=inspect(client,root).json()
    assert legacy._command(task,tool,"/trusted/compiler",data)==["/trusted/compiler",*args]
    with pytest.raises(Exception):
        legacy._command(task,"unrelated","/trusted/compiler",data)

def test_approval_trust_drift_no_arbitrary_command(project,monkeypatch):
    client,root=project
    executable=str(Path(sys.executable).resolve())
    sha=hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    monkeypatch.setattr(legacy,"_tools",lambda _root:(
        [{"name":"gfortran","status":"installed_not_executed",
          "executable":executable,"sha256":sha}],"a"*64))
    body=payload(client,root,"fortran_compile","gfortran")
    assert client.post(BASE+"/compile",headers=AUTH,json=body).status_code==403
    trust(client,root)
    calls=[]
    def runner(cwd,command,env,timeout):
        assert (cwd/"test/v32_fixture.f90").is_file()
        calls.append(command)
        (cwd/"v32.o").write_bytes(b"mock-object")
        return {"status":"completed","exit_code":0,"output":"","elapsed_ms":1}
    monkeypatch.setattr(legacy.native,"_execute",runner)
    response=client.post(BASE+"/compile",headers=AUTH,json=body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result["status"]=="completed"
    assert result["generated_artifacts"][0]["name"]=="v32.o"
    assert result["artifacts_deleted_after_compile"]
    assert result["unsandboxed_compiler"]
    assert not result["deployment_started"]
    assert calls==[[executable,"-c","test/v32_fixture.f90","-o","v32.o"]]
    for key in ("expected_inventory_sha256","expected_toolchain_sha256","expected_sha256"):
        assert client.post(BASE+"/compile",headers=AUTH,
                           json={**body,key:"0"*64}).status_code==409
    for invalid in ({"confirmed":False},
                    {"accept_unsandboxed_compiler_and_network_risk":False},
                    {"task":"arbitrary"},{"args":["--run"]}):
        assert client.post(BASE+"/compile",headers=AUTH,
                           json={**body,**invalid}).status_code==422
    (root/"Makefile").write_text("all:\n\t@echo changed\n")
    assert client.post(BASE+"/compile",headers=AUTH,json=body).status_code==409
    assert len(calls)==1

@pytest.mark.parametrize("task,tool",[
    ("fortran_compile","gfortran"),("cobol_compile","cobc"),
    ("ada_compile","gnatmake"),("pascal_compile","fpc"),
    ("assembly_compile","nasm")])
def test_real_compiler_disposable_linux(project,task,tool):
    if os.getenv("AUTOMOTO_V32_REAL_TOOL_TESTS")!="1":
        pytest.skip("Real compiler tests require disposable Linux CI")
    client,root=project
    trust(client,root)
    before=original(root)
    body=payload(client,root,task,tool)
    response=client.post(BASE+"/compile",headers=AUTH,json=body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result["status"]=="completed",result
    assert result["exit_code"]==0,result
    assert result["generated_artifacts"],result
    assert result["artifacts_deleted_after_compile"]
    assert before==original(root)
