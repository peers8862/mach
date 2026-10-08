"""mach_sheets: sheet sets (index.csv + CSV files + a generated .xlsx), stdlib only (python 3.9+).

A sheet set is a folder with `index.csv` (the master index), the CSV files it lists, and `<name>.xlsx`, a workbook generated from
them (Index sheet first, then one sheet per CSV in index order). The CSVs are the source of truth; the workbook is never edited.
The workbook is written with zipfile + minimal SpreadsheetML, so it needs no install and is reproducible (fixed zip
timestamps, fixed compression level, no clock). A "build record" (content hash and `updated` date per CSV) lives in docProps/custom.xml.
"""
import csv
import datetime
import hashlib
import io
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

import minitoml

INDEX_COLS = ["id", "file", "sheet_name", "title", "description", "owner", "source", "generated_by", "updated", "rows"]
INDEX_SHEET = "Index"
CONFIG_FILE = "sheets.toml"
MAX_SHEET_NAME = 31
MAX_CELL = 32767
MAX_ROWS = 1048576
MAX_COLS = 16384
BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
ABS_HOME_PATH = re.compile(r"(?:^|[\s\"'(=,;:])/(?:home|Users|root)/")
FORMULA_LIKE = re.compile(r"^(?:[=@]|[+-][(=@])")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
RECORD_PREFIX = "mach.sheet."


# ----------------------------------------------------------------- CSV and set loading

