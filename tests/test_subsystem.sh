#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2016,SC2034
set -u
TEST_NAME=subsystem
. "$(dirname "$0")/lib.sh"
new_sandbox
mkdir -p "$MACH_MF_ROOT/subsystems/demo" "$MACH_MF_ROOT/subsystems/_template" "$MACH_MF_ROOT/files/inbox/subsystems"
cp "$TEST_ROOT/config/subsystem.example.toml" "$MACH_MF_ROOT/subsystems/demo/subsystem.toml"
cp "$FIXTURES/subsystems/_template/subsystem.toml" "$MACH_MF_ROOT/subsystems/_template/subsystem.toml"
export MACH_SUBSYSTEMS_DIR="$MACH_MF_ROOT/subsystems" MACH_FORCE_MINITOML=1
run subsystem lint demo; assert_rc 0 "example lints with minitoml"; assert_not_contains FAIL "example has no FAIL"
run subsystem list --json; assert_rc 0 "list"; assert_json "list JSON"; assert_contains demo "list contains the example"
run subsystem show demo --json; assert_rc 0 "show"; assert_json "show JSON"
mkdir -p "$MACH_SUBSYSTEMS_DIR/note"; cp "$MACH_SUBSYSTEMS_DIR/demo/subsystem.toml" "$MACH_SUBSYSTEMS_DIR/note/subsystem.toml"
run subsystem lint note; assert_rc 2 "collision fails lint"; assert_contains FAIL "collision shown"
run demo; assert_rc 0 "tree"; assert_contains beta "tree has beta"
run demo alpha --roles; assert_rc 0 "roles"; assert_contains drafting "secondary role"
run demo alpha --role drafting --dry-run hello; assert_rc 0 "role dry-run"; assert_contains claude "drafting uses claude"
run demo alpha --to codex --dry-run hello; assert_rc 0 "override"; assert_contains codex "override uses codex"
run demo alpha --dry-run hello; assert_rc 0 "webhook dry-run"; assert_contains '<redacted>' "dry-run key placeholder"
run demo alpha --to codex hello; assert_rc 0 "CLI dispatch with fake codex"; assert_contains 'MOCK-OUTPUT from codex' "CLI output"
RD=$(latest_run_dir); assert_file_has "$RD/run.md" 'delivery: cli' "CLI delivery recorded"
run demo alpha --to note:inbox hello; assert_rc 0 "note dispatch"; assert_contains 'noted' "note result"
printf '[note.dest.work]\ntype = "inbox"\n' > "$MACH_CONFIG_DIR/config.toml"
run demo alpha --to user hello; assert_rc 0 "user destination"; assert_contains 'noted' "user note result"

