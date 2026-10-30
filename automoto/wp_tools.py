"""Agent tools for WordPress plugins and themes (group ``wordpress``)."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from automoto import archives, sandbox, wordpress
from automoto.archive_tools import ARR, B, _list
from automoto.archives import ArchiveError
from automoto.tools import S, Tool, ToolContext, ToolFailed, _obj


def _wrap(fn):
    def inner(ctx: ToolContext, *args: Any, **kw: Any) -> str:
        try:
            return fn(ctx, *args, **kw)
        except (ArchiveError, sandbox.SandboxError) as exc:
            raise ToolFailed(str(exc)) from None
    return inner


def render_validation(r: dict) -> str:
    head = (f"{'VALID' if r['valid'] else 'NOT VALID'} WordPress {r['kind']} '{r['slug']}'"
            f"{' v' + r['version'] if r.get('version') else ''} ({r['files']} files) - {r['source']}")
    out = [head]
    if r.get("main_file"):
        out.append(f"main file: {r['main_file']}")
    for title, items in (("ERRORS", r["errors"]), ("WARNINGS", r["warnings"])):
        if items:
            out.append(f"{title} ({len(items)}):")
            out += [f"  - {x}" for x in items]
    lint = r.get("php_lint")
    if lint:
        out.append(f"PHP lint: {lint['status']}; {lint['files']} file(s), {len(lint['errors'])} error(s)")
    sec = r.get("security")
    if sec:
        c = sec["counts"]
        out.append(f"security checklist: {c['high']} high, {c['medium']} medium, {c['low']} low ({sec['note']})")
        out += [f"  [{f['severity']}] {f['file']}:{f['line']} {f['rule']}: {f['message']}" for f in sec["findings"][:25]]
    if r.get("phpcs"):
        out.append(f"phpcs: {r['phpcs'].get('status')}" + (f"\n{r['phpcs']['summary']}" if r["phpcs"].get("summary") else ""))
    meta = {k: r.get(k) for k in ("headers", "readme", "theme_json", "screenshot", "block_theme") if r.get(k) is not None}
    out.append("details: " + json.dumps(meta, ensure_ascii=False)[:3000])
    return "\n".join(out)


@_wrap
def wp_validate(ctx: ToolContext, path: str, kind: str = "auto", run_phpcs: bool = False) -> str:
    return render_validation(wordpress.validate(path, kind=kind or "auto", run_phpcs=bool(run_phpcs)))


@_wrap
def wp_security_review(ctx: ToolContext, path: str) -> str:
    with wordpress.open_package(path) as pkg:
        r = wordpress.security_review(pkg.top, kind=wordpress._detect_kind(pkg.top))
    c = r["counts"]
    lines = [f"{c['high']} high, {c['medium']} medium, {c['low']} low - {r['note']}",
             "passed: " + ", ".join(f"{k} {v}" for k, v in r["passed"].items())]
    lines += [f"[{f['severity']}] {f['file']}:{f['line']} {f['rule']}: {f['message']}" for f in r["findings"]]
    return "\n".join(lines)


def _zip_job(path: str, out: str, fn) -> dict:
    """Run ``fn(folder)`` on a copy of a zip's folder and package it to ``out``."""
    if not out:
        raise ToolFailed("path is a zip: give out='name.zip' for the new package (the original is kept)")
    o = sandbox.resolve(out, allow_outside=True)
    with wordpress.open_package(path) as pkg:
        work = Path(tempfile.mkdtemp(prefix="automoto-wpjob-"))
        try:
            top = work / pkg.top.name
            shutil.copytree(pkg.top, top)
            res = fn(top)
            res["package"] = wordpress._pack(top, o, top.name, wordpress.DEV_FILES)
            return res
        finally:
            shutil.rmtree(work, ignore_errors=True)


@_wrap
def wp_bump_version(ctx: ToolContext, path: str, version: str = "patch", changelog: str = "", out: str = "") -> str:
    p = sandbox.resolve(path, allow_outside=True)
    if p.is_dir():
        r = wordpress.bump_folder(p, version or "patch", changelog or None)
    else:
        r = _zip_job(path, out, lambda top: wordpress.bump_folder(top, version or "patch", changelog or None))
    text = f"{r['kind']} version {r['old'] or '(none)'} -> {r['new']}\n" + "\n".join("  " + c for c in r["changes"])
    if r.get("package"):
        v = r["package"]["validation"]
        text += (f"\npackaged {r['package']['out']} ({r['package']['files']} files, sha256 {r['package']['sha256'][:16]}…): "
                 f"{'valid' if v['valid'] else 'NOT valid: ' + '; '.join(v['errors'])}")
    return text


