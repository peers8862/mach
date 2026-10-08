"""Unit tests: minitoml, frontmatter, recipes. Run: python3 -m unittest discover -s tests (python 3.9+)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.dont_write_bytecode = True

import minitoml  # noqa: E402
import frontmatter as fm  # noqa: E402

TEMPLATES = os.path.join(ROOT, "tests", "fixtures", "templates")


class MiniTomlTests(unittest.TestCase):
    def test_scalars_and_tables(self):
        d = minitoml.loads('''
# comment
title = "hello # not a comment"   # real comment
n = 1_000
neg = -5
pi = 3.5
yes = true
no = false
lit = 'C:\\path'
[a]
x = 1
[a.b.c]
y = "deep"
[a."quoted key"]
z = 2
''')
        self.assertEqual(d["title"], "hello # not a comment")
        self.assertEqual(d["n"], 1000)
        self.assertEqual(d["neg"], -5)
        self.assertEqual(d["pi"], 3.5)
        self.assertIs(d["yes"], True)
        self.assertIs(d["no"], False)
        self.assertEqual(d["lit"], "C:\\path")
        self.assertEqual(d["a"]["b"]["c"]["y"], "deep")
        self.assertEqual(d["a"]["quoted key"]["z"], 2)

    def test_arrays_and_inline_tables(self):
        d = minitoml.loads('''
m = ["mcp", "url"]
multi = [
  "a",   # first
  "b",
]
nested = [[1, 2], [3]]
inl = { a = 1, b = "x" }
empty = []
''')
        self.assertEqual(d["m"], ["mcp", "url"])
        self.assertEqual(d["multi"], ["a", "b"])
        self.assertEqual(d["nested"], [[1, 2], [3]])
        self.assertEqual(d["inl"], {"a": 1, "b": "x"})
        self.assertEqual(d["empty"], [])

    def test_escapes(self):
        d = minitoml.loads('s = "a\\nb\\t\\"q\\" \\u00e9"')
        self.assertEqual(d["s"], 'a\nb\t"q" \u00e9')

    def test_errors_have_line_numbers(self):
        for bad, line in (("a = 1\nb\n", 2), ("[x\n", 1), ("a = \"open\n", 1), ("a = 1\na = 2\n", 2), ("[[t]]\n", 1)):
            with self.assertRaises(minitoml.TomlError) as cm:
                minitoml.loads(bad)
            self.assertEqual(cm.exception.line, line, bad)

    def test_matches_tomllib_on_example_config(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs python 3.11+")
        for rel in ("config/config.example.toml", "config/hosts/linux-box.example.toml", "config/hosts/mac-laptop.example.toml"):
            with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
                text = fh.read()
            self.assertEqual(minitoml.loads(text), tomllib.loads(text), rel)

    def test_parse_falls_back_when_tomllib_is_missing(self):
        # setting sys.modules["tomllib"] to None makes the module unimportable, like python 3.9 on the Mac
        saved = sys.modules.get("tomllib", "absent")
        sys.modules["tomllib"] = None
        try:
            with open(os.path.join(ROOT, "config", "config.example.toml"), "r", encoding="utf-8") as fh:
                text = fh.read()
            self.assertEqual(minitoml.parse(text), minitoml.loads(text))
            import mach_common as mc
            os.environ["MACH_CONFIG_DIR"] = os.path.join(ROOT, "config")
            try:
                cfg = mc.load_config()
            finally:
                del os.environ["MACH_CONFIG_DIR"]
            self.assertEqual(cfg.errors, [])
        finally:
            if saved == "absent":
                del sys.modules["tomllib"]
            else:
                sys.modules["tomllib"] = saved

    def test_example_config_has_expected_keys(self):
        with open(os.path.join(ROOT, "config", "config.example.toml"), "r", encoding="utf-8") as fh:
            d = minitoml.loads(fh.read())
        self.assertEqual(d["note"]["default"], "inbox")
        self.assertEqual(d["note"]["dest"]["work"]["type"], "agenda")
        self.assertEqual(d["routes"]["default_tool"], "claude")
        self.assertIn("peer_ssh", d["doctor"])


GOOD_TASK = """---
mach: 1
type: task
title: Tidy
goal: Tidy the headings   # trailing comment
tool: claude
output: stdout
path: ""
tags: [a, "b c"]
---
Body text.
"""


class FrontmatterTests(unittest.TestCase):
    def check(self, text):
        d = fm.parse_text(text)
        fm.validate(d)
        return d

    def test_valid_task(self):
        d = self.check(GOOD_TASK)
        self.assertEqual(d.errors, [], d.errors)
        self.assertEqual(d.meta["goal"], "Tidy the headings")
        self.assertEqual(d.meta["tags"], ["a", "b c"])
        self.assertEqual(d.meta["mach"], 1)
        self.assertEqual(d.body.strip(), "Body text.")
        self.assertEqual(d.lines["goal"], 5)

    def test_unknown_key_has_line_number(self):
        d = self.check(GOOD_TASK.replace("tool: claude", "tool: claude\nbogus: 1"))
        self.assertIn((7, "unknown key 'bogus'"), d.errors)

    def test_key_valid_for_other_type_is_still_unknown_here(self):
        d = self.check(GOOD_TASK.replace("tool: claude", "tool: claude\nquestion: why"))
        self.assertTrue(any("valid for another type" in m for _l, m in d.errors), d.errors)

    def test_bad_values(self):
        for old, new, needle in (("tool: claude", "tool: gpt", "tool:"),
                                 ("output: stdout", "output: ", "output:"),
                                 ("mach: 1", "mach: 2", "schema version"),
                                 ("type: task", "type: nope", "type:")):
            d = self.check(GOOD_TASK.replace(old, new))
            self.assertTrue(any(needle in m for _l, m in d.errors), (old, new, d.errors))

    def test_enum_errors_point_at_the_line(self):
        d = self.check(GOOD_TASK.replace("tool: claude", "tool: gpt"))
        self.assertEqual([l for l, m in d.errors if m.startswith("tool:")], [d.lines["tool"]])

    def test_missing_required_key(self):
        d = self.check(GOOD_TASK.replace("goal: Tidy the headings   # trailing comment\n", ""))
        self.assertTrue(any("missing required key 'goal'" in m for _l, m in d.errors), d.errors)

    def test_missing_mach_type_title_is_an_error(self):
        d = self.check("---\ngoal: x\ntool: claude\noutput: stdout\n---\nbody\n")
        msgs = " | ".join(m for _l, m in d.errors)
        self.assertIn("'type'", msgs)
        self.assertIn("'mach'", msgs)

    def test_no_frontmatter(self):
        d = self.check("just text\n")
        self.assertEqual(d.errors[0][0], 1)

    def test_nesting_and_duplicates_rejected(self):
        d = self.check(GOOD_TASK.replace("tool: claude", "tool: claude\n  nested: yes"))
        self.assertTrue(any("nesting" in m for _l, m in d.errors))
        d = self.check(GOOD_TASK.replace("tool: claude", "tool: claude\ntool: codex"))
        self.assertTrue(any("duplicate key" in m for _l, m in d.errors))

    def test_unclosed_frontmatter(self):
        d = fm.parse_text("---\ntype: task\n")
        self.assertTrue(d.errors)

    def test_bad_date_and_sources(self):
        d = self.check("---\nmach: 1\ntype: research\ntitle: t\nquestion: q\noutput: stdout\ndue: tomorrow\nsources: [web, tv]\n---\n")
        msgs = " | ".join(m for _l, m in d.errors)
        self.assertIn("YYYY-MM-DD", msgs)
        self.assertIn("sources: 'tv'", msgs)

    def test_flow_document_empty_input_is_only_a_warning(self):
        d = self.check("---\nmach: 1\ntype: flow\ntitle: t\nflow: morning\ninput: \"\"\n---\n")
        self.assertEqual(d.errors, [])
        self.assertTrue(d.warnings)

    def test_nested_mode_for_lessons(self):
        d = fm.parse_text("---\nid: L-1\nscope:\n  tools: [all]\n  machines: [linux-box]\nstatus: active\n---\nbody\n", nested=True)
        self.assertEqual(d.errors, [])
        self.assertEqual(d.meta["scope.tools"], ["all"])
        self.assertEqual(d.meta["status"], "active")

    def test_value_parser(self):
        self.assertEqual(fm.parse_value('"a # b" # c'), "a # b")
        self.assertEqual(fm.parse_value("[]"), [])
        self.assertEqual(fm.parse_value("[a, 'b']"), ["a", "b"])
        self.assertEqual(fm.parse_value("12"), 12)
        with self.assertRaises(ValueError):
            fm.parse_value("[a, b")

    def test_the_three_fixture_templates_validate(self):
        for name in ("task-brief.md", "research-brief.md", "flow-request.md"):
            d = fm.load_prompt_doc(os.path.join(TEMPLATES, name))
            self.assertEqual(d.errors, [], (name, d.errors))


RECIPE = """---
mach: 1
type: recipe
name: demo
title: Demo
---
Intro.

