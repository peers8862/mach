"""Schema parity and execution of the actual generated Drafts action."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import frontmatter as fm


class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=str(ROOT))
        cls.addClassCleanup(cls.temp.cleanup)
        cls.actions = {}
        env = dict(os.environ, MACH_CONFIG_DIR=cls.temp.name,
                   PYTHONDONTWRITEBYTECODE='1')
        for adapter in ('mach', 'na'):
            path = pathlib.Path(cls.temp.name) / (adapter+'.json')
            cmd = [sys.executable, str(ROOT/'tools/build-drafts-hub.py'), '--adapter',
                   str(ROOT/('config/drafts/'+adapter+'.json')), '--templates',
                   str(ROOT/'tests/fixtures/templates'), '--out', str(path)]
            subprocess.check_call(cmd, env=env, stdout=subprocess.DEVNULL)
            before = path.read_bytes()
            subprocess.check_call(cmd, env=env, stdout=subprocess.DEVNULL)
            assert before == path.read_bytes()
            cls.actions[adapter] = json.loads(before)

    def execute(self, requests, adapter='na'):
        if not shutil.which('node'):
            self.skipTest('node missing: Drafts execution tests skipped')
        script = self.actions[adapter]['steps'][0]['data']['script']
        subprocess.run(['node', '--check'], input=script, text=True, check=True, capture_output=True)
        result = subprocess.run(['node', str(ROOT/'tests/drafts_hub_runner.js')],
                                input=json.dumps(dict(script=script, requests=requests)),
                                text=True, check=True, capture_output=True)
        return json.loads(result.stdout)

    def test_identity_and_neutrality(self):
        self.assertEqual(self.actions['na']['uuid'], '25F53AC0-AF0B-53CD-AB30-CA172E50A5E7')
        self.assertEqual(self.actions['na']['steps'][0]['uuid'], '5517EA4C-D6F9-5EB5-B1A6-D47A8B365907')
        self.assertEqual(self.actions['na']['groupUUID'], '0776A915-74D5-5575-AC7A-F6B1029B5AC0')
        hub = json.loads((ROOT/'config/drafts/mach.json').read_text())
        self.assertEqual([t['label'] for t in hub['templates']], ['New task brief','New research brief','New flow'])

    def test_parity(self):
        texts = [p.read_text() for p in sorted((ROOT/'tests/fixtures/templates').glob('*.md'))]
        task = (ROOT/'tests/fixtures/templates/task-brief.md').read_text()
        # Each field gets scalar/list/boolean/empty/malformed variants, plus parser edges.
        for key in fm.SCHEMA['task']['required']+fm.SCHEMA['task']['optional']:
            for value in ('"1"','true','[]','[a, "b,c"]','""','bogus','2026-01-02','[oops','"oops','{x: y}'):
                texts.append(re.sub(r'^'+key+r':.*$',key+': '+value,task,flags=re.M))
        texts += [task.replace('type: task','type: toString'), task.replace('title:', ' title:'), task.replace('---','---  '),
                  task.replace('title: Short name for this task','title: "A # quoted title"'),
                  task.replace('mach: 1','mach: 1\nmach: 1'), 'plain note', '---\nmach: 1',
                  task.replace('title: ', 'title:'),task.replace('tags: []','sources: [invalid]')]
        for source in list(texts[:9]):
            for key in ('due','date','sources','reply','depth','input','output'):
                for value in ('""','[]','true','[web, bad]','[web, "repo"]','2026-01-02','tomorrow'):
                    if re.search(r'^'+key+r':',source,re.M):
                        texts.append(re.sub(r'^'+key+r':.*$',key+': '+value,source,flags=re.M))
        results = self.execute([dict(text=t,choice='Check frontmatter') for t in texts])
        for text, result in zip(texts,results):
            with self.subTest(text=text[:150]):
                doc = fm.validate(fm.parse_text(text))
                self.assertEqual(bool(doc.errors), bool(result['validation']['problems']))
                self.assertEqual(bool(doc.warnings), bool(result['validation']['warnings']))
                self.assertEqual(doc.meta, result['validation']['m'])

    def test_every_template_executes(self):
        for adapter in ('mach','na'):
            config = json.loads((ROOT/('config/drafts/'+adapter+'.json')).read_text())
            for i, template in enumerate(config['templates']):
                text = (ROOT/'tests/fixtures/templates'/template['file']).read_text()
                requests = [dict(text=text,choice=i),dict(text=text,choice='Check frontmatter'),
                            dict(text=text,choice='Show next step'),
                            dict(text=text,choice='Send to mach',tags=['mach-outbox']),
                            dict(text=text,choice='Send to mach',platform='iOS')]
                created, checked, next_step, mac, phone = self.execute(requests,adapter)
                self.assertIsNone(created['failed'])
                if 'due:' in text:
                    self.assertRegex(created['created']['content'], r'(?m)^due: \d{4}-\d{2}-\d{2}$')
                self.assertFalse(fm.validate(fm.parse_text(created['created']['content'])).errors)
                self.assertIn('Valid ',checked['messages'][0])
                self.assertTrue(next_step['messages'])
                self.assertEqual(len(mac['writes']),1)
                self.assertTrue(mac['writes'][0][0].endswith('/drafts-abcdef01-2345-6789-abcd-0123456789ab.md'))
                self.assertEqual(mac['writes'][0][1],text)
                self.assertEqual(mac['content'],text)
                self.assertNotIn('mach-outbox',mac['tags'])
                self.assertIn('mach-sent',mac['tags'])
                self.assertEqual(phone['bookmarks'],0)
                self.assertIn('mach-outbox',phone['tags'])
                self.assertIn('mach inbox pull-drafts --apply on the Mac',phone['messages'][0])

    def test_shipped_artifacts(self):
        for adapter,filename in (('mach','Mach-Hub'),('na','NA-Mach-Hub')):
            action=json.loads((ROOT/('drafts/Importing/'+filename+'.draftsAction')).read_text())
            script=action['steps'][0]['data']['script']
            hub=json.loads(script.splitlines()[0][len('const HUB = '):-1])
            for source in ('frontmatter.js','hub.js'):
                self.assertIn((ROOT/'tools/drafts-hub'/source).read_text(),script)
            # Execute the checked-in action, including its exact embedded templates.
            previous=self.actions[adapter]
            self.actions[adapter]=action
            try:
                results=self.execute([dict(text=t['text'],choice='Check frontmatter') for t in hub['templates']],adapter)
            finally:
                self.actions[adapter]=previous
            for t,result in zip(hub['templates'],results):
                doc=fm.validate(fm.parse_text(t['text']))
                self.assertEqual(bool(doc.errors),bool(result['validation']['problems']))
                self.assertEqual(bool(doc.warnings),bool(result['validation']['warnings']))

    def test_due_uses_local_calendar(self):
        text=(ROOT/'tests/fixtures/templates/task-brief.md').read_text()
        old=os.environ.get('TZ')
        os.environ['TZ']='America/Los_Angeles'
        try:
            result=self.execute([dict(text=text,choice=0,now='2026-01-01T03:00:00Z')])[0]
        finally:
            if old is None:
                os.environ.pop('TZ',None)
            else:
                os.environ['TZ']=old
        self.assertIn('due: 2026-01-01',result['created']['content'])

    def test_resend_cancel_and_failures(self):
        text=(ROOT/'tests/fixtures/templates/task-brief.md').read_text()
        base=dict(text=text,choice='Send to mach')
        results=self.execute([dict(base,cancel=True),dict(base,tags=['mach-sent'],cancelResend=True),
                              dict(base,tags=['mach-sent']),dict(base,throwWrite=True),
                              dict(base,failWrite=True),dict(base,missingBookmark=True)])
        for r in results[:2]:
            self.assertTrue(r['cancelled'])
            self.assertFalse(r['writes'])
        self.assertEqual(len(results[2]['writes']),1)
        for r,reason in zip(results[3:],('disk full','writeString returned false','Missing machine-flows')):
            self.assertIn(reason,r['messages'][0])
            self.assertIn('mach-outbox',r['tags'])
