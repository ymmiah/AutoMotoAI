---
name: premiere-pro
description: Work with Adobe Premiere Pro projects - open projects/media in Premiere; do the actual cuts with ffmpeg when automation is needed.
category: media
tools: open_in_app, run_app
apps: premiere
optional_apps: ffmpeg
status: untested
---
# Premiere Pro

Premiere's scripting (ExtendScript/UXP) only runs from a panel *inside* Premiere, so AutoMoto can't drive edits
directly - it never fakes it.
- Open a project or clip: `open_in_app` `premiere` `edits/project.prproj` (approval).
- Prepare media for the user with ffmpeg first (`video-editing` skill): trims, proxies
  (`["-i", "in.mp4", "-vf", "scale=-2:540", "-c:v", "libx264", "-crf", "23", "proxy.mp4"]`), audio normalisation.
- Write an edit decision list (EDL/CSV of in/out points) to `scratch/edl.csv` that the user can follow or import.
- Exports from Premiere are done in Premiere (or Adobe Media Encoder) by the user.
