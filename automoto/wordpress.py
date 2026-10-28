"""WordPress plugin and theme packages: validate, version bump, PHP lint, security checklist, package.

Works on a folder or an installable .zip. Zips are inspected with the archive guards and
extracted to a temporary folder for checks, never run. Nothing here executes plugin code:
``php -l`` only parses files.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from automoto import archives, sandbox
from automoto.archives import ArchiveError

PLUGIN_HEADERS = ["Plugin Name", "Plugin URI", "Description", "Version", "Requires at least", "Requires PHP", "Author",
                  "Author URI", "License", "License URI", "Text Domain", "Domain Path", "Network", "Update URI",
                  "Requires Plugins"]
THEME_HEADERS = ["Theme Name", "Theme URI", "Author", "Author URI", "Description", "Version", "Requires at least",
                 "Tested up to", "Requires PHP", "License", "License URI", "Text Domain", "Tags", "Template"]
README_HEADERS = ["Contributors", "Donate link", "Tags", "Requires at least", "Tested up to", "Requires PHP",
                  "Stable tag", "License", "License URI"]

DEV_FILES = [".git", ".github", ".gitignore", ".gitattributes", ".svn", ".hg", "node_modules", ".DS_Store", "__MACOSX",
             "Thumbs.db", ".idea", ".vscode", ".editorconfig", ".env", ".env.*", "*.log", "*.sql", "*.zip", "*.tar.gz",
             "phpunit.xml", "phpunit.xml.dist", ".phpcs.xml", "phpcs.xml", "phpcs.xml.dist", ".travis.yml",
             ".gitlab-ci.yml", "Gruntfile.js", "gulpfile.js", "webpack.config.js", "package-lock.json", "yarn.lock",
             "composer.lock", ".eslintrc*", ".stylelintrc*", ".prettierrc*", "tests", "bin", ".wordpress-org",
             "*.orig", "*.swp", "*~", ".php-cs-fixer*", "phpstan.neon*", "Dockerfile", "docker-compose*.yml"]
# dev files that are fine to ship but usually unwanted -> warnings, these -> errors
DEV_ERRORS = {".env", ".git", "*.sql", "__MACOSX", ".svn"}
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION = re.compile(r"^\d+(?:\.\d+){0,3}(?:[-+][0-9A-Za-z.-]+)?$")
GPL = re.compile(r"GPL|GNU General Public|MIT|BSD|Apache|MPL|LGPL|Expat|ISC|public domain|CC0", re.I)


def _header_re(name: str) -> re.Pattern:
    # WordPress get_file_data(): '/^(?:[ \t]*<\?php)?[ \t\/*#@]*' . preg_quote( $regex, '/' ) . ':(.*)$/mi'
    return re.compile(r"^(?:[ \t]*<\?php)?[ \t/*#@]*" + re.escape(name) + r":(.*)$", re.M | re.I)


def file_headers(text: str, names: list[str]) -> dict[str, str]:
    head = text[:8192].replace("\r", "\n")
    out = {}
    for n in names:
        m = _header_re(n).search(head)
        if m:
            v = re.sub(r"\s*(?:\*/|\?>).*", "", m.group(1)).strip()
            if v:
                out[n] = v
    return out


def parse_readme(text: str) -> dict:
    """readme.txt in the WordPress.org format."""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    info: dict = {"name": "", "headers": {}, "short_description": "", "sections": [], "problems": []}
    first = next((ln for ln in lines if ln.strip()), "")
    m = re.match(r"^===\s*(.+?)\s*===\s*$", first.strip())
    if m:
        info["name"] = m.group(1)
    else:
        info["problems"].append("first line must be '=== Plugin Name ==='")
    i = lines.index(first) + 1 if first in lines else 0
    while i < len(lines) and lines[i].strip():
        hm = re.match(r"^([A-Za-z ]+):\s*(.*)$", lines[i].strip())
        if hm:
            info["headers"][hm.group(1).strip().title() if hm.group(1).strip().lower() != "requires php"
                            else "Requires PHP"] = hm.group(2).strip()
        i += 1
    # normalise case to the documented names
    fixed = {}
    for k, v in info["headers"].items():
        canon = next((h for h in README_HEADERS if h.lower() == k.lower()), k)
        fixed[canon] = v
    info["headers"] = fixed
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and not lines[i].startswith("=="):
        info["short_description"] = lines[i].strip()
    info["sections"] = [s.strip() for s in re.findall(r"^==\s*([^=].*?)\s*==\s*$", text, re.M)]
    return info




# -- opening a package (folder or zip) ----------------------------------------------------------
class Package:
    def __init__(self, top: Path, entries: list[str], source: str, is_zip: bool):
        self.top = top            # folder on disk that holds the plugin/theme files
        self.entries = entries    # paths as they appear in the package (zip names or top/relpath)
        self.source = source
        self.is_zip = is_zip


@contextmanager
def open_package(path: str | Path) -> Iterator[Package]:
    p = sandbox.resolve(str(path), allow_outside=True)
    if p.is_dir():
        entries = []
        for f in sorted(p.rglob("*")):
            if f.is_symlink() or f.is_file():
                entries.append(p.name + "/" + f.relative_to(p).as_posix())
        yield Package(p, entries, sandbox.rel(p), False)
        return
    if not p.is_file():
        raise ArchiveError(f"no such file or folder: {path}")
    if archives.detect(p) != "zip":
        raise ArchiveError(f"{p.name}: WordPress packages are .zip files")
    rep = archives.inspect_path(p)
    if not rep["safe"]:
        raise ArchiveError(f"{p.name} is not safe to open: {'; '.join(rep['problems'])}")
    with zipfile.ZipFile(p) as zf:
        entries = [archives.safe_name(archives._fix_zip_name(i)[0])[0] + ("/" if i.is_dir() else "")
                   for i in zf.infolist()]
    work = Path(tempfile.mkdtemp(prefix="automoto-wp-"))
    try:
        archives._extract(p, work / "x", skip_links=True)
        kids = [k for k in (work / "x").iterdir() if k.name != "__MACOSX"]
        top = kids[0] if len(kids) == 1 and kids[0].is_dir() else work / "x"
        yield Package(top, entries, sandbox.rel(p), True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _matches_dev(rel_parts: list[str]) -> str | None:
    import fnmatch

    for part in rel_parts:
        for pat in DEV_FILES:
            if fnmatch.fnmatch(part, pat):
                return pat
    return None


def _php_files(top: Path) -> list[Path]:
    return sorted(f for f in top.rglob("*.php") if f.is_file() and not f.is_symlink()
                  and not any(x in f.relative_to(top).parts for x in ("vendor", "node_modules")))


def _rtext(f: Path) -> str:
    """Read keeping the file's own line endings (CRLF stays CRLF on every OS)."""
    with f.open("r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        return fh.read()


def _wtext(f: Path, text: str) -> None:
    with f.open("w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        fh.write(text)


def _read(f: Path, limit: int = 2_000_000) -> str:
    with f.open("rb") as fh:
        return fh.read(limit).decode("utf-8", errors="replace")


# -- PHP lint / phpcs ------------------------------------------------------------------------------
def php_available() -> str | None:
    return shutil.which("php")


def php_lint(top: Path, max_files: int = 800) -> dict:
    php = php_available()
    files = _php_files(top)
    if not php:
        return {"status": "skipped - php not installed (install PHP to lint)", "files": len(files), "errors": []}
    errors, checked = [], 0
    for f in files[:max_files]:
        r = subprocess.run([php, "-n", "-d", "display_errors=1", "-d", "error_reporting=E_ALL", "-l", str(f)],
                           capture_output=True, text=True, timeout=60, env=sandbox.clean_env(), stdin=subprocess.DEVNULL)
        checked += 1
        if r.returncode != 0:
            msg = (r.stdout + r.stderr).strip().replace(str(f), f.relative_to(top).as_posix())
            errors.append(msg.splitlines()[0][:300] if msg else "syntax error")
    ver = subprocess.run([php, "-n", "-r", "echo PHP_VERSION;"], capture_output=True, text=True, timeout=20,
                         env=sandbox.clean_env()).stdout.strip()
    return {"status": f"ran php -l (PHP {ver})", "files": checked, "errors": errors,
            **({"not_checked": len(files) - checked} if len(files) > checked else {})}


def phpcs(top: Path) -> dict:
    exe = shutil.which("phpcs")
    if not exe:
        return {"status": "skipped - phpcs with WordPress Coding Standards not installed "
                          "(composer global require wp-coding-standards/wpcs)"}
    r = subprocess.run([exe, "-i"], capture_output=True, text=True, timeout=60, env=sandbox.clean_env())
    if "WordPress" not in r.stdout:
        return {"status": "skipped - phpcs found but the WordPress standard is not installed"}
    r = subprocess.run([exe, "--standard=WordPress", "--report=summary", "--extensions=php", "-q", str(top)],
                       capture_output=True, text=True, timeout=600, env=sandbox.clean_env())
    return {"status": "ran phpcs --standard=WordPress", "ok": r.returncode == 0,
            "summary": (r.stdout or r.stderr).strip()[-3000:].replace(str(top), top.name)}


# -- security checklist (heuristic) ----------------------------------------------------------------
_GUARD = re.compile(r"defined\s*\(\s*['\"](ABSPATH|WPINC|WP_UNINSTALL_PLUGIN)['\"]\s*\)")
_INPUT = re.compile(r"\$_(GET|POST|REQUEST|COOKIE|FILES|SERVER)\s*\[")
_SANITIZERS = re.compile(r"sanitize_\w+|absint|intval|floatval|\(int\)|\(float\)|\(bool\)|wp_unslash|esc_\w+|"
                         r"isset|empty|wp_verify_nonce|check_admin_referer|check_ajax_referer|is_numeric|in_array|"
                         r"array_key_exists|wp_kses\w*|filter_input|filter_var|rest_sanitize|sanitize_key|=== ?|== ?")
_RULES = [
    ("high", "eval", re.compile(r"(?<![\w>$])eval\s*\("), "eval() runs arbitrary code"),
    ("high", "create_function", re.compile(r"\bcreate_function\s*\("), "create_function() is eval in disguise (removed in PHP 8)"),
    ("high", "assert-code", re.compile(r"\bassert\s*\(\s*\$"), "assert() on a variable can run code"),
    ("high", "preg-e", re.compile(r"preg_replace\s*\(\s*['\"](.).*\1[a-zA-Z]*e[a-zA-Z]*['\"]"), "preg_replace /e modifier executes code"),
    ("high", "shell", re.compile(r"(?<![\w>$])(shell_exec|system|passthru|exec|popen|proc_open|pcntl_exec)\s*\("),
     "runs shell commands"),
    ("medium", "obfuscation", re.compile(r"\b(base64_decode|gzinflate|gzuncompress|str_rot13|convert_uudecode)\s*\("),
     "decoding function often used to hide code"),
    ("medium", "hex-blob", re.compile(r"(\\x[0-9a-fA-F]{2}){12,}|[A-Za-z0-9+/]{400,}={0,2}"), "long encoded blob (obfuscation?)"),
    ("high", "unserialize-input", re.compile(r"(maybe_)?unserialize\s*\([^;]*\$_(GET|POST|REQUEST|COOKIE)"),
     "unserialize() of user input (object injection)"),
    ("high", "include-input", re.compile(r"\b(include|require)(_once)?\b[^;]*\$_(GET|POST|REQUEST|COOKIE)"),
     "include/require of user input (file inclusion)"),
    ("high", "extract-input", re.compile(r"\bextract\s*\(\s*\$_(GET|POST|REQUEST)"), "extract() of user input"),
    ("high", "sql-no-prepare", re.compile(r"\$wpdb->(query|get_results|get_row|get_var|get_col)\s*\(\s*(\"[^\"]*\$|[^)]*\.\s*\$)"),
     "SQL built from variables without $wpdb->prepare()"),
    ("low", "remote-file", re.compile(r"(file_get_contents|fopen)\s*\(\s*['\"]https?://"), "use wp_remote_get() for HTTP"),
    ("low", "curl", re.compile(r"\bcurl_exec\s*\("), "use the WordPress HTTP API (wp_remote_*) instead of cURL"),
]


def _silent_index(text: str) -> bool:
    body = re.sub(r"(?s)/\*.*?\*/|//[^\n]*|#[^\n]*|<\?php|\?>", "", text).strip()
    return body == ""


def security_review(top: Path, max_findings: int = 200, kind: str = "plugin") -> dict:
    findings: list[dict] = []
    checked = {"direct_access_guard": 0, "nonces": 0, "capabilities": 0, "input_sanitized": 0, "output_escaped": 0}

    def add(sev, rule, f, line, msg):
        if len(findings) < max_findings:
            findings.append({"severity": sev, "rule": rule, "file": f, "line": line, "message": msg})

    for f in _php_files(top):
        rel = f.relative_to(top).as_posix()
        text = _read(f)
        lines = text.splitlines()
        if not _GUARD.search(text) and not _silent_index(text):
            add("low" if kind == "theme" else "medium", "direct-access", rel, 1, "no direct-access guard - add "
                "`if ( ! defined( 'ABSPATH' ) ) { exit; }` near the top"
                + (" (uninstall.php should check WP_UNINSTALL_PLUGIN)" if f.name == "uninstall.php" else ""))
        else:
            checked["direct_access_guard"] += 1
        handles_forms = bool(_INPUT.search(text) and re.search(r"\$_(POST|REQUEST)", text)) or bool(
            re.search(r"['\"](wp_ajax_|admin_post_)", text))
        if handles_forms:
            if not re.search(r"wp_verify_nonce|check_admin_referer|check_ajax_referer", text):
                add("medium", "nonce", rel, 1, "handles form/AJAX input but never checks a nonce "
                    "(wp_verify_nonce / check_admin_referer / check_ajax_referer)")
            else:
                checked["nonces"] += 1
            if "current_user_can" not in text:
                add("medium", "capability", rel, 1, "handles form/AJAX input but never checks current_user_can()")
            else:
                checked["capabilities"] += 1
        for n, ln in enumerate(lines, 1):
            code = ln.split("//", 1)[0] if "://" not in ln else ln
            if len(code) > 20000:
                code = code[:20000]
            for sev, rule, rx, msg in _RULES:
                if rx.search(code):
                    if rule == "shell" and re.search(r"->\s*(exec|system)\s*\(|::(exec|system)\s*\(", code):
                        continue  # method calls like $wpdb->exec / Foo::system
                    add(sev, rule, rel, n, msg)
            if _INPUT.search(code):
                if _SANITIZERS.search(code):
                    checked["input_sanitized"] += 1
                else:
                    add("medium", "unsanitized-input", rel, n, "superglobal used without sanitize_*/wp_unslash/absint")
            if re.match(r"\s*(echo|print)\b", code) and "$" in code:
                if re.search(r"esc_\w+|wp_kses\w*|absint|intval|number_format|wp_json_encode|json_encode|"
                             r"\(int\)|_e\(|selected\(|checked\(|disabled\(", code):
                    checked["output_escaped"] += 1
                else:
                    add("low", "unescaped-output", rel, n, "echo of a variable without esc_html/esc_attr/esc_url/wp_kses")
    sev = {k: sum(1 for x in findings if x["severity"] == k) for k in ("high", "medium", "low")}
    # keep the report readable: at most 6 findings per rule, then one summary line
    per: dict[str, int] = {}
    shown = []
    for x in findings:
        per[x["rule"]] = per.get(x["rule"], 0) + 1
        if per[x["rule"]] <= 6:
            shown.append(x)
    for rule, n in per.items():
        if n > 6:
            shown.append({"severity": "info", "rule": rule, "file": "*", "line": 0,
                          "message": f"... {n - 6} more '{rule}' findings (same issue in other files)"})
    findings = shown
    return {"note": "heuristic checklist - review each finding; not a substitute for WordPress Plugin Check",
            "counts": sev, "passed": checked, "findings": findings}


# -- validation ---------------------------------------------------------------------------------------
def _detect_kind(top: Path) -> str:
    for f in sorted(top.glob("*.php")):
        if "Plugin Name" in file_headers(_read(f, 8192), ["Plugin Name"]):
            return "plugin"
    style = top / "style.css"
    if style.is_file() and "Theme Name" in file_headers(_read(style, 8192), ["Theme Name"]):
        return "theme"
    return "unknown"


def _structure(pkg: Package, errors: list, warnings: list) -> str:
    """Single top-level folder named like a slug; returns the slug."""
    names = [e for e in pkg.entries if e and not e.startswith("__MACOSX/")]
    tops = sorted({e.split("/")[0] for e in names})
    if pkg.is_zip:
        loose = [e for e in names if "/" not in e.rstrip("/") and not e.endswith("/")]
        if loose or len(tops) != 1:
            errors.append("the zip must contain exactly one top-level folder (the slug) with everything inside it; "
                          f"found {', '.join(tops[:6])}")
    slug = pkg.top.name if not pkg.is_zip or len(tops) != 1 else tops[0]
    if not SLUG.match(slug):
        errors.append(f"folder name '{slug}' is not a valid slug (lowercase letters, digits and single hyphens)")
    elif re.search(r"-\d+(\.\d+)+$|-v?\d+$", slug):
        warnings.append(f"folder name '{slug}' looks like it contains a version - WordPress treats it as a different plugin")
    return slug


def _dev_files(pkg: Package, errors: list, warnings: list) -> list[str]:
    hits = []
    for e in pkg.entries:
        parts = e.rstrip("/").split("/")
        pat = _matches_dev(parts[1:] if not e.startswith("__MACOSX") else parts)
        if pat:
            hits.append(e)
            (errors if pat in DEV_ERRORS else warnings).append(f"stray dev/system file: {e}")
    # collapse long lists
    for lst in (errors, warnings):
        dev = [x for x in lst if x.startswith("stray dev")]
        if len(dev) > 8:
            for x in dev[8:]:
                lst.remove(x)
            lst.append(f"... and {len(dev) - 8} more stray dev/system files")
    return hits


def _readme_checks(top: Path, version: str, name: str, headers: dict, errors: list, warnings: list,
                   kind: str) -> dict | None:
    rd = next((top / n for n in ("readme.txt", "README.txt") if (top / n).is_file()), None)
    if not rd:
        if (top / "readme.md").is_file() or (top / "README.md").is_file():
            warnings.append("readme.txt missing (WordPress.org reads readme.txt, not README.md)")
        else:
            warnings.append("readme.txt missing (required for the WordPress.org directory)")
        return None
    info = parse_readme(_read(rd))
    for pr in info["problems"]:
        warnings.append(f"readme.txt: {pr}")
    h = info["headers"]
    stable = h.get("Stable Tag") or h.get("Stable tag")
    if kind == "plugin":
        if not stable:
            errors.append("readme.txt has no 'Stable tag:'")
        elif stable.lower() == "trunk":
            warnings.append("readme.txt 'Stable tag: trunk' - set it to the released version")
        elif version and stable != version:
            errors.append(f"readme.txt Stable tag {stable} does not match the Version header {version}")
        for k in ("Tested up to", "Contributors", "License"):
            if not h.get(k):
                warnings.append(f"readme.txt has no '{k}:'")
    if name and info["name"] and info["name"].strip().lower() != name.strip().lower():
        warnings.append(f"readme.txt name '{info['name']}' differs from the header name '{name}'")
    for k in ("Requires at least", "Requires PHP"):
        if h.get(k) and headers.get(k) and h[k] != headers[k]:
            warnings.append(f"'{k}' is {headers[k]} in the header but {h[k]} in readme.txt")
    tags = [t for t in (h.get("Tags") or "").split(",") if t.strip()]
    if len(tags) > 5:
        warnings.append(f"readme.txt has {len(tags)} tags - WordPress.org shows at most 5")
    if len(info["short_description"]) > 150:
        warnings.append(f"readme.txt short description is {len(info['short_description'])} chars (max 150)")
    if not info["short_description"] and kind == "plugin":
        warnings.append("readme.txt has no short description line under the headers")
    secs = [x.lower() for x in info["sections"]]
    for sec in ("description", "changelog") if kind == "plugin" else ("description",):
        if sec not in secs:
            warnings.append(f"readme.txt has no == {sec.title()} == section")
    return {"name": info["name"], "headers": h, "short_description": info["short_description"],
            "sections": info["sections"]}


def validate(path: str | Path, *, kind: str = "auto", lint: bool = True, security: bool = True,
             run_phpcs: bool = False) -> dict:
    with open_package(path) as pkg:
        top = pkg.top
        errors: list[str] = []
        warnings: list[str] = []
        k = _detect_kind(top) if kind == "auto" else kind
        slug = _structure(pkg, errors, warnings)
        res: dict = {"source": pkg.source, "kind": k, "slug": slug, "files": sum(1 for e in pkg.entries if not e.endswith("/"))}
        if k == "plugin":
            res.update(_plugin_checks(top, slug, errors, warnings))
        elif k == "theme":
            res.update(_theme_checks(top, slug, errors, warnings))
        else:
            errors.append("no plugin main file (a top-level .php with a 'Plugin Name:' header) and no theme style.css "
                          "with 'Theme Name:' found" + (" - is the folder nested one level too deep?" if any(
                              (d / "style.css").exists() or list(d.glob("*.php")) for d in top.iterdir() if d.is_dir()) else ""))
        res["dev_files"] = len(_dev_files(pkg, errors, warnings))
        big = [f for f in top.rglob("*") if f.is_file() and f.stat().st_size > 10 * 1024 * 1024]
        for f in big[:5]:
            warnings.append(f"large file {f.relative_to(top).as_posix()} ({f.stat().st_size // 2**20} MB)")
        if lint:
            res["php_lint"] = php_lint(top)
            for e in res["php_lint"]["errors"]:
                errors.append(f"php -l: {e}")
        if security:
            res["security"] = security_review(top, kind=k)
            hi = res["security"]["counts"]["high"]
            if hi:
                warnings.append(f"security checklist: {hi} high-severity finding(s) - review them")
        res["phpcs"] = phpcs(top) if run_phpcs else {"status": "not requested (run_phpcs=true)"}
        res["errors"], res["warnings"] = errors, warnings
        res["valid"] = not errors
        return res


def _plugin_checks(top: Path, slug: str, errors: list, warnings: list) -> dict:
    mains = []
    for f in sorted(top.glob("*.php")):
        h = file_headers(_read(f, 8192), PLUGIN_HEADERS)
        if h.get("Plugin Name"):
            mains.append((f, h))
    if not mains:
        errors.append("no top-level .php file has a 'Plugin Name:' header")
        return {}
    if len(mains) > 1:
        warnings.append(f"{len(mains)} files have a Plugin Name header ({', '.join(m[0].name for m in mains)}) - keep one")
    main, h = next(((f, x) for f, x in mains if f.stem == slug), mains[0])
    if main.stem != slug:
        warnings.append(f"main file is {main.name}; the convention is {slug}.php (fine, but only if it is intentional)")
    v = h.get("Version", "")
    if not v:
        warnings.append("plugin header has no 'Version:'")
    elif not VERSION.match(v):
        errors.append(f"Version '{v}' is not a valid version number")
    if not h.get("License"):
        warnings.append("plugin header has no 'License:' (WordPress.org requires GPLv2 or later compatible)")
    elif not GPL.search(h["License"]):
        warnings.append(f"License '{h['License']}' may not be GPL-compatible")
    td = h.get("Text Domain")
    if td and td != slug:
        warnings.append(f"Text Domain '{td}' should match the slug '{slug}'")
    for k in ("Requires at least", "Requires PHP", "Description", "Author"):
        if not h.get(k):
            warnings.append(f"plugin header has no '{k}:'")
    readme = _readme_checks(top, v, h["Plugin Name"], h, errors, warnings, "plugin")
    if (top / "uninstall.php").is_file() and "WP_UNINSTALL_PLUGIN" not in _read(top / "uninstall.php"):
        warnings.append("uninstall.php does not check defined( 'WP_UNINSTALL_PLUGIN' )")
    return {"main_file": main.name, "headers": h, "version": v, "readme": readme}


def _theme_checks(top: Path, slug: str, errors: list, warnings: list) -> dict:
    style = top / "style.css"
    h = file_headers(_read(style, 8192), THEME_HEADERS)
    block = (top / "templates" / "index.html").is_file()
    if not (top / "index.php").is_file() and not block:
        errors.append("a theme needs index.php (classic) or templates/index.html (block theme)")
    tj = None
    if (top / "theme.json").is_file():
        try:
            data = json.loads(_read(top / "theme.json"))
            tj = {"version": data.get("version"), "schema": data.get("$schema", ""),
                  "settings": sorted((data.get("settings") or {}).keys())[:12]}
            if not isinstance(data.get("version"), int):
                warnings.append("theme.json has no integer 'version'")
        except json.JSONDecodeError as exc:
            errors.append(f"theme.json is not valid JSON ({exc})")
    elif block:
        warnings.append("block theme without theme.json")
    shot = next((top / f"screenshot.{e}" for e in ("png", "jpg", "jpeg", "gif", "webp") if (top / f"screenshot.{e}").is_file()), None)
    shot_info = None
    if not shot:
        warnings.append("no screenshot.png (1200x900 recommended)")
    else:
        try:
            from PIL import Image

            with Image.open(shot) as im:
                shot_info = {"file": shot.name, "size": list(im.size)}
                w, hgt = im.size
                if (w, hgt) != (1200, 900):
                    warnings.append(f"{shot.name} is {w}x{hgt}; the recommended size is 1200x900")
        except Exception as exc:  # unreadable image
            warnings.append(f"{shot.name} could not be read ({exc.__class__.__name__})")
    v = h.get("Version", "")
    for k in ("Version", "Requires at least", "Tested up to", "Requires PHP", "License", "License URI", "Text Domain"):
        if not h.get(k):
            warnings.append(f"style.css has no '{k}:' (required for the WordPress.org theme directory)")
    if v and not VERSION.match(v):
        errors.append(f"Version '{v}' is not a valid version number")
    if h.get("Text Domain") and h["Text Domain"] != slug:
        warnings.append(f"Text Domain '{h['Text Domain']}' should match the folder name '{slug}'")
    if h.get("Template"):
        warnings.append(f"child theme of '{h['Template']}' - the parent theme must be installed")
    readme = _readme_checks(top, v, h.get("Theme Name", ""), h, errors, warnings, "theme")
    return {"headers": h, "version": v, "block_theme": block, "theme_json": tj, "screenshot": shot_info,
            "readme": readme}


# -- version bump -----------------------------------------------------------------------------------
def next_version(cur: str, how: str) -> str:
    if VERSION.match(how):
        return how
    nums = [int(x) for x in re.findall(r"\d+", cur.split("-")[0].split("+")[0])[:3]] or [0]
    while len(nums) < 3:
        nums.append(0)
    if how == "major":
        nums = [nums[0] + 1, 0, 0]
    elif how == "minor":
        nums = [nums[0], nums[1] + 1, 0]
    elif how == "patch":
        nums = [nums[0], nums[1], nums[2] + 1]
    else:
        raise ArchiveError(f"version must be a number like 1.2.3 or one of patch/minor/major, not {how!r}")
    return ".".join(map(str, nums))


def _set_header(text: str, name: str, value: str) -> tuple[str, bool]:
    rx = re.compile(r"^((?:[ \t]*<\?php)?[ \t/*#@]*" + re.escape(name) + r":[ \t]*)([^\r\n]*?)([ \t]*(?:\*/)?[ \t]*)(?=\r?$)", re.M | re.I)
    head, tail = text[:8192], text[8192:]
    new, n = rx.subn(lambda m: m.group(1) + value + m.group(3), head, count=1)
    return new + tail, bool(n)


def bump_folder(top: Path, version: str = "patch", changelog: str | None = None) -> dict:
    kind = _detect_kind(top)
    changes = []
    if kind == "plugin":
        main = next(f for f in sorted(top.glob("*.php")) if "Plugin Name" in file_headers(_read(f, 8192), ["Plugin Name"]))
    elif kind == "theme":
        main = top / "style.css"
    else:
        raise ArchiveError("not a WordPress plugin or theme folder")
    text = _rtext(main)
    old = file_headers(text, ["Version"]).get("Version", "")
    new = next_version(old or "0.0.0", version)
    text, ok = _set_header(text, "Version", new)
    if not ok:  # no Version line: add one after the name header
        text = re.sub(r"^([ \t/*#@]*(?:Plugin|Theme) Name:[^\n]*\n)", lambda m: m.group(1) + re.sub(
            r"(Plugin|Theme) Name:.*", f"Version: {new}", m.group(1)), text, count=1, flags=re.M)
    changes.append(f"{main.name}: Version {old or '(none)'} -> {new}")
    if old and kind == "plugin":
        # constants that carry the version, e.g. define( 'MY_PLUGIN_VERSION', '1.2.3' ); const VERSION = '1.2.3';
        rx = re.compile(r"((?:define\s*\(\s*['\"][A-Z0-9_]*VERSION['\"]\s*,\s*|const\s+[A-Z0-9_]*VERSION\s*=\s*)['\"])"
                        + re.escape(old) + r"(['\"])")
        text, n = rx.subn(lambda m: m.group(1) + new + m.group(2), text)
        if n:
            changes.append(f"{main.name}: {n} VERSION constant(s) -> {new}")
    if old:
        # phpDoc / CSS-comment tags that repeat the old version, e.g. " * @version 1.7.2"
        text, n = re.subn(r"^([ \t/*]*@version[ \t]+)" + re.escape(old) + r"(?=\s)",
                          lambda m: m.group(1) + new, text, flags=re.M)
        if n:
            changes.append(f"{main.name}: {n} @version tag(s) -> {new}")
    if "\r\n" in text:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    _wtext(main, text)
    rd = next((top / n for n in ("readme.txt", "README.txt") if (top / n).is_file()), None)
    if rd:
        rt = _rtext(rd)
        rt2, n = re.subn(r"^(Stable tag:[ \t]*)\S+", lambda m: m.group(1) + new, rt, count=1, flags=re.M | re.I)
        if n:
            changes.append(f"{rd.name}: Stable tag -> {new}")
        elif kind == "plugin":
            rt2 = re.sub(r"^(Tested up to:[^\n]*\n)", lambda m: m.group(1) + f"Stable tag: {new}\n", rt, count=1,
                         flags=re.M | re.I)
            changes.append(f"{rd.name}: added Stable tag {new}")
        if changelog:
            entry = f"= {new} =\n" + "\n".join(f"* {ln.lstrip('*- ').strip()}" for ln in changelog.strip().splitlines()
                                              if ln.strip()) + "\n\n"
            m = re.search(r"^==\s*Changelog\s*==[ \t]*\n+", rt2, re.M | re.I)
            if m:
                rt2 = rt2[:m.end()] + entry + rt2[m.end():]
            else:
                rt2 = rt2.rstrip("\n") + "\n\n== Changelog ==\n\n" + entry
            changes.append(f"{rd.name}: changelog entry for {new}")
        if "\r\n" in rt:
            rt2 = rt2.replace("\r\n", "\n").replace("\n", "\r\n")
        _wtext(rd, rt2)
    return {"kind": kind, "old": old, "new": new, "changes": changes}


# -- direct-access guard -------------------------------------------------------------------------------
GUARD = "if ( ! defined( 'ABSPATH' ) ) {\n\texit; // Exit if accessed directly.\n}\n"
UNINSTALL_GUARD = "if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {\n\texit;\n}\n"


def add_guard_text(text: str, uninstall: bool = False) -> str | None:
    """Insert the guard after the opening docblock / declare / namespace. None = not applicable."""
    if _GUARD.search(text) or _silent_index(text):
        return None
    m = re.match(r"\A(\ufeff?<\?php)", text)
    if not m:
        return None
    pos = m.end()
    rest = text[pos:]
    # skip whitespace + leading comments/docblocks
    while True:
        mm = re.match(r"\s*(/\*.*?\*/|//[^\n]*|#(?!\[)[^\n]*)", rest, re.S)
        if not mm:
            break
        pos += mm.end()
        rest = text[pos:]
    for stmt in (r"\s*declare\s*\([^)]*\)\s*;", r"\s*namespace\s+[\w\\]+\s*;"):
        mm = re.match(stmt, rest)
        if mm:
            pos += mm.end()
            rest = text[pos:]
    if re.match(r"\s*namespace\s+[\w\\]*\s*\{", rest):
        return None  # braced namespaces: the guard has to go inside - leave it to a human
    guard = UNINSTALL_GUARD if uninstall else GUARD
    return text[:pos].rstrip(" \t") + "\n\n" + guard + "\n" + rest.lstrip("\n")


def add_guards(top: Path) -> list[str]:
    done = []
    for f in _php_files(top):
        text = _rtext(f)
        new = add_guard_text(text, uninstall=f.name == "uninstall.php")
        if new is not None:
            if "\r\n" in text:
                new = new.replace("\r\n", "\n").replace("\n", "\r\n")
            _wtext(f, new)
            done.append(f.relative_to(top).as_posix())
    return done


# -- packaging -------------------------------------------------------------------------------------
def package(src: str | Path, out: str | Path, *, slug: str | None = None, keep: list[str] | None = None,
            exclude: list[str] | None = None) -> dict:
    """Make an installable zip: one top folder (the slug), dev files removed, deterministic bytes."""
    s = sandbox.resolve(str(src), allow_outside=True)
    o = sandbox.resolve(str(out), allow_outside=True)
    if not o.name.lower().endswith(".zip"):
        raise ArchiveError("WordPress packages must be .zip")
    keep = keep or []
    pats = [p for p in DEV_FILES if p not in keep] + list(exclude or [])
    if s.is_file():  # a zip: unpack, then pack the folder inside
        with open_package(s) as pkg:
            return _pack(pkg.top, o, slug or pkg.top.name, pats)
    if not s.is_dir():
        raise ArchiveError(f"no such folder: {src}")
    return _pack(s, o, slug or s.name, pats)


def _pack(top: Path, o: Path, slug: str, pats: list[str]) -> dict:
    if not SLUG.match(slug):
        raise ArchiveError(f"'{slug}' is not a valid slug")
    r = archives._create([top], o, root_name=slug, exclude=pats, use_default_excludes=True, deterministic=True)
    r["validation"] = {k: v for k, v in validate(o, lint=False, security=False).items()
                       if k in ("kind", "slug", "version", "valid", "errors", "warnings", "main_file", "files")}
    return r
