#!/usr/bin/env bash
# shellcheck disable=SC2034,SC1091,SC2012,SC2015,SC2016,SC2086,SC2088,SC2221,SC2222  # test scripts: intentional shortcuts
# mach sheets: lint, build, new, refresh, and the drift check on the committed docs/sheets set. Hermetic: sandbox HOME and MACH_* variables.
TEST_NAME=sheets
. "$(dirname "$0")/lib.sh"
new_sandbox
cd "$SANDBOX" || exit 2

# --- help and registration
run help sheets; assert_rc 0 "help sheets"; assert_contains "mach sheets refresh <set>" "usage lists refresh"
run help; assert_contains "sheets" "mach help lists sheets"
run sheets; assert_rc 2 "no verb is a usage error"
run sheets frobnicate x; assert_rc 2 "unknown verb"

# --- new: preview first, then --apply
run sheets new proj/tracker; assert_rc 0 "new previews"; assert_contains "create proj/tracker/index.csv" "preview names index.csv"; assert_contains "preview only" "preview says so"
assert_no_file proj/tracker "preview creates nothing"
run sheets new proj/tracker --apply; assert_rc 0 "new --apply"
assert_file proj/tracker/index.csv "index.csv scaffolded"; assert_file proj/tracker/README.md "README scaffolded"
assert_eq "id,file,sheet_name,title,description,owner,source,generated_by,updated,rows" "$(cat proj/tracker/index.csv)" "scaffold header is exactly the index columns"
assert_file_has proj/tracker/README.md "mach sheets build proj/tracker" "README names the build command"
assert_file_has proj/tracker/README.md "Edit the CSVs, never the workbook" "README states the source of truth"
run sheets new proj/tracker --apply; assert_rc 2 "new refuses an existing set"
run sheets lint proj/tracker; assert_rc 1 "an empty new set lints with a warning (no workbook yet)"; assert_contains "does not exist yet" "lint says build is next"

# --- a real set: two CSVs
cd proj/tracker || exit 2
printf 'id,name,status\n1,Write plan,open\n2,Ship it,"blocked, waiting"\n' > tasks.csv
printf 'who,role\nann,dev\n' > people.csv
printf 'id,file,sheet_name,title,description,owner,source,generated_by,updated,rows\n' > index.csv
printf 't,tasks.csv,Tasks,Tasks,,me,,,,\np,people.csv,People,People,,me,,,,\n' >> index.csv
run sheets lint .; assert_rc 2 "unbuilt rows/updated fail lint"; assert_contains "rows='' but the CSV has 2" "rows mismatch is explained"
run sheets build . --dry-run; assert_rc 0 "build --dry-run"; assert_contains "would change index.csv: tasks.csv rows (empty) -> 2" "dry-run reports the rows change"; assert_contains "dry-run: nothing written" "dry-run says nothing written"
assert_no_file tracker.xlsx "dry-run writes no workbook"
run sheets build .; assert_rc 0 "build"; assert_file tracker.xlsx "workbook named after the folder"
assert_contains "Index, Tasks, People" "build lists the sheets in order"
assert_file_has index.csv "2026-10-08,2" "index.csv got updated and rows"
run sheets lint .; assert_rc 0 "built set lints clean"; assert_contains "OK sheet set ." "lint OK line"
cp tracker.xlsx "$SANDBOX/first.xlsx"
run sheets build .; assert_rc 0 "second build"; assert_contains "up to date" "nothing to do"
cmp -s tracker.xlsx "$SANDBOX/first.xlsx" && pass || flunk "a rebuild must give identical bytes"
run --json sheets lint .; assert_json "lint --json"; assert_eq "0" "$(json_get 'len(d["results"])')" "no findings"

# updated moves only with content; another day, unchanged -> same date
export MACH_NOW="2026-10-20 09:30:00"
run sheets build .; assert_contains "up to date" "unchanged on a later day"
assert_file_has index.csv "tasks.csv,Tasks,Tasks,,me,,,2026-10-08,2" "updated stays for unchanged content"
sed -i.bak 's/Write plan,open/Write plan,done/' tasks.csv && rm tasks.csv.bak
run sheets lint .; assert_rc 2 "an edited cell makes the workbook stale"; assert_contains "changed after tracker.xlsx was built" "stale workbook noticed"
printf '3,More,open\n' >> tasks.csv
run sheets lint .; assert_rc 2 "edited CSV makes lint fail"; assert_contains "rows='2' but the CSV has 3" "row count noticed"
run sheets build .; assert_rc 0 "rebuild after edit"
assert_file_has index.csv "2026-10-20,3" "updated moves for the changed CSV"
assert_file_has index.csv "2026-10-08,1" "other CSV keeps its date"
run sheets lint .; assert_rc 0 "clean again"
export MACH_NOW="2026-10-08 09:30:00"

# the build backs up what it overwrites and offers a rollback
printf '4,Again,open\n' >> tasks.csv
run sheets build .; assert_contains "rollback: bash" "rollback hint printed"
glob1 "$MACH_STAGING/backups/*-mach-sheets" >/dev/null && pass || flunk "backup folder missing"

