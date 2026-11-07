"""Bounded, deterministic group-keyframe animation for Visual Studio.

Only compiled native groups are transformed. Animations never modify scene
definitions, source photo files, or reusable draft content. No expressions,
remote scripts, runtime code execution, or external motion plugins.
"""
from __future__ import annotations

import math
from typing import Any

from automoto.visual_foundation import VisualError

ALLOWED_EASING = {"linear", "ease-in", "ease-out", "ease-in-out"}
MOTION_FIELDS = {"at", "dx", "dy", "scale", "opacity", "rotation", "easing"}
TRACK_FIELDS = {"group", "keyframes"}
MAX_TRACKS = 12
MAX_KEYS = 6


def _number(value: Any, name: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise VisualError(f"{name} must be a finite number")
    if not lo <= value <= hi:
        raise VisualError(f"{name} must be between {lo:g} and {hi:g}")
    return float(value)


def validate_keyframes(scene: dict, config: dict) -> dict[str, list[dict]]:
    """Fully reject malformed or excessive motion data *before* rendering."""
    if not isinstance(config, dict) or config.get("effect") != "keyframes":
        raise VisualError("keyframe animation requires the keyframes effect")
    if set(config) - {"effect", "frames", "duration_ms", "loop", "tracks"}:
        raise VisualError("unrecognised keyframe animation configuration")
    tracks = config.get("tracks")
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= MAX_TRACKS:
        raise VisualError("keyframe animation requires 1 to 12 group tracks")
    visible = {e["group"] for e in scene["elements"] if isinstance(e.get("group"), str)}
    seen: dict[str, list[dict]] = {}
    for track in tracks:
        if not isinstance(track, dict) or set(track) != TRACK_FIELDS:
            raise VisualError("each motion track must specify a group and keyframes")
        name = track["group"]
        if not isinstance(name, str) or name not in visible or name in seen:
            raise VisualError("keyframe tracks must reference unique visible groups")
        keys = track["keyframes"]
        if not isinstance(keys, list) or not 2 <= len(keys) <= MAX_KEYS:
            raise VisualError("each motion track requires 2 to 6 keyframes")
        normalised = []
        previous_at = -1.0
        for key in keys:
            if not isinstance(key, dict) or set(key) != MOTION_FIELDS:
                raise VisualError("motion keyframes require at, dx, dy, scale, opacity, rotation and easing")
            at = _number(key["at"], "keyframe position", 0.0, 1.0)
            if at <= previous_at:
                raise VisualError("keyframes must have strictly increasing positions")
            previous_at = at
            easing = key["easing"]
            if not isinstance(easing, str) or easing not in ALLOWED_EASING:
                raise VisualError("unsupported keyframe easing")
            normalised.append({
                "at": at, "dx": _number(key["dx"], "keyframe dx", -250, 250),
                "dy": _number(key["dy"], "keyframe dy", -250, 250),
                "scale": _number(key["scale"], "keyframe scale", 0.5, 1.5),
                "opacity": _number(key["opacity"], "keyframe opacity", 0, 1),
                "rotation": _number(key["rotation"], "keyframe rotation", -45, 45),
                "easing": easing,
            })
        if abs(normalised[0]["at"]) > 0.00001 or abs(normalised[-1]["at"] - 1) > 0.00001:
            raise VisualError("each motion track must start at 0 and end at 1")
        seen[name] = normalised
    return seen


def _ease(t: float, name: str) -> float:
    if name == "ease-in":
        return t * t
    if name == "ease-out":
        return t * (2 - t)
    if name == "ease-in-out":
        return t * t * (3 - 2 * t)
    return t


def interpolate(keys: list[dict], progress: float) -> dict[str, float]:
    """Deterministic position/scale/opacity/rotation sample at a frame time."""
    p = max(0.0, min(1.0, float(progress)))
    for index in range(len(keys) - 1):
        left, right = keys[index], keys[index + 1]
        if p <= right["at"]:
            ratio = (p - left["at"]) / (right["at"] - left["at"])
            amount = _ease(max(0.0, min(1.0, ratio)), left["easing"])
            return {k: left[k] + (right[k] - left[k]) * amount
                    for k in ("dx", "dy", "scale", "opacity", "rotation")}
    return {k: keys[-1][k] for k in ("dx", "dy", "scale", "opacity", "rotation")}


def motion_raster(scene: dict, progress: float, config: dict, scale: float = 1.0):
    """Render visible group sprites in paint order; no workspace modifications."""
    from PIL import Image, ImageDraw
    # Lazy import avoids a circular dependency with the normal renderer.
    from automoto.visual_renderer import _draw_element
    tracks = validate_keyframes(scene, config)
    w, h = round(scene["width"] * scale), round(scene["height"] * scale)
    if w < 1 or h < 1 or w * h > 2_100_000:
        raise VisualError("motion preview exceeds the bounded canvas")
    frame = Image.new("RGB", (w, h), scene["tokens"]["background"])
    draw = ImageDraw.Draw(frame)
    rendered = set()
    groups: dict[str, list[dict]] = {}
    for element in scene["elements"]:
        key = element.get("group")
        if key in tracks:
            groups.setdefault(key, []).append(element)

    for element in scene["elements"]:
        group = element.get("group")
        if group not in tracks:
            # Keep workflow connectors attached to moving groups' translated
            # anchors. Rotation/scale of a group remain visual transforms,
            # not mutations to the connector's original scene coordinates.
            drawn = element
            if element["type"] == "line":
                source = element.get("from_group")
                target = element.get("to_group")
                a = interpolate(tracks[source], progress) if source in tracks else None
                b = interpolate(tracks[target], progress) if target in tracks else None
                if ((a and a["opacity"] <= 0.03) or (b and b["opacity"] <= 0.03)):
                    continue
                if a or b:
                    drawn = dict(element)
                    if a:
                        drawn["x1"] += a["dx"]
                        drawn["y1"] += a["dy"]
                    if b:
                        drawn["x2"] += b["dx"]
                        drawn["y2"] += b["dy"]
            _draw_element(frame, draw, drawn, scale)
            continue
        if group in rendered:
            continue
        rendered.add(group)
        # Only the target group is painted to a transparent layer.
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        brush = ImageDraw.Draw(layer)
        for item in groups[group]:
            _draw_element(layer, brush, item, scale)
        bbox = layer.getbbox()
        if not bbox:
            continue
        sprite = layer.crop(bbox)
        state = interpolate(tracks[group], progress)
        if state["opacity"] <= 0:
            continue
        if abs(state["scale"] - 1) > 1e-5:
            sprite = sprite.resize(
                (max(1, round(sprite.width * state["scale"])),
                 max(1, round(sprite.height * state["scale"]))),
                Image.Resampling.BICUBIC,
            )
        if abs(state["rotation"]) > 1e-5:
            sprite = sprite.rotate(-state["rotation"], resample=Image.Resampling.BICUBIC, expand=True)
        if state["opacity"] < 1:
            opacity = sprite.getchannel("A").point(lambda v: round(v * state["opacity"]))
            sprite.putalpha(opacity)
        cx = (bbox[0] + bbox[2]) / 2 + state["dx"] * scale
        cy = (bbox[1] + bbox[3]) / 2 + state["dy"] * scale
        x = round(cx - sprite.width / 2)
        y = round(cy - sprite.height / 2)
        frame.paste(sprite, (x, y), sprite)
    return frame
