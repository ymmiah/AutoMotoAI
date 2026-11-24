"""V36 infrastructure and configuration: built-in checks, no deployment, approved offline validators."""
import os

import pytest
from fastapi.testclient import TestClient

from automoto import developer_infra as infra
from automoto import sandbox, server

AUTH = {"X-AutoMoto-Token": server.SESSION_TOKEN}
URL = "/api/developer/studio/infra"
REAL = os.environ.get("AUTOMOTO_V36_REAL_TOOL_TESTS") == "1"

TF = '''terraform {
  required_version = ">= 1.6"
}

resource "aws_security_group_rule" "web" {
  cidr_blocks = ["0.0.0.0/0"]
}

variable "db" {
  default = "x"
}

resource "aws_db_instance" "db" {
  password = "SuperSecretValue123"
  provisioner "local-exec" {
    command = "echo hi"
  }
}
'''
DOCKER = '''# syntax=docker/dockerfile:1
FROM python:latest AS build
ENV API_TOKEN=abcd1234secret
ADD https://example.com/tool.tar.gz /tmp/
RUN curl -fsSL https://example.com/install.sh | sh
FROM build
CMD ["python"]
'''
K8S = '''apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  template:
    spec:
      hostNetwork: true
      volumes:
        - name: data
          hostPath:
            path: /var/data
      containers:
        - name: web
          image: nginx
          securityContext:
            privileged: true
---
apiVersion: v1
kind: Secret
metadata:
  name: creds
stringData:
  password: hunter2hunter2
'''
NIX = '''{ pkgs ? import <nixpkgs> {} }:
let src = builtins.fetchTarball "https://example.com/a.tar.gz";
in pkgs.mkShell { buildInputs = [ pkgs.hello ]; }
'''
BICEP = "param adminPassword string\nresource sa 'Microsoft.Storage/storageAccounts@2023-01-01' = {\n  name: 'x'\n"
CUE = 'name: "demo"\nreplicas: 3\n'
GLSL = "#version 450\nlayout(location = 0) out vec4 color;\nvoid main() {\n  color = vec4(1.0);\n}\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMOTO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AUTOMOTO_WORKSPACE", str(tmp_path / "workspace"))
    root = sandbox.default_root() / "v36-infra"
    (root / "k8s").mkdir(parents=True)
    (root / "shaders").mkdir()
    (root / "main.tf").write_text(TF)
    (root / "Dockerfile").write_text(DOCKER)
    (root / "k8s" / "web.yaml").write_text(K8S)
    (root / ".github").mkdir()
    (root / "compose.yaml").write_text("services:\n  web:\n    image: nginx\n")
    (root / "flake.nix").write_text(NIX)
    (root / "main.bicep").write_text(BICEP)
    (root / "app.cue").write_text(CUE)
    (root / "shaders" / "color.frag").write_text(GLSL)
    (root / "shaders" / "blit.wgsl").write_text("fn helper() -> f32 { return 1.0; }\n")
    (root / "terraform.tfstate").write_text('{"secret": "never-read-this"}')
    return TestClient(server.app), root