@_wrap
def wp_add_guard(ctx: ToolContext, path: str, out: str = "") -> str:
    p = sandbox.resolve(path, allow_outside=True)
    if p.is_dir():
        done = wordpress.add_guards(p)
        pkg = None
    else:
        holder: dict = {}

        def job(top):
            holder["done"] = wordpress.add_guards(top)
            return {}
        pkg = _zip_job(path, out, job)["package"]
        done = holder["done"]
    text = (f"added a direct-access guard to {len(done)} file(s): {', '.join(done)}" if done
            else "every PHP file already has a guard (or is a silent index.php)")
    if pkg:
        text += f"\npackaged {pkg['out']}: {'valid' if pkg['validation']['valid'] else 'NOT valid'}"
    return text + "\nRun wp_validate to lint (php -l) the result."


@_wrap
def wp_package(ctx: ToolContext, src: str, out: str, slug: str = "", keep: Any = None, exclude: Any = None) -> str:
    r = wordpress.package(src, out, slug=slug or None, keep=_list(keep), exclude=_list(exclude))
    v = r["validation"]
    text = (f"wrote {r['out']} ({r['files']} files, {r['bytes_out']:,} bytes, sha256 {r['sha256']})\n"
            f"top folder: {', '.join(r['top_level'])}; left out {r['skipped_count']} dev/system file(s)"
            + (f": {', '.join(r['skipped'][:12])}" if r["skipped"] else "") + "\n"
            f"structure check: {'VALID' if v['valid'] else 'NOT VALID'} {v.get('kind')} {v.get('slug')} v{v.get('version', '?')}")
    for e in v.get("errors", []):
        text += f"\n  error: {e}"
    for w in v.get("warnings", [])[:10]:
        text += f"\n  warning: {w}"
    return text


TOOLS: list[Tool] = [
    Tool("wp_validate", "Validate a WordPress plugin or theme (installable .zip or folder): single slug top folder, plugin "
         "header / style.css header, readme.txt (Stable tag = Version), theme.json, screenshot, stray dev files, php -l "
         "lint (if PHP is installed) and a security checklist (ABSPATH guard, nonces, capability checks, sanitising/"
         "escaping, eval/base64/shell, SQL without prepare). run_phpcs=true also runs phpcs WordPress standards if installed.",
         _obj({"path": S, "kind": {**S, "description": "auto | plugin | theme"}, "run_phpcs": B}, ["path"]),
         "safe", wp_validate, "wordpress"),
    Tool("wp_security_review", "Only the heuristic security checklist for a plugin/theme zip or folder.",
         _obj({"path": S}, ["path"]), "safe", wp_security_review, "wordpress"),
    Tool("wp_bump_version", "Set or bump the version (version='1.8.0' or patch|minor|major) in the plugin header / "
         "style.css, VERSION constants and readme.txt Stable tag, plus an optional changelog entry. A folder is edited "
         "in place; a .zip is left untouched and a new package is written to out.",
         _obj({"path": S, "version": S, "changelog": S, "out": S}, ["path"]), "risky", wp_bump_version, "wordpress"),
    Tool("wp_add_guard", "Add `if ( ! defined( 'ABSPATH' ) ) { exit; }` to every PHP file of a plugin/theme that lacks a "
         "direct-access guard (after the header docblock, declare() and namespace; uninstall.php gets the "
         "WP_UNINSTALL_PLUGIN check). Folder in place, or zip -> out.",
         _obj({"path": S, "out": S}, ["path"]), "risky", wp_add_guard, "wordpress"),
    Tool("wp_package", "Build an installable WordPress zip from a folder (or clean an existing zip): one top folder "
         "named after the slug, dev files (.git, node_modules, tests, lock files, .env, __MACOSX…) left out, "
         "deterministic bytes, then a structure check.",
         _obj({"src": S, "out": S, "slug": S, "keep": {**ARR, "description": "dev patterns to keep, e.g. ['tests']"},
               "exclude": ARR}, ["src", "out"]), "risky", wp_package, "wordpress"),
]
