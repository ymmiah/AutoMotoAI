"""Regression tests for editorial PowerPoint layouts, visual fidelity and real local image generation."""

import hashlib
import io
import json
from pathlib import Path

import pytest

pytest.importorskip("pptx")
pytest.importorskip("PIL")

from PIL import Image
from automoto import office_build, office_check, office_visual, sandbox, tools, visual_tools
from automoto.office import OfficeError


@pytest.fixture
def original(tmp_path, monkeypatch):
    # The normal workspace route still validates paths. Keep test artifacts inside it.
    p = sandbox.root() / "scratch" / "visuals-test"
    p.mkdir(parents=True, exist_ok=True)
    sample = p / "original-reference.png"
    logo = p / "original-logo.png"
    Image.new("RGB", (800, 560), (19, 106, 164)).save(sample)
    Image.new("RGBA", (220, 90), (170, 23, 90, 255)).save(logo)
    return sample, logo


def test_editable_premium_deck_and_dark_theme_contrast(original):
    src, logo = original
    out = src.parent / "premium-regression.pptx"
    spec = {
        "aspect": "16:9",
        "theme": {"background": "#0B1220", "accent": "#50A7FF"},
        "slides": [
            {"layout": "title", "title": "A brighter visual story", "subtitle": "Precision matters"},
            {"layout": "cards", "title": "Four capabilities", "cards": [
                {"title": "Preserve", "text": "Identity, body and source logos", "icon": "shield"},
                {"title": "Generate", "text": "Original images using an installed local model", "icon": "image"},
                {"title": "Design", "text": "Editable native PowerPoint shapes", "icon": "idea"},
                {"title": "Validate", "text": "Review slide contrast and alignment", "icon": "check"},
            ], "notes": "Explain each capability."},
            {"layout": "metrics", "title": "Results", "metrics": [
                {"value": "96%", "label": "Example metric (illustrative)"},
                {"value": "24", "label": "Example count (illustrative)"}]},
            {"layout": "steps", "title": "Workflow", "steps": [
                {"title": "Plan", "text": "Confirm requirements"},
                {"title": "Build", "text": "Compose editable graphics"},
                {"title": "Check", "text": "Review the slide rendering"}]},
            {"layout": "image_text", "title": "Original reference", "image": str(src),
             "text": "The reference image is embedded without a generative edit.",
             "brand_logo": str(logo), "alt": "Source reference image"},
        ],
    }
    report = office_build.create_pptx(spec, out)
    assert "5 slides" in report
    from pptx import Presentation
    ppt = Presentation(out)
    assert len(ppt.slides) == 5
    title = ppt.slides[1].shapes.title
    assert title.text_frame.paragraphs[0].runs[0].font.color.rgb == office_visual._rgb("#FFFFFF")
    editable = [s for s in ppt.slides[1].shapes if s.shape_type == 1]
    assert len(editable) >= 10  # icon vectors and card backgrounds, not flattened screenshots
    assert any(s.shape_type == 13 and s._element.nvPicPr.cNvPr.get("descr") ==
               "Source reference image" for s in ppt.slides[4].shapes)
    assert "extends past the slide edge" not in office_check.check(str(out))


def test_reject_bad_visual_specs(original):
    src, _ = original
    out = src.parent / "visual-invalid.pptx"
    with pytest.raises(OfficeError, match="1-6 cards"):
        office_build.create_pptx({"slides": [{"layout": "cards", "title": "Too many",
                                             "cards": [{"title": "x"}] * 7}]}, out)
    with pytest.raises(OfficeError, match="Unknown icon"):
        office_build.create_pptx({"slides": [{"layout": "cards", "title": "Wrong icon",
                                             "cards": [{"title": "hi", "icon": "not-a-real-icon"}]}]}, out)


def test_exact_photo_logo_and_copy_remain_unchanged(original):
    src, logo = original
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (src, logo)]
    dest = src.parent / "composition-output.png"
    if dest.exists():
        dest.unlink()
    ctx = tools.ToolContext()
    result = visual_tools.compose_image(
        ctx, str(dest), str(src), title="Exactly the supplied headline",
        subtitle="No changes to the face, structure or logo", logo=str(logo))
    assert "Composed" in result
    with Image.open(dest) as rendered:
        assert rendered.size == (1600, 900)
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (src, logo)]
    with pytest.raises(tools.ToolFailed, match="exists"):
        visual_tools.compose_image(ctx, str(dest), str(src))


def test_image_backend_cannot_redirect_or_escape_loopback(monkeypatch):
    monkeypatch.setenv("AUTOMOTO_COMFYUI_URL", "https://example.org:8188")
    with pytest.raises(tools.ToolFailed, match="127.0.0.1"):
        visual_tools._comfy_base()
    monkeypatch.setenv("AUTOMOTO_COMFYUI_URL", "http://127.0.0.1:8188")
    assert visual_tools._comfy_base() == "http://127.0.0.1:8188"
    with pytest.raises(tools.ToolFailed, match="Only local"):
        visual_tools._req(visual_tools._comfy_base(), "https://example.com/")


def test_local_generation_uses_a_real_downloaded_checkpoint(original, monkeypatch):
    src, _ = original
    dest = src.parent / "generated-test.png"
    if dest.exists():
        dest.unlink()
    image = io.BytesIO()
    Image.new("RGB", (512, 512), (210, 100, 45)).save(image, format="PNG")
    png = image.getvalue()
    posted = []
    pid = "a" * 32

    def fake_json(base, route, payload=None):
        if route == "/models/checkpoints":
            return ["supported-model.safetensors"]
        if route == "/prompt":
            posted.append(payload)
            return {"prompt_id": pid}
        if route == "/history/" + pid:
            return {pid: {"outputs": {"9": {"images": [
                {"filename": "AutoMoto_001.png", "subfolder": "", "type": "output"}
            ]}}}}
        raise AssertionError(route)

    monkeypatch.setattr(visual_tools, "_json", fake_json)
    monkeypatch.setattr(visual_tools, "_req", lambda *a, **k: png)
    monkeypatch.setenv("AUTOMOTO_COMFYUI_URL", "http://127.0.0.1:8188")
    ctx = tools.ToolContext()
    done = visual_tools.generate_image(ctx, str(dest), "Original abstract flowing blue and gold art",
                                       checkpoint="supported-model.safetensors", width=1024, height=768)
    assert dest.read_bytes() == png
    assert "supported-model" in done
    assert posted[0]["prompt"]["9"]["class_type"] == "SaveImage"
    assert posted[0]["prompt"]["6"]["inputs"]["text"].startswith("Original")
    with pytest.raises(tools.ToolFailed, match="already exists"):
        visual_tools.generate_image(ctx, str(dest), "new original artwork")


def test_visual_tools_are_not_reachable_to_hosted_image_engine():
    all_local = tools.build(local_apps=True)
    hosted = tools.build(local_apps=False)
    assert {"image_generate", "image_models", "image_compose"} <= set(all_local)
    assert "image_generate" not in hosted and "image_models" not in hosted
    assert "image_compose" in hosted
