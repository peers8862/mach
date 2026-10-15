"""Hermetic execution metadata and write-approval tests."""
import contextlib
import io
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'lib'))
import frontmatter as fm
import mach_common as mc
import mach_exec as ex
import mach_runs as mr


class Config:
    def get(self, key, default=None):
        return default
    def section(self, key):
        return {}


class RecordsTests(unittest.TestCase):
    def doc(self, extra=''):
        return fm.validate(fm.parse_text('---\nmach: 1\ntype: task\ntitle: Test\ngoal: Test\ntool: codex\noutput: stdout\n'+extra+'---\nBody'))

    def test_permission(self):
        for approval in ('none', 'before-apply', 'before-run'):
            doc=self.doc('permission: write\napproval: '+approval+'\n')
            self.assertTrue(doc.ok)
            plan=ex.plan_doc(doc,Config())
            self.assertEqual(plan['route']['permission'],'write')
            self.assertIn('before-run',plan['gates'])
        self.assertFalse(self.doc('permission: execute\n').ok)

    def test_gate_execution_transcript_and_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=mr.Run(tmp)
            run.meta=dict(id='test',kind='run',tool='codex',permission='write',path_abs=tmp,status='queued')
            pathlib.Path(tmp,'input.md').write_text('---\nmach: 1\ntype: task\ntitle: Test\ngoal: Test\ntool: codex\noutput: stdout\npermission: write\napproval: none\n---\nBody')
            transcript='private full output\n429 rate limit quota exceeded\nfatal: cannot create .git/index.lock: Read-only file system\n'
            output=io.StringIO()
            with patch.object(mc,'tool_available',return_value=True), patch.object(mr,'tee_exec',return_value=(0,transcript, "")) as execute, contextlib.redirect_stdout(output):
                self.assertEqual(ex.continue_prompt_run(run,Config(),ex.Reporter()),3)
                self.assertFalse(execute.called)
                self.assertIn('picked_up',run.meta)
                self.assertIn('approval_requested',run.meta)
                self.assertEqual(ex.approve_run(run,Config(),ex.Reporter()),0)
                self.assertFalse(execute.call_args.args[3])
            self.assertNotIn('private full output',output.getvalue())
            self.assertIn('Transcript:',output.getvalue())
            self.assertEqual(pathlib.Path(tmp,'transcript.txt').read_text(),transcript)
            for key in ('approval_approved','agent_start','agent_end','elapsed_seconds'):
                self.assertIn(key,run.meta)
            self.assertEqual(run.meta['actual_tool'],'codex')
            self.assertEqual(run.meta['fallbacks'],[])
            self.assertEqual(run.meta['quota_errors'], [])
            self.assertTrue(run.meta['warnings'])
            restored=mr.load_run(tmp)
            self.assertEqual(restored.meta['actual_tool'],'codex')
            self.assertTrue(restored.meta['warnings'])

    def test_real_process_diagnostics(self):
        cases = [
            (0, 'print("quota exceeded 429")', '', False, False),
            (1, 'diff: + quota = 429', 'unrelated failure', False, False),
            (1, '', 'HTTP 429: too many requests', True, False),
            (2, '', 'quota exceeded', True, False),
            (0, '', 'quota mentioned on stderr', False, False),
            (0, "fatal: Unable to create '/repo/.git/index.lock': Permission denied", '', False, True),
            (0, 'fatal: index.lock: Read-only file system', '', False, True),
            (0, 'fatal: /repo/.git/objects: Permission denied', '', False, True),
            (0, 'index.lock documentation', '', False, False),
        ]
        root = pathlib.Path(__file__).resolve().parents[1]
        for rc, stdout, stderr, quota, warning in cases:
            with self.subTest(rc=rc, stdout=stdout, stderr=stderr), tempfile.TemporaryDirectory(dir=root) as tmp:
                run = mr.Run(tmp)
                run.meta = dict(id='diagnostics')
                script = 'import sys; print(%r); print(%r, file=sys.stderr); sys.exit(%d)' % (stdout, stderr, rc)
                with patch.object(mc, 'tool_argv', return_value=([sys.executable, '-c', script], None, '')), patch.object(mr, 'log_path', return_value=str(pathlib.Path(tmp)/'local.log')):
                    actual, text, _ = ex.exec_ai(run, 1, 'codex', '', tmp, False, Config(), False)
                self.assertEqual(actual, rc)
                restored = mr.load_run(tmp)
                self.assertEqual(bool(restored.meta['quota_errors']), quota)
                self.assertEqual(bool(restored.meta.get('git_sandbox_warnings')), warning)
                self.assertIn(stdout, text)
                self.assertIn(stderr, text)
                self.assertEqual(pathlib.Path(tmp, 'transcript.txt').read_text(), text)
