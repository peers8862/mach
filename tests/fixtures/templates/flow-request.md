---
mach: 1                      # schema version
type: flow
title: Short name for this run
flow: research-to-plan       # a recipe in the mach flows/ folder (research-to-plan | issue-to-pr | morning | ...)
input: ""                    # what the flow starts from: a question, a ticket id, a path
machine: any                 # a machine name from [machines] | any
output: ""                   # optional; the recipe sets a default
due: ""                      # YYYY-MM-DD, optional
approval: before-run         # none | before-run | before-apply (the recipe's own gates always apply)
tags: []
---
Anything the flow should know that the input doesn't say: limits, preferences, what to skip.

## Context
- (links, paths, ticket ids)
