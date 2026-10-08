#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# tests/lib.sh: helpers for the bash tests. Source it from a test_*.sh file. bash 3.2 compatible.
# Every test runs in a throwaway sandbox under <repo>/.tmp/ (never /tmp, never the real ~/machine-flows):
# HOME, MACH_MF_ROOT, MACH_STAGING, MACH_RUNS_DIR, MACH_CONFIG_DIR and MACH_HOST point into it, and mock AI tools are on PATH.
set -u
export PYTHONDONTWRITEBYTECODE=1
TEST_ROOT=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MACH="$TEST_ROOT/bin/mach"
REAL_HOME=$HOME
FIXTURES="$TEST_ROOT/tests/fixtures"   # generic templates and subsystems; tests never read the real machine-flows tree
# machine names for every sandbox (the shared/local config layers are written per test; this block is appended where needed)
SANDBOX_MACHINES='[machines]
names = ["linux-box", "mac-laptop"]
mac = "mac-laptop"
collector = "linux-box"
[machines.match]
mac-laptop = "mac-laptop"
linux-box = "linux-box"
debian = "linux-box"
'
PASS=0; FAILN=0; TEST_NAME=${TEST_NAME:-$(basename "$0")}
SANDBOX=""

pass() { PASS=$((PASS + 1)); }
flunk() { FAILN=$((FAILN + 1)); printf '  FAIL [%s] %s\n' "$TEST_NAME" "$*"; }

new_sandbox() {
  check_canaries
  mkdir -p "$TEST_ROOT/.tmp"
  SANDBOX=$(mktemp -d "$TEST_ROOT/.tmp/t.XXXXXX")
  export HOME="$SANDBOX/home" MACH_MF_ROOT="$SANDBOX/mf" MACH_STAGING="$SANDBOX/home/machine-flows-staging" MACH_CONFIG_DIR="$SANDBOX/cfg"
  export MACH_RUNS_DIR="$SANDBOX/mf/files/runs" MACH_HOST=linux-box MACH_OS="${MACH_TEST_OS:-linux}" MACH_NOW="2026-10-08 09:30:00"
  export MACH_BIN_DIR="$SANDBOX/home/.local/bin" MACH_LOCAL_STATE="$SANDBOX/state" MACH_NO_COLOR=1 TZ=America/Toronto
  unset MACH_NOTE_DEFAULT MACH_DRY_RUN MACH_JSON MACH_YES MACH_TARGET_HOST MACH_DEFAULT_TOOL MACH_STATE_DIR MACH_DOCS_COLLECT MACH_DOCS_HISTORY NO_COLOR
  sandbox_external_commands
  mkdir -p "$HOME/.local/bin" "$MACH_MF_ROOT" "$MACH_STAGING" "$MACH_CONFIG_DIR" "$SANDBOX/bin" "$MACH_LOCAL_STATE"
  printf '%s\n' "$SANDBOX_MACHINES" > "$MACH_CONFIG_DIR/local.toml"
  export PATH="$SANDBOX/bin:$SANDBOX/realbin:$ORIG_PATH"
  make_mocks
  make_canaries
  assert_sandbox_hermetic
}
ORIG_PATH=$PATH

