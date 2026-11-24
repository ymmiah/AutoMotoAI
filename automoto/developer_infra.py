"""Developer Studio V36: infrastructure and configuration files, checked safely.

Covers Terraform/OpenTofu HCL, Nix, Bicep, CUE, Dockerfiles, Kubernetes YAML and
shaders (GLSL, HLSL, WGSL, Metal). Inspection is pure Python: it reads bounded
files and reports problems with line numbers. Nothing is planned, applied,
deployed, built, pushed or sent to a cluster or cloud.

An optional, approved double-check runs one fixed, offline validator command
(for example ``terraform fmt -check``) against a SHA-checked copy of ONE file in
a temporary folder, with a scrubbed environment and an empty home folder, so no
cloud credentials, kube config or provider plugins are visible. ``terraform
plan/apply/init``, ``kubectl``, ``docker build`` and ``nix build`` are never run.
Validator processes are NOT OS-sandboxed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_adapters as adapters
from automoto import developer_index as index
from automoto import developer_native as native
from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/infra", tags=["developer-infra"])
VERSION = "1.0.0"
LOCK = threading.Lock()
MAX_FILES = 200
MAX_FILE = 256 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_FINDINGS = 40
TIMEOUT = 60
LABELS = {
    "terraform": "Terraform / OpenTofu", "nix": "Nix", "bicep": "Bicep", "cue": "CUE",
    "dockerfile": "Dockerfile", "kubernetes": "Kubernetes YAML", "glsl": "GLSL shader",
    "hlsl": "HLSL shader", "wgsl": "WGSL shader", "metal": "Metal shader",
    "tfstate": "Terraform state file",
}
SHADER_STAGES = {".vert", ".frag", ".comp", ".geom", ".tesc", ".tese"}
SUFFIXES = {
    ".tf": "terraform", ".tfvars": "terraform", ".nix": "nix", ".bicep": "bicep",
    ".bicepparam": "bicep", ".cue": "cue", ".dockerfile": "dockerfile",
    ".glsl": "glsl", **{s: "glsl" for s in SHADER_STAGES},
    ".hlsl": "hlsl", ".fx": "hlsl", ".wgsl": "wgsl", ".metal": "metal",
    ".yaml": "yaml", ".yml": "yaml",
}
# Fixed, offline validator commands. "{file}" is the staged copy's name.
VALIDATORS = {
    "terraform": {"kind": "terraform", "label": "Terraform format and syntax check",
                  "args": ["fmt", "-check", "-diff", "-no-color", "{file}"],
                  "install": {"macos": "brew install terraform", "linux": "https://developer.hashicorp.com/terraform/install",
                              "windows": "winget install --id Hashicorp.Terraform -e"}},
    "tofu": {"kind": "terraform", "label": "OpenTofu format and syntax check",
             "args": ["fmt", "-check", "-diff", "-no-color", "{file}"],
             "install": {"macos": "brew install opentofu", "linux": "https://opentofu.org/docs/intro/install/",
                         "windows": "https://opentofu.org/docs/intro/install/"}},
    "nix-instantiate": {"kind": "nix", "label": "Nix parse check (no evaluation, no build)",
                        "args": ["--parse", "{file}"],
                        "install": {"macos": "https://nixos.org/download/", "linux": "https://nixos.org/download/",
                                    "windows": "Use WSL, then https://nixos.org/download/"}},
    "bicep": {"kind": "bicep", "label": "Bicep compile check (local only)",
              "args": ["build", "--stdout", "{file}"],
              "install": {"macos": "brew install azure/bicep/bicep",
                          "linux": "https://learn.microsoft.com/azure/azure-resource-manager/bicep/install",
                          "windows": "winget install -e --id Microsoft.Bicep"}},
    "cue": {"kind": "cue", "label": "CUE vet", "args": ["vet", "{file}"],
            "install": {"macos": "brew install cue-lang/tap/cue", "linux": "https://cuelang.org/docs/introduction/installation/",
                        "windows": "https://cuelang.org/docs/introduction/installation/"}},
    "hadolint": {"kind": "dockerfile", "label": "Hadolint Dockerfile lint", "args": ["--no-color", "{file}"],
                 "install": {"macos": "brew install hadolint", "linux": "https://github.com/hadolint/hadolint/releases",
                             "windows": "https://github.com/hadolint/hadolint/releases"}},
    "glslangValidator": {"kind": "glsl", "label": "Khronos GLSL reference validator", "args": ["{file}"],
                         "install": {"macos": "brew install glslang", "linux": "sudo apt install glslang-tools",
                                     "windows": "https://github.com/KhronosGroup/glslang/releases"}},
    "naga": {"kind": "wgsl", "label": "naga WGSL validator", "args": ["{file}"],
             "install": {"macos": "cargo install naga-cli", "linux": "cargo install naga-cli",
                         "windows": "cargo install naga-cli"}},
}
NEVER_RUN = ("terraform init/plan/apply/destroy", "tofu init/plan/apply", "kubectl", "helm",
             "docker build/run/push", "nix build/develop/run", "az deployment", "bicep publish")
SECRET_NAME = r"(?:[A-Za-z_][\w-]*?)?(?:password|passwd|secret|token|api_?key|access_?key|private_?key|client_?secret|connection_?string)[\w-]*"
SECRET_ASSIGN = re.compile(r"(?im)^\s*\"?(" + SECRET_NAME + r")\"?\s*[=:]\s*[\"']([^\"'$\n{}]{4,})[\"']")
SECRET_ENV = re.compile(r"(?i)^(" + SECRET_NAME + r")\s*=\s*(\S{4,})")
PLACEHOLDER = re.compile(r"(?i)^(?:changeme|change-me|example|placeholder|xxx+|\*+|todo|none|null|<[^>]*>)$")


class ValidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    path: str = Field(min_length=1, max_length=1024)
    validator: Literal["terraform", "tofu", "nix-instantiate", "bicep", "cue", "hadolint",
                       "glslangValidator", "naga"]
    expected_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_executable: str = Field(min_length=1, max_length=2048)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]
    accept_unsandboxed_validator: Literal[True]


def _finding(fid: str, severity: str, line: int | None, message: str, fix: str) -> dict:
    return {"id": fid, "severity": severity, "line": line, "message": message, "fix": fix}


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _read(root: Path, relative: str) -> tuple[str, bytes, str]:
    path = studio._path(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode):
                raise HTTPException(403, "Only regular files can be checked.")
            if meta.st_size > MAX_FILE:
                raise HTTPException(413, "A config file is larger than the inspection limit.")
            raw = stream.read(MAX_FILE + 1)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(403, "A config file cannot be read safely.") from exc
    if len(raw) > MAX_FILE:
        raise HTTPException(413, "A config file is larger than the inspection limit.")
    return raw.decode("utf-8", errors="replace"), raw, hashlib.sha256(raw).hexdigest()


def _kind(name: str) -> str | None:
    leaf = name.rsplit("/", 1)[-1]
    low = leaf.lower()
    if low in ("dockerfile", "containerfile") or low.startswith(("dockerfile.", "containerfile.")):
        return "dockerfile"
    if low.endswith((".tfstate", ".tfstate.backup")):
        return "tfstate"
    return SUFFIXES.get(Path(low).suffix)


# ------------------------------------------------------------------ bracket scanner
def _balance(text: str, *, hash_comments: bool = False, single_quote: bool = False,
             nix_strings: bool = False, heredocs: bool = False) -> dict | None:
    """Return the first unbalanced bracket, ignoring comments and strings (heuristic)."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[tuple[str, int]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        two = text[i:i + 2]
        if two == "//" or (hash_comments and ch == "#"):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if two == "/*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if heredocs and text.startswith("<<", i):
            match = re.match(r"<<-?([A-Za-z_]\w*)[ \t]*\n", text[i:i + 80])
            if match:
                tail = re.compile(r"(?m)^[ \t]*" + re.escape(match.group(1)) + r"[ \t]*$")
                found = tail.search(text, i + match.end())
                i = n if not found else found.end()
                continue
        if nix_strings and two == "''":
            end = text.find("''", i + 2)
            while end >= 0 and text[end + 2:end + 3] in ("'", "$", "\\"):
                end = text.find("''", end + 3)
            i = n if end < 0 else end + 2
            continue
        if ch == '"' or (single_quote and ch == "'"):
            if text.startswith(ch * 3, i):
                end = text.find(ch * 3, i + 3)
                i = n if end < 0 else end + 3
                continue
            j = i + 1
            while j < n and text[j] != ch and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if ch in "([{":
            stack.append((ch, i))
        elif ch in pairs:
            if not stack or stack[-1][0] != pairs[ch]:
                return {"line": _line(text, i), "message": f"Unexpected '{ch}'."}
            stack.pop()
        i += 1
    if stack:
        opener, at = stack[-1]
        return {"line": _line(text, at), "message": f"'{opener}' is never closed."}
    return None


