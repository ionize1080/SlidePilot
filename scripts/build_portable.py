"""Assemble a self-contained Windows x64 distribution from pinned dependencies."""
import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from zipfile import ZIP_DEFLATED, ZipFile

from prepare_chatbox import COMMIT

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0-rc.4"
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


def safe_zip_path(name):
    """Reject paths that ZIP/Windows would normalize into a different target."""
    path = PurePosixPath(name)
    clean = name[:-1] if name.endswith("/") else name
    if (not clean or path.is_absolute() or path.as_posix() != clean or
            any(c in name for c in '\\:*?"<>|') or any(ord(c) < 32 for c in name)):
        raise ValueError("Unsafe portable archive path: " + repr(name))
    for part in path.parts:
        if part in (".", "..") or part.rstrip(" .") != part or PureWindowsPath(part).is_reserved():
            raise ValueError("Unsafe portable archive path: " + repr(name))
    return path


def restore_base_dependencies(archive, out, lockfile=None):
    """Reuse only verified dependencies, never old application code or binaries."""
    archive = Path(archive)
    out = Path(out).resolve()
    lockfile = Path(lockfile or ROOT / "chatbox/package-lock.json")
    prefix = "SlidePilot/"
    with ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) > 50000 or sum(e.file_size for e in entries) > 2 * 1024**3:
            raise ValueError("Base portable exceeds extraction limits")
        names, seen = {}, set()
        for entry in entries:
            if entry.orig_filename != entry.filename:
                raise ValueError("Truncated portable archive path")
            path = safe_zip_path(entry.filename)
            key = path.as_posix().casefold()
            mode = entry.external_attr >> 16
            if (key in seen or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or
                    entry.flag_bits & 1 or entry.file_size > 512 * 1024**2):
                raise ValueError("Duplicate, linked, encrypted or oversized portable entry: " + entry.filename)
            seen.add(key)
            if not entry.filename.startswith(prefix):
                raise ValueError("Expected a single SlidePilot/ archive root")
            if not entry.is_dir():
                names[entry.filename[len(prefix):]] = entry
        manifest_entry = names.get("manifest.sha256")
        if manifest_entry is None or manifest_entry.file_size > 4 * 1024**2:
            raise ValueError("Base portable requires manifest.sha256")
        manifest, manifest_seen = {}, set()
        for line in bundle.read(manifest_entry).decode("utf-8-sig").splitlines():
            match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", line)
            if match is None:
                raise ValueError("Malformed base portable SHA-256 manifest")
            expected, name = match.groups()
            safe_zip_path(name)
            if name.casefold() in manifest_seen or name.endswith("/"):
                raise ValueError("Duplicate or non-file manifest entry: " + name)
            manifest_seen.add(name.casefold())
            manifest[name] = expected.lower()
        if set(manifest) != set(names) - {"manifest.sha256"}:
            raise ValueError("Base portable manifest does not match its file inventory")

        def verified_bytes(name, maximum=4 * 1024**2):
            if name not in names or names[name].file_size > maximum:
                raise ValueError("Missing or oversized base dependency metadata: " + name)
            data = bundle.read(names[name])
            if hashlib.sha256(data).hexdigest() != manifest[name]:
                raise ValueError("Base portable SHA-256 mismatch: " + name)
            return data

        if verified_bytes("Chatbox/package-lock.json") != lockfile.read_bytes():
            raise ValueError("Base portable package-lock.json differs from the current pinned lock")
        expected_electron = re.search(r"/v([^/]+)/", ARCHIVES["Electron"][0]).group(1)
        if verified_bytes("Electron/version").decode("ascii").strip() != expected_electron:
            raise ValueError("Base portable Electron version differs from the pinned runtime")
        required = {"Runtime/python.exe", "Runtime/python312.dll", "Runtime/python312.zip", "Runtime/python312._pth",
                    "Electron/electron.exe", "Chatbox/node_modules/.package-lock.json"}
        if not required.issubset(names):
            raise ValueError("Base portable is missing required runtime dependencies")
        for name, version in PY_PACKAGES.items():
            metadata = "Runtime/Lib/site-packages/" + name + "-" + version + ".dist-info/METADATA"
            data = verified_bytes(metadata).decode("utf-8")
            if not re.search(r"^Version: " + re.escape(version) + r"\s*$", data, re.M):
                raise ValueError("Base portable Python package differs from the pinned version: " + name)
        restored = 0
        for name, entry in names.items():
            if not name.startswith(("Runtime/", "Electron/", "Chatbox/node_modules/")):
                continue
            target = out.joinpath(*PurePosixPath(name).parts)
            if not target.resolve().is_relative_to(out):
                raise ValueError("Dependency output leaves the fresh staging directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.resolve().is_relative_to(out):
                raise ValueError("Dependency output leaves the fresh staging directory")
            value = hashlib.sha256()
            created = False
            try:
                with bundle.open(entry) as source, target.open("xb") as destination:
                    created = True
                    while block := source.read(1024 * 1024):
                        value.update(block)
                        destination.write(block)
                if value.hexdigest() != manifest[name]:
                    raise ValueError("Base portable SHA-256 mismatch: " + name)
            except BaseException:
                # Only this newly-created file belongs to the failed operation.
                if created and target.is_file() and not target.is_symlink():
                    target.unlink()
                raise
            restored += 1
    (out / "dependency-source.json").write_text(json.dumps({"archive":archive.name,
        "sha256":digest(archive), "verifiedFiles":restored}, indent=2) + "\n", encoding="utf-8")
    return restored


def build_native(out, openxml):
    windows = Path(os.environ["WINDIR"])
    csc = windows / "Microsoft.NET/Framework/v4.0.30319/csc.exe"
    office = next((windows / "assembly/GAC_MSIL/office").glob("*/office.dll"))
    ext = next((windows / "assembly/GAC/Extensibility").glob("*/Extensibility.dll"))
    common = [csc, "/nologo", "/optimize+", "/codepage:65001", "/platform:anycpu"]
    run(*common, "/target:library", "/reference:Microsoft.CSharp.dll", "/reference:System.Windows.Forms.dll",
        "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll", f"/link:{office}", f"/link:{ext}",
        f"/out:{out / 'SlidePilot.PowerPoint.dll'}", ROOT/"native/Connect.cs", ROOT/"native/Live.cs", ROOT/"native/OfficeGraph.cs", ROOT/"native/HostHealth.cs", ROOT/"native/AiPane.cs")
    run(*common, "/target:exe", f"/out:{out / 'SlidePilot.Manager.exe'}", ROOT/"native/Manager.cs")
    run(*common, "/target:winexe", "/main:SlidePilot.SetupProgram", "/reference:System.Windows.Forms.dll",
        "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll", f"/win32manifest:{ROOT / 'native/Setup.manifest'}",
        f"/out:{out / 'SlidePilot.Setup.exe'}", ROOT/"native/Manager.cs", ROOT/"native/Setup.cs", ROOT/"native/HostHealth.cs")
    file_copy(openxml, out / "DocumentFormat.OpenXml.dll")
    windows_base = csc.parent / "WPF/WindowsBase.dll"
    run(*common, "/target:exe", f"/reference:{windows_base}", f"/reference:{openxml}",
        f"/out:{out / 'SlidePilot.Validate.exe'}", ROOT/"tests/validate.cs")


def chatbox_files(out, modules, reused=False):
    src = ROOT / ".build/chatbox"
    dest = out / "Chatbox"
    if not (src / "release/app/dist/renderer/index.html").is_file():
        raise ValueError("Compile the pinned Chatbox checkout using prepare_chatbox.py first.")
    for filename in ("package.json", "package-lock.json", "bootstrap.cjs", "provider-diagnostics.cjs", "workspace-main.cjs", "window-mode-main.cjs",
                     "settings-entry.cjs", "settings-preload.cjs", "settings.html", "settings.css", "settings.js"):
        file_copy(ROOT / "chatbox" / filename, dest / filename)
    if reused:
        if not (dest / "node_modules/.package-lock.json").is_file():
            raise ValueError("Verified base portable modules have not been restored")
    elif modules:
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


def package_files(out):
    """Inventory the immutable build stage without following links or junctions."""
    out = Path(out)
    if out.is_symlink() or out.is_junction():
        raise ValueError("Linked portable stage is not supported")
    result, seen = [], set()
    def fail(error):
        raise error
    for parent, directories, files in os.walk(out, followlinks=False, onerror=fail):
        for name in directories + files:
            path = Path(parent) / name
            relative = safe_zip_path(path.relative_to(out).as_posix()).as_posix()
            info = path.lstat()
            if (path.is_symlink() or path.is_junction() or
                    getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError("Linked portable entry: " + relative)
            if relative.casefold() in seen:
                raise ValueError("Duplicate portable path: " + relative)
            seen.add(relative.casefold())
            if path.is_file():
                if relative.casefold() == "manifest.sha256":
                    if relative != "manifest.sha256":
                        raise ValueError("Invalid manifest filename casing")
                    continue
                result.append(path)
            elif not path.is_dir():
                raise ValueError("Unsupported portable entry: " + relative)
    return sorted(result)


def write_manifest(out):
    files = package_files(out)
    lines = [digest(p) + "  " + p.relative_to(out).as_posix() for p in files]
    (out / "manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return files


def archive_project(out):
    files = write_manifest(out)
    archive = DIST / f"SlidePilot-{VERSION}-portable-win-x64.zip"
    temporary = out.parent / "portable.zip"
    with ZipFile(temporary, "w", ZIP_DEFLATED, compresslevel=6) as z:
        for p in files + [out / "manifest.sha256"]:
            z.write(p, "SlidePilot/" + p.relative_to(out).as_posix())
    os.replace(temporary, archive)
    return archive


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=ROOT / ".build/downloads")
    p.add_argument("--python-packages", type=Path, help="Optional verified wheel installation for offline builds")
    p.add_argument("--node-modules", type=Path, help="Optional production modules matching package-lock.json")
    p.add_argument("--base-portable", type=Path, help="Reuse manifest-verified dependencies from an existing portable ZIP; fully offline")
    p.add_argument("--openxml", type=Path, required=True, help="Open XML SDK 2.8.1 .NET Framework assembly")
    args = p.parse_args()
    if args.base_portable and (args.python_packages or args.node_modules):
        p.error("--base-portable cannot be combined with --python-packages or --node-modules")
    DIST.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=DIST) as temp:
        out = Path(temp) / "SlidePilot"
        out.mkdir()
        if args.base_portable:
            restore_base_dependencies(args.base_portable, out)
        build_native(out, args.openxml.resolve())
        if not args.base_portable:
            runtime_files(out, args)
        chatbox_files(out, args.node_modules, reused=bool(args.base_portable))
        for directory in ("engine", "assets", "examples", "licenses"):
            shutil.copytree(ROOT / directory, out / directory, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for filename in ("qwen_live.py", "workspace_benchmark.py", "fixtures.py"):
            file_copy(ROOT / "tests" / filename, out / "tests" / filename)
        for filename in ("Setup.cmd", "Enable.cmd", "Disable.cmd", "Status.cmd", "Test-Qwen.cmd", "LICENSE", "README.md", "THIRD-PARTY.md", "TESTING.md"):
            file_copy(ROOT / filename, out / filename)
        python_version = tuple(int(n) for n in re.search(r"/ftp/python/([^/]+)/", ARCHIVES["Runtime"][0]).group(1).split("."))
        run(out / "Runtime/python.exe", "-B", "-c",
            "import sys; assert sys.version_info[:3] == " + repr(python_version) + "; import PIL.Image, pypdfium2, server")
        write_manifest(out)
        run(out / "SlidePilot.Manager.exe", "check-package")
        archive = archive_project(out)
    print(f"{archive.name}  {archive.stat().st_size} bytes  {digest(archive)}")


if __name__ == "__main__":
    main()
