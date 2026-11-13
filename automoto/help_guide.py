"""Plain-language help for every Settings control, studio and tool.

The in-app Help page and the Settings tooltips both read :func:`guide`. Wording here is
for a person using the app, not for the model.
"""

from __future__ import annotations

from typing import Any

from automoto import brand

# id matches data-help on the Settings controls.
SETTINGS: tuple[dict[str, str], ...] = (
    {"id": "approval", "title": "Approval",
     "text": "Ask means AutoMoto stops before a risky step, such as running a command or writing outside its folder. Read-only lets it look but not change things. Auto-approve skips the question. Commands that touch passwords, keys or system folders stay blocked either way."},
    {"id": "new-chats", "title": "New chats",
     "text": "Assistant does the work: files, research and steps. Chat only answers and does not change files or run tools."},
    {"id": "offline-ai", "title": "Offline AI",
     "text": "Download a model onto this computer and chat without an API key. After the download, that model works with the internet off. You do not install Ollama or Python yourself. AutoMoto tunes llama.cpp for this PC: one thread per physical core, a context size and batch that fit the memory, memory mapping, flash attention when the engine supports it, a smaller KV cache on a 16 GB PC, and GPU offload when a Vulkan, CUDA or Metal build is available. The model marked Recommended for this PC is the one that fits. The first reply loads it; later replies start straight away. Tokens stream with a tokens-per-second count, Stop cancels the reply, and the model unloads after it has been idle so the memory is free again."},
    {"id": "offline-only", "title": "Offline only",
     "text": "Use only a model on this computer. Cloud models and web search stay off until you turn this off."},
    {"id": "gguf-model", "title": "Built-in model",
     "text": "The GGUF file the built-in engine will load. Switch, test or delete it from Settings > Offline AI."},
    {"id": "ollama-model", "title": "Ollama model",
     "text": "Optional. If you already installed Ollama, you can pick one of its models here. It is not required."},
    {"id": "theme", "title": "Theme",
     "text": "Dark, light, or match the Windows theme. This is saved on this computer."},
    {"id": "accent", "title": "Accent",
     "text": "The highlight colour for buttons and the current chat. Pick a swatch or a custom colour."},
    {"id": "folders", "title": "Folders",
     "text": "The assistant starts in its own sandbox folder. Add a project folder when you want it to read that project too. Anything outside the sandbox still asks first. Home directories that are too broad, SSH keys, .env files and browser profiles are refused."},
    {"id": "provider-order", "title": "Provider order",
     "text": "When a chat is set to Auto, AutoMoto tries these services from the top. If one errors, it moves to the next. Save order keeps your list. Use the recommended order puts the defaults back."},
    {"id": "provider-keys", "title": "Keys for this tab",
     "text": "Paste a provider key to use it until you close this window. It is not written to disk. A key already in the .env file works without pasting it here."},
    {"id": "test-keys", "title": "Test keys",
     "text": "Sends one tiny request to each cloud model this key can use, so you can see which ones answer. It does not spend a long chat."},
    {"id": "connectors", "title": "Connectors",
     "text": "Optional links to services such as a design tool. The first use opens a browser sign-in. Tokens stay in .env and are not shown here. Each connector action still asks before it runs."},
    {"id": "auto-memory", "title": "Memory",
     "text": "AutoMoto can remember stable facts you tell it, such as how you like answers written. You can read and delete those memories on the Memory page."},
    {"id": "advanced-tools", "title": "Tools and skills",
     "text": "The assistant picks tools itself. The raw list is only here so you can see what exists. You do not choose tools in the chat."},
)

