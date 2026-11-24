"""Run the real workspace-to-deck benchmark. Credentials are read only from the supplied file."""
import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import re
import time
import urllib.request
import urllib.error
import urllib.parse
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1"
MODEL = "qwen3.8-flash"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProviderError(RuntimeError):
    """A credential-free, actionable diagnostic suitable for a saved test report."""
    def __init__(self, message, diagnostic=None):
        super().__init__(message)
        self.diagnostic = diagnostic or {}


def safe_address(address):
    """Never include proxy credentials or URL query values in a diagnostic."""
    try:
        parsed = urllib.parse.urlsplit(address if "://" in address else "http://" + address)
        host = (parsed.hostname or "").encode("idna").decode("ascii")
        port = parsed.port
        if not host or not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host):
            return "invalid-address"
        if ":" in host:
            host = "[" + host + "]"
        return host + (":" + str(port) if port else "")
    except (TypeError, ValueError, UnicodeError):
        return "invalid-address"


def proxy_configuration(mode, endpoint_host):
    """Describe urllib's configured route; never claim to observe a connection."""
    if mode == "system":
        environment = urllib.request.getproxies_environment()
        proxies = environment or urllib.request.getproxies()
        source = "environment" if environment else "windows-registry" if proxies and os.name == "nt" else "system" if proxies else "none"
    elif mode == "direct":
        proxies, source = {}, "explicit-direct"
    else:
        proxies, source = {"https": mode}, "explicit-proxy"
    configured = proxies.get("https")
    bypass, expected = None, "direct"
    if configured:
        try:
            parsed = urllib.parse.urlsplit(configured if "://" in configured else "http://" + configured)
            if parsed.scheme not in ("http", "https") or safe_address(configured) == "invalid-address":
                raise ValueError
        except (TypeError, ValueError, UnicodeError):
            raise ValueError("Python urllib requires a valid HTTP/HTTPS proxy URL; desktop SOCKS/PAC settings are not shared.") from None
        try:
            # ProxyHandler applies bypass rules even to an explicitly selected proxy.
            bypass = bool(urllib.request.proxy_bypass(endpoint_host))
            expected = "direct" if bypass else "proxy"
        except (OSError, ValueError):
            expected = "unresolved"
    return proxies, {"proxyMode": mode if mode in ("system", "direct") else "explicit",
                     "proxySource": source, "configuredProxy": safe_address(configured) if configured else None,
                     "bypassMatched": bypass, "expectedRoute": expected, "actualRoute": "not-observed",
                     "allProxyIgnoredForHttps": bool(proxies.get("all")) and not bool(configured)}


def transport_diagnostic(error):
    """Only fixed templates and numeric codes leave this boundary."""
    if isinstance(error, urllib.error.HTTPError):
        status = error.code if type(error.code) is int and 100 <= error.code <= 599 else None
        if status is not None and 300 <= status < 400:
            return "redirect_rejected", "HTTP redirect refused; verify the configured endpoint. The redirect target was not followed.", {"httpStatus": status}
        if status == 407:
            return "proxy_authentication", "HTTP 407 requires proxy authentication.", {"httpStatus": status}
        hints = {401: "Check provider or intermediary authentication.", 403: "Check account access and intermediary access policies.",
                 404: "Check the endpoint and model name.", 429: "Check service limits or retry later."}
        message = "HTTP " + (str(status) if status is not None else "error") + " received; the response may originate from the provider or an intermediary. "
        return "http_response", message + hints.get(status, "Check the configured route and service status."), {"httpStatus": status, "responseOrigin": "unconfirmed"}
    reason = getattr(error, "reason", error)
    code = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
    code = code if type(code) is int else None
    details = {"osCode": code, "failingHop": "unknown"}
    if isinstance(reason, http.client.HTTPException):
        return "http_protocol", "The connection returned an incomplete or malformed HTTP response; its origin is unconfirmed.", details
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "tls_certificate", "TLS certificate verification failed; inspect certificate trust and the configured route.", details
    if isinstance(reason, ssl.SSLError):
        return "tls_handshake", "TLS negotiation failed; the failing endpoint or intermediary is not identified.", details
    if isinstance(reason, socket.gaierror):
        return "dns_resolution", "DNS resolution failed; this observation does not identify whether the provider or proxy name failed.", details
    if isinstance(reason, (TimeoutError, socket.timeout)) or code in (60, 110, 10060):
        return "timeout", "Connection or response timeout; the failing network hop and cause are unknown.", details
    if isinstance(reason, ConnectionRefusedError) or code in (61, 111, 10061):
        return "connection_refused", "A connection was refused; the rejecting network hop is unknown.", details
    # urllib creates this fixed prefix when a CONNECT response rejects its tunnel.
    # Extract only its status number, never its reason text, URL, or credentials.
    tunnel = re.search(r"Tunnel connection failed:\s*([1-5][0-9]{2})\b", str(reason)[:4096])
    if tunnel:
        status = int(tunnel.group(1))
        return "proxy_tunnel_http", "HTTP CONNECT tunnel returned " + str(status) + "; this identifies a proxy-path response, not a provider outage.", {"httpStatus": status, "failingHop": "proxy-path"}
    return "connection_failure", "Connection failed; DNS, proxy, TLS and provider causes have not been distinguished.", details


