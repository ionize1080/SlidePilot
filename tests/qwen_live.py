"""Run the real workspace-to-deck benchmark. Credentials are read only from the supplied file."""
import argparse
import json
import os
from pathlib import Path
import socket
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


def safe_address(address):
    """Never include proxy credentials or URL query values in a diagnostic."""
    parsed = urllib.parse.urlsplit(address if "://" in address else "http://" + address)
    return (parsed.hostname or "unknown") + (":" + str(parsed.port) if parsed.port else "")


def load_key(path):
    key = path.read_text(encoding="utf-8-sig").strip()
    if not key or any(c.isspace() for c in key):
        raise ValueError("The key file must contain one API key, without labels or extra lines.")
    return key


def make_complete(key, model, *, base=BASE, timeout=120, proxy="system", progress=None):
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The provider base URL must be HTTPS and contain no credentials, query, or fragment.")
    proxies = urllib.request.getproxies() if proxy == "system" else ({} if proxy == "direct" else {"https": proxy})
    network = {"endpoint": base.rstrip("/"), "proxy": safe_address(proxies["https"]) if proxies.get("https") else "direct",
               "sandboxNetworkDisabled": os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") == "1"}
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
        except urllib.error.HTTPError as error:
            hints = {401: "Check the API key.", 403: "Check the model and account access.",
                     404: "Check the endpoint and model name.", 429: "Check the plan quota or wait before retrying."}
            raise ProviderError("Provider HTTP " + str(error.code) + ". " + hints.get(error.code, "Check the provider service status.")) from None
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            code = getattr(reason, "winerror", None) or getattr(reason, "errno", None)
            label = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "connection failure"
            detail = " (OS code " + str(code) + ")" if code else ""
            hint = "This execution environment disables network access." if network["sandboxNetworkDisabled"] else "Check DNS, network access, and the system proxy."
            raise ProviderError("Provider " + label + detail + "; route: " + network["proxy"] + ". " + hint) from None
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
    p.add_argument("--proxy", default="system", help="system (default), direct, or an explicit proxy URL")
    opts = p.parse_args()
    if not 1 <= opts.timeout <= 600:
        p.error("--timeout must be between 1 and 600 seconds")
    opts.output.mkdir(parents=True, exist_ok=True)
    def progress(event):
        print(json.dumps(event, ensure_ascii=True), file=sys.stderr, flush=True)
    network = {}
    started = time.perf_counter()
    try:
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
        report = {"passed": False, "kind": "connectivity-probe" if opts.probe else "workspace-to-deck",
                  "error": str(error), "totalSeconds": round(time.perf_counter() - started, 3)}
    report.update(model=opts.model, network=network)
    (opts.output / "latest-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