## 1. First
tool: claude
prompt: Do {input}
  and more
output: first.md
gate: Check {prev}

## 2. Run mach
cmd: queue

## 3. Hand off
handoff: line one
  line two

## 4. Only a gate
gate: Final OK?
"""


class RecipeTests(unittest.TestCase):
    def test_parse(self):
        r = fm.parse_recipe_text(RECIPE)
        self.assertEqual(r.errors, [], r.errors)
        kinds = [(s.number, s.kind) for s in r.steps]
        # a gate line inside an action step becomes its own step AFTER that step
        self.assertEqual(kinds, [(1, "ai"), (2, "gate"), (3, "cmd"), (4, "handoff"), (5, "gate")])
        self.assertEqual(r.steps[0].prompt, "Do {input} and more")
        self.assertEqual(r.steps[3].handoff, "line one\nline two")
        self.assertEqual(r.steps[1].gate, "Check {prev}")

    def test_errors(self):
        r = fm.parse_recipe_text(RECIPE.replace("tool: claude", "tool: gpt"))
        self.assertTrue(any("tool 'gpt'" in m for _l, m in r.errors))
        r = fm.parse_recipe_text(RECIPE.replace("## 3.", "## 5."))
        self.assertTrue(any("consecutive" in m for _l, m in r.errors))
        r = fm.parse_recipe_text("---\nmach: 1\ntype: recipe\nname: x\n---\nno steps\n")
        self.assertTrue(any("no steps" in m for _l, m in r.errors))

    def test_builtin_recipes_parse(self):
        for name in ("morning", "research-to-plan", "issue-to-pr"):
            r = fm.parse_recipe_file(os.path.join(ROOT, "flows", name + ".md"))
            self.assertEqual(r.errors, [], (name, r.errors))
            self.assertEqual(r.name, name)


class ServicesTableTests(unittest.TestCase):
    TEXT = (
        "# host\n\n"
        "| Name | Type | File path | When | Runs | Who | Roll back | Status |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| A | agent | `~/x.plist` | login | `run --d {h}/a\\|b` | me | `undo \\| x` | active |\n"
        "| B | agent | `~/y.plist` | login | `a | b` | me | rm | active |\n\n"
        "| Name | What it is | Status |\n| --- | --- | --- |\n| Helper | daemon | off |\n"
    )

    def test_only_main_table_and_cells_with_pipes(self):
        import mach_doctor as md
        rows = md.parse_md_table_rows(self.TEXT)
        self.assertEqual([r[0] for r in rows], ["A", "B"])
        self.assertTrue(all(len(r) == 8 for r in rows), rows)
        self.assertEqual(rows[0][4], "`run --d {h}/a|b`")
        self.assertEqual(rows[1][4], "`a | b`")
        self.assertEqual([h[0] for h in md.other_md_tables(self.TEXT)], ["Name"])
        self.assertEqual(len(md.other_md_tables(self.TEXT)[0]), 3)

    def test_jobs_table_header_is_main_too(self):
        import mach_doctor as md
        t = "| Name | Mechanism | File | Schedule | Runs | By | Status | Rollback |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| j | cron | c | d | r | u | active | x |\n"
        self.assertEqual(len(md.parse_md_table_rows(t)), 1)


class ShellPathTests(unittest.TestCase):
    def test_tilde_not_escaped(self):
        import mach_common as mc
        h = mc.home()
        self.assertEqual(mc.shell_path(h + "/a/b.sh"), "~/a/b.sh")
        self.assertEqual(mc.shell_path(h + "/a b/c.sh"), "~/'a b/c.sh'")
        self.assertEqual(mc.shell_path("/opt/x y"), "'/opt/x y'")


if __name__ == "__main__":
    unittest.main()
