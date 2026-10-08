#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# mach note: inbox, stdin, tags, destination detection, --to/--, outbox fallback, dry-run, json, mac methods, flush.
TEST_NAME=note
. "$(dirname "$0")/lib.sh"
new_sandbox
INBOX="$MACH_MF_ROOT/files/inbox/notes/2026-10-08-linux-box.md"

# --- inbox is the built-in default
run note "first note about #things"
assert_rc 0 "inbox note"
assert_contains "noted" "inbox message"
assert_file "$INBOX" "inbox file is per day and host"
assert_file_has "$INBOX" "## 09:30 first note about #things" "entry heading uses time + title"
assert_file_has "$INBOX" "first note about #things" "entry text"

# --- title, tags (--tag repeatable, --tags csv), date
run note "second" -t "My title" --tag a --tag b --tags c,d --date 2026-10-09
assert_rc 0 "tags + title"
assert_file_has "$INBOX" "## 09:30 My title" "explicit title"
assert_file_has "$INBOX" "tags: a, b, c, d" "tags line"
assert_file_has "$INBOX" "date: 2026-10-09" "date line"

# --- stdin, and "-" means stdin
OUT=$(printf 'from a pipe\nsecond line\n' | "$MACH" note 2>&1); RC=$?
assert_rc 0 "stdin note"
assert_file_has "$INBOX" "from a pipe" "stdin text"
OUT=$(printf 'dash form' | "$MACH" note inbox - 2>&1); RC=$?
assert_rc 0 "stdin via -"
assert_file_has "$INBOX" "dash form" "dash form text"
OUT=$(printf '' | "$MACH" note 2>&1); RC=$?
assert_rc 2 "empty note is refused"

# --- title is the first line, max 60 chars
LONG="0123456789012345678901234567890123456789012345678901234567890123456789"
run note "$LONG"
assert_file_has "$INBOX" "## 09:30 012345678901234567890123456789012345678901234567890123456789" "title is cut at 60"

# --- destination detection: first word counts only when it is a destination name
run --json note --dry-run agenda "buy milk"
assert_eq "agenda" "$(json_get 'd["dest"]')" "agenda detected"
run --json note --dry-run "agendas are fun"
assert_eq "inbox" "$(json_get 'd["dest"]')" "similar word is just text"
run --json note --dry-run unknownword "text"
assert_eq "inbox" "$(json_get 'd["dest"]')" "unknown first word is text"
printf '[note.dest.ideas]\ntype = "file"\npath = "files/ideas.md"\n[note.dest.work]\ntype = "agenda"\nproject = "Example Project"\n' > "$MACH_CONFIG_DIR/config.toml"
run --json note --dry-run ideas "an idea"
assert_eq "ideas" "$(json_get 'd["dest"]')" "named destination detected"
run --json note --dry-run --to agenda -- "agenda for Monday"
assert_eq "agenda" "$(json_get 'd["dest"]')" "--to wins"
run --json note --dry-run --to inbox -- "agenda for Monday"
assert_eq "inbox" "$(json_get 'd["dest"]')" "--to inbox keeps 'agenda' in the text"
run note --to inbox -- "agenda for Monday"
assert_file_has "$INBOX" "agenda for Monday" "text starting with a destination name is kept whole"

# --- named file destination, and the guard that keeps it inside machine-flows
run note ideas "idea one" --tag x
assert_rc 0 "file destination"
assert_file_has "$MACH_MF_ROOT/files/ideas.md" "idea one" "file dest content"
printf '[note.dest.bad]\ntype = "file"\npath = "/etc/passwd-mach-test"\n' >> "$MACH_CONFIG_DIR/config.toml"
run note bad "nope"
assert_rc 2 "file destination outside machine-flows is refused"
assert_no_file /etc/passwd-mach-test "nothing written outside"

# --- dry-run writes nothing
BEFORE=$(find "$MACH_MF_ROOT" -type f | wc -l | tr -d ' ')
run note --dry-run "should not be written"
assert_rc 0 "dry-run"
assert_contains "dry-run" "dry-run label"
run note drafts --dry-run "x"
assert_rc 0 "dry-run drafts on linux"
AFTER=$(find "$MACH_MF_ROOT" -type f | wc -l | tr -d ' ')
assert_eq "$BEFORE" "$AFTER" "dry-run created no files"
MACH_DRY_RUN=1 run note "global dry run"
assert_file_lacks "$INBOX" "global dry run" "MACH_DRY_RUN is honoured"

