"""frontmatter: flat-YAML frontmatter + flow-recipe parser for mach (stdlib only, python 3.9+).

Flat YAML (plan 08 section 3.6): `key: value`, inline lists `[a, b]`, `#` comments, no nesting.

Public API
  parse_text(text)            -> ParsedDoc(meta, body, lines, errors, body_line)
  parse_file(path)            -> ParsedDoc
  validate(doc)               -> appends (line, message) errors / warnings on the doc
  load_prompt_doc(path)       -> ParsedDoc, parsed AND validated against the schema
  parse_recipe_text(text)     -> Recipe (steps, errors)
  parse_recipe_file(path)     -> Recipe
Errors are (line_number, message) tuples; line numbers are 1-based file lines.
"""
import re

SCHEMA_VERSION = 1

def machines():
    """Valid values of the `machine` key: `any` plus the machine names from the config (and this machine)."""
    import mach_common as mc
    return mc.machine_names() + ["any"]


TOOLS = ["claude", "codex", "cursor-agent", "grokcli-agent", "kiro", "auto"]
APPROVALS = ["none", "before-run", "before-apply"]
DEPTHS = ["quick", "deep"]
SOURCES = ["web", "repo", "linear", "files"]
TYPES = ["task", "research", "flow", "subsystem-prompt", "subsystem-setup", "unit-setup", "role-change"]
OUTWARD_OUTPUTS = ["pr", "linear-comment"]

COMMON_OPTIONAL = ["machine", "due", "approval", "tags"]
SCHEMA = {
    "task": {
        "required": ["mach", "type", "title", "goal", "tool", "output"],
        "optional": ["permission", "path", "machine", "due", "approval", "tags"],
    },
    "research": {
        "required": ["mach", "type", "title", "question", "output"],
        "optional": ["permission", "depth", "tool", "sources", "machine", "due", "approval", "tags"],
    },
    "flow": {
        "required": ["mach", "type", "title", "flow", "input"],
        "optional": ["machine", "due", "approval", "output", "tags"],
    },
    "subsystem-prompt": {
        "required": ["mach", "type", "title", "subsystem", "unit"],
        "optional": ["to", "role", "reply", "tags", "machine", "due"],
    },
    "subsystem-setup": {
        "required": ["mach", "type", "title", "id", "name", "working_root", "max_fires_per_day", "reply"],
        "optional": ["linear_team", "note_dest", "due", "tags"],
    },
    "unit-setup": {
        "required": ["mach", "type", "title", "subsystem", "unit"],
        "optional": ["due", "tags"],
    },
    "role-change": {
        "required": ["mach", "type", "title", "subsystem", "unit", "role", "to", "date", "reason"],
        "optional": ["due", "tags"],
    },
}
ALL_KEYS = sorted(set(k for v in SCHEMA.values() for k in v["required"] + v["optional"]))


TEXT_REQUIRED = ["title", "goal", "question", "flow", "subsystem", "unit", "id", "name", "working_root", "role", "to", "date", "reason"]
TEXT_OPTIONAL = ["path", "input", "output", "due"]
DATE_KEYS = ["date", "due"]
LIST_KEYS = ["tags", "sources"]


class ParsedDoc(object):
    def __init__(self):
        self.meta = {}
        self.body = ""
        self.lines = {}      # key -> line number
        self.errors = []     # (line, message)
        self.warnings = []   # (line, message)
        self.body_line = 1   # file line of the first body line
        self.has_frontmatter = False
        self.path = ""

    @property
    def ok(self):
        return not self.errors


# ----------------------------------------------------------------- scalars / lists

