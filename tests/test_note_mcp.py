"""Agenda MCP delivery for `mach note agenda`, against a local fake MCP server (no real app, no network beyond 127.0.0.1)."""
import json
import socket
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.dont_write_bytecode = True

import mach_note as mn  # noqa: E402


def make_server(mode):
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            calls.append(body)
            if mode == "http500":
                self.send_response(500); self.end_headers(); return
            method = body.get("method")
            if method == "notifications/initialized":
                self.send_response(202); self.end_headers(); return
            if method == "initialize":
                resp = {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-03-26", "capabilities": {}}}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Mcp-Session-Id", "sess-1")
                data = json.dumps(resp).encode()
            else:
                if mode == "toolerror":
                    resp = {"jsonrpc": "2.0", "id": body["id"], "result": {"isError": True, "content": []}}
                else:
                    resp = {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": "created"}]}}
                self.send_response(200)
                if mode == "sse":
                    self.send_header("Content-Type", "text/event-stream")
                    data = ("event: message\ndata: %s\n\n" % json.dumps(resp)).encode()
                else:
                    self.send_header("Content-Type", "application/json")
                    data = json.dumps(resp).encode()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever)
    t.daemon = True
    t.start()
    return srv, calls


class AgendaMcpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = socket.socket()
            probe.close()
        except OSError:
            raise unittest.SkipTest("loopback sockets unavailable in this sandbox")

    def run_mode(self, mode):
        srv, calls = make_server(mode)
        try:
            url = "http://127.0.0.1:%d/mcp" % srv.server_address[1]
            note = mn.Note("buy milk and eggs", title="Shopping", tags=["home"], project="Inbox", date="2026-10-09")
            return mn.agenda_mcp(url, note, {"project": "Default"}), calls
        finally:
            srv.shutdown()
            srv.server_close()

    def test_success_json(self):
        used, calls = self.run_mode("json")
        self.assertEqual(used, "mcp")
        call = [c for c in calls if c.get("method") == "tools/call"][0]
        self.assertEqual(call["params"]["name"], "create_note")
        args = call["params"]["arguments"]
        self.assertEqual(args["title"], "Shopping")
        self.assertEqual(args["project"], "Inbox")
        self.assertEqual(args["date"], "2026-10-09")
        self.assertTrue(args["text"].endswith("#home"))

    def test_success_sse(self):
        used, _calls = self.run_mode("sse")
        self.assertEqual(used, "mcp")

    def test_tool_error_is_a_failure(self):
        with self.assertRaises(mn.NoteError):
            self.run_mode("toolerror")

    def test_http_error_is_a_failure(self):
        with self.assertRaises(mn.NoteError):
            self.run_mode("http500")

    def test_unreachable(self):
        with self.assertRaises(mn.NoteError) as cm:
            mn.agenda_mcp("http://127.0.0.1:9/mcp", mn.Note("x"), {}, timeout=1)
        self.assertIn("not reachable", str(cm.exception))

    def test_urls_are_encoded(self):
        n = mn.Note("a b&c=d", title="T t", tags=["x"], project="P Q", flag=True)
        u = mn.agenda_url(n, {})
        self.assertTrue(u.startswith("agenda://x-callback-url/create-note?project-title=P%20Q&title=T%20t&text="))
        self.assertIn("a%20b%26c%3Dd", u)
        d = mn.drafts_url(n, {})
        self.assertTrue(d.startswith("drafts://x-callback-url/create?text="))
        self.assertIn("&tag=x&flagged=true", d)


if __name__ == "__main__":
    unittest.main()
