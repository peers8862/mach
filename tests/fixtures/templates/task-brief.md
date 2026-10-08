---
mach: 1                      # schema version
type: task
title: Short name for this task
goal: One sentence, the outcome you want
tool: auto                   # claude | codex | cursor-agent | grokcli-agent | kiro | auto
output: stdout               # path under machine-flows or a repo | stdout | pr | linear-comment (pr and linear-comment are always gated)
path: ""                     # working folder, or a project id from service-memories/project-map.tsv; empty = machine-flows
machine: any                 # a machine name from [machines] | any
due: ""                      # YYYY-MM-DD, optional
approval: before-apply       # none | before-run | before-apply
tags: []
---
What to do, in a few plain sentences. Name the files, issues or commands involved.

## Context
- (links, paths, ticket ids)

## Done when
- (checks that prove it's finished)
