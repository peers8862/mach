"""Syncthing REST checks in mach doctor, against a fake local server. The API key must be sent as a header and never appear in results."""
import json
import socket
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.dont_write_bytecode = True

import mach_common as mc  # noqa: E402
import mach_doctor as md  # noqa: E402

KEY = "TESTKEY-do-not-print-0123456789"


def server(status, conns, seen):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append((self.path, self.headers.get("X-API-Key")))
            if self.headers.get("X-API-Key") != KEY:
                self.send_response(403); self.end_headers(); return
            if self.path.startswith("/rest/db/status"):
                if status is None:
                    self.send_response(404); self.end_headers(); return
                body = json.dumps(status).encode()
            elif self.path.startswith("/rest/system/connections"):
                body = json.dumps(conns).encode()
            else:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever)
    t.daemon = True
    t.start()
    return srv


class SyncthingRestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = socket.socket()
            probe.close()
        except OSError:
            raise unittest.SkipTest("loopback sockets unavailable in this sandbox")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mach-rest.", dir=os.path.join(ROOT, ".tmp") if os.path.isdir(os.path.join(ROOT, ".tmp")) else None)
        self.old = dict(os.environ)
        os.environ["HOME"] = self.tmp
        os.environ["MACH_OS"] = "linux"
        os.environ["MACH_HOST"] = "linux-box"
        os.environ["MACH_CONFIG_DIR"] = os.path.join(self.tmp, "cfg")
        os.environ["MACH_MF_ROOT"] = os.path.join(self.tmp, "mf")
        for var in mc.CMD_VARS.values():   # never reach a real systemctl/launchctl/ssh/... from a test
            os.environ[var] = os.path.join(self.tmp, "no-such-bin", var)
        d = os.path.join(self.tmp, ".local", "state", "syncthing")
        os.makedirs(d)
        with open(os.path.join(d, "config.xml"), "w") as fh:
            fh.write("<configuration><gui><apikey>%s</apikey></gui></configuration>" % KEY)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctx(self, url):
        os.makedirs(os.environ["MACH_CONFIG_DIR"], exist_ok=True)
        with open(os.path.join(os.environ["MACH_CONFIG_DIR"], "config.toml"), "w") as fh:
            fh.write('[doctor]\nsyncthing_url = "%s"\n' % url)
        return md.Ctx(mc.load_config())

    def run_check(self, status, conns):
        seen = []
        srv = server(status, conns, seen)
        try:
            res = md.check_syncthing_state(self.ctx("http://127.0.0.1:%d" % srv.server_address[1]))
        finally:
            srv.shutdown()
            srv.server_close()
        text = json.dumps(res)
        self.assertNotIn(KEY, text, "the API key must never appear in results")
        return res, seen

    def test_idle_and_connected(self):
        res, seen = self.run_check({"state": "idle", "errors": 0, "needTotalItems": 0}, {"connections": {"AAAA": {"connected": True}}})
        levels = [r[0] for r in res]
        self.assertEqual(levels, ["OK", "OK"], res)
        self.assertTrue(all(k == KEY for _p, k in seen), "key is sent as the X-API-Key header")
        self.assertIn("/rest/db/status?folder=machine-flows", [p for p, _k in seen])

    def test_folder_errors_and_disconnected_peer(self):
        res, _ = self.run_check({"state": "idle", "errors": 2, "pullErrors": 1}, {"connections": {"AAAA": {"connected": False}}})
        self.assertEqual(res[0][0], "WARN")
        self.assertIn("3 error(s)", res[0][2])
        self.assertEqual(res[1][0], "WARN")
        self.assertIn("no remote device is connected", res[1][2])

    def test_scanning_is_info_and_unknown_folder_fails(self):
        res, _ = self.run_check({"state": "scanning", "errors": 0}, {"connections": {}})
        self.assertEqual(res[0][0], "INFO")
        res, _ = self.run_check(None, {"connections": {}})
        self.assertEqual(res[0][0], "FAIL")
        self.assertIn("HTTP 404", res[0][2])

    def test_unreachable_api_is_a_warning(self):
        res = md.check_syncthing_state(self.ctx("http://127.0.0.1:9"))
        self.assertEqual(res[0][0], "WARN")
        self.assertNotIn(KEY, json.dumps(res))

    def test_no_config_xml_is_skipped(self):
        os.remove(os.path.join(self.tmp, ".local", "state", "syncthing", "config.xml"))
        res = md.check_syncthing_state(self.ctx("http://127.0.0.1:9"))
        self.assertEqual(res[0][0], "INFO")


if __name__ == "__main__":
    unittest.main()
