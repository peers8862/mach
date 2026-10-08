---
mach: 1
type: recipe
name: morning
title: Morning brief (health, queue, due prompts, Linear, brief)
description: Gathers doctor output, the queue, prompt docs due today and assigned Linear issues, then writes brief.md in the run folder.
---
Built-in recipe (plan 08 section 3.3). Fits alongside the Drafts Morning Brief. Nothing here posts anywhere; the last step
only captures the brief with `mach note` (to the default or Drafts destination), which is a note, not an outward action.

## 1. Health
cmd: doctor --quiet
output: health.md

## 2. Queue
cmd: queue
output: queue.md

## 3. Due today
cmd: queue --due today
output: due-today.md

## 4. Linear issues
tool: claude
prompt: Using the Linear MCP server, list the open issues assigned to me (ID, title, state, due date), one line each, most urgent first. If Linear is not available in this session, say so in one line and stop. Do not change anything.
output: linear.md

## 5. Write the brief
tool: claude
prompt: Write a morning brief in Markdown, under 25 lines, from these inputs. Lead with anything that needs action today (warnings, approvals waiting, due prompts), then the Linear issues, then a one-line health summary. Inputs: {steps_text}
output: brief.md

## 6. Capture the brief
cmd: note drafts --title "Morning brief {date}" --tag morning --file {brief}
output: note.md
