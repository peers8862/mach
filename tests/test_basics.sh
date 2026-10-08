#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# help for every command, unknown command, global options, host map, config precedence.
TEST_NAME=basics
. "$(dirname "$0")/lib.sh"
new_sandbox

# --- help for every command (names come from the libexec headers)
CMDS=""
for f in "$TEST_ROOT"/libexec/mach-*; do
  case "$f" in *.*) continue ;; esac
  CMDS="$CMDS ${f##*/mach-}"
done
N=0
for c in $CMDS; do
  N=$((N + 1))
  run "$c" --help
  assert_rc 0 "mach $c --help"
  assert_contains "Usage:" "mach $c --help has usage"
  run help "$c"
  assert_rc 0 "mach help $c"
done
if [ "$N" -ge 20 ]; then pass; else flunk "expected at least 20 commands, found $N"; fi

run help
assert_rc 0 "mach help"
for c in doctor inventory docs names services mcp ai memory plans onboard "do" ask note research run flow status queue approve reject; do
  assert_contains "  $c " "help lists $c"
done

run --help; assert_rc 0 "mach --help"
run --version; assert_rc 0 "--version"; assert_contains "mach $(cat "$TEST_ROOT/VERSION")" "version text"
run; assert_rc 0 "no args prints help"
run bogus; assert_rc 2 "unknown command exits 2"; assert_contains "unknown command: bogus" "unknown cmd message"
run --nope; assert_rc 2 "unknown global option exits 2"
run help bogus; assert_rc 2 "help for unknown command"

# --- docs/COMMANDS.md is generated from the headers: it must not drift
run help --markdown
assert_rc 0 "help --markdown"
if [ -f "$TEST_ROOT/docs/COMMANDS.md" ]; then
  if [ "$OUT" = "$(cat "$TEST_ROOT/docs/COMMANDS.md")" ]; then pass; else flunk "docs/COMMANDS.md is stale: regenerate with: bin/mach help --markdown > docs/COMMANDS.md"; fi
else flunk "docs/COMMANDS.md missing"; fi

# --- invoked through a symlink (the ~/.local/bin/mach case) resolves its real directory
ln -s "$MACH" "$SANDBOX/bin/mach"
OUT=$("$SANDBOX/bin/mach" --version 2>&1); RC=$?
assert_rc 0 "symlinked entry"; assert_contains "mach $(cat "$TEST_ROOT/VERSION")" "symlinked entry version"
OUT=$("$SANDBOX/bin/mach" doctor --help 2>&1); RC=$?
assert_rc 0 "symlinked entry dispatches"; assert_contains "mach doctor" "symlinked dispatch"

# --- config precedence: default < shared < host < local < env < flag
run --json note --dry-run "x"
assert_eq "inbox" "$(json_get 'd["dest"]')" "built-in default is inbox"
mkdir -p "$MACH_CONFIG_DIR/hosts"
printf '[note]\ndefault = "drafts"\n' > "$MACH_CONFIG_DIR/config.toml"
run --json note --dry-run "x"
assert_eq "drafts" "$(json_get 'd["dest"]')" "shared config wins over built-in"
printf '[note]\ndefault = "agenda"\n' > "$MACH_CONFIG_DIR/hosts/linux-box.toml"
run --json note --dry-run "x"
assert_eq "agenda" "$(json_get 'd["dest"]')" "host config wins over shared"
printf '[note]\ndefault = "drafts"\n' > "$MACH_CONFIG_DIR/hosts/mac-laptop.toml"
MACH_HOST=mac-laptop run --json note --dry-run "x"
assert_eq "drafts" "$(json_get 'd["dest"]')" "each host reads only its own file"
printf '[note]\ndefault = "inbox"\n%s\n' "$SANDBOX_MACHINES" > "$MACH_CONFIG_DIR/local.toml"
run --json note --dry-run "x"
assert_eq "inbox" "$(json_get 'd["dest"]')" "local config wins over host"
MACH_NOTE_DEFAULT=drafts run --json note --dry-run "x"
assert_eq "drafts" "$(json_get 'd["dest"]')" "env wins over local"
MACH_NOTE_DEFAULT=drafts run --json note --dry-run --to agenda "x"
assert_eq "agenda" "$(json_get 'd["dest"]')" "flag wins over env"
# a broken config file is reported, not fatal
printf '[note\n' > "$MACH_CONFIG_DIR/local.toml"
run note --dry-run "x"
assert_contains "config not loaded" "broken config is reported"

# --- host map (tested through the python helper, which mirrors lib/common.sh)
printf '%s\n' "$SANDBOX_MACHINES" > "$MACH_CONFIG_DIR/local.toml"
for pair in "Mac-Laptop-Air.local:mac-laptop" "mac-laptop:mac-laptop" "linux-box:linux-box" "debian-lap:linux-box" "other:other"; do
  H=${pair%%:*}; WANT=${pair##*:}
  GOT=$(cd "$TEST_ROOT/lib" && MACH_HOST="" python3 -c "
import socket, mach_common as mc
socket.gethostname = lambda: '$H'
import os; os.environ.pop('MACH_HOST', None)
print(mc.host())")
  assert_eq "$WANT" "$GOT" "python host map $H"
  GOT=$(bash -c ". '$TEST_ROOT/lib/common.sh'; unset MACH_HOST; MACH_HOSTNAME='$H' mach_host")
  assert_eq "$WANT" "$GOT" "bash host map $H"
done
finish
