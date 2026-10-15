"""mach_runs: run records (files/runs/YYYY/MM/<id>/run.md) for the work gateway.

A run record is a folder:
  run.md        frontmatter (id, created, machine, tool, path, status, input, outputs ...) + steps table + notes
  input.md      a copy of the input (prompt document, task text, or flow input)
  output-N.md / step-N-*.md   outputs
Full agent output is also saved as transcript.txt in the run folder.
Each machine writes only its own runs.
"""
import os
import re

import mach_common as mc
import frontmatter as fm

STATUSES = ["queued", "running", "waiting-approval", "done", "failed", "cancelled"]
FM_ORDER = ["id", "created", "updated", "machine", "tool", "path", "status", "kind", "title", "input", "source",
            "flow", "approval", "permission", "output", "outputs", "gate", "current_step", "reason"]


def fm_value(v):
    if isinstance(v, list):
        return "[" + ", ".join(fm_scalar(x) for x in v) + "]"
    return fm_scalar(v)


def fm_scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if s == "" or re.search(r"[#:\[\]{}\",']|^\s|\s$|^[-?]", s) or s in ("true", "false") or re.match(r"^-?\d+$", s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


class Run(object):
    def __init__(self, directory):
        self.dir = directory
        self.meta = {}
        self.steps = []     # dicts: n, step, tool, status, output
        self.notes = []

    # ---- identity
    @property
    def id(self):
        return str(self.meta.get("id", os.path.basename(self.dir)))

    @property
    def status(self):
        return str(self.meta.get("status", ""))

    def path_of(self, name):
        return os.path.join(self.dir, name)

    # ---- persistence
    def render(self):
        keys = [k for k in FM_ORDER if k in self.meta] + [k for k in self.meta if k not in FM_ORDER]
        lines = ["---"]
        for k in keys:
            lines.append("%s: %s" % (k, fm_value(self.meta[k])))
        lines.append("---")
        lines.append("")
        lines.append("# Run %s" % self.id)
        lines.append("")
        lines.append("%s on %s with %s: %s" % (self.meta.get("kind", "run"), self.meta.get("machine", "?"),
                                              self.meta.get("tool", "?"), self.meta.get("title", "")))
        lines.append("")
        lines.append("## Steps")
        lines.append("")
        lines.append("| # | step | tool | status | output |")
        lines.append("| --- | --- | --- | --- | --- |")
        for s in self.steps:
            cells = [str(s.get("n", "")), s.get("step", ""), s.get("tool", ""), s.get("status", ""), s.get("output", "")]
            lines.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for n in self.notes:
            lines.append("- " + n.replace("\n", " "))
        lines.append("")
        return "\n".join(lines)

    def save(self):
        self.meta["updated"] = mc.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(self.dir, exist_ok=True)
        mc.write_text(os.path.join(self.dir, "run.md"), self.render())

    # ---- mutation helpers
    def set_status(self, status, reason=None, gate=None):
        assert status in STATUSES, status
        if status == "waiting-approval":
            self.meta["approval_requested"] = mc.now().astimezone().isoformat()
        self.meta["status"] = status
        if reason is not None:
            self.meta["reason"] = reason
        elif "reason" in self.meta and status in ("running", "done"):
            self.meta.pop("reason", None)
        if gate is not None:
            if gate:
                self.meta["gate"] = gate
            else:
                self.meta.pop("gate", None)
        self.save()

    def note(self, text):
        self.notes.append(text)

    def add_output(self, relname):
        outs = list(self.meta.get("outputs", []))
        if relname not in outs:
            outs.append(relname)
        self.meta["outputs"] = outs

    def step(self, n):
        for s in self.steps:
            if s.get("n") == n:
                return s
        return None

    def set_step(self, n, **kw):
        s = self.step(n)
        if s is None:
            s = {"n": n, "step": "", "tool": "", "status": "pending", "output": ""}
            self.steps.append(s)
            self.steps.sort(key=lambda x: x["n"])
        s.update(kw)


def _parse_run(directory):
    p = os.path.join(directory, "run.md")
    if not os.path.isfile(p):
        return None
    doc = fm.parse_file(p)
    run = Run(directory)
    run.meta = doc.meta
    mode = None
    for raw in doc.body.split("\n"):
        line = raw.rstrip()
        if line.startswith("## Steps"):
            mode = "steps"
            continue
        if line.startswith("## Notes"):
            mode = "notes"
            continue
        if mode == "steps" and line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 5 and cells[0].isdigit():
                run.steps.append({"n": int(cells[0]), "step": cells[1], "tool": cells[2], "status": cells[3], "output": cells[4]})
        elif mode == "notes" and line.startswith("- "):
            run.notes.append(line[2:])
    return run


def load_run(directory):
    return _parse_run(directory)


def _iter_run_dirs(base):
    if not os.path.isdir(base):
        return
    for year in sorted(os.listdir(base), reverse=True):
        yp = os.path.join(base, year)
        if not (year.isdigit() and os.path.isdir(yp)):
            continue
        for month in sorted(os.listdir(yp), reverse=True):
            mp = os.path.join(yp, month)
            if not (month.isdigit() and os.path.isdir(mp)):
                continue
            for rid in sorted(os.listdir(mp), reverse=True):
                d = os.path.join(mp, rid)
                if os.path.isfile(os.path.join(d, "run.md")):
                    yield d


def list_runs(cfg=None, limit=None):
    out = []
    for d in _iter_run_dirs(mc.runs_dir(cfg)):
        r = _parse_run(d)
        if r is not None:
            out.append(r)
    out.sort(key=lambda r: (str(r.meta.get("created", "")), r.id), reverse=True)
    return out[:limit] if limit else out


def find_run(rid, cfg=None):
    """Exact id, else a unique prefix. Returns Run or None; raises ValueError when ambiguous."""
    matches = []
    for d in _iter_run_dirs(mc.runs_dir(cfg)):
        name = os.path.basename(d)
        if name == rid:
            return _parse_run(d)
        if name.startswith(rid):
            matches.append(d)
    if len(matches) == 1:
        return _parse_run(matches[0])
    if len(matches) > 1:
        raise ValueError("ambiguous run id %r matches %d runs" % (rid, len(matches)))
    return None


def new_run(cfg, *, kind, title, tool, path, input_text, machine=None, status="queued", extra=None, input_name="input.md"):
    """Allocate a unique run id and folder, write input copy and run.md."""
    t = mc.now()
    h = mc.host()
    slug = mc.slugify(title, 30)
    base_id = "%s-%s-%s" % (t.strftime("%Y%m%d-%H%M"), h, slug)
    folder = os.path.join(mc.runs_dir(cfg), t.strftime("%Y"), t.strftime("%m"))
    rid, n = base_id, 1
    while os.path.exists(os.path.join(folder, rid)):
        n += 1
        rid = "%s-%d" % (base_id, n)
    run = Run(os.path.join(folder, rid))
    first_line = (input_text or "").strip().split("\n")[0]
    run.meta = {
        "id": rid,
        "created": t.strftime("%Y-%m-%d %H:%M:%S"),
        "machine": machine or h,
        "tool": tool,
        "path": mc.tilde(path) if path else "",
        "status": status,
        "kind": kind,
        "title": mc.truncate(title, 80),
        "input": mc.truncate(first_line, 120),
    }
    run.meta["writer"] = h
    if extra:
        run.meta.update(extra)
    os.makedirs(run.dir, exist_ok=True)
    mc.write_text(os.path.join(run.dir, input_name), input_text if input_text.endswith("\n") else input_text + "\n")
    run.meta["input_file"] = input_name
    run.save()
    return run


def tee_exec(argv, cwd, logfile, stream=True):
    """Run a tool headless, stream its output, tee into a local log. Returns (rc, text)."""
    import subprocess
    import sys
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    chunks = []
    try:
        p = subprocess.Popen(argv, cwd=cwd or None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, universal_newlines=True)
    except OSError as exc:
        return 127, "cannot run %s: %s" % (argv[0], exc)
    with open(logfile, "a", encoding="utf-8") as log:
        log.write("$ %s\n" % mc.shown_cmd(argv))
        for line in p.stdout:
            chunks.append(line)
            log.write(line)
            if stream:
                sys.stdout.write(line)
                sys.stdout.flush()
    p.wait()
    return p.returncode, "".join(chunks)


def log_path(run_id):
    return os.path.join(mc.log_dir(), run_id + ".log")
