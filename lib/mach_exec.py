"""mach_exec: routing, prompt-document runs, flows, gates and approvals (the work gateway engine).

Safety model (v1):
  * tools run headless and READ-ONLY unless --write is given;
  * mach itself writes the `output` file, and only inside machine-flows, the run folder or the working path;
  * anything outward (output: pr | linear-comment, or a flow handoff step) stops at a gate (exit 3) and, even
    after approval, only produces a ready-to-run command or draft file: mach never posts, opens PRs or comments.
"""
import json
import os
import re
import shlex
import sys

import mach_common as mc
import mach_runs as mr
import frontmatter as fm

OUTWARD = fm.OUTWARD_OUTPUTS


class Reporter(object):
    """Human lines go to stdout, or to stderr when --json owns stdout."""

    def __init__(self, json_mode=False):
        self.json = json_mode

    def say(self, msg=""):
        print(msg, file=sys.stderr if self.json else sys.stdout)


# ----------------------------------------------------------------- routing

def git_root(path):
    cur = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def project_map_lookup(ident):
    """Resolve a project id from service-memories/project-map.tsv (first column id, first path-like column)."""
    p = os.path.join(mc.mf_root(), "service-memories", "project-map.tsv")
    for line in mc.read_text(p).splitlines():
        cols = line.split("\t")
        if cols and cols[0].strip() == ident:
            for c in cols[1:]:
                c = c.strip()
                if c.startswith("~") or c.startswith("/"):
                    return mc.expand(c)
    return None


def resolve_path(path):
    if not path:
        root = git_root(os.getcwd())
        return root or mc.mf_root()
    if "/" not in path and not os.path.exists(mc.expand(path)):
        hit = project_map_lookup(path)
        if hit:
            return hit
    p = mc.expand(path)
    return p if os.path.isabs(p) else os.path.join(mc.mf_root(), p)


def route(cfg, tool=None, machine=None, path=None, permission=None, write=False):
    """Decide tool, machine, working path and permission. Returns a dict with a `why` list."""
    why = []
    work = resolve_path(path)
    proj_tool, proj_machine, proj_name = None, None, None
    for name, proj in sorted(cfg.section("routes.project").items()):
        if not isinstance(proj, dict) or not proj.get("path"):
            continue
        if mc.is_inside(work, mc.expand(proj["path"])):
            proj_tool, proj_machine, proj_name = proj.get("tool"), proj.get("machine"), name
            break
    if tool and tool != "auto":
        t = tool
        why.append("tool from flag/document")
    elif proj_tool:
        t = proj_tool
        why.append("tool from project route '%s'" % proj_name)
    else:
        t = cfg.get("routes.default_tool", "claude")
        why.append("default tool (routes.default_tool)")
    if machine and machine != "any":
        m = machine
        why.append("machine from flag/document")
    elif proj_machine and machine != "any":
        m = proj_machine
        why.append("machine from project route '%s'" % proj_name)
    else:
        m = cfg.get("routes.default_machine", "") or mc.host()
        why.append("current machine" if m == mc.host() else "machine from routes.default_machine")
    perm = "write" if write else (permission or cfg.get("routes.permission", "read-only"))
    if perm not in ("read-only", "write"):
        perm = "read-only"
    return {"tool": t, "machine": m, "path": work, "permission": perm, "why": why}


def show_route(rep, r, output="run record + stdout"):
    rep.say("route:")
    rep.say("  tool        %s" % r["tool"])
    rep.say("  machine     %s%s" % (r["machine"], "" if r["machine"] == mc.host() else "  (not this machine: v1 queues it, no SSH execution yet)"))
    rep.say("  path        %s" % mc.tilde(r["path"]))
    rep.say("  permission  %s" % r["permission"])
    rep.say("  output      %s" % output)
    rep.say("  why         %s" % "; ".join(r["why"]))


def require_tool(tool, cfg, rep):
    if tool not in mc.KNOWN_TOOLS:
        mc.die("unknown tool %r: use one of %s" % (tool, ", ".join(mc.KNOWN_TOOLS)))
    if not mc.tool_available(tool, cfg):
        mc.die("tool %r not found on PATH (looked for %r). Install it or pick another with --tool." % (tool, mc.tool_binary_name(tool, cfg)))


