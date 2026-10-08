# mach guide

The guidance document for people and agents. Spec history: `plans/08-mach-cli.md` (design), `plans/09-memory-and-lessons.md` (memory
rules). Command-by-command reference: [COMMANDS.md](COMMANDS.md) (generated). Decisions made while building: [DECISIONS.md](DECISIONS.md).
Version 1.3.0, 2026-10-08.

## 1. What machine-flows and mach are

**machine-flows** is a folder (`~/machine-flows/`) synced by Syncthing between the user's computers (typically a Mac and one or more
Linux laptops; the examples call them `mac-laptop` and `linux-box`). It holds shared plans, inventories, AI rules, MCP definitions, prompt templates, notes
and run records. Nothing secret lives in it, and there are no symlinks inside it (Syncthing would sync the links themselves).

**mach** is its command line. The name is the German imperative of *machen* ("do/make", *Mach das!* = "Do it!"); the noun *Macht* means
power. It has two halves:

1. **Upkeep** keeps the multi-machine system healthy: doctor, inventory, docs index, CLI names, services, MCP, AI wiring, memory review,
   plan archiving, onboarding. It does the chores; the user approves.
2. **Work gateway** takes work in (a one-liner, a prompt document written in Drafts, a recipe) and sends it to the right tool on the
   right machine, keeps a record, and stops at approval gates.

## 2. Design rules

- **Preview first.** Administrative changes print exactly what they will do and stop. They act only with `--apply` (or an interactive
  `y` on a terminal; `--yes` also counts). Before applying it backs up to `~/machine-flows-staging/backups/<ts>-mach-<cmd>/` and prints a
  one-line rollback (`rollback: bash ~/machine-flows-staging/backups/<run>/rollback.sh`; paste it as printed, the `~` expands).
- **Portable.** Bash 3.2 (macOS 12) and python3 3.9 standard library only. `lib/minitoml.py` replaces `tomllib` where it is missing.
  No GNU-only flags in the scripts (no `readlink -f`, `sed -i` without a suffix, `date -d`, `stat -c`, `find -printf`, `grep -P`).
- **Explicit tool names.** `claude`, `codex`, `cursor-agent` (Cursor CLI), `grokcli-agent` (xAI grok CLI, Mac) and `kiro` (runs `kiro-cli`).
  Never a bare `agent`. Grok Bot, the app, has no CLI: `mach ask grokbot` writes a paste-ready prompt and a queued item.
- **Safe by default.** No sudo and no secret values printed. Subsystem sends are explicit commands and execute immediately; other outward work uses gates. Router credentials are read only from a mode-600 unsynced file.
- **Light on the Mac.** No version-probing by running binaries there, no heavy scans by default.
- **Script-friendly.** Exit codes 0 OK, 1 warnings, 2 failure, 3 waiting for approval. `--json` where it helps.

## 3. Commands

Run `mach help` or `mach <command> --help`. Examples:

### Upkeep

```bash
mach doctor [--json] [--quiet]        # OK|WARN|FAIL|INFO per check, summary, exit by worst; read-only, < 15 s
mach inventory [--section 70] [--apply]
mach docs                              # preview CSV changes; --apply writes. `mach docs build` only when you ask for the workbook
                                       # personal history (purposes, dates, extra rows): docs-history.local.py, see below
mach names [--fix [--apply]]
mach services [show|check] [--update]  # --update prints a proposed patch (v1 never writes the 75/76 files)
mach mcp render [--tool cursor-agent]  # `mach mcp apply --apply` passes through to mcp-apply.sh (a stub)
mach ai apply [rules|skills] [--tool codex] [--apply]
mach memory init [--reindex] [--apply]  # create the plan 09 lessons skeleton (README, generated INDEX.md, topic folders, archived/); never overwrites
mach memory review [--save] [--apply]  # --save: lessons/reviews/YYYY-MM.md (never overwrites: -2, -3); collect / promote: preview-only in v1
mach plans list | mach plans archive 04 [--apply]
mach onboard [--apply]
mach sheets lint|build <dir> | mach sheets new <dir> [--apply] | mach sheets refresh mach [--build|--check]   # sheet sets, see "Sheet sets"
```

