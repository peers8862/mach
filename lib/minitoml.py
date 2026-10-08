"""minitoml: a small TOML-subset parser (stdlib only, python 3.9+).

Used when `tomllib` (python 3.11+) is not available, e.g. the Mac's /usr/bin/python3 (3.9).

Supported:
  - comments (#), blank lines
  - tables [a], dotted tables [a.b.c], quoted key parts [a."b c"]
  - key = value with bare, dotted or quoted keys
  - basic strings "..." (with \\n \\t \\" \\\\ \\uXXXX escapes), literal strings '...'
  - integers (with _ separators), floats, booleans
  - inline arrays of scalars / arrays / inline tables, possibly spanning lines
  - inline tables { a = 1, b = "x" }
Not supported (raises TomlError): multi-line strings, dates/times, arrays of tables [[x]].
"""


class TomlError(ValueError):
    def __init__(self, msg, line=0):
        ValueError.__init__(self, "line %d: %s" % (line, msg) if line else msg)
        self.line = line


_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", '"': '"', "\\": "\\"}


def _strip_comment(s):
    """Remove a trailing # comment that is not inside a string."""
    out = []
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            out.append(c)
            if quote == '"' and c == "\\" and i + 1 < len(s):
                out.append(s[i + 1])
                i += 1
            elif c == quote:
                quote = None
        else:
            if c in "\"'":
                quote = c
                out.append(c)
            elif c == "#":
                break
            else:
                out.append(c)
        i += 1
    return "".join(out).rstrip()


def _bracket_depth(s):
    """Net depth of [ ] and { } outside strings (used to join multi-line arrays)."""
    depth = 0
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        i += 1
    return depth


def _split_key(s, lineno):
    """Split a dotted key (bare or quoted parts) into a list of parts."""
    parts = []
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i] in " \t":
            i += 1
        if i >= n:
            break
        if s[i] == '"':
            j = i + 1
            buf = []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n:
                    buf.append(_ESC.get(s[j + 1], s[j + 1]))
                    j += 2
                    continue
                buf.append(s[j])
                j += 1
            if j >= n:
                raise TomlError("unterminated quoted key", lineno)
            parts.append("".join(buf))
            i = j + 1
        elif s[i] == "'":
            j = s.find("'", i + 1)
            if j < 0:
                raise TomlError("unterminated quoted key", lineno)
            parts.append(s[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and (s[j].isalnum() or s[j] in "_-"):
                j += 1
            if j == i:
                raise TomlError("bad key %r" % s, lineno)
            parts.append(s[i:j])
            i = j
        while i < n and s[i] in " \t":
            i += 1
        if i < n:
            if s[i] != ".":
                raise TomlError("bad key %r" % s, lineno)
            i += 1
    if not parts:
        raise TomlError("empty key", lineno)
    return parts


class _P:
    """Value parser over one string."""

    def __init__(self, s, lineno):
        self.s = s
        self.i = 0
        self.lineno = lineno

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def value(self):
        self.ws()
        if self.i >= len(self.s):
            raise TomlError("missing value", self.lineno)
        c = self.s[self.i]
        if c == '"':
            return self.basic_string()
        if c == "'":
            j = self.s.find("'", self.i + 1)
            if j < 0:
                raise TomlError("unterminated string", self.lineno)
            v = self.s[self.i + 1:j]
            self.i = j + 1
            return v
        if c == "[":
            return self.array()
        if c == "{":
            return self.inline_table()
        return self.scalar()

    def basic_string(self):
        s = self.s
        j = self.i + 1
        buf = []
        while j < len(s):
            c = s[j]
            if c == "\\":
                if j + 1 >= len(s):
                    break
                e = s[j + 1]
                if e == "u" and j + 5 < len(s) + 0:
                    buf.append(chr(int(s[j + 2:j + 6], 16)))
                    j += 6
                    continue
                buf.append(_ESC.get(e, e))
                j += 2
                continue
            if c == '"':
                self.i = j + 1
                return "".join(buf)
            buf.append(c)
            j += 1
        raise TomlError("unterminated string", self.lineno)

    def array(self):
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise TomlError("unterminated array", self.lineno)
            if self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self.value())
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
            elif self.i < len(self.s) and self.s[self.i] != "]":
                raise TomlError("expected , or ] in array", self.lineno)

    def inline_table(self):
        self.i += 1
        out = {}
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise TomlError("unterminated inline table", self.lineno)
            if self.s[self.i] == "}":
                self.i += 1
                return out
            j = self.i
            while j < len(self.s) and self.s[j] != "=":
                j += 1
            if j >= len(self.s):
                raise TomlError("expected = in inline table", self.lineno)
            keys = _split_key(self.s[self.i:j].strip(), self.lineno)
            self.i = j + 1
            _set(out, keys, self.value(), self.lineno)
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def scalar(self):
        j = self.i
        while j < len(self.s) and self.s[j] not in ",]} \t\r\n":
            j += 1
        tok = self.s[self.i:j]
        self.i = j
        if tok == "true":
            return True
        if tok == "false":
            return False
        t = tok.replace("_", "")
        try:
            if t.lower().startswith(("0x", "+0x", "-0x")):
                return int(t, 16)
            return int(t)
        except ValueError:
            pass
        try:
            return float(t)
        except ValueError:
            raise TomlError("cannot parse value %r" % tok, self.lineno)


def _set(d, keys, val, lineno):
    for k in keys[:-1]:
        nxt = d.setdefault(k, {})
        if not isinstance(nxt, dict):
            raise TomlError("key %r is not a table" % k, lineno)
        d = nxt
    if keys[-1] in d:
        raise TomlError("duplicate key %r" % keys[-1], lineno)
    d[keys[-1]] = val


def loads(text):
    root = {}
    cur = root
    lines = text.splitlines()
    n = 0
    while n < len(lines):
        raw = lines[n]
        lineno = n + 1
        n += 1
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[["):
            raise TomlError("arrays of tables are not supported", lineno)
        if line.startswith("["):
            if not line.endswith("]"):
                raise TomlError("bad table header", lineno)
            keys = _split_key(line[1:-1], lineno)
            cur = root
            for k in keys:
                nxt = cur.setdefault(k, {})
                if not isinstance(nxt, dict):
                    raise TomlError("key %r is not a table" % k, lineno)
                cur = nxt
            continue
        # key = value, value may continue over several lines (arrays / inline tables)
        eq = _find_eq(line)
        if eq < 0:
            raise TomlError("expected key = value", lineno)
        keys = _split_key(line[:eq].strip(), lineno)
        vtext = line[eq + 1:].strip()
        while _bracket_depth(vtext) > 0:
            if n >= len(lines):
                raise TomlError("unterminated array or table", lineno)
            vtext += "\n" + _strip_comment(lines[n]).strip()
            n += 1
        p = _P(vtext, lineno)
        val = p.value()
        p.ws()
        if p.i < len(vtext):
            raise TomlError("trailing characters after value", lineno)
        _set(cur, keys, val, lineno)
    return root


def _find_eq(line):
    quote = None
    for i, c in enumerate(line):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "=":
            return i
    return -1


def load_path(path):
    with open(path, "r", encoding="utf-8") as fh:
        return loads(fh.read())


def parse(text):
    """tomllib when available, else minitoml. Same result shape either way."""
    try:
        import tomllib  # python 3.11+
        return tomllib.loads(text)
    except ImportError:
        return loads(text)