def run_dir_rel(run):
    return mc.tilde(run.dir)


# ----------------------------------------------------------------- tool execution

def exec_ai(run, n, tool, prompt, workdir, write, cfg, stream, outname=None):
    argv, _pidx, note = mc.tool_argv(tool, prompt, write=write, cfg=cfg)
    if note:
        run.note("%s: %s" % (tool, note))
    cwd = workdir if workdir and os.path.isdir(workdir) else None
    rc, text = mr.tee_exec(argv, cwd, mr.log_path(run.id), stream)
    outname = outname or "output-%d.md" % n
    mc.write_text(run.path_of(outname), text)
    run.add_output(outname)
    return rc, text, outname


def fill(template, ctx):
    def rep(m):
        k = m.group(1)
        return str(ctx[k]) if k in ctx else m.group(0)
    return re.sub(r"\{(\w+)\}", rep, template)


# ----------------------------------------------------------------- outputs

def resolve_output(output, title, work):
    """Return (kind, path): kind is stdout | pr | linear-comment | file."""
    o = str(output or "").strip()
    if o in ("", "stdout"):
        return "stdout", None
    if o in OUTWARD:
        return o, None
    date = mc.now().strftime("%Y-%m-%d")
    o = o.replace("YYYY-MM-DD", date)
    o = re.sub(r"(?<![A-Za-z])slug(?![A-Za-z])", mc.slugify(title, 40), o)
    p = mc.expand(o)
    if p.startswith("./"):
        p = os.path.join(work, p[2:])
    elif not os.path.isabs(p):
        p = os.path.join(mc.mf_root(), p)
    return "file", os.path.normpath(p)


def output_allowed(path, work):
    for root in (mc.mf_root(), work, mc.runs_dir()):
        if root and mc.is_inside(path, root):
            return True
    return False


def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists("%s-%d%s" % (base, n, ext)):
        n += 1
    return "%s-%d%s" % (base, n, ext)


def write_output_file(path, text):
    path = unique_path(path)
    mc.write_text(path, text if text.endswith("\n") else text + "\n")
    return path


TICKET_RE = re.compile(r"\b([A-Za-z]{2,6}-\d+)\b")


def ticket_of(text):
    m = TICKET_RE.search(text or "")
    return m.group(1).upper() if m else ""


def make_handoff(run, kind, title, body_text):
    """Write a ready-to-run command or draft for an outward action. mach never executes it."""
    if kind == "pr":
        body_file = "handoff-pr-body.md"
        mc.write_text(run.path_of(body_file), body_text if body_text.endswith("\n") else body_text + "\n")
        tk = ticket_of(title) or ticket_of(run.meta.get("input", ""))
        pr_title = title if title.startswith("[") or not tk else "[%s] %s" % (tk, title)
        cmd = "gh pr create --title %s --body-file %s" % (shlex.quote(pr_title), shlex.quote(mc.tilde(run.path_of(body_file))))
        text = "# Handoff: open a pull request\n\nmach never runs `gh`. Review the body, then run this from the repo/branch:\n\n```bash\n%s\n```\n\nBody: `%s`\nLink the Linear ticket in the PR (title format `[TICKET-ID] Short description`).\n" % (cmd, body_file)
        name = "handoff-pr.md"
    else:
        name = "handoff-linear-comment.md"
        text = "# Handoff: Linear comment (draft)\n\nmach never posts. Review, then paste it into the issue (or use the Linear MCP yourself):\n\n---\n\n%s\n" % body_text
    mc.write_text(run.path_of(name), text)
    run.add_output(name)
    return name


# ----------------------------------------------------------------- prompt documents

def prompt_for(doc):
    meta = doc.meta
    typ = meta.get("type")
    head = []
    if typ == "task":
        head.append("Goal: %s" % meta.get("goal", ""))
    elif typ == "research":
        head.append("Question: %s" % meta.get("question", ""))
        src = meta.get("sources") or ["web"]
        head.append("Allowed sources: %s. Cite every source with a link and the date checked. Lead with the answer, then the evidence, and end with a '## Sources' section." % ", ".join(src))
        if meta.get("depth"):
            head.append("Depth: %s" % meta["depth"])
    return ("\n".join(head) + "\n\n" + doc.body.strip()).strip()


