# Decisions made while building mach v1

Recorded 2026-10-08 during the autonomous build (no questions were asked). Format: decision, then why.

## Layout and portability

1. **Folder instead of `scripts/mach`.** The spec's `scripts/mach` + `scripts/mach.d/` became a dedicated repo folder: `bin/mach`,
   `libexec/mach-<cmd>`, `lib/`, `flows/`. Link target is `~/.local/bin/mach -> ~/machine-flows/mach/bin/mach`. *Why:* the user chose a
   separate git repo after the spec was written.
2. **Most logic in python, bash only where it fits.** `bin/mach`, `inventory`, `docs`, `names`, `mcp`, `onboard` and `install.sh` are
   bash 3.2 (they mostly call other programs); everything with parsing, JSON, HTTP or state is python3 stdlib. *Why:* bash 3.2 has no
   associative arrays, empty arrays break under `set -u`, and one parser for TOML/frontmatter beats two.
3. **`lib/minitoml.py` is used only when `tomllib` is missing** (python < 3.11, e.g. the Mac's 3.9). A unit test checks it parses the example
   configs to the same data as `tomllib`.
4. **Help comes from headers.** Each `libexec/mach-<cmd>` has `# mach-summary:`, `# mach-group:`, `# mach-usage:` and `# mach-help:` lines;
   `bin/mach` builds `mach help`, `mach <cmd> --help` and `docs/COMMANDS.md` (`mach help --markdown`) from them. A test fails if
   `docs/COMMANDS.md` is stale. Helper scripts in `libexec/` have a dot in the name (`mach-docs-collect.py`) and are not commands.
5. **Global `--host H` exports `MACH_TARGET_HOST`**, not `MACH_HOST`. `MACH_HOST` is the machine's identity (tests set it); the target is
   what the user asks about. Only `inventory` uses it, and it refuses any host but the current one.
6. **`MACH_OS`** (`darwin`|`linux`) overrides OS detection so tests can exercise macOS branches on Linux. Never needed in normal use.
7. **Test scratch lives in `<repo>/.tmp/` (gitignored), not `/tmp`** (the user's rule 13) and not in the real staging area. Suggest adding
   `/mach/.tmp` to `.stglobalignore` (it is the user's file; not edited). `mach doctor`'s hygiene walk skips this folder.
8. **Python 3.9 / bash 3.2 compliance is linted, not run.** This machine has python 3.11 and bash 5; `tests/test_lint.sh` greps bash for 4+
   constructs and GNU-only flags and parses every python file with `ast.parse(feature_version=(3, 9))`. Not yet run on the Mac.

## Config

9. **`MACH_CONFIG_DIR`** replaces `~/machine-flows/service-settings/mach` (it holds `config.toml`, `hosts/<host>.toml`) **and** `local.toml`
   (otherwise `~/.config/mach/local.toml`). Env keys: `MACH_NOTE_DEFAULT`, `MACH_DEFAULT_TOOL`, `MACH_PEER_SSH`, `MACH_RETENTION_DAYS`.
10. **A broken config layer is skipped with a warning**, the other layers still load (a typo must not make `mach doctor` unusable).
11. **Routes:** `[routes.project.<id>] path/tool/machine`; the first project whose path contains the working path wins. A project id may also
    be resolved from `service-memories/project-map.tsv` (first column id, first path-like column).

## Work gateway

12. **Headless flags** (checked with each tool's `--help`, 2026-10-08): `claude -p <prompt> --permission-mode plan` (write:
    `acceptEdits`); `codex exec --sandbox read-only --skip-git-repo-check <prompt>` (write: `workspace-write`);
    `cursor-agent -p --output-format text --trust --mode ask <prompt>` (write: drop `--mode ask`); `kiro-cli chat --no-interactive
    --trust-tools= <prompt>` (write: `--trust-tools=fs_read,fs_write`). **`grokcli-agent -p <prompt>` is a documented best guess**: the grok
    CLI exists only on the Mac, so its flags could not be checked and it has no known read-only switch; the dry-run output says so.
    Overridable per tool with `[tools.<name>] command / read_args / write_args`.
13. **`do` is read-only too** (spec only said `ask`). The route preview shows `permission read-only`; `--write` or `routes.permission = "write"`
    changes it. *Why:* a one-liner routed automatically should not edit files unless asked.
14. **`mach` writes output files itself** (the tool's stdout), only inside machine-flows, the run folder or the working path, never overwriting
    (`-2` suffix). `YYYY-MM-DD` and `slug` in `output:` are substituted (the shipped templates use them literally).
15. **Approval semantics.** `before-run` stops before executing. `before-apply` runs the tool read-only and holds the output; approval writes
    the file. Outward outputs (`pr`, `linear-comment`) always gate, even with `approval: none`, and after approval only a `handoff-*.md` is
    written. `mach approve` on a queued/other-state run is an error; `reject` also cancels queued runs.
16. **`gate:` inside a step with an action pauses after that step**, a step with only `gate:` is a pure gate. Gate steps get their own step
    number, so `approve --step N` uses the numbers shown in the run's steps table.
17. **Flows never edit code or post.** `issue-to-pr` v1 reads the issue, prepares branch/worktree/tmux commands, produces an implementation
    *plan* (read-only) and hands off the tests and PR; `research-to-plan` hands off registration. This follows "outward steps are NEVER executed".
18. **`machine:` other than this machine -> queued record, nothing executed** (no SSH yet). `machine: any` runs here interactively, and means the
    background machine (`[queue] background_machine`, default the machine you run on) for `--queue` and `--inbox`.
19. **Templates validate as written** (all three, in `--dry-run`), no template edits were needed. One nuance: `flow-request.md` ships
    `input: ""`; an empty required `input` is a warning for `--dry-run` and an error for a real run.
20. **Inbox "already run"** is decided by a run record whose `source:` equals the document's path relative to machine-flows (cancelled runs
    do not count, so a rejected document can be run again).
21. **`ask grokbot`** writes `prompt-for-grokbot.md` in a queued run folder; `mach reject <id> "pasted"` clears it. Nothing is automated.
22. **`--bg`** re-invokes `mach do ... --yes` inside `tmux new-session -d -s mach-<slug>`; `MACH_TMUX` overrides the tmux name (tests).

## Notes

23. **Agenda MCP:** JSON-RPC over HTTP POST to `mcp_url` with `initialize`, `notifications/initialized` and `tools/call create_note` with
    arguments `title`, `text` (tags appended as `#tag`), `project`, `date`. The tool's argument names are a best guess from the spec; only
    a fake server was tested. If Agenda rejects them the URL-scheme fallback runs (exit 1, never silent).
24. **A fallback exits 1 even when the second method worked** (spec: "A fallback exits with code 1").
25. **`--file PATH`** was added to `note` so flows can capture a file without shell pipes (`morning` uses it).
26. **`note flush`** parses the outbox file's frontmatter (`dest`, `type`, `title`, `tags`, `project`, `date`, `flag`, `open`) and re-uses the
    same delivery code; failed items stay in the outbox.

## Upkeep

27. **doctor** never writes. Peer disconnection duration cannot be known without state, so a disconnected peer is a WARN without the
    10-minute rule. Syncthing's monitor+child processes count as one instance (parent pid is a syncthing). Version parity reads
    `inventory/<host>/70-services-network.md` (`syncthing vX.Y.Z`); if only one host has it the check is INFO. The hygiene walk prunes `.git`,
    `node_modules`, `.stversions`, `__pycache__`, `.venv`, mach's own `.tmp`, and stops at a time budget (`doctor.scan_budget_s`).
28. **`inventory`** runs the generator into a temp folder and compares file by file. It never copies the generated `README.md`, the hand-kept
    `75`/`76` files or `docs-index.csv`. Linux runs the full generator (as before); macOS runs light (`SKIP_SIZES=1 SKIP_NET=1
    SKIP_BREW_DOCTOR=1`). A light run replaces the size tables with a "skipped" note, hence `--light` / `--full`.
29. **`docs collect`** uses a *copy* of the user's `collect.py` (`libexec/mach-docs-collect.py`); the staging original is untouched. Changes:
    paths from env, output folder override, `--preview` (no state write, no backups), mach's own backup instead of the built-in one,
    python `os.lstat` instead of `stat -c` on macOS, prune of `.git`/`.tmp`/`__pycache__`/`node_modules`, rows for the mach checkout, and the
    router IP scrubbed from one hard-coded path string (the existing CSV row for it will show as one removed + one added row). The script's
    long hard-coded history rows were later moved out (decision 36).
    It runs on one machine only (`[machines] collector`, overridden by `MACH_DOCS_COLLECTOR`; default the machine you run on). `docs build` wraps `scripts/docs-index-build.py` in place (not copied) and
    needs `openpyxl`. `docs macstat` wraps a copy of `mac-stat.sh`.
30. **`mcp`** wraps `scripts/mcp-apply.sh` in place. Its `--apply` currently exits 3 ("documented stub"); `mach mcp apply --apply` reports
    that honestly (exit 1) instead of pretending. `cursor-agent` maps to the script's `cursor` target; `grokcli-agent` has none.
31. **`ai apply` safe-write rules.** Claude import stubs may carry an HTML comment header (the real ones do). Generated files (Codex
    `~/.codex/AGENTS.md`, Kiro steering, Cursor plugin rule) carry a `generated by mach ai apply` first line and are refreshed only while that
    line is present; anything else is "differs". Skills: symlinks from `~/.claude/skills` and `~/.agents/skills` into machine-flows (never
    inside it) and copies for Kiro (marker `.mach-copy` with a content hash). `ai-authored/skills/synced/` is never touched. Cursor account User
    Rules and the Grok Bot private skill are shown as manual. Until `ai-authored/AGENTS.md` exists, generated rules are "blocked".
32. **`memory review`** reads lessons with a tolerant frontmatter parser (one nested level, `scope.tools`). Archive proposals: lessons marked
    `superseded`/`archived` still in the live tree, and `low` confidence lessons 90+ days past `review_by`. Duplicate = title similarity >= 0.8
    or slug >= 0.85 (difflib); contradiction *candidate* = similar titles with opposite advice words and overlapping scope. `collect`,
    `promote` are preview-only; `migrate` (files/Lessons) is not built.
33. **`plans archive`** refuses plan 00 and plans with open boxes (`--force` overrides); `--apply` is taken as the user's OK. It repoints
    `plans/NN-name.md` -> `plans/archived/NN-name.md` (other mentions are listed for hand-checking), adds the plan 00 change-log entry, updates the
    register row in `plans/README.md`, and **prints** (does not run) `mach docs --apply`.
34. **`services`** matches by unit/file names found in the 75/76 tables (backticked names and `*.service|timer|desktop|plist`). Failed units are
    reported only if a unit file exists in `~/.config/systemd/user`. `--update` prints proposed rows only.
35. **`onboard --apply`** runs only `install.sh --apply`. The previews (inventory, names, ai apply, mcp render) can be skipped with
    `--skip-previews`.

36. **Personal docs history is data, not code.** The repo is going to a private GitHub repo, so `libexec/mach-docs-collect.py` keeps only
    the generic walk and the row logic. Everything user-specific (purposes per file, origin-machine lists, created-date overrides, backup names,
    Mac items, change-log dates, rows for files outside machine-flows) moved to `docs-history.local.py`, a plain Python module loaded with
    `importlib` from the first of `$MACH_DOCS_HISTORY`, `$MACH_CONFIG_DIR/`, `~/machine-flows/service-settings/mach/`, `<repo>/config/`. It is
    gitignored (`config/docs-history.local.py`, `config/*.local.*`); `config/docs-history.example.py` documents the format with fake entries.
    Rows are dicts (a few `@`-tokens and `{placeholders}` cover the cases that need the live file system); `dynamic_rows(ctx)` is the one
    function, for rows that depend on `mac-stat.tsv`. No history file = generic walk plus one INFO line on stderr. The refactor was checked by
    running the original and the new collector back to back in preview mode, with and without a `mac-stat.tsv`: the CSVs are byte-identical.
    Tests never need the local file (`tests/test_docs_history.sh` writes fake ones). The repo location is taken from the script's own path,
    not `MACH_HOME`, so a copied collector (tests) cannot pick up the real checkout's file.
37. **Outside programs are resolved through override variables, and tests can't reach the real ones.** A test on the real Mac removed the
    `open` mock to simulate "no opener", `/usr/bin/open` was found on `PATH`, and a real Drafts draft was created. Now `mc.cmd(name)` /
    `mc.ext_cmd(var, default)` resolve `open`, `drafts`, `osascript`, `tmux`, `launchctl`, `systemctl`, `crontab`, `ssh` and the five AI CLIs
    (`MACH_OPEN_CMD`, `MACH_DRAFTS_CMD`, `MACH_OSASCRIPT_CMD`, `MACH_TMUX`, `MACH_LAUNCHCTL_CMD`, `MACH_SYSTEMCTL_CMD`, `MACH_CRONTAB_CMD`,
    `MACH_SSH_CMD`, `MACH_CLAUDE_CMD`, `MACH_CODEX_CMD`, `MACH_CURSOR_AGENT_CMD`, `MACH_KIRO_CMD`, `MACH_GROKCLI_AGENT_CMD`); the Agenda MCP
    endpoint is `MACH_AGENDA_MCP_URL` > the destination's `mcp_url` > `127.0.0.1:16106`. Env beats config (the usual precedence), so a
    `tools.<tool>.command` config entry applies only when the variable is unset or empty. The test sandbox pins every variable to a path
    inside itself (a missing path means "not available") and points the MCP URL at a closed port. As a second layer, canary scripts named
    like the real programs sit on `PATH` behind the mocks and `finish()` fails a test if one ran; `tests/test_lint.sh` checks that
    `tests/lib.sh` and `CMD_VARS` list the same variables and that lib/libexec never run these programs by bare name.
38. **`mach doctor` ordering.** The symlink, secrets-guard and sync-conflict lists are sorted case-insensitively by path, so output is the same on
    ext4 and APFS (the walk order differs). Tests assert each name and the sorted order.
39. **Review files (1.0.1).** `memory review --save` writes `service-memories/lessons/reviews/YYYY-MM.md` (plan 09 section 7), not the
    old staging `reports/` folder. It never clobbers: a second save in the same month becomes `YYYY-MM-2.md`, then `-3` (chosen over a
    dated section so each file stays one report). The folder is created on demand with a short `README.md` (written only when the folder
    is new). Override: `[memory] reviews_dir` or `MACH_REVIEWS_DIR`. `scan()` already skips `reviews/`, so these are never read as lessons.
40. **Rollback hint (1.0.1).** `rollback: bash ~/…/rollback.sh` is printed with the `~` unquoted (`shell_path` in Python,
    `mach_shell_path` in bash); only the part after `~/` is quoted, and only when needed. The old `%q`/`shlex.quote` output escaped the
    tilde, so pasting it failed.
41. **75/76 parser (1.0.1).** Only the main services table is parsed: first header cell `Name`, a `Status*` column, 5+ columns (falls back
    to the file's first table if none matches). Other tables (e.g. a 3-column "Name | What it is | Status") are not rows;
    `doctor` and `services show` list them as ignored. Cells split on unescaped `|` outside backtick spans; `\|` becomes `|`.
42. **Lessons skeleton (1.0.2).** `mach memory init` creates the plan 09 skeleton instead of `review` doing it implicitly: review stays
    read-only (plus `--save`/`--apply`), and a missing folder or INDEX.md is INFO with the fix command. INDEX.md carries a "generated by mach"
    marker; only marked files are regenerated (`init --reindex`, `review --apply`), hand-edited ones are patched line by line. Topic order in
    the header follows plan 09 section 3 (sync, ai-tools, cli, ...), not alphabetical.

## Things noticed (for the user)

- The internal build brief was removed from the repository in 1.3.0 (it held personal context).
- `mach/.tmp/` is created by tests inside a synced folder; add `/mach/.tmp` to `.stglobalignore` if tests will be run on a machine while Syncthing is up.
- The first `mach docs` preview lists every new `mach/` file as an added row (purpose text "mach CLI ... file").
- The build session could only write inside `~/machine-flows/mach/`; see the build summary for what that affected.

## 2026-10-08 — Subsystem dispatcher (mach 1.1.0)

- The command `mach <subsystem> <unit> "prompt"` is the explicit authorization to send immediately. There is no second confirmation. Built-ins win when names collide; `lint` rejects the collision.
- Subsystem manifests are keyed TOML data adjacent to mach. Unit IDs are unique per subsystem. Unverified bindings remain marked `verified = false`; the user's own terms govern unit names.
- Grok Bot delivery uses one router routine. Secrets live only in an unsynced mode-600 local TOML file; curl receives them through a config on stdin. Missing or unsafe credentials create a paste-ready queued run and exit 1. Each successful 2xx POST records `done`, and the local run history enforces the daily cap.
- Setup drafts have a deterministic heading and `key: value` grammar and are ingested with `mach subsystem ... --from`; `mach run` rejects them with the right hint. Drafts drops files into inbox folders and does not call apps or URLs.

## 2026-10-08 — Sheet sets (mach 1.2.0)

- **Workbook writer is stdlib-only.** `scripts/docs-index-build.py` needs openpyxl (its header says one machine's python has it; on this machine
  `import openpyxl` fails, and the Mac is the same story). `mach sheets build` writes SpreadsheetML itself with `zipfile`: inline strings
  (no sharedStrings), one style sheet (bold filled header, wrapped body, right-aligned numbers), frozen first row, `autoFilter`, widths from
  the content (8-60), a hidden `_FilterDatabase` name per sheet. Fixed zip timestamps, entry order, attributes and compression level and no
  clock anywhere: the same CSVs give the same bytes with one zlib version. Staleness is therefore judged by content hashes, never by zip bytes.
  `docs build` is untouched. The XML is read back with `xml.etree` (own files only; a hardened parser would need a dependency).
- **`rows`** = records in the CSV after the header, blank lines ignored. **`updated`** = the date the CSV's *cells* last changed, as
  recorded by `build`: the workbook carries a build record (`docProps/custom.xml`, per CSV: sha256 of the parsed cells + the `updated`
  date). On `build`: record present and hash equal -> keep the recorded date; hash differs -> today (`MACH_NOW` in tests); no record (first
  build, or the workbook is missing) -> keep a valid date already in `index.csv`, else today. Line endings and quoting are not changes. *Why
  not mtime or git:* mtime changes on every checkout or Syncthing copy, and git is not always there; the hash makes lint reproducible in
  any clone. `lint` fails when a CSV changed after the last build (workbook stale) or `updated` disagrees with the build record.
- **`build` writes** (explicit action; backup + rollback of what it overwrites; `--dry-run` reports only; a no-op build writes nothing).
  `lint` and `build --dry-run` never write. `build` refuses a set with FAIL findings other than the stale-workbook ones it repairs.
- **Lint levels.** FAIL: index columns not exact, orphan/missing/duplicate files, duplicate ids, duplicate or illegal `sheet_name`
  (case-insensitive; `Index` and `History` are reserved), ragged records, empty header cell, control characters, cells over 32,767
  characters, wrong `rows`, bad `updated`, stale workbook. WARN: no workbook yet, duplicate column names, formula-like cells (`=`/`@`, or
  `+`/`-` before `(`, `=`, `@`; `--apply` and `-t` are fine), absolute `/home`, `/Users`, `/root` paths. The workbook stores every string
  as text, so formula-like cells cannot execute there; the warning is about opening the CSV directly.
- **Workbook name** = the folder name unless the optional `sheets.toml` says `workbook = "name"` (`docs/sheets` uses `mach`).
- **The mach set is generated from headers, not typed.** New optional headers in `libexec/mach-*`: `# mach-subcommands:` (the
  subcommand words), `# mach-status:` (`working`, `preview-only`, `stub`; `sub=value` overrides, e.g. `memory collect/promote` are
  preview-only and `mcp apply` is a stub), `# mach-writes:` (`yes`, `sub=no`), `# mach-half:` and `# mach-flag: --flag | meaning | default`.
  `bin/mach` ignores them. `writes` = `--apply` in the usage segment, or the header. Usage lines are split on top-level `|` into
  per-subcommand segments (`unit|role <id> --from D` shares its tail). Shared flags (`--apply`, `--json`, `--tool`, ...) live in one
  table, `COMMON_FLAGS` in `lib/mach_sheets_gen.py`; a test fails for any flag without a meaning.
- **Destination syntax lives next to the code** as `DEST_DOCS` tables in `lib/mach_subsystem.py` and `lib/mach_note.py`; `destinations.csv`
  is generated from them (and `KNOWN_TOOLS`). `functions.csv` takes the first docstring line, a trailing `# comment` on the `def` line, or
  the comment block above or just inside the function; a function with none has an empty purpose rather than an invented one.
- **Drift test.** `mach sheets refresh mach --check` regenerates in memory and compares with the committed files (CSVs, the static columns
  of `index.csv` plus row counts, `COMMANDS-TABLE.md`). `templates.csv` and `subsystem-units.csv` need `~/machine-flows/...` files outside
  the repo; when the source is missing the CSV is skipped by refresh and by the check. `rows`/`updated` in `index.csv` are owned by `build`.
- **No absolute home paths** in the generated CSVs or the workbook (a test unzips the xlsx and greps). `test_lint.sh` now greps with `-I`
  so the binary workbook is not scanned as text.
- **`refresh` does not build** unless `--build` is given, so the review of the CSV diff stays a separate step.

## 2026-10-08 — Public release (mach 1.3.0)

- **Machine names come from config, not code.** `[machines]` holds `names`, `mac`, `collector` and `[machines.match]`. `host()` reads only the
  shared and local layers for the match table (the host layer is chosen by the host name itself, so reading it would be circular). Bash
  asks the python helper (`lib/mach_common.py host|mac|collector|get KEY`) instead of duplicating the logic. With no config the host is the
  short hostname and the only known machine is this one.
- **Collector and background machine default to "this machine"**, so a single-machine setup needs no config. `MACH_DOCS_COLLECTOR` still wins.
  The collector script receives its two machine names through `MACH_DOCS_LINUX` / `MACH_DOCS_MAC` (set by `mach docs`), so it also works
  when copied elsewhere.
- **Tests are standalone.** Fixtures in `tests/fixtures/` replace the real templates; `test_lint.sh` fails when a test reaches outside the repo
  and when a tracked text file holds a personal path, email, IP or token. The `docs-history.local.py` and `config.toml` of a real
  installation stay outside the repository.

