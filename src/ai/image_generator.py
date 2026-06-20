"""
AI Image Generation — text-to-image and region inpainting.

Backends
--------
  • Text-to-image : OpenAI DALL-E 3  (primary, high quality)
  • Inpainting    : OpenAI DALL-E 2 edit endpoint  (mask-based region editing)

Style presets inject professional wording into the prompt so DALL-E produces
output that matches the requested design category without the user having to
craft perfect prompt language.
"""
from __future__ import annotations

import base64
import io
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from src.core.config import ai_config
from src.core.exceptions import AIProviderError

logger = logging.getLogger(__name__)

_IMG_DIR = Path.home() / "Documents" / "AutoMotoAI_Documents" / "images"


# ── style / size presets ─────────────────────────────────────────────────────

STYLE_PRESETS: dict[str, str] = {
    "photo":       "Photorealistic, professional photography quality, high detail, sharp focus.",
    "logo":        "Professional vector-style logo design, clean, minimal, scalable. White or transparent background. Suitable for branding.",
    "poster":      "High-quality poster/banner design, bold typography, striking visuals, professional layout.",
    "social":      "Eye-catching social media graphic, modern design, strong visual hierarchy, vibrant colors.",
    "print":       "Print-quality design, CMYK-friendly rich colors, high detail, suitable for large-format printing.",
    "icon":        "Clean flat icon design, simple, recognisable, consistent style, suitable for UI/app use.",
    "product":     "Photorealistic product mockup, high-quality studio rendering, clean background, professional lighting.",
    "character":   "Character/mascot design, expressive, detailed, clean outlines, suitable for brand identity.",
    "background":  "Professional atmospheric background, cinematic quality, wide landscape or abstract.",
    "infographic": "Infographic-style visual, clean data layout, professional typography, informative design.",
}

SIZE_PRESETS: dict[str, str] = {
    "square":    "1024x1024",   # 1:1   — logos, social media, icons
    "landscape": "1792x1024",   # 16:9  — banners, YouTube thumbnails
    "portrait":  "1024x1792",   # 9:16  — posters, stories, A4
}


# ── result dataclass ─────────────────────────────────────────────────────────

@dataclass
class GeneratedImage:
    prompt: str
    revised_prompt: str
    style: str
    width: int
    height: int
    image_data: bytes          # raw PNG bytes
    filename: str
    provider: str
    generation_time: float = 0.0

    @property
    def ok(self) -> bool:
        return len(self.image_data) > 0

    def save(self) -> Path:
        _IMG_DIR.mkdir(parents=True, exist_ok=True)
        path = _IMG_DIR / self.filename
        path.write_bytes(self.image_data)
        return path


# ── generator ────────────────────────────────────────────────────────────────

