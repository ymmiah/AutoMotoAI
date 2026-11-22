# Project map: languages, links, API calls and safe renames

Developer Studio → Tools → **Project map** helps you understand a project that mixes languages,
for example a TypeScript website, a Python API, SQL tables and a Rust add-on. It only **reads**
your files. It never runs, builds or uploads your code.

It is roadmap batch **V37–V40 ("polyglot intelligence")**. The technical notes are in
[DEVELOPER-STUDIO-V37-V40.md](DEVELOPER-STUDIO-V37-V40.md).

## The five steps

1. **Map your project.** Click **Map it**. The small ring card shows how many files were read,
   for example "412 files read of 430", your main languages and how many links there are between
   files. A *link* is one file using another, such as an `import`, `require`, `use`, `#include` or
   `<script src>`. **Broken links** point at a project file that isn't there. Type a file name in
   **Look up a file** to see what it uses and what uses it.
2. **What talks to what.** Click **Follow the calls**. The card shows, for example, "2 of 3 calls
   matched a route". Each match shows the frontend call, the server code that answers it and the
   data models it uses. Only addresses written out in the code are matched, so nothing is guessed:
   - **Maybe**: the address starts with a variable, such as `${BASE}/api/users`. These are shown but
     never counted.
   - **No match**: no route in this project has that address. Calls to outside websites are skipped.
3. **Your data models.** Tables and models from SQL, Prisma, Django, SQLAlchemy, TypeORM, Rails,
   Laravel and JPA, and how they connect.
4. **Rename safely.** Type the current name and the new name, then click **Preview changes**. You
   see every file and line that would change. Comments and text in quotes are left alone.
   AutoMoto stops if:
   - the name is defined in more than one file (you pick the one you mean);
   - the new name is already used;
   - the change would break Python syntax;
   - too many places would change at once.

   If the name is an API route handler or a data model, tick the box to say you've checked it.
   **Rename** shows a confirm dialog first, and **Undo rename** puts the files back. Tip: save a
   checkpoint in **Checkpoints (Git)** before you start. You need to allow changes for the project.
5. **Packages and bindings.** For big projects (monorepos) you see each part and its languages,
   which parts use which, where languages meet (for example Rust ↔ Python with PyO3), and generated
   files you shouldn't edit by hand. Each part lists its build and test commands with a copy
   button. AutoMoto doesn't run them. Copy them into your terminal when you're ready, for example:

   ```
   cd web && npm run build
   ```

## Safety

- Your project is untrusted. It's read with size limits, symbolic links are skipped, and private
  files such as `.env` and keys are never read.
- Nothing in your project is run, imported or built here. No network is used.
- The map lives in memory only and is rebuilt when files change.
- A rename is tied to a checksum of every file in the preview. If any file changed since then,
  nothing is written. Each file is replaced in one step, and if one fails, the others are put back.
