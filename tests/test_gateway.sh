#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# do / ask / research / run / flow / approve / reject / status / queue, all against mock tools.
TEST_NAME=gateway
. "$(dirname "$0")/lib.sh"
new_sandbox
TPL="$FIXTURES/templates"
mkdir -p "$MACH_MF_ROOT/files/inbox/prompts" "$SANDBOX/docs"

task_doc() { # task_doc <file> <extra frontmatter lines...>; an extra line replaces a default key of the same name
  local f=$1; shift
  local base='mach: 1|type: task|title: Test task|goal: Summarise things|tool: claude|output: stdout' line key l skip
  {
    printf -- '---\n'
    OLDIFS=$IFS; IFS='|'
    for line in $base; do
      key=${line%%:*}; skip=0
      for l in "$@"; do case "$l" in "$key":*) skip=1 ;; esac; done
      [ "$skip" = 1 ] || printf '%s\n' "$line"
    done
    IFS=$OLDIFS
    for l in "$@"; do printf '%s\n' "$l"; done
    printf -- '---\nDo the thing.\n\n## Context\n- none\n'
  } > "$f"
}

# ===================== real templates: dry-run accepted (they may hold placeholders)
if [ -d "$TPL" ]; then
  for t in task-brief research-brief flow-request; do
    run run --dry-run "$TPL/$t.md"
    assert_rc 0 "dry-run $t"
  done
  run run --dry-run "$TPL/task-brief.md"
  assert_contains "claude -p" "dry-run prints the exact command"
  assert_contains "--permission-mode plan" "read-only by default"
  assert_eq "0" "$(find "$MACH_RUNS_DIR" -name run.md 2>/dev/null | wc -l | tr -d ' ')" "dry-run creates no run record"
  assert_eq "" "$(mock_calls)" "dry-run calls no tool"
else
  printf '  note: real templates not found at %s, skipped\n' "$TPL"
fi

# ===================== validation errors carry file:line
task_doc "$SANDBOX/docs/bad.md" "bogus: 1"
run run "$SANDBOX/docs/bad.md"
assert_rc 2 "unknown key exits 2"
assert_contains "bad.md:8: error: unknown key 'bogus'" "error has the line number (extra keys are appended after the 6 defaults)"
task_doc "$SANDBOX/docs/badval.md" "approval: sometimes"
run run --dry-run "$SANDBOX/docs/badval.md"
assert_rc 2 "bad value exits 2"
assert_contains "approval:" "bad value is named"
printf 'no frontmatter at all\n' > "$SANDBOX/docs/plain.md"
run run "$SANDBOX/docs/plain.md"
assert_rc 2 "no frontmatter exits 2"
run run "$SANDBOX/docs/missing.md"
assert_rc 2 "missing file exits 2"
assert_eq "" "$(mock_calls)" "invalid documents never reach a tool"

# ===================== run: execute, record, never modify the input
task_doc "$SANDBOX/docs/ok.md"
SUM_BEFORE=$(cksum < "$SANDBOX/docs/ok.md")
run run "$SANDBOX/docs/ok.md"
assert_rc 0 "run executes"
assert_contains "MOCK-OUTPUT from claude" "tool output is shown"
assert_eq "$SUM_BEFORE" "$(cksum < "$SANDBOX/docs/ok.md")" "input file is untouched"
RD=$(latest_run_dir)
assert_file "$RD/run.md" "run record"
assert_file "$RD/input.md" "input copy"
assert_file "$RD/output-1.md" "step output"
assert_file_has "$RD/run.md" "status: done" "record says done"
assert_file_has "$RD/run.md" "machine: linux-box" "record has the machine"
assert_file_has "$RD/run.md" "tool: claude" "record has the tool"
assert_file_has "$RD/run.md" "| 1 | run | claude | done |" "record has the steps table"
case "$(basename "$RD")" in 20261008-0930-linux-box-test-task) pass ;; *) flunk "run id format: $(basename "$RD")" ;; esac
assert_file "$MACH_LOCAL_STATE/logs/$(basename "$RD").log" "raw log stays local"
assert_eq "0" "$(find "$MACH_MF_ROOT" -name '*.log' | wc -l | tr -d ' ')" "no log files inside machine-flows"
run run "$SANDBOX/docs/ok.md"
case "$(ls "$MACH_RUNS_DIR/2026/10" | tr '\n' ' ')" in *"20261008-0930-linux-box-test-task-2"*) pass ;; *) flunk "id collision suffix: $(ls "$MACH_RUNS_DIR/2026/10")" ;; esac

