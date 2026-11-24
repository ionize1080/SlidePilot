"""Offline checks for live-test diagnostics; these never contact a model provider."""
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from qwen_live import BASE, NoRedirect, ProviderError, load_key, make_complete, safe_address
from workspace_benchmark import run_model


class LiveDiagnosticsTests(unittest.TestCase):
    def test_proxy_diagnostic_hides_password_and_query(self):
        self.assertEqual(safe_address("http://user:private@proxy.example:8080/?secret=yes"), "proxy.example:8080")

    def test_key_file_accepts_bom_but_rejects_multiple_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "key.txt"
            path.write_text("sk-test\n", encoding="utf-8-sig")
            self.assertEqual(load_key(path), "sk-test")
            path.write_text("sk-test\nsecond", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one API key"):
                load_key(path)

    def test_http_error_never_exposes_response_body(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(BASE, 401, "sk-sensitive", {}, StringIO("sk-sensitive"))
        with patch("urllib.request.build_opener", return_value=opener):
            complete, _ = make_complete("sk-sensitive", "test", proxy="direct")
            with self.assertRaises(ProviderError) as caught:
                complete([{"role": "user", "content": "OK"}])
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("sensitive", str(caught.exception))

    def test_redirect_and_unsafe_endpoint_are_rejected(self):
        request = urllib.request.Request(BASE)
        self.assertIsNone(NoRedirect().redirect_request(request, None, 302, "redirect", {}, "https://elsewhere.example"))
        for base in ("http://example.com/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=private"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                make_complete("sk-test", "test", base=base)

    def test_response_progress_does_not_contain_content_or_key(self):
        events = []
        opener = Mock()
        opener.open.return_value = StringIO(json.dumps({"choices": [{"message": {"role": "assistant", "content": "private response"}}]}))
        with patch("urllib.request.build_opener", return_value=opener):
            complete, _ = make_complete("sk-private", "test", proxy="direct", progress=events.append)
            self.assertEqual(complete([{"role": "user", "content": "private prompt"}])["content"], "private response")
        self.assertEqual([e["event"] for e in events], ["request", "response"])
        self.assertNotIn("private", json.dumps(events))

    def test_failed_model_run_saves_partial_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            validator = root / "unused-validator.exe"
            validator.touch()
            def failed_provider(*args):
                raise ProviderError("Provider timeout; route: direct.")
            report = run_model(failed_provider, root / "runs", validator)
            self.assertFalse(report["passed"])
            self.assertIn("timeout", report["error"])
            self.assertFalse(report["checks"]["draftCreated"])
            saved = Path(report["runDirectory"]) / "result.json"
            self.assertEqual(json.loads(saved.read_text()), report)


if __name__ == "__main__":
    unittest.main()
