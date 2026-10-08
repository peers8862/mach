"""Markdown validity: every .md in docs/ (plus README.md) must render as CommonMark/GFM.

Hermetic: reads only files inside the repo; no network, no HOME. Checks, outside fenced code blocks:
  - a table has a header row, a `---` separator row, and the same column count in every row
    (unescaped pipes count, also inside backticks: GFM splits cells there too, so write `\\|`);
  - a blank line before and after every table, and around every heading;
  - no raw `<tag>` outside backticks (previews swallow it as HTML; `<br>` is the one allowed tag);
  - usage shown as indented code (4+ spaces after a blank line, outside a list) is refused: use a fenced block.
"""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
SEP_CELL = re.compile(r"^\s*:?-{1,}:?\s*$")
LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")
HEADING = re.compile(r"^ {0,3}#{1,6}(\s|$)")


def split_cells(line):
    """Cells of a table row: split on unescaped pipes, ignoring one leading and one trailing pipe."""
    s = line.strip()
    cells, cur, i = [], "", 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            cur += s[i:i + 2]
            i += 2
            continue
        if c == "|":
            cells.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    cells.append(cur)
    if s.startswith("|"):
        cells = cells[1:]
    if s.endswith("|") and not s.endswith("\\|") and cells:
        cells = cells[:-1]
    return cells


def is_separator(line):
    if "|" not in line and "-" not in line:
        return False
    cells = split_cells(line)
    return bool(cells) and all(SEP_CELL.match(c) for c in cells)


RAW_TAG = re.compile(r"<(?!br\s*/?>)/?[A-Za-z][^<>]*>")
CODE_SPAN = re.compile(r"(`+).*?\1")


def raw_tags(line):
    return RAW_TAG.findall(CODE_SPAN.sub("", line))


def check_text(text):
    """Return a list of 'line N: problem' strings."""
    lines = text.split("\n")
    problems = []
    in_fence, fence_ch, in_list = False, "", False
    para, para_start = [], 0

    def flush():
        # code spans may wrap over lines, so look for tags paragraph-wise
        if para:
            for tag in raw_tags(" ".join(para)):
                problems.append("line %d: raw %s outside backticks (wrap it in `code`)" % (para_start, tag))
        del para[:]

    for k, line in enumerate(lines):
        m = FENCE.match(line)
        if m and (not in_fence or m.group(1)[0] == fence_ch):
            flush()
            in_fence, fence_ch = not in_fence, m.group(1)[0]
        elif not in_fence and line.strip():
            if not para:
                para_start = k + 1
            para.append(line)
        else:
            flush()
    flush()
    in_fence, fence_ch = False, ""
    i = 0
    while i < len(lines):
        line, n = lines[i], i + 1
        m = FENCE.match(line)
        if m:
            if not in_fence:
                in_fence, fence_ch = True, m.group(1)[0]
            elif m.group(1)[0] == fence_ch:
                in_fence = False
            i += 1
            continue
        if in_fence:
            i += 1
            continue
        prev = lines[i - 1] if i > 0 else ""
        # headings
        if HEADING.match(line):
            if i > 0 and prev.strip():
                problems.append("line %d: heading needs a blank line before it" % n)
            if i + 1 < len(lines) and lines[i + 1].strip():
                problems.append("line %d: heading needs a blank line after it" % n)
        # tables: a run of lines that contain a pipe and start (after trim) with one, or a header followed by a separator
        starts_table = line.strip().startswith("|") or (
            "|" in line and i + 1 < len(lines) and is_separator(lines[i + 1]) and "|" in lines[i + 1])
        if starts_table and not LIST_ITEM.match(line):
            j = i
            while j < len(lines) and lines[j].strip() and "|" in lines[j] and not FENCE.match(lines[j]):
                j += 1
            block = lines[i:j]
            if i > 0 and prev.strip():
                problems.append("line %d: table needs a blank line before it" % n)
            if j < len(lines) and lines[j].strip():
                problems.append("line %d: table needs a blank line after it" % (j + 1))
            if len(block) < 2 or not is_separator(block[1]):
                problems.append("line %d: table has no separator row (| --- | --- |) after the header" % n)
            else:
                want = len(split_cells(block[0]))
                if len(split_cells(block[1])) != want:
                    problems.append("line %d: separator row has %d columns, header has %d" % (n + 1, len(split_cells(block[1])), want))
                for k, row in enumerate(block[2:], start=2):
                    got = len(split_cells(row))
                    if got != want:
                        problems.append("line %d: row has %d columns, header has %d (unescaped | in a cell?)" % (n + k, got, want))
            i = j
            in_list = False
            continue
        # indented code
        if LIST_ITEM.match(line):
            in_list = True
        elif line.strip() and not line.startswith("  "):
            in_list = False
        elif line.startswith("    ") and line.strip() and not prev.strip() and not in_list:
            problems.append("line %d: indented code block: use a fenced block (```text)" % n)
        i += 1
    if in_fence:
        problems.append("end of file: unclosed code fence")
    return problems


