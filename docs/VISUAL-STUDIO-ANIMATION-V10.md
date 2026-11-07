# AutoMoto Visual Studio v10 — Advanced keyframe motion

**Development-only milestone.** Microsoft Store publication remains paused until the wider AutoMoto AI roadmap is completed and approved.

## What v10 delivers

Visual Studio supports a new **Keyframe motion** effect alongside the existing Flow, Pulse, Float, Reveal and Layer timeline GIF effects. It animates **visible native groups** in the editable canvas. The timeline controls can place up to six keys per group, adjust timing (for intermediate keys), edit X/Y offset, scale, opacity, rotation and choose interpolation easing (linear, ease-in, ease-out, ease-in-out). A single animation can control up to 12 groups.

Keyframe fields are strictly bounded: X/Y offsets −250 to +250 design units, scale 0.5–1.5, opacity 0–1, rotation −45° to +45°. Each track requires ordered keys at 0% and 100%. Keyframes are stored in `spec.animation` with the native design, so they survive saving/reopening, layered exports, and in-session Undo/Redo. Original scene geometry, wording, group membership, uploaded photo pixels and original asset files **are never changed by rendering motion**.

## Using the editor

1. Open Visual Studio with a grouped workflow, poster or editable feature cards; for freeform artwork, select and group related unlocked layers first.
2. Select **Animated GIF → Keyframe motion**. Choose a group and its 0% or 100% key from the track panel.
3. Move the playhead to a position between 1% and 99% and select **Add at playhead** to insert a key. Edit X/Y, scale, opacity, rotation and easing; any intermediate key can be moved or removed. The 0% and 100% endpoints cannot be removed.
4. Scrub to inspect exact rendered frames through the existing server preview. **Play motion preview** renders one bounded GIF locally for smooth browser playback, without dozens of per-frame API calls. Select **Stop playback** to return to the still frame inspector.
5. Export as an actual animated GIF. Keep **Editable layers + file** selected if you also want the native layers and keyframes saved alongside the output.

Existing Layer timeline (group reveal), Flow, Pulse, Float and Reveal modes continue to work. GIFs remain limited to 8–48 frames, 50–500 ms/frame, a one-megapixel canvas and loop count 0–20 (0 means infinite). Real-time preview may downscale to a maximum 720px edge and up to 24 sample frames; **final exported GIF** uses the selected 8–48 frames at the source canvas resolution. A preview does not write temporary files.

## Safeguards and limits

- All keyframe schema fields are explicitly validated on the server before preview and before export. Unknown fields, duplicate groups, missing groups, unsorted times, non-finite values, unsupported easing and out-of-range transformations are rejected.
- Authenticated preview and render routes use the same workspace image validation, visual-quality checks, origin restrictions and server rate limiting as existing Visual Studio workflows. Preview files are constructed in memory only.
- Native grouped text, shapes, icons and image copies animate as a unit; original images remain unchanged on disk.
- Connector endpoints follow **group translations**, although the connector attachment cannot precisely follow arbitrary rotation/scale of a group. Advanced rigging and path-based connectors are outside this milestone.
- Animated GIF is the real supported animation delivery format; **MP4/WebM or native PowerPoint transition/keyframe playback are not claimed**. PowerPoint remains a static editable slide deck. Browser playback Stop returns to a static frame; it is not a frame-exact GIF pause.

## Test gates

Run `python -m pytest -q tests/test_visual_motion.py tests/test_visual_studio.py tests/test_visual_foundation.py`, then `cd apps/desktop && npm run test:ui`. Tests cover real changing GIF frames and preview, interpolation, easing, strict hostile keyframe validation, asset checksum protection, saved editable keyframe drafts, browser controls, real animated preview and backward compatibility with the original sequence timeline.

Check Windows, Linux and macOS automated tests, security, Office and app-install workflows and manually inspect motion before merging. This release does not create a Store submission, tag or installer publication.

**After v10:** close Visual Studio's remaining critical defects and shift major feature development to the offline **Document Assistant**.
