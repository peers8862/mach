#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2034
# Drafts iPhone -> Mac -> synced inbox. The mock never opens the real Drafts app.
set -u
. "$(dirname "$0")/lib.sh"
new_sandbox
export MACH_OS=darwin
ID=12345678-1234-1234-1234-123456789abc
export DRAFTS_ID="$ID"
export DRAFTS_CONTENT='---
mach: 1
type: research
title: Check the source
question: What happened?
output: stdout
---
Read the original article.'

cat > "$SANDBOX/bin/drafts" <<'EOF'
#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
ident = os.environ['DRAFTS_ID']
if args == ['--json', 'list', '--folder', 'inbox', '--tag', 'mach-outbox']:
    rows = [{'id': ident, 'title': 'Check the source'}]
    if os.environ.get('DRAFTS_EXTRA'):
        rows.append({'id': '00000000-0000-0000-0000-000000000001', 'title': 'Another brief'})
    print(json.dumps(rows))
elif args == ['--json', 'get', ident]:
    print(json.dumps({'id': ident, 'title': 'Check the source', 'folder': 'inbox',
                      'tags': ['mach-outbox'], 'content': os.environ['DRAFTS_CONTENT']}))
elif args == ['archive', ident]:
    if os.environ.get('DRAFTS_ARCHIVE_FAIL'):
        sys.exit(1)
    with open(os.environ['SANDBOX'] + '/archived', 'a') as fh:
        fh.write(ident + '\n')
else:
    sys.exit(2)
EOF
chmod +x "$SANDBOX/bin/drafts"
export SANDBOX
TARGET="$MACH_MF_ROOT/files/inbox/prompts/drafts-$ID.md"

run inbox pull-drafts
assert_rc 0 "preview succeeds"
assert_contains "PREVIEW $ID files/inbox/prompts/" "preview gives destination"
assert_no_file "$TARGET" "preview makes no file"
assert_no_file "$SANDBOX/archived" "preview leaves Drafts alone"

export DRAFTS_EXTRA=1
run --json inbox pull-drafts --limit 1
assert_rc 0 "limit caps a larger Drafts inbox"
assert_eq "1" "$(json_get 'len(d["items"])')" "limit processes just one draft"
unset DRAFTS_EXTRA

run --json inbox pull-drafts --apply
assert_rc 0 "apply succeeds"
assert_json "apply JSON"
assert_eq "delivered" "$(json_get 'd["items"][0]["status"]')" "reports delivery"
assert_file_has "$TARGET" "Read the original article." "saved exact prompt"
assert_file_has "$SANDBOX/archived" "$ID" "archives only after save"

export DRAFTS_ARCHIVE_FAIL=1
run inbox pull-drafts --apply
assert_rc 1 "archive failure is reported"
assert_contains "WARNING" "save is acknowledged as pending Drafts archive"
assert_file_has "$TARGET" "Read the original article." "saved document survives archive failure"
unset DRAFTS_ARCHIVE_FAIL
run inbox pull-drafts --apply
assert_rc 0 "retry is idempotent"
assert_eq "2" "$(wc -l < "$SANDBOX/archived" | tr -d ' ')" "retry can archive after a prior failure"

export DRAFTS_CONTENT='---
mach: 1
type: research
title: Changed after delivery
question: What happened?
output: stdout
---
Different content.'
run inbox pull-drafts --apply
assert_rc 1 "changed Drafts copy is a conflict"
assert_contains "CONFLICT" "conflict is visible"
assert_file_has "$TARGET" "Read the original article." "existing inbox file is preserved"

export DRAFTS_CONTENT='not a mach document'
export DRAFTS_ID=00000000-0000-0000-0000-000000000002
run --json inbox pull-drafts --apply
assert_rc 0 "plain tagged note is captured"
assert_eq "True" "$(json_get 'd["items"][0]["wrapped"]')" "plain note is marked wrapped"
assert_file_has "$MACH_MF_ROOT/files/inbox/prompts/drafts-$DRAFTS_ID.md" "Source: drafts://x-callback-url/open?uuid=$DRAFTS_ID" "capture keeps source link"
assert_file_has "$MACH_MF_ROOT/files/inbox/prompts/drafts-$DRAFTS_ID.md" "not a mach document" "capture keeps original text"

export DRAFTS_ID="$ID"
export DRAFTS_CONTENT='---
mach: 1
type: task
---
broken brief'
run inbox pull-drafts --apply
assert_rc 1 "malformed structured brief is retained"
assert_contains "INVALID" "validation failure is visible"

# Generated task/research actions round-trip through the actual collector and planner.
if command -v node >/dev/null 2>&1; then
  for choice in 0 1; do
    export DRAFTS_ID="00000000-0000-0000-0000-00000000001$choice"
    DRAFTS_CONTENT=$(python3 - "$TEST_ROOT" "$choice" <<'PYCODE'
import json, pathlib, subprocess, sys
root=pathlib.Path(sys.argv[1])
action=json.loads((root/'drafts/Importing/Mach-Hub.draftsAction').read_text())
request=dict(script=action['steps'][0]['data']['script'],requests=[dict(text='',choice=int(sys.argv[2]))])
result=subprocess.check_output(['node',str(root/'tests/drafts_hub_runner.js')],input=json.dumps(request).encode())
print(json.loads(result)[0]['created']['content'])
PYCODE
)
    export DRAFTS_CONTENT
    run inbox pull-drafts --apply
    assert_rc 0 "generated template collects"
    run inbox pull-drafts --apply
    assert_rc 0 "generated template resends idempotently"
    assert_eq "1" "$(find "$MACH_MF_ROOT/files/inbox/prompts" -name "drafts-$DRAFTS_ID.md" | wc -l | tr -d ' ')" "one request file per UUID"
    run run --inbox --dry-run
    assert_rc 0 "generated templates round-trip through inbox planning"
  done
fi

export MACH_OS=linux
run inbox pull-drafts --apply
assert_rc 1 "Linux cannot pull Mac Drafts"
assert_contains "Mac" "Linux explains where to run it"
finish
