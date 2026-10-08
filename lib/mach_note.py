"""mach_note: quick capture to inbox / Agenda / Drafts / named destinations (plan 08 section 3.5).

A note is captured text. Nothing runs and no run record is made. Fallbacks are never silent and exit 1.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import mach_common as mc
import frontmatter as fm
from mach_runs import fm_value

BUILTIN = ["inbox", "agenda", "drafts"]
TYPES = ["inbox", "agenda", "drafts", "file"]
# `mach note` destination syntax -> (kind, how it is delivered). docs/sheets/destinations.csv is generated from this table.
DEST_DOCS = [
    ("inbox", "note/file", "appended to the dated Markdown file under files/inbox/notes in machine-flows"),
    ("agenda", "note/app", "macOS Agenda: MCP tools/call create_note, then the URL scheme; else the outbox (exit 1)"),
    ("drafts", "note/app", "macOS Drafts: the drafts CLI, then the URL scheme; else the outbox (exit 1)"),
    ("<name>", "note/named", "a [note.dest.<name>] table in config with type file, inbox, agenda or drafts"),
]


class NoteError(Exception):
    pass


class Note(object):
    def __init__(self, text, title="", tags=None, project="", date="", flag=False, open_app=False):
        self.text = text
        self.title = title or derive_title(text)
        self.tags = tags or []
        self.project = project
        self.date = date
        self.flag = flag
        self.open_app = open_app


def derive_title(text):
    first = text.strip().split("\n")[0].strip() if text.strip() else ""
    return first[:60].rstrip()


def split_tags(values, csv):
    out = []
    for v in list(values or []) + [t for t in (csv or "").split(",")]:
        v = v.strip().lstrip("#")
        if v and v not in out:
            out.append(v)
    return out


# ----------------------------------------------------------------- destinations

def known_dests(cfg):
    names = list(BUILTIN)
    for n in cfg.section("note.dest"):
        if n not in names:
            names.append(n)
    return names


def resolve_dest(cfg, name):
    """Return (type, settings dict) for a destination name."""
    if name in BUILTIN:
        typ = name
        settings = dict(cfg.section("note.%s" % name))
    else:
        d = cfg.section("note.dest").get(name)
        if not isinstance(d, dict):
            raise NoteError("unknown destination %r (known: %s)" % (name, ", ".join(known_dests(cfg))))
        typ = d.get("type", "file")
        if typ not in TYPES:
            raise NoteError("destination %r has unknown type %r (use %s)" % (name, typ, ", ".join(TYPES)))
        settings = dict(cfg.section("note.%s" % typ)) if typ != "file" else {}
        settings.update(d)
    return typ, settings


# ----------------------------------------------------------------- formatting

def entry_markdown(note, when):
    lines = ["## %s %s" % (when.strftime("%H:%M"), note.title or "(no title)")]
    if note.tags:
        lines.append("tags: " + ", ".join(note.tags))
    if note.date:
        lines.append("date: " + note.date)
    lines.append("")
    lines.append(note.text.strip())
    return "\n".join(lines) + "\n"


def with_hash_tags(text, tags):
    if not tags:
        return text
    return text.rstrip() + "\n\n" + " ".join("#" + t for t in tags)


# ----------------------------------------------------------------- inbox / file

def inbox_path(cfg, when):
    d = mc.rel_to_mf(cfg.get("note.inbox.dir", "files/inbox/notes"))
    return os.path.join(d, "%s-%s.md" % (when.strftime("%Y-%m-%d"), mc.host()))


def append_entry(path, note, when, header=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as fh:
        if new and header:
            fh.write(header + "\n\n")
        elif not new:
            fh.write("\n")
        fh.write(entry_markdown(note, when))


def deliver_file(path, note, when):
    if not mc.is_inside(path, mc.mf_root()):
        raise NoteError("file destinations must stay inside machine-flows; refusing %s" % mc.tilde(path))
    append_entry(path, note, when, header="# Notes")
    return "file", mc.tilde(path)


# ----------------------------------------------------------------- agenda

def _post(url, payload, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        return resp.status, resp.headers, body


def _json_from_body(body, ctype):
    body = body.strip()
    if not body:
        return None
    if "event-stream" in (ctype or "") or body.startswith("event:") or body.startswith("data:"):
        last = None
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    last = json.loads(line[5:].strip())
                except ValueError:
                    pass
        return last
    try:
        return json.loads(body)
    except ValueError:
        return None


def agenda_mcp_url(settings):
    """Agenda's local MCP endpoint: $MACH_AGENDA_MCP_URL > the destination's `mcp_url` setting > Agenda's usual localhost port."""
    return os.environ.get("MACH_AGENDA_MCP_URL") or settings.get("mcp_url") or "http://127.0.0.1:16106/mcp"


