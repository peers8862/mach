---
mach: 1
type: recipe
name: issue-to-pr
title: Linear issue to pull request (read issue, branch plan, implementation plan, gates, PR handoff)
description: Reads a Linear issue, prepares branch/worktree/tmux commands and an implementation plan, and hands off the PR. Never edits code or opens a PR itself in v1.
input: the Linear issue id, e.g. ENG-79
---
Built-in recipe (plan 08 section 3.3). v1 limits, on purpose: the implementation step only PLANS (read-only); branch creation,
code changes, tests and the PR are handoff commands you run. Outward actions are never executed by mach.

## 1. Read the issue
tool: claude
prompt: Using the Linear MCP server, read issue {ticket} (input: {input}). Summarise the goal, acceptance criteria, linked context and any open questions in under 30 lines. If Linear is not available in this session, say so and stop. Do not change anything.
output: issue.md

## 2. Branch, worktree and tmux (handoff)
handoff: Create the branch and worktree yourself (branch named per CLAUDE.md, lower case):
  git worktree add ../{branch} -b {branch}
  tmux new-session -d -s {branch} -c ../{branch}
  Then attach with: tmux attach -t {branch}

gate: Confirm the branch name {branch} and that the issue summary in {prev} is the right work. Approve to plan the implementation.

## 3. Implementation plan
tool: claude
prompt: Plan the implementation of this issue as a numbered, file-level change list with the test commands to run and the risks. Do not edit any file. Issue summary: {prev_text}
output: implementation-plan.md

gate: Review {prev}. Approve to get the test and PR handoff, reject to stop.

## 4. Tests and pull request (handoff, never automatic)
handoff: Do these in the worktree, in order:
  1. Implement the plan in {run_dir}/implementation-plan.md with the tool you prefer (for example: mach do "implement ..." --path ../{branch} --write --yes).
  2. Run the project's tests and read the diff yourself.
  3. Push the branch and open the PR yourself. Title format: [{ticket}] Short description. Link the Linear ticket. Body: What changed, Why, How to test.
     gh pr create --title "[{ticket}] ..." --body-file <body file>   (mach never runs gh)
