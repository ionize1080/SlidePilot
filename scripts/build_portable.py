"""Assemble a self-contained Windows x64 distribution from pinned dependencies."""
import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from zipfile import ZIP_DEFLATED, ZipFile

from prepare_chatbox import COMMIT

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0-rc.1"
DIST = ROOT / "dist"
ARCHIVES = {
    "Runtime": ("https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
                "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"),
    "Electron": ("https://github.com/electron/electron/releases/download/v44.7.0/electron-v44.7.0-win32-x64.zip",
                 "eee30dc8fa1f5ea95490e59f44e46ea68dd24c6e93d22facf70fe5c2d4c2665c"),
}
PY_PACKAGES = {"pillow": "13.0.0", "pypdfium2": "5.15.2"}


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def file_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def run(*args, cwd=ROOT):
    subprocess.run([str(item) for item in args], cwd=cwd, check=True)


def runtime_files(out, args):
    for folder, (url, expected) in ARCHIVES.items():
        archive = args.cache / url.rsplit("/", 1)[1]
        if not archive.is_file():
            archive.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, archive)
        if digest(archive) != expected:
            raise ValueError("Unexpected runtime archive digest: " + archive.name)
        with ZipFile(archive) as bundle:
            bundle.extractall(out / folder)
    runtime = out / "Runtime"
    site = runtime / "Lib/site-packages"
    if args.python_packages:
        installed = {d.metadata["Name"].lower(): d for d in
                     importlib.metadata.distributions(path=[str(args.python_packages)])}
        for name, version in PY_PACKAGES.items():
            dist = installed[name]
            if dist.version != version or not dist.files:
                raise ValueError("Incorrect installed distribution: " + name)
            for entry in dist.files:
                if ".." in entry.parts or entry.suffix == ".pyc" or entry.name in ("direct_url.json", "REQUESTED", "INSTALLER"):
                    continue
                source = Path(dist.locate_file(entry))
                if entry.hash:
                    if entry.hash.mode != "sha256":
                        raise ValueError("Unexpected RECORD hash in " + name)
                    actual = base64.urlsafe_b64encode(bytes.fromhex(digest(source))).decode().rstrip("=")
                    if actual != entry.hash.value:
                        raise ValueError("Installed wheel differs from RECORD: " + str(entry))
                file_copy(source, site / entry)
    else:
        run(sys.executable, "-m", "pip", "install", "--only-binary=:all:", "--no-compile",
            "--platform", "win_amd64", "--python-version", "3.12", "--implementation", "cp",
            "--target", site, *(f"{k}=={v}" for k, v in PY_PACKAGES.items()))
    (runtime / "python312._pth").write_text("python312.zip\n.\n../engine\nLib/site-packages\n", encoding="ascii")


def build_native(out, openxml):
    windows = Path(os.environ["WINDIR"])
    csc = windows / "Microsoft.NET/Framework/v4.0.30319/csc.exe"
    office = next((windows / "assembly/GAC_MSIL/office").glob("*/office.dll"))
    ext = next((windows / "assembly/GAC/Extensibility").glob("*/Extensibility.dll"))
    common = [csc, "/nologo", "/optimize+", "/codepage:65001", "/platform:anycpu"]
    run(*common, "/target:library", "/reference:Microsoft.CSharp.dll", "/reference:System.Windows.Forms.dll",
        "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll", f"/link:{office}", f"/link:{ext}",
        f"/out:{out / 'SlidePilot.PowerPoint.dll'}", ROOT/"native/Connect.cs", ROOT/"native/Live.cs", ROOT/"native/OfficeGraph.cs")
    run(*common, "/target:exe", f"/out:{out / 'SlidePilot.Manager.exe'}", ROOT/"native/Manager.cs")
    file_copy(openxml, out / "DocumentFormat.OpenXml.dll")
    windows_base = csc.parent / "WPF/WindowsBase.dll"
    run(*common, "/target:exe", f"/reference:{windows_base}", f"/reference:{openxml}",
        f"/out:{out / 'SlidePilot.Validate.exe'}", ROOT/"tests/validate.cs")


