"""mach_sheets_gen: generates the CSVs of the `docs/sheets` set (the mach self-description) from code, never by hand.

Sources: the `# mach-*:` headers of libexec/mach-* (commands, flags), the python/bash sources under lib/ and libexec/ (functions),
config/config.example.toml and mach_common.DEFAULTS (config keys), the DEST_DOCS tables in mach_subsystem / mach_note
(destinations), a generic template list (templates) and config/subsystem.example.toml (subsystem units).
Every source lives in this repo, so the set never depends on a particular machine-flows tree.
Everything is deterministic (sorted, no clock) and uses ~/ or repo-relative paths only.
"""
import ast
import json
import os
import re

import mach_common as mc
import mach_note
import mach_sheets as sh
import mach_subsystem as ss

EXAMPLE_MANIFEST = "subsystem.example.toml"
STATUSES = ("working", "preview-only", "stub")
HEADER_RE = re.compile(r"^# mach-([a-z]+): ?(.*)$")

# (id, file, sheet_name, title, description, source)
SET = [
    ("commands", "commands.csv", "Commands", "Commands and subcommands",
     "One row per mach command or subcommand: usage, summary, which half it belongs to, whether it works, writes and takes --apply / --dry-run.",
     "libexec/mach-* headers (mach-usage, mach-summary, mach-group, mach-subcommands, mach-status, mach-writes)"),
    ("flags", "flags.csv", "Flags", "Flags per command",
     "Every flag found in the command usage lines, with its argument, meaning and default; plus the global options.",
     "libexec/mach-* usage and mach-flag headers; bin/mach"),
    ("functions", "functions.csv", "Functions", "Functions in lib/ and libexec/",
     "Every top-level function, class and method in the python and bash sources, with the one-line purpose from its docstring or comment.",
     "lib/*, libexec/* (python ast, bash function definitions)"),
    ("config-keys", "config-keys.csv", "Config keys", "Configuration keys",
     "Every key in config/config.example.toml and the built-in defaults, with the default and what it does; plus the env overrides.",
     "config/config.example.toml, lib/mach_common.py DEFAULTS and ENV_KEYS"),
    ("destinations", "destinations.csv", "Destinations", "Destinations",
     "Where prompts and notes can be sent: subsystem role destinations and `mach note` destinations.",
     "lib/mach_subsystem.py DEST_DOCS, lib/mach_note.py DEST_DOCS"),
    ("templates", "templates.csv", "Templates", "Prompt-document templates",
     "The generic prompt-document templates a machine-flows tree can hold, what each is for and which command ingests it.",
     "lib/mach_sheets_gen.py TEMPLATES"),
    ("subsystem-units", "subsystem-units.csv", "Subsystem units", "Subsystem units (example)",
     "Units of the example subsystem manifest: kind, parent, lead, repo, folder and whether the binding is verified.",
     "config/subsystem.example.toml"),
]
OWNER = "machine-flows"
GENERATED_BY = "mach sheets refresh mach"

# Flags that mean the same thing everywhere. A command can override one with a `# mach-flag: --flag | meaning | default` header.
# tests/test_sheets.sh fails when a flag in a usage line has no meaning here or in a header.
COMMON_FLAGS = {
    "--apply": ("Carry out the change; without it the command only previews", "preview"),
    "--dry-run": ("Show what would happen and change nothing", ""),
    "--json": ("Machine-readable JSON output", ""),
    "--yes": ("Answer yes to the confirmation", ""),
    "--force": ("Override a safety stop (cap, open boxes, already-exists)", ""),
    "--write": ("Allow the tool to edit files (default is read-only)", "routes.permission (read-only)"),
    "--tool": ("AI tool to use", "routes.default_tool (%s)" % mc.DEFAULTS["routes"]["default_tool"]),
    "--path": ("Working folder or project id for the run", "the working folder"),
    "--machine": ("Machine to run on (a name from [machines], or any)", "routes.default_machine (this machine)"),
    "--queue": ("Record the run as queued instead of executing it now", ""),
    "--host": ("Act on this host", "this machine"),
    "--version": ("Print the mach version", ""),
    "--help": ("Show help", ""),
    "-h": ("Show help", ""),
}