def agenda_mcp(url, note, settings, timeout=2):
    """Create a note through Agenda's built-in MCP server (localhost, no token). Raises NoteError on any failure."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    try:
        status, hdrs, body = _post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                         "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                                    "clientInfo": {"name": "mach", "version": mc.version()}}}, headers, timeout)
        sid = hdrs.get("Mcp-Session-Id") or hdrs.get("mcp-session-id")
        if sid:
            headers["Mcp-Session-Id"] = sid
        try:
            _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers, timeout)
        except (urllib.error.URLError, OSError, ValueError):
            pass
        args = {"title": note.title, "text": with_hash_tags(note.text, note.tags)}
        project = note.project or settings.get("project")
        if project:
            args["project"] = project
        if note.date:
            args["date"] = note.date
        status, hdrs, body = _post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                         "params": {"name": "create_note", "arguments": args}}, headers, timeout)
    except urllib.error.HTTPError as exc:
        raise NoteError("MCP HTTP %s" % exc.code)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NoteError("MCP not reachable (%s)" % getattr(exc, "reason", exc))
    msg = _json_from_body(body, hdrs.get("Content-Type", ""))
    if not isinstance(msg, dict) or "error" in msg or (msg.get("result") or {}).get("isError"):
        raise NoteError("MCP create_note failed")
    return "mcp"


def agenda_url(note, settings):
    q = []
    project = note.project or settings.get("project")
    if project:
        q.append(("project-title", project))
    q.append(("title", note.title))
    q.append(("text", with_hash_tags(note.text, note.tags)))
    if note.date:
        q.append(("date", note.date))
    return "agenda://x-callback-url/create-note?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


# ----------------------------------------------------------------- drafts

def drafts_body(note):
    text = note.text.strip()
    if note.title and not text.startswith("# "):
        text = "# %s\n\n%s" % (note.title, text)
    return text


def drafts_url(note, settings):
    q = [("text", drafts_body(note))]
    for t in note.tags:
        q.append(("tag", t))
    if note.flag:
        q.append(("flagged", "true"))
    return "drafts://x-callback-url/create?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)


def drafts_cli(note, settings):
    argv = [mc.cmd("drafts"), "create"]
    for t in note.tags:
        argv += ["--tag", t]
    if note.flag:
        argv.append("--flagged")
    argv.append(drafts_body(note))
    return argv


def run_open(url, foreground):
    opener = mc.cmd("open")
    if not mc.which(opener):
        raise NoteError("`%s` not found (macOS only)" % os.path.basename(opener))
    argv = [opener] + ([] if foreground else ["-g"]) + [url]
    rc, _o, e = mc.run_capture(argv, timeout=10)
    if rc != 0:
        raise NoteError("open failed: %s" % (e.strip() or rc))
    return "url"


def run_drafts_cli(note, settings):
    if not mc.which(mc.cmd("drafts")):
        raise NoteError("`drafts` CLI not installed")
    rc, _o, e = mc.run_capture(drafts_cli(note, settings), timeout=15)
    if rc != 0:
        raise NoteError("drafts CLI failed: %s" % (e.strip()[:80] or rc))
    return "cli"


def try_methods(typ, note, settings, methods):
    """Try each method in order. Returns (method_used, index_used, failures). Raises NoteError if all fail."""
    failures = []
    for i, m in enumerate(methods):
        try:
            if typ == "agenda" and m == "mcp":
                used = agenda_mcp(agenda_mcp_url(settings), note, settings)
            elif typ == "agenda" and m == "url":
                used = run_open(agenda_url(note, settings), note.open_app)
            elif typ == "drafts" and m == "cli":
                used = run_drafts_cli(note, settings)
            elif typ == "drafts" and m == "url":
                used = run_open(drafts_url(note, settings), note.open_app)
            else:
                failures.append("%s: unknown method" % m)
                continue
            return used, i, failures
        except NoteError as exc:
            failures.append("%s: %s" % (m, exc))
    raise NoteError("; ".join(failures) or "no methods configured")


# ----------------------------------------------------------------- outbox

def outbox_file(dest, when):
    d = os.path.join(mc.mf_root(), "files", "inbox", "outbox", dest)
    base = "%s-%s" % (when.strftime("%Y%m%d-%H%M%S"), mc.host())
    path = os.path.join(d, base + ".md")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(d, "%s-%d.md" % (base, n))
    return path


def write_outbox(dest, typ, note, when):
    path = outbox_file(dest, when)
    meta = [("dest", dest), ("type", typ), ("title", note.title), ("tags", note.tags), ("project", note.project),
            ("date", note.date), ("flag", bool(note.flag)), ("open", bool(note.open_app)),
            ("created", when.strftime("%Y-%m-%d %H:%M:%S")), ("host", mc.host())]
    lines = ["---"] + ["%s: %s" % (k, fm_value(v)) for k, v in meta] + ["---", "", note.text.strip(), ""]
    mc.write_text(path, "\n".join(lines))
    return path


def read_outbox(path):
    doc = fm.parse_file(path)
    m = doc.meta
    return m.get("dest", ""), m.get("type", ""), Note(doc.body.strip(), title=str(m.get("title", "")), tags=list(m.get("tags") or []),
                                                        project=str(m.get("project", "")), date=str(m.get("date", "")),
                                                        flag=bool(m.get("flag")), open_app=bool(m.get("open")))


# ----------------------------------------------------------------- log

def log_note(dest, method):
    """Local log: time, destination, method only. Never the text."""
    p = os.path.join(mc.local_state_dir(), "notes.log")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("%s\t%s\t%s\n" % (mc.now().strftime("%Y-%m-%dT%H:%M:%S"), dest, method))
    except OSError:
        pass


# ----------------------------------------------------------------- the main operation

def capture(cfg, dest, note, dry=False):
    """Capture a note. Returns a result dict: dest, type, method, status (noted|queued), path, exit, message."""
    typ, settings = resolve_dest(cfg, dest)
    when = mc.now()
    tags = []
    for t in list(settings.get("tags") or []) + list(note.tags):
        if t not in tags:
            tags.append(t)
    note.tags = tags
    res = {"dest": dest, "type": typ, "method": "", "status": "noted", "path": "", "exit": 0, "message": ""}
    mac = mc.is_mac()
    if typ in ("inbox", "file"):
        if typ == "inbox":
            path = inbox_path(cfg, when)
        else:
            raw = settings.get("path")
            if not raw:
                raise NoteError("destination %r (type file) needs a path" % dest)
            path = mc.rel_to_mf(raw)
            if not mc.is_inside(path, mc.mf_root()):
                raise NoteError("file destinations must stay inside machine-flows; refusing %s" % mc.tilde(path))
        res["method"] = "file"
        res["path"] = mc.tilde(path)
        if dry:
            res["status"] = "dry-run"
            res["message"] = "would append to %s" % mc.tilde(path)
            return res
        if typ == "inbox":
            append_entry(path, note, when, header="# Notes %s (%s)" % (when.strftime("%Y-%m-%d"), mc.host()))
        else:
            append_entry(path, note, when, header="# Notes")
        res["message"] = "noted → %s (%s)" % (dest, mc.tilde(path))
        log_note(dest, "file")
        return res
    # agenda / drafts
    default_methods = ["mcp", "url"] if typ == "agenda" else ["cli", "url"]
    methods = list(settings.get("method") or default_methods)
    if dry:
        res["status"] = "dry-run"
        if not mac:
            res["method"] = "outbox"
            res["path"] = mc.tilde(outbox_file(dest, when))
            res["message"] = "would queue to outbox/%s (this machine is not a Mac; deliver with: mach note flush on %s)" % (dest, mc.mac_machine(cfg) or "the Mac")
        else:
            res["method"] = ",".join(methods)
            res["message"] = "would try: %s" % ", ".join(methods)
            if "url" in methods:
                u = agenda_url(note, settings) if typ == "agenda" else drafts_url(note, settings)
                res["message"] += " (url: %s)" % mc.truncate(u, 110)
        return res
    reason = ""
    if mac:
        try:
            used, idx, failures = try_methods(typ, note, settings, methods)
            res["method"] = used
            if idx == 0:
                res["message"] = "noted → %s via %s" % (dest, used)
                log_note(dest, used)
                return res
            res["exit"] = mc.EXIT_WARN
            res["message"] = "noted → %s via %s (%s)" % (dest, used, failures[0] if failures else "preferred method failed")
            log_note(dest, used + "-fallback")
            return res
        except NoteError as exc:
            reason = str(exc)
    else:
        reason = "%s needs macOS" % typ
    path = write_outbox(dest, typ, note, when)
    res["status"] = "queued"
    res["method"] = "outbox"
    res["path"] = mc.tilde(path)
    res["exit"] = mc.EXIT_WARN
    res["message"] = "queued → outbox/%s (%s; deliver with: mach note flush on %s)" % (dest, reason, mc.mac_machine(cfg) or "the Mac")
    log_note(dest, "outbox")
    return res


def flush(cfg, apply):
    """Deliver outbox files (macOS). Preview unless apply. Returns (lines, exit_code)."""
    root = os.path.join(mc.mf_root(), "files", "inbox", "outbox")
    lines = []
    if not mc.is_mac():
        return ["note flush delivers outbox items into Agenda/Drafts and only runs on macOS; this machine is %s" % mc.host()], mc.EXIT_WARN
    files = []
    if os.path.isdir(root):
        for dest in sorted(os.listdir(root)):
            dp = os.path.join(root, dest)
            if os.path.isdir(dp):
                files.extend(os.path.join(dp, f) for f in sorted(os.listdir(dp)) if f.endswith(".md"))
    if not files:
        return ["outbox is empty"], mc.EXIT_OK
    failed = 0
    for f in files:
        dest, typ, note = read_outbox(f)
        rel = os.path.relpath(f, root)
        if not apply:
            lines.append("would deliver %s → %s (%s)" % (rel, dest, typ))
            continue
        try:
            t, settings = resolve_dest(cfg, dest) if dest else (typ, {})
            if t == "file":
                raise NoteError("file destinations are not delivered through the outbox")
            methods = list(settings.get("method") or (["mcp", "url"] if t == "agenda" else ["cli", "url"]))
            used, _idx, _f = try_methods(t, note, settings, methods)
            os.remove(f)
            lines.append("delivered %s via %s (removed)" % (rel, used))
            log_note(dest or typ, "flush-" + used)
        except NoteError as exc:
            failed += 1
            lines.append("FAILED %s: %s (kept in the outbox)" % (rel, exc))
    if not apply:
        lines.append("preview only: run `mach note flush --apply` to deliver and remove these files")
    return lines, (mc.EXIT_WARN if failed else mc.EXIT_OK)
