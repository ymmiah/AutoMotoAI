---
name: linux-terminal
description: Use the Linux/macOS terminal safely - find files, inspect processes, disk, network, logs, text processing.
category: system
tools: run_shell
status: live
---
# Linux terminal (safe patterns)

Commands run in the working folder through `run_shell` (you approve each one). Destructive commands that reach
outside it, `sudo`, `curl | sh`, and anything touching SSH keys, keychains or `.env` files are blocked.

- Look before you act: `pwd; ls -la`, `du -sh * | sort -h`, `df -h`, `file x`, `head -n 50 log.txt`.
- Find: `find . -name '*.py' -mtime -2`, `grep -rn "TODO" --include=*.js .`, `rg pattern` if installed.
- Text: `wc -l`, `sort | uniq -c | sort -rn | head`, `cut -d, -f2`, `awk -F, '{s+=$3} END {print s}'`, `sed -n '10,20p'`, `jq .` for JSON.
- Processes: `ps aux --sort=-%mem | head`, `top -b -n1 | head -20`, `lsof -i :8000` (ports).
- Network checks: `curl -sI https://example.com`, `dig +short example.com`, `ss -tlnp`.
- Archives: `tar czf out.tgz folder/`, `tar xzf in.tgz`, `zip -r out.zip folder`, `unzip -l in.zip`.
- Permissions inside the project: `chmod +x script.sh` (only inside the working folder).
- Prefer dry runs: `rsync -avn`, `find … -print` before `-delete`, `git clean -n` before `-f`.
- Explain every command you propose in one line so the user can approve it confidently.
Windows: the same tool runs `cmd`; for PowerShell use `powershell -NoProfile -Command "..."`.