# --- linux: agenda and drafts always go to the synced outbox, never silently, exit 1
run note agenda "call the plumber" --project Home
assert_rc 1 "agenda on linux falls back (exit 1)"
assert_contains "queued" "fallback is announced"
assert_contains "outbox/agenda" "names the outbox"
F=$(ls "$MACH_MF_ROOT"/files/inbox/outbox/agenda/*.md | head -n 1)
assert_file "$F" "agenda outbox file"
assert_file_has "$F" "call the plumber" "outbox keeps the text"
assert_file_has "$F" "project: Home" "outbox keeps the project"
run note drafts "idea for later" --flag --tag urgent
assert_rc 1 "drafts on linux falls back (exit 1)"
D=$(ls "$MACH_MF_ROOT"/files/inbox/outbox/drafts/*.md | head -n 1)
assert_file_has "$D" "flag: true" "outbox keeps flag"
run --json note drafts "json fallback"
assert_rc 1 "json fallback exit"
assert_json "note --json"
assert_eq "queued" "$(json_get 'd["status"]')" "json status"
assert_eq "outbox" "$(json_get 'd["method"]')" "json method"
run --json note "plain"
assert_rc 0 "json inbox"
assert_eq "file" "$(json_get 'd["method"]')" "json inbox method"
assert_contains "path" "json has a path"
# the queue and the outbox listing see the items
run queue
assert_contains "outbox (" "queue lists the outbox"
assert_contains "agenda" "queue shows agenda items"

# --- the local log has time/dest/method and never the note text
LOG="$MACH_LOCAL_STATE/notes.log"
assert_file "$LOG" "notes.log exists"
assert_file_has "$LOG" "drafts	outbox" "log has dest and method"
assert_file_lacks "$LOG" "call the plumber" "log never has note text"
assert_file_lacks "$LOG" "idea for later" "log never has note text (2)"

# --- macOS behaviour (simulated): MCP unreachable -> url fallback exits 1; drafts CLI works; cli missing -> url
export MACH_OS=darwin
run note agenda "mac agenda note" --project Inbox --tag t1
assert_rc 1 "mac agenda: MCP down, url fallback exits 1"
assert_contains "via url" "names the method used"
assert_contains "MCP not reachable" "says why"
OUT=$(mock_calls); assert_contains "agenda://x-callback-url/create-note?project-title=Inbox&title=mac%20agenda%20note&text=mac%20agenda%20note%0A%0A%23t1" "agenda url is encoded and tagged"
assert_contains "MOCK open -g" "stays in the background by default"
run note agenda "foreground" --open
OUT=$(mock_calls); assert_contains "MOCK open agenda://" "--open drops -g"
run note drafts "mac draft" --tag x --flag
assert_rc 0 "mac drafts via cli"
OUT=$(mock_calls); assert_contains "MOCK drafts create --tag mach --tag x --flagged # mac draft" "drafts CLI call"
rm -f "$SANDBOX/bin/drafts"
run note drafts "mac draft 2"
assert_rc 1 "drafts without the CLI uses the url (exit 1)"
OUT=$(mock_calls); assert_contains "MOCK open -g drafts://x-callback-url/create?text=" "drafts url"
rm -f "$SANDBOX/bin/open"
run note drafts "no open either"
assert_rc 1 "everything fails: outbox"
assert_contains "outbox/drafts" "falls to the outbox"

# --- flush (mac): preview first, --apply delivers and removes
make_mock open; make_mock drafts
N0=$(ls "$MACH_MF_ROOT"/files/inbox/outbox/drafts/ | wc -l | tr -d ' ')
run note flush
assert_rc 0 "flush preview"
assert_contains "would deliver" "flush preview text"
assert_contains "preview only" "flush says preview"
N1=$(ls "$MACH_MF_ROOT"/files/inbox/outbox/drafts/ | wc -l | tr -d ' ')
assert_eq "$N0" "$N1" "preview removes nothing"
run note flush --apply
assert_rc 0 "flush apply"
assert_contains "delivered" "flush delivers"
N2=$(ls "$MACH_MF_ROOT"/files/inbox/outbox/drafts/ 2>/dev/null | wc -l | tr -d ' ')
assert_eq "0" "$N2" "delivered files are removed"
export MACH_OS=linux
run note flush
assert_rc 1 "flush on linux is a warning"
assert_contains "macOS" "flush explains itself"

finish
