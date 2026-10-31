"""Regenerate every installer / Windows app brand asset from ``automoto/brand.py``.

    python packaging/branding/generate.py            # writes the files below
    python packaging/branding/generate.py --check    # exit 1 if a generated file is out of date (text files only)

A rename only needs: edit the name/colours in automoto/brand.py (and, for a new logo, ``draw_logo`` below), run
this script, commit. Outputs:

* apps/desktop/src-tauri/icons/  icon.png (1024), 32x32.png, 128x128.png, 128x128@2x.png, icon.ico
  (16-256 px, small sizes hand-tuned), icon.icns
* packaging/branding/out/        uninstall.ico, nsis-header.bmp (150x57), nsis-sidebar.bmp (164x314),
  wix-banner.bmp (493x58), wix-dialog.bmp (493x312), LICENSE-installer.txt (licence + privacy; Tauri also turns it
  into the MSI's licence RTF),
  installer-hooks.nsh (NSIS welcome/finish text, CompanyName, Add/Remove Programs links)
* packaging/branding/out/msix/   MSIX tiles and logos (Square44x44 + target sizes, Square71/150/310, Wide310x150,
  StoreLogo, SplashScreen; scale-100...400) for packaging/msstore/msix.py
* packaging/msstore/images/      app-tile-icon-300x300.png and super-hero-art-1920x1080.png for the Store listing
* packaging/branding/previews/   PNG mock-ups of the installer pages (labelled previews, not screenshots)

Needs Pillow. Fonts: Noto Sans, Segoe UI or DejaVu Sans (whichever is installed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from automoto import __version__, brand  # noqa: E402

OUT = ROOT / "packaging" / "branding" / "out"
PREV = ROOT / "packaging" / "branding" / "previews"
ICONS = ROOT / "apps" / "desktop" / "src-tauri" / "icons"
MSIX = OUT / "msix"  # MSIX package images (packaging/msstore/msix.py puts them in the package's Assets folder)
STORE = ROOT / "packaging" / "msstore" / "images"  # images you upload to the Store listing yourself
C = brand.COLORS
NAME, PUB = brand.DEFAULT_NAME, brand.PUBLISHER


def rgb(h: str, a: int | None = None):
    h = h.lstrip("#")
    t = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return t if a is None else t + (a,)


def mix(a: str, b: str, t: float):
    x, y = rgb(a), rgb(b)
    return tuple(round(x[i] + (y[i] - x[i]) * t) for i in range(3))


FONT_DIRS = ["/usr/share/fonts/truetype/noto", "/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts",
             "/Library/Fonts", "/System/Library/Fonts/Supplemental"]
FONT_FILES = {"bold": ["NotoSans-Bold.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
              "semi": ["NotoSans-SemiBold.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
              "reg": ["NotoSans-Regular.ttf", "segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf"]}


def font(kind: str, size: int):
    for name in FONT_FILES[kind]:
        for d in FONT_DIRS:
            p = Path(d) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def vgrad(w: int, h: int, top: str, bottom: str) -> Image.Image:
    g = Image.new("RGB", (1, h))
    for y in range(h):
        g.putpixel((0, y), mix(top, bottom, y / max(1, h - 1)))
    return g.resize((w, h))


def rrect_mask(w: int, h: int, r: int, box=None) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle(box or (0, 0, w - 1, h - 1), r, fill=255)
    return m


# ------------------------------------------------------------------------------------------------ logo
def draw_logo(size: int, *, simple: bool = False, tile: bool = True) -> Image.Image:
    """The app mark: a friendly robot head on a dark rounded tile. ``simple`` = bold shapes for 16-32 px."""
    S = size * 4  # supersample
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if tile:
        bg = vgrad(S, S, "#18212d", "#06080c").convert("RGBA")
        im.paste(bg, (0, 0), rrect_mask(S, S, int(S * (0.2 if simple else 0.225))))
        if not simple:  # hairline rim
            rim = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            ImageDraw.Draw(rim).rounded_rectangle((S * .012, S * .012, S * .988, S * .988), int(S * .215),
                                                  outline=rgb(C["accent"], 46), width=max(2, S // 160))
            im.alpha_composite(rim)
    # geometry (fractions of S)
    if simple:
        hx0, hy0, hx1, hy1, hr = .12, .30, .88, .86, .17
    else:
        hx0, hy0, hx1, hy1, hr = .19, .33, .81, .80, .14
    box = tuple(int(v * S) for v in (hx0, hy0, hx1, hy1))
    if not simple:  # glow
        glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle(box, int(hr * S), fill=rgb(C["accent"], 120))
        im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(S * .05)))
    # antenna
    cx = S // 2
    stem_w = int(S * (.07 if simple else .045))
    ball_r = int(S * (.095 if simple else .07))
    ball_y = int(S * (.15 if simple else .17))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((cx - stem_w // 2, ball_y, cx + stem_w // 2, box[1] + 10), stem_w // 2, fill=rgb("#2fe39a", 255))
    if not simple:
        g2 = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(g2).ellipse((cx - ball_r * 1.6, ball_y - ball_r * 1.6, cx + ball_r * 1.6, ball_y + ball_r * 1.6),
                                   fill=rgb(C["accent2"], 140))
        im.alpha_composite(g2.filter(ImageFilter.GaussianBlur(S * .03)))
    ball = vgrad(2 * ball_r, 2 * ball_r, "#a48bff", "#6a45f5").convert("RGBA")
    bm = Image.new("L", ball.size, 0)
    ImageDraw.Draw(bm).ellipse((0, 0, 2 * ball_r - 1, 2 * ball_r - 1), fill=255)
    im.paste(ball, (cx - ball_r, ball_y - ball_r), bm)
    # head with gradient
    hw, hh = box[2] - box[0], box[3] - box[1]
    head = vgrad(hw, hh, "#6bfac6", "#19c983").convert("RGBA")
    hm = rrect_mask(hw, hh, int(hr * S))
    im.paste(head, box[:2], hm)
    if not simple:  # top sheen
        sheen = Image.new("RGBA", (hw, hh), (255, 255, 255, 0))
        ImageDraw.Draw(sheen).rounded_rectangle((hw * .06, hh * .05, hw * .94, hh * .42), int(hr * S * .8),
                                                fill=(255, 255, 255, 34))
        sheen.putalpha(ImageChops.multiply(sheen.getchannel("A"), hm))
        im.alpha_composite(sheen, box[:2])
    # visor + eyes
    vx0, vy0 = box[0] + hw * (.12 if simple else .13), box[1] + hh * (.24 if simple else .25)
    vx1, vy1 = box[2] - hw * (.12 if simple else .13), box[1] + hh * (.70 if simple else .66)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((vx0, vy0, vx1, vy1), int((vy1 - vy0) * .48), fill=rgb("#0a0f16", 255))
    ey = (vy0 + vy1) / 2
    er = (vy1 - vy0) * (.30 if simple else .27)
    for ex in (vx0 + (vx1 - vx0) * .29, vx0 + (vx1 - vx0) * .71):
        if not simple:
            ge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            ImageDraw.Draw(ge).ellipse((ex - er * 1.9, ey - er * 1.9, ex + er * 1.9, ey + er * 1.9), fill=rgb(C["accent"], 150))
            im.alpha_composite(ge.filter(ImageFilter.GaussianBlur(er * .6)))
            d = ImageDraw.Draw(im)
        d.ellipse((ex - er, ey - er, ex + er, ey + er), fill=rgb("#7dffd0", 255))
        if not simple:
            d.ellipse((ex - er * .35, ey - er * .55, ex + er * .05, ey - er * .15), fill=(255, 255, 255, 220))
    if not simple:  # smile
        sy = box[1] + hh * .80
        d.rounded_rectangle((cx - hw * .14, sy - hh * .035, cx + hw * .14, sy + hh * .035), int(hh * .035),
                            fill=rgb("#0f8f5c", 255))
    return im.resize((size, size), Image.LANCZOS)


def icon_set() -> dict[int, Image.Image]:
    return {s: draw_logo(s, simple=s <= 32) for s in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)}


def uninstall_badge(img: Image.Image) -> Image.Image:
    im = img.copy()
    s = im.width
    d = ImageDraw.Draw(im)
    r = s * .2
    cx, cy = s - r - s * .02, s - r - s * .02
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgb("#ff6b6b", 255), outline=rgb("#0a0d12", 255), width=max(1, s // 32))
    d.rounded_rectangle((cx - r * .55, cy - r * .14, cx + r * .55, cy + r * .14), max(1, int(r * .12)), fill=(255, 255, 255, 255))
    return im


def save_ico(path: Path, imgs: dict[int, Image.Image]) -> None:
    sizes = sorted(imgs)
    big = imgs[sizes[-1]]
    big.save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=[imgs[s] for s in sizes[:-1]])


# ---------------------------------------------------------------------------------------- installer art
def wrap(d: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def sidebar(w: int = 164, h: int = 314) -> Image.Image:
    im = vgrad(w, h, "#121a25", "#05070a").convert("RGBA")
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-40, 10, w + 40, 190), fill=rgb(C["accent"], 46))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(28)))
    logo = draw_logo(92)
    im.alpha_composite(logo, ((w - 92) // 2, 34))
    d = ImageDraw.Draw(im)
    f1, f2 = font("bold", 19), font("reg", 10)
    words = NAME.split(" ", 1)
    y = 144
    tw = d.textlength(NAME, font=f1)
    if tw <= w - 16:
        x = (w - tw) / 2
        d.text((x, y), words[0], font=f1, fill=rgb(C["text"]))
        if len(words) > 1:
            d.text((x + d.textlength(words[0] + " ", font=f1), y), words[1], font=f1, fill=rgb(C["accent"]))
        y += 30
    else:
        for line in wrap(d, NAME, f1, w - 16):
            d.text(((w - d.textlength(line, font=f1)) / 2, y), line, font=f1, fill=rgb(C["text"]))
            y += 24
        y += 6
    d.line((w / 2 - 18, y, w / 2 + 18, y), fill=rgb(C["accent"]), width=2)
    y += 10
    for line in wrap(d, brand.TAGLINE, f2, w - 22):
        d.text(((w - d.textlength(line, font=f2)) / 2, y), line, font=f2, fill=rgb(C["dim"]))
        y += 14
    f3 = font("reg", 9)
    for i, line in enumerate(("Open source · AGPL-3.0", f"by {PUB}")):
        d.text(((w - d.textlength(line, font=f3)) / 2, h - 34 + i * 13), line, font=f3, fill=rgb("#66727f"))
    d.rectangle((0, h - 4, w, h), fill=rgb(C["accent"]))
    return im.convert("RGB")


def header(w: int = 150, h: int = 57) -> Image.Image:
    """MUI2 header: sits on the white page header, so a light image that blends in."""
    im = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    logo = draw_logo(40)
    im.alpha_composite(logo, (w - 40 - 8, (h - 40) // 2))
    d = ImageDraw.Draw(im)
    f = font("bold", 13)
    parts = NAME.split(" ", 1)
    x = w - 48 - 6 - d.textlength(NAME, font=f)
    if x < 4:
        return im.convert("RGB")
    y = (h - 16) // 2 - 1
    d.text((x, y), parts[0], font=f, fill=rgb("#0a0d12"))
    if len(parts) > 1:
        d.text((x + d.textlength(parts[0] + " ", font=f), y), parts[1], font=f, fill=rgb("#0f9d63"))
    return im.convert("RGB")


def wix_banner(w: int = 493, h: int = 58) -> Image.Image:
    """WiX draws the dialog title in black on the left: keep that side white, brand on the right."""
    im = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    band = Image.new("RGBA", (190, h), (0, 0, 0, 0))
    for x in range(190):
        a = int(255 * min(1, max(0, (x - 10) / 120)))
        ImageDraw.Draw(band).line((x, 0, x, h), fill=rgb(C["bg"], a))
    im.alpha_composite(band, (w - 190, 0))
    im.alpha_composite(draw_logo(40), (w - 40 - 10, (h - 40) // 2))
    d = ImageDraw.Draw(im)
    f = font("bold", 13)
    tx = w - 58 - d.textlength(NAME, font=f)
    d.text((tx, (h - 17) // 2), NAME, font=f, fill=rgb(C["text"]))
    d.rectangle((0, h - 2, w, h), fill=rgb(C["accent"]))
    return im.convert("RGB")


def wix_dialog(w: int = 493, h: int = 312) -> Image.Image:
    """Welcome/finish dialogs: WiX puts the text on the right (x > 164), so the left panel is ours."""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    im.paste(sidebar(164, h), (0, 0))
    d = ImageDraw.Draw(im)
    d.line((164, 0, 164, h), fill=rgb(C["accent"]), width=1)
    return im


def license_texts() -> tuple[str, str]:
    # one line per paragraph: the NSIS licence box and the RTF Tauri makes for the MSI both wrap it themselves
    lic = "\n\n".join(" ".join(p.split()) for p in (ROOT / "LICENSE").read_text(encoding="utf-8").strip().split("\n\n"))
    privacy = ("PRIVACY: " + NAME + " has no telemetry. It only connects to the AI providers, web pages, connectors and "
               "account server you choose, checks this project's GitHub releases for updates "
               "(set AUTOMOTO_NO_UPDATE_CHECK=1 to turn the automatic check off), and downloads WebView2 from Microsoft "
               "during installation if it is missing. Full policy: " + brand.HOMEPAGE + "PRIVACY.html")
    head = (f"{NAME} - {brand.COPYRIGHT}\n\n"
            f"{NAME} is free software: you can redistribute it and/or modify it under the terms of the GNU Affero "
            "General Public License version 3 (AGPL-3.0-only), printed below. It comes with NO WARRANTY.\n\n"
            "Using it in a closed-source or commercial product or service without the AGPL obligations needs a "
            f"commercial licence: {brand.COMMERCIAL_URL}\n\n"
            "Versions up to and including 5.6.0-beta.3 were released under the MIT licence and stay MIT for those copies.")
    txt = f"{head}\n\n{privacy}\n\n{lic}\n"
    if not txt.isascii():
        raise SystemExit("LICENSE-installer.txt must be plain ASCII (Tauri turns it into the MSI's RTF)")
    return txt.replace("\n", "\r\n"), privacy


SHORTCUT_FIX = r"""  ; installs before the Start menu folder existed put the shortcut in the Start menu root: keep only one
  Push $0
  Push $1
  Push $2
  Push $3
  ${If} $AppStartMenuFolder != ""
  ${AndIf} ${FileExists} "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
    !insertmacro IsShortcutTarget "$SMPROGRAMS\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      Delete "$SMPROGRAMS\${PRODUCTNAME}.lnk"
    ${EndIf}
  ${EndIf}
  Pop $3
  Pop $2
  Pop $1
  Pop $0