def plan_doc(doc, cfg, tool=None, machine=None, path=None, write=False):
    meta = doc.meta
    rt = route(cfg, tool=tool or meta.get("tool"), machine=machine or meta.get("machine"), path=path or meta.get("path") or None,
               permission=None, write=write)
    okind, opath = resolve_output(meta.get("output", "stdout"), meta.get("title", "run"), rt["path"])
    approval = meta.get("approval", "none")
    gates = []
    if approval == "before-run":
        gates.append("before-run")
    if okind == "file" and approval == "before-apply":
        gates.append("apply")
    if okind in OUTWARD:
        gates.append("outward")
    return {"route": rt, "output_kind": okind, "output_path": opath, "approval": approval,
            "gates": gates, "prompt": prompt_for(doc), "title": meta.get("title", "run"), "type": meta.get("type")}


def describe_plan(rep, p, run_id=None):
    show_route(rep, p["route"], output=("%s%s" % (p["output_kind"], (": " + mc.tilde(p["output_path"])) if p["output_path"] else "")))
    rep.say("  approval    %s%s" % (p["approval"], ("  gates: " + ", ".join(p["gates"])) if p["gates"] else ""))


def source_label(path):
    ap = os.path.realpath(path)
    root = os.path.realpath(mc.mf_root())
    if mc.is_inside(ap, root):
        return os.path.relpath(ap, root)
    return mc.tilde(ap)


def start_prompt_run(cfg, doc, doc_path, rep, *, tool=None, machine=None, path=None, write=False, queue=False, json_mode=False):
    """Create the run record for a validated prompt document and (unless queued) execute it. Returns (run, exit)."""
    plan = plan_doc(doc, cfg, tool=tool, machine=machine, path=path, write=write)
    rt = plan["route"]
    with open(doc_path, "r", encoding="utf-8") as fh:
        original = fh.read()
    meta = {"source": source_label(doc_path), "approval": plan["approval"], "permission": rt["permission"],
            "output": doc.meta.get("output", "stdout"), "path_abs": rt["path"], "type": plan["type"]}
    target_machine = rt["machine"] if rt["machine"] != "any" else mc.host()
    # `machine: any` -> background machine for queued work; interactive runs execute here
    if (machine or doc.meta.get("machine")) == "any" and queue:
        target_machine = mc.background_machine(cfg)
    run = mr.new_run(cfg, kind="run", title=plan["title"], tool=rt["tool"], path=rt["path"], input_text=original,
                     machine=target_machine, status="queued", extra=meta, input_name="input.md")
    run.set_step(1, step="run", tool=rt["tool"], status="pending")
    run.save()
    if queue:
        rep.say("queued %s (machine: %s)" % (run.id, target_machine))
        return run, 0
    if target_machine != mc.host():
        run.note("queued for %s: v1 has no SSH execution; run `mach run --inbox` or continue on that machine" % target_machine)
        run.save()
        rep.say("queued %s for machine %s (v1: no SSH execution yet; it runs when that machine picks it up)" % (run.id, target_machine))
        return run, 0
    return run, continue_prompt_run(run, cfg, rep, json_mode=json_mode)