run demo alpha hello; assert_rc 1 "missing secrets fallback"; assert_contains paste-ready "fallback shown"
RD=$(latest_run_dir); assert_file "$RD/prompt-for-grokbot.md" "fallback prompt"; assert_file_has "$RD/run.md" 'delivery: paste-ready' "fallback delivery"
mkdir -p "$HOME/.config/mach"
cat > "$HOME/.config/mach/secrets.toml" <<'TOML'
[grokbot_router]
url = "https://router.example.invalid/secret-path"
key = "test-key-12345"
key_header = "X-Webhook-Key"
TOML
export MACH_SECRETS_FILE="$HOME/.config/mach/secrets.toml"
chmod 644 "$MACH_SECRETS_FILE"
run demo alpha hello; assert_rc 1 "unsafe secrets fallback"; assert_contains 'chmod 600' "chmod hint"
chmod 600 "$MACH_SECRETS_FILE"
cat > "$MACH_CURL_CMD" <<'SH'
#!/usr/bin/env bash
cat > "$SANDBOX/curl-config"
printf '%s\n' "$*" > "$SANDBOX/curl-argv"
printf 'receipt-ok\n200'
SH
chmod +x "$MACH_CURL_CMD"
export SANDBOX
run demo alpha hello; assert_rc 0 "router success"; assert_contains 'delivered to router' "router receipt"
RD=$(latest_run_dir); assert_file_has "$RD/run.md" 'status: done' "router run done"; assert_file_lacks "$RD/run.md" 'test-key-12345' "run redacts key"
assert_file_lacks "$RD/run.md" 'secret-path' "run redacts URL"
assert_file_lacks "$SANDBOX/curl-argv" 'test-key-12345' "curl argv redacts key"
assert_file_has "$SANDBOX/curl-config" 'test-key-12345' "curl stdin carries key"
run demo alpha --dry-run --reply inbox hello; assert_rc 0 "inbox reply dry-run"; assert_contains 'files/inbox/replies/' "reply path"
cat > "$MACH_CURL_CMD" <<'SH'
#!/usr/bin/env bash
cat >/dev/null
printf 'failed request test-key-12345 https://router.example.invalid/secret-path\n500'
SH
chmod +x "$MACH_CURL_CMD"
run demo alpha hello; assert_rc 2 "router 500"; assert_contains 'failed request' "redacted failure receipt"; assert_not_contains 'test-key-12345' "failure hides key"; assert_not_contains 'secret-path' "failure hides URL"
# A low cap blocks another router fire; --force bypasses it.
python3 - "$MACH_SUBSYSTEMS_DIR/demo/subsystem.toml" <<'PY2'
import sys
p=sys.argv[1];s=open(p).read().replace('max_fires_per_day = 20','max_fires_per_day = 1');open(p,'w').write(s)
PY2
run demo alpha hello; assert_rc 2 "daily cap blocks after router fires"; assert_contains 'daily Grok Bot cap' "cap message"
run demo alpha --force --dry-run hello; assert_rc 0 "force skips cap"
python3 - "$MACH_SUBSYSTEMS_DIR/demo/subsystem.toml" <<'PY2'
import sys
p=sys.argv[1];s=open(p).read().replace('max_fires_per_day = 1','max_fires_per_day = 20');open(p,'w').write(s)
PY2
# A subsystem prompt in the prompt inbox is marked processed via the run source.
mkdir -p "$MACH_MF_ROOT/files/inbox/prompts"
cat > "$MACH_MF_ROOT/files/inbox/prompts/test.md" <<'PROMPT'
---
mach: 1
type: subsystem-prompt
title: Inbox unit prompt
subsystem: demo
unit: alpha
to: note:inbox
machine: linux-box
---
Review this issue.
PROMPT
run run --inbox; assert_rc 0 "run inbox subsystem prompt"
run queue; assert_not_contains 'test.md ' "processed prompt leaves queue"
run subsystem new example; assert_rc 0 "scaffold preview"; assert_no_file "$MACH_SUBSYSTEMS_DIR/example/subsystem.toml" "preview no write"
run subsystem new example --apply; assert_rc 0 "scaffold apply"; assert_file "$MACH_SUBSYSTEMS_DIR/example/subsystem.toml" "scaffold file"
cp "$FIXTURES/templates/subsystem-setup.md" "$SANDBOX/setup.md"
run subsystem new example --from "$SANDBOX/setup.md" --replace; assert_rc 0 "from preview"
run subsystem new example --from "$SANDBOX/setup.md" --replace --apply; assert_rc 0 "from apply"
cp "$FIXTURES/templates/unit-setup.md" "$SANDBOX/unit.md"
run subsystem unit example --from "$SANDBOX/unit.md"; assert_rc 0 "unit preview"
run subsystem unit example --from "$SANDBOX/unit.md" --apply; assert_rc 0 "unit apply"
cp "$FIXTURES/templates/role-change.md" "$SANDBOX/role.md"
run subsystem role example --from "$SANDBOX/role.md"; assert_rc 0 "role preview"
run subsystem role example --from "$SANDBOX/role.md" --apply; assert_rc 0 "role apply"
assert_file_has "$MACH_SUBSYSTEMS_DIR/example/subsystem.toml" 'Human review' "role history"
cp "$SANDBOX/setup.md" "$MACH_MF_ROOT/files/inbox/subsystems/setup.md"
printf "\n# pending new request\n" >> "$MACH_MF_ROOT/files/inbox/subsystems/setup.md"
run queue; assert_rc 0 "queue"; assert_contains 'mach subsystem new example --from' "queue ingest hint"
# point a copy of the subsystem-prompt template at the example manifest
sed -e 's/^subsystem: .*/subsystem: demo/' -e 's/^unit: .*/unit: alpha/' "$FIXTURES/templates/subsystem-prompt.md" > "$SANDBOX/subsystem-prompt.md"
run run --dry-run "$SANDBOX/subsystem-prompt.md"; assert_rc 0 "subsystem-prompt run dry-run"
for name in task-brief research-brief; do
  run run --dry-run "$FIXTURES/templates/$name.md"
  assert_rc 0 "$name run dry-run"
done
run run --dry-run "$SANDBOX/setup.md"; assert_rc 2 "run rejects setup"; assert_contains 'mach subsystem new' "setup hint"
finish
