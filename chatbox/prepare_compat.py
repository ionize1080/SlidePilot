"""Apply SlidePilot's bounded OpenAI-compatible transport adapters at source level."""
from pathlib import Path
import argparse
import shutil


def apply(src: Path):
    src = Path(src)
    destination = src / "src/shared/models/utils/slidepilot-openai-compat.ts"
    fetch = src / "src/shared/models/utils/fetch-proxy.ts"
    text = fetch.read_text(encoding="utf-8")
    marker = "import { createSlidePilotCompatFetch } from './slidepilot-openai-compat'"
    if marker not in text:
        anchor = "return async (url: RequestInfo | URL, init?: RequestInit) => {"
        if text.count(anchor) != 1 or not text.rstrip().endswith("  }\n}"):
            raise RuntimeError("Chatbox fetch adapter changed; review the compatibility patch before rebuilding.")
        text = marker + "\n" + text.replace(anchor, "return createSlidePilotCompatFetch(async (url: RequestInfo | URL, init?: RequestInit) => {")
        text = text.rstrip()[:-5] + "  })\n}\n"
        fetch.write_text(text, encoding="utf-8")
    elif "return createSlidePilotCompatFetch(async" not in text:
        raise RuntimeError("Incomplete SlidePilot compatibility patch in fetch-proxy.ts")
    shutil.copyfile(Path(__file__).with_name("slidepilot-openai-compat.ts"), destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Prepared Chatbox source directory")
    apply(parser.parse_args().source)
