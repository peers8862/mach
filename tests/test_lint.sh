#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# Portability lint: bash 3.2 (macOS 12) and python 3.9 constructs, GNU-only flags, shellcheck, executable bits, no symlinks.
TEST_NAME=lint
. "$(dirname "$0")/lib.sh"
cd "$TEST_ROOT" || exit 2

# --- which files are bash? (shebang says bash/sh, or .sh extension)
BASH_FILES=""
for f in bin/mach lib/common.sh install.sh libexec/* tests/*.sh; do
  [ -f "$f" ] || continue
  if head -n 1 "$f" | grep -Eq '^#!.*(bash|/sh)'; then BASH_FILES="$BASH_FILES $f"; fi
done
[ -n "$BASH_FILES" ] && pass || flunk "no bash files found"

# the lint skips itself: its own patterns would match
SCAN=""
for f in $BASH_FILES; do [ "$f" = "tests/test_lint.sh" ] || SCAN="$SCAN $f"; done

check() { # check <regex> <message>
  local hits
  # shellcheck disable=SC2086
  hits=$(grep -nE -- "$1" $SCAN 2>/dev/null | grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' || true)
  if [ -z "$hits" ]; then pass; else flunk "$2: $(printf '%s' "$hits" | head -n 3 | tr '\n' '|')"; fi
}

check 'declare[[:space:]]+-[a-zA-Z]*A|local[[:space:]]+-[a-zA-Z]*A|typeset[[:space:]]+-[a-zA-Z]*A' "associative arrays are bash 4+"
check '(^|[^[:alnum:]_])(mapfile|readarray)([[:space:]]|$)' "mapfile/readarray are bash 4+"
check '\$\{[A-Za-z_][A-Za-z0-9_]*(,,|\^\^|,|\^)[^}]*\}' "case-modifying expansions are bash 4+"
check '\|&' "|& is bash 4+"
check '(^|[^[:alnum:]_])coproc([[:space:]]|$)' "coproc is bash 4+"
check '(declare|local)[[:space:]]+-[a-zA-Z]*n[[:space:]]' "namerefs are bash 4.3+"
check '\[\[[[:space:]]+-v[[:space:]]|\[[[:space:]]+-v[[:space:]]' "test -v is bash 4.2+"
check 'printf[[:space:]]+-v[[:space:]]+[A-Za-z_]+\[' "printf -v into array elements"
check ';;&|;&' "case fall-through terminators are bash 4+"
check '\$\{[A-Za-z_][A-Za-z0-9_]*\[-[0-9]' "negative array indexes are bash 4.3+"
check '&>>' "&>> is bash 4+"
check 'declare[[:space:]]+-g' "declare -g is bash 4.2+"
check 'shopt[[:space:]]+-s[[:space:]]+(globstar|lastpipe|autocd|dirspell)' "shopt options newer than 3.2"
check 'wait[[:space:]]+-n' "wait -n is bash 4.3+"
check 'readlink[[:space:]]+-f' "readlink -f is GNU only"
check 'sed[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*-i([[:space:]]|$)' "sed -i without a suffix is GNU only (use -i.bak)"
check 'date[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*-d([[:space:]]|$)|date[[:space:]].*--date' "date -d is GNU only"
check 'stat[[:space:]]+-c([[:space:]]|$)' "stat -c is GNU only"
check 'find[[:space:]].*-printf' "find -printf is GNU only"
check 'grep[[:space:]]+(-[a-zA-Z]*P|--perl)' "grep -P is GNU only"
check 'xargs[[:space:]]+-r([[:space:]]|$)' "xargs -r is GNU only"
check 'sort[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*-V' "sort -V is GNU only"
check 'date[[:space:]]+[^|;]*%N' "date %N is GNU only"
check '(^|[[:space:];|(])(cp|mv|ls)[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*--[a-z]' "long GNU options on cp/mv/ls"
check 'mktemp[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*--' "mktemp long options are GNU only"
check '(^|[[:space:]])local[[:space:]]+[A-Za-z_]+=\([^)]' "local array initialisation with a value list"

# --- empty arrays under `set -u` break on bash 3.2: any ${arr[@]} must use the guard ${arr[@]+"${arr[@]}"}
HITS=$(grep -nE '\$\{[A-Za-z_][A-Za-z0-9_]*\[[@*]\]\}|"\$\{[A-Za-z_][A-Za-z0-9_]*\[[@*]\]\}"' $SCAN 2>/dev/null | grep -v '\[@\]+' | grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' || true)
if [ -z "$HITS" ]; then pass; else flunk "unguarded array expansion (breaks on 3.2 with set -u): $(printf '%s' "$HITS" | head -n 3 | tr '\n' '|')"; fi

# --- bash syntax parses in posix-ish mode where possible, and `bash -n` passes for every bash file
for f in $BASH_FILES; do
  if bash -n "$f" 2>/dev/null; then pass; else flunk "bash -n failed: $f"; fi
done

# --- python: syntax must be valid for 3.9 (no match statements, no parenthesised with-items, no X | Y annotations)
PYFILES=""
for f in lib/*.py tests/*.py libexec/*; do
  [ -f "$f" ] || continue
  case "$f" in *.py) PYFILES="$PYFILES $f" ;; *) head -n 1 "$f" | grep -q python && PYFILES="$PYFILES $f" ;; esac
done
for f in $PYFILES; do
  if python3 - "$f" <<'EOF' 2>/dev/null
import ast, sys
src = open(sys.argv[1], encoding="utf-8").read()
ast.parse(src, filename=sys.argv[1], feature_version=(3, 9))
EOF
  then pass; else flunk "python 3.9 syntax check failed: $f"; fi
done
# shellcheck disable=SC2086
PYHITS=$(grep -nE '^[[:space:]]*match[[:space:]].*:[[:space:]]*$|:[[:space:]]*[A-Za-z_\[\]]+[[:space:]]*\|[[:space:]]*None|->[[:space:]]*[A-Za-z_\[\]]+[[:space:]]*\|[[:space:]]*None|zip\(.*strict=|^from datetime import UTC' $PYFILES 2>/dev/null | grep -v 'test_lint' | grep -vE 'try:|except ImportError' || true)
# tomllib is allowed only inside a try/except ImportError (it is 3.11+)
TOMLHITS=$(grep -n 'import tomllib' $PYFILES | while IFS=: read -r f ln _; do prev=$((ln - 1)); sed -n "${prev}p" "$f" | grep -q 'try:' || echo "$f:$ln"; done)
if [ -z "$PYHITS" ] && [ -z "$TOMLHITS" ]; then pass; else flunk "python 3.10+ construct: $PYHITS $TOMLHITS"; fi
# python files must not depend on third-party modules
THIRD=$(grep -nE '^(import|from)[[:space:]]+(yaml|requests|openpyxl|numpy|pandas|toml|tomli|click|typer)\b' $PYFILES 2>/dev/null | grep -v 'test_' || true)
if [ -z "$THIRD" ]; then pass; else flunk "third-party import in mach code: $THIRD"; fi

# --- shellcheck (when installed)
if command -v shellcheck >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  OUTSC=$(shellcheck -s bash $BASH_FILES 2>&1); RCS=$?
  if [ "$RCS" = 0 ]; then pass; else flunk "shellcheck: $(printf '%s' "$OUTSC" | head -n 12 | tr '\n' '|')"; fi
else
  printf '  note: shellcheck not installed, skipped\n'
fi

# --- executable bits and the shebangs
for f in bin/mach install.sh libexec/*; do
  [ -f "$f" ] || continue
  case "$f" in *.sh|*.py|bin/*|libexec/*|install.sh) [ -x "$f" ] && pass || flunk "not executable: $f" ;; esac
  head -n 1 "$f" | grep -Eq '^#!/usr/bin/env (bash|python3)$|^#!/bin/bash$' && pass || flunk "shebang: $f ($(head -n 1 "$f"))"
done

# --- every libexec command (no dot in the name) has the help header the dispatcher needs
for f in libexec/*; do
  case "$f" in *.*) continue ;; esac
  grep -q '^# mach-summary: ' "$f" && grep -q '^# mach-usage: ' "$f" && grep -q '^# mach-group: ' "$f" && pass || flunk "missing mach-summary/usage/group header: $f"
done

# --- no personal data in the publishable files (no home paths, IPs, emails, tokens, Syncthing device IDs)
# Gitignored personal files (config/*.local.*) are exempt. Placeholder users (x, someone, user, you, name, example) and sandbox `$SANDBOX/home/...` paths are allowed.
PUBLISH="README.md CHANGELOG.md docs config bin lib libexec flows install.sh tests tools .gitignore"
PERS=$(grep -rInE --exclude='*.local.*' '/(home|Users)/[a-z][a-z0-9_.-]*|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|[A-Z0-9]{7}-[A-Z0-9]{7}-[A-Z0-9]{7}-[A-Z0-9]{7}-|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}' $PUBLISH 2>/dev/null | grep -vE '127\.0\.0\.1|tests/test_lint\.sh|noreply@|/(home|Users)/(x|someone|user|you|name|example|machine-flows|svc)\b|/(home|Users)/\||/(home|Users)/\.\.\.' || true)
if [ -z "$PERS" ]; then pass; else flunk "personal data in publishable files: $(printf '%s' "$PERS" | head -n 3 | tr '\n' '|')"; fi
# --- standalone: tests never read the real machine-flows tree or the real $HOME (a clean clone of mach alone must pass)
# They use tests/fixtures/ and the sandbox only. Flag the usual ways of reaching outside the repository.
OUTSIDE=$(grep -rnE 'REAL_HOME[^ ]*/machine-flows|expanduser\("~"\)[^)]*machine-flows|ROOT\.parent|parents\[2\]|dirname "\$TEST_ROOT"|\$TEST_ROOT/\.\.|/machine-flows/(ai-authored|drafts|subsystems|service-settings|inventory|plans)/' tests --include='*.sh' --include='*.py' 2>/dev/null | grep -v 'tests/test_lint\.sh' | grep -vE '~/machine-flows/|MACH_MF_ROOT|\$MF' || true)
if [ -z "$OUTSIDE" ]; then pass; else flunk "a test reads outside the repository (use tests/fixtures): $(printf '%s' "$OUTSIDE" | head -n 3 | tr '\n' '|')"; fi
# the personal docs-history module must be gitignored
grep -qxF 'config/docs-history.local.py' .gitignore && grep -qxF 'config/*.local.*' .gitignore && pass || flunk ".gitignore lacks the config/*.local.* entries"
[ -f config/docs-history.example.py ] && pass || flunk "config/docs-history.example.py is missing"