def load_key(path):
    key = path.read_text(encoding="utf-8-sig").strip()
    if not key or any(c.isspace() for c in key):
        raise ValueError("The key file must contain one API key, without labels or extra lines.")
    return key


def make_complete(key, model, *, base=BASE, timeout=120, proxy="system", progress=None):
    try:
        parsed = urllib.parse.urlsplit(base)
        valid = parsed.scheme == "https" and parsed.hostname and not (parsed.username or parsed.password or parsed.query or parsed.fragment) and safe_address(base) != "invalid-address" and not any(ord(c) < 32 or ord(c) == 127 for c in base)
    except (TypeError, ValueError, UnicodeError):
        valid = False
    if not valid:
        raise ValueError("The provider base URL must be HTTPS and contain no credentials, query, or fragment.")
    proxies, route = proxy_configuration(proxy, parsed.netloc)
    network = {"endpointOrigin": "https://" + safe_address(base), "client": "python-urllib", "stream": False,
               "desktopProxySettingsApplied": False, **route,
               "executorNetworkRestrictionFlag": os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") == "1"}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies), NoRedirect)
    request_count = 0

    def complete(messages, tools=None):
        nonlocal request_count
        request_count += 1
        if progress:
            progress({"event": "request", "number": request_count, "messages": len(messages), "model": model})
        body = {"model": model, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                                     {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            with opener.open(req, timeout=timeout) as response:
                result = json.load(response)
            msg = result["choices"][0]["message"]
            if not isinstance(msg, dict) or not (msg.get("content") or msg.get("tool_calls")):
                raise ProviderError("Provider returned an empty assistant message.")
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            category, message, details = transport_diagnostic(error)
            network["lastError"] = {"category": category, **details}
            raise ProviderError(message, network["lastError"]) from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("Provider response is not a valid chat-completions message.") from None
        if progress:
            progress({"event": "response", "number": request_count, "seconds": round(time.perf_counter() - started, 3),
                      "tools": [c.get("function", {}).get("name") for c in msg.get("tool_calls", [])]})
        return msg
    return complete, network


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--probe", action="store_true")
    p.add_argument("--output", type=Path, default=ROOT / ".build/qwen")
    p.add_argument("--validator", type=Path)
    p.add_argument("--base-url", default=BASE)
    p.add_argument("--timeout", type=float, default=120, help="Per-request timeout in seconds")
    p.add_argument("--proxy", default="system", help="urllib environment/OS proxy discovery (system, default), direct, or an HTTP/HTTPS proxy URL; desktop settings are separate")
    opts = p.parse_args()
    if not 1 <= opts.timeout <= 600:
        p.error("--timeout must be between 1 and 600 seconds")
    def progress(event):
        print(json.dumps(event, ensure_ascii=True), file=sys.stderr, flush=True)
    network = {}
    started = time.perf_counter()
    try:
        opts.output.mkdir(parents=True, exist_ok=True)
        complete, network = make_complete(load_key(opts.key_file), opts.model, base=opts.base_url,
                                          timeout=opts.timeout, proxy=opts.proxy, progress=progress)
        progress({"event": "network", **network})
        if opts.probe:
            msg = complete([{"role": "user", "content": "Reply with OK."}])
            report = {"passed": bool(msg.get("content")), "kind": "connectivity-probe"}
        else:
            # Embedded Python uses a fixed ._pth and omits the script's directory.
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from workspace_benchmark import run_model
            report = run_model(complete, opts.output, opts.validator, progress=progress)
            report["kind"] = "workspace-to-deck"
    except (ProviderError, ValueError, OSError) as error:
        # Do not record response bodies, authorization headers, or the key-file contents.
        message = str(error) if isinstance(error, ProviderError) else (
            "Invalid test configuration or key-file encoding. Check the command options and key-file format."
            if isinstance(error, ValueError) else "A required local file could not be accessed. Check file locations and permissions.")
        report = {"passed": False, "kind": "connectivity-probe" if opts.probe else "workspace-to-deck",
                  "error": message, "totalSeconds": round(time.perf_counter() - started, 3)}
    report.update(model=opts.model, network=network)
    try:
        (opts.output / "latest-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        report.update(passed=False, reportSaved=False, reportError="The diagnostic report could not be saved. Check output-folder access.")
    print(json.dumps(report, ensure_ascii=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