### Work gateway

```bash
mach do "tidy the headings in plan 04" [--tool T] [--machine M] [--path P] [--write] [--bg] [--yes] [--dry-run]
mach ask codex "why does mcp-apply skip Kiro on linux-box?" [--write] [--dry-run]
mach note "Kiro skills: copy, not link"      # inbox by default
mach note agenda "call the plumber" --project Home --tag urgent
pbpaste | mach note drafts
mach note --to agenda -- "agenda for Monday"
mach research "Syncthing on macOS 12: launchd vs app" [--depth deep]
mach run files/inbox/prompts/2026-10-09-weekly-status.md [--dry-run | --queue]     # a prompt document
mach run --inbox                                 # run waiting documents addressed to this machine
mach flow morning | research-to-plan "question" | issue-to-pr ENG-79
mach status [id]   mach queue   mach approve <id> [--step N]   mach reject <id> "reason"
```

## 4. Configuration and precedence

mach works with **no config file**. Optional files (TOML; no secrets):

| Layer | File |
| --- | --- |
| shared | `~/machine-flows/service-settings/mach/config.toml` (synced) |
| host | `~/machine-flows/service-settings/mach/hosts/<host>.toml` (synced; each machine reads only its own) |
| local | `~/.config/mach/local.toml` (unsynced, for experiments) |

Precedence: **command-line flags > environment (`MACH_NOTE_DEFAULT`, `MACH_DEFAULT_TOOL`, `MACH_PEER_SSH`, `MACH_RETENTION_DAYS`) >
local > host > shared > built-in defaults.** `config/config.example.toml` documents every key; `config/hosts/*.example.toml` show per-host
overrides. Test and relocation knobs: `MACH_MF_ROOT` (default `~/machine-flows`), `MACH_STAGING` (`~/machine-flows-staging`),
`MACH_STATE_DIR` (docs-index state, default `<staging>/docs-index`), `MACH_RUNS_DIR`, `MACH_CONFIG_DIR` (replaces the shared+host folder and
holds `local.toml`), `MACH_HOST`, `MACH_OS`, `MACH_BIN_DIR`, `MACH_NOW`. Machine names: `MACH_HOST`, else the short hostname mapped by `[machines.match]`
(lower-case prefix -> name), else the short hostname unchanged. `[machines]` also lists `names`, the `mac` machine that delivers notes and
the `collector` that runs `mach docs collect`; `MACH_HOSTNAME` pins the hostname for tests, `MACH_DOCS_COLLECTOR` overrides the collector.

## 5. Run records

Every `do`, `ask`, `research`, `run` and `flow` creates `files/runs/YYYY/MM/<id>/`:

```text
run.md      frontmatter (id, created, machine, tool, path, status, input, outputs, gate, ...) + steps table + notes
input.md    a copy of the input (prompt document, task text or flow input); the original is never modified
output-N.md / step-N-*.md / handoff-*.md   outputs
```

- **Run id:** `YYYYMMDD-HHMM-<host>-<slug>` (`-2`, `-3` on collision). Each machine writes only its own records.
- **Status:** `queued`, `running`, `waiting-approval`, `done`, `failed`, `cancelled`.
- **Logs:** raw logs stay local (`~/.local/state/mach/logs/<id>.log`); `*.log` is in `.stglobalignore` on purpose. `run.md` holds a short summary.
- **One executor:** a queued item runs only on the machine in its `machine:` field; `machine: any` means the background machine (`[queue] background_machine`, default the machine you run on).
  v1 has no SSH execution: `--machine` other than the current one creates a queued record for that machine.
- **Retention:** full records for 90 days, then monthly summaries (config key `runs.retention_days`; compaction itself is a later step).

## 6. Notes (`mach note`)

A note is captured text; nothing runs and no run record is made. Destinations: `inbox` (any machine), `agenda`, `drafts`, and named ones
from `[note.dest.<name>]` (`type` = `file`, `inbox`, `agenda` or `drafts`).

