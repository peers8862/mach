#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# mach doctor: runs, exits 0/1/2 (never crashes), valid JSON, and each check reacts to a fixture.
TEST_NAME=doctor
. "$(dirname "$0")/lib.sh"
new_sandbox
MF="$MACH_MF_ROOT"

rc_ok() { case "$RC" in 0|1|2) pass ;; *) flunk "$1: exit $RC (want 0/1/2): $(printf '%s' "$OUT" | head -n 5 | tr '\n' '|')" ;; esac; }

# --- empty sandbox: does not crash, finishes quickly, JSON is valid
START=$(date +%s)
run doctor
rc_ok "doctor on an empty tree"
assert_contains "doctor linux-box:" "summary line"
END=$(date +%s)
if [ $((END - START)) -le 15 ]; then pass; else flunk "doctor took $((END - START))s (limit 15)"; fi
run_split doctor --json
rc_ok "doctor --json"
assert_json "doctor --json"
assert_eq "linux-box" "$(json_get 'd["host"]')" "json host"
assert_contains '"checks"' "json has checks"
assert_eq "$RC" "$(json_get 'd["exit"]')" "json exit matches the process exit"
run doctor --quiet
rc_ok "doctor --quiet"
assert_not_contains "OK    config" "quiet hides OK lines"
run --json doctor
assert_json "global --json before the command"

# --- syncthing service: mock systemctl says inactive -> FAIL -> exit 2
cat > "$SANDBOX/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
case "$*" in *is-active*) echo inactive; exit 3 ;; esac
exit 0
EOF
run doctor
assert_rc 2 "inactive syncthing is a FAIL"
assert_contains "FAIL  syncthing-service" "says which check"
cat > "$SANDBOX/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
case "$*" in *is-active*) echo active; exit 0 ;; esac
exit 0
EOF
run doctor
assert_not_contains "FAIL  syncthing-service" "active syncthing is fine"
assert_contains "OK    syncthing-service" "service ok"

# --- hygiene: symlinks, secrets-guard names, conflicts (names only), pruned dirs
printf '// machine-flows: shared Syncthing ignore patterns\n// --- secrets guard: never sync credentials ---\n(?i)*.env\n*.pem\nid_rsa*\n**/credentials*.json\n\n// --- OS junk\n.DS_Store\n' > "$MF/.stglobalignore"
mkdir -p "$MF/a/node_modules/x" "$MF/b"
touch "$MF/real.md"
run doctor
assert_contains "OK    mf-hygiene  no symlinks inside machine-flows" "clean tree"
ln -s real.md "$MF/b/link.md"
printf 'x\n' > "$MF/b/Prod.ENV"; printf 'x\n' > "$MF/b/credentials-x.json"; printf 'x\n' > "$MF/b/notes.sync-conflict-20261008-abc.md"
ln -s ../real.md "$MF/a/node_modules/x/ignored-link"
run doctor
assert_rc 2 "symlink / secret-looking names are FAIL"
assert_contains "1 symlink(s) inside machine-flows: b/link.md" "symlink reported by path"
assert_not_contains "ignored-link" "node_modules is not scanned"
assert_contains "2 file name(s) match the secrets guard (names only)" "secrets-guard count"
assert_contains "b/Prod.ENV" "secrets-guard names the .ENV file"
assert_contains "b/credentials-x.json" "secrets-guard names the credentials file"
# lists are sorted case-insensitively by path, so the order is the same on ext4 and APFS
assert_contains "b/credentials-x.json, b/Prod.ENV" "secrets-guard names are sorted (case-insensitive)"
assert_contains "WARN  sync-conflicts" "conflict files warn"
assert_not_contains "x
" "contents are never printed"
rm -rf "$MF/b"

# --- outbox older than 24h
mkdir -p "$MF/files/inbox/outbox/drafts"
printf 'x\n' > "$MF/files/inbox/outbox/drafts/old.md"
touch -t 202610070900 "$MF/files/inbox/outbox/drafts/old.md"
run doctor
assert_rc 1 "old outbox item warns"
assert_contains "WARN  outbox  1 outbox item(s) older than 24h" "outbox warning"
rm -f "$MF/files/inbox/outbox/drafts/old.md"