# --- tests can never reach a real side-effecting program
# (1) the sandbox pins every external command into itself; (2) lib.sh and CMD_VARS list the same variables;
# (3) lib/ and libexec/ never run those programs by bare name (they go through mach_common.cmd / ext_cmd).
new_sandbox
assert_sandbox_hermetic
ENVSET=$(python3 - <<'PYEOF'
import re, sys
sys.path.insert(0, "lib")
import mach_common as mc
lib = open("tests/lib.sh").read()
shell = set(re.findall(r"\b(MACH_[A-Z_]+):", lib.split("EXTERNAL_CMD_VARS=", 1)[1].split("sandbox_external_commands()", 1)[0]))
print("same" if shell == set(mc.CMD_VARS.values()) else "differ: %s" % sorted(shell ^ set(mc.CMD_VARS.values())))
PYEOF
)
assert_eq "same" "$ENVSET" "tests/lib.sh EXTERNAL_CMD_VARS matches CMD_VARS in lib/mach_common.py"
# a missing sandbox path must read as "not available", even if the real program exists on the machine
OUT=$(MACH_OPEN_CMD="$SANDBOX/bin/no-such-open" python3 -c 'import sys; sys.path.insert(0, "lib"); import mach_common as mc; print(mc.which(mc.cmd("open")))'); assert_eq "None" "$OUT" "a missing sandbox opener is not found (no fallback to the real open)"
BARE=$(grep -nE '(run_capture|subprocess\.(run|Popen|call|check_output)|which)\(\[?"(open|drafts|osascript|tmux|launchctl|systemctl|crontab|ssh|claude|codex|cursor-agent|kiro-cli|grokcli-agent)"' lib/*.py libexec/mach-* 2>/dev/null | grep -v 'lib/mach_common.py' || true)
if [ -z "$BARE" ]; then pass; else flunk "outside program run by bare name (use mc.cmd): $(printf '%s' "$BARE" | head -n 3 | tr '\n' '|')"; fi
BARE_SH=$(grep -nE '^[^#]*(^|[;&|(]|\$\()[[:space:]]*(open|osascript|drafts|launchctl|crontab)[[:space:]]' libexec/*.sh libexec/mach-onboard libexec/mach-inventory libexec/mach-names libexec/mach-mcp 2>/dev/null || true)
[ -z "$BARE_SH" ] && pass || flunk "bash helper runs an outside program by bare name: $(printf '%s' "$BARE_SH" | head -n 3 | tr '\n' '|')"
finish
