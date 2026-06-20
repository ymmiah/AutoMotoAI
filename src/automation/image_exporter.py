"""
Professional image export engine.

Supported output formats
------------------------
  png_web     : PNG 72 DPI  — web/screen
  png_print   : PNG 300 DPI — offset print
  webp        : WebP lossy 90  — web optimised
  svg         : SVG vector via vtracer (raster→vector)
  pdf         : PDF with embedded image at 300 DPI
  tiff        : TIFF 300 DPI — Photoshop / print press
  ai_pdf      : PDF/X-compatible — Illustrator import

All formats also support 2× / 4× Lanczos upscaling before export,
giving print-quality sharpness on large-format material.
"""
from __future__ import annotations

import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from src.core.exceptions import AIProviderError

logger = logging.getLogger(__name__)

_IMG_DIR = Path.home() / "Documents" / "AutoMotoAI_Documents" / "images"

EXPORT_FORMATS: dict[str, dict] = {
    "png_web":    {"ext": "png",  "label": "PNG (Web 72 dpi)",          "dpi": 72},
    "png_print":  {"ext": "png",  "label": "PNG (Print 300 dpi)",        "dpi": 300},
    "webp":       {"ext": "webp", "label": "WebP (Web optimised)",       "dpi": 72},
    "svg":        {"ext": "svg",  "label": "SVG Vector (scalable)",      "dpi": None},
    "pdf":        {"ext": "pdf",  "label": "PDF (print ready)",          "dpi": 300},
    "tiff":       {"ext": "tif",  "label": "TIFF (Photoshop 300 dpi)",   "dpi": 300},
    "ai_pdf":     {"ext": "pdf",  "label": "PDF/AI (Illustrator ready)", "dpi": 300},
}

UPSCALE_OPTIONS: dict[str, int] = {
    "1x": 1,
    "2x": 2,
    "4x": 4,
}


@dataclass
class ExportResult:
    filename: str
    format:   str
    path:     Path
    size_kb:  float
    width:    int
    height:   int

    @property
    def ok(self) -> bool:
        return self.path.exists()


class ImageExporter:

    def export(
        self,
        source_bytes: bytes,
        fmt: str = "png_print",
        upscale: str = "1x",
        base_name: str = "",
    ) -> ExportResult:
        """
        Export *source_bytes* (PNG) to the requested format.

        Parameters
        ----------
        source_bytes : raw PNG bytes (output of ImageGenerator.generate)
        fmt          : one of EXPORT_FORMATS keys
        upscale      : "1x" | "2x" | "4x" — Lanczos upscaling applied first
        base_name    : stem for the output filename (slug + timestamp appended)
        """
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"Unknown export format: {fmt!r}. Choose from {list(EXPORT_FORMATS)}")
        if upscale not in UPSCALE_OPTIONS:
            raise ValueError(f"Unknown upscale: {upscale!r}. Choose from {list(UPSCALE_OPTIONS)}")

        spec   = EXPORT_FORMATS[fmt]
        ext    = spec["ext"]
        dpi    = spec["dpi"] or 72
        factor = UPSCALE_OPTIONS[upscale]

        try:
            from PIL import Image
        except ImportError as exc:
            raise AIProviderError("Pillow not installed: pip install Pillow") from exc

        _IMG_DIR.mkdir(parents=True, exist_ok=True)

        img = Image.open(io.BytesIO(source_bytes)).convert("RGBA")

        if factor > 1:
            new_w = img.width  * factor
            new_h = img.height * factor
            img = img.resize((new_w, new_h), Image.LANCZOS)

        stem  = self._slug(base_name or "export")
        fname = f"{stem}_{int(time.time())}.{ext}"
        path  = _IMG_DIR / fname

        if fmt == "svg":
            data = self._to_svg(source_bytes if factor == 1 else self._to_png_bytes(img))
            path.write_bytes(data.encode())
        elif fmt == "webp":
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="WEBP", quality=90)
            path.write_bytes(buf.getvalue())
        elif fmt in ("pdf", "ai_pdf"):
            self._to_pdf(img, path, dpi, illustrator=(fmt == "ai_pdf"))
        elif fmt == "tiff":
            img.save(path, format="TIFF", dpi=(dpi, dpi), compression="tiff_lzw")
        else:
            img.save(path, format="PNG", dpi=(dpi, dpi))

        size_kb = path.stat().st_size / 1024
        logger.info("Exported %s (%.0f KB) — %s", fname, size_kb, spec["label"])

        return ExportResult(
            filename=fname,
            format=fmt,
            path=path,
            size_kb=round(size_kb, 1),
            width=img.width,
            height=img.height,
        )

    # ── internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _slug(text: str) -> str:
        import re
        return re.sub(r"[^\w]", "_", text)[:28]

    @staticmethod
    def _to_png_bytes(img) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _to_svg(png_bytes: bytes) -> str:
        try:
            import vtracer
            return vtracer.convert_raw_image_to_svg(
                png_bytes,
                img_format="PNG",
                colormode="color",
                hierarchical="stacked",
                mode="spline",
                filter_speckle=4,
                color_precision=6,
                layer_difference=16,
                corner_threshold=60,
                length_threshold=4.0,
                max_iterations=10,
                splice_threshold=45,
                path_precision=3,
            )
        except ImportError:
            # Fallback: embed the PNG as a base64 data URI inside an SVG wrapper.
            import base64
            b64 = base64.b64encode(png_bytes).decode()
            try:
                from PIL import Image
                img  = Image.open(io.BytesIO(png_bytes))
                w, h = img.width, img.height
            except Exception:
                w, h = 1024, 1024
            return (
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
                f'  <image width="{w}" height="{h}" '
                f'xlink:href="data:image/png;base64,{b64}"/>\n'
                f'</svg>\n'
            )

    @staticmethod
    def _to_pdf(img, path: Path, dpi: int, illustrator: bool = False) -> None:
        try:
            from fpdf import FPDF
        except ImportError as exc:
            raise AIProviderError("fpdf2 not installed: pip install fpdf2") from exc

        px_to_mm = 25.4 / dpi
        w_mm = img.width  * px_to_mm
        h_mm = img.height * px_to_mm

        pdf = FPDF(orientation="P", unit="mm", format=(w_mm, h_mm))
        pdf.set_auto_page_break(False)
        pdf.add_page()

        if illustrator:
            pdf.set_creator("AutoMoto AI — Illustrator-compatible PDF")
            pdf.set_title("AI Generated Artwork")

        tmp_png = path.with_suffix(".tmp.png")
        try:
            img.convert("RGB").save(tmp_png, format="PNG", dpi=(dpi, dpi))
            pdf.image(str(tmp_png), x=0, y=0, w=w_mm, h=h_mm)
        finally:
            tmp_png.unlink(missing_ok=True)

        pdf.output(str(path))


image_exporter = ImageExporter()
