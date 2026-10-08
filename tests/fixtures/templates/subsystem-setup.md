---
mach: 1
type: subsystem-setup
title: Set up Example subsystem
id: example
name: Example subsystem
working_root: ~/example
linear_team: ""
note_dest: inbox
max_fires_per_day: 20
reply: chat
---
Use `mach subsystem new example --from this-file.md` to preview; add `--apply` to write.
Each `## Repo: id`, `## Unit: id`, or `## Service: dest` section has flat `key: value` lines. Arrays use `[one, two]`; booleans use `true` or `false`. Unit roles use `roles.<role>: <dest>`; `roles.changed` and `roles.assignments` are arrays. Routines, recipes and agent-file sources go in `routines`, `recipes`, and `agent_files` on each unit. IDs are lowercase kebab. Keep each section unique.

## Repo: example
path: ~/example/repo
remote: org/example
verified: false
source: proposed

## Unit: example
name: Example unit
kind: pillar
repo: example
special: false
types: []
routines: []
agent_files: []
recipes: []
verified: false
notes: Example unit
roles.lead: grokbot:Example
roles.since: 2026-10-08
roles.changed: []
roles.assignments: []

## Service: grokbot:Example
strengths: [drafting]
limits: [each fire uses Grok Bot quota]
workloads: []
notes: Example bot profile
