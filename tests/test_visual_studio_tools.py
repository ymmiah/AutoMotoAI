"""Visual Studio tools call the studio. Repair stays a proposal."""

import json

from automoto import hosted, sandbox, tools as tools_mod, visual_studio
from automoto.tools import ToolContext
from automoto.visual_studio_tools import PROMO_SPEC, visual_brand_save, visual_export, visual_repair

CTX = ToolContext()
PALETTE = {"background": "#F8F9F7", "ink": "#172638", "muted": "#526476", "accent": "#246D83",
           "card": "#FFFFFF", "border": "#DCE5E9", "tone0": "#E8F3F1", "tone1": "#E7ECFB", "tone2": "#FFF0CF"}


def test_registered_levels_and_hosted_filter():
    tools = tools_mod.build()
    assert tools["visual_repair"].level == "safe"
    assert tools["visual_export"].level == "risky"
    assert tools["visual_brand_save"].level == "risky"
    assert tools["visual_pages_export"].level == "risky"
    names = hosted.hosted_tools()
    assert "visual_export" in names and "visual_ai_review" not in names
    assert "visual_repair" in names


def test_repair_calls_the_studio_and_writes_nothing(monkeypatch):
    seen = {}
    real = visual_studio.propose_repair

    def wrap(body, request):
        seen["title"] = body.spec.get("title")
        return real(body, request)

    monkeypatch.setattr(visual_studio, "propose_repair", wrap)
    root = sandbox.default_root()
    before = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} if root.exists() else set()
    out = json.loads(visual_repair(CTX, PROMO_SPEC, "Promo"))
    after = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} if root.exists() else set()
    assert seen["title"] == "Visual Studio test"
    assert out["applied"] is False and "not applied" in out["summary"].lower()
    assert before == after


def test_export_and_brand_call_the_studio(monkeypatch):
    seen = {}
    real = visual_studio.export

    def wrap(body, request):
        seen["format"] = body.format
        return real(body, request)

    monkeypatch.setattr(visual_studio, "export", wrap)
    exported = json.loads(visual_export(CTX, PROMO_SPEC, "Promo", "png"))
    assert seen["format"] == "png"
    assert (sandbox.default_root() / exported["path"]).is_file()
    saved = json.loads(visual_brand_save(CTX, "Promo brand", PALETTE, 32, 18))
    assert saved["path"].endswith(".brand.json")
    assert (sandbox.default_root() / saved["path"]).is_file()
