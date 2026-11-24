import contextlib
import hashlib
import io
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_portable as build


class OfflinePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = self.root / "lock.json"
        self.lock.write_bytes(b'{"packages":{}}\n')
        self.base = self.root / "base.zip"
        self.out = self.root / "out"
        self.out.mkdir()
        self.files = {
            "Runtime/python.exe": b"python",
            "Runtime/python312.dll": b"runtime",
            "Runtime/python312.zip": b"stdlib",
            "Runtime/python312._pth": b"python312.zip\n.\n../engine\nLib/site-packages\n",
            "Electron/electron.exe": b"electron",
            "Electron/version": b"44.7.0",
            "Chatbox/node_modules/.package-lock.json": b'{"packages":{}}\n',
            "Chatbox/node_modules/example/index.js": b"module.exports = 1",
            "Chatbox/package-lock.json": self.lock.read_bytes(),
            "Chatbox/bootstrap.cjs": b"old bootstrap",
            "Chatbox/dist/renderer/index.html": b"old renderer",
            "SlidePilot.PowerPoint.dll": b"old native",
        }
        for name, version in build.PY_PACKAGES.items():
            self.files[f"Runtime/Lib/site-packages/{name}-{version}.dist-info/METADATA"] = (
                f"Name: {name}\nVersion: {version}\n".encode())

    def archive(self, files=None, manifest=None, extras=()):
        files = self.files if files is None else files
        if manifest is None:
            manifest = "".join(hashlib.sha256(value).hexdigest() + "  " + name + "\n"
                               for name, value in files.items())
        with ZipFile(self.base, "w") as z:
            for name, value in files.items():
                z.writestr("SlidePilot/" + name, value)
            z.writestr("SlidePilot/manifest.sha256", manifest)
            for name, value in extras:
                z.writestr(name, value)

    def restore(self):
        return build.restore_base_dependencies(self.base, self.out, self.lock)

    def test_reuses_only_verified_dependencies(self):
        self.archive()
        count = self.restore()
        expected = {name for name in self.files if name.startswith(("Runtime/", "Electron/", "Chatbox/node_modules/"))}
        self.assertEqual(count, len(expected))
        actual = {p.relative_to(self.out).as_posix() for p in self.out.rglob("*") if p.is_file()}
        self.assertEqual(actual, expected | {"dependency-source.json"})
        self.assertEqual((self.out / "Runtime/python.exe").read_bytes(), b"python")

    def test_tampered_dependency_is_rejected_and_not_left_on_disk(self):
        manifest = "".join(hashlib.sha256(value).hexdigest() + "  " + name + "\n"
                           for name, value in self.files.items())
        self.files["Runtime/python.exe"] = b"changed"
        self.archive(manifest=manifest)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.restore()
        self.assertFalse((self.out / "Runtime/python.exe").exists())

    def test_existing_output_is_never_overwritten_or_removed(self):
        self.archive()
        target = self.out / "Runtime/python.exe"
        target.parent.mkdir()
        target.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            self.restore()
        self.assertEqual(target.read_bytes(), b"existing")

    def test_lock_must_match_exactly(self):
        self.archive()
        self.lock.write_bytes(b'{ "packages": {} }\n')
        with self.assertRaisesRegex(ValueError, "pinned lock"):
            self.restore()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_incomplete_manifest_and_runtime_are_rejected(self):
        self.archive(manifest="0" * 64 + "  Electron/version\n")
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.restore()
        del self.files["Runtime/python.exe"]
        self.archive()
        with self.assertRaisesRegex(ValueError, "missing required"):
            self.restore()

    def test_duplicate_names_and_manifest_entries_are_rejected(self):
        self.archive(extras=[("SlidePilot/runtime/PYTHON.exe", b"other")])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.restore()
        entry = hashlib.sha256(b"python").hexdigest() + "  Runtime/python.exe\n"
        self.archive(manifest=entry + entry)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.restore()

    def test_windows_unsafe_paths_and_symlinks_are_rejected(self):
        for name in ("../outside", "/absolute", "a\\b", "a:b", "a/../b", "a//b", "a/./b",
                     "NUL.txt", "COM\u00b9.exe", "CONIN$", "a. /b", "a/b ", "a\x00b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build.safe_zip_path(name)
        link = ZipInfo("SlidePilot/Runtime/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.archive(extras=[(link, b"../../outside")])
        with self.assertRaisesRegex(ValueError, "linked"):
            self.restore()

    def test_base_mode_builds_current_code_without_network_or_package_install(self):
        self.archive()
        source = self.root / "source"
        chat = source / "chatbox"
        chat.mkdir(parents=True)
        (chat / "package-lock.json").write_bytes(self.lock.read_bytes())
        (chat / "package.json").write_text("{}")
        (chat / "bootstrap.cjs").write_bytes(b"current bootstrap")
        for filename in ("workspace-main.cjs", "window-mode-main.cjs", "settings-entry.cjs", "settings-preload.cjs", "settings.html", "settings.css", "settings.js"):
            (chat / filename).write_text(filename)
        upstream = source / ".build/chatbox"
        (upstream / "release/app/dist/renderer").mkdir(parents=True)
        (upstream / "release/app/dist/renderer/index.html").write_bytes(b"current renderer")
        (upstream / "assets").mkdir()
        (upstream / "LICENSE").write_text("license")
        for directory in ("engine", "assets", "examples", "licenses"):
            (source / directory).mkdir()
        (source / "tests").mkdir()
        for filename in ("qwen_live.py", "workspace_benchmark.py", "fixtures.py"):
            (source / "tests" / filename).write_text(filename)
        for filename in ("Setup.cmd", "Enable.cmd", "Disable.cmd", "Status.cmd", "Test-Qwen.cmd", "LICENSE", "README.md", "THIRD-PARTY.md", "TESTING.md"):
            (source / filename).write_text(filename)

        def native(out, openxml):
            (out / "SlidePilot.PowerPoint.dll").write_bytes(b"current native")

        def finalize(out):
            self.assertEqual((out / "Chatbox/bootstrap.cjs").read_bytes(), b"current bootstrap")
            self.assertTrue((out / "Chatbox/workspace-main.cjs").is_file())
            self.assertTrue((out / "Chatbox/window-mode-main.cjs").is_file())
            self.assertTrue((out / "Chatbox/settings.html").is_file())
            self.assertEqual((out / "Chatbox/dist/renderer/index.html").read_bytes(), b"current renderer")
            self.assertEqual((out / "SlidePilot.PowerPoint.dll").read_bytes(), b"current native")
            self.assertTrue((out / "manifest.sha256").is_file())
            return self.base

        with mock.patch.object(build, "ROOT", source), mock.patch.object(build, "DIST", self.root / "dist"), \
             mock.patch.object(build, "build_native", side_effect=native), \
             mock.patch.object(build, "archive_project", side_effect=finalize), \
             mock.patch.object(build, "runtime_files", side_effect=AssertionError("runtime download attempted")), \
             mock.patch.object(build.urllib.request, "urlretrieve", side_effect=AssertionError("network attempted")), \
             mock.patch.object(build, "run") as run, \
             mock.patch.object(sys, "argv", ["build_portable.py", "--base-portable", str(self.base), "--openxml", "unused.dll"]), \
             contextlib.redirect_stdout(io.StringIO()):
            build.main()
        self.assertEqual(run.call_count, 2)
        self.assertEqual([Path(call.args[0]).name for call in run.call_args_list], ["python.exe", "SlidePilot.Manager.exe"])

    def test_manifest_is_complete_and_repeatable_without_self_hash(self):
        (self.out / "Runtime").mkdir()
        (self.out / "Runtime/python.exe").write_bytes(b"python")
        (self.out / "readme.txt").write_text("readme")
        files = build.write_manifest(self.out)
        manifest = (self.out / "manifest.sha256").read_bytes()
        self.assertEqual({p.relative_to(self.out).as_posix() for p in files}, {"Runtime/python.exe", "readme.txt"})
        self.assertNotIn(b"manifest.sha256", manifest)
        build.write_manifest(self.out)
        self.assertEqual((self.out / "manifest.sha256").read_bytes(), manifest)
        (self.out / "readme.txt").write_text("changed")
        build.write_manifest(self.out)
        self.assertNotEqual((self.out / "manifest.sha256").read_bytes(), manifest)

    def test_archive_manifest_covers_exact_final_payload(self):
        (self.out / "payload.txt").write_bytes(b"new")
        (self.out / "manifest.sha256").write_text("old manifest")
        with mock.patch.object(build, "DIST", self.root):
            archive = build.archive_project(self.out)
        with ZipFile(archive) as z:
            manifest = z.read("SlidePilot/manifest.sha256").decode()
            self.assertEqual(manifest.strip(), hashlib.sha256(b"new").hexdigest() + "  payload.txt")
            self.assertEqual(set(z.namelist()), {"SlidePilot/payload.txt", "SlidePilot/manifest.sha256"})

    def test_build_native_includes_pane_and_both_deployment_executables(self):
        (self.root / "OpenXml.dll").write_bytes(b"SDK placeholder")
        with mock.patch.object(build, "run") as run, \
             mock.patch.dict(build.os.environ, {"WINDIR": str(self.root / "Windows")}), \
             mock.patch.object(Path, "glob", side_effect=[iter([self.root / "office.dll"]), iter([self.root / "Extensibility.dll"])]):
            build.build_native(self.out, self.root / "OpenXml.dll")
        native_args = [str(arg) for arg in run.call_args_list[0].args]
        self.assertIn(str(build.ROOT / "native/AiPane.cs"), native_args)
        self.assertTrue(any("SlidePilot.Manager.exe" in str(a) for a in run.call_args_list[1].args))
        self.assertTrue(any("SlidePilot.Setup.exe" in str(a) for a in run.call_args_list[2].args))


if __name__ == "__main__":
    unittest.main()