# --- lint rules that need the CLI
printf 'a,b\n1,2\n' > stray.csv
run sheets lint .; assert_rc 2 "orphan CSV fails"; assert_contains "stray.csv is not listed in index.csv (orphan)" "orphan named"
run sheets build .; assert_rc 2 "build refuses an orphan"; assert_contains "not built" "build says it did not build"
rm stray.csv
sed -i.bak 's/^p,people.csv,People/p,people.csv,Tasks/' index.csv && rm index.csv.bak
run sheets lint .; assert_rc 2 "duplicate sheet name fails"; assert_contains "repeats row" "duplicate named"
sed -i.bak 's/^p,people.csv,Tasks/p,people.csv,A name that is far too long for excel/' index.csv && rm index.csv.bak
run sheets lint .; assert_contains "Excel allows 31" "31 character limit"
sed -i.bak 's/^p,people.csv,A name that is far too long for excel/p,people.csv,Pe:ople/' index.csv && rm index.csv.bak
run sheets lint .; assert_contains "contains one of" "forbidden character"
sed -i.bak 's/^p,people.csv,Pe:ople/p,people.csv,People/' index.csv && rm index.csv.bak
rm people.csv
run sheets lint .; assert_rc 2 "missing listed file fails"; assert_contains "people.csv does not exist" "missing file named"
printf 'who,role\nann,dev\n' > people.csv
cd "$SANDBOX" || exit 2

# --- workbook name from sheets.toml
mkdir -p named; printf 'k,v\na,b\n' > named/data.csv
printf 'id,file,sheet_name,title,description,owner,source,generated_by,updated,rows\nd,data.csv,Data,,,,,,,\n' > named/index.csv
printf 'workbook = "report"\n' > named/sheets.toml
run sheets build named; assert_rc 0 "build with sheets.toml"; assert_file named/report.xlsx "workbook name from sheets.toml"
run sheets lint named; assert_rc 0 "named set lints clean"

# --- the generated mach set: refresh into a scratch folder, drift check, every source in the repo
run sheets refresh nonsense; assert_rc 2 "unknown generated set"
run sheets refresh mach --out gen; assert_rc 0 "refresh --out"; assert_file gen/commands.csv "commands.csv generated"; assert_file gen/COMMANDS-TABLE.md "table generated"
assert_file gen/templates.csv "templates.csv generated from the in-repo list"; assert_file gen/subsystem-units.csv "subsystem-units.csv generated from the example manifest"
assert_not_contains "skipped" "nothing is skipped: every source is in the repo"
run sheets refresh mach --out gen --check; assert_rc 0 "no drift right after refresh"; assert_contains "no drift" "says no drift"
run sheets refresh mach --out gen --dry-run; assert_contains "up to date" "second refresh changes nothing"
printf 'x\n' >> gen/commands.csv
run sheets refresh mach --out gen --check; assert_rc 1 "a changed CSV is drift"; assert_contains "DRIFT" "drift is listed"
run sheets refresh mach --out gen; assert_contains "write" "refresh repairs it"
run sheets refresh mach --out gen --check; assert_rc 0 "drift repaired"
printf 'a|b\n' >> gen/COMMANDS-TABLE.md
run sheets refresh mach --out gen --check; assert_rc 1 "a changed table is drift too"
run sheets refresh mach --out gen --build; assert_rc 0 "refresh --build"; assert_not_contains "skipped" "nothing skipped"
assert_file gen/mach.xlsx "workbook built next to the CSVs (name from sheets.toml)"
assert_file_has gen/templates.csv "~/machine-flows/ai-authored/templates/subsystem-setup.md,Describe a whole subsystem to scaffold,mach subsystem new <id> --from <file>" "template purpose and ingester"
assert_file_has gen/templates.csv "task-brief.md" "generic template listed"
assert_file_has gen/subsystem-units.csv "alpha,pillar,,grokbot:Example,example,alpha,false" "unit row with lead"
assert_file_has gen/subsystem-units.csv "beta,product,alpha,user,example,beta,true" "child unit with parent"
run sheets lint gen; assert_rc 0 "generated set lints clean"

# --- the committed set: lints clean, and matches what the code generates today
cd "$TEST_ROOT" || exit 2
run sheets lint docs/sheets; assert_rc 0 "committed docs/sheets lints clean"
run sheets refresh mach --check; assert_rc 0 "committed CSVs match the generated ones (run: mach sheets refresh mach)"
assert_not_contains "skipped" "nothing skipped"
assert_not_contains "DRIFT" "no drifting file"
# no absolute home paths anywhere in the committed set
if grep -rIE '/home/|/Users/' docs/sheets docs/COMMANDS-TABLE.md >/dev/null 2>&1; then flunk "absolute path in docs/sheets or COMMANDS-TABLE.md"; else pass; fi
UNZ="$SANDBOX/unz"; mkdir -p "$UNZ"
python3 -I - "$TEST_ROOT/docs/sheets/mach.xlsx" "$UNZ" <<'PYEOF' && pass || flunk "xlsx unzip"
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    z.extractall(sys.argv[2])
PYEOF
if grep -rE '/home/|/Users/' "$UNZ" >/dev/null 2>&1; then flunk "absolute path inside mach.xlsx"; else pass; fi
assert_file_has docs/COMMANDS-TABLE.md "## Flags" "table has the flags section"
finish
