"""v5.4 WordPress plugin/theme tools: validation, version bump, ABSPATH guard, packaging, security checklist."""

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from automoto import sandbox, tools, wordpress
from automoto.archives import ArchiveError

HAS_PHP = bool(shutil.which("php"))

MAIN = """<?php
/**
 * @package Hello_Dolly
 * @version 1.7.2
 */
/*
Plugin Name: Hello Dolly
Plugin URI: http://wordpress.org/plugins/hello-dolly/
Description: A tiny test plugin.
Author: Matt Mullenweg
Version: 1.7.2
Author URI: http://ma.tt/
*/

function hello_dolly_get_lyric() {
	return 'Hello, Dolly';
}
"""
README = """=== Hello Dolly ===
Contributors: matt, wordpressdotorg
Stable tag: 1.7.2
Tested up to: 6.9
Requires at least: 4.6

A tiny test plugin.

== Description ==

Lyrics.

== Changelog ==

= 1.7.2 =
* Earlier release.
"""


@pytest.fixture
def ws():
    root = sandbox.root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def plugin_zip(ws: Path, name="hello-dolly.zip", files=None) -> Path:
    files = files if files is not None else {"hello-dolly/hello.php": MAIN, "hello-dolly/readme.txt": README}
    z = ws / name
    with zipfile.ZipFile(z, "w") as zf:
        first = next(iter(files))
        if "/" in first:
            zf.writestr(first.split("/")[0] + "/", "")
        for n, d in files.items():
            zf.writestr(n, d)
    return z


def theme_dir(ws: Path, block=True) -> Path:
    from PIL import Image

    t = ws / "my-theme"
    (t / "templates").mkdir(parents=True)
    (t / "style.css").write_text("/*\nTheme Name: My Theme\nVersion: 1.0.0\nRequires at least: 6.4\nTested up to: 6.6\n"
                                 "Requires PHP: 7.4\nLicense: GPLv2 or later\nLicense URI: https://gnu.org\n"
                                 "Text Domain: my-theme\n*/\n")
    if block:
        (t / "templates" / "index.html").write_text("<!-- wp:post-content /-->")
        (t / "theme.json").write_text(json.dumps({"version": 3, "settings": {"color": {}}}))
    else:
        (t / "index.php").write_text("<?php get_header();\n")
    Image.new("RGB", (1200, 900)).save(t / "screenshot.png")
    (t / "functions.php").write_text("<?php\nif ( ! defined( 'ABSPATH' ) ) { exit; }\nadd_theme_support( 'title-tag' );\n")
    return t


def test_headers_and_readme_parse():
    h = wordpress.file_headers(MAIN, wordpress.PLUGIN_HEADERS)
    assert h["Plugin Name"] == "Hello Dolly" and h["Version"] == "1.7.2" and h["Author URI"] == "http://ma.tt/"
    r = wordpress.parse_readme(README)
    assert r["name"] == "Hello Dolly" and r["headers"]["Stable tag"] == "1.7.2"
    assert r["short_description"] == "A tiny test plugin." and "Changelog" in r["sections"]


def test_validate_good_plugin_zip(ws):
    plugin_zip(ws)
    r = wordpress.validate("hello-dolly.zip")
    assert r["valid"], r["errors"]
    assert r["kind"] == "plugin" and r["slug"] == "hello-dolly" and r["main_file"] == "hello.php" and r["version"] == "1.7.2"
    assert any(f["rule"] == "direct-access" for f in r["security"]["findings"])
    assert r["php_lint"]["status"].startswith("ran php -l" if HAS_PHP else "skipped")


def test_validate_catches_structure_and_dev_files(ws):
    plugin_zip(ws, "bad.zip", {"hello.php": MAIN, "readme.txt": README.replace("1.7.2\nTested", "1.0\nTested"),
                               "other/x.txt": "x"})
    r = wordpress.validate("bad.zip")
    assert not r["valid"] and any("one top-level folder" in e for e in r["errors"])
    plugin_zip(ws, "dev.zip", {"hello-dolly/hello.php": MAIN, "hello-dolly/readme.txt": README,
                               "hello-dolly/.env": "K=1", "hello-dolly/node_modules/a.js": "1",
                               "__MACOSX/hello-dolly/._hello.php": "x"})
    r = wordpress.validate("dev.zip")
    assert not r["valid"] and any(".env" in e for e in r["errors"]) and any("node_modules" in w for w in r["warnings"])
    plugin_zip(ws, "tag.zip", {"hello-dolly/hello.php": MAIN, "hello-dolly/readme.txt": README.replace("Stable tag: 1.7.2", "Stable tag: 1.6")})
    r = wordpress.validate("tag.zip")
    assert any("Stable tag 1.6 does not match" in e for e in r["errors"])
    plugin_zip(ws, "Bad Slug.zip", {"Bad Slug/x.php": MAIN})
    assert any("not a valid slug" in e for e in wordpress.validate("Bad Slug.zip")["errors"])