def md_files():
    files = sorted(glob.glob(os.path.join(ROOT, "docs", "**", "*.md"), recursive=True))
    files.append(os.path.join(ROOT, "README.md"))
    return files


class MarkdownFiles(unittest.TestCase):
    def test_every_file_is_valid(self):
        files = md_files()
        names = {os.path.basename(f) for f in files}
        for need in ("COMMANDS.md", "COMMANDS-TABLE.md", "GUIDE.md", "README.md"):
            self.assertIn(need, names)
        for path in files:
            with open(path, encoding="utf-8") as fh:
                problems = check_text(fh.read())
            self.assertEqual(problems, [], "%s: %s" % (os.path.relpath(path, ROOT), "; ".join(problems)))


class CheckerCatchesBadMarkdown(unittest.TestCase):
    GOOD = "# T\n\ntext\n\n| a | b |\n| --- | --- |\n| 1 | `x\\|y` |\n\nafter\n"

    def test_good_passes(self):
        self.assertEqual(check_text(self.GOOD), [])

    def test_column_mismatch(self):
        self.assertTrue(check_text("| a | b |\n| --- | --- |\n| 1 | 2 | 3 |\n"))
        self.assertTrue(check_text("| a | b |\n| --- | --- |\n| 1 | x|y |\n"))
        self.assertTrue(check_text("| a | b |\n| --- | --- |\n| 1 | `x|y` |\n"))

    def test_missing_separator(self):
        self.assertTrue(any("separator" in p for p in check_text("| a | b |\n| 1 | 2 |\n")))

    def test_blank_lines_around_table(self):
        self.assertTrue(any("before" in p for p in check_text("text\n| a |\n| --- |\n| 1 |\n")))
        self.assertTrue(any("after" in p for p in check_text("| a |\n| --- |\n| 1 |\ntext\n")))

    def test_indented_code(self):
        self.assertTrue(any("indented" in p for p in check_text("Usage:\n\n    mach foo [--bar]\n")))
        self.assertEqual(check_text("- item\n\n    continued paragraph\n"), [])

    def test_raw_tags(self):
        self.assertTrue(check_text("| a |\n| --- |\n| mach ask <tool> |\n"))
        self.assertEqual(check_text("| a |\n| --- |\n| `mach ask <tool>` x<br>y |\n"), [])
        self.assertEqual(check_text("a < b and c > d\n"), [])

    def test_fenced_code_is_ignored(self):
        self.assertEqual(check_text("```text\n| not | a table\n    indented\n```\n"), [])

    def test_heading_spacing(self):
        self.assertTrue(check_text("text\n## H\n\nbody\n"))
        self.assertTrue(check_text("## H\nbody\n"))


if __name__ == "__main__":
    unittest.main()
