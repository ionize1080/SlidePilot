"""Build Chatbox CE from its pinned upstream revision. All writes stay in this checkout."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".build/chatbox"
COMMIT = "d3cd0ad1e6a1127bbbf3991bb5296c181f4cbdeb"
sys.path.insert(0, str(ROOT / "chatbox"))
import workspace_source
import prepare_compat
import provider_source
import prepare_provider_registry


def run(*args, cwd=ROOT, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mirror", default="https://github.com/chatboxai/chatbox.git")
    parser.add_argument("--archive", type=Path, help="Pinned git archive included in the source distribution")
    parser.add_argument("--deps", type=Path)
    parser.add_argument("--node", default="node")
    parser.add_argument("--reuse-source", action="store_true", help="Rebuild existing patched source and dependencies offline")
    args = parser.parse_args()
    SRC.parent.mkdir(exist_ok=True)
    if args.reuse_source:
        if not (SRC / "src/renderer/components/InputBox/SlidePilotControls.tsx").exists():
            raise RuntimeError("No existing patched Chatbox source is available")
    elif args.archive or Path(args.mirror).is_dir():
        # A local source archive also works with shallow mirrors and on machines
        # without the Git for Windows Unix process launcher.
        archive = args.archive or SRC.parent / "chatbox-upstream.zip"
        if not args.archive:
            run("git", "-C", args.mirror, "archive", COMMIT, "-o", str(archive))
        SRC.mkdir(exist_ok=True)
        with ZipFile(archive) as source:
            if source.comment != COMMIT.encode("ascii"):
                raise ValueError("Archive must be a git archive of the pinned Chatbox revision")
            source.extractall(SRC)
        if not (SRC / ".git").exists():
            run("git", "init", "-q", cwd=SRC)
    else:
        if not (SRC / ".git").exists():
            run("git", "clone", "--no-checkout", args.mirror, str(SRC))
        run("git", "checkout", "--detach", COMMIT, cwd=SRC)
    patch = ROOT / "chatbox/slidepilot.patch"
    provider_source.restore(SRC)
    workspace_source.restore(SRC)
    if not args.reuse_source and subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=SRC, capture_output=True).returncode:
        run("git", "apply", "--whitespace=nowarn", str(patch), cwd=SRC)
    workspace_source.apply(SRC)
    prepare_compat.apply(SRC)
    provider_source.apply(SRC)
    prepare_provider_registry.apply(SRC)
    env = dict(os.environ, ELECTRON_SKIP_BINARY_DOWNLOAD="1", HUSKY="0", NODE_OPTIONS="--max-old-space-size=8192", NODE_ENV="development")
    if args.reuse_source:
        if not (SRC / "node_modules/electron-vite/bin/electron-vite.js").exists():
            raise RuntimeError("Existing Chatbox build dependencies are unavailable")
    elif args.deps:
        if not (SRC / "node_modules/electron-vite/bin/electron-vite.js").exists():
            shutil.copytree(args.deps, SRC / "node_modules", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".vite", ".cache", ".vite-temp"))
    else:
        run("pnpm.cmd" if os.name == "nt" else "pnpm", "install", "--frozen-lockfile", "--ignore-scripts", cwd=SRC, env=env)
    env["NODE_ENV"] = "production"
    run(args.node, "node_modules/electron-vite/bin/electron-vite.js", "build", cwd=SRC, env=env)
    workspace_source.append_preload(SRC)
    if not (SRC / "release/app/dist/renderer/index.html").is_file():
        raise RuntimeError("Renderer missing after compilation")


if __name__ == "__main__":
    main()
