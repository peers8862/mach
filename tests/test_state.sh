#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# services, ai apply, memory, plans: fixtures under the sandbox only.
TEST_NAME=state
. "$(dirname "$0")/lib.sh"
new_sandbox
MF="$MACH_MF_ROOT"

# ============================================================ services
INV="$MF/inventory/linux-box"; mkdir -p "$INV" "$HOME/.config/systemd/user" "$HOME/.config/autostart"
cat > "$INV/75-custom-startup-services.md" <<'EOF'
# linux-box: custom login and boot services

| Name | Type | File path | When it starts | What it runs | Who created it, when | How to disable / roll back | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `syncthing.service` | systemd **user** unit | `~/.config/systemd/user/syncthing.service` | at boot | syncthing serve | Grok Bot, 2026-10-07 | disable it | enabled, active (running) |
| Grok Bot at login | XDG autostart | `~/.config/autostart/grok-bot.desktop` | at login | grok-bot | Grok Bot | rm it | active |
| Ghost service | systemd **user** unit | `~/.config/systemd/user/ghost.service` | at boot | nothing | someone | n/a | enabled, active |
EOF
cat > "$INV/76-custom-scheduled-jobs.md" <<'EOF'
# linux-box: scheduled jobs

| Name | Mechanism | File or crontab line | Schedule | What it runs | Created by, when | Status | Rollback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mach memory review` | systemd user timer | planned | monthly | mach memory review | user | **planned** | none |
| old thing | cron | `0 2 * * 0 /x/old.sh` | weekly | old.sh | unknown | **removed 2026-10-08** | restore |
EOF
touch "$HOME/.config/systemd/user/syncthing.service" "$HOME/.config/autostart/grok-bot.desktop" "$HOME/.config/systemd/user/stray.timer"
cat > "$SANDBOX/bin/crontab" <<'EOF'
#!/usr/bin/env bash
[ "$1" = "-l" ] && cat "$SANDBOX_CRON" 2>/dev/null
exit 0
EOF
chmod +x "$SANDBOX/bin/crontab"; export SANDBOX_CRON="$SANDBOX/cron.txt"
printf '# comment\n0 6 * * * /home/x/bin/unlisted-job.sh >> /tmp/x.log\n' > "$SANDBOX_CRON"
run services show
assert_rc 0 "services show"
assert_contains "syncthing.service" "services show: lists 75 rows"
assert_contains "mach memory review" "services show: lists 76 rows"
run services
assert_rc 1 "services check finds problems"
assert_contains "OK    listed  systemd-user syncthing.service (active)" "listed unit is fine"
assert_contains "UNLISTED  systemd-user stray.timer" "unit not in the index"
assert_contains "UNLISTED  crontab line not in the index" "cron line not in the index"
assert_contains "MISSING  active row 'Ghost service'" "active row without a live unit"
assert_not_contains "planned" "planned rows are not 'missing'"
run services --update
assert_contains "proposed patch" "services --update prints a patch"
assert_contains "+ | \`stray.timer\`" "patch proposes a row"
assert_file_lacks "$INV/75-custom-startup-services.md" "stray.timer" "services --update never writes (v1)"
# fix the index and the live side -> clean
rm "$HOME/.config/systemd/user/stray.timer"; : > "$SANDBOX_CRON"
touch "$HOME/.config/systemd/user/ghost.service"
run services
assert_rc 0 "services check clean"
printf 'linux-box,x\n' > /dev/null
rm -f "$INV/76-custom-scheduled-jobs.md"
run services
assert_rc 1 "missing 76 file is a warning"
assert_contains "76-custom-scheduled-jobs.md is missing" "says which file"

# ============================================================ ai apply
AI="$MF/ai-authored"; mkdir -p "$AI/claude/machines" "$AI/skills/mf-hello" "$AI/skills/synced/skip"
printf '# Shared rules\n' > "$AI/claude/CLAUDE.md"
printf '# linux-box notes\n' > "$AI/claude/machines/linux-box.md"
printf '# Agents\n- be kind\n' > "$AI/AGENTS.md"
printf -- '---\nname: mf-hello\ndescription: hi\n---\nbody\n' > "$AI/skills/mf-hello/SKILL.md"
printf -- '---\nname: skip\n---\n' > "$AI/skills/synced/skip/SKILL.md"
run ai show
assert_rc 0 "ai show"
assert_contains "CREATE" "ai: missing items are creates"
assert_contains "~/.claude/CLAUDE.md" "ai: claude import stub"
assert_contains "~/.codex/AGENTS.md" "ai: codex generated file"
assert_contains "machine-flows/rules/machine-flows.mdc" "ai: cursor plugin rule"
assert_contains ".kiro/steering/AGENTS.md" "ai: kiro steering"
assert_contains "MANUAL" "ai: manual items are labelled"
assert_contains "User Rules" "ai: cursor account rules are manual"
assert_not_contains "synced" "ai: never touches skills/synced"
assert_no_file "$HOME/.claude/CLAUDE.md" "ai show writes nothing"
run ai apply
assert_contains "preview only" "ai apply is a preview without --apply"
assert_no_file "$HOME/.codex/AGENTS.md" "ai apply w/o --apply writes nothing"
# a hand-written ~/.claude/CLAUDE.md must never be overwritten
mkdir -p "$HOME/.claude"; printf 'my own long instructions\nline 2\nline 3\nline 4\n' > "$HOME/.claude/CLAUDE.md"
run ai apply --apply
assert_rc 0 "ai apply --apply"
assert_file_has "$HOME/.claude/CLAUDE.md" "my own long instructions" "ai: real content is kept"
assert_contains "has real content" "ai: says why it did not touch it"
assert_file_has "$HOME/.claude/CLAUDE.machine.md" "@~/machine-flows/ai-authored/claude/machines/linux-box.md" "ai: machine import stub created"
assert_file_has "$HOME/.codex/AGENTS.md" "generated by mach ai apply" "ai: codex file is marked generated"
assert_file_has "$HOME/.codex/AGENTS.md" "be kind" "ai: codex file has the shared rules"
assert_file_has "$HOME/.codex/AGENTS.md" "linux-box notes" "ai: codex file has the machine file"
assert_file_has "$HOME/.kiro/steering/AGENTS.md" "generated by mach ai apply" "ai: kiro steering"
assert_file_has "$HOME/.cursor/plugins/local/machine-flows/rules/machine-flows.mdc" "alwaysApply: true" "ai: cursor rule"
assert_file_has "$HOME/.cursor/plugins/local/machine-flows/.cursor-plugin/plugin.json" '"name": "machine-flows"' "ai: cursor manifest"
[ -L "$HOME/.claude/skills/mf-hello" ] && pass || flunk "ai: claude skill link"
[ -L "$HOME/.agents/skills/mf-hello" ] && pass || flunk "ai: codex/cursor skill link"
[ -d "$HOME/.kiro/skills/mf-hello" ] && [ ! -L "$HOME/.kiro/skills/mf-hello" ] && pass || flunk "ai: kiro gets a copy, not a link"
assert_file "$HOME/.kiro/skills/mf-hello/.mach-copy" "ai: copy marker"
assert_no_file "$HOME/.claude/skills/skip" "ai: skills/synced is not wired"
assert_eq "0" "$(find "$MF" -type l | wc -l | tr -d ' ')" "ai: no symlinks inside machine-flows"
assert_contains "rollback: bash" "ai: rollback line"
run ai apply
assert_contains "nothing to write" "ai: idempotent"
# refresh a generated file when the source changes; never touch a hand-edited one
printf '# Agents\n- be kind\n- be brief\n' > "$AI/AGENTS.md"
run ai show --tool codex
assert_contains "REFRESH" "ai: changed source means refresh"
run ai apply rules --tool codex --apply
assert_file_has "$HOME/.codex/AGENTS.md" "be brief" "ai: generated file refreshed"
printf 'hand edited codex rules\n' > "$HOME/.codex/AGENTS.md"
run ai apply rules --tool codex --apply
assert_file_has "$HOME/.codex/AGENTS.md" "hand edited codex rules" "ai: hand-edited file is not overwritten"
assert_contains "DIFFERS" "ai: reported as differs"
# skills in the shared folder: refresh the kiro copy only if mach made it
printf 'changed\n' >> "$AI/skills/mf-hello/SKILL.md"
run ai show skills --tool kiro
assert_contains "REFRESH" "ai: kiro copy refresh"
rm -f "$AI/AGENTS.md"
run ai show rules --tool cursor-agent
assert_contains "BLOCKED" "ai: missing AGENTS.md blocks generated rules"
run ai show --tool grokcli-agent
assert_contains "MANUAL" "ai: grokcli-agent is manual"
run ai show --tool nope
assert_rc 2 "ai: unknown tool"

# ============================================================ memory
LS="$MF/service-memories/lessons"
run memory review
assert_rc 0 "memory review with no lessons folder"
assert_contains "no lessons folder yet" "memory: graceful when missing"
mkdir -p "$MF/files/Lessons"; printf '# idx\nl1\nl2\n' > "$MF/files/Lessons/INDEX.md"
run memory review
assert_contains "legacy knowledge base" "memory: notes the legacy files/Lessons"
mkdir -p "$LS/cli" "$LS/sync"
lesson() { # lesson <path> <id> <title> <status> <review_by> <confidence> [confirmations]
  cat > "$1" <<EOF
---
id: $2
title: $3
date: 2026-07-01
source: test
scope:
  tools: [all]
  machines: [all]
confidence: $6
review_by: $5
status: $4
confirmations: ${7:-0}
---
**Lesson:** something.
EOF
}
lesson "$LS/cli/2026-07-01-bare-agent.md" L-1 "Installers recreate a bare agent command" active 2027-01-01 high 4
lesson "$LS/cli/2026-07-02-bare-agent-again.md" L-2 "Installers recreate a bare agent command again" active 2027-01-01 medium
lesson "$LS/sync/2026-07-03-use-links.md" L-3 "Use symlinks for skills" active 2027-01-01 medium
lesson "$LS/sync/2026-07-04-avoid-links.md" L-4 "Avoid symlinks for skills" active 2027-01-01 medium
lesson "$LS/sync/2026-01-01-stale-one.md" L-5 "An old tip about thunderbolt docks" active 2026-02-01 low
lesson "$LS/sync/2026-01-02-superseded-one.md" L-6 "Something replaced long ago" superseded 2027-01-01 low
lesson "$LS/cli/2026-07-05-proposed.md" L-7 "Brand new idea about tmux" proposed 2027-01-01 low
printf -- '---\nid: L-8\ntitle: Missing fields\n---\nx\n' > "$LS/cli/2026-07-06-missing.md"
cat > "$LS/INDEX.md" <<'EOF'
# Lessons index
- [cli] Installers recreate bare agent → cli/2026-07-01-bare-agent.md
- [sync] Old tip → sync/2026-01-01-stale-one.md
- [sync] Replaced → sync/2026-01-02-superseded-one.md
- [cli] Gone → cli/2026-01-01-does-not-exist.md
EOF
run memory review
assert_rc 1 "memory review has warnings"
assert_contains "duplicate candidate" "memory: duplicates"
assert_contains "bare-agent" "memory: names the duplicate pair"
assert_contains "contradiction candidate" "memory: contradiction candidates"
assert_contains "stale: sync/2026-01-01-stale-one.md" "memory: stale"
assert_contains "missing field(s): date" "memory: missing frontmatter fields"
assert_contains "not in INDEX.md: cli/2026-07-02-bare-agent-again.md" "memory: index drift (missing)"
assert_contains "points to a missing file: cli/2026-01-01-does-not-exist.md" "memory: index drift (dangling)"
assert_contains "promotion candidate: cli/2026-07-01-bare-agent.md" "memory: promotion candidate"
assert_contains "proposed backlog: 1" "memory: proposed backlog"
assert_contains "proposed archives" "memory: lists proposed archives"
assert_contains "superseded-one.md" "memory: superseded lesson proposed for archive"
assert_file "$LS/sync/2026-01-02-superseded-one.md" "memory: review alone moves nothing"
run memory review --save
assert_file "$LS/reviews/2026-10.md" "memory: --save writes lessons/reviews/YYYY-MM.md"
assert_file_has "$LS/reviews/README.md" "mach memory review --save" "memory: --save creates the reviews README"
assert_file_has "$LS/reviews/README.md" "proposals only" "memory: README says proposals only"
assert_no_file "$MACH_STAGING/mach/reports/memory-review-2026-10-08.md" "memory: old staging report path is gone"
echo "keep me" > "$LS/reviews/README.md"
run memory review --save
assert_file "$LS/reviews/2026-10-2.md" "memory: second --save in a month gets a -2 suffix"
assert_file_has "$LS/reviews/2026-10.md" "mach memory review" "memory: first review file not clobbered"
assert_file_has "$LS/reviews/README.md" "keep me" "memory: existing reviews README not rewritten"
MACH_REVIEWS_DIR="$SANDBOX/custom-reviews" "$MACH" memory review --save >/dev/null 2>&1
assert_file "$SANDBOX/custom-reviews/2026-10.md" "memory: MACH_REVIEWS_DIR overrides the folder"
assert_file "$SANDBOX/custom-reviews/README.md" "memory: override folder gets a README too"
run_split --json memory review
assert_json "memory review --json"
run memory review --apply
assert_no_file "$LS/sync/2026-01-02-superseded-one.md" "memory --apply moves the archive"
assert_file "$LS/archived/sync/2026-01-02-superseded-one.md" "memory: file is in archived/"
assert_file_has "$LS/archived/sync/2026-01-02-superseded-one.md" "status: archived" "memory: status set"
assert_file_has "$LS/archived/sync/2026-01-02-superseded-one.md" "archived: 2026-10-08" "memory: archived date"
assert_file_lacks "$LS/INDEX.md" "superseded-one" "memory: INDEX line removed"
assert_file_has "$LS/archived/INDEX.md" "Something replaced long ago" "memory: archived index updated"
assert_file "$LS/archived/sync/2026-01-01-stale-one.md" "memory: low-confidence lesson 90+ days past review_by is archived too"
assert_contains "rollback: bash" "memory: rollback line"
assert_contains "rollback: bash ~/" "memory: rollback hint starts with an unescaped ~/"
assert_not_contains '\~' "memory: rollback hint has no escaped tilde"
BK=$(ls -d "$MACH_STAGING"/backups/*-mach-memory | head -n 1)
bash "$BK/rollback.sh"
assert_file "$LS/sync/2026-01-02-superseded-one.md" "memory: rollback restores the lesson"
assert_no_file "$LS/archived/sync/2026-01-02-superseded-one.md" "memory: rollback removes the archived copy"
# collect / promote are preview-only
BEFORE=$(find "$MF" -type f | wc -l | tr -d ' ')
run memory collect
assert_rc 0 "memory collect"
assert_contains "PREVIEW-ONLY" "memory collect: labelled"
run memory promote
assert_rc 0 "memory promote"
assert_contains "PREVIEW-ONLY" "memory promote: labelled"
assert_contains "promotion candidate" "memory promote: lists candidates"
assert_eq "$BEFORE" "$(find "$MF" -type f | wc -l | tr -d ' ')" "collect/promote write nothing"

# ============================================================ plans
P="$MF/plans"; mkdir -p "$P/archived"
cat > "$P/00-master.md" <<'EOF'
# 00: Master

Status: **active**.

- [x] done

## Change log
### 2026-10-07 01:00 EDT (linux-box): created
- first
EOF
cat > "$P/02-finished.md" <<'EOF'
# 02: Finished

Status: **active (waiting for the user)**.

- [x] a
- [x] b
EOF
cat > "$P/03-open.md" <<'EOF'
# 03: Open

Status: **active**.

- [x] a
- [ ] b
EOF
cat > "$P/README.md" <<'EOF'
# plans/

| # | File | Topic | State |
| --- | --- | --- | --- |
| 00 | `00-master.md` | Master | active (never archived) |
| 02 | `02-finished.md` | Finished thing | active |
| 03 | `03-open.md` | Open thing | active |
EOF
printf 'See ~/machine-flows/plans/02-finished.md and also plans/02-finished.md. Link: [x](plans/archived/02-finished.md)\n' > "$MF/ai-authored/ref.md"
printf 'sibling mention 02-finished.md here\n' > "$P/03-open.md.note"
run plans list
assert_rc 0 "plans list"
assert_contains "02  02-finished.md" "plans list: row"
assert_contains "0/2" "plans list: counts for a finished plan"
assert_contains "1/2" "plans list: counts for an open plan"
assert_contains "archive candidate" "plans list: marks the finished plan"
run --json plans list
assert_json "plans list --json"
run plans archive 00
assert_rc 2 "plan 00 is never archived"
assert_contains "never archived" "plans: says why"
run plans archive 03
assert_rc 2 "open boxes block archiving"
assert_contains "open box" "plans: names the problem"
run plans archive 99
assert_rc 2 "unknown plan"
BEFORE=$(cksum "$P"/*.md | cksum)
run plans archive 02
assert_rc 0 "plans archive preview"
assert_contains "Status: **done 2026-10-08, archived**" "plans: status line step"
assert_contains "plans/02-finished.md -> plans/archived/02-finished.md" "plans: reference fixes"
assert_contains "ai-authored/ref.md" "plans: names the file with a reference"
assert_contains "archived plan 02 (finished)" "plans: change-log line"
assert_contains "mach docs --apply" "plans: docs index step is printed, not run"
assert_contains "preview only" "plans: preview"
assert_eq "$BEFORE" "$(cksum "$P"/*.md | cksum)" "plans: preview changes nothing"
assert_file "$P/02-finished.md" "plans: not moved by a preview"
run plans archive 02 --apply
assert_rc 0 "plans archive --apply"
assert_no_file "$P/02-finished.md" "plans: moved out of plans/"
assert_file "$P/archived/02-finished.md" "plans: moved into archived/"
assert_file_has "$P/archived/02-finished.md" "Status: **done 2026-10-08, archived**" "plans: status line set"
assert_file_has "$P/archived/02-finished.md" "Follow-ups:" "plans: follow-up line"
assert_file_has "$MF/ai-authored/ref.md" "~/machine-flows/plans/archived/02-finished.md and also plans/archived/02-finished.md" "plans: references repointed"
assert_file_has "$P/00-master.md" "archived plan 02 (finished)" "plans: plan 00 change log"
assert_file_has "$P/README.md" "| 02 | \`archived/02-finished.md\` | Finished thing | done 2026-10-08, archived |" "plans: register row"
assert_contains "rollback: bash" "plans: rollback line"
BK=$(ls -d "$MACH_STAGING"/backups/*-mach-plans | head -n 1)
bash "$BK/rollback.sh"
assert_file "$P/02-finished.md" "plans: rollback restores the plan"
assert_no_file "$P/archived/02-finished.md" "plans: rollback removes the archived copy"
assert_file_lacks "$P/00-master.md" "archived plan 02" "plans: rollback restores plan 00"
run plans archive 03 --force
assert_contains "[--force]" "plans: --force is explicit"

# ============================================================ 75 file with a second (3-column) table
INV2="$MF/inventory/mac-laptop"; mkdir -p "$INV2"
cat > "$INV2/75-custom-startup-services.md" <<'EOF'
# mac-laptop: custom login and boot services

| Name | Type | File path | When it starts | What it runs | Who created it, when | How to disable / roll back | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Sync agent | LaunchAgent | `~/Library/LaunchAgents/com.x.sync.plist` | at login | `sync --dir {home}/a\|b` | Claude, 2026-10-07 | `launchctl bootout gui/$UID/com.x.sync` | active |
| Pipe in code | LaunchAgent | `~/Library/LaunchAgents/com.x.pipe.plist` | at login | `a | b` | user | rm it | active |

Related items that are not services:

| Name | What it is | Status |
| --- | --- | --- |
| Helper (`helper.mjs`, 127.0.0.1:17342) | On-demand daemon | **not running** |
| `~/.config/example-agents/` | env and scripts | run on demand |
EOF
cat > "$INV2/76-custom-scheduled-jobs.md" <<'EOF'
# mac-laptop: scheduled jobs

| Name | Mechanism | File or crontab line | Schedule | What it runs | Created by, when | Status | Rollback |
| --- | --- | --- | --- | --- | --- | --- | --- |
| none yet | n/a | n/a | n/a | n/a | n/a | **planned** | none |
EOF
export MACH_HOST=mac-laptop
run doctor
assert_not_contains "malformed" "doctor: two-table 75 file has no malformed rows"
assert_contains "2 row(s)" "doctor: only the main table's 2 rows counted"
assert_contains "1 other table(s) ignored" "doctor: other table reported, not parsed"
run services show
assert_contains "Sync agent" "services show: main table row listed"
assert_contains "other table, not parsed as services: Name | What it is | Status" "services show: lists the other table separately"
assert_not_contains "Helper (" "services show: other table rows are not services"
export MACH_HOST=linux-box

finish
