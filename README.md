# mach

`mach` is a small command-line tool that keeps a multi-computer, multi-AI-tool work system healthy and sends work down the right path.
The name is the German imperative of *machen* ("do/make": *Mach das!* means "Do it!"); the related noun *Macht* means power.

It has two halves:

- **Upkeep:** health checks, inventories, document indexes, explicit CLI names, service lists, MCP and AI-rule wiring, lesson review and
  plan archiving. Anything that changes state shows a preview first and acts only with `--apply`.
- **Work gateway:** one-line tasks, prompts for a named tool, quick notes, sourced research, prompt documents and multi-step flows.
  Every piece of work becomes a *run* with a record and stops at an approval gate before anything leaves the machine.

`mach` is written for the machine-flows setup (a Syncthing-synced folder shared by a Mac and one or more Linux laptops; `~/machine-flows`
is the default root), but it works with no config file and the pieces are plain bash 3.2 plus python 3.9 (standard library only).

## Install

```bash
git clone https://github.com/peers8862/mach ~/machine-flows/mach     # or copy the folder
bash ~/machine-flows/mach/install.sh                 # preview
bash ~/machine-flows/mach/install.sh --apply         # links ~/.local/bin/mach
mach --version
```

The link lives outside the synced folder. `--uninstall` removes it again. `MACH_BIN_DIR` changes the target folder.

## Configuration

Copy `config/config.example.toml` to `~/machine-flows/service-settings/mach/config.toml` and edit it (every key is documented in the
file; none is required). Machine names are yours to choose, mach has none built in:

```toml
[machines]
names = ["linux-box", "mac-laptop"]   # valid values of `machine:` in prompt documents, besides `any`
mac = "mac-laptop"                    # the macOS machine that delivers Agenda/Drafts notes
collector = "linux-box"               # the machine that runs `mach docs collect` (single writer)
[machines.match]                      # short hostname prefix (lower case) -> machine name
mac-laptop = "mac-laptop"
```

Without `[machines]` the machine name is the short hostname. Other keys added in 1.3.0: `[docs] macstat_paths`, `macstat_cron_pattern`
and `[drafts] hub_name`, `hub_group_uuid` (the Drafts hub builder, `tools/build-drafts-hub.py --name NAME`). Per-host overrides:
`config/hosts/*.example.toml`.

## Quick start

```bash
mach help                         # every command
mach doctor                       # read-only health checks (exit 0 ok, 1 warnings, 2 failure)
mach note "call the plumber"      # capture to the inbox (or agenda/drafts/<name>)
mach ask claude "why is the sky blue" --dry-run     # shows the exact command, runs nothing
mach do "tidy the headings in plan 04"              # route, confirm, run, record
mach run brief.md --dry-run       # validate and plan a prompt document
mach flow list                    # morning, research-to-plan, issue-to-pr
mach status                       # recent runs
```

## Commands

| Command | What it does | Status in v1 |
| --- | --- | --- |
| `doctor` | Health checks: Syncthing, services, CLI names, Grok Bot daemon, disk, memory, hygiene, caps | working |
| `inventory` | Regenerate `inventory/<host>/`, show the diff, write with `--apply` | working |
| `docs` | Update the docs-index CSVs (`collect`), rebuild the workbook only on request (`build`) | working |
| `names` | Check explicit CLI names; `--fix --apply` removes bare `agent` links | working |
| `services` | Compare live services/jobs with the 75/76 index files | working; `--update` prints a patch only |
| `mcp` | Render or apply the MCP manifest through `mcp-apply.sh` | render working; apply passes through to a stub |
| `ai` | Preview/apply wiring of shared rules and skills per tool | working (safe writes only) |
| `memory` | Review lessons; `collect` and `promote` | `review` working; `collect`, `promote` preview-only |
| `plans` | List plans with open boxes; archive a finished plan | working |
| `onboard` | New-machine checklist, link `mach`, previews | working |
| `sheets` | Sheet sets: `lint`, `build` (CSVs to a generated xlsx), `new`, `refresh mach` | working |
| `do`, `ask`, `research` | Route/ask/answer headless, read-only by default | working |
| `note` | Quick capture with destinations and an outbox | working |
| `subsystem`, `<subsystem>` | Manage unit manifests and dispatch to roles | working |
| `run`, `flow` | Prompt documents and recipes with gates | working |
| `status`, `queue`, `approve`, `reject` | Track, approve, cancel runs | working |

Full reference: [docs/COMMANDS.md](docs/COMMANDS.md). The complete guide (design rules, config, run records, templates, flows, safety model,
roadmap): [docs/GUIDE.md](docs/GUIDE.md). Decisions made while building v1: [docs/DECISIONS.md](docs/DECISIONS.md).

## Sheet sets (tracking any project)

A **sheet set** is a folder with a master `index.csv`, the CSV files it lists (the source of truth) and one generated workbook. Edit the
CSVs, never the workbook; `mach sheets build` regenerates it. No install needed (the xlsx is written with the standard library).

```bash
mach sheets new ~/making/myproject/tracking --apply   # index.csv (header only) + README.md
# add rows to index.csv (id, file, sheet_name, title, ...) and your CSVs, then:
mach sheets lint ~/making/myproject/tracking          # every CSV indexed, rows/updated right, Excel-safe, workbook current
mach sheets build ~/making/myproject/tracking         # fixes rows/updated in index.csv, writes tracking.xlsx (Index sheet first)
```

`docs/sheets/` is mach's own set, generated from the code and the `# mach-*` headers of `libexec/` (commands, flags, functions, config
keys, destinations, templates, subsystem units): `mach sheets refresh mach`, then `mach sheets build docs/sheets` (or `refresh mach
--build`). Templates and subsystem units come from generic examples in the repo (`config/subsystem.example.toml`). A test fails when the committed CSVs drift from the code. Table view: [docs/COMMANDS-TABLE.md](docs/COMMANDS-TABLE.md).

## Safety

No sudo. Secrets are never printed. Subsystem prompt commands send immediately to their configured destination; other tools run read-only unless you pass `--write`. Pull requests and
Linear changes are never executed by `mach`: they stop at a gate and become a ready-to-run command or draft.

## Tests

```bash
bash tests/run.sh          # bash tests with mock tools in a sandbox + python unittest
```

Tests never call a real AI tool or the network, and they never read anything outside the repository: templates and the sample
subsystem live in `tests/fixtures/`, so a clean clone of this repository passes `bash tests/run.sh` on its own.

## License

MIT, see [LICENSE](LICENSE).