def continue_prompt_run(run, cfg, rep, json_mode=False):
    """Drive a prompt-document run through its stages and gates. Returns an exit code."""
    doc = fm.parse_file(run.path_of("input.md"))
    fm.validate(doc)
    work = mc.expand(run.meta.get("path_abs", "")) or mc.mf_root()
    plan = plan_doc(doc, cfg, tool=run.meta.get("tool"), machine=None, path=work, write=(run.meta.get("permission") == "write"))
    tool = run.meta.get("tool")
    approved = list(run.meta.get("approved", []))
    stage = run.meta.get("stage", "start")
    title = plan["title"]

    def gate(name, message):
        run.meta["approved"] = approved
        run.set_step(1, status="waiting-approval")
        run.set_status("waiting-approval", reason=message, gate=name)
        rep.say("waiting for approval (%s): %s" % (name, message))
        rep.say("  approve: mach approve %s     reject: mach reject %s \"reason\"" % (run.id, run.id))
        if json_mode:
            mc.emit_json({"id": run.id, "status": "waiting-approval", "gate": name, "reason": message})
        return mc.EXIT_WAIT

    if stage == "start":
        if "before-run" in plan["gates"] and "before-run" not in approved:
            return gate("before-run", "approval: before-run, nothing has executed yet")
        if plan["output_kind"] == "file" and not output_allowed(plan["output_path"], work):
            run.set_status("failed", reason="output path outside machine-flows, the run folder and the working path")
            mc.eprint("mach: refusing to write outside machine-flows/working path: %s" % mc.tilde(plan["output_path"]))
            return mc.EXIT_FAIL
        run.set_status("running", gate="")
        run.set_step(1, status="running")
        run.save()
        if not mc.tool_available(tool, cfg):
            run.set_step(1, status="failed")
            run.set_status("failed", reason="tool %s not found on PATH" % tool)
            mc.eprint("mach: tool %r not found on PATH" % tool)
            return mc.EXIT_FAIL
        rc, text, outname = exec_ai(run, 1, tool, plan["prompt"], work, run.meta.get("permission") == "write", cfg, stream=not json_mode)
        if rc != 0:
            run.set_step(1, status="failed", output=outname)
            run.set_status("failed", reason="%s exited %d" % (tool, rc))
            mc.eprint("mach: %s exited %d (run %s)" % (tool, rc, run.id))
            return mc.EXIT_FAIL
        run.meta["stage"] = "executed"
        run.set_step(1, status="executed", output=outname)
        run.save()
    text = mc.read_text(run.path_of("output-1.md"))
    kind, opath = plan["output_kind"], plan["output_path"]
    if kind in OUTWARD:
        if "outward" not in approved:
            return gate("outward", "output '%s' leaves this machine: review %s first" % (kind, os.path.join(run_dir_rel(run), "output-1.md")))
        name = make_handoff(run, kind, title, text)
        run.set_step(1, status="handoff", output=name)
        run.note("outward step approved; handoff written (%s). mach does not run it." % name)
        run.set_status("done", gate="")
        rep.say("handoff ready: %s" % mc.tilde(run.path_of(name)))
    elif kind == "file":
        if "apply" in plan["gates"] and "apply" not in approved:
            return gate("apply", "review %s, then approve to write %s" % (os.path.join(run_dir_rel(run), "output-1.md"), mc.tilde(opath)))
        written = write_output_file(opath, text)
        run.meta["outputs"] = list(run.meta.get("outputs", [])) + [mc.tilde(written)]
        run.set_step(1, status="done")
        run.set_status("done", gate="")
        rep.say("wrote %s" % mc.tilde(written))
    else:
        run.set_step(1, status="done")
        run.set_status("done", gate="")
        if json_mode:
            pass
    if json_mode:
        mc.emit_json({"id": run.id, "status": run.status, "outputs": run.meta.get("outputs", []), "run_dir": mc.tilde(run.dir)})
    else:
        rep.say("run %s: %s" % (run.id, run.status))
    return mc.EXIT_OK


# ----------------------------------------------------------------- inbox

def inbox_dir():
    return os.path.join(mc.mf_root(), "files", "inbox", "prompts")


def outbox_root():
    return os.path.join(mc.mf_root(), "files", "inbox", "outbox")


def inbox_items(cfg, runs=None):
    """Every prompt doc in files/inbox/prompts with its target machine and whether it already ran."""
    runs = runs if runs is not None else mr.list_runs(cfg)
    seen = set(str(r.meta.get("source", "")) for r in runs if r.status != "cancelled")
    out = []
    d = inbox_dir()
    if not os.path.isdir(d):
        return out
    bg = mc.background_machine(cfg)
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md") or fn.lower() == "readme.md":
            continue
        p = os.path.join(d, fn)
        doc = fm.load_prompt_doc(p)
        label = source_label(p)
        target = str(doc.meta.get("machine", "")) if doc.ok else ""
        eff = bg if target in ("any", "") else target
        out.append({"path": p, "source": label, "name": fn, "ok": doc.ok, "errors": doc.errors,
                    "machine": target or "?", "executor": eff, "due": str(doc.meta.get("due", "")) if doc.ok else "",
                    "title": str(doc.meta.get("title", fn)), "ran": label in seen, "doc": doc})
    return out


