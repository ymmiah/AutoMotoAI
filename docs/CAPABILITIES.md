# What you can ask AutoMoto to do

You don't need to know any tool names. Type what you want in your own words, or attach a file, and AutoMoto
works out the steps. This page lists the kinds of things people ask for, with examples you can copy, and what
you get back.

> **How it works, in one line.** A built-in planner reads your request and any attached files (`.pptx`, `.docx`,
> `.xlsx`, `.pdf`, `.csv`, `.zip`, code, images…), decides what kind of task it is, and gives the AI only the
> few tools and the one playbook ("skill") that task needs. If it needs something else halfway through, it asks
> for it. Risky steps (writing outside `scratch/`, running commands, apps, connectors) still wait for your
> **Approve**.

## Files you attach

Click 📎 (or drag a file in). You'll see ideas for that file above the message box. Sending the file with no
text gives you a summary.

| You attach | Ideas you'll see | Try typing |
|---|---|---|
| PowerPoint `.pptx` | Summarise my slides · Speaker notes · Improve my deck | *what are the speaker notes in my deck?* |
| Word `.docx` | Summarise it · Proofread & improve · Turn into a PDF | *proofread my report and fix the wording of the intro* |
| Excel `.xlsx` | Explain this sheet · Find problems | *what's the total in my budget spreadsheet?* · *change Food to 300* |
| PDF | Summarise · Pull out the key facts | *read page 2 of this pdf* |
| CSV / JSON / YAML / XML / SQLite / logs | Key insights · Clean it up · Make a chart | *what's the revenue per product? units times price* · *find the errors in my log file* |
| `.zip` / `.tar.gz` / `.7z` | What's inside · Unzip & edit | *unzip project.zip, change the app to print 'hi', and zip it again* |
| WordPress plugin or theme `.zip` | Check my plugin · Fix & repackage | *check the attached WordPress plugin zip, fix any problems and repackage it* |
| Code (`.py`, `.js`, `.php`…) | Explain this code · Find bugs | *my average function is wrong, test fails. fix it* |
| Image | Describe the image · Resize it | *make an 800px wide copy of my photo* |
| Audio / video | Trim / convert | *convert my video to mp4 and trim it to 30 seconds* (needs free ffmpeg) |

## Making documents

| Ask for | Example | You get |
|---|---|---|
| A Word report or essay | *Make a Word report about the benefits of regular exercise for students, with headings, a table of contents and references.* | A `.docx` with a title page, real headings, contents, page numbers and Harvard references, checked before it says "done" |
| A letter or CV | *write me a cover letter for a junior developer job at a bank as a docx* | A tidy Word file |
| Slides | *Make a 6-slide PowerPoint about time management for students, with speaker notes.* | A `.pptx` with one idea per slide and notes, checked for text overflowing |
| Slides from a document | *turn my report into a short presentation* | A deck built from your file |
| A spreadsheet | *build me a monthly budget spreadsheet with formulas and a chart* | An `.xlsx` with live formulas (recalculated and checked), number formats and a chart |
| A PDF | *convert my report to PDF* | A PDF next to your file (needs free LibreOffice) |

Typos are fine: *"can u make a presntation abt dogs 3 slids"* works.

## Data

*Analyse the attached data and give me the key insights* · *show only the North rows with more than 5 units* ·
*remove the duplicate rows and save a clean copy* · *convert my csv to excel* · *turn people.json into a csv* ·
*how much has each customer spent? the db is uploads/shop.sqlite* · *show me the last lines of app.log*

AutoMoto profiles the file first (columns, types, empty cells), then filters, groups and totals it. It quotes
the numbers the tools return and never makes numbers up.

## Code

*explain what calc.py does* · *I get ZeroDivisionError in safe_div, fix it* · *write a pytest test for safe_div* ·
*write a python script that prints the first 10 fibonacci numbers and run it* · *make a simple html landing page*

It reads the code, reproduces the problem (running the tests after you approve), makes the smallest fix and runs
the tests again to prove it. In VS Code, use the AutoMoto panel's ideas or right-click a file.

## Web research

*Research the latest news about renewable energy in the UK and give me 5 bullets with links* ·
*summarise https://example.org/article* · *research the history of the bicycle and put it in a word document with sources*

