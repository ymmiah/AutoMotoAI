# Windows window frame

The Windows app does not use the system minimize / maximize / close caption. It draws its own bar: **Menu**, the AutoMoto name, and minimize, maximize and close. The glyphs are AutoMoto's, not the Windows caption font, so the window is not pretending to be system UI.

macOS and Linux builds keep the native frame. The bar stays in the page and is hidden unless the window asks for it.

## How it is built

| Piece | Where | What it does |
|---|---|---|
| No system caption | `WebviewWindowBuilder` in `apps/desktop/src-tauri/src/main.rs` | On Windows only: `decorations(false)`, a window shadow, and a dark page background while the UI loads |
| Caption in the page | `automoto/web/index.html`, `login.html`, `apps/desktop/dist/index.html`, both `app.css` files | A 40px bar. Hidden until `html[data-chrome="custom"]` |
| Behaviour | `apps/desktop/src-tauri/src/chrome.js` (copied to `automoto/web/static/` and `apps/desktop/dist/`) | Menu, min / max / close, double-click fallback, restore icon. The Windows window runs this script on every page and sets `__AUTOMOTO_FORCE_CHROME__` |
| Hit-testing | `apps/desktop/src-tauri/src/chrome.rs` | `WM_NCHITTEST` subclass |
| Who may call it | `apps/desktop/src-tauri/capabilities/chrome.json` | Drag, min, max, close, and Menu actions only |

The native **AutoMoto / Edit / Help** menu stays attached so Ctrl+Shift+H, Ctrl+R, Ctrl+Q and F1 keep working. **Menu** in the caption opens the same actions. Copy and paste stay on Ctrl+C / Ctrl+V inside the page.

### Hit-testing

tao (the window library Tauri uses) already treats the outer edge of an undecorated window as a resize border, including corners, and keeps the drop shadow. `chrome.rs` subclasses the HWND and:

1. Leaves those resize hits alone (`HTLEFT` through `HTBOTTOMRIGHT`).
2. Marks the top band, under the resize strip, from the CSS contract: **40px** tall, **64px** Menu on the left (still a normal click), then a drag caption (`HTCAPTION`), then **46px** minimize, maximize and close.
3. Scales those sizes with `GetDpiForWindow` so they match CSS pixels.

Dragging the caption uses Tauri's drag region (`data-tauri-drag-region`), which starts a real window move, so dragging to a screen edge snaps. Double-click on that region toggles maximize. **Win+Left / Win+Right** and **Win+Z** snap as well. The page buttons call Tauri `minimize`, `toggle_maximize` and `close`.

`chrome.rs` also subclasses the HWND. It leaves tao's resize-border hits alone and, in the caption band, returns `HTCAPTION` (drag) and `HTMINBUTTON` / `HTMAXBUTTON` / `HTCLOSE`. That is best-effort: the Win11 maximize snap flyout is not required for this release. If the subclass is not installed, the HTML controls and the drag region still run the window.

The three numbers are checked by `tests/test_window_chrome.py` and by `caption_hit` in `chrome.rs`. Change them in the CSS and in Rust together.

### Permissions

The sign-in commands stay on the bundled page only. Caption permissions are separate and narrow:

* window drag, minimize, maximize, restore, close, and "is maximized"
* `chrome_action` for the Menu entries (switch mode, reload, updates, sign out, guide, log, about, quit)

They are granted to the bundled page, to the local engine at `http://127.0.0.1:8765` and `http://localhost:8765`, and to `https://` pages. The window still refuses to navigate anywhere except the sign-in page, that engine, and the signed-in server; other links open in the browser. No file, shell, or account command is included.

## Microsoft Store (MSIX)

This is a classic desktop window (`runFullTrust`) with WebView2 filling the client area. The caption is HTML inside that webview, not a UWP `ApplicationViewTitleBar`. Undecorated Win32 windows are allowed in a full-trust MSIX. The package does not draw the Windows caption glyphs and does not replace system dialogs.

Store builds keep the current identity unless a package has already been published at that version:

* App **5.6.0-beta.5**
* Engine **5.6.0b5**
* MSIX identity version **5.6.5.0** (the last number stays 0; the Store reserves it)

Partner Center upload (do this by hand; nothing in CI submits it):

1. GitHub Actions → **Windows app** → the successful run for this change.
2. Download the artifact **`automoto-ai-msstore`**.
3. Upload **`AutoMoto-AI-5.6.0-beta.5-Windows-x64.msixupload`**. That zip is what Partner Center asks for. The artifact also contains `AutoMoto-AI-5.6.0-beta.5-Windows-x64.msix` and `SHA256SUMS.txt`; check the hash, and do not upload the loose `.msix` in place of the `.msixupload`.
4. The package is unsigned. The Store signs it. A CI-only self-signed copy is installed and launched, then removed.
5. Confirm the identity matches the existing product (`MSSTORE_IDENTITY_NAME`, `MSSTORE_PUBLISHER`, `MSSTORE_PUBLISHER_DISPLAY_NAME`, `MSSTORE_DISPLAY_NAME`). A placeholder identity must not be submitted.
6. If **5.6.5.0** is already published, Partner Center will reject another package with the same version. The app version would have to move forward before a new upload. This change does not bump it.

The in-app updater stays off when `GetCurrentPackageFullName` shows the process is inside an MSIX package, so a Store install is not replaced by the GitHub NSIS installer.
