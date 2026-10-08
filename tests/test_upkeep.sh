#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# names, inventory, docs, mcp, install, onboard (all with fixtures and mock scripts; nothing touches the real home).
TEST_NAME=upkeep
. "$(dirname "$0")/lib.sh"
new_sandbox
BIN="$MACH_BIN_DIR"

# ============================================================ names
touch "$BIN/cursor-agent"; chmod +x "$BIN/cursor-agent"
run names
assert_rc 0 "names: clean state"
assert_contains "no 'agent' on PATH" "names: clean"
ln -s cursor-agent "$BIN/agent"
run names
assert_rc 1 "names: bare agent is a problem"
assert_contains "bare agent" "names: reports it"
run names --fix
assert_rc 1 "names --fix is a preview"
assert_contains "remove symlink" "names: shows the plan"
assert_contains "preview only" "names: says preview"
[ -L "$BIN/agent" ] && pass || flunk "names --fix must not remove anything without --apply"
mkdir -p "$HOME/.grok/bin"; touch "$HOME/.grok/bin/grok"; chmod +x "$HOME/.grok/bin/grok"
ln -s ../downloads/grok "$HOME/.grok/bin/agent"
run names --fix --apply
assert_contains "removed" "names --apply removes"
[ -L "$BIN/agent" ] && flunk "names --apply left the bare agent link" || pass
[ -L "$HOME/.grok/bin/agent" ] && flunk "names --apply left ~/.grok/bin/agent" || pass
[ -L "$BIN/grokcli-agent" ] && pass || flunk "names --apply should create grokcli-agent"
BK=$(ls -d "$MACH_STAGING"/backups/*-mach-names | head -n 1)
assert_file "$BK/removed-links.tsv" "names: removed targets recorded"
assert_file_has "$BK/removed-links.tsv" "cursor-agent" "names: record has the target"
assert_contains "rollback: bash" "names: prints a one-line rollback"
assert_contains "rollback: bash ~/" "names: rollback hint uses an unescaped ~/"
assert_not_contains '\~' "names: rollback hint has no escaped tilde"
bash "$BK/rollback.sh"
[ -L "$BIN/agent" ] && [ "$(readlink "$BIN/agent")" = "cursor-agent" ] && pass || flunk "names: rollback restores the link"
run names --fix --apply
run names
assert_rc 0 "names: clean again"

# ============================================================ inventory
SCRIPTS="$MACH_MF_ROOT/scripts"; mkdir -p "$SCRIPTS" "$MACH_MF_ROOT/inventory/linux-box/raw"
for f in 00-summary.md 70-services-network.md 75-custom-startup-services.md 76-custom-scheduled-jobs.md; do printf 'old %s\n' "$f" > "$MACH_MF_ROOT/inventory/linux-box/$f"; done
printf 'raw old\n' > "$MACH_MF_ROOT/inventory/linux-box/raw/ports.txt"
printf 'host,csv\n' > "$MACH_MF_ROOT/inventory/linux-box/docs-index.csv"
printf 'README keep me\n' > "$MACH_MF_ROOT/inventory/README.md"
cat > "$SCRIPTS/inventory-linux.sh" <<'EOF'
#!/usr/bin/env bash
# mock generator: writes OUT/<hostname -s>/... like the real one, and a README.md at the root
OUT=${1:?}; H=$(hostname -s); mkdir -p "$OUT/$H/raw"
echo "new summary" > "$OUT/$H/00-summary.md"
echo "services new" > "$OUT/$H/70-services-network.md"
echo "raw new" > "$OUT/$H/raw/ports.txt"
echo "must not be copied" > "$OUT/$H/75-custom-startup-services.md"
echo "generated readme" > "$OUT/README.md"
echo "SKIP_SIZES=${SKIP_SIZES:-} SKIP_NET=${SKIP_NET:-}" >> "$OUT/$H/raw/env.txt"
EOF
chmod +x "$SCRIPTS/inventory-linux.sh"
run inventory --host mac-laptop
assert_rc 2 "inventory refuses another host"
assert_contains "refusing --host mac-laptop" "inventory: says why"
run inventory
assert_rc 0 "inventory preview"
assert_contains "changed" "inventory: diff summary"
assert_contains "00-summary.md" "inventory: lists changed files"
assert_contains "preview only" "inventory: preview"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/00-summary.md" "old 00-summary.md" "inventory: preview writes nothing"
run inventory --section 70
assert_contains "section: 70" "inventory: section filter"
assert_not_contains "00-summary.md" "inventory: section filter hides other files"
run inventory --apply
assert_rc 0 "inventory apply"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/00-summary.md" "new summary" "inventory: written"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/75-custom-startup-services.md" "old 75-custom-startup-services.md" "inventory: never touches the hand-maintained 75 file"
assert_file_has "$MACH_MF_ROOT/inventory/README.md" "README keep me" "inventory: never copies the generated README"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/raw/env.txt" "SKIP_SIZES= SKIP_NET=" "inventory: full run by default on Linux"
assert_contains "rollback: bash" "inventory: rollback line"
BK=$(ls -d "$MACH_STAGING"/backups/*-mach-inventory | head -n 1)
assert_file_has "$BK/rollback.sh" "00-summary.md" "inventory: rollback script lists the files"
bash "$BK/rollback.sh"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/00-summary.md" "old 00-summary.md" "inventory: rollback restores"
assert_no_file "$MACH_MF_ROOT/inventory/linux-box/raw/env.txt" "inventory: rollback removes created files"
assert_eq "0" "$(find "$MACH_STAGING/tmp" -mindepth 1 -maxdepth 1 -name 'mach.*' 2>/dev/null | wc -l | tr -d ' ')" "inventory: temp folder is cleaned up"
run inventory --apply; run inventory
assert_contains "identical" "inventory: counts identical files"
run inventory --light --section raw/env --diff
assert_contains "SKIP_SIZES=1 SKIP_NET=1" "inventory: --light skips the heavy parts"
cp "$SCRIPTS/inventory-linux.sh" "$SCRIPTS/inventory-macos.sh"
MACH_OS=darwin run inventory --section raw/env --diff
assert_contains "SKIP_SIZES=1 SKIP_NET=1" "inventory: macOS is light by default (no heavy scans on the Mac)"
MACH_OS=darwin run inventory --full --section raw/env --diff
assert_not_contains "SKIP_SIZES=1" "inventory: --full overrides the light default"

# ============================================================ docs (collector and builder are mocks)
mkdir -p "$MACH_MF_ROOT/inventory/mac-laptop"
cat > "$SANDBOX/collect-mock.py" <<'EOF'
import os, sys
preview = "--preview" in sys.argv
root = os.environ.get("MACH_DOCS_OUT") or os.path.join(os.environ["MACH_MF_ROOT"], "inventory")
for h in ("linux-box", "mac-laptop"):
    os.makedirs(os.path.join(root, h), exist_ok=True)
    with open(os.path.join(root, h, "docs-index.csv"), "w") as fh:
        fh.write("machine,path,name,kind,area,scope,purpose,created,modified,created_by,status,retired_date,replaced_by,notes\n")
        fh.write("%s,~/machine-flows/new-%s.md,n,doc,a,s,p,c,m,x,active,,,\n" % (h, h))
with open(os.path.join(os.environ["MACH_STAGING"], "collect-calls.txt"), "a") as fh:
    fh.write("preview=%s nobackup=%s\n" % (preview, os.environ.get("MACH_DOCS_NO_BACKUP")))
EOF
export MACH_DOCS_COLLECT="$SANDBOX/collect-mock.py"
printf 'machine,path,name,kind,area,scope,purpose,created,modified,created_by,status,retired_date,replaced_by,notes\ndeb,~/machine-flows/old.md,o,doc,a,s,p,c,m,x,active,,,\n' > "$MACH_MF_ROOT/inventory/linux-box/docs-index.csv"
run docs
assert_rc 0 "docs preview"
assert_contains "added 1, removed 1" "docs: row diff"
assert_contains "+ ~/machine-flows/new-linux-box.md" "docs: lists the new row"
assert_contains "preview only" "docs: preview"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/docs-index.csv" "old.md" "docs: preview writes nothing"
assert_file_has "$MACH_STAGING/collect-calls.txt" "preview=True" "docs: collector was run in preview mode"
run docs --apply
assert_rc 0 "docs apply"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/docs-index.csv" "new-linux-box.md" "docs: CSV written"
assert_file_has "$MACH_STAGING/collect-calls.txt" "preview=False nobackup=1" "docs: apply uses mach's own backup"
assert_contains "workbook is NOT rebuilt" "docs: workbook untouched"
assert_contains "rollback: bash" "docs: rollback line"
BK=$(ls -d "$MACH_STAGING"/backups/*-mach-docs | head -n 1)
bash "$BK/rollback.sh"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/docs-index.csv" "old.md" "docs: rollback restores the CSV"
run docs --apply; run docs
assert_contains "up to date" "docs: idempotent"
MACH_HOST=mac-laptop run docs
assert_rc 2 "docs collect is linux-box-only (single writer)"
unset MACH_DOCS_COLLECT
# build: wraps scripts/docs-index-build.py; only with --apply
cat > "$SCRIPTS/docs-index-build.py" <<'EOF'
import sys
out = sys.argv[sys.argv.index("--out") + 1]
open(out, "w").write("xlsx-mock " + " ".join(a for a in sys.argv[1:] if a.endswith(".csv")))
EOF
if python3 -c 'import openpyxl' 2>/dev/null; then HAVE_OPENPYXL=1; else HAVE_OPENPYXL=0; fi
if [ "$HAVE_OPENPYXL" = 0 ]; then
  run docs build
  assert_rc 2 "docs build without openpyxl explains itself"
  assert_contains "openpyxl" "docs build: names the missing module"
  export MACH_SKIP_OPENPYXL_CHECK=1      # test knob: the build script below is a mock that needs no openpyxl
fi
if true; then
  run docs build
  assert_rc 0 "docs build preview"
  assert_contains "preview only" "docs build: preview"
  assert_no_file "$MACH_MF_ROOT/inventory/docs-index.xlsx" "docs build: nothing written without --apply (rule 10)"
  run docs build --apply
  assert_rc 0 "docs build apply"
  assert_file_has "$MACH_MF_ROOT/inventory/docs-index.xlsx" "xlsx-mock" "docs build: workbook written only on explicit request"
fi
unset MACH_SKIP_OPENPYXL_CHECK
MACH_OS=linux run docs macstat
assert_rc 2 "macstat is mac-only"

# ============================================================ mcp (wraps scripts/mcp-apply.sh)
cat > "$SCRIPTS/mcp-apply.sh" <<'EOF'
#!/usr/bin/env bash
echo "mcp-apply called: $*" >> "$MACH_STAGING/mcp-calls.txt"
echo "## dry-run for $*"
for a in "$@"; do if [ "$a" = "--apply" ]; then exit "${MOCK_MCP_APPLY_RC:-3}"; fi; done
exit 0
EOF
run mcp render
assert_rc 0 "mcp render"
assert_contains "## dry-run for --tool all --machine linux-box" "mcp: all tools, this machine"
run mcp render --tool cursor-agent
assert_contains "--tool cursor --machine linux-box" "mcp: cursor-agent maps to the cursor target"
run mcp render --tool grokcli-agent
assert_rc 0 "mcp: grokcli-agent"
assert_contains "no MCP target" "mcp: explains grokcli-agent"
run mcp render --tool nope
assert_rc 2 "mcp: unknown tool"
run mcp apply --tool claude
assert_rc 0 "mcp apply previews first"
assert_contains "preview only" "mcp: says preview"
assert_file_lacks "$MACH_STAGING/mcp-calls.txt" "--apply" "mcp: --apply is not passed without --apply"
run mcp apply --tool claude --apply
assert_rc 1 "mcp apply: the stub is reported honestly (exit 1)"
assert_contains "documented stub" "mcp: stub message"
MOCK_MCP_APPLY_RC=0 run mcp apply --tool claude --apply
assert_rc 0 "mcp apply passes through when the script applies"
MOCK_MCP_APPLY_RC=7 run mcp apply --tool claude --apply
assert_rc 2 "mcp apply: script failure is a failure"

# ============================================================ install.sh
INST="$TEST_ROOT/install.sh"
rm -rf "$SANDBOX/ibin"; IB="$SANDBOX/ibin"
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" 2>&1); RC=$?
assert_rc 0 "install preview"; assert_contains "would create link" "install: preview text"; assert_contains "preview only" "install: preview"
[ -e "$IB/mach" ] && flunk "install preview created the link" || pass
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" --apply 2>&1); RC=$?
assert_rc 0 "install --apply"
[ -L "$IB/mach" ] && [ "$(readlink "$IB/mach")" = "$TEST_ROOT/bin/mach" ] && pass || flunk "install: link target"
OUT=$("$IB/mach" --version 2>&1); RC=$?; assert_rc 0 "installed link works"; assert_contains "mach $(cat "$TEST_ROOT/VERSION")" "installed link runs"
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" --apply 2>&1); RC=$?
assert_rc 0 "install is idempotent"; assert_contains "already installed" "install: idempotent message"
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" --uninstall 2>&1); RC=$?
assert_rc 0 "uninstall preview"; [ -L "$IB/mach" ] && pass || flunk "uninstall preview must not remove"
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" --uninstall --apply 2>&1); RC=$?
assert_rc 0 "uninstall --apply"; [ -e "$IB/mach" ] || [ -L "$IB/mach" ] && flunk "uninstall left the link" || pass
printf 'not a link\n' > "$IB/mach"
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" --apply 2>&1); RC=$?
assert_rc 2 "install refuses to replace a regular file"; assert_contains "not a symlink" "install: says why"
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" --uninstall --apply 2>&1); RC=$?
assert_rc 2 "uninstall refuses a regular file"
rm -f "$IB/mach"; ln -s /somewhere/else "$IB/mach"
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" --uninstall --apply 2>&1); RC=$?
assert_rc 2 "uninstall refuses a link to another checkout"
OUT=$(MACH_BIN_DIR="$IB" bash "$INST" --apply 2>&1); RC=$?
assert_rc 0 "install replaces a stale link (with a recorded backup)"
assert_contains "rollback: bash" "install: rollback line"
# the repository itself holds no symlinks (plan 00: none inside machine-flows)
SYML=$(find "$TEST_ROOT" -type l -not -path "$TEST_ROOT/.tmp/*" -not -path "$TEST_ROOT/.git/*" | wc -l | tr -d ' ')
assert_eq "0" "$SYML" "no symlinks inside the mach repo"

# ============================================================ onboard
run onboard --skip-previews
case "$RC" in 0|1) pass ;; *) flunk "onboard exit $RC: $OUT" ;; esac
assert_contains "1. Prerequisites" "onboard: prerequisites section"
assert_contains "Syncthing pairing" "onboard: pairing text"
assert_contains "would create link" "onboard: previews the link"
[ -e "$BIN/mach" ] && flunk "onboard without --apply must not link" || pass
run onboard --skip-previews --apply
[ -L "$BIN/mach" ] && pass || flunk "onboard --apply creates the link"
run onboard
assert_contains "-- mach inventory" "onboard: runs the inventory preview"
assert_contains "-- mach names" "onboard: runs names"
assert_contains "-- mach ai apply" "onboard: runs ai apply preview"
assert_contains "-- mach mcp render" "onboard: runs mcp render"
assert_file_has "$MACH_MF_ROOT/inventory/linux-box/00-summary.md" "new summary" "onboard previews write nothing (file is as the last --apply left it)"
finish
