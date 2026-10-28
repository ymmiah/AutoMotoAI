---
name: audio-editing
description: Edit audio with ffmpeg (or SoX) - convert, cut, join, normalise loudness, fade, denoise, change speed.
category: media
tools: run_app
apps: ffmpeg
optional_apps: sox
status: live
---
# Audio editing

Inspect: `run_app` `ffprobe` `["-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "compact", "in.wav"]`.

| Task | `run_app` `ffmpeg` args |
|---|---|
| Convert to MP3 | `["-i", "in.wav", "-c:a", "libmp3lame", "-q:a", "2", "out.mp3"]` |
| Cut 0:30-1:10 | `["-ss", "30", "-to", "70", "-i", "in.mp3", "-c", "copy", "cut.mp3"]` |
| Normalise (podcast −16 LUFS) | `["-i", "in.wav", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "norm.wav"]` |
| Fade in/out | `["-i", "in.mp3", "-af", "afade=t=in:d=2,afade=t=out:st=58:d=2", "faded.mp3"]` |
| Basic denoise | `["-i", "in.wav", "-af", "highpass=f=80,lowpass=f=12000,afftdn=nf=-25", "clean.wav"]` |
| Remove silence | `["-i", "in.wav", "-af", "silenceremove=start_periods=1:start_threshold=-50dB", "trim.wav"]` |
| Join | `list.txt` with `file 'a.mp3'` lines, then `["-f", "concat", "-i", "list.txt", "-c", "copy", "joined.mp3"]` |
| Mono, 16 kHz (speech AI) | `["-i", "in.mp3", "-ac", "1", "-ar", "16000", "speech.wav"]` |
| Speed ×1.25 | `["-i", "in.mp3", "-af", "atempo=1.25", "faster.mp3"]` |

SoX (if installed): `run_app` `sox` `["in.wav", "out.wav", "norm", "-1", "fade", "1", "0", "1"]`.
Check loudness after: `["-i", "norm.wav", "-af", "ebur128", "-f", "null", "-"]`.
