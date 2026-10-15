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


WORKSPACE = sys.argv.pop(1)
UPSTREAM = sys.argv.pop(1)
RUNNER = """
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('workspace', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if len(sys.argv) > 5 and sys.argv[5] == "run":
    module.REMOTE = sys.argv[4]
    module.run_workspace(sys.argv[2], sys.argv[3], ["--build", "--no-browser"])
elif len(sys.argv) > 5:
    with module.workspace_lock(pathlib.Path(sys.argv[2]).parent) as (_, lock):
        module.refresh_runtime(pathlib.Path(sys.argv[2]), sys.argv[3], lock.fileno())
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
                        XDG_CONFIG_HOME=str(self.base / "config"))
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

    def make_legacy_workspace(self):
        legacy = self.state / f"source-{self.old}"
        subprocess.run(["git", "clone", "--quiet", str(self.repo), str(legacy)],
                       env=self.env, check=True)
        subprocess.run(["git", "-C", str(legacy), "checkout", "--quiet", self.old],
                       env=self.env, check=True)
        shutil.rmtree(legacy / ".git")
        return legacy

    def test_legacy_multi_model_update_and_offline_rollback(self):
        legacy = self.make_legacy_workspace()
        settings = Path(self.env["XDG_CONFIG_HOME"]) / "strata/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"installs": [str(legacy)]}))
        expected = {}
        for model in ("first", "second"):
            expected[f"strata-{model}.json"] = json.dumps({
                "exe": str(legacy / "engine/strata"), "cwd": str(legacy),
                "args": ["--native", str(self.state / "Strata-data" / model)],
                "custom": {"api_key": f"{model}-test-key"},
            })
            expected[f"strata-{model}.shared-settings.json"] = json.dumps({"temperature": 0.7})
        expected["engine/strata"] = "existing engine"
        expected[".venv/user-cache"] = "existing virtual environment"
        expected["build/user-cache"] = "existing build cache"
        for name, text in expected.items():
            path = legacy / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        root = self.prepare(self.new)
        self.assertEqual(root, legacy)
        self.assertEqual((root / "code.py").read_text(), "new source\n")
        self.assertFalse((root / "removed.py").exists())
        for name, text in expected.items():
            self.assertEqual((root / name).read_text(), text, name)
        self.repo.rename(self.base / "remote-offline")
        self.assertEqual(self.prepare(self.old), legacy)
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

    def test_invalid_settings_preserve_existing_workspace(self):
        legacy = self.make_legacy_workspace()
        config = legacy / "strata-user.json"
        config.write_text('{"custom": "preserve"}')
        settings = Path(self.env["XDG_CONFIG_HOME"]) / "strata/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"installs":')
        self.assertEqual(self.prepare(self.new), legacy)
        self.assertEqual(config.read_text(), '{"custom": "preserve"}')

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

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux bootstrap; Darwin dispatches to Metal")
    def test_runtime_update_failure_retries_and_success_uses_upstream(self):
        root = self.base / "runtime"
        shutil.copytree(UPSTREAM, root)
        for directory, _, _ in os.walk(root):
            Path(directory).chmod(0o700)
        (root / ".git").mkdir()
        marker = root / ".git/strata-runtime-revision"
        marker.write_text(self.old)
        setup = root / "setup.sh"
        setup.unlink()
        setup.write_text("#!/bin/sh\nexit 9\n")
        command = [sys.executable, "-c", RUNNER, WORKSPACE, str(root), self.new, "", "refresh"]
        for _ in range(2):
            result = subprocess.run(command, env=self.env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), self.old)
        shutil.copyfile(Path(UPSTREAM) / "setup.sh", setup)
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text().strip(), self.new)
        settings = Path(self.env["XDG_CONFIG_HOME"]) / "strata/settings.json"
        self.assertIn(str(root), json.loads(settings.read_text())["installs"])
        self.assertTrue(os.access(root / ".venv/bin/python", os.X_OK))


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
        readable, _, _ = select.select([descriptor], [], [], 15)
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
        self.assertEqual(marker.read_text().strip(), self.old)
        peer.sendall(b"q")
        peer.close()
        self.assert_workspace_unlocked()

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
        (root / "strata-process.json").write_text(json.dumps({
            "exe": sys.executable, "args": [], "backend": "hip",
            "model_name": "process-fixture",
        }))
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
