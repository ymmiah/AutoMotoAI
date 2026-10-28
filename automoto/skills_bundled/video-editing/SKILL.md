---
name: video-editing
description: Edit video with ffmpeg - trim, cut, join, resize, compress, add subtitles or music, make GIFs.
category: media
tools: run_app
apps: ffmpeg, ffprobe
status: live
---
# Video editing (ffmpeg)

Always inspect first: `run_app` `ffprobe` `["-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height", "-of", "compact", "in.mp4"]`.
Write outputs to new names (never overwrite the input). Use `run_app` `ffmpeg` with `-y` only for outputs.

| Task | args |
|---|---|
| Trim (fast, keyframe) | `["-ss", "00:00:05", "-to", "00:00:20", "-i", "in.mp4", "-c", "copy", "clip.mp4"]` |
| Trim (exact) | `["-ss", "5", "-to", "20", "-i", "in.mp4", "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "clip.mp4"]` |
| Resize to 720p | `["-i", "in.mp4", "-vf", "scale=-2:720", "-c:a", "copy", "720p.mp4"]` |
| Compress for web | `["-i", "in.mp4", "-c:v", "libx264", "-crf", "28", "-preset", "medium", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "small.mp4"]` |
| Join clips | write `list.txt` with lines `file 'a.mp4'` then `["-f", "concat", "-i", "list.txt", "-c", "copy", "joined.mp4"]` |
| Burn subtitles | `["-i", "in.mp4", "-vf", "subtitles=subs.srt", "out.mp4"]` |
| Replace audio | `["-i", "in.mp4", "-i", "music.mp3", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-shortest", "out.mp4"]` |
| Extract audio | `["-i", "in.mp4", "-vn", "-c:a", "libmp3lame", "-q:a", "2", "audio.mp3"]` |
| GIF | `["-i", "in.mp4", "-vf", "fps=12,scale=480:-1:flags=lanczos", "out.gif"]` |
| Thumbnail | `["-ss", "3", "-i", "in.mp4", "-frames:v", "1", "thumb.jpg"]` |
| Speed ×2 | `["-i", "in.mp4", "-filter:v", "setpts=0.5*PTS", "-filter:a", "atempo=2.0", "fast.mp4"]` |

Notes: network URLs are refused (download with fetch_url first). For long encodes pass `timeout` (seconds).
Premiere Pro: see the `premiere-pro` skill (open-only).
