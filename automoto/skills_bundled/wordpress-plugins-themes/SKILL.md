---
name: wordpress-plugins-themes
description: Check, fix, version-bump and package WordPress plugins and themes as installable zips - header/readme validation, php -l, security checklist (ABSPATH guard, nonces, capabilities, sanitising/escaping).
category: web
tools: wp_validate, wp_security_review, wp_bump_version, wp_add_guard, wp_package, archive_extract, archive_read, edit_file, download_file
optional_apps: php (lint), phpcs + WordPress Coding Standards
status: live
---
# WordPress plugins and themes

An installable package is **one zip with one top folder named after the slug** (lowercase,
hyphens), e.g. `my-plugin.zip → my-plugin/my-plugin.php, my-plugin/readme.txt`.

1. **Validate first**: `wp_validate path=plugin.zip` (zip or folder). It checks the structure,
   the plugin header (`Plugin Name`, `Version`, `Requires at least`, `Requires PHP`, `License`,
   `Text Domain` = slug) or theme `style.css` header, `readme.txt` (`=== Name ===`, `Stable tag`
   = Version, `Tested up to`, short description ≤ 150 chars, ≤ 5 tags, Description/Changelog
   sections), themes' `index.php` or `templates/index.html`, `theme.json`, `screenshot.png`
   (1200x900), stray dev files, `php -l` on every PHP file, and a security checklist.
2. **Edit**: extract to a work folder (`archive_extract … dest=work/x strip_top=false`) and edit the
   PHP with `edit_file`. Keep WordPress coding style (tabs, Yoda conditions, prefixed function
   names). Never add remote code loading, `eval`, obfuscation or tracking.
3. **Security fixes** (what the checklist looks for):
   - direct-access guard at the top of every PHP file: `wp_add_guard` adds
     `if ( ! defined( 'ABSPATH' ) ) { exit; }` after the header comment (after `declare`/`namespace`);
   - forms/AJAX: `wp_nonce_field` + `check_admin_referer` / `check_ajax_referer`, and
     `current_user_can( 'manage_options' )` (or the right capability) before acting;
   - input: `sanitize_text_field( wp_unslash( $_POST['x'] ) )`, `absint()`, `sanitize_email()`;
   - output: `esc_html()`, `esc_attr()`, `esc_url()`, `wp_kses_post()`;
   - SQL: `$wpdb->prepare()` - never interpolate variables;
   - HTTP: `wp_remote_get()` instead of `file_get_contents('http…')` or cURL.
   The checklist is heuristic: read each finding, fix real issues, explain false positives.
4. **Version**: `wp_bump_version path=… version=1.8.0 changelog="…"` (or `patch|minor|major`) updates
   the header, `VERSION` constants, readme `Stable tag` and adds a changelog entry. On a zip it
   writes a new package to `out` and leaves the original untouched.
5. **Package**: `wp_package src=work/x/my-plugin out=dist/my-plugin.zip` - slug top folder, dev files
   (`.git`, `node_modules`, `tests`, lock files, `.env`, `__MACOSX`…) left out, deterministic.
6. **Verify**: `wp_validate` the final zip (0 errors, php -l clean) and `archive_list` it. Report the
   version change, the fixes, remaining warnings and the zip path + sha256.
   `run_phpcs=true` adds WordPress Coding Standards when phpcs is installed (optional).

Do not upload to WordPress.org or a live site, or install on a site, without the user's explicit OK.
