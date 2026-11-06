# Visual Studio v9 — private brand kits and premium templates

**Internal development only. No Microsoft Store publication.**

## Reusable brand-kit library

A kit holds a name, nine validated `#RRGGBB` colour tokens (background, ink, muted, accent, card, border, and three tones), heading/body sizes from 12–90, and optionally a reference to an existing uploaded logo. The ink/background contrast must be **at least 4.5:1**. Kits are held in each authenticated user's own workspace, with a maximum of 30 saved kits and no remote image or model dependencies.

To use: open **Visual Studio → Brand kits**, use the current palette or load a saved kit, edit the colours and sizes, then save. **Apply to page** or **Apply to all pages** runs a read-only authoritative quality check on the entire candidate document before committing any change. If one page fails, nothing is applied. Each modified page keeps its own Undo entry. A proposal is discarded if the document changes while it is being validated.

Only native layers with explicit `auto_fill`, `auto_stroke` or `auto_colour` tags are recoloured. Font sizes change only on text deliberately marked `style_role: heading` or `style_role: body`. The text inspector lets authors assign either role; manually editing a font size removes automatic sizing. User wording, manual colours, locked/hidden layers, source images and original logos are not rewritten.

**Place logo** is a separate explicit action that references an uploaded, valid workspace image and inserts it in an available area as a native image layer after a server preview check. Kit creation does not alter, copy or download a logo. Removing a saved kit leaves existing designs unchanged.

## Native premium templates

- **Brand launch:** editable purpose and promise content blocks.
- **Executive brief:** editable outcomes, evidence and next steps.

Both use existing rendered shapes, icons and text, not flattened images. The templates are editable starting points; they do not claim to generate a company's actual branding automatically.

## Endpoints

`GET /api/visual/studio/brand-kits/list` and `/load?path=…`; `POST /api/visual/studio/brand-kits/validate`, `/save`, `/delete`; and read-only `POST /api/visual/studio/document/validate`. Auth, origin and workspace checks, file limits and quota controls remain in place.

## Validation and limitations

Run `python -m pytest -q tests/test_visual_brand_kits.py tests/test_visual_documents.py tests/test_visual_studio.py` and `cd apps/desktop && npm run test:ui`. Tests include private CRUD, logo checksums, invalid colour and contrast rejection, non-writing cross-page validation, exact text/manual-style preservation, Undo and browser integration.

The renderer uses built-in fonts and native PowerPoint text. **Arbitrary custom-font embedding, licensed font management, full grid systems and master-page controls are not included** in this increment. PDF pages are flattened; PPTX retains native supported text and shapes.

**Release policy:** keep this milestone on a development PR pending full CI and manual review. Defer Microsoft Store submission until the wider AutoMoto AI product is complete.