def strip_comment(s):
    """Drop a trailing ` # comment` that is not inside quotes."""
    quote = None
    for i, c in enumerate(s):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        inner = s[1:-1]
        if s[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return s


def _split_list(inner):
    items, buf, quote = [], [], None
    for c in inner:
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
            buf.append(c)
        elif c == ",":
            items.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    if "".join(buf).strip() or items:
        items.append("".join(buf))
    return [_unquote(x) for x in items if x.strip() != "" or False]


def parse_value(raw):
    """Parse the text after `key:`. Returns a python value; raises ValueError on bad syntax."""
    s = strip_comment(raw).strip()
    if s == "":
        return ""
    if s[0] == "[":
        if not s.endswith("]"):
            raise ValueError("unterminated list")
        return _split_list(s[1:-1])
    if s[0] in "{":
        raise ValueError("nested values are not supported (flat YAML only)")
    if s[0] in "\"'":
        if len(s) < 2 or s[-1] != s[0]:
            raise ValueError("unterminated quoted string")
        return _unquote(s)
    if re.match(r"^-?\d+$", s):
        return int(s)
    if s in ("true", "false"):
        return s == "true"
    return s


# ----------------------------------------------------------------- documents

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(?:\s+(.*)|\s*)$")


def parse_text(text, nested=False):
    """Parse a document. nested=True (lesson files) tolerates one level of indented `child: value` lines,
    stored as `parent.child`; strict mode (prompt documents) rejects any indentation."""
    doc = ParsedDoc()
    parent = None
    lines = text.split("\n")
    if lines and lines[0].rstrip() == "---":
        doc.has_frontmatter = True
        end = None
        for idx in range(1, len(lines)):
            if lines[idx].rstrip() == "---":
                end = idx
                break
        if end is None:
            doc.errors.append((1, "frontmatter opened with --- but never closed"))
            doc.body = "\n".join(lines[1:])
            doc.body_line = 2
            return doc
        for idx in range(1, end):
            ln = idx + 1
            raw = lines[idx]
            if raw.strip() == "" or raw.lstrip().startswith("#"):
                continue
            if raw[0] in " \t":
                if not nested:
                    doc.errors.append((ln, "indented line: nesting is not supported (flat YAML only)"))
                    continue
                cm = _KEY_RE.match(raw.strip())
                if cm and parent:
                    try:
                        doc.meta["%s.%s" % (parent, cm.group(1))] = parse_value(cm.group(2) or "")
                        doc.lines["%s.%s" % (parent, cm.group(1))] = ln
                    except ValueError as exc:
                        doc.errors.append((ln, str(exc)))
                continue
            m = _KEY_RE.match(raw.rstrip())
            if not m:
                doc.errors.append((ln, "not a `key: value` line: %r" % raw.strip()[:60]))
                continue
            key, rest = m.group(1), m.group(2) or ""
            parent = key if strip_comment(rest).strip() == "" else None
            if key in doc.meta:
                doc.errors.append((ln, "duplicate key %r (first on line %d)" % (key, doc.lines[key])))
                continue
            try:
                val = parse_value(rest)
            except ValueError as exc:
                doc.errors.append((ln, "key %r: %s" % (key, exc)))
                continue
            doc.meta[key] = val
            doc.lines[key] = ln
        doc.body = "\n".join(lines[end + 1:])
        doc.body_line = end + 2
    else:
        doc.body = text
        doc.errors.append((1, "no frontmatter: a prompt document must start with ---"))
    return doc


def parse_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    doc = parse_text(text)
    doc.path = path
    return doc


def _check_enum(doc, key, allowed):
    if key in doc.meta:
        v = doc.meta[key]
        if not isinstance(v, str) or v not in allowed:
            doc.errors.append((doc.lines[key], "%s: %r is not one of %s" % (key, v, ", ".join(allowed))))


def _check_str(doc, key, required_nonempty):
    if key not in doc.meta:
        return
    v = doc.meta[key]
    ln = doc.lines[key]
    if isinstance(v, (list, bool)) or v is None:
        doc.errors.append((ln, "%s: expected a text value" % key))
        return
    if required_nonempty and str(v).strip() == "":
        doc.errors.append((ln, "%s: required value is empty" % key))


def validate(doc):
    """Validate doc.meta against the schema (plan 08 section 3.6). Adds to doc.errors / doc.warnings."""
    meta = doc.meta
    if not doc.has_frontmatter:
        return doc
    typ = meta.get("type")
    if "type" not in meta:
        doc.errors.append((1, "missing required key 'type' (one of %s)" % ", ".join(TYPES)))
        typ = None
    elif not isinstance(typ, str) or typ not in SCHEMA:
        doc.errors.append((doc.lines["type"], "type: %r is not one of %s" % (typ, ", ".join(TYPES))))
        typ = None
    if "mach" not in meta:
        doc.errors.append((1, "missing required key 'mach' (schema version, currently %d)" % SCHEMA_VERSION))
    elif meta["mach"] != SCHEMA_VERSION or isinstance(meta["mach"], bool):
        doc.errors.append((doc.lines["mach"], "mach: schema version %r is not supported (this mach reads %d)" % (meta["mach"], SCHEMA_VERSION)))
    if typ:
        spec = SCHEMA[typ]
        allowed = set(spec["required"] + spec["optional"])
        for key in meta:
            if key not in allowed:
                known = key in ALL_KEYS
                hint = " (valid for another type, not for type: %s)" % typ if known else ""
                doc.errors.append((doc.lines[key], "unknown key %r%s" % (key, hint)))
        for key in spec["required"]:
            if key not in meta:
                doc.errors.append((1, "missing required key %r for type: %s" % (key, typ)))
    # value checks
    _check_enum(doc, "tool", TOOLS)
    _check_enum(doc, "machine", machines())
    _check_enum(doc, "approval", APPROVALS)
    _check_enum(doc, "permission", ["read-only", "write"])
    _check_enum(doc, "depth", DEPTHS)
    _check_enum(doc, "reply", ["chat", "inbox"])
    for key in TEXT_REQUIRED:
        _check_str(doc, key, True)
    for key in TEXT_OPTIONAL:
        _check_str(doc, key, False)
    if "date" in meta and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(meta["date"])):
        doc.errors.append((doc.lines["date"], "date must be YYYY-MM-DD"))
    if "due" in meta and meta["due"] != "":
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(meta["due"])):
            doc.errors.append((doc.lines["due"], "due: %r is not YYYY-MM-DD" % (meta["due"],)))
    for key in LIST_KEYS:
        if key in meta and not isinstance(meta[key], list):
            doc.errors.append((doc.lines[key], "%s: expected an inline list like [a, b]" % key))
    if isinstance(meta.get("sources"), list):
        for s in meta["sources"]:
            if s not in SOURCES:
                doc.errors.append((doc.lines["sources"], "sources: %r is not one of %s" % (s, ", ".join(SOURCES))))
    if typ in ("task", "research") and "output" in meta and str(meta["output"]).strip() == "":
        doc.errors.append((doc.lines["output"], "output: required value is empty (a path, stdout, pr or linear-comment)"))
    if typ == "flow" and "input" in meta and str(meta["input"]).strip() == "":
        doc.warnings.append((doc.lines["input"], "input is empty: the flow starts with no input (fill it in before a real run)"))
    return doc


