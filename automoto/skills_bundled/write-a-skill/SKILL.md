---
name: write-a-skill
description: Turn a task you just finished into a reusable SKILL.md the user can keep.
---
# Write a skill

1. Summarise the steps that worked as a short numbered list (tools used, order, checks).
2. Pick a kebab-case name and a one-line description.
3. Show the user the SKILL.md (front matter `name` + `description`, then the steps).
4. Save it with `write_file` to `scratch/skills/<name>/SKILL.md` and tell the user to move it to
   `~/.automoto/skills/<name>/SKILL.md` to install it (AutoMoto never writes outside its workspace).
