# Studios the assistant can use

One request is enough. The assistant chooses the studio, does the steps, and names the file it made.
You do not pick tool names. The raw tool list stays on **Tools (advanced)**.

Saves, exports, trust and program runs wait for **Approve**. A repair or an offline AI review returns a
proposal and does not change the file. Hosted servers never run a program on the host. Offline mode
removes network tools such as DOI lookup.

## What it can do

| Studio | Ask for | You get |
|---|---|---|
| Document Assistant | *write my thesis chapter with Harvard refs and export Word* | A new `.docx` with the references you supplied. A wording fix is a new copy; the original stays. |
| Spreadsheet and invoices | *make an invoice for Northwind and an email-ready PDF* | A draft PDF. It is not sent, issued or marked paid. Formula workbooks and a cash summary from numbers you typed are the same studio. |
| Research Studio | *what evidence answers the research question about the Friday beta in my notes?* | Quotes from your files, checksum-pinned. A DOI check uses the network and is skipped offline. Citations are not invented. |
| Visual Studio | *make a promo GIF in my brand colours* or *make a 3-slide promo deck* | A real GIF or PPTX. *repair the layout and do not apply it* returns the proposal only. |
| Developer Studio | *fix the bug in this repo file and show the diff* | A diff against the checksum it just read. The save is refused if the file changed. Not available on a hosted server. |
| iPhone apps (inside Developer Studio) | *make an iPhone app that counts taps* | A project on this computer, then a build and an install on a real iPhone when the tools are there. The App Store send waits for the **Send to Apple** button. |

Developer Studio on this version is the explorer, editor, search, symbols, diff, save, language detection,
already-registered adapters, and iPhone apps (`automoto/developer_ios_studio_tools.py`). LaTeX, BibTeX,
TeX build, Typst, Quarto and frontend preview are not included yet. When those modules are added as below,
the assistant picks them up by itself.

## How to add a new studio so the assistant uses it

Add `automoto/<name>_studio_tools.py` (the name must end in `_studio_tools.py`). The module sets `STUDIO`
to a `StudioSpec` from `automoto.studio_registry`. A third-party package can instead expose an entry point
in the group `automoto.studios` that returns a `StudioSpec`. `AUTOMOTO_STUDIO_PATH` is an extra folder of
the same files, for a studio that is not inside the package. Restart is not required for a path added
before the next request; a broken module is logged and skipped.

```python
from automoto.studio_registry import S, StudioSpec, call_studio, obj, studio_request
from automoto.tools import Tool

def ping(ctx, name: str = "world") -> str:
    return call_studio(some_studio.ping, studio_request("POST"), name)

STUDIO = StudioSpec(
    id="ping",
    name="Ping studio",
    words=r"\bping studio\b",
    exts=(".ping",),
    how="Call ping_studio, then tell the user the result.",
    labels={"ping_studio": "Pinging"},
    hosted_ok=False,
    tools=(Tool("ping_studio", "Ping.", obj({"name": S}), "safe", ping),),
)
```

Do not edit `tools.py` or `planner.py`. `tools.build()` and the planner read the registry.

The registry, not the new module, enforces the safety rules:

| Field | Effect |
|---|---|
| Tool name like `save`, `export`, `run`, `trust`, `pdf` | Forced to **risky** (Approve), even if the module says safe. |
| `host_exec` | Omitted when local apps are off. Hosted mode always turns local apps off, so these tools never run on a hosted server. |
| `hosted_ok` | Default false. A studio stays out of hosted mode until this is true. `local_only` tools stay out even then. |
| `online_only` | Removed in offline mode. |
| `needs_local_apps` | The whole studio is omitted when local apps are off. |

Call the existing studio function with `call_studio` and `studio_request`. Do not reimplement the check.
If the studio requires a checksum or a confirmation flag, pass the checksum the user already saw and set
the flag only inside the tool that Approve already allowed. If the studio returns a proposal, return that
proposal. Do not add a tool that applies it behind the user's back.

`words` is the regex for the request. `exts` are uploaded suffixes such as `.docx` or `.py`. `how` is the
playbook injected into the prompt. `labels` are the plain sentences shown while the tool runs. `skills`
names a folder in `automoto/skills_bundled/<skill>/SKILL.md` when the model needs a longer playbook.

A module that raises on import is logged (`skipping broken studio module ...`) and the assistant still
starts. Reuse of a built-in capability id such as `word` or `code` is ignored for planning so the new
studio cannot replace one.
