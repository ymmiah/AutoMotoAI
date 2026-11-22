# Developer Studio V37–V40: polyglot intelligence

Roadmap batch V37–V40 ("Phase 10" in the 64-version milestone tracker). It ships as one engine
module, `automoto/developer_polyglot.py`, one Tools card, **Project map**
(`automoto/web/static/developer-polyglot.js`), and the user guide [PROJECT-MAP.md](PROJECT-MAP.md).

| Version | Tracker definition | What ships |
|---|---|---|
| V37 Cross-language index | Multi-language symbols, imports, schema relationships and bounded incremental project graphs | `POST /polyglot/map` and `/polyglot/file`: an import graph across 20+ languages, outside packages, broken local links, cross-language links, hub files and data models and relations |
| V38 Cross-language traceability | Trace frontend requests through APIs, services and DB models, without fabricating unknown edges | `POST /polyglot/trace`: frontend call → route → handler → models, with *possible* and *unknown* kept separate and never counted |
| V39 Safe refactoring | Cross-file rename, impact maps, API contract checks, approval-gated code actions | `POST /polyglot/rename/preview`, `/apply` and `/undo` |
| V40 Monorepo and native bindings | Large monorepos, C/Python and Rust/JS bindings, generated code, mixed-language builds, memory budgets | `POST /polyglot/packages`: workspaces, packages, package dependencies, bindings, generated files and per-package commands (shown, never run) |

All endpoints are under `/api/developer/studio/polyglot`. They are local-only (`studio._auth`) and
limited to approved project roots (`studio._project`).

## Untrusted code: static analysis only

Project files are read through a no-follow descriptor, after `studio._path` and the V7 index
exclusions (secrets, `.env`, `node_modules`, build output, `generated`, dot-folders, symlinks and
junctions). Each file is capped at 256 KiB, must be UTF-8 and must have no NUL bytes. The analysis
uses regular expressions, Python `ast.parse` (parse only) and `tokenize`. The module imports no
process, network or dynamic-import APIs, and a test checks that. No project command is executed.
The V40 build and test commands are text for the user to copy.

## Budgets (memory and time)

The limits are 4,000 files, 1,500 folders, 2,000 items per folder, depth 14, 256 KiB per file,
32 MiB in total, 12 seconds per scan and 20,000 links. If a limit is hit, the result says
`truncated` with notes, and the UI says the map is partial. The cache holds up to 3 projects in
memory, keyed by root path, device and inode. A rescan re-parses only files whose SHA-256 changed
(`reused`/`parsed`/`removed` in `budget`). Nothing is written to disk (`index_persisted: false`).

## V37 import resolution

| Language | Resolved to a project file |
|---|---|
| Python | relative imports; absolute imports from the root and `src`, `lib`, `app`, `backend`, `server`, `python` |
| JS/TS/Vue/Svelte | relative specifiers with extension and index lookup; `tsconfig.json`/`jsconfig.json` `paths` aliases; web addresses such as `/static/x.js` by suffix |
| Go | `go.mod` module path → package folder |
| Rust | `mod x;` → `x.rs`/`x/mod.rs`; `use crate::/super::/self::` |
| Java/Kotlin/Scala | import path suffix |
| C/C++ | `#include "…"` (relative, root, `include/`, then by name; never reported broken, because include paths come from the build) |
| PHP, Ruby, CSS, HTML, Dart | `require`/`include`/`use`, `require_relative`, `@import`, `src`/`href`, relative imports |

Anything else becomes an outside package. A local-looking specifier that doesn't resolve is
reported as broken, with the file and line. Models are read from SQL `CREATE TABLE … REFERENCES`,
Prisma, Django, SQLAlchemy, TypeORM, ActiveRecord, Eloquent and JPA.

## V38 matching rules

Routes come from:

- FastAPI and Flask (including `APIRouter(prefix=…)` and `Blueprint(url_prefix=…)`) and Django `urls.py`
- Express-style routers, only when the file uses a server framework and the receiver is a known app or router
- Next.js `app/**/route.ts` exports and `pages/api`
- Spring, Go (`net/http` including `"GET /x"` patterns, chi, gin and echo), ASP.NET attributes and minimal APIs
- Laravel `routes/*.php` (`api.php` → `/api`) and Rails verbs and `resources`

Calls come from `fetch` (the method is read from the call's own options), axios-style clients and
`useSWR`/`$fetch`. Absolute URLs are kept only for localhost. Paths are normalised, so `${id}`,
`:id`, `{id}`, `<int:id>`, `[id]` and regex groups all become `{}`. An exact match wins over a
pattern match.

A call whose base is a variable is only ever *possible*. A call with no route is *unknown*, with
the reason. The ring counts only fixed-address calls, so "N of M calls matched a route" never
includes a guess. Handler models are names of known models used in the handler body, up to the
next route or 80 lines.

## V39 safe rename

- **Names.** Identifier names only. Reserved words in Python, JS/TS, Rust, Go, Java and C# are refused.
- **Definition.** It must be found in code: comments and strings don't count. More than one
  defining file, with no file chosen, is **blocked**, and the choices are listed. Scope is the
  defining file plus the files that import it.
- **Code-only edits.** Python uses `tokenize` NAME tokens. Other languages use a scanner that
  skips comments and strings, but keeps code inside JS template `${…}`.
- **Blocks:**
  - the name is defined in more than one file, or not found at all
  - a file that imports it defines the same name too
  - the new name already exists in scope
  - a Python file would no longer parse
  - more than 200 files or 2,000 places
- **Warnings:**
  - generated files are skipped
  - other files use the name without importing the definer
  - the map is partial
  - contract: a route handler or a data model; apply needs `contract_ok`
- **Apply** needs:
  - `confirmed`
  - a trusted project
  - the single-use preview hash, which expires after 10 minutes and covers project, names, scope and each file's SHA-256 and count
  - a re-read of every file with the same SHA-256 and the same count

  Writes keep the BOM and line endings and are atomic per file. On failure, the files already
  written are restored.
- **Undo** (last 10, in memory) only runs if every file still has its post-rename checksum.

## V40 packages

- **Workspace tools:** npm/Yarn workspaces, pnpm, Lerna, Nx, Turborepo, Cargo, `go.work`, Gradle `include`, Maven modules, uv and `.sln`.
- **Packages:** any folder with a manifest (npm, Cargo, Go, Maven, Gradle, CMake, node-gyp, Python/maturin, .NET, Composer, Ruby).
- **Package dependencies:** workspace names, plus Cargo and Go `path`/`replace` dependencies.
- **Bindings:** the CPython C API, pybind11, cffi, ctypes, setuptools `Extension`, PyO3/maturin, napi-rs, wasm-bindgen, Neon, Node-API/node-gyp, cgo, JNI, P/Invoke and Cython.
- **Generated files:** header markers (`DO NOT EDIT`, `@generated`, protoc and similar) and names (`*_pb2.py`, `*.pb.go`, `*.g.dart`, `*.designer.cs` and similar).

## Known limits

- **Symbols.** This is pattern-based static analysis, not a compiler, and there is no Tree-sitter
  or language-server resolution. Dynamic imports, re-exports through barrels, reflection, runtime
  route registration and string-built URLs are reported as unknown or not seen.
- **Rename.** It is limited to identifiers. It doesn't rename files, routes, database columns,
  string keys or uses in files that reach the name without importing its definer. Those are
  listed as warnings.
- **Builds.** V40 shows build commands but doesn't run fixture builds. Building still goes
  through the existing approval-gated Run my app and adapters.
- **Index.** The index is per-process memory only and is not shared between sessions.