def _secret_literals(text: str, out: list[dict], fid: str) -> None:
    for match in SECRET_ASSIGN.finditer(text[:MAX_FILE]):
        if PLACEHOLDER.match(match.group(2).strip()):
            continue
        out.append(_finding(fid, "problem", _line(text, match.start()),
                            f"'{match.group(1)}' looks like a password or key written straight into the file. The value is hidden here.",
                            "Move it to a secret store or a variable marked sensitive, and rotate it if it was ever shared."))


# ------------------------------------------------------------------ per-kind checks
def _check_terraform(text: str) -> list[dict]:
    out: list[dict] = []
    bad = _balance(text, hash_comments=True, heredocs=True)
    if bad:
        out.append(_finding("T001", "problem", bad["line"], "Brackets don't match: " + bad["message"],
                            "Check the block that starts near this line."))
    for match in re.finditer(r"0\.0\.0\.0/0|::/0", text):
        out.append(_finding("T002", "warning", _line(text, match.start()),
                            "This opens access to the whole internet.",
                            "Limit it to the addresses that really need access."))
    _secret_literals(text, out, "T003")
    for match in re.finditer(r"provisioner\s+\"(local-exec|remote-exec)\"", text):
        out.append(_finding("T005", "warning", _line(text, match.start()),
                            f"A {match.group(1)} provisioner runs commands when someone applies this.",
                            "Prefer built-in resources; review the command carefully."))
    return out