# --- plans with every box ticked -> INFO "propose archiving"; open ones are fine
mkdir -p "$MF/plans"
printf '# 00\n- [x] a\n' > "$MF/plans/00-master.md"
printf '# 04\n- [x] a\n- [x] b\n' > "$MF/plans/04-done.md"
printf '# 05\n- [x] a\n- [ ] b\n' > "$MF/plans/05-open.md"
run doctor
assert_contains "INFO  plans  plan 04 has all 2 box(es) ticked: propose archiving" "archive proposal"
assert_not_contains "plan 00 has all" "plan 00 is never proposed"
assert_not_contains "plan 05 has all" "open plans are not proposed"

# --- caps: AGENTS.md > 130 lines, lessons INDEX > 300 lines, proposed > 30
mkdir -p "$MF/ai-authored" "$MF/service-memories/lessons"
i=0; : > "$MF/ai-authored/AGENTS.md"; while [ $i -lt 140 ]; do echo "rule $i" >> "$MF/ai-authored/AGENTS.md"; i=$((i + 1)); done
i=0; : > "$MF/service-memories/lessons/INDEX.md"; while [ $i -lt 320 ]; do echo "- [proposed] lesson $i" >> "$MF/service-memories/lessons/INDEX.md"; i=$((i + 1)); done
run doctor
assert_contains "WARN  ai-memory-caps  ai-authored/AGENTS.md: 140 lines (cap 130)" "AGENTS.md cap"
assert_contains "WARN  ai-memory-caps  lessons/INDEX.md: 320 lines (cap 300)" "INDEX cap"
assert_contains "WARN  ai-memory-caps  proposed lessons: 320 (cap 30)" "proposed cap"
printf '[doctor]\nagents_max_lines = 500\n' > "$MACH_CONFIG_DIR/config.toml"
run doctor
assert_contains "OK    ai-memory-caps  ai-authored/AGENTS.md: 140 lines (cap 500)" "caps are configurable"
rm -f "$MACH_CONFIG_DIR/config.toml"

# --- CLI names
touch "$HOME/.local/bin/cursor-agent"
ln -s cursor-agent "$HOME/.local/bin/agent"
run doctor
assert_contains "WARN  cli-names  bare \`agent\` exists: ~/.local/bin/agent" "bare agent"
rm -f "$HOME/.local/bin/agent" "$HOME/.local/bin/cursor-agent"
run doctor
assert_contains "WARN  cli-names  missing: cursor-agent" "cursor-agent missing"

# --- 75/76 presence
mkdir -p "$MF/inventory/linux-box"
run doctor
assert_contains "WARN  startup-index  missing: inventory/linux-box/75-custom-startup-services.md" "75 missing"
printf '| Name | a | b | c | d |\n| --- | --- | --- | --- | --- |\n| x | y | z | w | active |\n' > "$MF/inventory/linux-box/75-custom-startup-services.md"
printf '| Name | a | b | c | d | e | f | g |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| `job` | c | d | e | f | g | active | h |\n' > "$MF/inventory/linux-box/76-custom-scheduled-jobs.md"
run doctor
assert_contains "OK    startup-index" "75 present"
assert_contains "OK    jobs-index" "76 present"

# --- syncthing version parity from inventory (no binary is run)
mkdir -p "$MF/inventory/mac-laptop"
printf '| Version | syncthing v2.1.5 "Hafnium Hornet" (go1.27.1) |\n' > "$MF/inventory/linux-box/70-services-network.md"
printf '| Version | syncthing v2.1.6 "Hafnium Hornet" (go1.27.1) |\n' > "$MF/inventory/mac-laptop/70-services-network.md"
run doctor
assert_contains "WARN  syncthing-version  versions differ: linux-box=2.1.5, mac-laptop=2.1.6" "version mismatch"
printf '| Version | syncthing v2.1.5 "Hafnium Hornet" |\n' > "$MF/inventory/mac-laptop/70-services-network.md"
run doctor
assert_contains "OK    syncthing-version  same version everywhere (2.1.5" "same version"