| Destination | macOS | Linux |
| --- | --- | --- |
| `inbox` | appends to `files/inbox/notes/YYYY-MM-DD-<host>.md` (`## HH:MM title`, `tags:` line, text) | same |
| `agenda` | Agenda MCP at `127.0.0.1:16106` (localhost, no token) -> `open -g agenda://x-callback-url/create-note?...` -> outbox | outbox |
| `drafts` | `drafts create ...` CLI -> `open -g drafts://x-callback-url/create?...` -> outbox | outbox |
| named `file` | appends to a path inside machine-flows; refuses paths outside | same |

The first word is a destination only if it matches a name; `--to` and `--` remove the ambiguity. Options: `-t/--title`, `--tag` (repeatable),
`--tags a,b`, `--project`, `--date`, `--flag`, `--open`, `--file PATH`, `--dry-run`, `--json`; stdin when there is no text or the text is `-`.
**A fallback is never silent** and exits 1 (`queued -> outbox/agenda (...; deliver with: mach note flush on mac-laptop)`). `mach note flush --apply`
on the Mac delivers `files/inbox/outbox/<dest>/*.md` and removes them. `mach queue` lists outbox items; `mach doctor` warns after 24 h. A local log
`~/.local/state/mach/notes.log` records time, destination and method only, never the text.

## 7. Prompt documents and templates

Templates live in `ai-authored/templates/` (`task-brief.md`, `research-brief.md`, `flow-request.md`). A prompt document is Markdown with
flat-YAML frontmatter (`key: value`, inline lists, `#` comments, no nesting); the body is the prompt.

| `type` | Required keys | Optional keys |
| --- | --- | --- |
| `task` | `mach`, `type`, `title`, `goal`, `tool`, `output` | `path`, `machine`, `due`, `approval`, `tags` |
| `research` | `mach`, `type`, `title`, `question`, `output` | `depth`, `tool`, `sources`, `machine`, `due`, `approval`, `tags` |
| `flow` | `mach`, `type`, `title`, `flow`, `input` | `machine`, `due`, `approval`, `output`, `tags` |

Values: `mach: 1`; `tool` = claude, codex, cursor-agent, grokcli-agent, kiro, auto; `machine` = any, or a name from `[machines] names`; `approval` = none,
before-run, before-apply; `depth` = quick, deep; `sources` = web, repo, linear, files; `output` = a path (relative paths are under
machine-flows; `YYYY-MM-DD` and `slug` are substituted), `stdout`, `pr` or `linear-comment` (the last two are outward and always gated).
`mach run` refuses unknown keys or values with `file:line: error: ...` (exit 2). An empty required `input:` in a flow document is a warning
in `--dry-run` and an error on a real run.

## 8. Flows and gates

Recipes are Markdown: frontmatter (`type: recipe`, `name`), then numbered steps (`## 1. Title`) with keys `tool`, `machine`, `prompt`,
`cmd` (a mach command), `handoff`, `output`, and `gate:`. `mach` looks in `~/machine-flows/autoflows/mach/<name>.md` first, then the built-in
`flows/`. Placeholders in prompts: `{input}`, `{prev}`, `{prev_text}`, `{steps_text}`, `{run_dir}`, `{date}`, `{host}`, `{ticket}`, `{branch}`,
`{next_plan}`, `{slug}`, `{brief}`.

- **Gates.** A `gate:` line pauses the run **after** that step (status `waiting-approval`, exit 3). `mach approve <id> [--step N]` continues;
  `mach reject <id> "reason"` cancels. Prompt documents have gates too: `approval: before-run` (stop before executing), `before-apply` (run
  read-only, hold the output, write the output file only after approval) and any outward `output`.
- **Outward steps are never executed in v1,** even after approval. They produce a ready-to-run command or draft (`handoff-*.md`) and the
  step is marked `handoff`: opening a PR (`gh pr create ...`), a Linear comment, registering a plan in `plans/`.
- **Built-in recipes.** `morning`: doctor -> queue -> due prompts -> Linear issues -> `brief.md` -> captured with `mach note drafts` (on Linux that
  is an outbox item, so the flow exits 1). `research-to-plan`: research -> gate -> plan draft following `plans/README.md` -> gate -> registration
  handoff. `issue-to-pr`: read the issue -> branch/worktree/tmux handoff -> gate -> implementation plan (read-only) -> gate -> tests and PR handoff.