def test_unsafe_zip_refused(ws):
    with zipfile.ZipFile(ws / "evil.zip", "w") as zf:
        zf.writestr("../../wp-config.php", "<?php")
    with pytest.raises(ArchiveError, match="not safe"):
        wordpress.validate("evil.zip")


@pytest.mark.skipif(not HAS_PHP, reason="php not installed")
def test_php_lint_reports_syntax_error(ws):
    plugin_zip(ws, "syn.zip", {"hello-dolly/hello.php": MAIN + "\nfunction broken( { \n", "hello-dolly/readme.txt": README})
    r = wordpress.validate("syn.zip")
    assert not r["valid"] and any("php -l" in e for e in r["errors"])


def test_security_checklist_rules(ws):
    d = ws / "risky-plugin"
    d.mkdir()
    (d / "risky-plugin.php").write_text("""<?php
/* Plugin Name: Risky */
add_action( 'wp_ajax_save', 'risky_save' );
function risky_save() {
    global $wpdb;
    $id = $_POST['id'];
    $wpdb->query( "DELETE FROM t WHERE id = $id" );
    echo $id;
    eval( base64_decode( 'ZWNobyAxOw==' ) );
    shell_exec( 'ls' );
    $o = unserialize( $_COOKIE['x'] );
}
""")
    r = wordpress.security_review(d)
    rules = {f["rule"] for f in r["findings"]}
    assert {"direct-access", "nonce", "capability", "unsanitized-input", "sql-no-prepare", "unescaped-output", "eval",
            "obfuscation", "shell", "unserialize-input"} <= rules
    (d / "risky-plugin.php").write_text("""<?php
/* Plugin Name: Safe */
defined( 'ABSPATH' ) || exit;
add_action( 'admin_post_save', function () {
    check_admin_referer( 'save' );
    if ( ! current_user_can( 'manage_options' ) ) { wp_die(); }
    $id = absint( $_POST['id'] ?? 0 );
    echo esc_html( $id );
} );
""")
    r = wordpress.security_review(d)
    assert r["counts"] == {"high": 0, "medium": 0, "low": 0}, r["findings"]


def test_guard_insertion_respects_declare_and_namespace():
    t = "<?php\n/**\n * Plugin Name: X\n */\ndeclare(strict_types=1);\nnamespace Foo\\Bar;\n\nuse Baz;\nfunction a() {}\n"
    new = wordpress.add_guard_text(t)
    assert new.index("namespace Foo") < new.index("ABSPATH") < new.index("use Baz")
    assert new.startswith("<?php\n/**\n * Plugin Name: X\n */")
    assert wordpress.add_guard_text(new) is None
    assert wordpress.add_guard_text("<?php\n// Silence is golden.\n") is None
    assert wordpress.add_guard_text("<?php\nnamespace A {\n}\n") is None
    assert "WP_UNINSTALL_PLUGIN" in wordpress.add_guard_text("<?php\ndelete_option('x');\n", uninstall=True)


def test_bump_guard_and_package_zip_via_tools(ws):
    plugin_zip(ws)
    t = tools.build()
    ctx = tools.ToolContext()
    ok, out = tools.call(t["wp_bump_version"], ctx, {"path": "hello-dolly.zip", "version": "1.8.0",
                                                     "changelog": "Add ABSPATH guard", "out": "dist/hello-dolly-bumped.zip"})
    assert ok, out
    assert "1.7.2 -> 1.8.0" in out and "valid" in out
    ok, out = tools.call(t["wp_add_guard"], ctx, {"path": "dist/hello-dolly-bumped.zip", "out": "dist/hello-dolly.zip"})
    assert ok and "hello.php" in out, out
    with zipfile.ZipFile(ws / "dist" / "hello-dolly.zip") as zf:
        assert zf.namelist() == ["hello-dolly/", "hello-dolly/hello.php", "hello-dolly/readme.txt"]
        main = zf.read("hello-dolly/hello.php").decode()
        readme = zf.read("hello-dolly/readme.txt").decode()
    assert "Version: 1.8.0" in main and "defined( 'ABSPATH' )" in main
    assert main.index("Plugin Name") < main.index("ABSPATH") < main.index("function hello_dolly_get_lyric")
    assert "Stable tag: 1.8.0" in readme and "= 1.8.0 =\n* Add ABSPATH guard" in readme
    r = wordpress.validate("dist/hello-dolly.zip")
    assert r["valid"] and r["version"] == "1.8.0"
    assert not any(f["rule"] == "direct-access" for f in r["security"]["findings"])
    with zipfile.ZipFile(ws / "hello-dolly.zip") as zf:  # original untouched
        assert "Version: 1.7.2" in zf.read("hello-dolly/hello.php").decode()


