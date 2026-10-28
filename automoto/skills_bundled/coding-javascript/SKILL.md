---
name: coding-javascript
description: Write, run and test JavaScript/TypeScript - Node projects, npm scripts, async code, testing and bundling.
category: coding
tools: write_file, edit_file, run_shell
apps: node, npm
status: live
---
# JavaScript / TypeScript

- Project: `npm init -y`, `"type": "module"` for ES modules, scripts in `package.json` (`test`, `build`, `lint`).
- TypeScript: `npm i -D typescript @types/node`, `npx tsc --init --strict`, compile with `npx tsc -p .`.
- Tests: `node --test` (built in, Node 18+) or `vitest`/`jest` if the project uses them. Run with `npm test`.
- Async: always `await` promises or return them; `try/catch` around `await`; `Promise.all` for parallel work;
  never mix callbacks and promises in one API.
- Safety: never `eval` user input, use `textContent` not `innerHTML` for untrusted text, validate JSON input.
- Lint/format: `npx eslint .`, `npx prettier --check .` when configured.
- Debug: `node --inspect`, `console.table`, check `node --version` matches `engines`.
- Pitfalls: `==` vs `===`, `this` in callbacks (use arrow functions), floating point, `forEach` with async,
  `JSON.parse` of empty strings, timezone handling with `Date`.
- Supply chain: prefer well-known packages, pin versions with a lockfile, run `npm audit`.