def load_prompt_doc(path):
    doc = parse_file(path)
    validate(doc)
    doc.errors.sort(key=lambda e: e[0])
    return doc


def is_outward(output):
    return str(output).strip() in OUTWARD_OUTPUTS


def format_problems(path, items, label):
    return ["%s:%d: %s: %s" % (path, ln, label, msg) for ln, msg in items]


# ----------------------------------------------------------------- recipes

STEP_KEYS = ["title", "kind", "tool", "machine", "prompt", "cmd", "output", "gate", "handoff"]
STEP_KINDS = ["ai", "cmd", "handoff", "gate"]
RECIPE_META = ["mach", "type", "name", "title", "description", "input"]


class Step(object):
    def __init__(self, number, title, line):
        self.number = number
        self.title = title
        self.line = line
        self.kind = "ai"
        self.tool = ""
        self.machine = ""
        self.prompt = ""
        self.cmd = ""
        self.output = ""
        self.gate = ""
        self.handoff = ""

    def as_dict(self):
        return {"n": self.number, "title": self.title, "kind": self.kind, "tool": self.tool,
                "machine": self.machine, "output": self.output, "gate": self.gate}


class Recipe(object):
    def __init__(self):
        self.meta = {}
        self.steps = []
        self.errors = []
        self.intro = ""
        self.path = ""

    @property
    def name(self):
        return str(self.meta.get("name", ""))