It searches the web (free, no key), reads the best pages and answers with links. It refuses private and local
addresses (for example `localhost` or `169.254.169.254`).

## Writing (no files needed)

*write a short poem about autumn* · *draft a polite email to my lecturer asking for an extension* ·
*translate 'good morning' into Bengali* · *explain recursion like I'm 10* · *write a haiku and save it as haiku.txt*

## Terminal and apps

*how much disk space do I have left?* · *what's the git status of my project?* · *install the requests package*

Every command waits for your **Approve**; dangerous ones (like `rm -rf /`) are always refused. Local apps
(ffmpeg, ImageMagick, LibreOffice, LaTeX, git…) are used when they're installed.

## Memory, routines and connectors

* *Remember that I prefer short answers with bullet points.* · *what do you know about me?*
* *every morning at 8 give me the top 3 tech headlines* · *remind me every 2h to drink water* (runs while
  AutoMoto is open; it asks before saving the routine)
* *list my open github issues* · *summarise my notion meeting notes page* (after you connect the service in
  **Settings → Connectors**; AutoMoto asks before every connector call)

## Coming in the next beta

These are on `main` and will be in the next beta build.

* **It learns about you as you chat.** Say *my name is Sam*, *I prefer British English*, *I live in Leeds* or
  *always use metric units* and it remembers (you'll see "Remembered: …" under the answer). Passwords, keys, card
  numbers and e-mail addresses are never saved. See, edit or delete every fact in **Memory**, or switch
  *Learn from my messages* off.
* **Tidy folders.** Your workspace has `uploads/` (your files), `artifacts/` (everything it makes, one folder per
  task and date, e.g. `artifacts/2026-10-31-budget-report/`), `projects/`, `memory/` (with a readable
  `MEMORY.md` copy and your research library), `skills/`, `logs/` (one line per task) and `scratch/`. New files in
  `artifacts/` need no approval; overwriting or editing still asks. Each answer ends with **Files made** links.
* **Your own research library.** *save the FastAPI docs to my library* (follows `robots.txt`, same site only) ·
  *add uploads/lecture.srt to my library* · *search my library for middleware* · *what are developers saying on
  hacker news / stack overflow / github / bluesky about local LLMs* · *read this RSS feed*.
* **Code checks without running anything.** *inspect my project for risky code* (TLS checks off, `eval`, shell
  calls, secrets in files) · *check the header on my local site http://127.0.0.1:3000* (only sites you allow in
  `AUTOMOTO_BROWSER_ORIGINS`; asks first; never in hosted mode).
* **Help running your own server.** *help me run AutoMoto on Oracle Cloud for free* · *I want to use it from my
  phone* · *is my computer ready to host it?* It checks your computer, makes the files (Docker Compose, Cloudflare
  Tunnel scripts, Oracle cloud-init, Caddy, a checklist) and walks you through it, asking before any command.
  Kid-simple guide: [SERVER-SETUP.md](SERVER-SETUP.md).

## How this is tested

Every example on this page is one of the **92 scenarios** in [`evals/scenarios.py`](https://github.com/ymmiah/AutoMotoAI/blob/main/evals/scenarios.py).
`python -m evals` runs each one through the real agent loop with real sample files (a real `.pptx`, `.docx`,
`.xlsx`, PDF, CSV, SQLite database, WordPress plugin zip, buggy Python project…) and checks the result: the
right kind of task was recognised, the AI was only offered tools that fit, files were created and open cleanly,
the content is right, risky steps asked first and unsafe ones were refused. It also runs in CI on every change.

| | Before (5.6.0 Beta 2) | Now (5.6.0 Beta 3) |
|---|---|---|
| Tools the AI could see | all 48, every request (about 24 KB of tool descriptions) | 41 in total, but only **10-22 per task** (median 13, about 4-10 KB) |
| Tools for reading files | 6 different ones (`office_read`, `pdf_text`, `data_read`, `text_tail`, `image_info`, `read_file`) | **1**: `read_file` reads anything |
| Scripted-model scenarios | none | **86/86 pass** (85/86 with the right tools on the first try; the other one asks for more tools mid-task, as designed) |
| Real-model scenarios | none | `python -m evals --real` runs the same requests against your own keys |

`python -m evals --real` needs a working AI key in `.env`; it reports how many scenarios a real model gets right.
