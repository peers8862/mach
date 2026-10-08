---
mach: 1
type: recipe
name: research-to-plan
title: Research to plan (sourced report, gate, plan draft, gate, register handoff)
description: Researches a question, drafts a plans/NN-*.md following plans/README.md, and hands off the registration steps.
input: the research question
---
Built-in recipe (plan 08 section 3.3). Both gates are real stops: nothing changes in `plans/` until you do the handoff yourself.

## 1. Research
tool: claude
prompt: Research this question using web search. Write a sourced report in Markdown. Lead with the answer, then the evidence. Cite every source with a link and the date checked, and end with a "## Sources" section. Say plainly what you could not verify. Question: {input}
output: research.md

gate: Read {prev} (the sourced report). Approve to draft a plan from it, or reject to stop.

## 2. Draft the plan
tool: claude
prompt: Read ~/machine-flows/plans/README.md first. Then draft a plan document that follows its convention exactly - "# NN: Title", a Status line, 1-3 short paragraphs, then checklists and tables; facts carry a date and a source; no secrets. Use the number {next_plan} for NN. Base it on this research: {prev_text}
output: plan-draft.md

gate: Review the plan draft in {prev} before it is registered. Approve to get the registration handoff, reject to stop.

## 3. Register (handoff, never automatic)
handoff: Register the plan yourself, in this order (plans/README.md sections 1, 2 and 4):
  1. Copy the draft: cp {run_dir}/plan-draft.md ~/machine-flows/plans/{next_plan}-{slug}.md (and edit the title/number).
  2. Add a row to the register table in plans/README.md section 2.
  3. Add a dated line to plan 00's Change log.
  4. Update the docs index: mach docs  (preview), then mach docs --apply. Rebuild the workbook only if you ask: mach docs build.