PAGES: tuple[dict[str, str], ...] = (
    {"id": "chat", "title": "Chat",
     "text": "The home of the app. Type what you want finished. Assistant mode does the steps. Chat mode only replies. The list on the left is your saved conversations. New chat, search and Quick commands stay at the top. Studios, Library and chats scroll in the middle, including on a short window or a phone-width layout. Settings, Help and the version stay at the bottom. A long chat list only draws the rows you can see."},
    {"id": "tasks", "title": "Tasks",
     "text": "Runs that are still going, waiting for you to approve a step, or finished. Open one to see the plain-language progress."},
    {"id": "memory", "title": "Memory",
     "text": "Facts AutoMoto has saved about how you like to work, plus a short journal. Delete anything you do not want kept."},
    {"id": "routines", "title": "Routines",
     "text": "A saved request that can run on a schedule while AutoMoto is open. You still approve risky steps."},
    {"id": "files", "title": "Files",
     "text": "The sandbox folder: uploads, exports and files the assistant made. You can open, download, zip and unzip them here."},
    {"id": "settings", "title": "Settings",
     "text": "Assistant behaviour, offline models, appearance, folders and cloud providers. The page opens from the last saved settings straight away. The model list, hardware details and disk space fill in afterwards. Saved on this computer. Keys you paste stay in this window only."},
    {"id": "help", "title": "Help",
     "text": "This page. It explains each setting, studio and tool in ordinary language."},
)

STUDIO_PLAIN: dict[str, str] = {
    "document": "Write and edit documents. You keep the draft, export Word, and can ask a local model to suggest a proofread or a summary. Drop a file on the studio to import it. A task stays in the queue if another is already running, and the studio stays usable. With Offline on, the review uses the built-in engine on this PC. Nothing is sent to a cloud model unless you have chosen one for the chat.",
    "research": "Collect sources, compare quotes and keep the evidence next to the claim. Publishing a citation still asks you before it writes a file.",
    "spreadsheet": "Open a workbook, calculate, and export a spreadsheet or an invoice. The original file stays the source of truth until you export a new one.",
    "visual": "Make and edit images, simple layouts and exports such as PNG, PDF or slides. Brand colours and motion stay in this studio.",
    "developer": "Open a local project, read and edit source with a checksum on each save, and run a language tool only after you approve it. It does not upload your project.",
    "developer-ios": "A step-by-step page for an iPhone build. Nothing is sent to Apple until you tick the box and press Send to Apple.",
}


def guide() -> dict[str, Any]:
    """Everything the Help page renders. Tool descriptions come from the tool list itself."""
    from automoto import config
    from automoto.studio_registry import load_studios
    from automoto.tools import build

    studios = []
    for spec in load_studios():
        studios.append({
            "id": spec.id,
            "title": spec.name,
            "text": STUDIO_PLAIN.get(spec.id) or spec.words or spec.how,
        })
    known = {item["id"] for item in studios}
    for studio_id, text in STUDIO_PLAIN.items():
        if studio_id not in known:
            studios.append({"id": studio_id, "title": studio_id.replace("-", " ").title(), "text": text})
    tools = []
    for tool in build(desktop=config.desktop_enabled()).values():
        if getattr(tool, "hidden", False):
            continue
        tools.append({"name": tool.name, "description": tool.description, "level": tool.level,
                      "group": tool.group})
    return {
        "brand": brand.name(),
        "intro": (
            f"{brand.short()} is a chat that can finish work: writing, files, research and code. "
            "You describe the result. It chooses the steps and asks before anything risky. "
            "The raw tool list stays under Settings > More."
        ),
        "settings": list(SETTINGS),
        "pages": list(PAGES),
        "studios": studios,
        "tools": tools,
        "shortcuts": [
            {"keys": "Ctrl+N", "text": "New chat. In a browser, Ctrl+Shift+O also works."},
            {"keys": "Ctrl+B", "text": "Show or hide the sidebar."},
            {"keys": "Ctrl+K", "text": "Search chats and commands."},
            {"keys": "Enter", "text": "Send. Shift+Enter adds a line."},
            {"keys": "Esc", "text": "Stop a run, or close a dialog."},
            {"keys": "F1", "text": "Open this guide."},
        ],
    }