## 8b. The docs history file (`mach docs`)

`mach docs` walks `~/machine-flows` and writes one row per file or folder. What only the user knows (why a file exists, which machine it
came from, change-log dates, rows for things outside machine-flows such as services, links and backups) is kept in **`docs-history.local.py`**,
a plain Python data file that is **never committed** (`.gitignore`: `config/docs-history.local.py`, `config/*.local.*`). The collector uses
the first of these that exists:

1. `$MACH_DOCS_HISTORY` (explicit path)
2. `$MACH_CONFIG_DIR/docs-history.local.py`
3. `~/machine-flows/service-settings/mach/docs-history.local.py` (synced to both machines; the usual home)
4. `<checkout>/config/docs-history.local.py`

Copy `config/docs-history.example.py` (every field is explained there) to one of those places and edit it. Without a file, `mach docs`
still works: generic purposes, no extra rows, one `INFO: no docs-history.local.py found` line.

## 9. Safety model

1. Tools run headless and **read-only** by default (`claude --permission-mode plan`, `codex exec --sandbox read-only`, `cursor-agent -p --mode ask`,
   `kiro-cli chat --no-interactive --trust-tools=`). `--write` (or `routes.permission = "write"`) opts into writes.
2. mach writes output files only inside machine-flows, the run folder or the working path, and never overwrites (`name-2.ext`).
3. `doctor` reads the Syncthing API key from `config.xml` at run time into a variable, sends it as a header, and never prints or stores it.
   Grok Bot: only `local-exec-daemon.json`, `local-exec-supervisor.json` and the log are read, never the credential or connection files.
4. No sudo, no timers/cron/launchd/systemd units are created, no Grok Bot settings are touched, no messages are sent.
5. `ai apply` writes only: missing import stubs, generated files that carry mach's own header, symlinks from tool folders into machine-flows
   (never inside it), copies for Kiro. A file with other content is "differs" and is left alone.

## 10. Exit codes

| Code | Meaning |
| --- | --- |
| 0 | OK |
| 1 | warnings (doctor WARN, a note fallback, invalid inbox documents, `mcp apply` stub) |
| 2 | failure (FAIL check, validation error, missing tool, refused action) |
| 3 | waiting for approval (a gate) |

## 11. Install and test

```bash
bash install.sh            # preview;  --apply links ~/.local/bin/mach -> <checkout>/bin/mach;  --uninstall removes it
bash tests/run.sh          # all tests; python3 -m unittest discover -s tests runs the python part alone
```

Tests run in sandboxes under `.tmp/` with mock AI tools on `PATH` (they print their arguments) and `HOME`, `MACH_MF_ROOT`, `MACH_STAGING`,
`MACH_RUNS_DIR`, `MACH_CONFIG_DIR`, `MACH_HOST` redirected. They never call a real paid tool or the network (the Agenda MCP test uses a fake
server on 127.0.0.1). Every outside program (`open`, `drafts`, `osascript`, `tmux`, `launchctl`, `systemctl`, `crontab`, `ssh`, the AI CLIs)
is pinned to a sandbox path through `MACH_*_CMD` variables (a missing file = "not available"), the Agenda MCP URL points at a closed port,
and canary stand-ins for the real programs sit on `PATH`: a test that reaches one fails. `MACH_TEST_OS=darwin bash tests/run.sh` runs the
suite with the Mac code paths where tests allow it (Linux-only sections then fail by design). `tests/test_lint.sh` greps for bash 4+ and GNU-only constructs, checks python syntax for 3.9, runs `shellcheck -s bash`
when installed, and checks the publishable files for personal data.

## 12. Roadmap and v1 status

