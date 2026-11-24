"""Run the real workspace-to-deck benchmark. Credentials are read only from the supplied file."""
import argparse
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1"
MODEL = "qwen3.8-flash"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--probe", action="store_true")
    p.add_argument("--output", type=Path, default=ROOT / ".build/qwen")
    p.add_argument("--validator", type=Path)
    opts = p.parse_args()
    key = opts.key_file.read_text(encoding="utf-8-sig").strip()
    opener = urllib.request.build_opener(NoRedirect)
    def complete(messages, tools=None):
        body = {"model":opts.model, "messages":messages, "stream":False}
        if tools:
            body["tools"] = tools
        req = urllib.request.Request(BASE + "/chat/completions", json.dumps(body).encode(),
                                     {"Authorization":"Bearer " + key, "Content-Type":"application/json"})
        try:
            with opener.open(req, timeout=120) as response:
                return json.load(response)["choices"][0]["message"]
        except urllib.error.HTTPError as error:
            raise SystemExit("Provider HTTP " + str(error.code)) from None
        except (urllib.error.URLError, OSError) as error:
            raise SystemExit("Provider connection failed: " + str(getattr(error, "reason", type(error).__name__))) from None
    if opts.probe:
        msg = complete([{"role":"user","content":"Reply with OK."}])
        print("Valid provider response:", bool(msg.get("content")))
        return
    from workspace_benchmark import run_model
    report=run_model(complete, opts.output, opts.validator)
    print(json.dumps(report, ensure_ascii=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
