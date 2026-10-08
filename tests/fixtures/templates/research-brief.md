---
mach: 1                      # schema version
type: research
title: Short name for this research
question: The one question to answer
output: files/research/YYYY-MM-DD-slug.md   # or stdout
depth: quick                 # quick (one sourced pass) | deep (runs the research-to-plan flow)
tool: auto                   # claude | codex | cursor-agent | grokcli-agent | kiro | auto
sources: [web]               # any of: web, repo, linear, files
machine: any                 # a machine name from [machines] | any
due: ""                      # YYYY-MM-DD, optional
approval: none               # none | before-run | before-apply
tags: []
---
Why this matters and what decision it feeds. Say what's already known and what to leave out.

## Context
- (links, paths, earlier notes)

## Answer format
- Lead with the answer, then the evidence. Cite every source with a link and the date checked.
