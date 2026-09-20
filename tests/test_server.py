"""Check asset serving without opening sockets or adding dependencies."""

from email.message import Message
import io
import unittest
from unittest.mock import patch

from qualeidoscope import ViewerHandler, WEB_ROOT


class Request:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = io.BytesIO()

    def makefile(self, mode, buffering=None):
        return self.input

    def sendall(self, data):
        self.output.write(data)


class ServerTests(unittest.TestCase):
    def request(self, path, headers=None, method="GET"):
        headers = headers or {}
        lines = [f"{method} {path} HTTP/1.0", "Host: localhost"]
        lines.extend(f"{key}: {value}" for key, value in headers.items())
        request = Request(("\r\n".join(lines) + "\r\n\r\n").encode())
        with patch.object(ViewerHandler, "log_message"):
            ViewerHandler(request, ("127.0.0.1", 1234), None)
        head, body = request.output.getvalue().split(b"\r\n\r\n", 1)
        lines = head.decode().split("\r\n")
        parsed = Message()
        for line in lines[1:]:
            key, value = line.split(":", 1)
            parsed[key] = value.strip()
        return int(lines[0].split()[1]), parsed, body

    def test_all_viewer_assets_are_served(self):
        for name in ["index.html", "app.js", "qls.js", "data.js", "data-worker.js", "renderer.js", "style.css", "color.wgsl"]:
            with self.subTest(name=name):
                status, headers, body = self.request("/" if name == "index.html" else f"/{name}")
                self.assertEqual(status, 200)
                self.assertEqual(body, (WEB_ROOT / name).read_bytes())
                self.assertEqual(int(headers["Content-Length"]), len(body))
                self.assertEqual(headers["Cache-Control"], "no-store")
                if name.endswith(".js"):
                    self.assertIn("javascript", headers["Content-Type"])

    def test_cached_assets_are_refreshed_including_module_query_strings(self):
        for name in ["index.html", "app.js?v=3", "renderer.js?v=2", "qls.js", "color.wgsl"]:
            with self.subTest(name=name):
                status, headers, body = self.request(f"/{name}", {
                    "If-Modified-Since": "Thu, 01 Jan 2099 00:00:00 GMT",
                })
                self.assertEqual(status, 200)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(body, (WEB_ROOT / name.split("?")[0]).read_bytes())

    def test_head_has_no_payload(self):
        status, headers, body = self.request("/qls.js", method="HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(int(headers["Content-Length"]), (WEB_ROOT / "qls.js").stat().st_size)

    def test_server_does_not_expose_project_files(self):
        for path in ["/AGENTS.md", "/qualeidoscope.py", "/../qualeidoscope.py", "/.git/config", "/examples/circuit-history.qls"]:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)


if __name__ == "__main__":
    unittest.main()
