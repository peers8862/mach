#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# The docs collector is generic; personal history comes from a separate data module. Nothing here needs the real
# config/docs-history.local.py (CI and clean clones do not have it): fake history files are written into the sandbox.
TEST_NAME=docs-history
. "$(dirname "$0")/lib.sh"
new_sandbox
COLLECT_REAL="$TEST_ROOT/libexec/mach-docs-collect.py"
# a copy of the collector in the sandbox: its <repo>/config/ lookup then finds nothing, whatever exists in the real checkout
mkdir -p "$SANDBOX/repo/libexec" "$SANDBOX/out"
cp "$COLLECT_REAL" "$SANDBOX/repo/libexec/mach-docs-collect.py"
COLLECT="$SANDBOX/repo/libexec/mach-docs-collect.py"
export MACH_STATE_DIR="$SANDBOX/state" MACH_DOCS_OUT="$SANDBOX/out"
export MACH_DOCS_MAC=mac-laptop
mkdir -p "$MACH_STATE_DIR" "$MACH_MF_ROOT/plans" "$MACH_MF_ROOT/inventory/linux-box" "$MACH_MF_ROOT/inventory/mac-laptop"
printf '# plan\n' > "$MACH_MF_ROOT/plans/01-example-plan.md"
printf '# other\n' > "$MACH_MF_ROOT/plans/02-other.md"

collect() { OUT=$(python3 -I "$COLLECT" --preview 2>"$SANDBOX/collect.err"); RC=$?; ERR=$(cat "$SANDBOX/collect.err"); }

# --- no history file anywhere: generic walk, exactly one INFO line, rc 0
collect
assert_rc 0 "collector works without a history module"
assert_eq "1" "$(printf '%s\n' "$ERR" | grep -c '^INFO')" "exactly one INFO line"
case "$ERR" in *"no docs-history.local.py found"*) pass ;; *) flunk "INFO text: $ERR" ;; esac
assert_file "$SANDBOX/out/linux-box/docs-index.csv" "linux-box csv written to MACH_DOCS_OUT"
assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "plans/01-example-plan.md" "walk lists the plan"
assert_file_lacks "$SANDBOX/out/linux-box/docs-index.csv" "Example plan purpose" "no history, no purposes"

# --- explicit history ($MACH_DOCS_HISTORY) is used, no INFO line
cat > "$SANDBOX/hist.py" <<'EOF'
PURPOSE = {"plans/01-example-plan.md": "Example plan purpose"}
ROWS = [dict(machine="linux-box", path="~/.config/example/app.conf", kind="config", area="example", scope="local",
             purpose="Fake history row", created_by="agent", created="2026-01-02 03:04", stat=False)]
EOF
MACH_DOCS_HISTORY="$SANDBOX/hist.py" collect
assert_rc 0 "collector with an explicit history file"
assert_eq "" "$ERR" "no INFO when a history file is found"
assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "Example plan purpose" "purpose from the history file"
assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "Fake history row" "extra row from the history file"
assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "2026-01-02T03:04:00-05:00" "literal time is New York wall-clock with offset"

# --- search order: $MACH_CONFIG_DIR beats service-settings and the repo config
printf 'PURPOSE = {"plans/02-other.md": "from config dir"}\n' > "$MACH_CONFIG_DIR/docs-history.local.py"
mkdir -p "$MACH_MF_ROOT/service-settings/mach" "$SANDBOX/repo/config"
printf 'PURPOSE = {"plans/02-other.md": "from service-settings"}\n' > "$MACH_MF_ROOT/service-settings/mach/docs-history.local.py"
printf 'PURPOSE = {"plans/02-other.md": "from repo config"}\n' > "$SANDBOX/repo/config/docs-history.local.py"
collect; assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "from config dir" "MACH_CONFIG_DIR is searched first (after the explicit path)"
rm "$MACH_CONFIG_DIR/docs-history.local.py"
collect; assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "from service-settings" "then service-settings/mach"
rm "$MACH_MF_ROOT/service-settings/mach/docs-history.local.py"
collect; assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "from repo config" "then <repo>/config"
# an explicit path that does not exist falls through to the next candidate
MACH_DOCS_HISTORY="$SANDBOX/nope.py" collect; assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "from repo config" "missing explicit path falls through"
rm -rf "$SANDBOX/repo/config"

# --- the shipped example file loads and runs
MACH_DOCS_HISTORY="$TEST_ROOT/config/docs-history.example.py" collect
assert_rc 0 "config/docs-history.example.py is a valid history module"
assert_file_has "$SANDBOX/out/linux-box/docs-index.csv" "Example app settings we changed" "example row appears"

# --- the collector itself holds no personal history (that is the point of the split)
if grep -qE 'Grok Bot|Distill|syncthing\.service|/var/lib/systemd/linger' "$COLLECT_REAL"; then flunk "personal history leaked back into libexec/mach-docs-collect.py"; else pass; fi

# --- mach docs (preview) shows the INFO line and never writes the live inventory
mkdir -p "$MACH_MF_ROOT/inventory/linux-box"
MACH_DOCS_COLLECT="$COLLECT" run docs
assert_rc 0 "mach docs preview"
assert_contains "INFO: no docs-history.local.py found" "mach docs shows the INFO line"
assert_no_file "$MACH_MF_ROOT/inventory/linux-box/docs-index.csv" "preview does not write the live CSV"
finish