def outbox_items():
    out = []
    root = outbox_root()
    if not os.path.isdir(root):
        return out
    t = mc.now().timestamp()
    for dest in sorted(os.listdir(root)):
        dp = os.path.join(root, dest)
        if not os.path.isdir(dp):
            continue
        for fn in sorted(os.listdir(dp)):
            fp = os.path.join(dp, fn)
            if os.path.isfile(fp):
                age_h = max(0.0, (t - os.path.getmtime(fp)) / 3600.0)
                out.append({"dest": dest, "name": fn, "path": fp, "age_hours": round(age_h, 1)})
    return out


# ----------------------------------------------------------------- flows

def load_recipe(name):
    cands = [os.path.join(mc.mf_root(), "autoflows", "mach", name + ".md"),
             os.path.join(mc.mach_home(), "flows", name + ".md")]
    for p in cands:
        if os.path.isfile(p):
            return fm.parse_recipe_file(p), p
    return None, None


def list_recipes():
    seen = {}
    for label, d in (("autoflows", os.path.join(mc.mf_root(), "autoflows", "mach")), ("built-in", os.path.join(mc.mach_home(), "flows"))):
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".md") and fn[:-3] not in seen:
                    seen[fn[:-3]] = (label, os.path.join(d, fn))
    return seen


def next_plan_number():
    nums = [0]
    for d in (os.path.join(mc.mf_root(), "plans"), os.path.join(mc.mf_root(), "plans", "archived")):
        if os.path.isdir(d):
            for fn in os.listdir(d):
                m = re.match(r"^(\d\d)-", fn)
                if m:
                    nums.append(int(m.group(1)))
    return "%02d" % (max(nums) + 1)


def flow_ctx(run, rec, input_text, prev_name):
    t = input_text or ""
    tk = ticket_of(t)
    rest = TICKET_RE.sub("", t, count=1).strip() if tk else t
    branch = (tk.lower() + "-" + mc.slugify(rest, 30)).strip("-") if tk else mc.slugify(t, 40)
    prev_text = ""
    if prev_name:
        prev_text = mc.read_text(run.path_of(prev_name))[:20000]
    steps_text = []
    for s in run.steps:
        if s.get("output") and s["output"].endswith(".md") and os.path.isfile(run.path_of(s["output"])):
            steps_text.append("### Step %s: %s\n\n%s" % (s["n"], s["step"], mc.read_text(run.path_of(s["output"]))[:8000].strip()))
    return {"input": t, "date": mc.now().strftime("%Y-%m-%d"), "host": mc.host(), "run_dir": mc.tilde(run.dir),
            "prev": mc.tilde(run.path_of(prev_name)) if prev_name else "", "prev_text": prev_text,
            "steps_text": "\n\n".join(steps_text), "ticket": tk, "branch": branch,
            "brief": run.path_of("brief.md"), "next_plan": next_plan_number(), "slug": mc.slugify(t, 40)}


def describe_recipe(rep, rec, input_text, cfg):
    rep.say("flow steps:")
    for st in rec.steps:
        if st.kind == "gate":
            rep.say("  %d. GATE   %s" % (st.number, st.gate))
        elif st.kind == "cmd":
            rep.say("  %d. cmd    mach %s" % (st.number, mc.truncate(st.cmd, 70)))
        elif st.kind == "handoff":
            rep.say("  %d. HANDOFF %s (never executed by mach)" % (st.number, st.title))
        else:
            tool = st.tool if st.tool and st.tool != "auto" else cfg.get("routes.default_tool", "claude")
            argv, pidx, _n = mc.tool_argv(tool, fill(st.prompt, {"input": input_text}), cfg=cfg)
            rep.say("  %d. ai     %s: %s" % (st.number, st.title, mc.shown_cmd(argv, pidx)))


