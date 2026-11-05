"""Image tools: an honest optional local diffusion backend and a fidelity-first compositor.

ComfyUI executes an installed, locally selected diffusion checkpoint. Images composed
from supplied photos/logos use the original pixels instead of generatively redrawing
faces, bodies, typography, or branding.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from automoto import config, sandbox
from automoto.tools import I, S, Tool, ToolContext, ToolFailed, _obj


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ToolFailed("Image server redirected the request: refusing to contact another host")


def _comfy_base() -> str:
    raw = (config.env("AUTOMOTO_COMFYUI_URL") or "http://127.0.0.1:8188").strip().rstrip("/")
    u = urllib.parse.urlsplit(raw)
    if (u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1")
            or u.username or u.password or u.path or u.query or u.fragment
            or not u.port or not 1 <= u.port <= 65535):
        raise ToolFailed("ComfyUI URL must be http://127.0.0.1:<port> on this computer only")
    return raw


def _req(base: str, endpoint: str, payload: dict | None = None, limit: int = 1024 * 1024,
         timeout: float = 20) -> bytes:
    # Never follow redirects, don't use environment proxies, and don't accept external URLs.
    if endpoint.startswith(("http:", "https:")) or not endpoint.startswith("/"):
        raise ToolFailed("Only local ComfyUI routes are allowed")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(base + endpoint, data=data,
                                     headers={"Content-Type": "application/json"}, method="POST" if payload is not None else "GET")
    try:
        with opener.open(request, timeout=timeout) as r:
            if r.status != 200:
                raise ToolFailed(f"Local image engine returned HTTP {r.status}")
            data = r.read(limit + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolFailed("Cannot reach local ComfyUI: install and run it on 127.0.0.1, then install a supported checkpoint. "
                         + str(exc)[:180]) from None
    if len(data) > limit:
        raise ToolFailed("ComfyUI returned more data than the allowed image size")
    return data


def _json(base: str, endpoint: str, payload: dict | None = None) -> Any:
    try:
        return json.loads(_req(base, endpoint, payload))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolFailed(f"Local image engine returned invalid JSON: {exc}") from None


def local_image_status(ctx: ToolContext) -> str:
    """Check local ComfyUI and the supported checkpoint files without downloading anything."""
    base = _comfy_base()
    checkpoints = _json(base, "/models/checkpoints")
    if not isinstance(checkpoints, list):
        raise ToolFailed("Local image engine returned an invalid checkpoint list")
    return "ComfyUI ready. Installed checkpoint models: " + (", ".join(str(s) for s in checkpoints[:30]) or
          "none. Install a compatible checkpoint to generate images.")


def _basic_workflow(prompt: str, negative: str, checkpoint: str, width: int, height: int,
                    steps: int, seed: int) -> dict[str, Any]:
    """Standard local CheckpointLoaderSimple pipeline; not a proprietary/cloud workflow."""
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": negative}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": 7.0,
              "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
              "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "AutoMoto"}},
    }


def generate_image(ctx: ToolContext, path: str, prompt: str, checkpoint: str = "",
                   negative: str = "", width: int = 1024, height: int = 768,
                   steps: int = 22, seed: int | None = None) -> str:
    """Generate an *original* image from text through a local ComfyUI install."""
    if not isinstance(prompt, str) or not 4 <= len(prompt.strip()) <= 2500:
        raise ToolFailed("Image prompt must be 4-2500 characters")
    if not isinstance(negative, str) or len(negative) > 1000:
        raise ToolFailed("Negative prompt is too long")
    if (not 512 <= int(width) <= 1536 or not 512 <= int(height) <= 1536
            or width % 64 or height % 64 or width*height > 1_600_000):
        raise ToolFailed("Image dimensions must be multiples of 64, 512-1536 px, at most 1.6 megapixels")
    if not 4 <= int(steps) <= 40:
        raise ToolFailed("Image steps must be between 4 and 40")
    dest = sandbox.resolve(path, allow_outside=True)
    if dest.suffix.lower() != ".png":
        raise ToolFailed("Generated images must be saved as .png")
    if dest.exists():
        raise ToolFailed("Output already exists. Choose a new path; existing files are never overwritten")
    base = _comfy_base()
    models = _json(base, "/models/checkpoints")
    if not isinstance(models, list) or not models:
        raise ToolFailed("ComfyUI has no installed checkpoints; install a compatible Stable Diffusion checkpoint first")
    if checkpoint:
        if checkpoint not in models:
            raise ToolFailed("Checkpoint is not installed; use image_models to see available choices")
        chosen = checkpoint
    else:
        chosen = str(models[0])
    if not isinstance(chosen, str) or not chosen or len(chosen) > 250:
        raise ToolFailed("Invalid checkpoint name returned by ComfyUI")
    rng = secrets.randbelow(2**32) if seed is None else int(seed)
    if not 0 <= rng < 2**64:
        raise ToolFailed("Seed must be a nonnegative 64-bit integer")
    wf = _basic_workflow(prompt.strip(), negative.strip() or
         "watermark, low contrast, incorrect lettering, garbled text, poor anatomy", chosen,
         int(width), int(height), int(steps), rng)
    result = _json(base, "/prompt", {"prompt": wf})
    prompt_id = result.get("prompt_id") if isinstance(result, dict) else None
    if not isinstance(prompt_id, str) or not re.fullmatch(r"[a-fA-F0-9-]{32,40}", prompt_id):
        detail = (result.get("error") if isinstance(result, dict) else "") or "workflow rejected"
        raise ToolFailed(f"ComfyUI did not accept the image workflow: {str(detail)[:250]}. "
                         "This simple workflow needs a compatible SD/SDXL-style checkpoint.")
    end = time.monotonic() + 180
    while time.monotonic() < end:
        hist = _json(base, "/history/" + prompt_id)
        record = hist.get(prompt_id) if isinstance(hist, dict) else None
        if isinstance(record, dict):
            status = record.get("status") or {}
            if status.get("status_str") == "error":
                raise ToolFailed("Local image model failed during generation. Check ComfyUI's logs.")
            outputs = record.get("outputs") or {}
            images = (outputs.get("9") or {}).get("images") or []
            if images:
                info = images[0]
                filename = info.get("filename", "")
                sub = info.get("subfolder", "")
                if (not isinstance(filename, str) or not re.fullmatch(r"[\w .-]+\.png", filename, re.I)
                        or not isinstance(sub, str) or "/" in sub or "\\" in sub or
                        info.get("type") != "output"):
                    raise ToolFailed("ComfyUI returned an unsafe output file descriptor")
                q = urllib.parse.urlencode({"filename": filename, "subfolder": sub, "type": "output"})
                data = _req(base, "/view?" + q, limit=24 * 1024 * 1024, timeout=45)
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ToolFailed("ComfyUI returned a non-PNG image")
                from PIL import Image
                try:
                    with Image.open(io.BytesIO(data)) as im:
                        im.verify()
                except (OSError, ValueError) as exc:
                    raise ToolFailed(f"Local image output is not a valid PNG: {exc}") from None
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                return (f"Generated original image at {sandbox.rel(dest)} ({width}×{height}), model {chosen}, "
                        f"seed {rng}. It has not altered any reference photo. Review before using.")
        time.sleep(.75)
    raise ToolFailed("Local image generation timed out after three minutes; check the ComfyUI queue")


def _image(path: str):
    from PIL import Image, ImageOps
    p = sandbox.resolve(path, allow_outside=True)
    if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        raise ToolFailed(f"Image file not found or unsupported: {path}")
    if p.stat().st_size > 24 * 1024 * 1024:
        raise ToolFailed("Input image is too large (24 MB limit)")
    try:
        with Image.open(p) as opened:
            return ImageOps.exif_transpose(opened).convert("RGBA")
    except OSError as exc:
        raise ToolFailed(f"Unable to read image: {exc}") from None


def _font(px: int, bold=False):
    from PIL import ImageFont
    names = (("DejaVuSans-Bold.ttf", "arialbd.ttf") if bold else ("DejaVuSans.ttf", "arial.ttf"))
    for n in names:
        try:
            return ImageFont.truetype(n, px)
        except OSError:
            continue
    return ImageFont.load_default()


def compose_image(ctx: ToolContext, path: str, source: str, title: str = "", subtitle: str = "",
                  logo: str = "", width: int = 1600, height: int = 900,
                  accent: str = "#3C82F6", background: str = "#111B2C",
                  image_side: str = "right") -> str:
    """Compose exactly supplied photography and text into a designed canvas, without AI redrawing."""
    from PIL import Image, ImageDraw, ImageOps
    width, height = int(width), int(height)
    if not 640 <= width <= 4096 or not 480 <= height <= 4096 or width * height > 12_000_000:
        raise ToolFailed("Canvas must be 640-4096 px and no larger than 12 MP")
    if len(title) > 220 or len(subtitle) > 520:
        raise ToolFailed("Text is too long for a legible graphic; shorten it, do not clip it")
    for colour in (accent, background):
        if not re.fullmatch(r"#[a-fA-F0-9]{6}", colour):
            raise ToolFailed("Colours must use #RRGGBB")
    if image_side not in ("right", "left"):
        raise ToolFailed("image_side must be right or left")
    dest = sandbox.resolve(path, allow_outside=True)
    if dest.suffix.lower() != ".png":
        raise ToolFailed("Output must be a .png image")
    if dest.exists():
        raise ToolFailed("Output exists. Never overwrite user files")
    source_img = _image(source)
    emblem = _image(logo) if logo else None
    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)
    margin = int(width * .058)
    gap = int(width * .036)
    box_w = int(width * .47)
    box_h = int(height * .83)
    img_x = width - margin - box_w if image_side == "right" else margin
    img_y = (height-box_h)//2
    draw.rounded_rectangle((img_x-6, img_y-6, img_x+box_w+6, img_y+box_h+6),
                           radius=28, fill=accent)
    draw.rounded_rectangle((img_x, img_y, img_x+box_w, img_y+box_h),
                           radius=22, fill="#FFFFFF")
    # Preserve all source content: aspect-fit, centre; never crop or edit faces/logos.
    fitted = ImageOps.contain(source_img, (box_w-20, box_h-20), Image.Resampling.LANCZOS)
    px = img_x + (box_w-fitted.width)//2
    py = img_y + (box_h-fitted.height)//2
    canvas.paste(fitted, (px, py), fitted)
    tx = margin if image_side == "right" else img_x+box_w+gap
    text_w = min(int(width * .42), width-margin-tx)
    if text_w < 180:
        raise ToolFailed("Not enough space for title text")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((tx, int(height*.18), tx+int(width*.09), int(height*.19)+3), radius=3, fill=accent)
    def draw_wrapped(text, y, size, weight, line_height):
        if not text:
            return y
        f = _font(size, weight)
        lines = []
        for raw in text.splitlines():
            line = ""
            for word in raw.split(" "):
                trial = (line + " " + word).strip() if line else word
                if draw.textbbox((0,0), trial, font=f)[2] > text_w:
                    if not line:
                        raise ToolFailed("One word is wider than the available text box")
                    lines.append(line); line=word
                else:
                    line=trial
            lines.append(line)
        if y+line_height*len(lines)>height-int(height*.10):
            raise ToolFailed("Text exceeds the designed space; reduce it rather than clipping")
        for line in lines:
            draw.text((tx,y), line, font=f, fill="#FFFFFF" if background.lower() != "#ffffff" else "#10243D")
            y += line_height
        return y
    offset = int(height*.27)
    offset = draw_wrapped(title, offset, max(27,int(height*.065)), True, max(40,int(height*.085)))
    draw_wrapped(subtitle, offset+int(height*.055), max(16,int(height*.030)), False, max(23,int(height*.045)))
    if emblem is not None:
        emblem = ImageOps.contain(emblem, (int(width*.17), int(height*.11)), Image.Resampling.LANCZOS)
        canvas.paste(emblem, (tx,int(height*.06)), emblem)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format="PNG", optimize=True)
    return (f"Composed {sandbox.rel(dest)} ({width}×{height}). The supplied face/body/logo was "
            "not AI-generated, warped, beautified or cropped; original source files are unchanged. "
            "Text is drawn from the exact provided strings.")


TOOLS = [
    Tool("image_models", "Check a separately installed local ComfyUI image engine and list its installed checkpoint models; requires no cloud key.",
         _obj({}), "safe", local_image_status, "visual"),
    Tool("image_generate", "Generate original images with a real free LOCAL diffusion checkpoint via ComfyUI. "
         "Requires ComfyUI already installed/running on this computer with a compatible SD/SDXL checkpoint; "
         "downloads no code or models. Does NOT preserve a reference person's identity. "
         "For photos/logos needing strict preservation, use image_compose instead.",
         _obj({"path": S, "prompt": S, "checkpoint": S, "negative": S, "width": I,
               "height": I, "steps": I, "seed": I}, ["path", "prompt"]),
         "risky", generate_image, "visual"),
    Tool("image_compose", "Create a premium presentation/banner PNG with exact user-supplied photo, logo and text. "
         "Preserves the identity, proportions, logo structure and source files; it never generatively changes "
         "people, recreates brand marks, changes wording or crops source photos. "
         "Use this for reference-image fidelity (NOT image_generate).",
         _obj({"path": S, "source": S, "title": S, "subtitle": S, "logo": S, "width": I,
               "height": I, "accent": S, "background": S, "image_side": S}, ["path", "source"]),
         "risky", compose_image, "visual"),
]
