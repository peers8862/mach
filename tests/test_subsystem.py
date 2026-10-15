"""Subsystem draft grammar, fallback TOML parser and Drafts builder tests."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests' / 'fixtures'
sys.path.insert(0, str(ROOT / 'lib'))
import mach_subsystem as ss
import frontmatter as fm


class SubsystemTests(unittest.TestCase):
    def test_example_minimal_toml(self):
        old = os.environ.get('MACH_FORCE_MINITOML')
        os.environ['MACH_FORCE_MINITOML'] = '1'
        try:
            data = ss.parse((ROOT / 'config/subsystem.example.toml').read_text())
        finally:
            if old is None: os.environ.pop('MACH_FORCE_MINITOML', None)
            else: os.environ['MACH_FORCE_MINITOML'] = old
        self.assertEqual(data['services']['grokbot:Example']['limits'], ['each fire uses Grok Bot quota'])
        self.assertEqual(data['units']['beta']['roles']['lead'], 'user')
        self.assertFalse(any(level == 'FAIL' for level, _ in ss.lint(data, 'demo')))

    def test_setup_roundtrip(self):
        source = FIX / 'templates/subsystem-setup.md'
        data = ss.from_setup(ss.draft(str(source), 'subsystem-setup'))
        self.assertEqual(ss.parse(ss.render(data)), data)
        self.assertFalse(any(level == 'FAIL' for level, _ in ss.lint(data, 'example')))

    def test_textual_unit_update_preserves_comments(self):
        original = '# keep this\n' + ss.render(ss.from_setup(ss.draft(str(FIX / 'templates/subsystem-setup.md'),'subsystem-setup')))
        new = ss.update_unit(original, 'example', {'name':'Updated','kind':'pillar','roles':{'lead':'user'}})
        self.assertIn('# keep this', new)
        self.assertEqual(ss.parse(new)['units']['example']['roles']['lead'], 'user')

    def test_templates_validate(self):
        tdir = FIX / 'templates'
        for p in tdir.glob('*.md'):
            if p.name == 'README.md': continue
            with self.subTest(p=p.name):
                doc = fm.load_prompt_doc(str(p))
                self.assertEqual([], doc.errors)

    def test_hub_deterministic(self):
        script = ROOT / 'tools/build-drafts-hub.py'
        with tempfile.TemporaryDirectory() as d:
            a, b = pathlib.Path(d) / 'a.json', pathlib.Path(d) / 'b.json'
            subprocess.check_call([sys.executable, str(script), '--templates', str(FIX / 'templates'), '--out', str(a)], stdout=subprocess.DEVNULL, env=dict(os.environ, MACH_CONFIG_DIR=d))
            subprocess.check_call([sys.executable, str(script), '--templates', str(FIX / 'templates'), '--out', str(b)], stdout=subprocess.DEVNULL, env=dict(os.environ, MACH_CONFIG_DIR=d))
            before = a.read_bytes()
            self.assertEqual(before, b.read_bytes())
        action = json.loads(before)
        js = action['steps'][0]['data']['script']
        self.assertIn('Bookmark.find(', js)
        self.assertIn('New task brief', js)
        if subprocess.call(['bash','-c','command -v node >/dev/null']) == 0:
            with tempfile.NamedTemporaryFile('w', suffix='.js') as f:
                f.write(js); f.flush()
                subprocess.check_call(['node','--check',f.name])


if __name__ == '__main__': unittest.main()