# the tool failing is a failed run, exit 2
MOCK_FAIL=1 run run "$SANDBOX/docs/ok.md"
assert_rc 2 "tool failure exits 2"
assert_contains "exited 1" "failure is reported"
run status --json
assert_json "status --json"
assert_contains "failed" "status lists the failed run"

# ===================== output to a file
task_doc "$SANDBOX/docs/file.md" "output: files/reports/out-YYYY-MM-DD.md"
run run "$SANDBOX/docs/file.md"
assert_rc 0 "file output"
assert_file "$MACH_MF_ROOT/files/reports/out-2026-10-08.md" "output file with date substituted"
run run "$SANDBOX/docs/file.md"
assert_file "$MACH_MF_ROOT/files/reports/out-2026-10-08-2.md" "existing output is never overwritten"
task_doc "$SANDBOX/docs/out.md" "output: /etc/mach-test-output.md"
run run "$SANDBOX/docs/out.md"
assert_rc 2 "output outside allowed folders is refused"
assert_no_file /etc/mach-test-output.md "nothing written outside"

# ===================== gates
# before-apply: runs read-only, holds the output, writes only after approve
task_doc "$SANDBOX/docs/apply.md" "output: files/reports/held.md" "approval: before-apply"
run run "$SANDBOX/docs/apply.md"
assert_rc 3 "before-apply stops at a gate"
assert_contains "waiting for approval" "gate message"
assert_no_file "$MACH_MF_ROOT/files/reports/held.md" "nothing written before approval"
RID=$(basename "$(latest_run_dir)")
run status "$RID"
assert_contains "waiting-approval" "status shows the gate"
run queue
assert_contains "waiting for approval (1)" "queue lists the waiting run"
run approve "$RID"
assert_rc 0 "approve continues"
assert_file "$MACH_MF_ROOT/files/reports/held.md" "output written after approval"
run approve "$RID"
assert_rc 2 "cannot approve twice"
# before-run: nothing executes until approved
: > "$SANDBOX/mock-calls.log"
task_doc "$SANDBOX/docs/brun.md" "approval: before-run"
run run "$SANDBOX/docs/brun.md"
assert_rc 3 "before-run stops at a gate"
assert_eq "" "$(mock_calls)" "no tool call before approval"
RID=$(basename "$(latest_run_dir)")
run reject "$RID" "not now"
assert_rc 0 "reject"
run status "$RID"
assert_contains "cancelled" "rejected run is cancelled"
assert_contains "not now" "reason is recorded"
run approve "$RID"
assert_rc 2 "a cancelled run cannot be approved"
# outward outputs ALWAYS stop at a gate, even with approval: none; after approval only a handoff is written
for o in pr linear-comment; do
  task_doc "$SANDBOX/docs/$o.md" "output: $o" "approval: none"
  : > "$SANDBOX/mock-calls.log"
  run run "$SANDBOX/docs/$o.md"
  assert_rc 3 "output $o is gated"
  RID=$(basename "$(latest_run_dir)")
  run approve "$RID"
  assert_rc 0 "approve $o"
  assert_file "$(latest_run_dir)/handoff-$o.md" "handoff file for $o"
  assert_eq "1" "$(mock_count)" "exactly one tool call for $o (no outward tool call)"
  if [ "$o" = pr ]; then PRDIR=$(latest_run_dir); fi
done
assert_file_has "$PRDIR/handoff-pr.md" "gh pr create" "pr handoff has the command"
assert_file_has "$PRDIR/handoff-pr.md" "mach never runs" "pr handoff says mach will not run it"
OUT=$(mock_calls); assert_not_contains "MOCK gh" "gh is never called"

