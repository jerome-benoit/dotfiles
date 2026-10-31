import fcntl
import json
import os
from pathlib import Path
import shutil
import select
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
import zipfile


WORKSPACE = sys.argv.pop(1)
UPSTREAM = sys.argv.pop(1)
RUNNER = """
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('workspace', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if len(sys.argv) > 5 and sys.argv[5] == "run":
    module.REMOTE = sys.argv[4]
    module.run_workspace(sys.argv[2], sys.argv[3], sys.argv[6:] or ["--build", "--no-browser"])
elif len(sys.argv) > 5:
    with module.workspace_lock(pathlib.Path(sys.argv[2]).parent) as (_, lock):
        module.refresh_runtime(pathlib.Path(sys.argv[2]), sys.argv[3], lock.fileno(), sys.argv[6:])
else:
    print(module.prepare_workspace(sys.argv[2], sys.argv[3], sys.argv[4]))
"""

GATE = """
import os, signal, socket
listener = socket.socket(socket.AF_UNIX)
listener.bind(os.environ["GATE_SOCKET"])
listener.listen(1)
with open(os.environ["GATE_READY"], "w") as ready:
    ready.write(str(os.getpid()))
with listener.accept()[0] as peer:
    signal.signal(signal.SIGTERM, lambda *_: peer.sendall(b"t"))
    peer.sendall(b"r")
    peer.recv(1)
"""


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "remote"
        self.repo.mkdir()
        self.env = dict(os.environ, HOME=str(self.base / "home"),
                        XDG_CONFIG_HOME=str(self.base / "config"),
                        NIX_STORE_DIR=str(self.base / "nix-store"),
                        NIX_STATE_DIR=str(self.base / "nix-state"),
                        NIX_LOG_DIR=str(self.base / "nix-log"),
                        NIX_CONF_DIR=str(self.base / "nix-conf"),
                        NIX_REMOTE="local",
                        NIX_CONFIG="experimental-features = nix-command flakes\nrequire-sigs = false\n")
        self.git("init", "--quiet")
        (self.repo / ".gitignore").write_text(".venv/\nengine/\nbuild/\nstrata-*.json\n")
        (self.repo / "code.py").write_text("old source\n")
        (self.repo / "removed.py").write_text("obsolete source\n")
        self.old = self.commit()
        (self.repo / "code.py").write_text("new source\n")
        (self.repo / "removed.py").unlink()
        self.new = self.commit()
        self.state = self.base / "data with spaces"

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], env=self.env, stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

    def commit(self):
        self.git("add", "--all")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--quiet", "-m", "source revision")
        return self.git("rev-parse", "HEAD")

    def command(self, revision):
        return [sys.executable, "-c", RUNNER, WORKSPACE, str(self.state), revision, str(self.repo)]

    def prepare(self, revision):
        result = subprocess.run(self.command(revision), env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip())

    def test_initial_bootstrap_failure_never_certifies_runtime(self):
        root = self.prepare(self.old)
        marker = root / ".git/strata-runtime-revision"
        self.assertFalse(marker.exists())
        setup = root / "setup.sh"
        setup.write_text(f'''#!{shutil.which("sh")}
cd "$(dirname "$0")" || exit 8
attempts=0
test ! -f bootstrap-attempts || read -r attempts < bootstrap-attempts
printf '%s\\n' "$((attempts + 1))" > bootstrap-attempts
exit 9
''')
        setup.chmod(0o700)
        for attempt in (1, 2):
            result = subprocess.run(self.command(self.old) + ["run"], env=self.env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 9)
            self.assertFalse(marker.exists())
            self.assertEqual((root / "bootstrap-attempts").read_text().strip(), str(attempt))

    def test_user_state_survives_update_gc_and_offline_rollback(self):
        root = self.prepare(self.old)
        expected = {}
        for model in ("first", "second"):
            expected[f"strata-{model}.json"] = json.dumps({
                "exe": str(root / "engine/strata"), "cwd": str(root),
                "args": ["--native", str(self.state / "Strata-data" / model)],
                "custom": {"api_key": f"{model}-test-key"},
            })
            expected[f"strata-{model}.shared-settings.json"] = json.dumps({"temperature": 0.7})
        expected["engine/strata"] = "existing engine"
        expected[".venv/user-cache"] = "existing virtual environment"
        expected["build/user-cache"] = "existing build cache"
        for name, text in expected.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.assertEqual(self.prepare(self.new), root)
        self.assertEqual((root / "code.py").read_text(), "new source\n")
        self.assertFalse((root / "removed.py").exists())
        for name, text in expected.items():
            self.assertEqual((root / name).read_text(), text, name)
        (self.repo / "code.py").write_text("third source\n")
        third = self.commit()
        self.assertEqual(self.prepare(third), root)
        for args in (("reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all"),
                     ("gc", "--prune=now")):
            subprocess.run(["git", "-C", str(root), *args], env=self.env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.repo.rename(self.base / "remote-offline")
        self.assertEqual(self.prepare(self.new), root)
        self.assertEqual((root / "code.py").read_text(), "new source\n")
        self.assertEqual(self.prepare(self.old), root)
        self.assertEqual((root / "removed.py").read_text(), "obsolete source\n")
        for name, text in expected.items():
            self.assertEqual((root / name).read_text(), text, name)

    def test_concurrent_initialization_and_conflicting_user_edit(self):
        processes = [subprocess.Popen(self.command(self.old), env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(2)]
        roots = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr)
            roots.append(Path(stdout.strip()))
        self.assertEqual(roots[0], roots[1])
        self.assertEqual((roots[0] / "code.py").read_text(), "old source\n")
        (roots[0] / "code.py").write_text("user edit\n")
        result = subprocess.run(self.command(self.new), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((roots[0] / "code.py").read_text(), "user edit\n")
        self.assertTrue((roots[0] / "removed.py").exists())

    def test_existing_source_symlink_without_git_preserves_user_state(self):
        root = self.prepare(self.old)
        legacy = root.with_name(f"source-{self.old}")
        root.rename(legacy)
        source = self.state / "source"
        source.symlink_to(legacy.name, target_is_directory=True)
        config = legacy / "strata-user.json"
        expected = '{"custom": "preserve"}'
        config.write_text(expected)
        subprocess.run(["git", "-C", str(legacy), "check-ignore", "--quiet", config.name],
                       env=self.env, check=True)
        shutil.rmtree(legacy / ".git")
        self.assertFalse((legacy / ".git").exists())
        (self.repo / "code.py").write_text("third source\n")
        revision = self.commit()
        self.assertEqual(self.prepare(revision), legacy)
        self.assertTrue(source.is_symlink())
        self.assertEqual(os.readlink(source), legacy.name)
        self.assertTrue((legacy / ".git").is_dir())
        self.assertEqual((legacy / "code.py").read_text(), "third source\n")
        self.assertFalse((legacy / "removed.py").exists())
        self.assertEqual(config.read_text(), expected)
        self.repo.rename(self.base / "remote-offline")
        self.assertEqual(self.prepare(self.old), legacy)
        self.assertEqual((legacy / "code.py").read_text(), "old source\n")
        self.assertEqual((legacy / "removed.py").read_text(), "obsolete source\n")
        self.assertEqual(config.read_text(), expected)

    def test_settings_do_not_select_the_workspace(self):
        self.state.mkdir()
        candidate = self.state / f"source-{self.old}"
        subprocess.run(["git", "clone", "--quiet", str(self.repo), str(candidate)],
                       env=self.env, check=True)
        subprocess.run(["git", "-C", str(candidate), "checkout", "--quiet", self.old],
                       env=self.env, check=True)
        config = candidate / "strata-user.json"
        expected = '{"custom": "preserve"}'
        config.write_text(expected)
        settings = Path(self.env["XDG_CONFIG_HOME"]) / "strata/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"installs": [str(candidate)]}))
        root = self.prepare(self.new)
        self.assertEqual(root, self.state / "source")
        self.assertFalse(root.is_symlink())
        self.assertEqual((root / "code.py").read_text(), "new source\n")
        self.assertEqual(config.read_text(), expected)
        self.assertEqual((candidate / "code.py").read_text(), "old source\n")

    def test_broken_source_symlink_reports_repair_without_creating_directory(self):
        self.state.mkdir()
        source = self.state / "source"
        missing = self.state / "missing-source"
        source.symlink_to(missing.name, target_is_directory=True)
        result = subprocess.run(self.command(self.new), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(source.is_symlink())
        self.assertEqual(os.readlink(source), missing.name)
        self.assertFalse(missing.exists())
        self.assertEqual({path.name for path in self.state.iterdir()}, {"source", ".source.lock"})
        self.assertIn(f"Workspace link {source} is broken", result.stderr)
        self.assertIn("restore its target or remove the link and retry", result.stderr)

    def test_uninitialised_tree_outside_revision_pattern_reports_repair(self):
        root = self.prepare(self.old)
        candidate = root.with_name(f"source-{self.old}-custom")
        root.rename(candidate)
        source = self.state / "source"
        source.symlink_to(candidate.name, target_is_directory=True)
        config = candidate / "strata-user.json"
        expected = '{"custom": "preserve"}'
        config.write_text(expected)
        shutil.rmtree(candidate / ".git")
        result = subprocess.run(self.command(self.new), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(source.is_symlink())
        self.assertEqual(os.readlink(source), candidate.name)
        self.assertEqual((candidate / "code.py").read_text(), "old source\n")
        self.assertEqual((candidate / "removed.py").read_text(), "obsolete source\n")
        self.assertEqual(config.read_text(), expected)
        self.assertIn(f"Cannot initialise workspace {candidate}", result.stderr)
        self.assertIn("move it aside and retry", result.stderr)

    def test_ignored_runtime_collision_is_not_overwritten(self):
        root = self.prepare(self.old)
        cache = root / "build/user-cache"
        cache.parent.mkdir()
        cache.write_text("runtime state")
        (self.repo / "build").mkdir()
        (self.repo / "build/user-cache").write_text("new upstream source")
        self.git("add", "--force", "build/user-cache")
        revision = self.commit()
        result = subprocess.run(self.command(revision), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cache.read_text(), "runtime state")
        self.assertEqual((root / "code.py").read_text(), "old source\n")

    def test_existing_detached_revision_survives_gc_and_offline_rollback(self):
        root = self.prepare(self.old)
        subprocess.run(["git", "-C", str(root), "update-ref", "-d",
                        f"refs/strata/revisions/{self.old}"], env=self.env, check=True)
        self.prepare(self.new)
        for args in (("reflog", "expire", "--expire=now", "--expire-unreachable=now", "--all"),
                     ("gc", "--prune=now")):
            subprocess.run(["git", "-C", str(root), *args], env=self.env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.repo.rename(self.base / "remote-offline")
        self.assertEqual(self.prepare(self.old), root)
        self.assertEqual((root / "code.py").read_text(), "old source\n")

    def make_runtime_source(self, root):
        shutil.copyfile(Path(UPSTREAM) / "setup.py", root / "setup.py")
        shutil.copytree(Path(UPSTREAM) / "strata_control", root / "strata_control")
        # Use a real local distribution, without fetching the pinned production wheels.
        (root / "requirements.txt").write_text("pip\n")

    def make_runtime_model(self, root, name="fixture"):
        tokenizer = root / "tokenizer"
        tokenizer.mkdir(exist_ok=True)
        for child in ("vocab.json", "merges.txt", "token_type.json"):
            (tokenizer / child).write_text("{}")
        engine = root / "engine"
        engine.mkdir(exist_ok=True)
        (engine / "strata").write_text("B")
        (engine / "strata").chmod(0o700)
        (engine / "BUILD.json").write_text(json.dumps({"version": "0.1.46", "source": "prebuilt"}))
        config = {
            "exe": str(engine / "strata"), "args": [], "backend": "cuda",
            "tokenizer": str(tokenizer), "custom": {"preserve": True},
        }
        (root / f"strata-{name}.json").write_text(json.dumps(config))
        return config

    def make_updater_workspace(self):
        root = self.prepare(self.old)
        self.make_runtime_source(root)
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], env=self.env, check=True)
        setup = root / "setup.sh"
        setup.write_text(f'''#!{shutil.which("sh")}
cd "$(dirname "$0")" || exit 8
exec "{sys.executable}" - "$@" <<'PY'
import sys
sys.path.append(r"{UPSTREAM}")
from pathlib import Path
import setup
attempts = setup.ROOT / "update-attempts"
attempts.write_text(str(int(attempts.read_text()) + 1) if attempts.exists() else "1")
setup.pip_install = lambda *args, **kwargs: None
def install(url):
    candidate = setup.ROOT / "engine/default" if url == setup.PREBUILT_URL else Path(url)
    if (candidate / "strata").exists():
        setup.install_unpacked(candidate, setup.engine_dir())
setup.update_installed_engine = install
sys.exit(setup.main())
PY
''')
        setup.chmod(0o700)
        self.make_runtime_model(root)
        for name, version in ((".previous", "A"), ("default", "C"), ("custom", "D")):
            folder = root / "engine" / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "strata").write_text(version)
            (folder / "strata").chmod(0o700)
            (folder / "BUILD.json").write_text(json.dumps({"version": "0.1.46", "source": "prebuilt"}))
        return root

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_refresh_respects_engine_build_and_custom_source(self):
        state = self.state
        for build, flag_value in ((True, False), (False, False), (False, True)):
            with self.subTest(build=build, flag_value=flag_value):
                self.state = state / f"{build}-{flag_value}"
                root = self.make_updater_workspace()
                source = str(root / "engine/custom")
                if flag_value:
                    (root / "engine/custom").rename(root / "--check")
                    source = "--check"
                args = ["--up", "--check", f"--prebuilt={source}"]
                if build:
                    args.append("--buil")
                result = subprocess.run(self.command(self.new) + ["run", *args], env=self.env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "engine/strata").read_text(), "B" if build else "D")
                self.assertEqual((root / "engine/.previous/strata").read_text(), "A" if build else "B")
                self.assertEqual((root / "engine/default/strata").read_text(), "C")
                self.assertEqual((root / ".git/strata-runtime-revision").read_text().strip(), self.new)
                if not build:
                    candidate = root / source
                    (candidate / "strata").write_text("E")
                    (candidate / "strata").chmod(0o700)
                    (candidate / "BUILD.json").write_text(json.dumps({"version": "0.1.46", "source": "prebuilt"}))
                    result = subprocess.run(self.command(self.new) + ["run", *args], env=self.env,
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((root / "engine/strata").read_text(), "E")
                    self.assertEqual((root / "engine/.previous/strata").read_text(), "D")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_help_preserves_engine_and_pending_refresh(self):
        state = self.state
        for flag in ("-h", "--help", "--hel"):
            with self.subTest(flag=flag):
                self.state = state / flag.lstrip("-")
                root = self.make_updater_workspace()
                (root / ".git/strata-runtime-revision").write_text(self.old)
                config = (root / "strata-fixture.json").read_bytes()
                result = subprocess.run(self.command(self.new) + ["run", flag], env=self.env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "engine/strata").read_text(), "B")
                self.assertEqual((root / "engine/.previous/strata").read_text(), "A")
                self.assertEqual((root / "engine/default/strata").read_text(), "C")
                self.assertEqual((root / "strata-fixture.json").read_bytes(), config)
                self.assertEqual((root / ".git/strata-runtime-revision").read_text().strip(), self.old)

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux bootstrap; Darwin dispatches to Metal")
    def test_engine_rollback_precedes_pending_runtime_refresh(self):
        state = self.state
        for flag in ("--rollback-engine", "--rollback-eng"):
            with self.subTest(flag=flag):
                self.state = state / flag.removeprefix("--")
                root = self.prepare(self.old)
                shutil.copyfile(Path(UPSTREAM) / "setup.py", root / "setup.py")
                setup = root / "setup.sh"
                setup.write_text(f'''#!{shutil.which("sh")}
cd "$(dirname "$0")" || exit 8
exec "{sys.executable}" - "$@" <<'PY'
import sys
sys.path.append(r"{UPSTREAM}")
import setup
import sys
if sys.argv[1:] == ["--update"]:
    setup.install_unpacked(setup.ROOT / "engine/incoming", setup.engine_dir())
else:
    sys.exit(setup.main())
PY
''')
                setup.chmod(0o700)
                engine = root / "engine"
                previous = engine / ".previous"
                incoming = engine / "incoming"
                for folder, version in ((engine, "B"), (previous, "A"), (incoming, "C")):
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / "strata").write_text(version)
                    (folder / "BUILD.json").write_text(json.dumps({"version": version}))
                marker = root / ".git/strata-runtime-revision"
                marker.write_text(self.old)
                command = self.command(self.new) + ["run", flag]
                for current, saved in (("A", "B"), ("B", "A")):
                    result = subprocess.run(command, env=self.env, capture_output=True,
                                            text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((root / "code.py").read_text(), "new source\n")
                    for folder, version in ((engine, current), (previous, saved), (incoming, "C")):
                        self.assertEqual((folder / "strata").read_text(), version)
                        self.assertEqual(json.loads((folder / "BUILD.json").read_text())["version"],
                                         version)
                    self.assertEqual(marker.read_text().strip(), self.old)

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_zero_exit_partial_update_retries_same_revision_and_reuses_valid_runtime(self):
        root = self.make_updater_workspace()
        marker = root / ".git/strata-runtime-revision"
        (root / "engine/BUILD.json").write_text(json.dumps({"version": "0.1.12", "source": "prebuilt"}))
        # Missing update source leaves the installed engine unchanged; upstream still returns zero.
        command = self.command(self.new) + ["run", "--prebuilt=missing"]
        config = (root / "strata-fixture.json").read_bytes()
        for attempt in (1, 2):
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
            self.assertEqual((root / "update-attempts").read_text(), str(attempt))
            self.assertEqual((root / "strata-fixture.json").read_bytes(), config)
        valid = self.command(self.new) + ["run", "--update", "--prebuilt=" + str(root / "engine/custom")]
        result = subprocess.run(valid, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text().strip(), self.new)
        # A normal refresh reuses a locally valid certificate without running the updater.
        refresh = [sys.executable, "-c", RUNNER, WORKSPACE, str(root), self.new, "", "refresh"]
        result = subprocess.run(refresh, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((root / "update-attempts").read_text(), "3")
        # Explicit --update still forces the actual upstream update even at the same revision.
        result = subprocess.run(valid, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((root / "update-attempts").read_text(), "4")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_runtime_validation_rejects_missing_components_and_false_existing_certificate(self):
        root = self.make_updater_workspace()
        marker = root / ".git/strata-runtime-revision"
        refresh = [sys.executable, "-c", RUNNER, WORKSPACE, str(root), self.new, "", "refresh", "--build"]
        for missing in (root / "engine/strata", root / "tokenizer/vocab.json"):
            with self.subTest(missing=missing):
                saved = missing.read_bytes()
                mode = missing.stat().st_mode
                missing.unlink()
                marker.write_text(self.new)
                result = subprocess.run(refresh, env=self.env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(missing), result.stderr)
                self.assertFalse(marker.exists())
                missing.write_bytes(saved)
                missing.chmod(mode)
        (root / "strata-fixture.json").unlink()
        result = subprocess.run(refresh, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run strata --setup", result.stderr)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_every_installed_model_engine_must_satisfy_runtime_contract(self):
        root = self.make_updater_workspace()
        other = root / "engine/other"
        other.mkdir()
        (other / "strata").write_text("old second engine")
        (other / "strata").chmod(0o700)
        (other / "BUILD.json").write_text(json.dumps({"version": "0.1.12", "source": "prebuilt"}))
        config = json.loads((root / "strata-fixture.json").read_text())
        config["exe"] = str(other / "strata")
        (root / "strata-second.json").write_text(json.dumps(config))
        result = subprocess.run(self.command(self.new) + ["run", "--update", "--build"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(other / "strata"), result.stderr)
        self.assertFalse((root / ".git/strata-runtime-revision").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_component_manifest_version_does_not_require_optional_build_record(self):
        root = self.make_updater_workspace()
        engine = root / "engine"
        executable = engine / "strata"
        # Exercise metadata precedence with a real native executable, never model inference.
        shutil.copyfile(shutil.which("true"), executable)
        executable.chmod(0o700)
        (engine / "BUILD.json").unlink()
        payload = executable.read_bytes()
        import hashlib
        manifest = {
            "schema_version": 1,
            "id": "strata-engine",
            "version": "0.1.46",
            "platform": "linux-x86_64",
            "backend": "cpu",
            "entrypoint": "strata",
            "files": [{"path": "strata", "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}],
        }
        path = engine / "engine-component.json"
        path.write_text(json.dumps(manifest))
        command = [str(root / ".venv/bin/python"), WORKSPACE, "--runtime-status", str(root)]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest["version"] = "0.1.12"
        path.write_text(json.dumps(manifest))
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_failed_explicit_update_invalidates_existing_same_revision_certificate(self):
        root = self.make_updater_workspace()
        self.prepare(self.new)
        marker = root / ".git/strata-runtime-revision"
        marker.write_text(self.new)
        setup = root / "setup.sh"
        setup.write_text(f"#!{shutil.which('sh')}\nexit 9\n")
        result = subprocess.run([sys.executable, WORKSPACE, str(self.state), self.new, "--update"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 9)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_runtime_validation_rejects_missing_and_stale_python_distribution(self):
        root = self.make_updater_workspace()
        command = self.command(self.new) + ["run", "--update", "--build"]
        marker = root / ".git/strata-runtime-revision"
        for requirement, diagnostic in (("strata-missing-runtime==1", "Python package missing"),
                                        ("pip==0", "requires ==0")):
            (root / "requirements.txt").write_text(requirement + "\n")
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(diagnostic, result.stderr)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_runtime_validation_rejects_failed_local_build_stamp(self):
        root = self.make_updater_workspace()
        shutil.copyfile(Path(UPSTREAM) / "CMakeLists.txt", root / "CMakeLists.txt")
        code = (
            "import setup; from pathlib import Path; import json; "
            "p = Path('engine/BUILD.json'); "
            "p.write_text(json.dumps({'source': 'local', 'version': setup.source_version(), "
            "'src': setup.source_hash(setup.ENGINE_SOURCES), 'vision': 'none'}))"
        )
        subprocess.run([str(root / ".venv/bin/python"), "-c", code], cwd=root,
                       env=self.env, check=True)
        # BUILD.json claims the new source; the binary still carries the older compiled-in version.
        (root / "engine/strata").write_text("engine=0.1.46\n")
        result = subprocess.run(self.command(self.new) + ["run", "--update", "--build"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("compiled engine does not match this source", result.stderr)
        self.assertFalse((root / ".git/strata-runtime-revision").exists())


    def gated_process(self, command):
        self.env.pop("STRATA_EXECV", None)
        ready = self.base / "ready"
        os.mkfifo(ready)
        descriptor = os.open(ready, os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, descriptor)
        self.env["GATE_READY"] = str(ready)
        self.env["GATE_SOCKET"] = str(self.base / "gate.sock")
        process = subprocess.Popen(command, env=self.env, start_new_session=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def cleanup():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=10)

        self.addCleanup(cleanup)
        readable, _, _ = select.select([descriptor], [], [], 120)
        if not readable:
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
            self.fail(f"Child did not reach its gate: {stdout}\n{stderr}")
        pid = int(os.read(descriptor, 64))
        peer = socket.socket(socket.AF_UNIX)
        self.addCleanup(peer.close)
        peer.settimeout(10)
        peer.connect(self.env["GATE_SOCKET"])
        self.assertEqual(peer.recv(1), b"r")
        return process, pid, peer

    def assert_workspace_locked(self):
        with (self.state / ".source.lock").open("a") as lock:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def assert_workspace_unlocked(self):
        probe = "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX)"
        subprocess.run([sys.executable, "-c", probe, str(self.state / ".source.lock")],
                       env=self.env, check=True, timeout=10)

    def test_updater_keeps_lock_after_helper_is_killed(self):
        root = self.prepare(self.old)
        self.make_runtime_model(root)
        gate = self.base / "updater.py"
        gate.write_text(GATE)
        (root / "setup.sh").write_text(f'exec "{sys.executable}" "{gate}"\n')
        marker = root / ".git/strata-runtime-revision"
        command = self.command(self.new) + ["run"]
        process, child_pid, peer = self.gated_process(command)
        self.assertNotEqual(child_pid, process.pid)
        self.assert_workspace_locked()
        process.kill()
        process.wait(timeout=10)
        self.assert_workspace_locked()
        self.assertFalse(marker.exists())
        peer.sendall(b"q")
        peer.close()
        self.assert_workspace_unlocked()

    def make_venv_without_pip(self, root):
        venv = root / ".venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], env=self.env, check=True)
        python = venv / "bin/python"
        for path in venv.glob("lib/python*/site-packages/pip*"):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        self.assertTrue(os.access(python, os.X_OK))
        probe = subprocess.run([str(python), "-m", "pip", "--version"],
                               env=self.env, capture_output=True)
        self.assertNotEqual(probe.returncode, 0)
        return venv

    @unittest.skipUnless(sys.platform == "linux", "Nix interpreter restoration on Linux")
    def test_collected_interpreter_restores_sdk_without_recreating_venv(self):
        root = self.prepare(self.new)
        staged = self.base / "python-sdk"
        (staged / "bin").mkdir(parents=True)
        executable = f"python{sys.version_info.major}.{sys.version_info.minor}"
        shutil.copy2(sys.executable, staged / "bin" / executable)

        def run(*command):
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

        store = run("nix-store", "--add", str(staged))
        venv = root / ".venv"
        run(f"{store}/bin/{executable}", "-m", "venv", "--symlinks", str(venv))
        python = venv / "bin/python"
        wheel = self.base / "sdk_probe-1.0-py3-none-any.whl"
        files = {
            "sdk_probe/__init__.py": (
                "from importlib.resources import files\n"
                "def main():\n"
                "    values = files('sdk_probe').joinpath('runtime/data').read_text().split()\n"
                "    print(sum(int(value) ** 2 for value in values))\n"
            ),
            "sdk_probe/runtime/data": "3 5 7\n",
            "sdk_probe-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: sdk-probe\nVersion: 1.0\n",
            "sdk_probe-1.0.dist-info/WHEEL": (
                "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            ),
            "sdk_probe-1.0.dist-info/entry_points.txt": "[console_scripts]\nsdk-probe = sdk_probe:main\n",
        }
        files["sdk_probe-1.0.dist-info/RECORD"] = "".join(f"{name},,\n" for name in files)
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        run(str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel))
        probe = venv / "bin/sdk-probe"
        self.assertEqual(run(str(probe)), "83")
        purelib = Path(run(str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"))
        library = purelib / "sdk_probe/runtime"
        expected = {
            "engine/BUILD.json": json.dumps({"backend": "hip", "lib_dirs": [str(library)]}),
            "strata-first.json": json.dumps({"api_key": "first-key", "lib_dirs": [str(library)]}),
            "strata-second.json": json.dumps({"api_key": "second-key", "custom": {"preserve": True}}),
            "strata-first.shared-settings.json": '{"temperature": 0.7}',
        }
        for name, content in expected.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        setup = root / "setup.sh"
        setup.write_text(f'#!{shutil.which("sh")}\nexec "{probe}"\n')
        setup.chmod(0o700)
        cache = self.base / "binary-cache"
        run("nix", "copy", "--to", f"file://{cache}", store)
        run("nix-store", "--delete", store)
        self.assertFalse(os.access(python, os.X_OK))
        self.env["NIX_CONFIG"] += f"substituters = file://{cache}\n"
        result = subprocess.run(self.command(self.new) + ["run"], env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "83")
        self.assertEqual(run(str(probe)), "83")
        run(str(python), "-m", "pip", "--version")
        for name, content in expected.items():
            self.assertEqual((root / name).read_text(), content)
        protected = subprocess.run(["nix-store", "--delete", store], env=self.env, capture_output=True)
        self.assertNotEqual(protected.returncode, 0)
        self.assertEqual(run(str(probe)), "83")
        (self.state / ".python-root").unlink()
        run("nix-store", "--delete", store)
        empty = self.base / "empty-cache"
        empty.mkdir()
        self.env["NIX_CONFIG"] += f"substituters = file://{empty}\n"
        marker = root / ".git/strata-runtime-revision"
        marker.unlink(missing_ok=True)
        failed = subprocess.run(self.command(self.new) + ["run"], env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual((library / "data").read_text(), "3 5 7\n")
        for name, content in expected.items():
            self.assertEqual((root / name).read_text(), content)

    def test_executable_venv_without_pip_invalidates_runtime_before_update(self):
        root = self.prepare(self.new)
        venv = self.make_venv_without_pip(root)
        config = root / "strata-user.json"
        expected_config = {
            "exe": sys.executable, "args": [], "backend": "hip", "custom": "preserve",
        }
        config.write_text(json.dumps(expected_config))
        marker = root / ".git/strata-runtime-revision"
        marker.write_text(self.new)
        gate = self.base / "updater.py"
        gate.write_text(GATE)
        setup = root / "setup.sh"
        setup.write_text(f'#!{shutil.which("sh")}\nexec "{sys.executable}" "{gate}"\n')
        setup.chmod(0o700)
        process, child_pid, peer = self.gated_process(self.command(self.new) + ["run"])
        self.assertFalse(venv.exists())
        self.assertFalse(marker.exists())
        self.assertNotEqual(child_pid, process.pid)
        self.assertEqual(json.loads(config.read_text()), expected_config)
        self.assert_workspace_locked()
        process.kill()
        process.wait(timeout=10)
        peer.sendall(b"q")
        peer.close()
        self.assert_workspace_unlocked()

    def test_failed_venv_repair_is_retried_across_launcher_invocations(self):
        root = self.prepare(self.new)
        venv = self.make_venv_without_pip(root)
        self.make_runtime_source(root)
        expected_config = self.make_runtime_model(root, "user")
        marker = root / ".git/strata-runtime-revision"
        config = root / "strata-user.json"
        allow_success = self.base / "allow-success"
        setup = root / "setup.sh"
        setup.write_text(f'''#!{shutil.which("sh")}
cd "$(dirname "$0")" || exit 8
if [ "${{1:-}}" = --update ]; then
    "{sys.executable}" -m venv .venv || exit 8
    test -f "{allow_success}" || exit 7
fi
''')
        setup.chmod(0o700)
        command = self.command(self.new) + ["run"]
        for _ in range(2):
            result = subprocess.run(command, env=self.env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
            self.assertTrue(os.access(venv / "bin/python", os.X_OK))
            subprocess.run([str(venv / "bin/python"), "-m", "pip", "--version"],
                           env=self.env, check=True, stdout=subprocess.DEVNULL)
            self.assertEqual(json.loads(config.read_text()), expected_config)
        allow_success.touch()
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text().strip(), self.new)
        self.assertEqual(json.loads(config.read_text()), expected_config)
        allow_success.unlink()
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text().strip(), self.new)

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux bootstrap; Darwin dispatches to Metal")
    def test_upstream_server_exec_keeps_pid_and_lock(self):
        shutil.copytree(UPSTREAM, self.repo, dirs_exist_ok=True)
        for directory, _, _ in os.walk(self.repo):
            Path(directory).chmod(0o700)
        server = self.repo / "serve/server.py"
        server.unlink()
        server.write_text(GATE)
        setup = self.repo / "setup.sh"
        content = setup.read_text()
        setup.unlink()
        setup.write_text(f"#!{shutil.which('sh')}\n" + content.split("\n", 1)[1])
        setup.chmod(0o700)
        revision = self.commit()
        root = self.prepare(revision)
        for name in ("requirements.txt", "requirements-monitor.txt"):
            path = root / name
            path.unlink()
            path.write_text("pip\n")
        config = self.make_runtime_model(root, "process")
        (root / "engine/strata").unlink()
        (root / "engine/strata").symlink_to(sys.executable)
        config.update(backend="hip", model_name="process-fixture")
        (root / "strata-process.json").write_text(json.dumps(config))
        command = self.command(revision) + ["run"]
        process, server_pid, peer = self.gated_process(command)
        self.assertEqual(server_pid, process.pid)
        self.assert_workspace_locked()
        process.terminate()
        self.assertEqual(peer.recv(1), b"t")
        self.assert_workspace_locked()
        process.kill()
        process.wait(timeout=10)
        peer.close()
        self.assert_workspace_unlocked()


unittest.main()