def test_bump_folder_constants_and_semver(ws):
    d = ws / "my-plugin"
    d.mkdir()
    (d / "my-plugin.php").write_text("<?php\n/**\n * Plugin Name: My Plugin\n * Version:     2.3.4\n */\n"
                                     "define( 'MY_PLUGIN_VERSION', '2.3.4' );\n")
    (d / "readme.txt").write_text("=== My Plugin ===\nStable tag: 2.3.4\n\nShort.\n")
    r = wordpress.bump_folder(d, "minor", "New feature")
    assert r["new"] == "2.4.0"
    txt = (d / "my-plugin.php").read_text()
    assert " * Version:     2.4.0\n" in txt and "'MY_PLUGIN_VERSION', '2.4.0'" in txt
    assert "== Changelog ==\n\n= 2.4.0 =\n* New feature" in (d / "readme.txt").read_text()
    assert wordpress.next_version("1.9", "patch") == "1.9.1" and wordpress.next_version("1.2.3", "major") == "2.0.0"
    with pytest.raises(ArchiveError):
        wordpress.next_version("1.0", "bogus")


def test_theme_validation_block_and_classic(ws):
    t = theme_dir(ws)
    r = wordpress.validate(str(t))
    assert r["valid"] and r["kind"] == "theme" and r["block_theme"] and r["screenshot"]["size"] == [1200, 900]
    (t / "theme.json").write_text("{bad json")
    assert any("theme.json" in e for e in wordpress.validate(str(t))["errors"])
    shutil.rmtree(t)
    t = theme_dir(ws, block=False)
    (t / "index.php").unlink()
    assert any("index.php" in e for e in wordpress.validate(str(t))["errors"])


def test_package_folder_excludes_dev_files(ws):
    t = theme_dir(ws)
    (t / ".git").mkdir()
    (t / ".git" / "config").write_text("x")
    (t / "node_modules" / "a").mkdir(parents=True)
    (t / "node_modules" / "a" / "i.js").write_text("1")
    (t / "package-lock.json").write_text("{}")
    (t / "tests").mkdir()
    (t / "tests" / "t.php").write_text("<?php")
    r = wordpress.package(str(t), "my-theme.zip")
    names = zipfile.ZipFile(ws / "my-theme.zip").namelist()
    assert all(n.startswith("my-theme/") for n in names)
    assert not any(x in n for n in names for x in (".git", "node_modules", "package-lock", "tests/"))
    assert r["validation"]["valid"] and r["validation"]["kind"] == "theme"
    r2 = wordpress.package(str(t), "my-theme-2.zip", keep=["tests"])
    assert "my-theme/tests/t.php" in zipfile.ZipFile(ws / "my-theme-2.zip").namelist()
    assert r2["sha256"] != r["sha256"]
    with pytest.raises(ArchiveError, match="zip"):
        wordpress.package(str(t), "x.tar.gz")


def test_wp_policy(ws):
    from automoto import policy

    assert policy.classify("wp_validate", "safe", {"path": "a.zip"})[0] == "safe"
    assert policy.classify("wp_package", "risky", {"src": "a", "out": "b.zip"})[0] == "risky"
    assert policy.classify("wp_package", "risky", {"src": "~/.ssh", "out": "b.zip"})[0] == "blocked"


def test_crlf_files_keep_crlf(ws):
    d = ws / "crlf-plugin"
    d.mkdir()
    (d / "crlf-plugin.php").write_bytes(b"<?php\r\n/*\r\nPlugin Name: CRLF\r\nVersion: 1.0.0\r\n*/\r\nfunction f() {}\r\n")
    (d / "readme.txt").write_bytes(b"=== CRLF ===\r\nStable tag: 1.0.0\r\n\r\nShort.\r\n\r\n== Changelog ==\r\n\r\n= 1.0.0 =\r\n* x\r\n")
    wordpress.bump_folder(d, "1.0.1", "Fix")
    wordpress.add_guards(d)
    main = (d / "crlf-plugin.php").read_bytes()
    readme = (d / "readme.txt").read_bytes()
    assert b"Version: 1.0.1\r\n" in main and b"ABSPATH" in main and b"\n" not in main.replace(b"\r\n", b"")
    assert b"= 1.0.1 =\r\n* Fix\r\n" in readme and b"\n" not in readme.replace(b"\r\n", b"")