# ===================== --queue and --inbox
task_doc "$SANDBOX/docs/q.md" "machine: any"
: > "$SANDBOX/mock-calls.log"
run run --queue "$SANDBOX/docs/q.md"
assert_rc 0 "queue"
assert_contains "queued" "queue message"
assert_eq "" "$(mock_calls)" "queueing calls no tool"
run queue
assert_contains "queued runs (1)" "queue shows the queued run"
run_split --json run --queue "$SANDBOX/docs/q.md"
assert_json "run --queue --json (human lines go to stderr)"
assert_eq "queued" "$(json_get 'd["status"]')" "queued status in json"
# a doc for another machine is queued for it, not executed here
task_doc "$SANDBOX/docs/mac.md" "machine: mac-laptop"
run run "$SANDBOX/docs/mac.md"
assert_rc 0 "doc for another machine"
assert_contains "no SSH execution" "explains v1 limit"
assert_eq "" "$(mock_calls)" "other machine's work is not executed here"
# inbox
task_doc "$MACH_MF_ROOT/files/inbox/prompts/20261008-0900-mine.md" "machine: linux-box" "tool: codex"
task_doc "$MACH_MF_ROOT/files/inbox/prompts/20261008-0901-theirs.md" "machine: mac-laptop"
task_doc "$MACH_MF_ROOT/files/inbox/prompts/20261008-0902-any.md" "machine: any" "due: 2026-10-08"
task_doc "$MACH_MF_ROOT/files/inbox/prompts/20261008-0903-bad.md" "nonsense: 1"
run queue
assert_contains "inbox prompts not yet run (4)" "queue lists inbox prompts"
assert_contains "INVALID" "queue flags the invalid one"
run queue --due today
assert_contains "inbox prompts not yet run (1)" "due filter"
: > "$SANDBOX/mock-calls.log"
run run --inbox --dry-run
assert_contains "2 to run on linux-box" "inbox dry-run counts docs for this machine (mine + any→linux-box)"
assert_eq "" "$(mock_calls)" "inbox dry-run runs nothing"
run run --inbox
assert_rc 1 "inbox: invalid doc makes it a warning"
assert_contains "MOCK-OUTPUT from codex" "uses the document's tool"
OUT=$(mock_calls); assert_contains "MOCK codex exec --sandbox read-only" "codex headless read-only"
run run --inbox
assert_contains "0 to run on linux-box" "second pass: nothing left to run"
MACH_HOST=mac-laptop run queue
assert_contains "theirs" "the other machine still sees its own doc"

# ===================== do
: > "$SANDBOX/mock-calls.log"
run "do" "tidy the headings" --dry-run
assert_rc 0 "do --dry-run"
assert_contains "tool        claude" "route shows the tool"
assert_contains "machine     linux-box" "route shows the machine"
assert_contains "permission  read-only" "route shows the permission"
assert_contains "claude -p 'tidy the headings' --permission-mode plan" "exact command"
assert_eq "" "$(mock_calls)" "dry-run runs nothing"
run "do" "tidy the headings"
assert_rc 2 "non-interactive do needs --yes"
assert_contains "--yes" "says how to confirm"
run "do" "tidy the headings" --yes
assert_rc 0 "do --yes"
assert_contains "MOCK-OUTPUT from claude: -p tidy the headings --permission-mode plan" "tool ran read-only"
run "do" "write it" --yes --write --tool codex
OUT=$(mock_calls); assert_contains "MOCK codex exec --sandbox workspace-write" "--write switches permission"
run "do" "x" --yes --tool nonsense
assert_rc 2 "unknown tool"
run "do" "x" --yes --tool kiro --dry-run
assert_contains "kiro-cli chat --no-interactive --trust-tools= x" "kiro maps to kiro-cli, no tools trusted"
run "do" "remote job" --machine mac-laptop --yes
assert_rc 0 "do for another machine"
assert_contains "queued" "queued for the other machine"
assert_contains "no SSH" "no ssh in v1"
: > "$SANDBOX/mock-calls.log"
run "do" "bg job" --bg --yes
assert_rc 0 "do --bg"
assert_contains "tmux" "uses tmux"
OUT=$(mock_calls); assert_contains "MOCK tmux new-session -d -s mach-bg-job" "tmux session started"
MACH_TMUX=tmux-not-installed-xyz run "do" "bg" --bg --yes
assert_rc 2 "--bg without tmux is an error"
assert_contains "needs tmux" "names tmux"
run "do" "bg" --bg --dry-run
assert_rc 0 "--bg dry-run prints the plan"
assert_contains "tmux session named mach-bg" "dry-run mentions the tmux session"
# config routes: a project path routes to its tool
mkdir -p "$SANDBOX/proj"
printf '[routes.project.demo]\npath = "%s"\ntool = "codex"\n' "$SANDBOX/proj" > "$MACH_CONFIG_DIR/config.toml"
run "do" "in project" --path "$SANDBOX/proj" --dry-run
assert_contains "tool        codex" "project route picks the tool"
assert_contains "project route 'demo'" "route says why"
rm -f "$MACH_CONFIG_DIR/config.toml"
MACH_DEFAULT_TOOL=kiro run "do" "x" --dry-run
assert_contains "tool        kiro" "env default tool"