def inspect(client, root):
    response = client.get(URL + "/inspect", params={"project": str(root)}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def ids(data, path):
    item = next(f for f in data["files"] if f["path"] == path)
    return {f["id"] for f in item["findings"]}


def trust(client, root):
    result = client.post("/api/developer/studio/trust", headers=AUTH,
                         json={"project": str(root), "trusted": True, "confirmed": True})
    assert result.status_code == 200, result.text


def test_never_deploys_or_changes_anything(project):
    client, root = project
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    data = inspect(client, root)
    for flag in ("infrastructure_changed", "deployment_started", "cloud_contacted",
                 "cluster_contacted", "image_built", "secret_values_returned"):
        assert data[flag] is False
    assert "kubectl" in data["never_run"]
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_kinds_and_non_kubernetes_yaml_ignored(project):
    client, root = project
    data = inspect(client, root)
    kinds = {f["path"]: f["kind"] for f in data["files"]}
    assert kinds["main.tf"] == "terraform"
    assert kinds["Dockerfile"] == "dockerfile"
    assert kinds["k8s/web.yaml"] == "kubernetes"
    assert kinds["flake.nix"] == "nix"
    assert kinds["main.bicep"] == "bicep"
    assert kinds["app.cue"] == "cue"
    assert kinds["shaders/color.frag"] == "glsl"
    assert kinds["shaders/blit.wgsl"] == "wgsl"
    assert "compose.yaml" not in kinds


def test_terraform_findings(project):
    client, root = project
    data = inspect(client, root)
    assert {"T002", "T003", "T005"} <= ids(data, "main.tf")
    assert not any(f["id"] == "T004" for f in data["project_findings"])


def test_secret_values_never_returned(project):
    client, root = project
    text = client.get(URL + "/inspect", params={"project": str(root)}, headers=AUTH).text
    for secret in ("SuperSecretValue123", "abcd1234secret", "hunter2hunter2", "never-read-this"):
        assert secret not in text


def test_state_file_flagged_without_reading(project):
    client, root = project
    item = next(f for f in inspect(client, root)["files"] if f["kind"] == "tfstate")
    assert item["contents_read"] is False and item["findings"][0]["id"] == "T006"


def test_dockerfile_findings(project):
    client, root = project
    assert {"D001", "D002", "D003", "D004", "D005"} <= ids(inspect(client, root), "Dockerfile")


def test_dockerfile_clean_and_stage_alias(project):
    client, root = project
    (root / "Dockerfile").write_text("FROM python:3.13-slim AS build\nRUN echo ok\nFROM build\nUSER app\n")
    assert ids(inspect(client, root), "Dockerfile") == set()


def test_kubernetes_findings_with_lines(project):
    client, root = project
    data = inspect(client, root)
    found = {f["id"]: f for f in next(x for x in data["files"] if x["path"] == "k8s/web.yaml")["findings"]}
    assert {"K002", "K003", "K004", "K005", "K006", "K007", "K008"} <= set(found)
    assert found["K002"]["line"] == 17
    assert found["K003"]["line"] == 8


def test_broken_yaml_reports_line(project):
    client, root = project
    (root / "k8s" / "web.yaml").write_text("apiVersion: v1\nkind: Pod\nmetadata:\n  name: [oops\n")
    item = next(f for f in inspect(client, root)["files"] if f["path"] == "k8s/web.yaml")
    assert item["findings"][0]["id"] == "K000" and item["findings"][0]["line"]


def test_recursive_yaml_alias_is_safe(project):
    client, root = project
    (root / "k8s" / "web.yaml").write_text("apiVersion: v1\nkind: Pod\nmetadata: &m\n  name: a\n  self: *m\nspec: {containers: []}\n")
    inspect(client, root)


def test_nix_bicep_cue_shader_findings(project):
    client, root = project
    data = inspect(client, root)
    assert "N002" in ids(data, "flake.nix")
    assert any(f["id"] == "N003" for f in data["project_findings"])
    assert {"B001", "B002"} <= ids(data, "main.bicep")
    assert "C002" in ids(data, "app.cue")
    assert ids(data, "shaders/color.frag") == set()
    assert "S004" in ids(data, "shaders/blit.wgsl")


def test_bracket_scanner_ignores_strings_comments_heredocs():
    text = 'a = "}" # }\n// {\nb = <<EOF\n{{{\nEOF\nc = { d = 1 }\n'
    assert infra._balance(text, hash_comments=True, heredocs=True) is None
    assert infra._balance("x = {\n", hash_comments=True)["line"] == 1
    assert infra._balance("''${ { }''\n{ }", nix_strings=True) is None


def test_missing_validators_reported_with_install_hint(project, monkeypatch):
    client, root = project
    monkeypatch.setattr(infra.shutil, "which", lambda name: None)
    data = inspect(client, root)
    assert all(v["status"] == "unavailable" and v["install_hint"] for v in data["validators"])
    assert all(f["validators"] == [] for f in data["files"])


def test_validate_requires_trust_hash_and_offered_validator(project, tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("shell-script fake validator is POSIX only")
    client, root = project
    fake = tmp_path / "bin" / "hadolint"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\necho "checked $2"; env | grep -q AWS_SECRET && echo LEAK; exit 0\n')
    fake.chmod(0o755)
    monkeypatch.setattr(infra.shutil, "which", lambda name: str(fake) if name == "hadolint" else None)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "should-not-pass")
    data = inspect(client, root)
    item = next(f for f in data["files"] if f["path"] == "Dockerfile")
    assert item["validators"] == ["hadolint"]
    tool = next(v for v in data["validators"] if v["name"] == "hadolint")
    body = {"project": str(root), "path": "Dockerfile", "validator": "hadolint",
            "expected_file_sha256": item["sha256"], "expected_executable": tool["executable"],
            "expected_sha256": tool["sha256"], "confirmed": True, "accept_unsandboxed_validator": True}
    assert client.post(URL + "/validate", json=body, headers=AUTH).status_code == 403
    trust(client, root)
    assert client.post(URL + "/validate", json={**body, "expected_file_sha256": "0" * 64}, headers=AUTH).status_code == 409
    assert client.post(URL + "/validate", json={**body, "path": "main.tf"}, headers=AUTH).status_code == 409
    result = client.post(URL + "/validate", json=body, headers=AUTH)
    assert result.status_code == 200, result.text
    out = result.json()
    assert out["result"] == "passed" and "checked Dockerfile" in out["output"]
    assert "LEAK" not in out["output"]
    assert out["infrastructure_changed"] is False and out["ran_on_temporary_copy"] is True


def test_validate_refuses_state_and_unknown(project):
    client, root = project
    trust(client, root)
    body = {"project": str(root), "path": "terraform.tfstate", "validator": "terraform",
            "expected_file_sha256": "0" * 64, "expected_executable": "/x", "expected_sha256": "0" * 64,
            "confirmed": True, "accept_unsandboxed_validator": True}
    assert client.post(URL + "/validate", json=body, headers=AUTH).status_code == 422
    assert client.post(URL + "/validate", json={**body, "validator": "kubectl"}, headers=AUTH).status_code == 422


def test_bicep_registry_module_not_offered(project, tmp_path, monkeypatch):
    client, root = project
    fake = tmp_path / "bin" / "bicep"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setattr(infra.shutil, "which", lambda name: str(fake) if name == "bicep" else None)
    (root / "main.bicep").write_text("module m 'br:mcr.microsoft.com/bicep/x:1.0' = {\n  name: 'm'\n}\n")
    item = next(f for f in inspect(client, root)["files"] if f["path"] == "main.bicep")
    assert item["validators"] == [] and "B003" in {f["id"] for f in item["findings"]}


def test_requires_session(project):
    client, root = project
    assert client.get(URL + "/inspect", params={"project": str(root)}).status_code in (401, 403)


@pytest.mark.skipif(not REAL, reason="real terraform and glslangValidator run in the V36 CI job")
@pytest.mark.parametrize("path,validator,good", [
    ("main.tf", "terraform", True), ("shaders/color.frag", "glslangValidator", True),
    ("shaders/broken.frag", "glslangValidator", False), ("bad.tf", "terraform", False)])
def test_real_validators(project, path, validator, good):
    client, root = project
    (root / "main.tf").write_text('terraform {\n  required_version = ">= 1.6"\n}\n')
    (root / "bad.tf").write_text('resource "x" "y" {\n  a = \n}\n')
    (root / "shaders" / "broken.frag").write_text("#version 450\nvoid main() {\n  undefined_call();\n}\n")
    trust(client, root)
    data = inspect(client, root)
    item = next(f for f in data["files"] if f["path"] == path)
    tool = next(v for v in data["validators"] if v["name"] == validator)
    assert tool["status"] == "installed_not_executed", tool
    body = {"project": str(root), "path": path, "validator": validator,
            "expected_file_sha256": item["sha256"], "expected_executable": tool["executable"],
            "expected_sha256": tool["sha256"], "confirmed": True, "accept_unsandboxed_validator": True}
    out = client.post(URL + "/validate", json=body, headers=AUTH).json()
    assert (out["result"] == "passed") is good, out
    assert not (root / ".terraform").exists()
