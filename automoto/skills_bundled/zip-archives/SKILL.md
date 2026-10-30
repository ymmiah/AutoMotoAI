---
name: zip-archives
description: Open, inspect, extract, edit and re-pack .zip/.tar.gz/.tgz/.tar.bz2/.tar.xz/.gz archives (and read .7z/.rar) safely - zip-slip, symlinks, zip bombs and encrypted members handled.
category: files
tools: archive_list, archive_read, archive_extract, archive_create, archive_repack, download_file
optional_apps: 7-Zip or py7zr (.7z), unar (.rar)
status: live
---
# Archives (zip, tar, gz, 7z, rar)

Archives from other people are **untrusted data**. Never run anything inside them.

1. **Look first**: `archive_list path=… check=true` - it reports the format, file count, unpacked size,
   compression ratio, unsafe names (`../`, absolute paths, drive letters), symlinks/hardlinks,
   nested archives and encryption. If it says UNSAFE, stop and tell the user why - do not try to
   work around it. `archive_list` shows the tree; `archive_read member=…` reads one text file
   without extracting (readme, manifest, main source file).
2. **Extract into a new folder**: `archive_extract path=x.zip dest=work/x` (inside the workspace;
   `scratch/…` needs no approval). Options: `strip_top=true` drops a single top folder,
   `members=[…]` extracts only some paths, `skip_links=true` skips link members instead of refusing,
   `nested=true` also unpacks archives inside (depth-limited). Nothing is written unless the whole
   extraction succeeds.
3. **Encrypted**: if a password is needed, ask the user. Pass it only as `password=…`; it is masked
   in logs. Never guess or brute-force passwords. AES zips need 7-Zip.
4. **Work on the files** with `read_file` / `edit_file` / `search_files` (or the office, data and
   wp_* tools).
5. **Re-pack**: `archive_create sources=[work/x/my-folder] out=dist/my-folder.zip`. Defaults:
   deterministic (sorted, fixed timestamps - same input, same bytes), excludes `.git`,
   `node_modules`, `.DS_Store`, `__MACOSX`, `.env`, `__pycache__`, editor folders; symlinks are
   skipped. `root_name` sets the top folder ('' = none); `exclude=['tests','*.map']` adds patterns.
   `archive_repack` cleans or converts an archive in one step (e.g. strip `__MACOSX`, zip → tar.gz).
6. **Verify**: `archive_list` the result and report the path, file count, size and sha256.

Downloads: `download_file url=… path=downloads/x.zip` (public http(s) only; internal addresses are
blocked; archives are safety-checked on arrival). Formats you can write: zip, tar, tar.gz/tgz,
tar.bz2, tar.xz, and single-file gz/bz2/xz. 7z/rar are read-only.