# ===================== ask
: > "$SANDBOX/mock-calls.log"
for t in claude codex cursor-agent kiro grokcli-agent; do
  run ask $t "why is the sky blue" --dry-run
  assert_rc 0 "ask $t --dry-run"
done
run ask claude "why" --dry-run;        assert_contains "claude -p why --permission-mode plan" "claude read-only flags"
run ask codex "why" --dry-run;         assert_contains "codex exec --sandbox read-only" "codex read-only flags"
run ask cursor-agent "why" --dry-run;  assert_contains "cursor-agent -p --output-format text --trust --mode ask why" "cursor-agent read-only flags"
run ask kiro "why" --dry-run;          assert_contains "kiro-cli chat --no-interactive --trust-tools= why" "kiro read-only flags"
run ask grokcli-agent "why" --dry-run; assert_contains "grokcli-agent -p why" "grok best-guess flags"
assert_contains "best guess" "grok flags are marked as a guess"
run ask claude "why" --write --dry-run; assert_contains "acceptEdits" "--write for claude"
assert_eq "" "$(mock_calls)" "ask --dry-run never calls a tool"
run ask agent "x";   assert_rc 2 "bare agent is refused"; assert_contains "no bare" "explains"
run ask bogus "x";   assert_rc 2 "unknown tool refused"
printf '[tools.codex]\ncommand = "codex-not-installed-xyz"\n' > "$MACH_CONFIG_DIR/config.toml"
MACH_CODEX_CMD="" run ask codex "x"   # env override blanked: the config command applies
assert_rc 2 "missing tool exits 2"
assert_contains "not found on PATH" "clear missing-tool error"
rm -f "$MACH_CONFIG_DIR/config.toml"
rm -f "$SANDBOX/bin/codex"          # a removed mock means "not installed", never the real codex
run ask codex "x"
assert_rc 2 "removed sandbox mock: tool not available"
assert_contains "not found on PATH" "removed mock gives the missing-tool error"
make_mock codex
run ask claude "hello there"
assert_rc 0 "ask runs"
assert_contains "MOCK-OUTPUT from claude: -p hello there --permission-mode plan" "answer on stdout"
run --json ask codex "json please"
assert_json "ask --json"
run ask grokbot "paste me"
assert_rc 0 "ask grokbot"
assert_contains "prompt-for-grokbot.md" "paste-ready prompt file"
assert_file "$(latest_run_dir)/prompt-for-grokbot.md" "prompt file in the run folder"
assert_file_has "$(latest_run_dir)/run.md" "status: queued" "grokbot item is queued"
assert_eq "0" "$(mock_calls | grep -c grokbot)" "no automation of the Grok Bot app"
MOCK_FAIL=1 run ask claude "boom"
assert_rc 2 "failing tool"

# ===================== research
: > "$SANDBOX/mock-calls.log"
run research "syncthing on macos" --dry-run
assert_rc 0 "research dry-run"
assert_contains "files/research/2026-10-08-syncthing-on-macos.md" "target file"
assert_eq "" "$(mock_calls)" "dry-run calls nothing"
run research "syncthing on macos"
assert_rc 0 "research quick"
assert_file "$MACH_MF_ROOT/files/research/2026-10-08-syncthing-on-macos.md" "research file"
assert_file_has "$MACH_MF_ROOT/files/research/2026-10-08-syncthing-on-macos.md" "## Sources" "has a sources section"
run research "deep question" --depth deep --dry-run
assert_rc 0 "deep dry-run"
assert_contains "research-to-plan" "deep starts the flow"

