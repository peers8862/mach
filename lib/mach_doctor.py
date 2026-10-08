"""mach_doctor: read-only health checks (plan 08 section 4). Each check returns a list of (level, check, detail).

Hard rules: no secrets are ever printed (the Syncthing API key is read into a local variable, sent as a header, dropped),
Grok Bot credential files are never opened, every external call has a timeout, the whole run stays well under 15 s.
"""
import fnmatch
import json
import os
import re
import time
import urllib.error
import urllib.request

import mach_common as mc

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"

PRUNE = (".git", "node_modules", ".stversions", "__pycache__", ".venv")
DEFAULT_SECRET_PATTERNS = ["*.env", ".env.*", "*.pem", "*.p12", "id_rsa*", "id_ed25519*", "bridge-token", "credentials*.json"]


class Ctx(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.host = mc.host()
        self.mac = mc.is_mac()
        self.mf = mc.mf_root()
        self.start = time.time()
        self.budget = 12.0
        self._scan = None

    def time_left(self):
        return self.budget - (time.time() - self.start)

    def get(self, key, default=None):
        return self.cfg.get("doctor." + key, default)


# ----------------------------------------------------------------- syncthing

def _count_syncthing_procs():
    """Independent syncthing instances: Syncthing's monitor process and its child count as one."""
    rc, out, _e = mc.run_capture(["ps", "-axo", "pid=,ppid=,comm="], timeout=3)
    if rc != 0:
        return None
    pids, ppids = set(), []
    for ln in out.splitlines():
        parts = ln.split(None, 2)
        if len(parts) == 3 and os.path.basename(parts[2].strip()) == "syncthing":
            pids.add(parts[0])
            ppids.append(parts[1])
    return sum(1 for pp in ppids if pp not in pids)


def check_syncthing_service(ctx):
    name = "syncthing-service"
    if ctx.mac:
        rc, out, err = mc.run_capture([mc.cmd("launchctl"), "print", "gui/%d/net.syncthing.syncthing" % os.getuid()], timeout=4)
        if rc == 127:
            return [(INFO, name, "launchctl not available")]
        if rc != 0:
            return [(FAIL, name, "LaunchAgent net.syncthing.syncthing not loaded")]
        running = re.search(r"state\s*=\s*running", out) is not None
        res = [(OK if running else FAIL, name, "LaunchAgent net.syncthing.syncthing %s" % ("running" if running else "loaded but not running"))]
    else:
        rc, out, err = mc.run_capture([mc.cmd("systemctl"), "--user", "is-active", "syncthing"], timeout=3)
        if rc == 127:
            return [(INFO, name, "systemctl not available")]
        state = out.strip() or err.strip() or "unknown"
        res = [(OK if state == "active" else FAIL, name, "syncthing.service (user) is %s" % state)]
    n = _count_syncthing_procs()
    if n is not None and n > 1:
        res.append((WARN, "syncthing-instances", "%d syncthing processes are running (expected one)" % n))
    elif n == 1:
        res.append((OK, "syncthing-instances", "one syncthing process"))
    return res


def _api_key_paths(ctx):
    h = mc.home()
    paths = [os.path.join(h, ".local", "state", "syncthing", "config.xml")]
    if ctx.mac:
        paths.insert(0, os.path.join(h, "Library", "Application Support", "Syncthing", "config.xml"))
    return paths


def _read_api_key(ctx):
    """Read the API key at runtime only. The caller must never print, log or store it."""
    for p in _api_key_paths(ctx):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                m = re.search(r"<apikey>([^<]+)</apikey>", fh.read())
        except OSError:
            continue
        if m:
            return m.group(1).strip()
    return None


def _rest(base, path, key, timeout=3):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(base.rstrip("/") + path, headers={"X-API-Key": key})
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def check_syncthing_state(ctx):
    name = "syncthing-state"
    key = _read_api_key(ctx)
    if not key:
        return [(INFO, name, "skipped: no Syncthing config.xml with an API key found")]
    base = str(ctx.get("syncthing_url", "http://127.0.0.1:8384"))
    folder = str(ctx.get("syncthing_folder", "machine-flows"))
    res = []
    try:
        st = _rest(base, "/rest/db/status?folder=" + folder, key)
        conns = _rest(base, "/rest/system/connections", key)
    except urllib.error.HTTPError as exc:
        key = None
        return [(FAIL if exc.code in (400, 404) else WARN, name, "REST API answered HTTP %s for folder '%s'" % (exc.code, folder))]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        key = None
        return [(WARN, name, "REST API at %s not reachable (%s)" % (base, getattr(exc, "reason", exc)))]
    key = None  # drop the secret as early as possible
    state = str(st.get("state", "unknown"))
    errors = int(st.get("errors", 0) or 0) + int(st.get("pullErrors", 0) or 0)
    need = int(st.get("needTotalItems", 0) or 0)
    if errors:
        res.append((WARN, name, "folder '%s' is %s with %d error(s)" % (folder, state, errors)))
    elif state in ("idle", "scanning", "syncing", "sync-preparing", "scan-waiting", "sync-waiting", "cleaning", "clean-waiting"):
        res.append((OK if state == "idle" else INFO, name, "folder '%s' is %s, %d item(s) out of sync" % (folder, state, need)))
    else:
        res.append((WARN, name, "folder '%s' state is %s" % (folder, state)))
    peers = [v for v in (conns.get("connections") or {}).values() if isinstance(v, dict)]
    connected = sum(1 for v in peers if v.get("connected"))
    if not peers:
        res.append((INFO, "syncthing-peer", "no remote devices configured"))
    elif connected:
        res.append((OK, "syncthing-peer", "%d of %d remote device(s) connected" % (connected, len(peers))))
    else:
        res.append((WARN, "syncthing-peer", "no remote device is connected (0 of %d)" % len(peers)))
    return res


def _syncthing_version(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            m = re.search(r"syncthing v(\d+\.\d+\.\d+)", fh.read())
    except OSError:
        return None
    return m.group(1) if m else None


def check_syncthing_version(ctx):
    name = "syncthing-version"
    found = {}
    for h in mc.machine_names(ctx.cfg):
        v = _syncthing_version(os.path.join(ctx.mf, "inventory", h, "70-services-network.md"))
        if v:
            found[h] = v
    if len(found) < 2:
        return [(INFO, name, "cannot compare: inventory has a version for %s only" % (", ".join(sorted(found)) or "no host"))]
    if len(set(found.values())) == 1:
        return [(OK, name, "same version everywhere (%s, from inventory)" % list(found.values())[0])]
    return [(WARN, name, "versions differ: " + ", ".join("%s=%s" % kv for kv in sorted(found.items())))]


# ----------------------------------------------------------------- names

def check_cli_names(ctx):
    name = "cli-names"
    h = mc.home()
    bin_dir = os.path.join(h, ".local", "bin")
    bad = []
    for p in (os.path.join(bin_dir, "agent"), os.path.join(h, ".grok", "bin", "agent"), "/usr/local/bin/agent"):
        if os.path.lexists(p):
            bad.append(mc.tilde(p))
    res = []
    if bad:
        res.append((WARN, name, "bare `agent` exists: %s (fix: mach names --fix)" % ", ".join(bad)))
    else:
        res.append((OK, name, "no bare `agent` in ~/.local/bin, ~/.grok/bin, /usr/local/bin"))
    miss = []
    if not os.path.lexists(os.path.join(bin_dir, "cursor-agent")):
        miss.append("cursor-agent")
    grok_here = os.path.isdir(os.path.join(h, ".grok", "bin"))
    if not os.path.lexists(os.path.join(bin_dir, "grokcli-agent")):
        if ctx.mac or grok_here:
            miss.append("grokcli-agent")
    if miss:
        res.append((WARN, name, "missing: %s in ~/.local/bin" % ", ".join(miss)))
    else:
        res.append((OK, name, "explicit names present" + ("" if ctx.mac or grok_here else " (grokcli-agent n/a: grok not installed)")))
    w = mc.which("agent")
    if w:
        res.append((WARN, name, "`agent` still resolves on PATH: %s" % mc.tilde(w)))
    return res


# ----------------------------------------------------------------- 75 / 76

def split_md_row(line):
    """Cells of one Markdown table row. `\\|` and a `|` inside a backtick span do not split; `\\|` is unescaped."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    cells, cur, i, n = [], [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n and s[i + 1] == "|":
            cur.append("|")
            i += 2
        elif ch == "`":
            close = s.find("`", i + 1)
            if close == -1:
                cur.append(ch)
                i += 1
            else:
                cur.append(s[i:close + 1].replace("\\|", "|"))
                i = close + 1
        elif ch == "|":
            cells.append("".join(cur).strip())
            cur = []
            i += 1
        else:
            cur.append(ch)
            i += 1
    if "".join(cur).strip():
        cells.append("".join(cur).strip())   # last cell when the row has no closing pipe
    return cells


def parse_md_tables(text):
    """All pipe tables in the text: list of (header_cells, rows); separator rows dropped."""
    tables, header, rows, state = [], None, [], 0   # state 0 = outside, 1 = header seen, 2 = in body
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            if state:
                tables.append((header, rows))
            header, rows, state = None, [], 0
            continue
        cells = split_md_row(s)
        if state == 0:
            header, rows, state = cells, [], 1
        elif state == 1:
            if cells and all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                state = 2
            else:   # a '|' line without a separator row is not a table: start over from this line
                header, rows, state = cells, [], 1
        else:
            rows.append(cells)
    if state:
        tables.append((header, rows))
    return [t for t in tables if t[0] is not None]


def is_main_table(header):
    """The services table: first column 'Name', a 'Status' column, and at least 5 columns (75: Name/Type/File path/…/Status)."""
    low = [h.lower() for h in header]
    return len(low) >= 5 and low[0] == "name" and any(h.startswith("status") for h in low)


def parse_md_table_rows(text):
    """Rows of the main services table only (header and separator rows dropped); other tables are ignored.
    A file with no table headed Name/…/Status falls back to its first table."""
    tables = parse_md_tables(text)
    main = [t for t in tables if is_main_table(t[0])]
    chosen = main[0] if main else (tables[0] if tables else None)
    return chosen[1] if chosen else []


def other_md_tables(text):
    """Headers of tables that parse_md_table_rows ignores (for reporting)."""
    tables = parse_md_tables(text)
    main = [t for t in tables if is_main_table(t[0])]
    keep = main[0] if main else (tables[0] if tables else None)
    return [t[0] for t in tables if t is not keep]


def check_services_index(ctx):
    res = []
    for fname, label in (("75-custom-startup-services.md", "startup-index"), ("76-custom-scheduled-jobs.md", "jobs-index")):
        p = os.path.join(ctx.mf, "inventory", ctx.host, fname)
        if not os.path.isfile(p):
            res.append((WARN, label, "missing: inventory/%s/%s" % (ctx.host, fname)))
            continue
        text = mc.read_text(p)
        rows = parse_md_table_rows(text)
        insane = [r for r in rows if not r or not r[0] or len(r) < 5]
        if insane:
            res.append((WARN, label, "%d malformed row(s) in %s" % (len(insane), fname)))
        elif not rows:
            res.append((INFO, label, "%s has no table rows" % fname))
        else:
            active = sum(1 for r in rows if re.search(r"\b(active|enabled)\b", r[-1] if label == "startup-index" else " ".join(r), re.I)
                         and not re.search(r"\b(removed|planned|paused)\b", r[-1] if label == "startup-index" else " ".join(r[-2:-1]), re.I))
            extra = other_md_tables(text)
            note = "; %d other table(s) ignored: %s" % (len(extra), " / ".join(" | ".join(h)[:40] for h in extra)) if extra else ""
            res.append((OK, label, "%s: %d row(s), %d look active (details: mach services check)%s" % (fname, len(rows), active, note)))
    return res


# ----------------------------------------------------------------- grok bot

def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _epoch_seconds(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x / 1000.0 if x > 1e11 else x


def check_grokbot(ctx):
    """Plan 07: reads ONLY local-exec-daemon.json, local-exec-supervisor.json and local-exec-daemon.log."""
    name = "grokbot"
    gdir = os.path.join(mc.home(), ".grokbot")
    if not os.path.isdir(gdir):
        return [(INFO, name, "Grok Bot not set up on this machine (~/.grokbot absent)")]
    d = _read_json(os.path.join(gdir, "local-exec-daemon.json"))
    if not isinstance(d, dict):
        return [(WARN, name, "local-exec-daemon.json missing or unreadable: click into the Grok Bot app on this machine")]
    res = []
    pid = d.get("pid")
    if not _alive(pid):
        res.append((FAIL, name, "daemon pid %s is not running: click into Grok Bot on this machine" % pid))
    else:
        res.append((OK, name, "daemon pid %s alive" % pid))
    serving = _epoch_seconds(d.get("servingAt"))
    if not serving:
        res.append((WARN, name, "daemon has no servingAt: it is not serving yet (click into Grok Bot)"))
    else:
        res.append((OK, name, "serving since %.0f min ago" % ((time.time() - serving) / 60.0)))
    s = _read_json(os.path.join(gdir, "local-exec-supervisor.json"))
    maxage = float(ctx.get("grokbot_heartbeat_max_age_s", 180))
    if isinstance(s, dict) and _epoch_seconds(s.get("at")):
        age = time.time() - _epoch_seconds(s["at"])
        res.append((OK if age <= maxage else WARN, name, "supervisor heartbeat %.0f s ago%s" % (age, "" if age <= maxage else " (stale > %.0f s)" % maxage)))
    else:
        res.append((WARN, name, "no supervisor heartbeat found"))
    log = os.path.join(gdir, "local-exec-daemon.log")
    try:
        size = os.path.getsize(log)
        with open(log, "rb") as fh:
            fh.seek(max(0, size - 262144))
            lines = fh.read().decode("utf-8", "replace").splitlines()
        last_start = -1
        for i, ln in enumerate(lines):
            if re.search(r"\bstarted\b", ln):
                last_start = i
        failed = sum(1 for ln in lines[last_start + 1:] if "watch stream failed" in ln)
        if failed:
            res.append((WARN, name, "%d 'watch stream failed' line(s) since the last daemon start: click into Grok Bot on this machine" % failed))
        else:
            res.append((OK, name, "no 'watch stream failed' since the last daemon start"))
    except OSError:
        res.append((INFO, name, "daemon log not readable"))
    return res


# ----------------------------------------------------------------- disk / memory

def check_disk(ctx):
    import shutil
    name = "disk"
    minpct = float(ctx.get("disk_min_free_pct", 10))
    res, seen = [], set()
    for label, p in (("home", mc.home()), ("machine-flows", ctx.mf)):
        if not os.path.exists(p):
            continue
        try:
            dev = os.stat(p).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            u = shutil.disk_usage(p)
        except OSError:
            continue
        pct = 100.0 * u.free / u.total if u.total else 0.0
        level = FAIL if pct < minpct else (WARN if pct < minpct * 1.5 else OK)
        res.append((level, name, "%s: %.0f%% free (%.1f GiB of %.1f GiB)" % (label, pct, u.free / 2.0 ** 30, u.total / 2.0 ** 30)))
    return res or [(INFO, name, "cannot read disk usage")]


def _linux_mem_available_mb():
    for ln in mc.read_text("/proc/meminfo").splitlines():
        if ln.startswith("MemAvailable:"):
            return int(ln.split()[1]) / 1024.0
    return None


def _mac_mem_available_mb():
    rc, out, _e = mc.run_capture(["vm_stat"], timeout=3)
    if rc != 0:
        return None
    m = re.search(r"page size of (\d+) bytes", out)
    page = int(m.group(1)) if m else 4096
    total = 0
    for key in ("Pages free", "Pages inactive", "Pages speculative"):
        mm = re.search(r"%s:\s+(\d+)" % key, out)
        if mm:
            total += int(mm.group(1))
    return total * page / (1024.0 * 1024.0)


def check_memory(ctx):
    name = "memory"
    mb = _mac_mem_available_mb() if ctx.mac else _linux_mem_available_mb()
    if mb is None:
        return [(INFO, name, "cannot read available memory here")]
    low = float(ctx.get("mem_min_avail_mb", 500))
    return [(WARN if mb < low else OK, name, "%.0f MiB available%s" % (mb, " (below %.0f MiB)" % low if mb < low else ""))]


def check_peer(ctx):
    name = "peer-reachability"
    peer = str(ctx.get("peer_ssh", "") or "")
    if not peer:
        return [(INFO, name, "skipped: no ssh alias configured ([doctor] peer_ssh); Syncthing shows peer connection")]
    rc, _o, e = mc.run_capture([mc.cmd("ssh"), "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", peer, "true"], timeout=6)
    if rc == 0:
        return [(OK, name, "ssh to %s works" % peer)]
    return [(WARN, name, "ssh to %s failed (%s)" % (peer, "timeout" if rc == 124 else "rc=%d" % rc))]


# ----------------------------------------------------------------- hygiene

def _secret_patterns(mf):
    pats = []
    lines = mc.read_text(os.path.join(mf, ".stglobalignore")).splitlines()
    on = False
    for ln in lines:
        low = ln.lower()
        if "secrets guard" in low:
            on = True
            continue
        if on:
            if not ln.strip():
                break
            if ln.strip().startswith("//"):
                continue
            p = re.sub(r"^\(\?[a-z]\)", "", ln.strip())
            if p.startswith("**/"):
                p = p[3:]
            pats.append(p)
    return pats or DEFAULT_SECRET_PATTERNS


def scan_tree(ctx):
    """One bounded walk of machine-flows: symlinks, secrets-guard filename matches, sync conflicts."""
    if ctx._scan is not None:
        return ctx._scan
    out = {"symlinks": [], "secrets": [], "conflicts": [], "partial": False, "files": 0}
    pats = [p.lower() for p in _secret_patterns(ctx.mf)]
    deadline = time.time() + float(ctx.get("scan_budget_s", 4))
    own_tmp = os.path.join(os.path.realpath(mc.mach_home()), ".tmp")
    for dirpath, dirnames, filenames in os.walk(ctx.mf, followlinks=False):
        if time.time() > deadline:
            out["partial"] = True
            break
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                out["symlinks"].append(os.path.relpath(full, ctx.mf))
                continue
            if d in PRUNE or os.path.realpath(full) == own_tmp:
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            out["files"] += 1
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, ctx.mf)
            if os.path.islink(full):
                out["symlinks"].append(rel)
            low = f.lower()
            if ".sync-conflict-" in low:
                out["conflicts"].append(rel)
            if any(fnmatch.fnmatch(low, p) for p in pats):
                out["secrets"].append(rel)
    for key in ("symlinks", "secrets", "conflicts"):
        out[key].sort(key=lambda r: (r.lower(), r))   # same order on every filesystem (APFS and ext4 walk differently)
    ctx._scan = out
    return out


def _names(items, n=5):
    shown = ", ".join(items[:n])
    return shown + (" (+%d more)" % (len(items) - n) if len(items) > n else "")


def check_hygiene(ctx):
    name = "mf-hygiene"
    if not os.path.isdir(ctx.mf):
        return [(FAIL, name, "machine-flows root not found: %s" % mc.tilde(ctx.mf))]
    s = scan_tree(ctx)
    res = []
    res.append((FAIL, name, "%d symlink(s) inside machine-flows: %s" % (len(s["symlinks"]), _names(s["symlinks"]))) if s["symlinks"]
               else (OK, name, "no symlinks inside machine-flows (%d files scanned)" % s["files"]))
    res.append((FAIL, name, "%d file name(s) match the secrets guard (names only): %s" % (len(s["secrets"]), _names(s["secrets"]))) if s["secrets"]
               else (OK, name, "no file names match the secrets guard"))
    if s["conflicts"]:
        res.append((WARN, "sync-conflicts", "%d *.sync-conflict-* file(s): %s" % (len(s["conflicts"]), _names(s["conflicts"]))))
    else:
        res.append((OK, "sync-conflicts", "no sync-conflict files"))
    if s["partial"]:
        res.append((INFO, name, "scan stopped at the time budget; results are partial"))
    return res


# ----------------------------------------------------------------- caps / plans / queue

def _line_count(p):
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return None


def check_memory_caps(ctx):
    name = "ai-memory-caps"
    res = []
    lessons = mc.rel_to_mf(ctx.cfg.get("memory.lessons_dir", "service-memories/lessons"))
    items = (("ai-authored/AGENTS.md", os.path.join(ctx.mf, "ai-authored", "AGENTS.md"), int(ctx.get("agents_max_lines", 130))),
             ("lessons/INDEX.md", os.path.join(lessons, "INDEX.md"), int(ctx.get("lessons_index_max_lines", 300))))
    for label, p, cap in items:
        n = _line_count(p)
        if n is None:
            res.append((INFO, name, "%s not found yet (cap %d lines)" % (label, cap)))
        else:
            res.append((OK if n <= cap else WARN, name, "%s: %d lines (cap %d)" % (label, n, cap)))
    idx = mc.read_text(os.path.join(lessons, "INDEX.md"))
    if idx:
        proposed = sum(1 for ln in idx.splitlines() if "[proposed]" in ln and ln.lstrip().startswith("-"))
        cap = int(ctx.get("proposed_max", 30))
        res.append((OK if proposed <= cap else WARN, name, "proposed lessons: %d (cap %d)" % (proposed, cap)))
    if os.path.isdir(lessons):
        files = 0
        for dirpath, dirnames, fns in os.walk(lessons):
            dirnames[:] = [d for d in dirnames if d not in ("archived", "reviews")]
            files += sum(1 for f in fns if f.endswith(".md") and f.lower() not in ("index.md", "readme.md"))
        rdir = os.path.join(lessons, "reviews")
        newest = 0.0
        if os.path.isdir(rdir):
            for f in os.listdir(rdir):
                newest = max(newest, os.path.getmtime(os.path.join(rdir, f)))
        if files and (time.time() - newest) > 35 * 86400:
            res.append((WARN, name, "monthly lesson review is due (last review: %s)" % (time.strftime("%Y-%m-%d", time.localtime(newest)) if newest else "never")))
    return res


def count_boxes(text):
    open_n = len(re.findall(r"^\s*[-*]\s+\[ \]", text, re.M))
    done_n = len(re.findall(r"^\s*[-*]\s+\[[xX]\]", text, re.M))
    return open_n, done_n


def check_plans(ctx):
    name = "plans"
    d = os.path.join(ctx.mf, "plans")
    if not os.path.isdir(d):
        return [(INFO, name, "no plans/ folder")]
    res, total, withopen = [], 0, 0
    for fn in sorted(os.listdir(d)):
        m = re.match(r"^(\d\d)-.*\.md$", fn)
        if not m:
            continue
        total += 1
        o, c = count_boxes(mc.read_text(os.path.join(d, fn)))
        if o:
            withopen += 1
        elif c and m.group(1) != "00":
            res.append((INFO, name, "plan %s has all %d box(es) ticked: propose archiving (mach plans archive %s)" % (m.group(1), c, m.group(1))))
    res.insert(0, (OK, name, "%d plan(s), %d with open boxes" % (total, withopen)))
    return res


def check_outbox(ctx):
    name = "outbox"
    import mach_exec as ex
    items = ex.outbox_items()
    maxh = float(ctx.get("outbox_max_age_hours", 24))
    late = [i for i in items if i["age_hours"] > maxh]
    if late:
        return [(WARN, name, "%d outbox item(s) older than %gh: %s (deliver with: mach note flush on the Mac)" % (len(late), maxh, _names(["%s/%s" % (i["dest"], i["name"]) for i in late])))]
    return [(OK, name, "%d item(s) waiting, none older than %gh" % (len(items), maxh))]


def check_runs(ctx):
    import mach_runs as mr
    waiting = [r for r in mr.list_runs(ctx.cfg) if r.status == "waiting-approval"]
    if waiting:
        return [(INFO, "runs", "%d run(s) waiting for approval (mach queue)" % len(waiting))]
    return [(OK, "runs", "no runs waiting for approval")]


def check_config(ctx):
    if ctx.cfg.errors:
        return [(WARN, "config", "could not load: " + "; ".join(ctx.cfg.errors))]
    if not ctx.cfg.sources:
        return [(INFO, "config", "no config files found: using built-in defaults")]
    return [(OK, "config", "loaded " + ", ".join("%s" % layer for layer, _p in ctx.cfg.sources))]


CHECKS = [check_config, check_syncthing_service, check_syncthing_state, check_syncthing_version, check_cli_names,
          check_services_index, check_grokbot, check_disk, check_memory, check_peer, check_hygiene,
          check_memory_caps, check_plans, check_outbox, check_runs]


def run_all(cfg):
    ctx = Ctx(cfg)
    results = []
    for fn in CHECKS:
        if ctx.time_left() <= 0:
            results.append((INFO, fn.__name__.replace("check_", "").replace("_", "-"), "skipped: time budget used up"))
            continue
        try:
            results.extend(fn(ctx))
        except Exception as exc:  # a broken check must not hide the others
            results.append((WARN, fn.__name__.replace("check_", "").replace("_", "-"), "check crashed: %s: %s" % (type(exc).__name__, exc)))
    return results


def exit_code(results):
    levels = set(r[0] for r in results)
    if FAIL in levels:
        return mc.EXIT_FAIL
    if WARN in levels:
        return mc.EXIT_WARN
    return mc.EXIT_OK