def _check_nix(text: str) -> list[dict]:
    out: list[dict] = []
    bad = _balance(text, hash_comments=True, nix_strings=True)
    if bad:
        out.append(_finding("N001", "problem", bad["line"], "Brackets don't match: " + bad["message"],
                            "Check the expression that starts near this line."))
    for match in re.finditer(r"\b(?:builtins\.)?(fetchurl|fetchTarball|fetchGit|fetchFromGitHub|fetchzip)\b", text):
        window = text[match.end():match.end() + 400]
        if not re.search(r"\b(?:sha256|hash|narHash|rev)\s*=", window):
            out.append(_finding("N002", "warning", _line(text, match.start()),
                                f"{match.group(1)} without a pinned hash can download something different next time.",
                                "Add a sha256/hash (or rev) so builds are reproducible."))
    return out


def _check_bicep(text: str) -> list[dict]:
    out: list[dict] = []
    bad = _balance(text, single_quote=True)
    if bad:
        out.append(_finding("B001", "problem", bad["line"], "Brackets don't match: " + bad["message"],
                            "Check the block that starts near this line."))
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        match = re.match(r"\s*param\s+(" + SECRET_NAME + r")\s+string\b", line, re.I)
        if match and not any("@secure()" in prev for prev in lines[max(0, number - 4):number - 1]):
            out.append(_finding("B002", "warning", number,
                                f"Parameter '{match.group(1)}' looks secret but isn't marked @secure().",
                                "Add @secure() on the line above so it isn't logged or shown."))
    for match in re.finditer(r"'(?:br|ts):[^']{1,200}'", text):
        out.append(_finding("B003", "tip", _line(text, match.start()),
                            "This module comes from a registry, so checking it would need a download.",
                            "AutoMoto's Bicep double-check is skipped for files like this."))
    _secret_literals(text, out, "B004")
    return out


def _check_cue(text: str) -> list[dict]:
    out: list[dict] = []
    bad = _balance(text, single_quote=True)
    if bad:
        out.append(_finding("C001", "problem", bad["line"], "Brackets don't match: " + bad["message"],
                            "Check the value that starts near this line."))
    if not re.search(r"(?m)^\s*package\s+\w+", text):
        out.append(_finding("C002", "tip", 1, "No package line.", "Add 'package <name>' at the top so files combine predictably."))
    _secret_literals(text, out, "C003")
    return out