def start_flow(cfg, name, input_text, rep, *, write=False, json_mode=False, queue=False):
    rec, src = load_recipe(name)
    if rec is None:
        mc.die("unknown flow %r (try: mach flow list)" % name)
    if rec.errors:
        for ln, msg in rec.errors:
            mc.eprint("%s:%d: error: %s" % (src, ln, msg))
        return None, mc.EXIT_FAIL
    run = mr.new_run(cfg, kind="flow", title="%s: %s" % (name, input_text or "(no input)"), tool="auto", path=mc.mf_root(),
                     input_text=input_text or "(no input)", status="queued",
                     extra={"flow": name, "permission": "write" if write else "read-only", "recipe": os.path.basename(src)})
    mc.write_text(run.path_of("recipe.md"), mc.read_text(src))
    for st in rec.steps:
        run.set_step(st.number, step=st.title or st.kind, tool=(st.tool or ("" if st.kind != "ai" else "auto")), status="pending")
    run.save()
    if queue:
        rep.say("queued %s" % run.id)
        return run, 0
    return run, continue_flow(run, cfg, rep, json_mode=json_mode)


def continue_flow(run, cfg, rep, json_mode=False):
    rec = fm.parse_recipe_file(run.path_of("recipe.md"))
    input_text = mc.read_text(run.path_of("input.md")).strip()
    if input_text == "(no input)":
        input_text = ""
    write = run.meta.get("permission") == "write"
    work = mc.mf_root()
    warnings = 0
    run.set_status("running", gate="")
    prev_name = ""
    for s in run.steps:  # last finished output feeds {prev}
        if s.get("status") in ("done", "handoff", "approved") and s.get("output") and s["output"].endswith(".md"):
            prev_name = s["output"]
    for st in rec.steps:
        row = run.step(st.number) or {}
        if row.get("status") in ("done", "approved", "handoff", "skipped"):
            continue
        ctx = flow_ctx(run, rec, input_text, prev_name)
        slug = mc.slugify(st.title or st.kind, 24)
        if st.kind == "gate":
            run.set_step(st.number, status="waiting-approval")
            run.meta["current_step"] = st.number
            run.set_status("waiting-approval", reason=fill(st.gate, ctx), gate="step")
            rep.say("")
            rep.say("GATE at step %d: %s" % (st.number, fill(st.gate, ctx)))
            rep.say("  approve: mach approve %s    reject: mach reject %s \"reason\"" % (run.id, run.id))
            if json_mode:
                mc.emit_json({"id": run.id, "status": "waiting-approval", "step": st.number, "reason": fill(st.gate, ctx)})
            return mc.EXIT_WAIT
        if st.machine and st.machine not in ("any", mc.host()):
            run.set_step(st.number, status="skipped")
            run.note("step %d skipped: it names machine %s (v1 has no SSH execution)" % (st.number, st.machine))
            warnings += 1
            continue
        run.meta["current_step"] = st.number
        run.set_step(st.number, status="running")
        run.save()
        rep.say("step %d/%d: %s" % (st.number, len(rec.steps), st.title or st.kind))
        if st.kind == "ai":
            tool = st.tool if st.tool and st.tool != "auto" else cfg.get("routes.default_tool", "claude")
            if not mc.tool_available(tool, cfg):
                run.set_step(st.number, status="failed", tool=tool)
                run.set_status("failed", reason="tool %s not found on PATH (step %d)" % (tool, st.number))
                mc.eprint("mach: tool %r not found on PATH" % tool)
                return mc.EXIT_FAIL
            outname = os.path.basename(st.output) if st.output else "step-%d-%s.md" % (st.number, slug)
            rc, text, outname = exec_ai(run, st.number, tool, fill(st.prompt, ctx), work, write, cfg, stream=False, outname=outname)
            if rc != 0:
                run.set_step(st.number, status="failed", tool=tool, output=outname)
                run.set_status("failed", reason="step %d: %s exited %d" % (st.number, tool, rc))
                mc.eprint("mach: step %d: %s exited %d (run %s)" % (st.number, tool, rc, run.id))
                return mc.EXIT_FAIL
            run.set_step(st.number, status="done", tool=tool, output=outname)
            prev_name = outname
        elif st.kind == "cmd":
            argv = [os.path.join(mc.mach_home(), "bin", "mach")] + shlex.split(fill(st.cmd, ctx))
            rc, out, errtxt = mc.run_capture(argv, timeout=120)
            outname = os.path.basename(st.output) if st.output else "step-%d-%s.md" % (st.number, slug)
            mc.write_text(run.path_of(outname), "$ mach %s\n\n%s%s" % (fill(st.cmd, ctx), out, ("\n" + errtxt) if errtxt.strip() else ""))
            run.add_output(outname)
            if rc >= 2:
                run.set_step(st.number, status="failed", tool="mach", output=outname)
                run.set_status("failed", reason="step %d: mach %s exited %d" % (st.number, st.cmd.split(" ")[0], rc))
                return mc.EXIT_FAIL
            if rc == 1:
                warnings += 1
            run.set_step(st.number, status="done", tool="mach", output=outname)
            prev_name = outname
        elif st.kind == "handoff":
            outname = "handoff-%d-%s.md" % (st.number, slug)
            text = "# Handoff: %s\n\nmach never executes outward or repo-changing steps in v1. Review, then run what you need:\n\n%s\n" % (st.title, fill(st.handoff or st.prompt, ctx))
            mc.write_text(run.path_of(outname), text)
            run.add_output(outname)
            run.set_step(st.number, status="handoff", tool="you", output=outname)
            rep.say("  handoff: %s" % mc.tilde(run.path_of(outname)))
        run.save()
    final = ""
    for s in reversed(run.steps):
        if s.get("output") and s.get("status") in ("done", "handoff"):
            final = s["output"]
            break
    run.set_status("done", gate="")
    if json_mode:
        mc.emit_json({"id": run.id, "status": "done", "outputs": run.meta.get("outputs", []), "run_dir": mc.tilde(run.dir), "warnings": warnings})
    else:
        brief = run.path_of("brief.md")
        shown = brief if os.path.isfile(brief) else (run.path_of(final) if final else "")
        if shown and os.path.isfile(shown):
            rep.say("")
            rep.say(mc.read_text(shown).rstrip())
        rep.say("")
        rep.say("flow %s: done (%s)" % (run.meta.get("flow"), run.id))
    return mc.EXIT_WARN if warnings else mc.EXIT_OK