""".replace("\\\\", "\\")


def nsis_hooks() -> str:
    q = lambda s: s.replace("$", "$$").replace('"', "$\\\"")  # NSIS string escaping
    nl = "$\\r$\\n$\\r$\\n"  # NSIS: blank line
    welcome = nl.join(q(t) for t in (f"This will install {NAME} on your computer.",
                                     "It researches, writes Word, Excel and PowerPoint files, works with your data and "
                                     "code, and asks before anything risky.",
                                     "No administrator rights are needed. Click Next to continue."))
    finish = nl.join(q(t) for t in (f"{NAME} is installed.", "Sign in to your account to see the same chats on every "
                                    "device, or choose Local mode to run everything on this PC."))
    return f"""; Generated by packaging/branding/generate.py from automoto/brand.py. Edit those, then re-run the script.
; Included at the top level of Tauri's NSIS template (bundle.windows.nsis.installerHooks).

VIAddVersionKey "CompanyName" "{q(PUB)}"
VIAddVersionKey "Comments" "{q(brand.TAGLINE)}"

!define MUI_WELCOMEPAGE_TITLE "Welcome to {q(NAME)}"
!define MUI_WELCOMEPAGE_TEXT "{welcome}"
!define MUI_FINISHPAGE_TITLE "{q(NAME)} is ready"
!define MUI_FINISHPAGE_TEXT "{finish}"
!define MUI_FINISHPAGE_LINK "Getting started guide"
!define MUI_FINISHPAGE_LINK_LOCATION "{brand.HOMEPAGE}START.html"
!define MUI_FINISHPAGE_LINK_COLOR "0F9D63"