def _check_docker(text: str) -> list[dict]:
    out: list[dict] = []
    logical: list[tuple[int, str]] = []
    buffer, start = "", 0
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not buffer and (not stripped or stripped.startswith("#")):
            continue
        if not buffer:
            start = number
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        logical.append((start, buffer + stripped))
        buffer = ""
    if buffer:
        logical.append((start, buffer))
    known = {"FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV", "ADD", "COPY",
             "ENTRYPOINT", "VOLUME", "USER", "WORKDIR", "ARG", "ONBUILD", "STOPSIGNAL",
             "HEALTHCHECK", "SHELL"}
    stages: set[str] = set()
    user_in_stage = False
    seen_from = False
    for number, line in logical:
        word, _, rest = line.partition(" ")
        word = word.upper()
        if word not in known:
            out.append(_finding("D000", "problem", number, f"'{word}' is not a Dockerfile instruction.",
                                "Check the spelling, or a missing '\\' on the line before."))
            continue
        if not seen_from and word not in ("FROM", "ARG"):
            out.append(_finding("D007", "problem", number, "The first instruction must be FROM (ARG may come before it).",
                                "Start the file with FROM <image>:<version>."))
            seen_from = True
        if word == "FROM":
            seen_from = True
            user_in_stage = False
            parts = [p for p in rest.split() if not p.startswith("--")]
            image = parts[0] if parts else ""
            if len(parts) >= 3 and parts[1].lower() == "as":
                stages.add(parts[2].lower())
            base = image.split("@")[0]
            if image and image.lower() != "scratch" and image.lower() not in stages and "$" not in image:
                if "@" not in image and (":" not in base.rsplit("/", 1)[-1] or base.endswith(":latest")):
                    out.append(_finding("D001", "warning", number,
                                        f"'{image}' isn't pinned to a version, so builds can change without warning.",
                                        "Use a fixed tag such as python:3.13-slim, or a digest."))
        elif word == "USER":
            user_in_stage = rest.strip() not in ("root", "0", "0:0")
        elif word == "ADD" and re.search(r"https?://", rest):
            out.append(_finding("D003", "warning", number, "ADD downloads a file without checking it.",
                                "Download with a checksum check in RUN, or use ADD --checksum=sha256:…"))
        elif word == "RUN" and re.search(r"(?:curl|wget)[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b", rest):
            out.append(_finding("D004", "warning", number, "A script is downloaded and run in one go.",
                                "Download it, check its checksum, then run it."))
        elif word in ("ENV", "ARG"):
            for token in re.split(r"\s+", rest.strip()):
                match = SECRET_ENV.match(token)
                if match and not PLACEHOLDER.match(match.group(2).strip("\"'")) and "$" not in match.group(2):
                    out.append(_finding("D005", "problem", number,
                                        f"'{match.group(1)}' puts a secret inside the image, where anyone with the image can read it. The value is hidden here.",
                                        "Pass it at run time, or use a build secret (RUN --mount=type=secret)."))
    if seen_from and not user_in_stage:
        out.append(_finding("D002", "warning", None, "The final image runs as the root user.",
                            "Add a USER line with a non-root user near the end."))
    return out


def _yaml_get(node, key):
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            if isinstance(k, yaml.ScalarNode) and k.value == key:
                return v
    return None


def _yaml_true(node) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.value.lower() == "true"


def _pod_specs(doc):
    spec = _yaml_get(doc, "spec")
    for path in ((), ("template", "spec"), ("jobTemplate", "spec", "template", "spec")):
        node = spec
        for key in path:
            node = _yaml_get(node, key)
        if node is not None and (_yaml_get(node, "containers") is not None):
            yield node


