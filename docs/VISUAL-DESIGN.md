# Visual design, PowerPoint and image fidelity

This improvement is in development on `feature/visual-design-pptx-image-preservation`.
It is not part of the already-published Microsoft Store application.

## What's changed

AutoMoto's PowerPoint builder now uses native **editable PowerPoint vector shapes**
for icons, cards, visual metrics, timelines and custom-positioned elements. No
font downloads, subscription, remote icon set or screenshot-flattened decks.

### New `office_create_pptx` layouts

| Layout | When to use | Spec field |
|---|---|---|
| `cards` | A grid of benefits/features | `cards:[{title,text,icon}]` (1-6) |
| `metrics` | Real supplied KPIs | `metrics:[{value,label}]` (1-4) |
| `steps` | Workflow or implementation sequence | `steps:[{title,text}]` (2-5) |
| `image_text` / `hero` | Original photograph plus exact text | `image,text,image_side,alt` |
| `canvas` | Surgical positioning of individual objects | `elements:[{type,x,y,w,h,...}]` |

Canvas positions are **inches** on a 16:9 (13.333 × 7.5 in) slide, with a
reserved header and footer. For example:

```json
{
  "aspect": "16:9",
  "theme": {"background": "#F7F9FC", "accent": "#2E75B6"},
  "slides": [
    {"layout": "cards", "title": "Where we help", "cards": [
      {"title": "Security", "text": "Prevent and respond", "icon": "shield"},
      {"title": "Automation", "text": "Save manual effort", "icon": "settings"},
      {"title": "Analytics", "text": "Make evidence-led decisions", "icon": "chart"}
    ]},
    {"layout": "canvas", "title": "Original reference asset", "elements": [
      {"type": "image", "x": 0.6, "y": 1.7, "w": 5.4, "h": 4.8, "path": "uploads/original.png", "alt": "Original supplied photo"},
      {"type": "text", "x": 6.3, "y": 2.0, "w": 5.8, "h": 2.0,
       "text": "Original verified copy", "font_size": 28, "bold": true}
    ]}
  ]
}
```

All slide icons are PowerPoint shapes, not web images or icon fonts.
Slides automatically use contrasting foreground colours if a dark background
is selected and no explicit text colours are provided.

### Real local AI image generation

The `image_generate` tool runs a **real text-to-image model** via an
independently installed [ComfyUI](https://github.com/Comfy-Org/ComfyUI)
instance. It uses the official local ComfyUI HTTP API: `/models/checkpoints`,
`/prompt`, `/history/{prompt_id}`, `/view`.
Install ComfyUI and a compatible, locally available **SD/SDXL checkpoint**
first. Its default URL is `http://127.0.0.1:8188`, configurable via
`AUTOMOTO_COMFYUI_URL` to another **loopback address only**. No external
cloud image provider or API key is involved.

The tool intentionally refuses cloud/remote backends, redirects and unsafe
output paths. It never overwrites an existing file. These models consume
substantial memory/compute and their licences can restrict commercial use.
Other checkpoint architectures may require an exported custom API workflow,
which the built-in basic pipeline does not currently implement.

Use `image_models` to inspect installed checkpoints, then `image_generate`
for an **original** illustration or photograph, and provide the resulting
workspace path to `office_create_pptx`.

### Identity- and brand-preserving compositions

**Do not use text-to-image generation to recreate a supplied face, body,
product logo or exact typography.** Generative diffusion can modify all of
these even if the prompt says not to. This software cannot guarantee exact
identity preservation from a generative edit.

Use `image_compose` for supplied references. It creates a designed PNG from
the **original file contents** (aspect-fitted; no crops, reshaping, retouching
or generative reconstruction), optional unaltered logo and exactly supplied
text, keeping the originals on disk unchanged. PowerPoint's `image_text`
and `canvas` layouts can similarly embed the source picture without
redrawing it.

Some scripts require the right installed fonts and text-shaping support.
Check Bangla, Arabic and Urdu visually in the rendered result.

### Quality gate

Build → `office_check` → `office_review` / render with LibreOffice →
inspect every slide for contrast, overflow, image fidelity, missing icons,
and clipping. Correct actual issues before calling the deck finished.
Without LibreOffice/poppler a rendered preview is unavailable; don't claim
to have visually reviewed the output.

Testing and promotion to the Microsoft Store are separate actions.