# ===================== flows
run flow list
assert_rc 0 "flow list"
assert_contains "morning" "lists morning"
assert_contains "research-to-plan" "lists research-to-plan"
assert_contains "issue-to-pr" "lists issue-to-pr"
run flow nonsense
assert_rc 2 "unknown flow"
run flow research-to-plan "what is syncthing" --dry-run
assert_rc 0 "flow dry-run"
assert_contains "GATE" "dry-run marks gates"
: > "$SANDBOX/mock-calls.log"
run flow research-to-plan "what is syncthing"
assert_rc 3 "flow stops at the first gate"
FID=$(basename "$(latest_run_dir)")
assert_contains "GATE at step 2" "gate message"
assert_file "$(latest_run_dir)/research.md" "step output saved"
assert_eq "1" "$(mock_count)" "only the first step ran"
run status "$FID"
assert_contains "waiting-approval" "flow waits"
run approve "$FID" --step 5
assert_rc 2 "wrong --step is refused"
run approve "$FID" --step 2
assert_rc 3 "approve continues to the next gate"
assert_contains "GATE at step 4" "second gate"
assert_file "$(latest_run_dir)/plan-draft.md" "plan draft saved"
run approve "$FID"
assert_rc 0 "final approve finishes"
HF=$(glob1 "$(latest_run_dir)/handoff-5-*.md")
assert_file "$HF" "registration is a handoff file"
assert_file_has "$HF" "never executes" "handoff is marked as not executed"
assert_file_has "$HF" "plans/01-" "next plan number is computed from plans/ and plans/archived/ (empty here, so 01)"
assert_file_has "$(latest_run_dir)/run.md" "status: done" "flow is done"
assert_file_has "$(latest_run_dir)/run.md" "| handoff |" "handoff step is marked"
assert_eq "0" "$(ls "$MACH_MF_ROOT/plans" 2>/dev/null | wc -l | tr -d ' ')" "flow wrote nothing into plans/"
# reject mid-flow
run flow research-to-plan "second question"
FID=$(basename "$(latest_run_dir)")
run reject "$FID" "wrong question"
assert_rc 0 "reject a flow"
run approve "$FID"
assert_rc 2 "rejected flow cannot continue"
# issue-to-pr: outward steps are only handoffs
: > "$SANDBOX/mock-calls.log"
run flow issue-to-pr "ENG-79 normalise dates"
assert_rc 3 "issue-to-pr gate"
FID=$(basename "$(latest_run_dir)")
run approve "$FID"; run approve "$FID"; assert_rc 0 "issue-to-pr finishes"
I2P=$(latest_run_dir)
assert_file_has "$(glob1 "$I2P/handoff-2-*.md")" "eng-79-normalise-dates" "branch name follows the ticket convention"
assert_file_has "$(ls "$I2P"/handoff-*.md | tail -n 1)" "[ENG-79]" "PR title format"
assert_file_has "$(ls "$I2P"/handoff-*.md | tail -n 1)" "mach never runs gh" "PR step is a handoff"
assert_eq "0" "$(mock_calls | grep -c 'gh ')" "no gh call"
# morning
: > "$SANDBOX/mock-calls.log"
run flow morning
assert_rc 1 "morning: drafts note falls back to the outbox on linux (warning)"
assert_contains "MOCK-OUTPUT from claude: -p Write a morning brief" "brief is shown on screen"
MD=$(ls -d "$MACH_RUNS_DIR"/2026/10/*morning* | head -n 1)
assert_file "$MD/brief.md" "brief.md in the run folder"
assert_file "$MD/health.md" "doctor output captured"
assert_eq "1" "$(ls "$MACH_MF_ROOT"/files/inbox/outbox/drafts | wc -l | tr -d ' ')" "brief queued for Drafts via the outbox" 2>/dev/null || true

# ===================== status / queue json
run status
assert_rc 0 "status"
run --json status
assert_json "status --json"
run --json queue
assert_json "queue --json"
run status nosuchrun
assert_rc 2 "unknown run id"
finish
