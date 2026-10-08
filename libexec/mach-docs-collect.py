#!/usr/bin/env python3
"""Collect the machine-flows docs index (run on the collector machine; single writer).

Paths come from MACH_MF_ROOT / MACH_STAGING / MACH_STATE_DIR (defaults unchanged), the output
folder can be redirected with MACH_DOCS_OUT (default: <machine-flows>/inventory), `--preview` skips the state-file write and the
backups, `MACH_DOCS_NO_BACKUP=1` skips the built-in CSV backup (mach makes its own), and `stat` calls use python (mac-safe).
Run it through `mach docs`, which sets MACH_DOCS_LINUX and MACH_DOCS_MAC from the config.

This script is a generic collector: it walks the machine-flows folder and lists every file and folder. The user's own history
(purposes, origin machines, change-log dates, rows for things outside machine-flows) lives in a separate, gitignored data module
`docs-history.local.py`, found in this order: $MACH_DOCS_HISTORY, $MACH_CONFIG_DIR/docs-history.local.py,
<machine-flows>/service-settings/mach/docs-history.local.py, <repo>/config/docs-history.local.py. Without one, only the walk runs.
See config/docs-history.example.py for the format.

Writes <out>/<linux>/docs-index.csv and <out>/<mac>/docs-index.csv, where <linux> is [machines] collector (default: this
machine) and <mac> is [machines] mac (default: mac).
Approach: each shared-synced item is listed ONCE, in the CSV of the machine where it was
created or where our change was made (origin). Its notes carry 'present_on: <linux>, <mac>'.
Local (unsynced) items are listed in their own machine's CSV.
Mac facts come from mac-stat.tsv (output of mac-stat.sh run on the Mac) when present;
otherwise from the synced copy on the collector plus change-log dates (flagged in notes).
"""
import argparse
import csv
import datetime
import glob
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

_ap = argparse.ArgumentParser(description="Collect the docs-index CSVs (use via `mach docs`).")
_ap.add_argument("--preview", action="store_true", help="write only to MACH_DOCS_OUT; no state file, no backups")
ARGS = _ap.parse_args()

# Machine names come from `mach docs` ([machines] collector / mac in the config) through these variables.
LIN = os.environ.get("MACH_DOCS_LINUX") or os.environ.get("MACH_HOST") or os.uname().nodename.split(".")[0]   # the machine that walks machine-flows
MACN = os.environ.get("MACH_DOCS_MAC") or "mac"                                                               # the Mac whose facts come from mac-stat.tsv

TZ = ZoneInfo("America/New_York")
HOME = os.path.expanduser("~")
MF = os.environ.get("MACH_MF_ROOT") or os.path.join(HOME, "machine-flows")
STAGE = os.environ.get("MACH_STAGING") or os.path.join(HOME, "machine-flows-staging")
HERE = os.environ.get("MACH_STATE_DIR") or os.path.join(STAGE, "docs-index")
OUT_ROOT = os.environ.get("MACH_DOCS_OUT") or os.path.join(MF, "inventory")
NO_BACKUP = ARGS.preview or os.environ.get("MACH_DOCS_NO_BACKUP") == "1"
MAC_TSV = os.path.join(HERE, "mac-stat.tsv")
COLS = ["machine", "path", "name", "kind", "area", "scope", "purpose", "created", "modified",
        "created_by", "status", "retired_date", "replaced_by", "notes"]
BOTH = "present_on: %s, %s (shared-synced; dates are the origin machine's)" % (LIN, MACN)

def iso(ts):
    return datetime.datetime.fromtimestamp(ts, TZ).isoformat(timespec="seconds") if ts else ""

def T(s):  # literal local time 'YYYY-MM-DD HH:MM[:SS]' -> ISO with offset
    fmt = "%Y-%m-%d %H:%M:%S" if s.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.datetime.strptime(s, fmt).replace(tzinfo=TZ).isoformat(timespec="seconds")

def tilde(p):
    return "~" + p[len(HOME):] if p.startswith(HOME) else p