# Every outside program mach can run (anything with side effects or a network) is pinned to a path INSIDE the sandbox.
# A mock at that path = "installed"; a missing file = "not available". Removing a mock therefore never falls back to the real
# /usr/bin/open, drafts, osascript, claude, tmux, launchctl, systemctl, crontab, ssh ... on the machine running the tests.
# Keep this list in step with CMD_VARS in lib/mach_common.py (tests/test_lint.sh checks that).
EXTERNAL_CMD_VARS="MACH_OPEN_CMD:open MACH_DRAFTS_CMD:drafts MACH_OSASCRIPT_CMD:osascript MACH_TMUX:tmux MACH_LAUNCHCTL_CMD:launchctl
MACH_SYSTEMCTL_CMD:systemctl MACH_CRONTAB_CMD:crontab MACH_SSH_CMD:ssh MACH_CLAUDE_CMD:claude MACH_CODEX_CMD:codex
MACH_CURSOR_AGENT_CMD:cursor-agent MACH_KIRO_CMD:kiro-cli MACH_GROKCLI_AGENT_CMD:grokcli-agent MACH_CURL_CMD:curl"
sandbox_external_commands() {
  local pair
  for pair in $EXTERNAL_CMD_VARS; do export "${pair%%:*}=$SANDBOX/bin/${pair#*:}"; done
  export MACH_AGENDA_MCP_URL="http://127.0.0.1:9/mcp"   # port 9 (discard) is closed: a test that wants a fake Agenda starts its own server
}
# assert_sandbox_hermetic: fails when an external-command variable is unset or points outside the sandbox
assert_sandbox_hermetic() {
  local pair var val
  for pair in $EXTERNAL_CMD_VARS; do
    var=${pair%%:*}; eval "val=\${$var:-}"
    case "$val" in "$SANDBOX"/*) pass ;; *) flunk "sandbox: $var is not pinned inside the sandbox (got '${val:-unset}')" ;; esac
  done
  case "${MACH_AGENDA_MCP_URL:-}" in http://127.0.0.1:*) pass ;; *) flunk "sandbox: MACH_AGENDA_MCP_URL must be a closed local port" ;; esac
}

# Canaries: stand-ins for the REAL programs (like /usr/bin/open on a Mac). They sit on PATH behind the mocks, so a test that deletes
# a mock, or code that resolves a bare name, would reach them. They only log; finish() fails the test if any was called.
CANARY_NAMES="curl open drafts osascript claude codex cursor-agent kiro-cli grokcli-agent tmux launchctl systemctl crontab ssh"
make_canaries() {
  mkdir -p "$SANDBOX/realbin"; : > "$SANDBOX/canary.log"
  local n
  for n in $CANARY_NAMES; do
    printf '#!/usr/bin/env bash\necho "REAL %s $*" >> "%s/canary.log"\nexit 99\n' "$n" "$SANDBOX" > "$SANDBOX/realbin/$n"
    chmod +x "$SANDBOX/realbin/$n"
  done
}
check_canaries() {
  if [ -n "$SANDBOX" ] && [ -s "$SANDBOX/canary.log" ]; then flunk "a REAL side-effecting program was reached: $(head -n 3 "$SANDBOX/canary.log" | tr '\n' '|')"; else pass; fi
}

cleanup_sandbox() { [ -n "$SANDBOX" ] && case "$SANDBOX" in "$TEST_ROOT"/.tmp/t.*) rm -rf "$SANDBOX" ;; esac; }

# mock executables: print their name and arguments, never contact anything
make_mock() {
  local name=$1 out="$SANDBOX/bin/$1"
  cat > "$out" <<EOF
#!/usr/bin/env bash
echo "MOCK $name \$*" >> "$SANDBOX/mock-calls.log"
if [ -n "\${MOCK_FAIL:-}" ]; then echo "mock failure" >&2; exit 1; fi
echo "MOCK-OUTPUT from $name: \$*"
EOF
  chmod +x "$out"
}
make_mocks() {
  : > "$SANDBOX/mock-calls.log"
  local t
  for t in curl claude codex cursor-agent kiro-cli grokcli-agent tmux open drafts; do make_mock "$t"; done
  # a systemctl that says everything is fine, so doctor is hermetic
  cat > "$SANDBOX/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *is-active*) echo active; exit 0 ;;
  *--failed*) exit 0 ;;
esac
exit 0
EOF
  chmod +x "$SANDBOX/bin/systemctl"
}

# run <args...>: runs mach, captures stdout+stderr in $OUT and the exit code in $RC
run() { OUT=$("$MACH" "$@" 2>&1); RC=$?; }
run_split() { OUT=$("$MACH" "$@" 2>"$SANDBOX/stderr"); RC=$?; ERR=$(cat "$SANDBOX/stderr"); }

assert_rc() { # assert_rc <expected> <label>
  if [ "$RC" = "$1" ]; then pass; else flunk "$2: expected exit $1, got $RC; output: $(printf '%s' "$OUT" | head -n 6 | tr '\n' '|')"; fi
}
assert_contains() { # assert_contains <needle> <label>   (searches $OUT)
  case "$OUT" in *"$1"*) pass ;; *) flunk "$2: output lacks '$1'; got: $(printf '%s' "$OUT" | head -n 6 | tr '\n' '|')" ;; esac
}
assert_not_contains() {
  case "$OUT" in *"$1"*) flunk "$2: output unexpectedly has '$1'" ;; *) pass ;; esac
}
assert_file() { if [ -f "$1" ]; then pass; else flunk "${2:-file}: missing $1"; fi; }
assert_no_file() { if [ ! -e "$1" ]; then pass; else flunk "${2:-file}: unexpectedly exists $1"; fi; }
assert_file_has() { # assert_file_has <file> <needle> <label>
  if [ -f "$1" ] && grep -qF -- "$2" "$1"; then pass; else flunk "$3: $1 lacks '$2'"; fi
}
assert_file_lacks() {
  if [ -f "$1" ] && grep -qF -- "$2" "$1"; then flunk "$3: $1 unexpectedly has '$2'"; else pass; fi
}
assert_eq() { if [ "$1" = "$2" ]; then pass; else flunk "$3: expected '$1', got '$2'"; fi; }
assert_json() { # validates $OUT as JSON
  if printf '%s' "$OUT" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then pass; else flunk "$1: output is not valid JSON: $(printf '%s' "$OUT" | head -n 3 | tr '\n' '|')"; fi
}
json_get() { # json_get <python expr on d>  (reads $OUT)
  printf '%s' "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null
}

# most recently written run directory (ids share a minute because MACH_NOW is pinned, so go by file time)
latest_run_dir() {
  local f
  f=$(find "$MACH_RUNS_DIR" -name run.md 2>/dev/null | while IFS= read -r p; do printf '%s\t%s\n' "$(python3 -c 'import os,sys; print(os.stat(sys.argv[1]).st_mtime_ns)' "$p")" "$p"; done | sort -n | tail -n 1 | cut -f2)
  [ -n "$f" ] && dirname "$f"
}
mock_calls() { cat "$SANDBOX/mock-calls.log"; }
mock_count() { grep -c "^MOCK" "$SANDBOX/mock-calls.log" || true; }
glob1() { local f; for f in $1; do [ -e "$f" ] && { printf "%s" "$f"; return 0; }; done; return 1; }

finish() {
  check_canaries
  cleanup_sandbox
  printf '%s: %d passed, %d failed\n' "$TEST_NAME" "$PASS" "$FAILN"
  [ "$FAILN" = 0 ]
}