def read_csv(path):
    """All non-blank records of a CSV (UTF-8, BOM tolerated). Raises OSError / UnicodeDecodeError / csv.Error."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [r for r in csv.reader(fh) if r]


def write_csv_text(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def content_hash(records):
    """Hash of the parsed cells (not the bytes), so line endings and quoting style do not count as a change."""
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def valid_date(s):
    if not DATE_RE.match(s or ""):
        return False
    try:
        datetime.datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def set_config(d):
    """Optional sheets.toml: workbook = "<name>" (default: the folder name)."""
    p = os.path.join(d, CONFIG_FILE)
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        return minitoml.parse(fh.read())


def workbook_name(d):
    try:
        name = set_config(d).get("workbook")
    except (OSError, ValueError):
        name = None
    return name if isinstance(name, str) and name else os.path.basename(os.path.abspath(d))


def workbook_path(d):
    return os.path.join(d, workbook_name(d) + ".xlsx")


def sheet_name_problem(name):
    if not name:
        return "sheet_name is empty"
    if len(name) > MAX_SHEET_NAME:
        return "sheet_name %r is %d characters (Excel allows %d)" % (name, len(name), MAX_SHEET_NAME)
    if BAD_SHEET_CHARS.search(name):
        return "sheet_name %r contains one of [ ] : * ? / \\" % name
    if name.startswith("'") or name.endswith("'"):
        return "sheet_name %r starts or ends with an apostrophe" % name
    if name.lower() == "history":
        return "sheet_name %r is reserved by Excel" % name
    if name.lower() == INDEX_SHEET.lower():
        return "sheet_name %r is taken by the generated Index sheet" % name
    if XML_ILLEGAL.search(name):
        return "sheet_name %r has a control character" % name
    return ""


class Entry(object):
    """One index row plus what was read from its CSV."""

    def __init__(self, row):
        self.row = row
        self.header = []
        self.data = []
        self.sha = ""
        self.count = 0


def read_index(d):
    """Return (header, rows as dicts, errors). Rows are padded dicts keyed by the header."""
    p = os.path.join(d, "index.csv")
    if not os.path.isfile(p):
        return [], [], ["index.csv is missing"]
    try:
        recs = read_csv(p)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return [], [], ["index.csv cannot be read: %s" % exc]
    if not recs:
        return [], [], ["index.csv is empty (it needs the header row)"]
    header = [h.strip() for h in recs[0]]
    errors = []
    rows = []
    for n, r in enumerate(recs[1:], 2):
        if len(r) != len(header):
            errors.append("index.csv record %d has %d fields, the header has %d" % (n, len(r), len(header)))
            continue
        rows.append(dict(zip(header, r)))
    return header, rows, errors


def load_entries(d):
    """Read index.csv and every CSV it lists. Returns (entries, results) where results are (level, message)."""
    res = []
    header, rows, errs = read_index(d)
    for e in errs:
        res.append(("FAIL", e))
    if header and header != INDEX_COLS:
        res.append(("FAIL", "index.csv columns must be exactly: %s (found: %s)" % (", ".join(INDEX_COLS), ", ".join(header))))
        return [], res
    if not header:
        return [], res
    entries, seen_id, seen_file, seen_name = [], {}, {}, {}
    for n, row in enumerate(rows, 2):
        ent = Entry(row)
        entries.append(ent)
        tag = "index.csv row %d" % n
        rid, fn, sn = row["id"].strip(), row["file"].strip(), row["sheet_name"].strip()
        if not rid:
            res.append(("FAIL", "%s: id is empty" % tag))
        elif rid in seen_id:
            res.append(("FAIL", "%s: id %r repeats row %d" % (tag, rid, seen_id[rid])))
        else:
            seen_id[rid] = n
        problem = sheet_name_problem(sn)
        if problem:
            res.append(("FAIL", "%s: %s" % (tag, problem)))
        elif sn.lower() in seen_name:
            res.append(("FAIL", "%s: sheet_name %r repeats row %d (names compare case-insensitively)" % (tag, sn, seen_name[sn.lower()])))
        else:
            seen_name[sn.lower()] = n
        if not fn or os.path.basename(fn) != fn or fn.startswith(".") or not fn.lower().endswith(".csv"):
            res.append(("FAIL", "%s: file %r must be a plain file name ending in .csv" % (tag, fn)))
            continue
        if fn == "index.csv":
            res.append(("FAIL", "%s: index.csv cannot list itself" % tag))
            continue
        if fn in seen_file:
            res.append(("FAIL", "%s: file %s repeats row %d" % (tag, fn, seen_file[fn])))
            continue
        seen_file[fn] = n
        path = os.path.join(d, fn)
        if not os.path.isfile(path):
            res.append(("FAIL", "%s: %s does not exist" % (tag, fn)))
            continue
        try:
            recs = read_csv(path)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            res.append(("FAIL", "%s: cannot read as UTF-8 CSV: %s" % (fn, exc)))
            continue
        if not recs:
            res.append(("FAIL", "%s: empty (it needs a header row)" % fn))
            continue
        ent.header, ent.data = recs[0], recs[1:]
        ent.count = len(ent.data)
        ent.sha = content_hash(recs)
        res.extend(check_csv(fn, ent.header, ent.data))
    return entries, res


def check_csv(fn, header, data):
    res = []
    if len(header) > MAX_COLS:
        res.append(("FAIL", "%s: %d columns (Excel allows %d)" % (fn, len(header), MAX_COLS)))
    if len(data) + 1 > MAX_ROWS:
        res.append(("FAIL", "%s: %d rows (Excel allows %d)" % (fn, len(data) + 1, MAX_ROWS)))
    if any(not h.strip() for h in header):
        res.append(("FAIL", "%s: a header cell is empty" % fn))
    dup = sorted(set(h for h in header if header.count(h) > 1))
    if dup:
        res.append(("WARN", "%s: duplicate column names: %s" % (fn, ", ".join(dup))))
    ragged = [i for i, r in enumerate(data, 2) if len(r) != len(header)]
    if ragged:
        res.append(("FAIL", "%s: %d record(s) do not have %d fields (first: line/record %d)" % (fn, len(ragged), len(header), ragged[0])))
    bad_ctrl, too_long, formulas, abspath = [], [], [], []
    for rn, r in enumerate([header] + data, 1):
        for cn, v in enumerate(r, 1):
            ref = "%s%d" % (col_letter(cn), rn)
            if XML_ILLEGAL.search(v):
                bad_ctrl.append(ref)
            if len(v) > MAX_CELL:
                too_long.append(ref)
            if rn > 1 and FORMULA_LIKE.match(v):
                formulas.append(ref)
            if ABS_HOME_PATH.search(v):
                abspath.append(ref)
    if bad_ctrl:
        res.append(("FAIL", "%s: control characters Excel cannot store at %s" % (fn, ", ".join(bad_ctrl[:3]))))
    if too_long:
        res.append(("FAIL", "%s: cell longer than %d characters at %s" % (fn, MAX_CELL, ", ".join(too_long[:3]))))
    if formulas:
        res.append(("WARN", "%s: %d cell(s) start like a formula (%s); the workbook stores them as text but Excel would run them if you open the CSV directly" % (fn, len(formulas), ", ".join(formulas[:3]))))
    if abspath:
        res.append(("WARN", "%s: absolute home path at %s (use ~/ or a repo-relative path)" % (fn, ", ".join(abspath[:3]))))
    return res


# ----------------------------------------------------------------- build record and lint

def read_record(xlsx):
    """The build record stored in the workbook: {file: (sha256, updated)} and the sheet names; None when unreadable."""
    try:
        with zipfile.ZipFile(xlsx) as z:
            root = ET.fromstring(z.read("docProps/custom.xml"))
            wb = ET.fromstring(z.read("xl/workbook.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return None
    rec = {}
    for prop in root:
        name = prop.get("name", "")
        if name.startswith(RECORD_PREFIX):
            text = "".join(prop.itertext())
            sha, _, date = text.partition(";")
            rec[name[len(RECORD_PREFIX):]] = (sha, date)
    sheets = [s.get("name") for s in wb.iter("{%s}sheet" % NS_MAIN)]
    return {"files": rec, "sheets": sheets}


def lint_set(d):
    """Lint a sheet set folder. Returns a list of (level, message); levels FAIL, WARN."""
    if not os.path.isdir(d):
        return [("FAIL", "%s is not a folder" % d)]
    entries, res = load_entries(d)
    indexed = set(e.row["file"].strip() for e in entries)
    for fn in sorted(os.listdir(d)):
        if fn.startswith(".") or not fn.lower().endswith(".csv") or fn == "index.csv":
            continue
        if fn not in indexed:
            res.append(("FAIL", "%s is not listed in index.csv (orphan)" % fn))
    for ent in entries:
        fn = ent.row["file"].strip()
        if not ent.sha:
            continue
        r = ent.row["rows"].strip()
        if not r.isdigit() or int(r) != ent.count:
            res.append(("FAIL", "%s: index says rows=%r but the CSV has %d data rows (run: mach sheets build)" % (fn, r, ent.count)))
        u = ent.row["updated"].strip()
        if not valid_date(u):
            res.append(("FAIL", "%s: updated=%r is not a YYYY-MM-DD date" % (fn, u)))
    try:
        cfg = set_config(d)
    except (OSError, ValueError) as exc:
        res.append(("FAIL", "%s: %s" % (CONFIG_FILE, exc)))
        cfg = {}
    name = cfg.get("workbook") if isinstance(cfg.get("workbook"), str) else workbook_name(d)
    if not name or BAD_SHEET_CHARS.search(name) or os.path.basename(name) != name:
        res.append(("FAIL", "workbook name %r is not a plain file name" % name))
        return res
    if not any(lv == "FAIL" for lv, _ in res):
        res.extend(lint_workbook(d, entries))
    return res


def lint_workbook(d, entries):
    res = []
    xlsx = workbook_path(d)
    rel = os.path.basename(xlsx)
    if not os.path.isfile(xlsx):
        return [("WARN", "%s does not exist yet (run: mach sheets build %s)" % (rel, d))]
    rec = read_record(xlsx)
    if rec is None:
        return [("FAIL", "%s is not a workbook mach built (no build record); run: mach sheets build" % rel)]
    want_sheets = [INDEX_SHEET] + [e.row["sheet_name"].strip() for e in entries]
    if rec["sheets"] != want_sheets:
        res.append(("FAIL", "%s sheets are %s but the index says %s (run: mach sheets build)" % (rel, rec["sheets"], want_sheets)))
    for ent in entries:
        fn = ent.row["file"].strip()
        got = rec["files"].get(fn)
        if got is None:
            res.append(("FAIL", "%s has no record of %s (run: mach sheets build)" % (rel, fn)))
        elif got[0] != ent.sha:
            res.append(("FAIL", "%s changed after %s was built (run: mach sheets build)" % (fn, rel)))
        elif got[1] != ent.row["updated"].strip():
            res.append(("FAIL", "%s: updated=%s but the build recorded %s (run: mach sheets build)" % (fn, ent.row["updated"].strip(), got[1])))
    stale = sorted(set(rec["files"]) - set(e.row["file"].strip() for e in entries))
    if stale:
        res.append(("FAIL", "%s still holds removed file(s): %s (run: mach sheets build)" % (rel, ", ".join(stale))))
    return res


# ----------------------------------------------------------------- build

def plan_build(d, today):
    """Compute what `build` would write. Returns (problems, plan) - plan is None when something blocks the build.

    plan: {"entries", "index_rows", "index_text", "xlsx_bytes", "changes": [str]}
    """
    entries, res = load_entries(d)
    blocking = [m for lv, m in res if lv == "FAIL"]
    indexed = set(e.row["file"].strip() for e in entries)
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.startswith(".") and fn.lower().endswith(".csv") and fn != "index.csv" and fn not in indexed:
            blocking.append("%s is not listed in index.csv (orphan)" % fn)
    if blocking:
        return blocking, None
    xlsx = workbook_path(d)
    prior = read_record(xlsx) if os.path.isfile(xlsx) else None
    prior_files = prior["files"] if prior else {}
    index_rows = []
    for ent in entries:
        fn = ent.row["file"].strip()
        row = dict(ent.row)
        got = prior_files.get(fn)
        cur = row["updated"].strip()
        if got:
            row["updated"] = got[1] if got[0] == ent.sha and valid_date(got[1]) else today
        else:
            row["updated"] = cur if valid_date(cur) else today
        row["rows"] = str(ent.count)
        index_rows.append(row)
    index_text = write_csv_text(INDEX_COLS, [[r[c] for c in INDEX_COLS] for r in index_rows])
    sheets = [{"name": INDEX_SHEET, "header": INDEX_COLS, "rows": [[r[c] for c in INDEX_COLS] for r in index_rows], "numeric": {INDEX_COLS.index("rows")}}]
    for ent, row in zip(entries, index_rows):
        sheets.append({"name": row["sheet_name"].strip(), "header": ent.header, "rows": ent.data, "numeric": set()})
    record = dict((e.row["file"].strip(), (e.sha, r["updated"])) for e, r in zip(entries, index_rows))
    blob = build_xlsx(sheets, record, workbook_name(d))
    changes = []
    with open(os.path.join(d, "index.csv"), encoding="utf-8-sig", newline="") as fh:
        old_index = fh.read()
    if old_index != index_text:
        for ent, row in zip(entries, index_rows):
            fn = ent.row["file"].strip()
            if ent.row["rows"].strip() != row["rows"]:
                changes.append("index.csv: %s rows %s -> %s" % (fn, ent.row["rows"].strip() or "(empty)", row["rows"]))
            if ent.row["updated"].strip() != row["updated"]:
                changes.append("index.csv: %s updated %s -> %s" % (fn, ent.row["updated"].strip() or "(empty)", row["updated"]))
        if not changes:
            changes.append("index.csv: normalised formatting")
    old_blob = None
    if os.path.isfile(xlsx):
        with open(xlsx, "rb") as fh:
            old_blob = fh.read()
    if old_blob != blob:
        changes.append("%s: %s (%d sheets)" % (os.path.basename(xlsx), "create" if old_blob is None else "rewrite", len(sheets)))
    return [], {"entries": entries, "index_rows": index_rows, "index_text": index_text, "xlsx_bytes": blob, "xlsx_path": xlsx,
                "old_index_same": old_index == index_text, "old_blob_same": old_blob == blob, "changes": changes, "sheets": sheets}


# ----------------------------------------------------------------- scaffold

README_TEMPLATE = """# {title}