_STEP_HEAD = re.compile(r"^##\s+(\d+)[.)]?\s*(.*)$")


def parse_recipe_text(text):
    rec = Recipe()
    doc = parse_text(text)
    rec.errors.extend(doc.errors)
    rec.meta = doc.meta
    if doc.has_frontmatter:
        if doc.meta.get("type") != "recipe":
            rec.errors.append((doc.lines.get("type", 1), "recipe frontmatter needs `type: recipe`"))
        for key in doc.meta:
            if key not in RECIPE_META:
                rec.errors.append((doc.lines[key], "unknown recipe key %r" % key))
        if "name" not in doc.meta:
            rec.errors.append((1, "recipe frontmatter needs `name:`"))
    lines = doc.body.split("\n")
    base = doc.body_line
    cur = None
    intro = []
    last_key = None
    seen_numbers = []
    for idx, raw in enumerate(lines):
        ln = base + idx
        m = _STEP_HEAD.match(raw)
        if m:
            num = int(m.group(1))
            if num in seen_numbers:
                rec.errors.append((ln, "duplicate step number %d" % num))
            elif seen_numbers and num != seen_numbers[-1] + 1:
                rec.errors.append((ln, "step numbers must be consecutive (got %d after %d)" % (num, seen_numbers[-1])))
            seen_numbers.append(num)
            cur = Step(num, m.group(2).strip(), ln)
            rec.steps.append(cur)
            last_key = None
            continue
        if cur is None:
            intro.append(raw)
            continue
        if raw.strip() == "" or raw.lstrip().startswith("<!--"):
            continue
        km = _KEY_RE.match(raw.rstrip())
        if km and raw[0] not in " \t" and km.group(1) in STEP_KEYS:
            key, val = km.group(1), (km.group(2) or "").strip()
            setattr(cur, key, val)
            last_key = key
        elif raw[0] in " \t" and last_key in ("prompt", "gate", "handoff"):
            joiner = "\n" if last_key == "handoff" else " "
            setattr(cur, last_key, (getattr(cur, last_key) + joiner + raw.strip()).strip())
        else:
            rec.errors.append((ln, "unexpected line in step %d: %r" % (cur.number, raw.strip()[:60])))
    rec.intro = "\n".join(intro).strip()
    # normalise: kinds, validation, split `gate:` that sits in an action step into its own step
    final = []
    for st in rec.steps:
        if st.kind not in STEP_KINDS:
            rec.errors.append((st.line, "step %d: kind %r is not one of %s" % (st.number, st.kind, ", ".join(STEP_KINDS))))
        if st.tool and st.tool not in TOOLS:
            rec.errors.append((st.line, "step %d: tool %r is not one of %s" % (st.number, st.tool, ", ".join(TOOLS))))
        if st.machine and st.machine not in machines():
            rec.errors.append((st.line, "step %d: machine %r is not one of %s" % (st.number, st.machine, ", ".join(machines()))))
        has_action = bool(st.prompt or st.cmd or st.handoff)
        after_gate = None
        if st.gate and has_action:
            # a `gate:` line in a step with an action pauses AFTER that step finishes
            after_gate = Step(st.number, "Gate after: " + (st.title or ""), st.line)
            after_gate.kind = "gate"
            after_gate.gate = st.gate
            st.gate = ""
        elif st.gate and not has_action:
            st.kind = "gate"
        if st.cmd and st.kind == "ai":
            st.kind = "cmd"
        if st.handoff and st.kind == "ai" and not st.prompt:
            st.kind = "handoff"
        if st.kind == "ai" and not st.prompt:
            rec.errors.append((st.line, "step %d has no prompt:, cmd:, handoff: or gate:" % st.number))
        final.append(st)
        if after_gate is not None:
            final.append(after_gate)
    # renumber sequentially after gate splitting
    for i, st in enumerate(final):
        st.number = i + 1
    rec.steps = final
    if not final:
        rec.errors.append((1, "recipe has no steps (## 1. Title ...)"))
    rec.errors.sort(key=lambda e: e[0])
    return rec


def parse_recipe_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        rec = parse_recipe_text(fh.read())
    rec.path = path
    return rec