class ImageGenerator:
    """Unified image generation and inpainting via OpenAI DALL-E."""

    # ── internal helpers ─────────────────────────────────────────────────────

    def _client(self):
        if not ai_config.openai_api_key:
            raise AIProviderError(
                "OpenAI API key not configured. "
                "Add OPENAI_API_KEY to your .env file."
            )
        try:
            from openai import OpenAI
            return OpenAI(api_key=ai_config.openai_api_key)
        except ImportError as exc:
            raise AIProviderError("openai package not installed: pip install openai") from exc

    def _slug(self, text: str) -> str:
        return re.sub(r"[^\w]", "_", text)[:28]

    def _filename(self, prefix: str, ext: str = "png") -> str:
        return f"{self._slug(prefix)}_{int(time.time())}.{ext}"

    # ── text-to-image ─────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        style: str = "photo",
        size: str = "square",
        quality: str = "hd",        # "hd" | "standard"
    ) -> GeneratedImage:
        """Generate an image from a text prompt using DALL-E 3."""
        style_hint  = STYLE_PRESETS.get(style, "")
        full_prompt = f"{style_hint} {prompt}".strip() if style_hint else prompt
        dalle_size  = SIZE_PRESETS.get(size, "1024x1024")
        w, h        = map(int, dalle_size.split("x"))

        t0   = time.time()
        resp = self._client().images.generate(
            model="dall-e-3",
            prompt=full_prompt,
            size=dalle_size,
            quality=quality,
            response_format="b64_json",
            n=1,
        )
        elapsed     = time.time() - t0
        item        = resp.data[0]
        image_bytes = base64.b64decode(item.b64_json)
        fname       = self._filename(prompt)

        result = GeneratedImage(
            prompt=prompt,
            revised_prompt=getattr(item, "revised_prompt", "") or "",
            style=style,
            width=w, height=h,
            image_data=image_bytes,
            filename=fname,
            provider="dall-e-3",
            generation_time=round(elapsed, 2),
        )
        result.save()
        logger.info("Generated %s in %.1fs", fname, elapsed)
        return result

    # ── inpainting (region edit) ──────────────────────────────────────────────

    def inpaint(
        self,
        original_bytes: bytes,
        mask_bytes: bytes,
        prompt: str,
    ) -> GeneratedImage:
        """
        Edit a masked region of an existing image using DALL-E 2.

        Parameters
        ----------
        original_bytes : PNG bytes of the original image (≤ 4 MB)
        mask_bytes     : PNG bytes of the user-drawn mask.
                         Pixels with any alpha > 0 indicate the region to EDIT.
                         The backend inverts this so DALL-E receives
                         transparent=edit, white=keep.
        prompt         : What to generate in the selected region
        """
        prep_orig, dall_e_mask = self._prepare_inpaint(original_bytes, mask_bytes)

        t0   = time.time()
        resp = self._client().images.edit(
            model="dall-e-2",
            image=io.BytesIO(prep_orig),
            mask=io.BytesIO(dall_e_mask),
            prompt=prompt,
            size="1024x1024",
            response_format="b64_json",
            n=1,
        )
        elapsed     = time.time() - t0
        image_bytes = base64.b64decode(resp.data[0].b64_json)
        fname       = self._filename(f"inpaint_{prompt}")

        result = GeneratedImage(
            prompt=prompt,
            revised_prompt="",
            style="inpaint",
            width=1024, height=1024,
            image_data=image_bytes,
            filename=fname,
            provider="dall-e-2-edit",
            generation_time=round(elapsed, 2),
        )
        result.save()
        logger.info("Inpainted %s in %.1fs", fname, elapsed)
        return result

    # ── mask preparation ─────────────────────────────────────────────────────

    def _prepare_inpaint(
        self, orig_bytes: bytes, mask_bytes: bytes
    ) -> tuple[bytes, bytes]:
        """
        Resize both images to 1024×1024 RGBA PNG.

        DALL-E 2 mask convention: transparent pixels = region to fill.
        User-drawn mask convention: painted (alpha > 0) = region to edit.
        We invert here: painted → transparent, unpainted → white opaque.
        """
        try:
            from PIL import Image
        except ImportError as exc:
            raise AIProviderError(
                "Pillow not installed: pip install Pillow"
            ) from exc

        def to_rgba_1024(data: bytes) -> bytes:
            img = Image.open(io.BytesIO(data)).convert("RGBA").resize(
                (1024, 1024), Image.LANCZOS
            )
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        # Prepare original
        prep_orig = to_rgba_1024(orig_bytes)

        # Build DALL-E mask: transparent = edit, white = keep
        mask_img = Image.open(io.BytesIO(mask_bytes)).convert("RGBA").resize(
            (1024, 1024), Image.LANCZOS
        )
        out_mask = Image.new("RGBA", (1024, 1024), (255, 255, 255, 255))
        src_pixels = list(mask_img.getdata())
        out_pixels = list(out_mask.getdata())
        for i, (r, g, b, a) in enumerate(src_pixels):
            if a > 20:                          # user painted here → edit
                out_pixels[i] = (0, 0, 0, 0)   # transparent = DALL-E edits
            # else: keep white opaque = DALL-E preserves original
        out_mask.putdata(out_pixels)
        buf = io.BytesIO()
        out_mask.save(buf, format="PNG")
        dall_e_mask = buf.getvalue()

        return prep_orig, dall_e_mask


image_generator = ImageGenerator()