A mach **sheet set**: `index.csv` is the master index, the CSV files it lists are the source of truth, and `{book}.xlsx`
is generated from them. Edit the CSVs, never the workbook.

## Rules

- `index.csv` has exactly these columns: `{cols}`.
- One row per CSV file: `id` (short, unique), `file` (name of the CSV in this folder), `sheet_name` (unique, at most 31
  characters, none of `[ ] : * ? / \\`; "Index" is taken), `title`, `description`, `owner`, `source`, `generated_by`
  (empty for hand-kept CSVs, otherwise the command that writes it). Leave `updated` and `rows` empty; `build` fills them.
- Every CSV in this folder must be listed, and every listed file must exist. Each CSV starts with a header row.
- Use `~/` or repo-relative paths in cells, never `/home/...` or `/Users/...`.

## Commands

```text
mach sheets lint {dirarg}      check the set (exit 0 OK, 1 warnings, 2 failures)
mach sheets build {dirarg}     update rows/updated in index.csv, then write {book}.xlsx
mach sheets build --dry-run {dirarg}
```

`updated` is the date a CSV's cells last changed, as recorded by `build` (a later `build` keeps the date while the content is
unchanged). Run `lint` before you commit.
"""


def scaffold(d):
    """Files a new set would get: {relative name: text}."""
    book = os.path.basename(os.path.abspath(d))
    return {
        "index.csv": write_csv_text(INDEX_COLS, []),
        "README.md": README_TEMPLATE.format(title=book, book=book, cols=", ".join(INDEX_COLS), dirarg=d),
    }


# ----------------------------------------------------------------- xlsx writer

def col_letter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _text(v):
    v = XML_ILLEGAL.sub("�", v.replace("\r\n", "\n").replace("\r", "\n"))
    return v if len(v) <= MAX_CELL else v[:MAX_CELL]


def _width(header, rows, col):
    longest = max([max([len(x) for x in header[col].split("\n")] or [0])] +
                  [max([len(x) for x in r[col].split("\n")] or [0]) for r in rows[:200] if col < len(r)] or [0])
    return max(8, min(60, longest + 2))


def _sheet_xml(header, rows, numeric, first):
    ncols = max(len(header), 1)
    last = "%s%d" % (col_letter(ncols), len(rows) + 1)
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="%s">' % NS_MAIN]
    out.append('<dimension ref="A1:%s"/>' % last)
    out.append('<sheetViews><sheetView workbookViewId="0"%s><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
               '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews>' % (' tabSelected="1"' if first else ""))
    out.append('<sheetFormatPr defaultRowHeight="15"/>')
    out.append("<cols>" + "".join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (c + 1, c + 1, _width(header, rows, c)) for c in range(len(header))) + "</cols>")
    out.append("<sheetData>")

    def cell(ref, value, style, number=False):
        if value == "":
            return ""
        if number and re.match(r"^\d+$", value):
            return '<c r="%s" s="3"><v>%s</v></c>' % (ref, value)
        return '<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, style, escape(_text(value)))

    out.append('<row r="1">' + "".join(cell("%s1" % col_letter(c + 1), h, 1) for c, h in enumerate(header)) + "</row>")
    for rn, r in enumerate(rows, 2):
        out.append('<row r="%d">' % rn + "".join(cell("%s%d" % (col_letter(c + 1), rn), v, 2, c in numeric) for c, v in enumerate(r)) + "</row>")
    out.append("</sheetData>")
    out.append('<autoFilter ref="A1:%s"/>' % last)
    out.append("</worksheet>")
    return "".join(out)


STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<styleSheet xmlns="%s">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
    '<border><left/><right/><top/><bottom style="thin"><color auto="1"/></bottom><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="right" vertical="top"/></xf>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>' % NS_MAIN
)


def _quote_sheet(name):
    return "'" + name.replace("'", "''") + "'"


def build_xlsx(sheets, record, title):
    """sheets: [{"name", "header", "rows", "numeric"}]; record: {file: (sha, updated)}. Returns the .xlsx bytes (deterministic)."""
    n = len(sheets)
    parts = []   # (name, text) in zip order
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>']
    for i in range(1, n + 1):
        ct.append('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i)
    ct.append('<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
              '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
              '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
              '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/></Types>')
    parts.append(("[Content_Types].xml", "".join(ct)))
    parts.append(("_rels/.rels",
                  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="%s">'
                  '<Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/>'
                  '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                  '<Relationship Id="rId3" Type="%s/extended-properties" Target="docProps/app.xml"/>'
                  '<Relationship Id="rId4" Type="%s/custom-properties" Target="docProps/custom.xml"/></Relationships>'
                  % (NS_PKG_REL, NS_REL, NS_REL, NS_REL)))
    parts.append(("docProps/core.xml",
                  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                  '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                  'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                  'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>%s</dc:title><dc:creator>mach sheets</dc:creator>'
                  '<dcterms:created xsi:type="dcterms:W3CDTF">2000-01-01T00:00:00Z</dcterms:created></cp:coreProperties>' % escape(title)))
    parts.append(("docProps/app.xml",
                  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                  '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>mach sheets</Application></Properties>'))
    props = ['<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="mach.sheets.format"><vt:lpwstr>1</vt:lpwstr></property>']
    for i, fn in enumerate(sorted(record), 3):
        sha, date = record[fn]
        props.append('<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="%d" name=%s><vt:lpwstr>%s;%s</vt:lpwstr></property>'
                     % (i, quoteattr(RECORD_PREFIX + fn), escape(sha), escape(date)))
    parts.append(("docProps/custom.xml",
                  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
                  'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">' + "".join(props) + "</Properties>"))
    wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="%s" xmlns:r="%s"><bookViews><workbookView activeTab="0"/></bookViews><sheets>' % (NS_MAIN, NS_REL)]
    for i, s in enumerate(sheets, 1):
        wb.append('<sheet name=%s sheetId="%d" r:id="rId%d"/>' % (quoteattr(s["name"]), i, i))
    wb.append("</sheets><definedNames>")
    for i, s in enumerate(sheets):
        last = "$%s$%d" % (col_letter(max(len(s["header"]), 1)), len(s["rows"]) + 1)
        wb.append('<definedName name="_xlnm._FilterDatabase" localSheetId="%d" hidden="1">%s!$A$1:%s</definedName>' % (i, escape(_quote_sheet(s["name"])), last))
    wb.append("</definedNames></workbook>")
    parts.append(("xl/workbook.xml", "".join(wb)))
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="%s">' % NS_PKG_REL]
    for i in range(1, n + 1):
        rels.append('<Relationship Id="rId%d" Type="%s/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, NS_REL, i))
    rels.append('<Relationship Id="rId%d" Type="%s/styles" Target="styles.xml"/></Relationships>' % (n + 1, NS_REL))
    parts.append(("xl/_rels/workbook.xml.rels", "".join(rels)))
    parts.append(("xl/styles.xml", STYLES_XML))
    for i, s in enumerate(sheets, 1):
        parts.append(("xl/worksheets/sheet%d.xml" % i, _sheet_xml(s["header"], s["rows"], s.get("numeric", set()), i == 1)))
    buf = io.BytesIO()
    # fixed timestamps, attributes, order and compression level: the same input gives the same bytes (for one zlib version;
    # lint and the build record compare content hashes, never the zip bytes)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts:
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 3
            zi.external_attr = 0o644 << 16
            z.writestr(zi, text.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buf.getvalue()


# ----------------------------------------------------------------- xlsx reader (for lint --deep and tests)

def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path):
    """{sheet name: rows (lists of strings)} for workbooks built by mach (inline strings) or by Excel/openpyxl (shared strings)."""
    out = []
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = dict((r.get("Id"), r.get("Target")) for r in rels)
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS_MAIN)))
        for s in wb.iter("{%s}sheet" % NS_MAIN):
            target = targets[s.get("{%s}id" % NS_REL)]
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            sheet = ET.fromstring(z.read(target))
            rows = []
            for row in sheet.iter("{%s}row" % NS_MAIN):
                vals = []
                for c in row:
                    idx = _col_index(c.get("r"))
                    while len(vals) <= idx:
                        vals.append("")
                    t = c.get("t")
                    if t == "inlineStr":
                        vals[idx] = "".join(x.text or "" for x in c.iter("{%s}t" % NS_MAIN))
                    else:
                        v = c.find("{%s}v" % NS_MAIN)
                        text = v.text if v is not None and v.text is not None else ""
                        vals[idx] = shared[int(text)] if t == "s" and text != "" else text
                rows.append(vals)
            out.append((s.get("name"), rows))
    return out