def dstat(p):
    """(birth, mtime) on this machine, not following symlinks; birth 0 = n/a."""
    try:
        if sys.platform == "darwin":
            st = os.lstat(p)
            return int(getattr(st, "st_birthtime", 0)), int(st.st_mtime)
        out = subprocess.run(["stat", "-c", "%W %Y", p], capture_output=True, text=True, check=True).stdout.split()
        return int(out[0]), int(out[1])
    except Exception:
        return None

MAC = {}
MAC_CRON, MAC_AGENT, MAC_GROKCLI = [], None, None
if os.path.exists(MAC_TSV):
    for line in open(MAC_TSV, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("#CRON|"):
            MAC_CRON.append(line.split("|", 1)[1]); continue
        if line.startswith("#AGENTLINK|"):
            MAC_AGENT = line.split("|", 1)[1] or None; continue
        if line.startswith("#GROKCLILINK|"):
            MAC_GROKCLI = line.split("|", 1)[1] or None; continue
        if line.startswith("#") or line.count("|") < 4:
            continue
        b, m, c, t, p = line.split("|", 4)
        MAC[p.replace("~//", "~/")] = (int(b), int(m), t)

SEEN_F = os.path.join(HERE, "births-seen.json")
SEEN = json.load(open(SEEN_F)) if os.path.exists(SEEN_F) else {}

def seen_birth(path, b):
    """Keep the earliest birth ever seen for files inside machine-flows (atomic rewrites reset ext4 birth)."""
    if not path.startswith("~/machine-flows/") or not b:
        return b, False
    rel = path[len("~/machine-flows/"):]
    old = SEEN.get(rel)
    if old and old < b - 2:
        return old, True
    if not old:
        SEEN[rel] = b
    return b, False

rows = {LIN: [], MACN: []}

def add(machine, path, kind, area, scope, purpose, created_by, *, status="active", created=None,
        modified=None, retired_date="", replaced_by="", notes="", stat=True, name=None):
    notes_l = [notes] if notes else []
    c, m = created, modified
    real = path.replace("~", HOME, 1)
    if stat and machine == LIN and c is None:
        s = dstat(real)
        if s:
            b, mt = s
            b, rewritten = seen_birth(path, b)
            if rewritten:
                notes_l.append("file later rewritten in place (birth reset); created = earliest birth seen")
            if b == 0:
                notes_l.append("birth n/a")
            elif mt and mt < b - 2:
                c = iso(mt); notes_l.append("birth later than mtime (copied/moved with mtime kept); created = mtime")
            else:
                c = iso(b)
            if m is None: m = iso(mt)
    elif stat and machine == LIN and m is None:
        s = dstat(real)
        if s: m = iso(s[1])
    if stat and machine == MACN and path in MAC and MAC[path][2] != "MISSING":
        b, mt, _ = MAC[path]
        if c is None or c.startswith("~"):
            c = iso(b) if b else c
        if m is None or (modified and modified.startswith("~")):
            m = iso(mt)
        notes_l.append("dates: Mac stat -f %B/%m")
    rows[machine].append({
        "machine": machine, "path": path, "name": name or os.path.basename(path.rstrip("/")) or path,
        "kind": kind, "area": area, "scope": scope, "purpose": purpose,
        "created": (c or "").lstrip("~"), "modified": (m or "").lstrip("~"), "created_by": created_by,
        "status": status, "retired_date": retired_date, "replaced_by": replaced_by,
        "notes": "; ".join(n for n in notes_l if n)})

def synced_dates(rel):
    """For Mac-origin files: the collector's copy (birth=arrival, mtime preserved by Syncthing)."""
    s = dstat(os.path.join(MF, rel))
    return s if s else (0, 0)


# ---------------------------------------------------------------- personal history (optional data module)
def history_candidates():
    """Where the user's history module is looked for, in order (first existing file wins)."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the checkout this script lives in
    out = []
    if os.environ.get("MACH_DOCS_HISTORY"):
        out.append(os.environ["MACH_DOCS_HISTORY"])
    if os.environ.get("MACH_CONFIG_DIR"):
        out.append(os.path.join(os.environ["MACH_CONFIG_DIR"], "docs-history.local.py"))
    out.append(os.path.join(MF, "service-settings", "mach", "docs-history.local.py"))
    out.append(os.path.join(repo, "config", "docs-history.local.py"))
    return out

def load_history():
    cands = history_candidates()
    for p in cands:
        if os.path.isfile(p):
            sys.dont_write_bytecode = True  # no __pycache__ next to the data file (it may sit in a synced folder)
            spec = importlib.util.spec_from_file_location("mach_docs_history", p, loader=importlib.machinery.SourceFileLoader("mach_docs_history", p))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod, p
    print("INFO: no docs-history.local.py found (looked in: %s); listing the generic walk only, without history rows"
          % ", ".join(tilde(c) for c in cands), file=sys.stderr)
    return None, None

HIST, HIST_PATH = load_history()

def H(name, default):
    return getattr(HIST, name, default) if HIST else default

# ---------------------------------------------------------------- history rows (data -> add / mac_file / mac_out)
TIME_RE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d(:\d\d)?$")

def tv(v):
    """History time value: 'YYYY-MM-DD HH:MM[:SS]' (local) or int epoch -> ISO text; '' and None pass through."""
    if isinstance(v, int):
        return iso(v)
    if isinstance(v, str) and TIME_RE.match(v):
        return T(v)
    return v

def real_path(p):
    p = p.replace("{STAGE}", STAGE)
    return p.replace("~", HOME, 1) if p.startswith("~") else p

def cron_note():
    return ("current lines: " + " | ".join(MAC_CRON)) if MAC_CRON else H("CRON_NOTE_FALLBACK", "exact text not re-read (Mac offline)")

def expand(s):
    """Placeholders in history text: {BOTH}, {STAGE}, {cron_note}, {walkfiles:REL}, {nfiles:REL}."""
    if not isinstance(s, str) or "{" not in s:
        return s
    s = s.replace("{BOTH}", BOTH).replace("{STAGE}", tilde(STAGE))
    if "{cron_note}" in s:
        s = s.replace("{cron_note}", cron_note())
    s = re.sub(r"\{walkfiles:([^}]+)\}", lambda m: str(sum(len(f) for _, _, f in os.walk(os.path.join(MF, m.group(1))))), s)
    s = re.sub(r"\{nfiles:([^}]+)\}", lambda m: str(len(listdir_safe(os.path.join(MF, m.group(1))))), s)
    return s

def listdir_safe(d):
    try:
        return os.listdir(d)
    except OSError:
        return []

def min_child_mtime(rel):
    d = os.path.join(MF, rel)
    ts = [os.lstat(os.path.join(d, f)).st_mtime for f in listdir_safe(d)]
    return iso(int(min(ts))) if ts else None

def mac_file(rel, purpose, kind, area, created_override=None, extra=""):
    path = "~/machine-flows/" + rel
    b, mt = synced_dates(rel)
    mac_orig = H("MAC_ORIG", {})
    if rel in mac_orig and not created_override:
        created_override = iso(mac_orig[rel])
        if rel in H("MAC_ORIG_NOTE", {}):
            extra = (extra + "; " if extra else "") + H("MAC_ORIG_NOTE", {})[rel]
        if mt and abs(mt - mac_orig[rel]) > 2 and not (mt > b + 2):
            extra = (extra + "; " if extra else "") + f"last modified on {LIN} {iso(mt)}"
    if path in MAC and MAC[path][2] != "MISSING":
        c, m, n = None, None, ""
    else:
        c = created_override or (iso(min(x for x in (b, mt) if x)) if (b or mt) else "")
        m = iso(mt) if mt else ""
        n = MAC_NOTE_FALLBACK
    if mt and b and mt > b + 2:
        extra = (extra + "; " if extra else "") + f"last modified on {LIN} {iso(mt)}"
        if path in MAC: m = iso(mt)
    add(MACN, path, kind, area, "shared-synced", purpose, "agent", created=c, modified=m,
        notes="; ".join(x for x in [extra, n, BOTH] if x))

def mac_out(path, kind, area, purpose, by, approx_created, *, status="active", retired_date="", replaced_by="", notes="", name=None, modified=""):
    have = path in MAC and MAC[path][2] != "MISSING"
    if path in MAC and MAC[path][2] == "MISSING" and status == "active":
        notes = (notes + "; " if notes else "") + "NOT FOUND on the Mac at collection"
    add(MACN, path, kind, area, "local", purpose, by, status=status, retired_date=retired_date, replaced_by=replaced_by,
        created=None if have else approx_created, modified=None if have else modified, stat=have, name=name,
        notes="; ".join(x for x in [notes, "" if have else "Mac offline: date from change log (approx.)"] if x))

def add_history_row(spec):
    s = dict(spec)
    cond = s.pop("if_lexists", None)
    if cond and not os.path.lexists(real_path(cond)):
        return
    cond = s.pop("if_absent", None)
    if cond and os.path.lexists(real_path(cond)):
        return
    cond = s.pop("if_mf_exists", None)
    if cond and not os.path.exists(os.path.join(MF, cond)):
        return
    present = s.pop("mac_present", None)
    if present and s["path"] in MAC:
        s.update(present)
    kind_file = s.pop("kind_if_file", None)
    if kind_file and not os.path.isdir(real_path(s["path"])):
        s["kind"] = kind_file
    if s.get("stat") == "@in_mac":
        s["stat"] = s["path"] in MAC
    if isinstance(s.get("modified"), str) and s["modified"].startswith("@mf_mtime:"):
        st = dstat(os.path.join(MF, s["modified"][len("@mf_mtime:"):]))
        s["modified"] = iso(st[1]) if st else ""
    for key in ("created", "modified", "retired_date"):
        if key in s:
            s[key] = tv(s[key])
    s["path"] = expand(s["path"])
    if "notes" in s:
        s["notes"] = expand(s["notes"])
    machine, path, kind, area, scope, purpose, by = (s.pop(k) for k in ("machine", "path", "kind", "area", "scope", "purpose", "created_by"))
    add(machine, path, kind, area, scope, purpose, by, **s)

def apply_history_row(spec):
    typ = spec.get("type", "add")
    s = dict(spec)
    if typ == "mac_file":
        s.pop("type")
        co = s.get("created_override")
        if isinstance(co, str) and co.startswith("@min_child:"):
            co = min_child_mtime(co[len("@min_child:"):])
        mac_file(s["rel"], s["purpose"], s["kind"], s["area"], created_override=tv(co), extra=expand(s.get("extra", "")))
    elif typ == "mac_out":
        mac_out(s["path"], s["kind"], s["area"], s["purpose"], s["created_by"], tv(s["approx_created"]), status=s.get("status", "active"),
                retired_date=tv(s.get("retired_date", "")), replaced_by=s.get("replaced_by", ""), notes=expand(s.get("notes", "")),
                name=s.get("name"), modified=tv(s.get("modified", "")))
    else:
        add_history_row(s)

class Ctx:
    """What a history module's dynamic_rows(ctx) may look at."""
    os = os
    MF, STAGE, HOME, MAC, MAC_CRON, MAC_GROKCLI = MF, STAGE, HOME, MAC, MAC_CRON, MAC_GROKCLI
    tilde = staticmethod(tilde)

# ---------------------------------------------------------------- collector machine: inside machine-flows (generic walk)
PURPOSE = H("PURPOSE", {})
DEFAULT_PURPOSE = H("DEFAULT_PURPOSE", "No purpose recorded (add one to docs-history.local.py)")
FOLDER_PURPOSE = H("FOLDER_PURPOSE", {})
CREATED_OVERRIDE = {k: (T(v[0]), v[1]) for k, v in H("CREATED_OVERRIDE", H("DEB_CREATED_OVERRIDE", {})).items()}
INDEX_NOTE = ("Index approach: each shared-synced item is listed once, in the origin machine's CSV (where it was created or where our change was made), "
              "with 'present_on'. Local items are listed per machine. Dates are America/New_York with offset. " + LIN + ": stat -c %W/%Y (ext4 birth time); "
              "" + MACN + ": stat -f %B/%m when gathered, else the synced copy's mtime (Syncthing keeps mtime) plus change-log dates, flagged in notes.")

def mach_purpose(rel):
    """Purpose text for files of the mach CLI checkout (~/machine-flows/mach/), added by mach itself."""
    if not rel.startswith("mach/"):
        return None
    sub = rel[len("mach/"):]
    top = sub.split("/")[0]
    what = {"bin": "entry script", "libexec": "command script", "lib": "shared library", "flows": "built-in flow recipe",
            "config": "example config", "docs": "documentation", "tests": "test"}.get(top, "project file")
    return "mach CLI %s: %s" % (what, sub)

def area_kind(rel):
    top = rel.split("/")[0]
    if top == "plans": return "plan", "plans"
    if top == "ai-authored": return "doc", "ai-authored"
    if top == "mcp":
        if rel.endswith(".yaml"): return "config", "mcp"
        if rel.endswith(".sh"): return "script", "mcp"
        return "doc", "mcp"
    if top == "scripts": return "script", "scripts"
    if top == "inventory": return "inventory", "inventory"
    if top.startswith(".st"): return "config", "syncthing"
    if top == "files": return "folder", "files"
    return "doc", top

MAC_ORIGIN_PREFIX = tuple(H("MAC_ORIGIN_PREFIX", ()))
MAC_ORIGIN_EXACT = set(H("MAC_ORIGIN_EXACT", ()))
SKIP_EXACT = set(H("SKIP_EXACT", ()))
FOLDER_ONLY = set(H("FOLDER_ONLY", ()))

def lin_walk():
    out = []
    for dirpath, dirnames, filenames in os.walk(MF):
        rel_dir = os.path.relpath(dirpath, MF)
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in sorted(dirnames):
            if d in (".git", ".tmp", "__pycache__", "node_modules"):
                continue  # mach (2026-10-08): never index VCS internals, test scratch or caches
            rel = f"{rel_dir}/{d}".lstrip("/")
            if rel in FOLDER_ONLY or rel.endswith("/raw"):
                out.append((rel, True)); continue  # folder row only
            out.append((rel, True)); keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            out.append((f"{rel_dir}/{f}".lstrip("/"), False))
    return out

for rel, is_dir in lin_walk():
    if rel in MAC_ORIGIN_EXACT or (MAC_ORIGIN_PREFIX and rel.startswith(MAC_ORIGIN_PREFIX)) or rel in SKIP_EXACT:
        continue
    if rel == "inventory/" + MACN:
        continue
    path = "~/machine-flows/" + rel
    kind, area = area_kind(rel)
    if is_dir:
        kind = "folder"
        purpose = PURPOSE.get(rel) or FOLDER_PURPOSE.get(rel, "Folder")
        n = ""
        if rel.endswith("/raw"):
            n = f"{len(os.listdir(os.path.join(MF, rel)))} raw data files, summarised as one row"
        add(LIN, path, kind, area, "shared-synced", purpose, "agent", notes="; ".join(x for x in [n, BOTH] if x))
        continue
    purpose = PURPOSE.get(rel) or mach_purpose(rel) or DEFAULT_PURPOSE
    ov = CREATED_OVERRIDE.get(rel)
    notes = BOTH
    if rel.endswith("docs-index.csv") or rel.endswith("docs-index.xlsx"):
        notes = INDEX_NOTE + " " + BOTH
    if rel.startswith("inventory/" + MACN + "/"):
        notes = "about %s but written on %s; " % (MACN, LIN) + BOTH
    if rel.startswith("plans/archived/") and rel != "plans/archived/README.md":
        try:
            moved = iso(int(os.lstat(os.path.join(MF, rel)).st_ctime))
        except Exception:
            moved = ""
        add(LIN, path, kind, area, "shared-synced", PURPOSE.get(rel, "Archived plan"), "agent", status="retired", retired_date=moved,
            notes="archived plan (moved from plans/" + os.path.basename(rel) + "); retired_date = file ctime at the move; " + BOTH)
        continue
    if ov:
        add(LIN, path, kind, area, "shared-synced", purpose, "agent", created=ov[0], notes=ov[1] + "; " + notes)
    else:
        add(LIN, path, kind, area, "shared-synced", purpose, "agent", notes=notes)

# The index outputs themselves (may not exist yet at first collection)
for rel in ["inventory/%s/docs-index.csv" % LIN, "inventory/%s/docs-index.csv" % MACN, "inventory/docs-index.xlsx", "scripts/docs-index-build.py"]:
    if not any(r["path"] == "~/machine-flows/" + rel for r in rows[LIN]):
        now = iso(datetime.datetime.now().timestamp())
        kind, area = area_kind(rel)
        add(LIN, "~/machine-flows/" + rel, kind, area, "shared-synced", PURPOSE.get(rel, DEFAULT_PURPOSE), "agent", created=now, modified=now,
            stat=False, notes=(INDEX_NOTE + " " if "docs-index." in rel else "") + BOTH)

# ---------------------------------------------------------------- history rows from the data module
BACKUP_PURPOSE = H("BACKUP_PURPOSE", {})
BACKUP_OVERRIDES = H("BACKUP_OVERRIDES", {})
MAC_NOTE_FALLBACK = "Mac offline at collection: Mac birth time not read; created = original Mac mtime seen on the synced copy (Syncthing keeps mtime) or change-log time"

for spec in H("ROWS", []):
    apply_history_row(spec)
if HIST and hasattr(HIST, "dynamic_rows"):
    for spec in HIST.dynamic_rows(Ctx):
        apply_history_row(spec)

# collector machine: backups folder (names and purposes come from the history module; unknown ones get a generic purpose)
DI_BACKUPS = sorted(glob.glob(os.path.join(STAGE, "backups", "docs-index-*")))
if DI_BACKUPS:
    add(LIN, "~/machine-flows-staging/backups/docs-index-*", "backup", "staging", "local",
        "Previous docs-index CSVs/workbook, saved before each regeneration", "agent",
        created=iso(min(dstat(p)[0] for p in DI_BACKUPS)), modified=iso(max(dstat(p)[1] for p in DI_BACKUPS)), stat=False,
        name="docs-index-* backups", notes=f"{len(DI_BACKUPS)} timestamped folder(s), summarised as one row")
for p in sorted(glob.glob(os.path.join(STAGE, "backups", "*"))):
    n = os.path.basename(p)
    if n.startswith("docs-index-"):
        continue
    s = dstat(p)
    ov = next((v for k, v in BACKUP_OVERRIDES.items() if n.startswith(k)), None)
    if ov:
        add(LIN, tilde(p), "backup", "staging", "local", BACKUP_PURPOSE.get(n, "Backup made by a machine-flows task (see its folder/name)"), "agent",
            created=tv(ov["created"]), notes=ov["notes"])
        continue
    add(LIN, tilde(p), "backup", "staging", "local", created=iso(s[0]) if s else None,
        purpose=BACKUP_PURPOSE.get(n, "Backup made by a machine-flows task (see its folder/name)"), created_by="agent",
        notes=("backup time = birth; mtime kept from the original file" if s and s[1] < s[0] - 2 else ""))

# Mac: anything mac-stat.tsv saw in the Mac staging folder that has no row yet
for p, (b, m, t) in sorted(MAC.items()):
    if p.startswith("~/machine-flows-staging/") and t != "MISSING" and not any(r["path"] == p for r in rows[MACN]):
        add(MACN, p, "backup" if "/backups/" in p else ("folder" if t == "Directory" else "doc"), "staging", "local",
            "Mac staging item (see its name)", "agent")

# ---------------------------------------------------------------- write
if not ARGS.preview:
    os.makedirs(HERE, exist_ok=True)
    json.dump(SEEN, open(SEEN_F, "w"), indent=0, sort_keys=True)
ORDER = {"active": 0, "superseded": 1, "retired": 2, "deleted": 3}
for machine, sub in [(LIN, LIN), (MACN, MACN)]:
    out = os.path.join(OUT_ROOT, sub, "docs-index.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out) and not NO_BACKUP:
        ts = datetime.datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
        bdir = os.path.join(STAGE, "backups", f"docs-index-{ts}"); os.makedirs(bdir, exist_ok=True)
        shutil.copy2(out, os.path.join(bdir, f"{sub}-docs-index.csv"))
    rs = sorted(rows[machine], key=lambda r: (ORDER.get(r["status"], 9), r["area"], r["path"]))
    tmp = out + ".tmp" if ARGS.preview else os.path.join(HERE, f"{sub}-docs-index.csv.tmp")  # outside the synced folder
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader(); w.writerows(rs)
    try:
        os.replace(tmp, out)
    except OSError:  # different filesystems
        shutil.move(tmp, out)
    print(machine, len(rs), {s: sum(1 for r in rs if r["status"] == s) for s in ORDER})