# ----------------------------------------------------------------- command headers

def headers(path):
    """{key: [values]} for every `# mach-<key>: value` line; a usage line that does not start with `mach ` continues the previous one."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = HEADER_RE.match(line.rstrip("\n"))
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            if key == "usage" and out.get("usage") and not val.strip().startswith("mach "):
                out["usage"][-1] += " " + val.strip()
            else:
                out.setdefault(key, []).append(val.rstrip())
    return out


def split_top(text, sep):
    """Split on `sep` outside <>, [], () and quotes."""
    parts, depth, cur, quote = [], 0, "", ""
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "<[(":
            depth += 1
        elif ch in ">])":
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        cur += ch
    parts.append(cur)
    return parts


def kv_tokens(values):
    """`working collect=preview-only` -> ('working', {'collect': 'preview-only'})."""
    default, over = "", {}
    for v in values or []:
        for tok in v.split():
            if "=" in tok:
                k, _, val = tok.partition("=")
                over[k] = val
            elif not default:
                default = tok
    return default, over


def command_scripts(libexec):
    out = []
    for fn in sorted(os.listdir(libexec)):
        if not fn.startswith("mach-") or "." in fn:
            continue
        p = os.path.join(libexec, fn)
        if os.path.isfile(p):
            h = headers(p)
            if h.get("summary"):
                out.append((fn[len("mach-"):], p, h))
    return out


def yes(b):
    return "yes" if b else "no"


def _comment(line):
    m = re.search(r"\s{2,}\((.*)\)\s*$", line)
    return (line[:m.start()], m.group(1)) if m else (line, "")


def command_rows(libexec):
    """commands.csv rows plus {command: usage text} for the flag scan."""
    rows, usage_text = [], {}
    for name, _p, h in command_scripts(libexec):
        subs = " ".join(h.get("subcommands", [])).split()
        summary = h["summary"][0]
        group = h.get("group", ["other"])[0]
        half = h.get("half", [group])[0]
        stat_default, stat_over = kv_tokens(h.get("status"))
        writes_default, writes_over = kv_tokens(h.get("writes"))
        claimed, default_lines, other = {}, [], {}
        for line in h.get("usage", []):
            prefix = "mach %s" % name
            if not (line == prefix or line.startswith(prefix + " ")):
                other.setdefault(line.split()[1], []).append(line)
                continue
            body, comment = _comment(line[len(prefix):].strip())
            segs = [s.strip() for s in split_top(body, "|")]
            hit = False
            bare_tail = segs[-1].split(None, 1)[1] if len(segs) > 1 and " " in segs[-1] else ""
            for i, seg in enumerate(segs):
                tok = seg.split()[0].strip("[]") if seg.split() else ""
                if tok not in subs:
                    continue
                full = seg
                if bare_tail and i < len(segs) - 1 and seg == tok and all(" " not in x for x in segs[:-1]):
                    full = (seg + " " + bare_tail).strip()
                claimed.setdefault(tok, []).append((full, comment))
                hit = True
            if not hit:
                default_lines.append(re.sub(r"\s{2,}", " ", _comment(line)[0]))
        usage_text[name] = (name, " ".join(l for l in h.get("usage", []) if l == "mach " + name or l.startswith("mach %s " % name)))

        def row(cmd, sub, usage, comment, over_key):
            apply_ = "--apply" in usage
            stat = stat_over.get(over_key, stat_default) or "working"
            if over_key in writes_over:
                writes = writes_over[over_key] == "yes"
            else:
                writes = apply_ or writes_default == "yes"
            return [cmd, sub, usage, comment or summary, half if cmd == name else "subsystem", stat, yes(writes), yes(apply_), yes("--dry-run" in usage)]

        if default_lines or not subs:
            rows.append(row(name, "", "; ".join(default_lines), "", ""))
        for sub in subs:
            got = claimed.get(sub, [])
            usage = "; ".join("mach %s %s" % (name, g[0]) for g in got)
            comment = next((g[1] for g in got if g[1]), "")
            rows.append(row(name, sub, usage, comment, sub))
        for cmd in sorted(other):
            usage_text[cmd] = (name, " ".join(other[cmd]))
            r = row(name, "", "; ".join(other[cmd]), "", "")
            r[0], r[4] = cmd, "subsystem"
            rows.append(r)
    return rows, usage_text


COMMAND_COLS = ["command", "subcommand", "usage", "summary", "half", "status", "writes", "has_apply", "has_dry_run"]

ARG = r"(<[^<>\s]+>|[A-Z][A-Za-z0-9_]*(?:\|[A-Za-z0-9_][A-Za-z0-9_-]*)*|[a-zA-Z]+(?:\|[A-Za-z0-9_][A-Za-z0-9_-]*)+)"
FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*|-[A-Za-z])(?![\w-])(?:=(\S+)|[ ]+" + ARG + r"(?![\w-]))?")
FLAG_COLS = ["command", "flag", "argument", "meaning", "default"]


def flag_rows(libexec, mach_bin, usage_text):
    rows = []
    overrides = {}
    for name, _p, h in command_scripts(libexec):
        for line in h.get("flag", []):
            parts = [x.strip() for x in line.split("|")]
            parts += [""] * (3 - len(parts))
            overrides.setdefault(name, {})[parts[0]] = (parts[1], parts[2])
    with open(mach_bin, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"Global options \(before the command\): ([^\\']*)", text)
    sources = [("(global)", m.group(1) if m else "", {})]
    for cmd in sorted(usage_text):
        script, text = usage_text[cmd]
        sources.append((cmd, text, overrides.get(script, {})))
    for cmd, usage, over in sources:
        found = {}
        for m2 in FLAG_RE.finditer(re.sub(r"\s{2,}\([^)]*\)", " ", usage)):
            flag, eq, arg = m2.group(1), m2.group(2), m2.group(3)
            found.setdefault(flag, eq or arg or "")
        for flag, arg in found.items():
            meaning, default = over.get(flag) or COMMON_FLAGS.get(flag, ("", ""))
            rows.append([cmd, flag, arg, meaning, default])
    return rows


CODE_COLS = {"command", "subcommand", "usage", "flag", "argument", "default"}
_SPAN = re.compile(r"(`+)(?:(?!\1).)+\1")
_ANGLE = re.compile(r"<[^<>\s`][^<>`]*>")


def md_code(v):
    """A code span safe inside a table cell: backticks around it, pipes escaped (GFM turns \\| back into |)."""
    v = re.sub(r"\s+", " ", v).strip().replace("|", "\\|")
    if not v:
        return ""
    return "`` " + v + " ``" if "`" in v else "`" + v + "`"


def md_text(v):
    """Plain cell text: one line, pipes escaped, <placeholders> put in code spans so previews do not read them as HTML."""
    v = re.sub(r"\s+", " ", v).strip()
    out, pos = [], 0
    for m in _SPAN.finditer(v):
        out.append(_ANGLE.sub(lambda a: "`" + a.group(0) + "`", v[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_ANGLE.sub(lambda a: "`" + a.group(0) + "`", v[pos:]))
    return "".join(out).replace("|", "\\|")


def markdown_table(header, rows):
    """GFM table: header, --- separator, every row padded to the header width, a trailing newline (callers keep blank lines around it)."""
    def cell(col, v):
        return md_code(v) if col in CODE_COLS else md_text(v)
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        cells = [cell(c, r[i] if i < len(r) else "") for i, c in enumerate(header)]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def commands_table_md(cmd_rows, flg_rows):
    return ("# mach commands and flags (table view)\n\n"
            "Generated by `mach sheets refresh mach` from `docs/sheets/commands.csv` and `docs/sheets/flags.csv`. Do not edit by hand.\n"
            "The workbook `docs/sheets/mach.xlsx` has the same data plus functions, config keys, destinations, templates and subsystem units.\n\n"
            "## Commands\n\n" + markdown_table(COMMAND_COLS, cmd_rows) +
            "\n## Flags\n\n" + markdown_table(FLAG_COLS, flg_rows))


# ----------------------------------------------------------------- functions

FUNC_COLS = ["file", "function", "language", "purpose"]


def _clean(text):
    return re.sub(r"\s+", " ", text.strip().lstrip("#").strip())


def _comment_block_above(lines, lineno):
    """The comment block ending right above 1-based line `lineno`; its first line, or ''."""
    i, block = lineno - 2, []
    while i >= 0 and lines[i].strip().startswith("#"):
        block.insert(0, lines[i])
        i -= 1
    return _clean(block[0]) if block else ""


def python_functions(rel, text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    out = []

    def purpose(node):
        doc = ast.get_docstring(node)
        if doc:
            return _clean(doc.strip().splitlines()[0])
        trailing = re.search(r":\s*#\s*(.+)$", lines[node.lineno - 1]) if node.body[0].lineno > node.lineno else None
        if trailing:
            return _clean(trailing.group(1))
        first = node.body[0].lineno
        above = _comment_block_above(lines, first)
        if above:
            return above
        start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
        return _comment_block_above(lines, start)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append([rel, node.name, "python", purpose(node)])
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out.append([rel, "%s.%s" % (node.name, sub.name), "python", purpose(sub)])
    return out


BASH_DEF = re.compile(r"^(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{(.*)$")


def bash_functions(rel, text):
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = BASH_DEF.match(line)
        if not m:
            continue
        trailing = re.search(r"#\s*(.+)$", m.group(2))
        purpose = _clean(trailing.group(1)) if trailing and not m.group(2).strip().startswith("}") else ""
        if not purpose and i + 1 < len(lines) and lines[i + 1].strip().startswith("#"):
            purpose = _clean(lines[i + 1])
        if not purpose:
            purpose = _comment_block_above(lines, i + 1)
        out.append([rel, m.group(1), "bash", purpose])
    return out


def function_rows(mach_home):
    rows = []
    for sub in ("lib", "libexec"):
        d = os.path.join(mach_home, sub)
        for fn in sorted(os.listdir(d)):
            p = os.path.join(d, fn)
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            first = text.split("\n", 1)[0]
            rel = "%s/%s" % (sub, fn)
            if fn.endswith(".py") or "python" in first:
                rows.extend(python_functions(rel, text))
            elif fn.endswith(".sh") or "bash" in first or "/sh" in first:
                rows.extend(bash_functions(rel, text))
    return rows


# ----------------------------------------------------------------- config keys

CONFIG_COLS = ["section", "key", "default", "meaning"]


def _strip_inline_comment(value):
    quote = ""
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return value[:i].rstrip(), value[i + 1:].strip()
    return value.rstrip(), ""


def _default_for(section, key):
    cur = mc.DEFAULTS
    for part in (section.split(".") if section else []) + [key]:
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return None if isinstance(cur, dict) else cur


def _render(v):
    return json.dumps(v) if not isinstance(v, bool) else ("true" if v else "false")


def config_rows(example_path):
    with open(example_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    rows, seen = [], set()
    section, section_note = "", ""
    for i, raw in enumerate(lines):
        m = re.match(r"^\s*\[([^\[\]]+)\]\s*(?:#\s*(.*))?$", raw)
        if m:
            section, section_note = m.group(1).strip(), (m.group(2) or "").strip()
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*=\s*(.*)$", raw)
        if not m:
            continue
        key = m.group(1)
        _value, meaning = _strip_inline_comment(m.group(2))
        if not meaning and i > 0 and lines[i - 1].startswith("#") and not lines[i - 1].startswith("# -"):
            meaning = lines[i - 1].lstrip("#").strip()
        meaning = meaning or section_note
        d = _default_for(section, key)
        rows.append([section, key, "" if d is None else _render(d), meaning])
        seen.add((section, key))

    def walk(prefix, node):
        for k, v in node.items():
            if isinstance(v, dict):
                walk(prefix + [k], v)
            elif (".".join(prefix), k) not in seen:
                rows.append([".".join(prefix), k, _render(v), ""])
    walk([], mc.DEFAULTS)
    for env, key in sorted(mc.ENV_KEYS.items()):
        rows.append(["env", env, "", "overrides config key %s" % key])
    return rows


# ----------------------------------------------------------------- destinations, templates, subsystem units

DEST_COLS = ["dest_syntax", "kind", "how_delivered"]


def destination_rows():
    rows = []
    for syntax, kind, how in ss.DEST_DOCS:
        if syntax == "<tool>":
            for tool in mc.KNOWN_TOOLS:
                rows.append([tool, kind, how])
        else:
            rows.append([syntax, kind, how])
    for syntax, kind, how in mach_note.DEST_DOCS:
        rows.append(["mach note " + syntax, kind, how])
    return rows


TEMPLATE_COLS = ["template", "purpose", "ingested_by"]
TEMPLATE_DIR = "~/machine-flows/ai-authored/templates"
RUN = "mach run"
# (file, purpose, ingested_by): the generic templates mach documents; a tree may hold more.
TEMPLATES = [
    ("flow-request.md", "A request to run an existing mach flow", RUN),
    ("research-brief.md", "A research question for an AI tool", RUN),
    ("role-change.md", "Change who holds a role in a unit", "mach subsystem role <id> --from <file>"),
    ("subsystem-prompt.md", "A prompt for a unit's role, sent with mach run", RUN),
    ("subsystem-setup.md", "Describe a whole subsystem to scaffold", "mach subsystem new <id> --from <file>"),
    ("task-brief.md", "A task for an AI tool in a working folder", RUN),
    ("unit-setup.md", "Add or update one unit in a subsystem", "mach subsystem unit <id> --from <file>"),
]


def template_rows():
    return [["%s/%s" % (TEMPLATE_DIR, fn), purpose, by] for fn, purpose, by in TEMPLATES]


UNIT_COLS = ["unit", "kind", "parent", "lead", "repo", "folder", "verified"]


def unit_rows(mach_home):
    with open(os.path.join(mach_home, "config", EXAMPLE_MANIFEST), encoding="utf-8") as fh:
        data = ss.parse(fh.read())
    rows = []
    for uid, u in data.get("units", {}).items():
        roles = u.get("roles", {}) if isinstance(u.get("roles"), dict) else {}
        rows.append([uid, u.get("kind", ""), u.get("parent", ""), roles.get("lead", ""), u.get("repo", ""), u.get("folder", ""),
                     "true" if u.get("verified") else "false"])
    return rows


# ----------------------------------------------------------------- the whole set

def generate(mach_home, mf_root):
    """{file: (header, rows) or None when its source is missing} in index order, plus the COMMANDS-TABLE.md text."""
    libexec = os.path.join(mach_home, "libexec")
    cmd_rows, usage_text = command_rows(libexec)
    flg_rows = flag_rows(libexec, os.path.join(mach_home, "bin", "mach"), usage_text)
    out = {
        "commands.csv": (COMMAND_COLS, cmd_rows),
        "flags.csv": (FLAG_COLS, flg_rows),
        "functions.csv": (FUNC_COLS, function_rows(mach_home)),
        "config-keys.csv": (CONFIG_COLS, config_rows(os.path.join(mach_home, "config", "config.example.toml"))),
        "destinations.csv": (DEST_COLS, destination_rows()),
    }
    out["templates.csv"] = (TEMPLATE_COLS, template_rows())
    out["subsystem-units.csv"] = (UNIT_COLS, unit_rows(mach_home))
    return out, commands_table_md(cmd_rows, flg_rows)


def index_meta():
    """Static index.csv columns per file (rows and updated are filled by `mach sheets build`)."""
    return [dict(zip(["id", "file", "sheet_name", "title", "description", "source"], r),
                 owner=OWNER, generated_by=GENERATED_BY) for r in SET]
