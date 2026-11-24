"""Offline checks for live-test diagnostics; these never contact a model provider."""
from io import StringIO
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from qwen_live import BASE, NoRedirect, ProviderError, load_key, make_complete, safe_address, main
from workspace_benchmark import run_model


class LiveDiagnosticsTests(unittest.TestCase):
    def test_proxy_diagnostic_hides_password_and_query(self):
        self.assertEqual(safe_address("http://user:private@proxy.example:8080/?secret=yes"), "proxy.example:8080")
        self.assertEqual(safe_address("http://user:private@proxy.example:private"), "invalid-address")
        self.assertEqual(safe_address("http://[::1]:8080"), "[::1]:8080")

    def test_system_proxy_records_environment_and_bypass_without_claiming_actual_route(self):
        proxies = {"https":"http://user:private@proxy.example:8080", "no":"provider.example"}
        with patch("urllib.request.getproxies_environment", return_value=proxies), \
             patch("urllib.request.getproxies", side_effect=AssertionError("Environment must take precedence")), \
             patch("urllib.request.proxy_bypass", side_effect=lambda host: urllib.request.proxy_bypass_environment(host, proxies)):
            _, network = make_complete("sk-test", "test", base="https://provider.example/private-path/v1")
            request = urllib.request.Request("https://provider.example/v1/chat/completions")
            handler = urllib.request.ProxyHandler(proxies)
            self.assertIsNone(handler.https_open(request))
            self.assertEqual(request.host, "provider.example")
        self.assertEqual(network["proxySource"], "environment")
        self.assertEqual(network["configuredProxy"], "proxy.example:8080")
        self.assertTrue(network["bypassMatched"])
        self.assertEqual(network["expectedRoute"], "direct")
        self.assertEqual(network["actualRoute"], "not-observed")
        self.assertEqual(network["endpointOrigin"], "https://provider.example")
        self.assertFalse(network["desktopProxySettingsApplied"])
        self.assertNotIn("private", json.dumps(network))

    def test_system_registry_proxy_and_explicit_proxy_are_distinct(self):
        with patch("urllib.request.getproxies_environment", return_value={}), \
             patch("urllib.request.getproxies", return_value={"https":"http://proxy.example:8080"}), \
             patch("urllib.request.proxy_bypass", return_value=False):
            _, network = make_complete("sk-test", "test")
        self.assertEqual(network["proxySource"], "windows-registry" if os.name == "nt" else "system")
        self.assertEqual(network["expectedRoute"], "proxy")
        with patch("urllib.request.proxy_bypass", return_value=True):
            _, explicit = make_complete("sk-test", "test", proxy="http://user:private@proxy.example:8080")
        self.assertEqual(explicit["proxySource"], "explicit-proxy")
        self.assertEqual(explicit["expectedRoute"], "direct")
        self.assertTrue(explicit["bypassMatched"])

    def test_all_proxy_is_not_falsely_reported_as_an_https_proxy(self):
        with patch("urllib.request.getproxies_environment", return_value={"all":"http://user:private@proxy.example:8080"}):
            _, network = make_complete("sk-test", "test")
        self.assertIsNone(network["configuredProxy"])
        self.assertEqual(network["expectedRoute"], "direct")
        self.assertTrue(network["allProxyIgnoredForHttps"])
        self.assertNotIn("private", json.dumps(network))

    def test_unsupported_or_malformed_proxy_errors_never_echo_credentials(self):
        for proxy in ("socks5://user:private@proxy.example:1080", "http://user:private@proxy.example:private"):
            with self.subTest(proxy_type=proxy.split(":")[0]), self.assertRaises(ValueError) as caught:
                make_complete("sk-test", "test", proxy=proxy)
            self.assertIn("HTTP/HTTPS", str(caught.exception))
            self.assertNotIn("private", str(caught.exception))

    def failure(self, error, *, restricted=False):
        opener = Mock()
        opener.open.side_effect = error
        with patch("urllib.request.build_opener", return_value=opener), \
             patch.dict(os.environ, {"CODEX_SANDBOX_NETWORK_DISABLED":"1" if restricted else "0"}):
            complete, network = make_complete("sk-sensitive", "test", proxy="direct")
            with self.assertRaises(ProviderError) as caught:
                complete([{"role":"user", "content":"Synthetic test"}])
        self.assertNotIn("sensitive", str(caught.exception))
        self.assertNotIn("sensitive", json.dumps(network))
        return str(caught.exception), network

    def test_timeout_does_not_prove_sandbox_proxy_or_provider_failure(self):
        message, network = self.failure(urllib.error.URLError(socket.timeout("sensitive timeout detail")), restricted=True)
        self.assertEqual(network["lastError"]["category"], "timeout")
        self.assertEqual(network["lastError"]["failingHop"], "unknown")
        self.assertTrue(network["executorNetworkRestrictionFlag"])
        self.assertIn("unknown", message)
        self.assertNotIn("disables network", message)
        self.assertNotIn("system proxy", message)

    def test_http_gateway_and_connect_tunnel_have_different_evidence(self):
        message, http = self.failure(urllib.error.HTTPError(BASE, 502, "sensitive", {}, StringIO("sensitive")))
        self.assertEqual(http["lastError"]["category"], "http_response")
        self.assertEqual(http["lastError"]["httpStatus"], 502)
        self.assertEqual(http["lastError"]["responseOrigin"], "unconfirmed")
        self.assertIn("provider or an intermediary", message)
        message, tunnel = self.failure(urllib.error.URLError(OSError("Tunnel connection failed: 502 sensitive")))
        self.assertEqual(tunnel["lastError"]["category"], "proxy_tunnel_http")
        self.assertEqual(tunnel["lastError"]["httpStatus"], 502)
        self.assertIn("CONNECT", message)

    def test_dns_tls_and_refusal_do_not_expose_raw_os_errors(self):
        cases = ((socket.gaierror(11001, "sensitive hostname"), "dns_resolution"),
                 (ssl.SSLCertVerificationError(1, "sensitive certificate"), "tls_certificate"),
                 (ssl.SSLError(1, "sensitive handshake"), "tls_handshake"),
                 (ConnectionRefusedError(10061, "sensitive peer"), "connection_refused"))
        for reason, category in cases:
            with self.subTest(category=category):
                _, network = self.failure(urllib.error.URLError(reason))
                self.assertEqual(network["lastError"]["category"], category)
                self.assertEqual(network["lastError"]["failingHop"], "unknown")

    def test_malformed_http_status_is_reported_without_raw_server_text(self):
        message, network = self.failure(http.client.BadStatusLine("sensitive server text"))
        self.assertEqual(network["lastError"]["category"], "http_protocol")
        self.assertIn("unconfirmed", message)

    def test_redirect_and_proxy_authentication_are_explicit(self):
        for status, category in ((302, "redirect_rejected"), (407, "proxy_authentication")):
            with self.subTest(status=status):
                _, network = self.failure(urllib.error.HTTPError(BASE, status, "sensitive", {}, StringIO("sensitive")))
                self.assertEqual(network["lastError"]["category"], category)
                self.assertEqual(network["lastError"]["httpStatus"], status)

    def test_invalid_key_encoding_is_not_written_as_raw_exception_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "key.txt"
            key.write_bytes(b"\xffsensitive")
            output = StringIO()
            with patch.object(sys, "argv", ["qwen_live.py", "--key-file", str(key), "--probe", "--output", str(root / "report")]), \
                 patch("sys.stdout", output), self.assertRaises(SystemExit):
                main()
            report = json.loads((root / "report/latest-result.json").read_text())
            self.assertFalse(report["passed"])
            self.assertNotIn("sensitive", output.getvalue())
            self.assertNotIn("codec", report["error"])

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
        for base in ("http://example.com/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=private", "https://example.com/\nprivate"):
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