def _check_kubernetes(text: str) -> tuple[list[dict], bool]:
    """Returns (findings, is_kubernetes)."""
    if not re.search(r"(?m)^apiVersion:\s*\S", text) or not re.search(r"(?m)^kind:\s*\S", text):
        return [], False
    out: list[dict] = []
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        out.append(_finding("K000", "problem", (mark.line + 1) if mark else None,
                            "This YAML can't be read: " + str(getattr(exc, "problem", "") or "syntax error"),
                            "Check indentation (spaces, not tabs) near this line."))
        return out, True
    for doc in docs[:50]:
        if not isinstance(doc, yaml.MappingNode):
            continue
        kind = _yaml_get(doc, "kind")
        api = _yaml_get(doc, "apiVersion")
        if kind is None or api is None:
            continue
        line = doc.start_mark.line + 1
        meta = _yaml_get(doc, "metadata")
        if _yaml_get(meta, "name") is None and _yaml_get(meta, "generateName") is None:
            out.append(_finding("K001", "problem", line, f"{kind.value} has no metadata.name.",
                                "Give every object a name."))
        if isinstance(kind, yaml.ScalarNode) and kind.value == "Secret":
            if _yaml_get(doc, "data") is not None or _yaml_get(doc, "stringData") is not None:
                out.append(_finding("K008", "warning", line,
                                    "A Secret with its values is stored in this file. Values are hidden here.",
                                    "Keep real secrets out of Git (use a secret manager or sealed secrets)."))
        for pod in _pod_specs(doc):
            for flag in ("hostNetwork", "hostPID", "hostIPC"):
                node = _yaml_get(pod, flag)
                if _yaml_true(node):
                    out.append(_finding("K003", "warning", node.start_mark.line + 1,
                                        f"{flag}: true shares the machine's {flag[4:]} with this pod.",
                                        "Remove it unless the pod really needs it."))
            volumes = _yaml_get(pod, "volumes")
            if isinstance(volumes, yaml.SequenceNode):
                for vol in volumes.value[:100]:
                    host_path = _yaml_get(vol, "hostPath")
                    if host_path is not None:
                        out.append(_finding("K004", "warning", host_path.start_mark.line + 1,
                                            "hostPath mounts a folder from the machine into the pod.",
                                            "Use a PersistentVolumeClaim or emptyDir instead."))
            for group in ("containers", "initContainers"):
                items = _yaml_get(pod, group)
                if not isinstance(items, yaml.SequenceNode):
                    continue
                for container in items.value[:50]:
                    name_node = _yaml_get(container, "name")
                    cname = name_node.value if isinstance(name_node, yaml.ScalarNode) else "container"
                    cline = container.start_mark.line + 1
                    image = _yaml_get(container, "image")
                    if isinstance(image, yaml.ScalarNode):
                        ref = image.value
                        leaf = ref.split("@")[0].rsplit("/", 1)[-1]
                        if "@" not in ref and (":" not in leaf or leaf.endswith(":latest")):
                            out.append(_finding("K005", "warning", image.start_mark.line + 1,
                                                f"Container '{cname}' uses an image without a fixed version.",
                                                "Pin a tag like nginx:1.27 or a digest."))
                    security = _yaml_get(container, "securityContext")
                    privileged = _yaml_get(security, "privileged")
                    if _yaml_true(privileged):
                        out.append(_finding("K002", "problem", privileged.start_mark.line + 1,
                                            f"Container '{cname}' is privileged: it can control the whole machine.",
                                            "Remove privileged: true and add only the capabilities it needs."))
                    escalation = _yaml_get(security, "allowPrivilegeEscalation")
                    if not (isinstance(escalation, yaml.ScalarNode) and escalation.value.lower() == "false"):
                        out.append(_finding("K007", "tip", cline,
                                            f"Container '{cname}' doesn't set allowPrivilegeEscalation: false.",
                                            "Add it under securityContext, with runAsNonRoot: true."))
                    limits = _yaml_get(_yaml_get(container, "resources"), "limits")
                    if limits is None:
                        out.append(_finding("K006", "tip", cline,
                                            f"Container '{cname}' has no resource limits.",
                                            "Set resources.limits for memory and CPU."))
    return out, True


def _check_shader(kind: str, name: str, text: str) -> list[dict]:
    out: list[dict] = []
    bad = _balance(text)
    if bad:
        out.append(_finding("S001", "problem", bad["line"], "Brackets don't match: " + bad["message"],
                            "Check the function that starts near this line."))
    if kind == "glsl":
        if not re.search(r"(?m)^\s*#\s*version\s+\d+", text):
            out.append(_finding("S002", "warning", 1, "No #version line.",
                                "Add one at the very top, for example #version 450."))
        if Path(name).suffix.lower() in SHADER_STAGES and not re.search(r"\bvoid\s+main\s*\(", text):
            out.append(_finding("S003", "problem", None, "This shader stage has no main() function.",
                                "Add void main() { … }."))
    if kind == "wgsl" and not re.search(r"@(?:vertex|fragment|compute)\b", text):
        out.append(_finding("S004", "tip", None, "No @vertex, @fragment or @compute entry point.",
                            "Fine for a shared library file; otherwise add an entry point."))
    return out