| Command | v1 status | Next |
| --- | --- | --- |
| `doctor` | working | per-machine reachability over Tailscale (`tailscale ping`, ssh), peer-disconnect duration |
| `inventory` | working | --json, per-section regeneration |
| `docs` (collect, build, macstat) | working (history rows live in `docs-history.local.py`) | |
| `names` | working | |
| `services` | working (`--update` prints a patch only) | `--update` writes the 75/76 files after approval |
| `mcp` | `render` working; `apply` is a pass-through to a stub | implement `mcp-apply.sh --apply` |
| `ai` | working (safe writes); Cursor User Rules and Grok Bot skill are manual | settings merges (plan 03 stage E) |
| `memory` | `review` working; `collect`, `promote` preview-only | `collect`, `promote`, `migrate` (files/Lessons), monthly timer |
| `plans` | working | |
| `onboard` | working | |
| `sheets` | working (lint, build, new, refresh mach) | more generated sets (plans register, inventory) if wanted; a `--deep` lint that diffs workbook cells against the CSVs |
| `do`, `ask`, `research`, `run`, `flow`, `status`, `queue`, `approve`, `reject` | working | `--machine` over SSH/tmux (after Tailscale); retention compaction |
| `note` | working (flush, outbox, MCP, URL, CLI) | Obsidian / Apple Notes / Reminders destinations |
| Drafts "Mach Hub" action | spec only (plan 08 section 3.6) | build it; `mach inbox pull-drafts` for iPhone drafts |
| Timers | none installed by mach; an example is a systemd user timer on the collector machine that runs `mach memory review --save` monthly | morning flow, inbox pickup: each needs the user's approval and a row in `inventory/<host>/76-custom-scheduled-jobs.md` |

## 13. Rules for agents

- Read `plans/README.md` before touching a plan. Never archive a plan on your own judgment; `mach plans archive` needs the user's OK.
- When a task creates, changes or removes a **login/boot service**, update `inventory/<host>/75-custom-startup-services.md` in the same task;
  for a **scheduled job** (cron, launchd calendar job, systemd timer) update `76-custom-scheduled-jobs.md` (plan 00 rules 8 and 14).
  Shared `mach` jobs run on one machine only (the collector). mach itself installs no timers.
- When a task creates, retires, moves or replaces a machine-flows document or config file, update the machine's
  `inventory/<host>/docs-index.csv` (`mach docs`, then `--apply`). **Rebuild the workbook (`mach docs build`) only when the user asks** (plan 00 rule 10).
- Project tracking uses **sheet sets**: the CSVs are the source of truth, the workbook is generated and rebuilt with `mach sheets build <dir>`.
  Never edit an xlsx by hand, and run `mach sheets refresh mach` after changing commands, flags or functions (a test checks the drift).
- Use explicit tool names. After a Cursor or grok install or update run `mach names --fix`. Never call a bare `agent`.
- Never put secrets, IP addresses, device IDs or emails in committed files; write `~` instead of the home path.
- Machine unreachable? Retry about 3 minutes with backoff before calling it offline (plan 00 rule 13); copy files only under `~`, never `/tmp`.
- Prefer `--dry-run` / preview output when you are unsure; paste the preview to the user before `--apply`.

## Subsystems

Subsystems are keyed TOML manifests under `~/machine-flows/subsystems/<id>/subsystem.toml`. They describe units, repo pointers, roles and service profiles; the schema is in the `subsystems/README.md` of your machine-flows tree, and [`config/subsystem.example.toml`](../config/subsystem.example.toml) is a small working example (id `demo`). The command itself is an explicit send: `mach demo alpha "Summarize open decisions"` goes immediately to the unit's lead. Use `mach demo` for the unit tree, `mach demo alpha --roles` for assignments/history, `--role drafting` or `--to codex` to choose another destination, and `--dry-run` to preview the payload or command. CLI tools are read-only unless `--write` is given.

`mach subsystem list|show demo|lint demo` inspects manifests. `mach subsystem new demo --from draft.md`, `unit demo --from draft.md`, and `role demo --from draft.md` preview changes; `--apply` writes with a rollback backup. `mach queue` lists drafts waiting in `files/inbox/subsystems/`. `mach run` handles `type: subsystem-prompt` documents.