# ----------------------------------------------------------------- approve / reject

def approve_run(run, cfg, rep, step=None, json_mode=False):
    if run.status != "waiting-approval":
        mc.die("run %s is %s, not waiting-approval" % (run.id, run.status))
    if run.meta.get("kind") == "flow":
        if run.meta.get("gate") == "before-run":
            if step is not None:
                mc.die("run %s waits at the before-run gate, not at a step" % run.id)
            run.note("before-run approved %s" % mc.now().strftime("%Y-%m-%d %H:%M"))
            run.save()
            return continue_flow(run, cfg, rep, json_mode=json_mode)
        cur = run.meta.get("current_step")
        if step is not None and step != cur:
            mc.die("run %s is waiting at step %s, not step %d" % (run.id, cur, step))
        run.set_step(cur, status="approved")
        run.note("step %s approved %s" % (cur, mc.now().strftime("%Y-%m-%d %H:%M")))
        run.save()
        return continue_flow(run, cfg, rep, json_mode=json_mode)
    g = run.meta.get("gate", "")
    if step is not None and step != 1:
        mc.die("prompt runs have a single step (use --step 1 or omit it)")
    approved = list(run.meta.get("approved", []))
    if g and g not in approved:
        approved.append(g)
    run.meta["approved"] = approved
    run.note("gate '%s' approved %s" % (g, mc.now().strftime("%Y-%m-%d %H:%M")))
    run.save()
    return continue_prompt_run(run, cfg, rep, json_mode=json_mode)


def reject_run(run, reason):
    if run.status not in ("waiting-approval", "queued"):
        mc.die("run %s is %s: only queued or waiting-approval runs can be rejected" % (run.id, run.status))
    run.note("rejected %s: %s" % (mc.now().strftime("%Y-%m-%d %H:%M"), reason))
    run.set_status("cancelled", reason=reason, gate="")