def _check(kind: str, name: str, text: str) -> tuple[str | None, list[dict]]:
    if kind == "terraform":
        return kind, _check_terraform(text)
    if kind == "nix":
        return kind, _check_nix(text)
    if kind == "bicep":
        return kind, _check_bicep(text)
    if kind == "cue":
        return kind, _check_cue(text)
    if kind == "dockerfile":
        return kind, _check_docker(text)
    if kind == "yaml":
        findings, is_k8s = _check_kubernetes(text)
        return ("kubernetes" if is_k8s else None), findings
    if kind in ("glsl", "hlsl", "wgsl", "metal"):
        return kind, _check_shader(kind, name, text)
    return None, []


def _host() -> str:
    return "windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else "linux"


def _validators(root: Path) -> dict:
    host = _host()
    found = {}
    for name, spec in VALIDATORS.items():
        binary = shutil.which(name)
        if not binary:
            item = {"status": "unavailable"}
        elif Path(binary).suffix.lower() in (".cmd", ".bat", ".ps1"):
            item = {"status": "shell_wrapper_blocked"}
        else:
            try:
                item = {"status": "installed_not_executed",
                        **adapters._fingerprint(str(Path(binary).absolute()), root)}
            except HTTPException:
                item = {"status": "untrusted_executable"}
        found[name] = {"name": name, "kind": spec["kind"], "label": spec["label"],
                       "command_preview": " ".join([name, *spec["args"]]).replace("{file}", "<file>"),
                       "install_hint": spec["install"][host], **item}
    return found


def _offered(kind: str, name: str, text: str, validators: dict) -> list[str]:
    names = []
    for vname, spec in validators.items():
        if spec["kind"] != kind or spec["status"] != "installed_not_executed":
            continue
        if vname == "glslangValidator" and Path(name).suffix.lower() not in SHADER_STAGES:
            continue
        if vname in ("terraform", "tofu") and not name.endswith(".tf"):
            continue
        if vname == "bicep" and (re.search(r"'(?:br|ts):", text) or not name.endswith(".bicep")):
            continue
        names.append(vname)
    return names


def _inspect(root: Path) -> dict:
    files, total, incomplete = [], 0, False
    validators = _validators(root)
    digest = hashlib.sha256(b"automoto-v36-infra-inventory\0")
    has_flake = has_lock = has_required_version = False
    terraform_seen = False
    for name, warning in index._walk(root):
        if warning:
            incomplete = True
            continue
        leaf = name.rsplit("/", 1)[-1]
        if leaf == "flake.lock":
            has_lock = True
        kind = _kind(name)
        if not kind:
            continue
        if len(files) >= MAX_FILES:
            incomplete = True
            break
        if kind == "tfstate":
            # State files often contain secrets: flag the file, never read it.
            files.append({"path": name, "kind": "tfstate", "label": LABELS["tfstate"],
                          "sha256": None, "findings": [_finding(
                              "T006", "problem", None,
                              "A Terraform state file is in the project. State files often contain passwords and keys.",
                              "Move state to a remote backend, add *.tfstate to .gitignore, and rotate any exposed secrets.")],
                          "validators": [], "contents_read": False})
            continue
        text, raw, sha = _read(root, name)
        total += len(raw)
        if total > MAX_TOTAL:
            incomplete = True
            break
        real_kind, findings = _check(kind, name, text)
        if not real_kind:
            continue
        if leaf == "flake.nix":
            has_flake = True
        if real_kind == "terraform":
            terraform_seen = True
            if re.search(r"required_version\s*=", text):
                has_required_version = True
        digest.update(name.encode("utf-8") + b"\0" + sha.encode("ascii") + b"\0")
        files.append({"path": name, "kind": real_kind, "label": LABELS[real_kind], "sha256": sha,
                      "bytes": len(raw), "findings": findings[:MAX_FINDINGS],
                      "findings_truncated": len(findings) > MAX_FINDINGS,
                      "validators": _offered(real_kind, name, text, validators),
                      "contents_read": True})
    project_findings = []
    if terraform_seen and not has_required_version:
        project_findings.append(_finding("T004", "tip", None, "No Terraform required_version is set.",
                                         "Add terraform { required_version = \">= 1.6\" } so everyone uses a compatible version."))
    if has_flake and not has_lock:
        project_findings.append(_finding("N003", "tip", None, "flake.nix has no flake.lock next to it.",
                                         "Commit flake.lock so inputs stay pinned."))
    counts = {"problem": 0, "warning": 0, "tip": 0}
    for item in [*files, {"findings": project_findings}]:
        for found in item["findings"]:
            counts[found["severity"]] += 1
    return {
        "schema": VERSION, "files": files, "project_findings": project_findings,
        "counts": counts, "kinds": sorted({f["kind"] for f in files}),
        "validators": list(validators.values()), "inventory_sha256": digest.hexdigest(),
        "scan_incomplete": incomplete,
        "project_trusted": studio._trusted(root, studio._load()),
        "never_run": list(NEVER_RUN),
        "infrastructure_changed": False, "deployment_started": False,
        "cloud_contacted": False, "cluster_contacted": False, "image_built": False,
        "secret_values_returned": False, "network_started": False,
        "central_agent_studio": "developer",
        "limitations": ("Built-in checks are careful pattern and structure checks, not the real "
                        "tools: a clean result does not prove a plan will apply or a pod will start. "
                        "Helm templates, Kustomize overlays and HCL expressions are not rendered. "
                        "Optional double-checks run one offline validator on a copy of one file "
                        "and are not OS-sandboxed."),
    }