For Grok Bot delivery, create unsynced `~/.config/mach/secrets.toml` mode 600 with `[grokbot_router] url`, `key`, and optional `key_header = "Authorization: Bearer"`. Copy URL and key from the routine panel of **mach router: forward prompts to pillar bots**. A bare `key_header = "X-Webhook-Key"` sends `X-Webhook-Key: <key>`; `Authorization: Bearer` sends `Authorization: Bearer <key>`. The router payload carries subsystem, unit, dest, role, prompt, host, run_id, and reply. `--reply inbox` sets reply to `files/inbox/replies/<run_id>.md`. The manifest's `max_fires_per_day` caps router fires per local day from this machine's run records; `--force` overrides it. Missing or unsafe secrets queue a paste-ready prompt and exit 1. Successful 2xx posts mark the run done; delivery errors exit 2.

## Sheet sets

A **sheet set** is the reusable pattern for tracking anything (a project, a register, a self-description) in tables that humans can open in
Excel and agents can diff:

```text
tracking/
  index.csv          master index: id, file, sheet_name, title, description, owner, source, generated_by, updated, rows
  tasks.csv          the CSVs it lists: one header row, then records (source of truth)
  people.csv
  tracking.xlsx      generated: Index sheet first, then one sheet per CSV in index order (never edited by hand)
  sheets.toml        optional: workbook = "other-name" (default: the folder name)
```

**Start one for any project:** `mach sheets new <dir> --apply` writes `index.csv` (header only) and a `README.md` with the rules. Add one
index row per CSV, then `mach sheets lint <dir>` and `mach sheets build <dir>`. `build` is the explicit action, so it writes (after
backing up what it overwrites); `--dry-run` only reports. It sets `rows` and `updated` in `index.csv` and writes the workbook with a
frozen bold header row, an autofilter and sized columns. The xlsx is written with `zipfile` and minimal SpreadsheetML, so neither machine
needs openpyxl. Strings are stored as text, never as formulas. Lines with `FAIL` stop the build; lint exit codes are 0 OK, 1 warnings, 2 failures.

What `lint` checks: the index has exactly those columns; every CSV in the folder is indexed (no orphans) and every listed file exists;
`sheet_name` is unique (case-insensitive), at most 31 characters, free of `[ ] : * ? / \`, not `Index` or `History`; every CSV has a header
row and rectangular records; no cell over 32,767 characters or with control characters (FAIL), formula-like cells starting `=`/`@` and
absolute `/home/` or `/Users/` paths (WARN: use `~/` or repo-relative paths); `rows` equals the data-row count; `updated` is a date; the
workbook exists (WARN if not) and is current (FAIL if a CSV changed after the build). `updated` is the date the CSV's cells last changed,
recorded by `build` (see DECISIONS).

**`docs/sheets/` is mach's own set**, generated from the code, never typed:

| CSV | Sheet | Generated from |
| --- | --- | --- |
| `commands.csv` | Commands | `# mach-usage`, `-summary`, `-group`, `-subcommands`, `-status`, `-writes` headers of `libexec/mach-*` |
| `flags.csv` | Flags | usage lines, `# mach-flag: --flag \| meaning \| default` headers, shared flags, `bin/mach` global options |
| `functions.csv` | Functions | python docstrings/comments (ast) and bash function comments under `lib/` and `libexec/` |
| `config-keys.csv` | Config keys | `config/config.example.toml` plus `DEFAULTS` and `ENV_KEYS` in `lib/mach_common.py` |
| `destinations.csv` | Destinations | `DEST_DOCS` in `lib/mach_subsystem.py` and `lib/mach_note.py` |
| `templates.csv` | Templates | the generic `TEMPLATES` list in `lib/mach_sheets_gen.py` |
| `subsystem-units.csv` | Subsystem units | `config/subsystem.example.toml` (a generic example manifest, id `demo`) |

`mach sheets refresh mach` rewrites those CSVs, `index.csv` (static columns), `sheets.toml` and `docs/COMMANDS-TABLE.md`; then
`mach sheets build docs/sheets` (or `refresh mach --build`) updates the workbook. `refresh mach --check` compares without writing and exits 1 on
drift: the tests run it, so adding a command, flag or function without refreshing fails the suite. Every source is in the repo, so a
clean clone passes the same check. A command's status comes from `# mach-status:` (`working`,
`preview-only`, `stub`, optionally `sub=value`), and every flag in a usage line needs a meaning (a test enforces it).
