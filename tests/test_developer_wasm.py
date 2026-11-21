"""V33 WebAssembly evidence is inert and bounded."""
import hashlib
from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient
from automoto import developer_wasm, sandbox, server

AUTH={"X-AutoMoto-Token":server.SESSION_TOKEN}
URL="/api/developer/studio/wasm/inspect"

@pytest.fixture
def project(tmp_path,monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME",str(tmp_path/"home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE",str(tmp_path/"workspace"))
    root=sandbox.default_root()/"v33-wasm"
    root.mkdir(parents=True)
    (root/"main.wat").write_text('(module (func (export "answer") (result i32) i32.const 42))')
    (root/"interface.wit").write_text("package automoto:v33;\nworld demo { export answer: func() -> u32; }")
    (root/"module.wasm").write_bytes(b"\0asm\x01\x00\x00\x00")
    (root/"component.wasm").write_bytes(b"\0asm\x0d\x00\x00\x00")
    (root/"broken.wasm").write_bytes(b"notwasm")
    (root/"wit.toml").write_text('name = "v33"\n')
    return TestClient(server.app),root

def inspect(client,root):
    return client.get(URL,params={"project":str(root)},headers=AUTH)

def test_static_evidence_and_no_execution(project):
    client,root=project
    before={p.name:p.read_bytes() for p in root.iterdir()}
    response=inspect(client,root)
    assert response.status_code==200,response.text
    data=response.json()
    assert len(data["files"])==5
    assert data["manifests"][0]["evaluated"] is False
    assert data["runtime_started"] is False
    assert data["build_started"] is False
    assert data["wasi_permissions_granted"] is False
    assert data["deployment_started"] is False
    assert data["central_agent_studio"]=="developer"
    kinds={x["path"]:x for x in data["files"]}
    assert kinds["module.wasm"]["classification"]=="core_module"
    assert kinds["component.wasm"]["classification"]=="component_candidate"
    assert kinds["broken.wasm"]["valid_magic"] is False
    assert kinds["main.wat"]["kind"]=="wat"
    assert kinds["interface.wit"]["kind"]=="wit"
    assert all(f["executed"] is False for f in data["files"])
    assert before=={p.name:p.read_bytes() for p in root.iterdir()}

def test_inventory_drift(project):
    client,root=project
    before=inspect(client,root).json()["inventory_sha256"]
    (root/"main.wat").write_text("(module)")
    assert inspect(client,root).json()["inventory_sha256"]!=before

def test_linked_manifest_refused(project,tmp_path):
    client,root=project
    (root/"wit.toml").unlink()
    target=tmp_path/"outside"
    target.write_text("outside")
    try:(root/"wit.toml").symlink_to(target)
    except (OSError,NotImplementedError):pytest.skip("symlinks unavailable")
    assert inspect(client,root).status_code==403

def test_oversized_binary_refused(project):
    client,root=project
    (root/"module.wasm").write_bytes(b"\0asm\x01\x00\x00\x00"+b"x"*(developer_wasm.MAX_BINARY))
    assert inspect(client,root).status_code==413

def test_requires_session(project):
    client,root=project
    assert client.get(URL,params={"project":str(root)}).status_code in (401,403)