def _validate(root: Path, body: ValidateIn) -> dict:
    adapters._trusted(root)
    kind = _kind(body.path)
    if not kind or kind == "tfstate":
        raise HTTPException(422, "This file type has no validator.")
    text, raw, sha = _read(root, body.path)
    if sha != body.expected_file_sha256:
        raise HTTPException(409, "The file changed since you looked. Check again.")
    real_kind, _ = _check(kind, body.path, text)
    validators = _validators(root)
    if body.validator not in _offered(real_kind or "", body.path, text, validators):
        raise HTTPException(409, "That validator isn't available for this file.")
    chosen = validators[body.validator]
    if chosen.get("executable") != body.expected_executable or chosen.get("sha256") != body.expected_sha256:
        raise HTTPException(409, "The validator program changed since you approved it.")
    leaf = Path(body.path).name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", leaf):
        leaf = "config" + Path(body.path).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="automoto-v36-") as directory:
        folder = Path(directory)
        stage = folder / "check"
        stage.mkdir(mode=0o700)
        home = folder / "home"
        home.mkdir(mode=0o700)
        (stage / leaf).write_bytes(raw)
        env = adapters._environment(root)
        env.update({
            "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home), "LOCALAPPDATA": str(home),
            "TMPDIR": str(folder), "TEMP": str(folder), "TMP": str(folder),
            "XDG_CACHE_HOME": str(home / "cache"), "XDG_CONFIG_HOME": str(home / "config"),
            "CHECKPOINT_DISABLE": "1", "TF_IN_AUTOMATION": "1", "TF_INPUT": "0",
            "NIX_PATH": "", "CUE_CACHE_DIR": str(home / "cue"),
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "NO_COLOR": "1", "CI": "true",
        })
        command = [chosen["executable"], *[a.replace("{file}", leaf) for a in VALIDATORS[body.validator]["args"]]]
        again = _validators(root)[body.validator]
        if again.get("sha256") != body.expected_sha256:
            raise HTTPException(409, "The validator program changed while preparing the check.")
        started = time.monotonic()
        output = native._execute(stage, command, env, timeout=TIMEOUT)
    status = output["status"]
    result = ("passed" if status == "completed" else
              "timed_out" if status == "timeout" else
              "needs_formatting" if (body.validator in ("terraform", "tofu") and output["exit_code"] == 3)
              else "problems_found")
    return {
        "path": body.path, "validator": body.validator, "label": chosen["label"],
        "command_preview": chosen["command_preview"].replace("<file>", leaf),
        "result": result, "exit_code": output["exit_code"],
        "output": output["output"][:native.MAX_OUTPUT],
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "file_sha256": sha, "ran_on_temporary_copy": True, "temporary_copy_deleted": True,
        "project_files_modified": False, "infrastructure_changed": False,
        "deployment_started": False, "cloud_credentials_passed": False,
        "external_code_unsandboxed": True, "os_network_isolation": False,
        "central_agent_studio": "developer",
    }


@router.get("/inspect")
def inspect(request: Request, project: str):
    studio._auth(request)
    return _inspect(studio._project(project))


@router.post("/validate")
def validate(request: Request, body: ValidateIn):
    studio._auth(request)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, "A config check is already running.")
    try:
        return _validate(studio._project(body.project), body)
    finally:
        LOCK.release()