# --- Grok Bot (plan 07): reads daemon.json / supervisor.json / log only
G="$HOME/.grokbot"; mkdir -p "$G"
NOW_MS=$(python3 -c 'import time; print(int(time.time()*1000))')
printf '{"pid": 999999, "servingAt": %s}' "$NOW_MS" > "$G/local-exec-daemon.json"
printf '{"pid": 1, "at": %s}' "$NOW_MS" > "$G/local-exec-supervisor.json"
printf 'started (pid 999999); serving\n' > "$G/local-exec-daemon.log"
run doctor
assert_rc 2 "dead daemon pid is a FAIL"
assert_contains "daemon pid 999999 is not running: click into Grok Bot on this machine" "dead pid message"
printf '{"pid": %s, "servingAt": %s}' "$$" "$NOW_MS" > "$G/local-exec-daemon.json"
run doctor
assert_contains "OK    grokbot  daemon pid $$ alive" "live pid"
assert_contains "OK    grokbot  supervisor heartbeat" "fresh heartbeat"
assert_contains "OK    grokbot  no 'watch stream failed' since the last daemon start" "log clean"
printf 'started (pid 1)\n[x] watch stream failed: ConnectError\n[x] watch stream failed: ConnectError\n' > "$G/local-exec-daemon.log"
run doctor
assert_contains "WARN  grokbot  2 'watch stream failed' line(s) since the last daemon start" "errors after the last start"
printf '[x] watch stream failed: ConnectError\nstarted (pid 2)\n' > "$G/local-exec-daemon.log"
run doctor
assert_contains "no 'watch stream failed' since the last daemon start" "errors before the last start are history"
printf '{"pid": 1, "at": 1000}' > "$G/local-exec-supervisor.json"
run doctor
assert_contains "WARN  grokbot  supervisor heartbeat" "stale heartbeat"
printf '{"pid": %s}' "$$" > "$G/local-exec-daemon.json"
run doctor
assert_contains "no servingAt" "servingAt unset"
# credential files are never opened: make them unreadable and check doctor does not trip over them
printf 'zq-CREDVALUE-9' > "$G/local-exec-daemon-credential.json"; chmod 000 "$G/local-exec-daemon-credential.json"
printf 'zq-CREDVALUE-9' > "$G/local-exec-daemon-connection.json"; chmod 000 "$G/local-exec-daemon-connection.json"
run doctor
rc_ok "doctor with unreadable credential files"
assert_not_contains "zq-CREDVALUE-9" "no credential text in the output"
assert_not_contains "credential" "credential files are not even mentioned"
chmod 600 "$G/local-exec-daemon-credential.json" "$G/local-exec-daemon-connection.json"

# --- disk and memory lines exist
run doctor
assert_contains "disk  home:" "disk line"
assert_contains "memory" "memory line"
# --- peer ssh: skipped by default; used when configured (mock ssh)
assert_contains "INFO  peer-reachability  skipped" "peer ssh skipped by default"
printf '#!/usr/bin/env bash\necho "ssh $*" >> "%s/ssh-calls.txt"\nexit 0\n' "$SANDBOX" > "$SANDBOX/bin/ssh"; chmod +x "$SANDBOX/bin/ssh"
MACH_PEER_SSH=mac-laptop run doctor
assert_contains "OK    peer-reachability  ssh to mac-laptop works" "peer ssh ok"
assert_file_has "$SANDBOX/ssh-calls.txt" "-o BatchMode=yes -o ConnectTimeout=3 mac-laptop true" "ssh is called non-interactively with a timeout"

# --- macOS branch (simulated): launchctl instead of systemctl
cat > "$SANDBOX/bin/launchctl" <<'EOF'
#!/usr/bin/env bash
echo "state = running"
exit 0
EOF
chmod +x "$SANDBOX/bin/launchctl"
cat > "$SANDBOX/bin/vm_stat" <<'EOF'
#!/usr/bin/env bash
echo "Mach Virtual Memory Statistics: (page size of 4096 bytes)"
echo "Pages free:                               100000."
echo "Pages inactive:                           200000."
echo "Pages speculative:                         50000."
EOF
chmod +x "$SANDBOX/bin/vm_stat"
MACH_OS=darwin run doctor
rc_ok "doctor on (simulated) macOS"
assert_contains "OK    syncthing-service  LaunchAgent net.syncthing.syncthing running" "launchctl check"
assert_contains "memory  1367 MiB available" "vm_stat based memory"
finish