!macro NSIS_HOOK_POSTINSTALL
  ; Add/Remove Programs: support and info links, publisher contact
  WriteRegStr SHCTX "${{UNINSTKEY}}" "HelpLink" "{brand.SUPPORT_URL}"
  WriteRegStr SHCTX "${{UNINSTKEY}}" "URLInfoAbout" "{brand.HOMEPAGE}"
  WriteRegStr SHCTX "${{UNINSTKEY}}" "URLUpdateInfo" "{brand.REPO_URL}/releases"
  WriteRegStr SHCTX "${{UNINSTKEY}}" "Contact" "{q(PUB)}"
  WriteRegStr SHCTX "${{UNINSTKEY}}" "Comments" "{q(brand.TAGLINE)}"
{SHORTCUT_FIX}!macroend
"""


# -------------------------------------------------------------------------------------------- MSIX / Store
def tile(w: int, h: int, logo_frac: float = 0.62, wordmark: bool = False) -> Image.Image:
    """A Start-menu tile: the app's dark background with the logo (and optionally the name) centred."""
    im = vgrad(w, h, "#141c27", "#06080c").convert("RGBA")
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((w * .15, -h * .2, w * .85, h * .9), fill=rgb(C["accent"], 34))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(4, h // 6))))
    n = int(min(w, h) * logo_frac)
    logo = draw_logo(n, simple=n <= 32, tile=False)
    if not wordmark:
        im.alpha_composite(logo, ((w - n) // 2, (h - n) // 2))
        return im
    f = font("bold", max(10, h // 7))
    d = ImageDraw.Draw(im)
    words = NAME.split(" ", 1)
    tw = d.textlength(NAME, font=f)
    gap = h // 12
    x = int((w - (n + gap + tw)) / 2)
    im.alpha_composite(logo, (x, (h - n) // 2))
    tx, ty = x + n + gap, (h - f.size) / 2 - f.size * .1
    d.text((tx, ty), words[0], font=f, fill=rgb(C["text"]))
    if len(words) > 1:
        d.text((tx + d.textlength(words[0] + " ", font=f), ty), words[1], font=f, fill=rgb(C["accent"]))
    return im


def msix_images() -> dict[str, Image.Image]:
    """File name -> image. Unqualified names are the 100% versions (used if resources.pri is missing)."""
    out: dict[str, Image.Image] = {}

    def add(base: str, make, size100: tuple[int, int]):
        for scale in (100, 125, 150, 200, 400):
            w, h = (round(v * scale / 100) for v in size100)
            img = make(w, h)
            out[f"{base}.scale-{scale}.png"] = img
            if scale == 100:
                out[f"{base}.png"] = img

    add("Square44x44Logo", lambda w, h: draw_logo(w, simple=w <= 32), (44, 44))
    for t in (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256):
        out[f"Square44x44Logo.targetsize-{t}.png"] = draw_logo(t, simple=t <= 32)
        out[f"Square44x44Logo.targetsize-{t}_altform-unplated.png"] = draw_logo(t, simple=t <= 32)
        out[f"Square44x44Logo.targetsize-{t}_altform-lightunplated.png"] = draw_logo(t, simple=t <= 32)
    add("Square71x71Logo", lambda w, h: tile(w, h, .6), (71, 71))
    add("Square150x150Logo", lambda w, h: tile(w, h, .58), (150, 150))
    add("Wide310x150Logo", lambda w, h: tile(w, h, .5, wordmark=True), (310, 150))
    add("Square310x310Logo", lambda w, h: tile(w, h, .5), (310, 310))
    add("StoreLogo", lambda w, h: draw_logo(w), (50, 50))
    add("SplashScreen", lambda w, h: tile(w, h, .5, wordmark=True), (620, 300))
    return out


# -------------------------------------------------------------------------------------------- previews
def window(w: int, h: int, title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (w + 2, h + 32), (240, 240, 240))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, w + 1, 31), fill=(255, 255, 255))
    d.rectangle((0, 0, w + 1, h + 31), outline=(160, 160, 160))
    ic = draw_logo(16)
    im.paste(ic, (8, 8), ic)
    d.text((30, 8), title, font=font("reg", 12), fill=(30, 30, 30))
    for i, ch in enumerate(("_", "x")):
        d.text((w - 50 + i * 30, 7), ch, font=font("reg", 12), fill=(80, 80, 80))
    return im, d


def buttons(d, w: int, y: int, labels) -> None:
    f = font("reg", 12)
    x = w - 10
    for lab, primary in reversed(labels):
        bw = 80
        x -= bw
        d.rectangle((x, y, x + bw - 1, y + 23), fill=(225, 225, 225), outline=(0, 120, 215) if primary else (173, 173, 173))
        d.text((x + (bw - d.textlength(lab, font=f)) / 2, y + 4), lab, font=f, fill=(0, 0, 0))
        x -= 8


def label(im: Image.Image) -> Image.Image:
    out = Image.new("RGB", (im.width, im.height + 24), (255, 200, 87))
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    f = font("bold", 11)
    t = "PREVIEW - mock-up of the installer page made from the real artwork (not a screenshot)"
    d.text(((im.width - d.textlength(t, font=f)) / 2, im.height + 5), t, font=f, fill=(0, 0, 0))
    return out


def preview_nsis_welcome() -> Image.Image:
    w, h = 497, 360
    im, d = window(w, h, f"{NAME} Setup")
    im.paste(sidebar(), (1, 32))
    d.rectangle((165, 32, w, 32 + 314), fill=(255, 255, 255))
    d.text((180, 46), f"Welcome to {NAME}", font=font("bold", 17), fill=(0, 0, 0))
    y = 90
    for para in (f"This will install {NAME} on your computer.", "It researches, writes Word, Excel and PowerPoint "
                 "files, works with your data and code, and asks before anything risky.",
                 "No administrator rights are needed. Click Next to continue."):
        for line in wrap(d, para, font("reg", 12), w - 195):
            d.text((180, y), line, font=font("reg", 12), fill=(0, 0, 0))
            y += 17
        y += 10
    d.line((0, 32 + 314, w + 1, 32 + 314), fill=(160, 160, 160))
    buttons(d, w, 32 + 314 + 12, [("Next >", True), ("Cancel", False)])
    return label(im)


def preview_nsis_page(title: str, sub: str, body) -> Image.Image:
    w, h = 497, 360
    im, d = window(w, h, f"{NAME} Setup")
    d.rectangle((1, 32, w, 32 + 57), fill=(255, 255, 255))
    im.paste(header(), (w - 150, 32))
    d.text((12, 40), title, font=font("bold", 13), fill=(0, 0, 0))
    d.text((22, 60), sub, font=font("reg", 11), fill=(0, 0, 0))
    d.line((0, 89, w + 1, 89), fill=(160, 160, 160))
    body(d, im)
    d.line((0, h - 14, w + 1, h - 14), fill=(160, 160, 160))
    buttons(d, w, h - 6, [("< Back", False), ("I Agree" if "Licence" in title else "Next >", True), ("Cancel", False)])
    return label(im)


def preview_nsis_license() -> Image.Image:
    txt, _ = license_texts()

    def body(d, im):
        d.text((12, 98), f"Please review the licence terms before installing {NAME}.", font=font("reg", 11), fill=(0, 0, 0))
        d.rectangle((12, 118, 485, 300), fill=(255, 255, 255), outline=(130, 130, 130))
        y = 122
        for para in txt.split("\r\n"):
            for line in wrap(d, para, font("reg", 10), 455) or [""]:
                if y > 288:
                    return
                d.text((18, y), line, font=font("reg", 10), fill=(0, 0, 0))
                y += 13
    return preview_nsis_page("Licence Agreement", "Please review the licence terms before installing.", body)


def preview_nsis_finish() -> Image.Image:
    w, h = 497, 360
    im, d = window(w, h, f"{NAME} Setup")
    im.paste(sidebar(), (1, 32))
    d.rectangle((165, 32, w, 32 + 314), fill=(255, 255, 255))
    d.text((180, 46), f"{NAME} is ready", font=font("bold", 17), fill=(0, 0, 0))
    y = 90
    for para in (f"{NAME} is installed.", "Sign in to your account to see the same chats on every device, or choose "
                 "Local mode to run everything on this PC."):
        for line in wrap(d, para, font("reg", 12), w - 195):
            d.text((180, y), line, font=font("reg", 12), fill=(0, 0, 0))
            y += 17
        y += 10
    for i, t in enumerate((f"Run {NAME}", "Create desktop shortcut")):
        d.rectangle((182, y + 6 + i * 24, 194, y + 18 + i * 24), outline=(50, 50, 50), fill=(255, 255, 255))
        d.line((184, y + 12 + i * 24, 187, y + 15 + i * 24, 192, y + 8 + i * 24), fill=(0, 0, 0), width=2)
        d.text((202, y + 4 + i * 24), t, font=font("reg", 12), fill=(0, 0, 0))
    d.text((182, y + 60), "Getting started guide", font=font("reg", 12), fill=rgb("#0f9d63"))
    d.line((0, 32 + 314, w + 1, 32 + 314), fill=(160, 160, 160))
    buttons(d, w, 32 + 314 + 12, [("Finish", True)])
    return label(im)


def preview_msi() -> Image.Image:
    w, h = 493, 312 + 46
    im, d = window(w, h, f"{NAME} Setup")
    im.paste(wix_dialog(), (1, 32))
    d.text((180, 52), f"Welcome to the {NAME} Setup Wizard", font=font("bold", 14), fill=(0, 0, 0))
    y = 100
    for line in wrap(d, f"The Setup Wizard will install {NAME} on your computer. Click Next to continue or Cancel "
                     "to exit the Setup Wizard.", font("reg", 11), 290):
        d.text((180, y), line, font=font("reg", 11), fill=(0, 0, 0))
        y += 16
    d.rectangle((1, 32 + 312, w, h + 31), fill=(240, 240, 240))
    buttons(d, w, 32 + 312 + 12, [("Back", False), ("Next", True), ("Cancel", False)])
    im2, d2 = window(w, 300, f"{NAME} Setup")
    im2.paste(wix_banner(), (1, 32))
    d2.text((14, 40), "End-User License Agreement", font=font("bold", 12), fill=(0, 0, 0))
    d2.text((24, 58), "Please read the following license agreement carefully", font=font("reg", 10), fill=(0, 0, 0))
    d2.rectangle((14, 100, 478, 260), fill=(255, 255, 255), outline=(130, 130, 130))
    d2.text((22, 106), NAME, font=font("bold", 14), fill=rgb("#0a0d12"))
    paras = (ROOT / "LICENSE").read_text(encoding="utf-8").split("\n\n")
    d2.text((22, 128), paras[0].strip()[:70], font=font("reg", 10), fill=rgb("#0f9d63"))
    y = 148
    for line in wrap(d2, " ".join(" ".join(paras[1:3]).split()), font("reg", 10), 440)[:7]:
        d2.text((22, y), line, font=font("reg", 10), fill=(0, 0, 0))
        y += 14
    buttons(d2, w, 270, [("Back", False), ("Next", True), ("Cancel", False)])
    both = Image.new("RGB", (im.width, im.height + im2.height + 16), (210, 214, 220))
    both.paste(im, (0, 0))
    both.paste(im2, (0, im.height + 16))
    return label(both)


def preview_icons() -> Image.Image:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    im = Image.new("RGB", (sum(sizes) + 30 * len(sizes) + 30, 330), (246, 247, 249))
    dark = Image.new("RGB", (im.width, 330), rgb(C["bg"]))
    out = Image.new("RGB", (im.width, 660 + 40), (255, 255, 255))
    for row, bg in enumerate((im, dark)):
        x = 30
        d = ImageDraw.Draw(bg)
        for s in sizes:
            ic = draw_logo(s, simple=s <= 32)
            bg.paste(ic, (x, 290 - s), ic)
            d.text((x, 300), f"{s}px", font=font("reg", 11), fill=(120, 120, 120))
            x += s + 30
        out.paste(bg, (0, row * 330))
    ImageDraw.Draw(out).text((12, 670), f"{NAME} app icon (icon.ico sizes, light and dark backgrounds) - PREVIEW",
                             font=font("bold", 12), fill=(0, 0, 0))
    return out


# ------------------------------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only check the generated text files are up to date")
    a = ap.parse_args()
    texts = {OUT / "installer-hooks.nsh": nsis_hooks(),
             OUT / "LICENSE-installer.txt": license_texts()[0]}
    if a.check:
        stale = [str(p.relative_to(ROOT)) for p, t in texts.items()
                 if not p.exists() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != t.replace("\r\n", "\n")]
        if stale:
            print("out of date (run python packaging/branding/generate.py):", ", ".join(stale))
            return 1
        print("branding files are up to date")
        return 0
    for p in (OUT, PREV, ICONS, MSIX, STORE):
        p.mkdir(parents=True, exist_ok=True)
    for p, t in texts.items():
        p.write_bytes(t.encode("utf-8"))
    icons = icon_set()
    big = draw_logo(1024)
    big.save(ICONS / "icon.png")
    draw_logo(32, simple=True).save(ICONS / "32x32.png")
    icons[128].save(ICONS / "128x128.png")
    icons[256].save(ICONS / "128x128@2x.png")
    save_ico(ICONS / "icon.ico", icons)
    save_ico(OUT / "uninstall.ico", {s: uninstall_badge(i) for s, i in icons.items()})
    big.save(ICONS / "icon.icns")
    sidebar().save(OUT / "nsis-sidebar.bmp")
    header().save(OUT / "nsis-header.bmp")
    wix_banner().save(OUT / "wix-banner.bmp")
    wix_dialog().save(OUT / "wix-dialog.bmp")
    big.resize((512, 512), Image.LANCZOS).save(OUT / "logo-512.png")
    for old in MSIX.glob("*.png"):
        old.unlink()
    for fname, img in msix_images().items():
        img.save(MSIX / fname, optimize=True)
    big.resize((300, 300), Image.LANCZOS).save(STORE / "app-tile-icon-300x300.png", optimize=True)
    tile(1920, 1080, .42, wordmark=True).convert("RGB").save(STORE / "super-hero-art-1920x1080.png", optimize=True)
    for name, fn in (("nsis-welcome", preview_nsis_welcome), ("nsis-license", preview_nsis_license),
                     ("nsis-finish", preview_nsis_finish), ("msi-welcome-and-license", preview_msi),
                     ("app-icon-sizes", preview_icons)):
        fn().save(PREV / f"{name}.png", optimize=True)
    print(f"generated branding for {NAME} {__version__} into {OUT.relative_to(ROOT)}, {ICONS.relative_to(ROOT)}, "
          f"{PREV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