def chatbox_files(out, modules):
    src = ROOT / ".build/chatbox"
    dest = out / "Chatbox"
    if not (src / "release/app/dist/renderer/index.html").is_file():
        raise ValueError("Compile the pinned Chatbox checkout using prepare_chatbox.py first.")
    for filename in ("package.json", "package-lock.json", "bootstrap.cjs"):
        file_copy(ROOT / "chatbox" / filename, dest / filename)
    if modules:
        lock = json.loads((dest / "package-lock.json").read_text())["packages"]
        other = json.loads((modules.parent / "package-lock.json").read_text())["packages"]
        if {k:v for k,v in lock.items() if k} != {k:v for k,v in other.items() if k}:
            raise ValueError("Cached npm runtime differs from the pinned production lock.")
        shutil.copytree(modules, dest / "node_modules", ignore=shutil.ignore_patterns(".bin"))
    else:
        run("npm.cmd", "ci", "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund", cwd=dest)
    shutil.copytree(src / "release/app/dist", dest / "dist", ignore=shutil.ignore_patterns("*.map", "stats.html"))
    shutil.copytree(src / "assets", dest / "resources/assets")
    file_copy(src / "LICENSE", dest / "LICENSE")
    # Retain package notices for libraries compiled into the renderer and main process.
    for manifest in (src / "node_modules/.pnpm").glob("*/node_modules/*/package.json"):
        copy_notices(manifest.parent, dest / "licenses")
    for manifest in (src / "node_modules/.pnpm").glob("*/node_modules/@*/*/package.json"):
        copy_notices(manifest.parent, dest / "licenses")
    (dest / "source-build.json").write_text(json.dumps({"repository":"https://github.com/chatboxai/chatbox",
        "commit":COMMIT, "version":"1.20.3", "build":"electron-vite build"}, indent=2), encoding="utf-8")


def copy_notices(package, dest):
    if package.is_symlink() or os.path.isjunction(package):
        return
    info = json.loads((package / "package.json").read_text(encoding="utf-8-sig"))
    name = info.get("name", "").replace("/", "__")
    if not name or name in (".", ".."):
        return
    for file in package.iterdir():
        if file.is_file() and file.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
            file_copy(file, dest / (name + "-" + str(info.get("version", ""))) / file.name)


def archive_project(out):
    lines = [digest(p) + "  " + p.relative_to(out).as_posix()
             for p in sorted(out.rglob("*")) if p.is_file()]
    (out / "manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    archive = DIST / f"SlidePilot-{VERSION}-portable-win-x64.zip"
    temporary = out.parent / "portable.zip"
    with ZipFile(temporary, "w", ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file():
                z.write(p, "SlidePilot/" + p.relative_to(out).as_posix())
    os.replace(temporary, archive)
    return archive


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=ROOT / ".build/downloads")
    p.add_argument("--python-packages", type=Path, help="Optional verified wheel installation for offline builds")
    p.add_argument("--node-modules", type=Path, help="Optional production modules matching package-lock.json")
    p.add_argument("--openxml", type=Path, required=True, help="Open XML SDK 2.8.1 .NET Framework assembly")
    args = p.parse_args()
    DIST.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=DIST) as temp:
        out = Path(temp) / "SlidePilot"
        out.mkdir()
        build_native(out, args.openxml.resolve())
        runtime_files(out, args)
        chatbox_files(out, args.node_modules)
        for directory in ("engine", "assets", "examples", "licenses"):
            shutil.copytree(ROOT / directory, out / directory, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for filename in ("Enable.cmd", "Disable.cmd", "Status.cmd", "LICENSE", "README.md", "THIRD-PARTY.md", "TESTING.md"):
            file_copy(ROOT / filename, out / filename)
        run(out / "Runtime/python.exe", "-B", "-c", "import PIL.Image, pypdfium2, server")
        run(out / "SlidePilot.Manager.exe", "status")
        archive = archive_project(out)
    print(f"{archive.name}  {archive.stat().st_size} bytes  {digest(archive)}")


if __name__ == "__main__":
    main()
