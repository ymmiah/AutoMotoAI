"""Developer Studio V5: evidence-first, read-only language and framework intelligence.

No project content is executed, installed, uploaded, or written. Toolchain probing
only checks executable locations; it does not run a compiler or version command.
All project access is constrained by the existing V1 sandbox.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
from collections import Counter
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from automoto import developer_studio as studio

router = APIRouter(prefix="/api/developer/studio/language", tags=["developer-language"])
REGISTRY_VERSION = "1.0.0"
MAX_MANIFEST = 128 * 1024
MAX_INSPECT = 300
MAX_DEPTH = 2
MAX_TOOLS = 12


def _entry(identifier, extensions=(), filenames=(), shebangs=(), monaco=None, tools=()):
    return {"id": identifier, "name": identifier.replace("-", " ").title(),
            "extensions": list(extensions), "filenames": list(filenames),
            "shebangs": list(shebangs), "monaco": monaco or identifier,
            "tools": list(tools), "capabilities": ["detection", "syntax-mapping"],
            "registry_version": REGISTRY_VERSION}


LANGUAGES = [
    _entry("python", [".py", ".pyw", ".pyi"], shebangs=["python", "python3", "pypy", "pypy3"], tools=["python", "python3"]),
    _entry("javascript", [".js", ".jsx", ".mjs", ".cjs"], shebangs=["node"], tools=["node"]),
    _entry("typescript", [".ts", ".tsx", ".mts", ".cts"], tools=["tsc", "node"]),
    _entry("php", [".php", ".phtml"], shebangs=["php"], tools=["php"]),
    _entry("java", [".java"], tools=["java", "javac"]),
    _entry("c", [".c", ".h"], tools=["cc", "clang", "gcc"]),
    _entry("cpp", [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"], monaco="cpp", tools=["c++", "clang++", "g++"]),
    _entry("csharp", [".cs", ".csx"], tools=["dotnet"]),
    _entry("rust", [".rs"], tools=["rustc", "cargo"]),
    _entry("go", [".go"], tools=["go"]),
    _entry("swift", [".swift"], tools=["swift"]),
    _entry("kotlin", [".kt", ".kts"], tools=["kotlinc", "java"]),
    _entry("dart", [".dart"], tools=["dart", "flutter"]),
    _entry("ruby", [".rb", ".rake"], filenames=["Gemfile", "Rakefile"], shebangs=["ruby"], tools=["ruby"]),
    _entry("sql", [".sql"], monaco="sql"),
    _entry("html", [".html", ".htm"], monaco="html"),
    _entry("css", [".css"], monaco="css"),
    _entry("scss", [".scss"], monaco="scss"),
    _entry("json", [".json", ".jsonc"], monaco="json"),
    _entry("yaml", [".yaml", ".yml"], monaco="yaml"),
    _entry("bash", [".sh", ".bash"], filenames=[".bashrc", ".bash_profile"], shebangs=["bash", "sh", "dash"], monaco="shell", tools=["bash"]),
    _entry("powershell", [".ps1", ".psm1", ".psd1"], shebangs=["pwsh"], tools=["pwsh"]),
    _entry("xml", [".xml", ".xsd", ".svg"], monaco="xml"),
    _entry("markdown", [".md", ".mdx"], monaco="markdown"),
    _entry("latex", [".tex", ".sty", ".cls"], monaco="latex", tools=["tectonic", "latexmk"]),
    _entry("bibtex", [".bib"], monaco="latex", tools=["biber", "bibtex"]),
    _entry("r", [".r", ".rmd"], tools=["Rscript"]),
    _entry("julia", [".jl"], tools=["julia"]),
    _entry("lua", [".lua"], shebangs=["lua"], tools=["lua"]),
    _entry("perl", [".pl", ".pm"], shebangs=["perl"], tools=["perl"]),
    _entry("objective-c", [".m", ".mm"], monaco="objective-c", tools=["clang"]),
    _entry("matlab", [".m"], monaco="matlab"),
    _entry("toml", [".toml"], monaco="ini"),
    _entry("dockerfile", filenames=["Dockerfile", "Containerfile"], monaco="dockerfile", tools=["docker"]),
    _entry("makefile", filenames=["Makefile", "GNUmakefile"], monaco="makefile", tools=["make"]),
    _entry("terraform", [".tf", ".tfvars"], monaco="hcl", tools=["terraform"]),
    _entry("nix", [".nix"], tools=["nix"]),
    _entry("zig", [".zig"], tools=["zig"]),
    _entry("shell", [".zsh", ".fish"], shebangs=["zsh", "fish"], monaco="shell"),
    _entry("graphql", [".graphql", ".gql"]),
    _entry("protobuf", [".proto"]),
    _entry("typst", [".typ"], tools=["typst"]),
    _entry("quarto", [".qmd"], monaco="markdown", tools=["quarto"]),
    _entry("solidity", [".sol"], tools=["solc"]),
    _entry("wasm-text", [".wat", ".wast"], monaco="plaintext"),
    _entry("assembly", [".asm", ".s", ".S"], monaco="plaintext"),
]
IDS = {e["id"]: e for e in LANGUAGES}
assert len(IDS) == len(LANGUAGES)
assert all(e["registry_version"] == REGISTRY_VERSION for e in LANGUAGES)


class DetectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1, max_length=1024)
    path: Optional[str] = Field(default=None, max_length=1024)
    probe_tools: bool = False


def _read(root: Path, relative: str, cap: int = MAX_MANIFEST) -> Optional[str]:
    """Read existing regular files without following links, with a hard byte cap."""
    try:
        path = studio._path(root, relative)
        if path == root:
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
                return None
            raw = stream.read(cap + 1)
        if len(raw) > cap or b"\x00" in raw:
            return None
        return raw.decode("utf-8-sig")
    except (HTTPException, OSError, UnicodeError, ValueError):
        return None


def _file_language(name: str, text: Optional[str] = None) -> dict:
    filename = Path(name).name
    suffix = Path(filename).suffix.casefold()
    matches = []
    evidence = []
    for item in LANGUAGES:
        if filename in item["filenames"]:
            matches.append(item["id"])
            evidence.append("filename: " + filename)
    if not matches:
        for item in LANGUAGES:
            if suffix and suffix in item["extensions"]:
                matches.append(item["id"])
        if matches:
            evidence.append("extension: " + suffix)
    if text:
        first = text.split("\n", 1)[0][:256].strip()
        if first.startswith("#!"):
            # Interpret only the interpreter basename: never execute the shebang.
            tokens = first[2:].split()
            interpreter = Path(tokens[0]).name if tokens else ""
            if interpreter == "env" and len(tokens) > 1:
                interpreter = next((t for t in tokens[1:] if not t.startswith("-")), "")
            interpreter = re.sub(r"\d+(?:\.\d+)*$", "", interpreter).casefold()
            shebang_matches = [item["id"] for item in LANGUAGES
                               if interpreter in item["shebangs"]]
            if shebang_matches:
                matches = shebang_matches
                evidence.append("shebang interpreter: " + interpreter)
    matches = list(dict.fromkeys(matches))
    primary = matches[0] if len(matches) == 1 else None
    return {"language": primary, "candidates": matches,
            "monaco": IDS[primary]["monaco"] if primary else "plaintext",
            "confidence": "high" if primary and evidence and evidence[-1].startswith(("filename", "shebang"))
            else "medium" if primary else "ambiguous" if matches else "unknown",
            "evidence": evidence}


def _walk(root: Path):
    """Bounded breadth-first metadata inspection; no linked or restricted paths."""
    queue = [(root, 0)]
    seen = 0
    truncated = False
    while queue and seen < MAX_INSPECT:
        folder, depth = queue.pop(0)
        try:
            with os.scandir(folder) as scan:
                entries = sorted(list(scan), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if seen >= MAX_INSPECT:
                truncated = True
                break
            if studio._forbidden(entry.name) or entry.is_symlink():
                continue
            candidate = Path(entry.path)
            if getattr(candidate, "is_junction", lambda: False)():
                continue
            try:
                relative = candidate.relative_to(root).as_posix()
                studio._path(root, relative)
                if entry.is_file(follow_symlinks=False):
                    seen += 1
                    yield relative, False
                elif entry.is_dir(follow_symlinks=False) and depth < MAX_DEPTH:
                    queue.append((candidate, depth + 1))
            except (HTTPException, OSError, ValueError):
                continue
    if queue or truncated:
        yield None, True


def _frameworks(root: Path, files: set[str]) -> list[dict]:
    found = []
    names = {Path(p).name for p in files}
    def add(name, evidence):
        found.append({"name": name, "evidence": evidence, "confidence": "high"})
    package = _read(root, "package.json")
    if package:
        try:
            obj = json.loads(package)
            deps = {**(obj.get("dependencies") or {}), **(obj.get("devDependencies") or {})}
            if isinstance(deps, dict):
                for framework, key in [("Next.js", "next"), ("React", "react"),
                                       ("Vue", "vue"), ("Angular", "@angular/core"),
                                       ("Svelte", "svelte"), ("Nuxt", "nuxt")]:
                    if key in deps:
                        add(framework, ["package.json dependency: " + key])
        except (ValueError, TypeError, AttributeError):
            pass
    composer = _read(root, "composer.json")
    if composer:
        try:
            obj = json.loads(composer)
            deps = {**(obj.get("require") or {}), **(obj.get("require-dev") or {})}
            if "laravel/framework" in deps:
                add("Laravel", ["composer.json dependency: laravel/framework"])
            if "symfony/framework-bundle" in deps:
                add("Symfony", ["composer.json dependency: symfony/framework-bundle"])
        except (ValueError, TypeError, AttributeError):
            pass
    python = "\n".join(filter(None, (_read(root, file, 64 * 1024)
                      for file in ("requirements.txt", "pyproject.toml")))).lower()
    if "manage.py" in names and re.search(r"(?m)^\s*[\"']?django(?:\b|\[)", python):
        add("Django", ["manage.py", "dependency: django"])
    if re.search(r"(?m)^\s*[\"']?flask(?:\b|\[)", python):
        add("Flask", ["dependency: flask"])
    if "wp-includes/version.php" in files and ("wp-config.php" in names or "wp-content" in names):
        add("WordPress", ["wp-includes/version.php", "WordPress project marker"])
    pom = _read(root, "pom.xml") or ""
    gradle = "\n".join(filter(None, (_read(root, name) for name in
                ("build.gradle", "build.gradle.kts", "settings.gradle.kts"))))
    if "spring-boot" in pom or "org.springframework.boot" in gradle:
        add("Spring Boot", ["Maven/Gradle Spring Boot declaration"])
    if any(name.endswith((".csproj", ".sln", ".fsproj")) for name in names):
        add(".NET", ["project file: .csproj/.sln/.fsproj"])
    pubspec = _read(root, "pubspec.yaml") or ""
    if re.search(r"(?m)^\s*flutter:\s*(?:\n|$)", pubspec):
        add("Flutter", ["pubspec.yaml flutter declaration"])
    gemfile = _read(root, "Gemfile") or ""
    if re.search(r"(?m)^\s*gem\s+[\"']rails[\"']", gemfile):
        add("Ruby on Rails", ["Gemfile dependency: rails"])
    return found


def _tool_status(names: list[str], check: bool, root: Path) -> list[dict]:
    result = []
    for name in list(dict.fromkeys(names))[:MAX_TOOLS]:
        if not check:
            result.append({"tool": name, "status": "not_checked", "version": None})
            continue
        location = shutil.which(name)
        valid = False
        if location:
            try:
                resolved = Path(location).resolve(strict=True)
                # A binary inside the selected project is never a trusted host tool.
                if not resolved.is_relative_to(root) and resolved.is_file() and os.access(resolved, os.X_OK):
                    valid = True
            except (OSError, ValueError):
                pass
        result.append({"tool": name, "status": "available" if valid else "unavailable",
                       "version": None, "verification": "executable located; not run" if valid
                       else "not found in approved host PATH"})
    return result


@router.get("/registry")
def registry(request: Request):
    studio._auth(request)
    return {"schema_version": REGISTRY_VERSION, "languages": LANGUAGES,
            "toolchain_execution": False, "support_claim": "detection and syntax mapping only"}


@router.post("/detect")
def detect(request: Request, body: DetectIn):
    studio._auth(request)
    root = studio._project(body.project)
    filenames = set()
    counts: Counter[str] = Counter()
    capped = False
    for relative, truncated in _walk(root):
        if truncated:
            capped = True
            continue
        filenames.add(relative)
        match = _file_language(relative)
        if match["language"]:
            counts[match["language"]] += 1
    file_result = None
    if body.path is not None:
        # Validate the exact requested path even if the metadata scan was capped.
        target = studio._path(root, body.path)
        if target == root or not target.is_file():
            raise HTTPException(404, "Choose an existing ordinary source file.")
        sample = _read(root, body.path, 128 * 1024)
        file_result = _file_language(body.path, sample[:4096] if sample is not None else None)
    frameworks = _frameworks(root, filenames)
    primary = counts.most_common(1)[0][0] if counts else None
    if file_result and file_result["language"]:
        primary = file_result["language"]
    required = (IDS[primary]["tools"] if primary else [])
    return {"schema_version": REGISTRY_VERSION, "project": str(root),
            "primary_language": primary, "project_languages":
            [{"id": item, "files": count} for item, count in counts.most_common(16)],
            "file": file_result, "frameworks": frameworks,
            "toolchains": _tool_status(required, body.probe_tools, root),
            "files_inspected": sum(counts.values()), "scan_truncated": capped,
            "read_only": True, "source_executed": False,
            "limitations": ["Framework inference uses bounded project evidence.",
                            "Tool availability is path-based, not version or functionality certification.",
                            "No compiler, project script or language server is executed."]}
