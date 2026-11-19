import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import shutil
import select
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile


WORKSPACE = str(Path(sys.argv.pop(1)).resolve())
UPSTREAM_SOURCE = Path(sys.argv.pop(1)).resolve()
UPSTREAM = str(UPSTREAM_SOURCE / "terminal")
LAUNCHERS = json.loads(Path(sys.argv.pop(1)).read_text())
SOURCE_PATCH = str(Path(sys.argv.pop(1)).resolve())
OLD_UPSTREAM_SOURCE = Path(sys.argv.pop(1)).resolve()
WORKSPACE_LIB = Path(WORKSPACE).parent / "strata-managed"
RUNNER = """
import importlib.util, pathlib, subprocess, sys
spec = importlib.util.spec_from_file_location('workspace', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.TERMINAL_CLI = __import__("os").environ.get("TEST_TERMINAL_CLI", module.TERMINAL_CLI)
try:
    if len(sys.argv) > 5 and sys.argv[5] == "run":
        module.REMOTE = sys.argv[4]
        sys.exit(module.run_workspace(sys.argv[2], sys.argv[3], sys.argv[6:],
                             data_directory=__import__("os").environ.get("TEST_DATA_DIRECTORY"),
                             models_directory=__import__("os").environ.get("TEST_MODELS_DIRECTORY"),
                             source_patch=__import__("os").environ.get("TEST_SOURCE_PATCH", @SOURCE_PATCH@) or None))
    elif len(sys.argv) > 5:
        with module.workspace_lock(pathlib.Path(sys.argv[2]).parent) as (_, lock):
            module.refresh_runtime(pathlib.Path(sys.argv[2]), sys.argv[3], lock.fileno(), sys.argv[6:])
    else:
        print(module.prepare_workspace(sys.argv[2], sys.argv[3], sys.argv[4],
              source_patch=__import__("os").environ.get("TEST_SOURCE_PATCH", @SOURCE_PATCH@) or None) / "terminal")
except subprocess.CalledProcessError as error:
    sys.exit(error.returncode)
except RuntimeError as error:
    sys.exit(str(error))
""".replace("@SOURCE_PATCH@", repr(SOURCE_PATCH))

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

HARDWARE_SETUP = """
card = {"index": 0, "name": "Test GPU", "vram_gb": 48, "arch": "89", "driver": "600.0"}
setup.gpus = lambda: [card]
setup.gpu_info = lambda index: dict(card)
setup.amd_gpus = lambda: []
setup.ram_gb = lambda: 256
setup.cpu_info = lambda: ("Test CPU", True, False)
setup.page_file_gb = lambda: None
setup.pcie_link = lambda index: None
setup.pip_install = lambda *args, **kwargs: None
"""


def setup_wrapper(root):
    """Select the source checkout wrapper or a flat external installation's own wrapper."""
    return root.parent / "setup.sh" if root.name == "terminal" else root / "setup.sh"


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repository = self.base / "remote"
        self.repo = self.repository / "terminal"
        self.repo.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.base / "home"),
                        PYTHONPATH=os.pathsep.join((str(WORKSPACE_LIB), os.environ.get("PYTHONPATH", ""))),
                        XDG_CONFIG_HOME=str(self.base / "config"),
                        XDG_STATE_HOME=str(self.base / "state"),
                        NIX_STORE_DIR=str(self.base / "nix-store"),
                        NIX_STATE_DIR=str(self.base / "nix-state"),
                        NIX_LOG_DIR=str(self.base / "nix-log"),
                        NIX_CONF_DIR=str(self.base / "nix-conf"),
                        NIX_REMOTE="local",
                        GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="pack.threads", GIT_CONFIG_VALUE_0="1",
                        NIX_CONFIG="experimental-features = nix-command flakes\nrequire-sigs = false\n")
        self.git("init", "--quiet")
        self.git("config", "pack.threads", "1")
        (self.repository / ".gitignore").write_text("terminal/.venv/\nterminal/engine/\nterminal/build/\nterminal/strata-*.json\n")
        (self.repo / "code.py").write_text("old source\n")
        shutil.copyfile(Path(UPSTREAM) / "setup.py", self.repo / "setup.py")
        shutil.copytree(Path(UPSTREAM) / "strata_control", self.repo / "strata_control",
                        copy_function=shutil.copyfile)
        shutil.copytree(Path(UPSTREAM) / "strata_cli", self.repo / "strata_cli",
                        copy_function=shutil.copyfile)
        shutil.copytree(Path(UPSTREAM) / "serve", self.repo / "serve",
                        copy_function=shutil.copyfile)
        terminal_tests = self.repo / "tests/terminal"
        terminal_tests.mkdir(parents=True)
        for name in ("test_discovery.py", "test_net_own_folder.py", "test_model_folder_case.py",
                     "test_fix3_0212.py", "test_flow2_022.py"):
            shutil.copyfile(Path(UPSTREAM) / "tests/terminal" / name, terminal_tests / name)
        shutil.copyfile(Path(UPSTREAM) / "strata.py", self.repo / "strata.py")
        shutil.copyfile(UPSTREAM_SOURCE / "setup.sh", self.repository / "setup.sh")
        for directory, _, _ in os.walk(self.repo / "strata_control"):
            Path(directory).chmod(0o700)
        (self.repo / "tools").mkdir()
        shutil.copyfile(Path(UPSTREAM) / "tools/nvfp4_local_pack.py", self.repo / "tools/nvfp4_local_pack.py")
        shutil.copyfile(Path(UPSTREAM) / "tools/iq_pack.py", self.repo / "tools/iq_pack.py")
        shutil.copyfile(Path(UPSTREAM) / "tools/strata_mcp.py", self.repo / "tools/strata_mcp.py")
        shutil.copyfile(Path(UPSTREAM) / "tools/gguf_reader.py", self.repo / "tools/gguf_reader.py")
        for name in ("test_setup_qwen36.py", "test_setup_feed_models.py"):
            shutil.copyfile(Path(UPSTREAM) / "tools" / name, self.repo / "tools" / name)
        (self.repository / "engine/sycl").mkdir(parents=True)
        shutil.copyfile(UPSTREAM_SOURCE / "engine/CMakeLists.txt", self.repository / "engine/CMakeLists.txt")
        shutil.copyfile(UPSTREAM_SOURCE / "engine/sycl/setup_intel.py", self.repository / "engine/sycl/setup_intel.py")
        for name in (
            "engine/sycl/serve/strata-sycl.sh",
            "engine/metal/setup_mac.py", "engine/spark/build_engine.sh", "engine/sycl/tools/build.sh",
            "tools/packaging/build_cuda_linux.sh", "tools/packaging/build_cuda_windows.py",
            "tools/packaging/build_hip_linux.sh", "tools/packaging/build_split_cuda.sh",
            "tools/packaging/build_split_hip.sh", "tools/packaging/build_sycl_linux.sh",
            "tools/packaging/build_vision_mac.sh", "tools/packaging/build_vision_windows.bat",
        ):
            destination = self.repository / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(UPSTREAM_SOURCE / name, destination)
            shutil.copymode(UPSTREAM_SOURCE / name, destination)
        (self.repo / "removed.py").write_text("obsolete source\n")
        self.old = self.commit()
        (self.repo / "code.py").write_text("new source\n")
        (self.repo / "removed.py").unlink()
        self.new = self.commit()
        self.state = self.base / "data with spaces"

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repository), *args], env=self.env, stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

    def commit(self):
        self.git("add", "--all")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--quiet", "-m", "source revision")
        return self.git("rev-parse", "HEAD")

    def command(self, revision):
        return [sys.executable, "-c", RUNNER, WORKSPACE, str(self.state), revision, str(self.repository)]

    def prepare(self, revision):
        result = subprocess.run(self.command(revision), env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip())


    def make_cross_pin_sources(self):
        """Build two tracked revisions from the exact flat and split upstream consumer bytes."""
        patch_paths = {line.split()[3][2:] for line in Path(SOURCE_PATCH).read_text().splitlines()
                       if line.startswith("diff --git ")}
        def replace(source):
            for child in self.repository.iterdir():
                if child.name != ".git":
                    if child.is_dir():
                        for directory, _, _ in os.walk(child, followlinks=False):
                            Path(directory).chmod(Path(directory).stat().st_mode | 0o700)
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            runtime = source / "terminal" if (source / "terminal/setup.py").is_file() else source
            relative = runtime.relative_to(source)
            destination = self.repository / relative
            destination.mkdir(parents=True, exist_ok=True)
            for child in runtime.iterdir():
                if child.is_file():
                    shutil.copyfile(child, destination / child.name)
                    shutil.copymode(child, destination / child.name)
            for name in ("strata_control", "strata_cli", "serve", "tools"):
                shutil.copytree(runtime / name, destination / name, copy_function=shutil.copyfile)
            for name in patch_paths | {".gitignore", "setup.sh", "CMakeLists.txt", "engine/CMakeLists.txt",
                                       "sycl/setup_intel.py", "sycl/serve/strata-sycl.sh",
                                       "engine/sycl/setup_intel.py", "engine/sycl/serve/strata-sycl.sh"}:
                original = source / name
                if original.is_file():
                    target = self.repository / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        target.chmod(target.stat().st_mode | 0o200)
                    shutil.copyfile(original, target)
                    shutil.copymode(original, target)
            for directory, _, files in os.walk(self.repository):
                if ".git" in Path(directory).parts:
                    continue
                Path(directory).chmod(0o700)
                for name in files:
                    path = Path(directory) / name
                    path.chmod(path.stat().st_mode | 0o200)
            self.git("add", "--force", "--all")  # upstream tracks some paths also matched by its current ignore rules
            return self.commit()
        self.old = replace(OLD_UPSTREAM_SOURCE)
        self.new = replace(UPSTREAM_SOURCE)
        import difflib
        original = (OLD_UPSTREAM_SOURCE / "strata.py").read_text().splitlines(keepends=True)
        accepted = list(original)
        accepted[0] = accepted[0].replace("entry point.", "entry point (accepted historical overlay).")
        self.legacy_overlay = self.base / "accepted-flat.patch"
        self.legacy_overlay.write_text("diff --git a/strata.py b/strata.py\n" + "".join(
            difflib.unified_diff(original, accepted, fromfile="a/strata.py", tofile="b/strata.py")))
        self.state = self.base / "cross-pin's workspace with spaces"
        for key in ("STRATA_SYCL_ROOT", "STRATA_SYCL_BIN", "STRATA_SYCL_CWD"):
            self.env.pop(key, None)

    def prepare_cross_pin(self, revision, *, overlay=True):
        selected = self.legacy_overlay if revision == self.old else Path(SOURCE_PATCH)
        result = subprocess.run(self.command(revision), env=dict(self.env, TEST_SOURCE_PATCH=str(selected) if overlay else ""),
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        repository = Path(result.stdout.strip()).parent
        return repository / "terminal" if (repository / "terminal/setup.py").is_file() else repository

    def cross_pin_cli(self, revision, *args, overlay=True):
        selected = self.legacy_overlay if revision == self.old else Path(SOURCE_PATCH)
        result = subprocess.run(self.command(revision) + ["run", *args],
                                env=dict(self.env, TEST_SOURCE_PATCH=str(selected) if overlay else ""),
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def assert_cross_pin_sycl_consumers(self, revision, root, config, binary, model, pack, *, overlay=True):
        selected = self.legacy_overlay if revision == self.old else Path(SOURCE_PATCH)
        env = dict(self.env, TEST_SOURCE_PATCH=str(selected) if overlay else "")
        result = subprocess.run(self.command(revision) + ["run", "doctor", "--profile", str(config), "--output", "json"],
                                env=env, capture_output=True, text=True, timeout=60)
        # Monitor dependencies and hardware qualification are not the filesystem/transport contract.
        self.assertIn(result.returncode, (0, 5), result.stderr + result.stdout)
        components = {item["name"]: item for item in json.loads(result.stdout)["report"]["components"]}
        expected = {"engine": binary, "engine_launcher": WORKSPACE_LIB / "strata-sycl.sh", "native": model, "pack": pack}
        for name, path in expected.items():
            self.assertEqual(Path(components[name]["path"]).resolve(), path.resolve(), components[name])
            self.assertEqual(components[name]["status"], "ok", components[name])
        server = root / "serve/server_parts/engines.py" if (root / "serve/server_parts/engines.py").is_file() else root / "serve/server.py"
        # Execute the actual checkout's engine_binary declaration, avoiding unrelated HTTP/model dependencies.
        script = r"""
import ast, json, os
from pathlib import Path
from serve.runconfig import load
source = Path(SERVER)
bindings = [node for node in ast.parse(source.read_text()).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "engine_binary"
            or isinstance(node, ast.ImportFrom) and any((item.asname or item.name) == "engine_binary" for item in node.names)]
assert len(bindings) == 1, bindings
namespace = {"Path": Path, "os": os}
exec(compile(ast.Module(body=bindings, type_ignores=[]), str(source), "exec"), namespace)
cfg = load(CONFIG)
print(json.dumps(namespace["engine_binary"](cfg["exe"], cfg)))
""".replace("SERVER", repr(str(server))).replace("CONFIG", repr(str(config)))
        repository = root.parent if root.name == "terminal" else root
        result = subprocess.run([sys.executable, "-c", script], cwd=root,
                                env=dict(self.env, STRATA_MANAGED_SOURCE=str(repository)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(json.loads(result.stdout)).resolve(), binary.resolve())

    def make_local_runtime(self, root):
        """Create an offline real venv whose base interpreter belongs to the managed layout."""
        base = root / ".python"
        (base / "bin").mkdir(parents=True)
        shutil.copy2(sys._base_executable, base / "bin/python")
        (base / "lib").symlink_to(Path(sys.base_prefix) / "lib", target_is_directory=True)
        subprocess.run([str(base / "bin/python"), "-m", "venv", "--without-pip",
                        str(root / ".venv")], env=self.env, check=True, capture_output=True)
        version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        package = root / ".venv/lib" / version / "site-packages/relocation_fixture.py"
        package.write_text("VALUE = 'retained package'\n")
        package.chmod(0o640)
        entry = root / ".venv/bin/relocation-fixture"
        entry.write_text("#!/bin/sh\n"
                         + f"'''exec' {shlex.quote(str(root / '.venv/bin/python'))} \"$0\" \"$@\"\n"
                         + "' '''\n"
                         + "import relocation_fixture; print(relocation_fixture.VALUE)\n")
        entry.chmod(0o750)
        subprocess.run([str(entry)], env=self.env, check=True, capture_output=True)
        return {path.relative_to(root): (path.read_bytes(), path.stat().st_mode & 0o777,
                                        path.stat().st_ino)
                for path in (root / ".venv").rglob("*")
                if path.is_file() and ("site-packages" in path.parts)}

    def assert_local_runtime(self, root, retained):
        result = subprocess.run([str(root / ".venv/bin/relocation-fixture")], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "retained package")
        python = root / ".venv/bin/python"
        self.assertTrue(python.resolve().is_relative_to(root / ".python"))
        result = subprocess.run([str(python), "-c",
                                 "import json, sys; print(json.dumps([sys.prefix, sys.base_prefix]))"],
                                env=self.env, capture_output=True, text=True, check=True)
        prefix, base = json.loads(result.stdout)
        self.assertEqual(Path(prefix), root / ".venv")
        self.assertEqual(Path(base), root / ".python")
        self.assertEqual((root / ".venv/bin/relocation-fixture").stat().st_mode & 0o777, 0o750)
        metadata = (root / ".venv/pyvenv.cfg").read_text()
        self.assertIn(str(root / ".python/bin"), metadata)
        activated = subprocess.run(
            ["sh", "-c", '. "$1"; "$VIRTUAL_ENV/bin/relocation-fixture"; '
             'python -c "import json,sys; print(json.dumps([sys.prefix,sys.base_prefix]))"',
             "activate-fixture", str(root / ".venv/bin/activate")],
            env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(activated.returncode, 0, activated.stderr)
        lines = activated.stdout.splitlines()
        self.assertEqual(lines[0], "retained package")
        self.assertEqual(json.loads(lines[1]), [str(root / ".venv"), str(root / ".python")])
        for relative, expected in retained.items():
            path = root / relative
            self.assertEqual((path.read_bytes(), path.stat().st_mode & 0o777, path.stat().st_ino), expected)
    def test_module_launcher_quotes_all_directories_and_preserves_user_arguments(self):
        for fixture in LAUNCHERS:
            with self.subTest(expected=fixture["expected"]):
                args = ["source", "--models-dir", "/CLI's $(touch injected)", "--api-key=--setup"]
                result = subprocess.run([fixture["launcher"], *args], env=self.env, cwd=self.base,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = json.loads(result.stdout)
                self.assertEqual(actual[:2], ["develop", "--no-update-lock-file"])
                self.assertTrue(actual[2].startswith("path:") and actual[2].endswith("#strata"))
                self.assertEqual(actual[3:5], ["--command", "python3"])
                self.assertEqual(actual[6:10], fixture["expected"])
                self.assertEqual(actual[11:], args)
                self.assertFalse((self.base / "injected").exists())

    def make_acquisition_workspace(self):
        root = self.prepare(self.old)
        self.make_runtime_source(root)
        (root / ".venv/bin").mkdir(parents=True)
        (root / ".venv/bin/python").symlink_to(sys.executable)
        script = root / "setup-fixture.py"
        script.write_text(f'''#!{sys.executable}
import inspect, json, sys
from pathlib import Path
sys.path.append(r"{UPSTREAM}")
import setup
# Keep the real parser, folder resolver, wizard and destination calculations.
# Replace hardware and acquisition boundaries; never fetch packages, engines or weights.
{HARDWARE_SETUP}
setup.disk_room_problem = lambda *args, **kwargs: None
setup.engine_step = lambda a, gpu, hip, amd, cuda, vision: (
    setup.ROOT, setup.ROOT / "engine", {{"version": "0.1.46"}}, [], gpu, vision)
downloads, pack_commands = [], []
setup.download = lambda url, destination, *args, **kwargs: downloads.append(str(destination))
setup.check_shards = lambda shards: None
setup.run = lambda command, **kwargs: pack_commands.append(command)
def capture(draft, *args, **kwargs):
    state = inspect.currentframe().f_back.f_locals
    a = state["a"]
    (setup.ROOT / "destinations.json").write_text(json.dumps({{
        "data": str(state["data"]), "models": str(state["models_dir"]), "pack": str(state["pack"]),
        "draft": str(draft), "shards": [str(p) for p in state["shards"]],
        "downloads": downloads, "pack_commands": pack_commands, "api_key": a.api_key,
    }}))
    raise SystemExit(0)
setup.fetch_mtp = capture
sys.exit(setup.main())
''')
        script.chmod(0o700)
        return root

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_directory_defaults_reach_upstream_acquisition_and_cli_wins(self):
        original_state = self.state
        data = self.base / "new data with spaces"
        models = self.base / "GGUF's $(touch injected) ; models"
        cli_data = self.base / "CLI data"
        cli_models = self.base / "CLI models"
        cases = [
            (None, None, [], None, None),
            (str(data), None, [], data, None),
            (None, str(models), [], None, models),
            (str(data), str(models), [], data, models),
            (str(data), str(models), ["--setup"], data, models),
            (str(data), str(models), ["--setu"], data, models),
            (str(data), str(models), ["--model=Q2_0"], data, models),
            (str(data), str(models), ["--family=qwen"], data, models),
            (str(data), str(models), ["--no-start"], data, models),
            (str(data), str(models), ["--models-dir", str(cli_models)], data, cli_models),
            (str(data), str(models), [f"--models-dir={cli_models}"], data, cli_models),
            (str(data), str(models), ["--models", str(cli_models)], data, cli_models),
            (str(data), str(models), [f"--models-d={cli_models}"], data, cli_models),
            (str(data), str(models), ["--data-dir", str(cli_data)], cli_data, models),
            (str(data), str(models), [f"--data-d={cli_data}"], cli_data, models),
            (str(data), str(models), [f"--data-dir={cli_data}", f"--models-di={cli_models}"],
             cli_data, cli_models),
            (str(data), str(models), ["--api-key=--models-dir"], data, models),
            (None, None, [f"--models-dir={cli_models}"], None, cli_models),
        ]
        for index, (data_default, models_default, args, expected_data, expected_models) in enumerate(cases):
            with self.subTest(args=args, data=data_default, models=models_default):
                self.state = original_state / str(index)
                root = self.make_acquisition_workspace()
                if any(arg.partition("=")[0] in {"--setup", "--setu", "--model", "--family", "--no-start"}
                       for arg in args):
                    self.make_runtime_model(root)
                env = dict(self.env, XDG_CONFIG_HOME=str(self.base / "config" / str(index)))
                if data_default is not None:
                    env["TEST_DATA_DIRECTORY"] = data_default
                if models_default is not None:
                    env["TEST_MODELS_DIRECTORY"] = models_default
                result = subprocess.run(
                    self.command(self.old) + ["run", "source", "--yes", "--no-browser", "--context", "8192",
                                             "--vision", "no", "--experimental-speed-projection", "off", *args],
                    env=env, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = json.loads((root / "destinations.json").read_text())
                selected_data = expected_data or root.parent / "Strata-data"
                selected_models = expected_models or selected_data / "models"
                self.assertEqual(Path(actual["data"]), selected_data)
                self.assertEqual(Path(actual["models"]).parent, selected_models)
                self.assertTrue(actual["shards"])
                self.assertTrue(all(Path(p).is_relative_to(selected_models) for p in actual["shards"]))
                self.assertEqual(Path(actual["pack"]).parent, selected_data / "packs")
                self.assertEqual(Path(actual["draft"]), selected_data / "mtp")
                self.assertEqual(actual["downloads"], actual["shards"])
                self.assertTrue(actual["pack_commands"])
                for command in actual["pack_commands"]:
                    self.assertEqual(command[command.index("--out") + 1], actual["pack"])
                    self.assertEqual(command[command.index("--gguf") + 1], actual["shards"][0])
                self.assertEqual(actual["api_key"], "--models-dir" if "--api-key=--models-dir" in args else None)
                self.assertFalse(any(selected_models.rglob("*.gguf")))
                self.assertFalse((root / "injected").exists())
                self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())
                settings = Path(env["XDG_CONFIG_HOME"]) / "strata/settings.json"
                self.assertEqual(json.loads(settings.read_text())["data_dir"], str(selected_data))

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_directory_defaults_preserve_upstream_errors_and_standalone_commands(self):
        root = self.make_acquisition_workspace()
        data = self.base / "unused data"
        models = self.base / "unused models"
        env = dict(self.env, TEST_DATA_DIRECTORY=str(data), TEST_MODELS_DIRECTORY=str(models))
        script = root / "setup-fixture.py"
        script.write_text(script.read_text().replace(
            "sys.exit(setup.main())",
            '''def standalone(a):
    assert a.data_dir is None and a.models_dir is None
    return 0
setup.prepare_pack_only = standalone
sys.exit(setup.main())''',
        ))
        for args, code in ((["--help"], 0), (["--prepare-pack", "/not downloaded"], 0),
                           (["--set"], 2), (["--mod=/ambiguous"], 2), (["--models-dir"], 2)):
            with self.subTest(args=args):
                result = subprocess.run(self.command(self.old) + ["run", "source", *args], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, code, result.stderr)
                if code:
                    self.assertIn("error:", result.stderr)
                self.assertFalse(data.exists())
                self.assertFalse(models.exists())
                self.assertFalse((root / "destinations.json").exists())

    def make_ready_workspace(self):
        root = self.prepare(self.old)
        self.make_runtime_source(root)
        (root / ".venv/bin").mkdir(parents=True)
        (root / ".venv/bin/python").symlink_to(sys.executable)
        for name in ("gguf_reader.py", "image/qimage.py"):
            destination = root / "tools" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(UPSTREAM) / "tools" / name, destination)
        script = root / "setup-fixture.py"
        script.write_text(f'''#!{sys.executable}
import hashlib, importlib.util, inspect, json, os, socket, subprocess, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.append(r"{UPSTREAM}")
import setup
def no_network(*args, **kwargs):
    raise AssertionError("setup attempted a network connection")
socket.socket.connect = no_network
socket.create_connection = no_network
{HARDWARE_SETUP}
card["count"] = 1
setup.gpu_compute_mode = lambda *args: None
setup.gpu_drives_display = lambda *args: False
setup.rotational_disk = lambda *args: None
setup.free_gb = lambda *args: 1000.0
setup.cpu_sockets = lambda: []
setup.setup_calibration = lambda *args: None
setup.ensure_nvfp4_local_packages = lambda: None
setup.engine_step = lambda a, gpu, hip, amd, cuda, vision: (
    setup.ROOT, setup.ROOT / "engine", {{"version": "99.0.0"}}, [], gpu, vision)
setup.build_image_engine = lambda *args: (setup.ROOT / "sd-cli", [])
setup.image_backend_choice = lambda *args: ("cuda", "Q4_K_M", None)
payloads, payloads_by_sha = {{}}, {{}}
def pin(url, original_sha):
    payload = original_sha.encode()
    sha = hashlib.sha256(payload).hexdigest()
    payloads[url] = payload
    payloads_by_sha[sha] = payload
    return len(payload), sha
for name, repo in setup.NVFP4_REPOS.items():
    repo["files"] = {{path: (role, *pin(f"{{setup.hf_endpoint()}}/{{name}}/resolve/{{repo['revision']}}/{{path}}", sha))
                     for path, (role, _, sha) in repo["files"].items()}}
    setup.REV_PINS[(name, repo["revision"])] = {{Path(path).name: (size, sha)
                                            for path, (_, size, sha) in repo["files"].items()}}
for fam in setup.FAMILIES.values():
    if fam.get("mmproj_sha256"):
        fam["mmproj_sha256"] = pin(fam["mmproj_hf"] + fam["mmproj"], fam["mmproj_sha256"][1])
qi = setup._qimage()
qi.FILES = {{name: (repo, path, *pin(qi.file_url(name, setup.hf_endpoint()), sha))
            for name, (repo, path, _, sha) in qi.FILES.items()}}
downloads, commands, local_checks = [], [], []
original_download = setup.download
def write(path, payload=b"x"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
def download(url, destination, *args, **kwargs):
    destination = Path(destination)
    if os.environ.get("FORBID_DOWNLOADS"):
        raise AssertionError("unexpected download: " + str(destination))
    if os.environ.get("VERIFY_LOCAL_CHECKPOINT"):
        local_checks.append(str(destination))
        return original_download(url, destination, *args, **kwargs)
    if not destination.exists():
        if os.environ.get("FORBID_ACQUISITION"):
            raise AssertionError("unexpected download: " + str(destination))
        downloads.append(str(destination))
        payload = payloads[url]
        part = destination.with_name(destination.name + ".part")
        if part.exists():
            assert payload.startswith(part.read_bytes())
            part.unlink()
        write(destination, payload)
setup.download = download
spec = importlib.util.spec_from_file_location("local_pack", setup.ROOT / "tools/nvfp4_local_pack.py")
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)
producer.require_packages = lambda: None
def produce(command, **kwargs):
    commands.append([str(arg) for arg in command])
    if os.environ.get("FORBID_ACQUISITION"):
        raise AssertionError("unexpected producer: " + repr(command))
    name = Path(command[1]).name
    mode = command[2] if name == "nvfp4_local_pack.py" else name
    if name == "nvfp4_local_pack.py":
        checkpoint = Path(command[command.index("--model") + 1])
        for f in setup.ready_files("NVFP4-QAD"):
            source = checkpoint / f[3]
            assert setup.ready_verified(source, f[5]), source
            assert hashlib.sha256(source.read_bytes()).hexdigest() == f[5], source
    flag = "--outfile" if mode == "convert" else "--out"
    out = Path(command[command.index(flag) + 1])
    if mode in ("ple", "convert", "mtp_pack.py"):
        write(out)
    elif mode == "pack":
        dense = Path(command[command.index("--dense-gguf") + 1])
        assert dense.read_bytes() == b"x", dense
        for child in ("index.txt", "native_experts.txt", "experts.bin", "tokenizer/vocab.json"):
            write(out / child)
    elif mode == "mtp_rt.py":
        write(out / "experts.bin")
    else:
        out.mkdir(parents=True, exist_ok=True)
    return subprocess.CompletedProcess(command, 0)
def run(command, **kwargs):
    if "prepare" in command:
        commands.append([str(arg) for arg in command])
        if os.environ.get("FORBID_ACQUISITION"):
            raise AssertionError("unexpected prepare")
        args = SimpleNamespace(model=command[command.index("--model") + 1],
                               out=command[command.index("--out") + 1],
                               gguf_out=command[command.index("--gguf-out") + 1] if "--gguf-out" in command else None)
        with patch.object(subprocess, "run", side_effect=produce):
            producer.cmd_prepare(args)
    else:
        produce(command)
setup.run = run
setup.fetch_mtp = lambda folder, *args: write(folder / "rt/experts.bin")
setup.refresh_draft_vocab = lambda *args: None
setup.refresh_dflash2_vocab = lambda *args: None
if os.environ.get("WIZARD_MODEL"):
    original_ask = setup.ask
    def ask(prompt, options, default, yes):
        frame = inspect.currentframe().f_back
        if prompt == "Which model?":
            return str(frame.f_locals["allf"].index("nvfp4") + 1)
        if prompt == "Which size?":
            return str(frame.f_locals["names"].index(os.environ["WIZARD_MODEL"]) + 1)
        return original_ask(prompt, options, default, yes)
    setup.ask = ask
if os.environ.get("LEGACY_READY") or os.environ.get("LEGACY_CHECKPOINT"):
    model = os.environ.get("LEGACY_READY") or os.environ["LEGACY_CHECKPOINT"]
    models = Path(os.environ["LEGACY_MODELS"])
    checkpoint_only = bool(os.environ.get("LEGACY_CHECKPOINT"))
    files = setup.ready_files(model)
    pending = [f[3] for f in files if f[3].startswith("tensors/")][-2:] if os.environ.get("PARTIAL_CHECKPOINT") else []
    seed = {{"preserved": {{}}, "pending": [], "competitor": {{}}, "unmarked": []}}
    for f in files:
        if checkpoint_only or os.environ.get("RETAIN_CHECKPOINT") or not (
                setup.MODELS[model].get("prepare") and f[3].startswith("tensors/")):
            dst = setup.ready_where(models, f)
            payload = payloads_by_sha[f[5]]
            if f[3] in pending:
                seed["pending"].append(str(dst))
                if f[3] == pending[0]:
                    write(dst.with_name(dst.name + ".part"), payload[:len(payload) // 2])
                continue
            write(dst, payload)
            if os.environ.get("VERIFY_LOCAL_CHECKPOINT"):
                seed["unmarked"].append(str(dst))
            else:
                setup.mark(dst, "sha256 " + f[5])
    if os.environ.get("SEED_PLE"):
        ple = setup.ready_paths(model, Path(os.environ["TEST_MODELS_DIRECTORY"]),
                                Path(os.environ["TEST_DATA_DIRECTORY"]))["ple"]
        write(ple)
        write(ple.with_name("ple-nvfp4.gguf.done"))
    if not checkpoint_only and setup.MODELS[model].get("prepare"):
        paths = setup.ready_paths(model, models)
        for role, dst in paths.items():
            if role in ("dense", "ple"):
                write(dst)
            elif role == "pack":
                write(dst / "experts.bin")
            elif role == "mtp":
                write(dst / "rt/experts.bin")
        for mark in producer.MARKS:
            write(setup.prepared_dir(model, models) / mark)
    for path in models.rglob("*"):
        if path.is_file() and not path.name.endswith(".part"):
            seed["preserved"][str(path)] = [path.stat().st_ino, path.read_bytes().hex()]
    competitor = os.environ.get("CHECKPOINT_COMPETITOR")
    if competitor:
        assert len(files) == 29 and all(f[0] == "src" for f in files)
        other_models = Path(os.environ["TEST_DATA_DIRECTORY"]) / "models"
        for f in files[:-1]:
            dst = setup.ready_where(other_models, f)
            write(dst, payloads_by_sha[f[5]])
            setup.mark(dst, "sha256 " + f[5])
        last = files[-1]
        dst = setup.ready_where(other_models, last)
        part = dst.with_name(dst.name + ".part")
        payload = payloads_by_sha[last[5]]
        assert len(payload) == last[4] == 64
        if competitor == "full-part":
            part.parent.mkdir(parents=True, exist_ok=True)
            with part.open("wb") as stream:
                stream.seek(last[4] - 1)
                stream.write(payload[-1:])
        else:
            assert competitor == "short-part"
            write(part, payload[:len(payload) // 2])
        write(part.with_name(part.name + ".chunks"),
              json.dumps({{"v": 1, "total": last[4], "chunk": setup.DL_CHUNK, "done": []}}).encode())
        assert not dst.exists() and not setup.ready_verified(dst, last[5])
        for path in other_models.rglob("*"):
            if path.is_file():
                seed["competitor"][str(path)] = [path.stat().st_ino, path.read_bytes().hex()]
    (setup.ROOT / "checkpoint-seed.json").write_text(json.dumps(seed))
if os.environ.get("VERIFY_LOCAL_CHECKPOINT"):
    def no_acquisition(*args, **kwargs):
        raise AssertionError("unexpected acquisition: " + repr(args))
    setup.acquisition.require = no_acquisition
result = setup.main()
(setup.ROOT / "ready-observed.json").write_text(json.dumps({{"downloads": downloads, "commands": commands}}))
if os.environ.get("VERIFY_LOCAL_CHECKPOINT"):
    (setup.ROOT / "checkpoint-local-checks.json").write_text(json.dumps(local_checks))
sys.exit(result)
''')
        script.chmod(0o700)
        return root

    def ready_command(self, model, *, wizard=False):
        args = ["run", "source", "--yes", "--no-start", "--no-browser", "--context", "8192",
                "--vision", "gpu", "--images", "qwen-image",
                "--experimental-speed-projection", "off"]
        if not wizard:
            args += ["--family", "nvfp4", "--model", model]
        return self.command(self.old) + args

    def read_ready_config(self, root):
        paths = [p for p in root.glob("strata-*.json") if not p.name.endswith(".shared-settings.json")]
        self.assertEqual(len(paths), 1, paths)
        return json.loads(paths[0].read_text())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_ready_full_setup_json_roles_cli_and_late_wizard(self):
        initial = self.state
        for index, (model, split, override, wizard) in enumerate([
            ("NVFP4", False, False, False),
            ("NVFP4", True, False, False),
            ("NVFP4-NVIDIA", True, True, False),
            ("NVFP4-QAD", True, False, False),
            ("NVFP4-QAD", True, True, True),
            ("NVFP4", False, True, False),
        ]):
            with self.subTest(model=model, split=split, override=override, wizard=wizard):
                self.state = initial / str(index)
                root = self.make_ready_workspace()
                data, default_models, cli_models = (self.base / f"{index}-{name}" for name in ("data", "models", "CLI models"))
                models = cli_models if override else default_models if split else data / "models"
                env = dict(self.env, TEST_DATA_DIRECTORY=str(data), XDG_CONFIG_HOME=str(self.base / f"config-{index}"))
                if split:
                    env["TEST_MODELS_DIRECTORY"] = str(default_models)
                if wizard:
                    env["WIZARD_MODEL"] = model
                command = self.ready_command(model, wizard=wizard)
                if override:
                    command += [f"--models-di={cli_models}"]
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                cfg = self.read_ready_config(root)
                args = cfg["args"]
                native = Path(args[args.index("--native") + 1])
                pack = Path(args[args.index("--pack") + 1])
                ple = Path(args[args.index("--ple-gguf") + 1])
                mtp = Path(args[args.index("--mtp") + 1])
                auxiliary = data / "models" if split else models
                for path in (native, ple, Path(cfg["vision"]["mmproj"])):
                    self.assertTrue(path.is_relative_to(models), path)
                    self.assertTrue(path.is_file(), path)
                self.assertEqual(cfg["vision"]["model"], str(native))
                self.assertTrue(pack.is_relative_to(auxiliary), pack)
                self.assertTrue((pack / "experts.bin").is_file())
                if model == "NVFP4-QAD":
                    self.assertTrue(mtp.is_relative_to(auxiliary))
                    self.assertTrue((mtp / "experts.bin").is_file())
                    for mark in ("dense.gguf.done", "ple-nvfp4.gguf.done"):
                        self.assertTrue((native.parent / mark).is_file())
                    for mark in ("pack.done", "draft.done"):
                        self.assertTrue((pack.parent / mark).is_file())
                else:
                    self.assertTrue(mtp.is_relative_to(data))
                    embedding = Path(args[args.index("--embd-gguf") + 1])
                    self.assertTrue(embedding.is_relative_to(models))
                    self.assertTrue(embedding.is_file())
                images = cfg["images"]
                self.assertTrue(Path(images["vae"]).is_relative_to(auxiliary))
                for name in ("diffusion_model", "llm"):
                    self.assertTrue(Path(images[name]).is_relative_to(models))
                for name in ("vae", "diffusion_model", "llm"):
                    self.assertTrue(Path(images[name]).is_file())
                if split:
                    payloads = [p for p in models.rglob("*") if p.is_file() and not p.name.endswith(".done")]
                    self.assertTrue(all(p.suffix == ".gguf" for p in payloads), payloads)
                if model == "NVFP4-QAD":
                    for path in auxiliary.rglob("*.safetensors"):
                        if path != Path(images["vae"]):
                            path.unlink()
                second = subprocess.run(command + ["--setup"], env=dict(env, FORBID_ACQUISITION="1"),
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
                self.assertEqual(json.loads((root / "ready-observed.json").read_text()), {"downloads": [], "commands": []})

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_complete_legacy_ready_reuses_pair_without_moving_or_redownloading(self):
        root = self.make_ready_workspace()
        data, models = self.base / "primary data", self.base / "legacy GGUF root"
        env = dict(self.env, TEST_DATA_DIRECTORY=str(data), TEST_MODELS_DIRECTORY=str(models),
                   LEGACY_READY="NVFP4-QAD", LEGACY_MODELS=str(models))
        result = subprocess.run(self.ready_command("NVFP4-QAD"), env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        cfg = self.read_ready_config(root)
        args = cfg["args"]
        self.assertTrue(Path(args[args.index("--pack") + 1]).is_relative_to(models))
        self.assertTrue(Path(args[args.index("--mtp") + 1]).is_relative_to(models))
        self.assertTrue(Path(cfg["images"]["vae"]).is_relative_to(data / "models"))
        observed = json.loads((root / "ready-observed.json").read_text())
        self.assertEqual(observed["commands"], [])
        self.assertFalse(any("tensors/" in path for path in observed["downloads"]))

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_complete_ready_data_root_survives_new_models_directory(self):
        state = self.state
        for model, retained in (("NVFP4", False), ("NVFP4-QAD", False), ("NVFP4-QAD", True)):
            with self.subTest(model=model, retained=retained):
                case = model + ("-retained" if retained else "-deleted")
                self.state = state / case
                root = self.make_ready_workspace()
                data, models = self.base / case / "data", self.base / case / "new GGUF"
                legacy = data / "models"
                env = dict(self.env, TEST_DATA_DIRECTORY=str(data), TEST_MODELS_DIRECTORY=str(models),
                           LEGACY_READY=model, LEGACY_MODELS=str(legacy), FORBID_ACQUISITION="1")
                if retained:
                    env["RETAIN_CHECKPOINT"] = "1"
                command = self.ready_command(model)
                if model == "NVFP4":
                    command += ["--mtp", "off"]
                command[command.index("--vision") + 1] = "no"
                command[command.index("--images") + 1] = "no"
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                args = self.read_ready_config(root)["args"]
                for flag in ("--native", "--ple-gguf", "--pack", *(["--mtp"] if model == "NVFP4-QAD" else [])):
                    self.assertTrue(Path(args[args.index(flag) + 1]).is_relative_to(legacy), (flag, args))
                observed = json.loads((root / "ready-observed.json").read_text())
                self.assertEqual(observed, {"downloads": [], "commands": []})
                self.assertFalse(models.exists())
                seed = json.loads((root / "checkpoint-seed.json").read_text())
                for name, (inode, content) in seed["preserved"].items():
                    self.assertEqual(Path(name).stat().st_ino, inode)
                    self.assertEqual(Path(name).read_bytes().hex(), content)
                if model == "NVFP4-QAD":
                    self.assertEqual(bool(list(legacy.rglob("*.safetensors"))), retained)
        self.state = state

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_qad_existing_checkpoint_resumes_with_split_outputs(self):
        state = self.state
        for phase in ("checkpoint", "partial-download", "partial-preparation",
                      "verified-versus-full-part", "unmarked-versus-short-part"):
            with self.subTest(phase=phase):
                self.state = state / phase
                root = self.make_ready_workspace()
                data, models = self.base / phase / "data", self.base / phase / "GGUF"
                env = dict(self.env, TEST_DATA_DIRECTORY=str(data), TEST_MODELS_DIRECTORY=str(models),
                           LEGACY_CHECKPOINT="NVFP4-QAD", LEGACY_MODELS=str(models))
                if phase == "partial-download":
                    env["PARTIAL_CHECKPOINT"] = "1"
                if phase == "partial-preparation":
                    env["SEED_PLE"] = "1"
                if phase == "verified-versus-full-part":
                    env.update(CHECKPOINT_COMPETITOR="full-part", FORBID_DOWNLOADS="1")
                elif phase == "unmarked-versus-short-part":
                    env.update(CHECKPOINT_COMPETITOR="short-part", VERIFY_LOCAL_CHECKPOINT="1")
                command = self.ready_command("NVFP4-QAD")
                command[command.index("--vision") + 1] = "no"
                command[command.index("--images") + 1] = "no"
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                seed = json.loads((root / "checkpoint-seed.json").read_text())
                for name, (inode, content) in {**seed["preserved"], **seed["competitor"]}.items():
                    self.assertEqual(Path(name).stat().st_ino, inode)
                    self.assertEqual(Path(name).read_bytes().hex(), content)
                observed = json.loads((root / "ready-observed.json").read_text())
                self.assertEqual(set(observed["downloads"]), set(seed["pending"]))
                preparation = next(c for c in observed["commands"] if "prepare" in c)
                source = models / "nvidia--Qwen3.8-Flash-Next-FP4-Local"
                self.assertEqual(Path(preparation[preparation.index("--model") + 1]), source)
                self.assertEqual(Path(preparation[preparation.index("--gguf-out") + 1]),
                                 source / "prepared")
                if phase == "unmarked-versus-short-part":
                    checks = json.loads((root / "checkpoint-local-checks.json").read_text())
                    self.assertEqual(len(checks), 29)
                    self.assertEqual(set(checks), set(seed["unmarked"]))
                args = self.read_ready_config(root)["args"]
                for flag in ("--native", "--ple-gguf"):
                    self.assertTrue(Path(args[args.index(flag) + 1]).is_relative_to(models))
                    self.assertTrue(Path(args[args.index(flag) + 1]).is_file())
                for flag in ("--pack", "--mtp"):
                    self.assertTrue(Path(args[args.index(flag) + 1]).is_relative_to(data / "models"))
                self.assertTrue((source / "tensors").is_dir())
                concurrent_tensors = data / "models/nvidia--Qwen3.8-Flash-Next-FP4-Local/tensors"
                self.assertEqual(concurrent_tensors.exists(), bool(seed["competitor"]))
                if phase == "partial-preparation":
                    self.assertFalse(any("ple" in command for command in observed["commands"]))
                shutil.rmtree(source / "tensors")
                retry_env = dict(self.env, TEST_DATA_DIRECTORY=str(data), TEST_MODELS_DIRECTORY=str(models),
                                 FORBID_ACQUISITION="1")
                retry = subprocess.run(command, env=retry_env, capture_output=True, text=True, timeout=30)
                self.assertEqual(retry.returncode, 0, retry.stderr + retry.stdout)
                self.assertEqual(json.loads((root / "ready-observed.json").read_text()),
                                 {"downloads": [], "commands": []})
                self.assertEqual(self.read_ready_config(root)["args"], args)
        self.state = state

    def run_source_script(self, root, script):
        repository = root.parent if root.name == "terminal" and (root.parent / ".git").is_dir() else root
        env = dict(self.env)
        env.pop("STRATA_MANAGED_SOURCE", None)
        if (repository / ".git").is_dir():
            env["STRATA_MANAGED_SOURCE"] = str(repository)
        result = subprocess.run(
            [sys.executable, "-c", "import sys\nsys.path.append(" + repr(UPSTREAM) + ")\n" + script],
            env=env, cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_qad_real_prepare_split_marks_resume_and_legacy_default(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import importlib.util, subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import setup
spec = importlib.util.spec_from_file_location("producer", "tools/nvfp4_local_pack.py")
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)
producer.require_packages = lambda: None
commands = []
def run(command, **kwargs):
    commands.append(command)
    flag = "--outfile" if "convert" in command else "--out"
    out = Path(command[command.index(flag) + 1])
    if out.suffix == ".gguf":
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"small output")
    else:
        out.mkdir(parents=True, exist_ok=True)
        (out / "artifact").write_bytes(b"small output")
    return subprocess.CompletedProcess(command, 0)
models, data = Path("GGUF").resolve(), Path("data").resolve()
model = "NVFP4-QAD"
out = setup.prepared_dir(model, models, data)
gguf = setup.prepared_dir(model, models)
args = SimpleNamespace(model="checkpoint", out=str(out), gguf_out=str(gguf))
with patch.object(subprocess, "run", side_effect=run):
    assert producer.cmd_prepare(args) == 0
    assert len(commands) == 6
    assert setup.prepared_done(model, models, data)
    paths = setup.ready_paths(model, models, data)
    assert paths["dense"].is_file() and paths["ple"].is_file()
    pack_cmd = next(c for c in commands if "pack" in c)
    assert pack_cmd[pack_cmd.index("--dense-gguf") + 1] == str(paths["dense"])
    assert pack_cmd[pack_cmd.index("--out") + 1] == str(paths["pack"])
    assert not any(f[3].startswith("tensors/") for f in setup.ready_needed(model, models, data))
    commands.clear()
    producer.cmd_prepare(args)
    assert commands == []
    for mark, count in zip(producer.MARKS, (1, 1, 1, 3)):
        folder = gguf if mark.endswith(".gguf.done") else out
        (folder / mark).unlink()
        assert not setup.prepared_done(model, models, data)
        assert any(f[3].startswith("tensors/") for f in setup.ready_needed(model, models, data))
        producer.cmd_prepare(args)
        assert len(commands) == count, (mark, commands)
        assert setup.prepared_done(model, models, data)
        commands.clear()
    legacy = Path("legacy").resolve()
    producer.cmd_prepare(SimpleNamespace(model="checkpoint", out=str(legacy)))
    assert all((legacy / mark).is_file() for mark in producer.MARKS)
''')

    def test_ready_fetch_destinations_marks_resume_and_disk_filesystems(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import hashlib, os
from pathlib import Path
from unittest.mock import patch
import setup
models, data = Path("GGUF").resolve(), Path("data").resolve()
models.mkdir()
(data / "models").mkdir(parents=True)
files = {"dense.gguf": ("dense", 10, "dense"),
         "ple.gguf": ("ple", 20, "ple"), "embd.gguf": ("embd", 30, "embd"),
         "pack/index.txt": ("pack", 40, "index"), "pack/experts.bin": ("pack", 50, "experts"),
         "tensors/checkpoint.safetensors": ("src", 60, "checkpoint")}
payloads = {name: token.encode() for name, (_, _, token) in files.items()}
setup.MODELS = {"fixture": {"repo": "owner/repo"}}
setup.NVFP4_REPOS = {"owner/repo": {"revision": "local",
    "files": {name: (role, len(payloads[name]), hashlib.sha256(payloads[name]).hexdigest())
              for name, (role, _, _) in files.items()}}}
downloads = []
def download(url, destination, *args):
    name = url.split("/resolve/local/")[1]
    downloads.append(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payloads[name])
setup.download = download
setup.ready_fetch("fixture", models, data)
assert len(downloads) == len(files)
for f in setup.ready_files("fixture"):
    dst = setup.ready_where(models, f, data)
    assert setup.ready_verified(dst, f[5])
    assert dst.is_relative_to(models if f[0] in ("dense", "ple", "embd") else data / "models")
    assert setup.ready_where(models, f) == models / "owner--repo" / f[3]
downloads.clear()
setup.ready_fetch("fixture", models, data)
assert downloads == []
paths = setup.ready_paths("fixture", models, data)
assert paths["pack"] == data / "models/owner--repo/pack"
# Finished downloads need no disk budget. Missing experts consume only their remainder.
experts = next(f for f in setup.ready_files("fixture") if f[3] == "pack/experts.bin")
dst = setup.ready_where(models, experts, data)
dst.unlink()
dst.with_name(dst.name + ".part").write_bytes(payloads[experts[3]][:2])
original_stat = os.stat
def stat(path, *args, **kwargs):
    result = original_stat(path, *args, **kwargs)
    values = list(result)
    values[2] = 2 if Path(path).is_relative_to(data) else 1
    return os.stat_result(values)
with patch.object(setup.os, "stat", side_effect=stat):
    budgets = setup.destination_budgets([(models / "a.gguf", 3), (data / "models/b", 4)])
    assert sorted(gb for _, gb in budgets) == [3, 4]
    with patch.object(setup, "free_gb", side_effect=lambda path: 0 if Path(path).is_relative_to(data) else 100):
        problem = setup.ready_disk_problem("fixture", models, data)
        assert problem is not None and str(data) in problem[0], problem
        dst.with_name(dst.name + ".part").write_bytes(payloads[experts[3]])
        assert setup.ready_disk_problem("fixture", models, data) is None
    with patch.object(setup, "free_gb", side_effect=lambda path: 0 if Path(path).is_relative_to(models) else 100):
        dense = paths["dense"]
        dense.unlink()
        problem = setup.ready_disk_problem("fixture", models, data)
        assert problem is not None and str(models) in problem[0], problem
budgets = setup.destination_budgets([(models / "a.gguf", 3), (data / "models/b", 4)])
assert len(budgets) == 1 and budgets[0][1] == 7
setup.ready_fetch("fixture", models, data)
assert set(downloads) == {paths["dense"], dst}, downloads
assert all(setup.ready_verified(setup.ready_where(models, f, data), f[5]) for f in setup.ready_files("fixture"))
''')

    def test_unmarked_final_budget_verifies_once_without_download_or_payload_write(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r"""
import hashlib
from pathlib import Path
from unittest.mock import patch
import setup
models, data = Path("final-models").resolve(), Path("final-data").resolve()
models.mkdir()
data.mkdir()
payload = b"complete pinned payload"
sha = hashlib.sha256(payload).hexdigest()
setup.MODELS = {"fixture": {"repo": "owner/final"}}
setup.NVFP4_REPOS = {"owner/final": {"revision": "local", "files": {
    "dense.gguf": ("dense", len(payload), sha)}}}
f = setup.ready_files("fixture")[0]
dst = setup.ready_where(models, f, data)
dst.parent.mkdir(parents=True)
dst.write_bytes(payload)
before = (dst.read_bytes(), dst.stat().st_ino, dst.stat().st_mtime_ns)
native_hash = setup._hash_file
with patch.object(setup, "free_gb", return_value=0), \
     patch.object(setup, "download", side_effect=AssertionError("unneeded acquisition")), \
     patch.object(setup, "_hash_file", wraps=native_hash) as hashes:
    assert setup.ready_disk_problem("fixture", models, data) is None
    assert setup.ready_verified(dst, sha)
    assert hashes.call_count == 1
    setup.ready_fetch("fixture", models, data)
    assert setup.ready_disk_problem("fixture", models, data) is None
    assert hashes.call_count == 1
assert (dst.read_bytes(), dst.stat().st_ino, dst.stat().st_mtime_ns) == before
# A complete length is not a certificate, including a sparse final full of zeroes.
for sparse in (False, True):
    dst.unlink(missing_ok=True)
    for marker in (dst.with_name(dst.name + ".done"), setup._kept_mark(dst)):
        if marker is not None:
            marker.unlink(missing_ok=True)
    with dst.open("wb") as stream:
        if sparse:
            stream.truncate(len(payload))
        else:
            stream.write(b"x" * len(payload))
    with patch.object(setup, "free_gb", return_value=0), \
         patch.object(setup, "download", side_effect=AssertionError("budget acquired bytes")):
        try:
            problem = setup.ready_disk_problem("fixture", models, data)
        except SystemExit:
            pass
        else:
            assert problem is not None, "wrong final credited by length"
    assert not setup.ready_verified(dst, sha)
    assert dst.with_name(dst.name + ".bad").read_bytes() != payload
""")

    def test_checkpoint_ranking_verifies_unmarked_finals_before_budget_without_rewriting_payloads(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r"""
import hashlib, json
from pathlib import Path
from unittest.mock import patch
import setup
models, data, retained = [Path(name).resolve() for name in ("rank-models", "rank-data", "rank-retained")]
repo, model = "owner/pinned-checkpoint", "NVFP4-QAD"
setup.MODELS[model]["repo"] = repo
payloads = {"tensors/first.safetensors": b"first pinned checkpoint", "tensors/second.safetensors": b"second pinned checkpoint"}
setup.NVFP4_REPOS[repo] = {"revision": "chosen-revision", "files": {
    name: ("src", len(payload), hashlib.sha256(payload).hexdigest()) for name, payload in payloads.items()}}
files = setup.ready_files(model)
roots = [data / "models" / repo.replace("/", "--"), models / repo.replace("/", "--"),
         retained / "models" / repo.replace("/", "--")]
def seed(root, values):
    for name, payload in values.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
def select():
    return setup.model_download_layout("nvfp4", model, models, data_dir=data, elsewhere=[retained])
seed(roots[1], payloads)
originals = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in roots[1].rglob("*.safetensors")}
native_hash = setup._hash_file
with patch.object(setup, "_hash_file", wraps=native_hash) as hashes, \
     patch.object(setup, "download", side_effect=AssertionError("ranking acquired payloads")):
    # No default checkpoint exists: complete unmarked requested files beat the empty first candidate.
    layout = select()
    assert layout[2] == roots[1], layout
    assert hashes.call_count == len(files), hashes.call_args_list
    # All next checks use native marks, including budget, fetch and a later selection.
    with patch.object(setup, "free_gb", return_value=1000):
        assert setup.ready_disk_problem(model, *layout[:2], checkpoint_dir=layout[2]) is None
    setup.ready_fetch(model, *layout[:2], checkpoint_dir=layout[2])
    assert select()[2] == roots[1]
    assert hashes.call_count == len(files), hashes.call_args_list
for path, before in originals.items():
    assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == before
# A corrupt complete earlier candidate stays untouched and cannot hide a valid later candidate.
seed(roots[0], {name: b"x" * len(payload) for name, payload in payloads.items()})
wrong = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in roots[0].rglob("*.safetensors")}
assert select()[2] == roots[1]
for path, before in wrong.items():
    assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) == before
    assert not setup.ready_verified(path, next(f[5] for f in files if f[3] == str(path.relative_to(roots[0]))))
    assert not path.with_name(path.name + ".bad").exists()
    path.unlink()
# A logically complete sparse part and a wrong URL receipt must not outrank genuine resume bytes.
for path in roots[1].rglob("*.safetensors"):
    path.unlink()
    path.with_name(path.name + ".done").unlink(missing_ok=True)
setup.DL_CHUNK, setup.DL_MIN_PARALLEL = 4, 4
for f in files:
    dst = roots[0] / f[3]
    part = dst.with_name(dst.name + ".part")
    with part.open("wb") as stream:
        stream.truncate(f[4])
    part.with_name(part.name + ".chunks").write_text(json.dumps({
        "v": 1, "total": f[4], "chunk": 4, "done": []}))
    part.with_name(part.name + ".src").write_text(json.dumps({"url": "https://wrong.invalid/revision"}))
    target = roots[2] / f[3]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.with_name(target.name + ".part").write_bytes(payloads[f[3]][:8])
    target.with_name(target.name + ".part.src").write_text(json.dumps({
        "url": f"{setup.hf_endpoint()}/{f[1]}/resolve/{f[2]}/{f[3]}"}))
assert select()[2] == roots[2], "sparse logical size or wrong revision won checkpoint ranking"
""")

    def test_sparse_chunk_resume_evidence_is_read_only_and_not_logical_size(self):
        root = self.prepare(self.old)
        self.run_source_script(root, """
import json
from pathlib import Path
import setup
model = Path("sparse.gguf").resolve()
part = model.with_name(model.name + ".part")
total = setup.DL_CHUNK * 3
with part.open("wb") as stream:
    stream.truncate(total)
side = part.with_name(part.name + ".chunks")
side.write_text(json.dumps({"v": 1, "total": total, "chunk": setup.DL_CHUNK, "done": [[1, 2]]}))
before = (part.stat().st_mtime_ns, side.read_bytes())
assert setup.resume_bytes(model, total) == setup.DL_CHUNK
assert (part.stat().st_mtime_ns, side.read_bytes()) == before
side.write_text(json.dumps({"v": 1, "total": total, "chunk": setup.DL_CHUNK, "done": []}))
assert setup.resume_bytes(model, total) == 0
side.write_text("invalid chunk receipt")
before = side.read_bytes()
assert setup.resume_bytes(model, total) == 0
assert part.is_file() and side.read_bytes() == before
side.write_text("[]")
assert setup.resume_bytes(model, total) == 0 and side.read_text() == "[]"
source = part.with_name(part.name + ".src")
source.write_text(json.dumps({"url": "https://wrong.invalid/revision"}))
assert setup.resume_bytes(model, total, url="https://chosen.invalid/revision") == 0
side.unlink()
assert setup.resume_bytes(model, total) == 0
assert setup.resume_bytes(model) == 0
assert part.stat().st_size == total
""")

    def test_qad_downloaded_checkpoint_keeps_preparation_disk_guards(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import hashlib, os
from pathlib import Path
from unittest.mock import patch
import setup
models, data = Path("GGUF").resolve(), Path("data").resolve()
models.mkdir()
(data / "models").mkdir(parents=True)
model = "NVFP4-QAD"
sha = hashlib.sha256(b"x").hexdigest()
repo = setup.MODELS[model]["repo"]
setup.NVFP4_REPOS[repo]["files"] = {
    name: (role, 1, sha) for name, (role, _, _) in setup.NVFP4_REPOS[repo]["files"].items()}
for f in setup.ready_files(model):
    dst = setup.ready_where(models, f, data)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"x")
    setup.mark(dst, "sha256 " + sha)
assert not setup.prepared_done(model, models, data)
# Count the 110 GB preparation estimate once when both outputs share a filesystem.
with patch.object(setup, "free_gb", return_value=20):
    assert setup.ready_disk_problem(model, models, data) is not None
with patch.object(setup, "free_gb", return_value=120):
    assert setup.ready_disk_problem(model, models, data) is None
original_stat = os.stat
def stat(path, *args, **kwargs):
    result = list(original_stat(path, *args, **kwargs))
    result[2] = 2 if Path(path).is_relative_to(data) else 1
    return os.stat_result(result)
with patch.object(setup.os, "stat", side_effect=stat):
    with patch.object(setup, "free_gb", side_effect=lambda p: 20 if Path(p).is_relative_to(data) else 200):
        problem = setup.ready_disk_problem(model, models, data)
        assert problem is not None and str(data) in problem[0], problem
    # A small GGUF volume must not be charged all 110 GB.
    with patch.object(setup, "free_gb", side_effect=lambda p: 70 if Path(p).is_relative_to(data) else 20):
        assert setup.ready_disk_problem(model, models, data) is None
    out = setup.prepared_dir(model, models, data)
    out.mkdir(parents=True)
    (out / "pack.done").write_text("done")
    with patch.object(setup, "free_gb", return_value=1):
        assert setup.ready_disk_problem(model, models, data) is None
''')

    def test_qad_checkpoint_source_budget_preserves_output_guards(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import hashlib, os
from pathlib import Path
from unittest.mock import patch
import setup
models, data, checkpoint = [Path(name).resolve() for name in ("GGUF", "data", "checkpoint")]
for directory in (models, data / "models", checkpoint):
    directory.mkdir(parents=True)
model = "NVFP4-QAD"
payload = b"checkpoint"
sha = hashlib.sha256(payload).hexdigest()
setup.NVFP4_REPOS[setup.MODELS[model]["repo"]]["files"] = {
    "tensors/checkpoint": ("src", len(payload), sha)}
dst = checkpoint / "tensors/checkpoint"
dst.parent.mkdir()
part = dst.with_name(dst.name + ".part")
part.write_bytes(payload[:4])
original_stat = os.stat
def stat(path, *args, **kwargs):
    result = list(original_stat(path, *args, **kwargs))
    result[2] = 3 if Path(path).is_relative_to(checkpoint) else 2 if Path(path).is_relative_to(models) else 1
    return os.stat_result(result)
with patch.object(setup.os, "stat", side_effect=stat):
    with patch.object(setup, "free_gb", side_effect=lambda path: 0 if Path(path).is_relative_to(checkpoint) else 1000):
        problem = setup.ready_disk_problem(model, models, data, checkpoint_dir=checkpoint)
        assert problem is not None and str(checkpoint) in problem[0], problem
    part.unlink()
    dst.write_bytes(payload)
    setup.mark(dst, "sha256 " + sha)
    with patch.object(setup, "free_gb", side_effect=lambda path: 1 if Path(path).is_relative_to(data) else 1000):
        problem = setup.ready_disk_problem(model, models, data, checkpoint_dir=checkpoint)
        assert problem is not None and str(data) in problem[0], problem
''')

    def test_published_source_delta_is_hash_addressed_and_corruption_blocks_publication(self):
        import hashlib
        root = self.prepare(self.old)
        git_dir = root.parent / ".git"
        ledger = (git_dir / "strata-source.patch").read_bytes()
        digest = hashlib.sha256(ledger).hexdigest()
        cache = git_dir / "strata-source-patches"
        self.assertEqual((cache / f"{self.old}.sha256").read_text().strip(), digest)
        payload = cache / f"{self.old}-{digest}.patch"
        self.assertEqual(payload.read_bytes(), ledger)
        payload.write_bytes(ledger + b"corrupted publication bytes\n")
        result = subprocess.run(self.command(self.new), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cached source patch", result.stderr)
        self.assertEqual((git_dir / "strata-source.patch").read_bytes(), ledger)
        self.assertEqual(subprocess.check_output(["git", "-C", str(root.parent), "rev-parse", "HEAD"],
                                                text=True).strip(), self.old)

    def test_linked_config_preserves_external_bytes_and_restores_links_after_write_failure(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import json, os
from pathlib import Path
import setup
import strata_managed_state as state
from strata_control import profiles
repository = setup.ROOT.parent
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(repository.parent)})
external = repository.parent / "shared-config/config.json"
external.parent.mkdir()
external.write_text(json.dumps({"exe": "/external/engine", "args": [], "tokenizer": "/fixture/tokenizer", "note": str(repository / "models")}, indent=4))
external_before = (external.read_bytes(), external.stat().st_ino, external.stat().st_mtime_ns)
linked = repository / "strata-linked.json"
linked.symlink_to(os.path.relpath(external, repository))
regular = repository / "strata-owned.json"
regular.write_text(json.dumps({"exe": str(repository / "python/bin/python3"), "args": [], "cwd": str(repository), "tokenizer": "/fixture/tokenizer"}))
profiles.create("linked-config", str(linked))
profiles.create("owned-config-first", str(regular))
profiles.create("owned-config-second", str(regular))
for reverse in (False, True):
    source, destination = (setup.ROOT, repository) if reverse else (repository, setup.ROOT)
    source_link = source / linked.name
    before_link = (os.readlink(source_link), source_link.lstat().st_ino)
    before_regular = ((source / regular.name).read_bytes(), (source / regular.name).stat().st_ino)
    real_write = state.write_runtime
    def refuse_content(entry, payload, mode, backup=None):
        if entry.name == regular.name and mode is None:
            raise OSError("content write and restoration refused")
        return real_write(entry, payload, mode, backup)
    state.write_runtime = refuse_content
    try:
        try:
            state.migrate_layout(repository, reverse=reverse)
        except RuntimeError as error:
            assert "content write and restoration refused" in str(error)
            assert "rollback errors" in str(error)
        else:
            raise AssertionError("content failure committed layout")
    finally:
        state.write_runtime = real_write
    assert (os.readlink(source_link), source_link.lstat().st_ino) == before_link
    assert source_link.resolve() == external
    assert ((source / regular.name).read_bytes(), (source / regular.name).stat().st_ino) == before_regular
    assert not (destination / linked.name).is_symlink()
    assert not (destination / regular.name).exists()
    assert profiles.resolve("linked-config")[0] == external
    assert profiles.resolve("owned-config-first")[0] == source / regular.name
    assert (external.read_bytes(), external.stat().st_ino, external.stat().st_mtime_ns) == external_before
    profile_bytes = {path: path.read_bytes() for path in profiles.profile_dir().rglob("*.json")}
    real_save = profiles._save_locked
    saves = []
    def refuse_second(name, proposed, **kwargs):
        saves.append(name)
        if len(saves) == 2:
            raise OSError("linked-config profile publication refused")
        return real_save(name, proposed, **kwargs)
    profiles._save_locked = refuse_second
    try:
        try:
            state.migrate_layout(repository, reverse=reverse)
        except RuntimeError as error:
            assert "linked-config profile publication refused" in str(error), error
        else:
            raise AssertionError("profile failure committed linked config")
    finally:
        profiles._save_locked = real_save
    assert len(saves) == 2, saves
    assert (os.readlink(source_link), source_link.lstat().st_ino) == before_link
    assert ((source / regular.name).read_bytes(), (source / regular.name).stat().st_ino) == before_regular
    assert not (destination / linked.name).is_symlink()
    assert not (destination / regular.name).exists()
    assert {path: path.read_bytes() for path in profiles.profile_dir().rglob("*.json")} == profile_bytes
    assert (external.read_bytes(), external.stat().st_ino, external.stat().st_mtime_ns) == external_before
    state.migrate_layout(repository, reverse=reverse)
    moved_link = destination / linked.name
    assert moved_link.resolve() == external
    assert profiles.resolve("linked-config")[0] == external
    assert profiles.resolve("owned-config-first")[0] == destination / regular.name
    assert profiles.read_run_config(moved_link)["exe"] == "/external/engine"
    assert (destination / regular.name).stat().st_ino == before_regular[1]
    assert (external.read_bytes(), external.stat().st_ino, external.stat().st_mtime_ns) == external_before
''')

    def test_nonmodel_json_migrates_without_codec_or_script_rewrites(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import json
import setup
import strata_managed_state as state
repository = setup.ROOT.parent
payloads = {
    "strata-notes.json": json.dumps(["user note", str(repository / "models")], indent=4).encode(),
    "strata-truncated.json": b'{"user note": "cd ' + str(repository).encode() + b'\n',
    "strata-object-notes.json": json.dumps({"notes": str(repository / "models"), "exe": "not a model without args"}, indent=4).encode(),
    "strata-empty-exe.json": json.dumps({"exe": "", "args": [], "notes": str(repository / "models")}, indent=4).encode(),
    "strata-string-args.json": json.dumps({"exe": str(repository / "engine/strata"), "args": "user note"}, indent=4).encode(),
}
identities = {}
for name, payload in payloads.items():
    path = repository / name
    path.write_bytes(payload)
    identities[name] = (path.stat().st_ino, path.stat().st_mtime_ns)
for reverse in (False, True):
    state.migrate_layout(repository, reverse=reverse)
    destination = repository if reverse else setup.ROOT
    for name, payload in payloads.items():
        path = destination / name
        assert path.read_bytes() == payload
        assert (path.stat().st_ino, path.stat().st_mtime_ns) == identities[name]
        assert not setup.model_config(path)
''')

    def test_independent_sycl_transport_only_rebases_actual_moved_references(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import json
import setup
import strata_managed_state as state
from strata_control.cfg_paths import engine_argument_path
repository = setup.ROOT.parent
external = repository.parent / "independent"
(external / "models").mkdir(parents=True)
weights = external / "models/weights.gguf"
weights.write_bytes(b"independent weights")
(repository / "packs").mkdir()
(repository / "packs/index.txt").write_bytes(b"managed pack")
config = {
    "exe": str(external / "sycl/serve/strata-sycl.sh"),
    "cwd": str(external),
    "args": ["--native", "/work/independent/models/weights.gguf", "--pack", str(repository / "packs"), "--untouched", str(repository / "python/not-moved")],
    "env": {"STRATA_SYCL_ROOT": str(repository.parent), "STRATA_SYCL_CWD": "/work/independent", "STRATA_SYCL_BIN": "build-sycl-aot/strata", "STRATA_SYCL_HERE": str(external)},
    "tokenizer": "/fixture/tokenizer",
}
assert state.normalize_sycl_config(config, repository) is config
source_path = repository / "strata-independent.json"
source_path.write_text(json.dumps(config, indent=4))
# A second config already at destination must use the identical ownership policy.
destination_path = setup.ROOT / "strata-independent-existing.json"
destination_path.write_text(json.dumps(config, indent=4))
for reverse in (False, True):
    if reverse:
        # Avoid a genuine source/destination filename conflict on reverse.
        destination_path = setup.ROOT / destination_path.name
    state.migrate_layout(repository, reverse=reverse)
    destination = repository if reverse else setup.ROOT
    for name in (source_path.name, destination_path.name):
        changed = json.loads((destination / name).read_bytes())
        assert changed["exe"] == config["exe"]
        assert changed["cwd"] == config["cwd"]
        assert changed["env"] == config["env"]
        assert changed["args"][1] == config["args"][1]
        assert changed["args"][3] == str(destination / "packs")
        assert changed["args"][5] == config["args"][5]
        assert engine_argument_path(changed["args"][1], changed["exe"], changed).read_bytes() == b"independent weights"
        assert (engine_argument_path(changed["args"][3], changed["exe"], changed) / "index.txt").read_bytes() == b"managed pack"
''')

    def test_native_managed_runtime_layout_renames_and_inverse_preserve_payload_identity(self):
        self.state = self.base / "native runtime's workspace with spaces"
        root = self.prepare(self.old)
        repository = root.parent
        retained = self.make_local_runtime(repository)
        config = repository / "strata-layout.json"
        original = {"exe": str(repository / "engine/strata"), "cwd": str(repository),
                    "args": ["--native", str(repository / "models/model.gguf")],
                    "helper": str(repository / "sycl/serve/strata-sycl.sh"), "custom": "preserved"}
        config.write_text(json.dumps(original))
        paths = {"engine/strata": b"current payload", "engine/.previous/strata": b"previous payload",
                 "models/model.gguf": b"model", "build/user-cache": b"cache"}
        identity = {}
        for name, data in paths.items():
            path = repository / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            identity[name] = (path.stat().st_dev, path.stat().st_ino)
        approval = repository / ".git/strata-engine-rollback.json"
        approval.write_text("old path approval")
        self.assertEqual(self.prepare(self.old), root)
        self.assertFalse(approval.exists())
        self.assert_local_runtime(root, retained)
        for name, data in paths.items():
            path = root / name
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity[name])
        moved = json.loads((root / config.name).read_text())
        self.assertEqual(moved["exe"], str(root / "engine/strata"))
        self.assertEqual(moved["cwd"], str(root))
        self.assertEqual(moved["helper"], str(repository / "engine/sycl/serve/strata-sycl.sh"))
        self.run_source_script(root, """
import json, os
import setup
import strata_managed_state
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(setup.ROOT.parent.parent)})
strata_managed_state.migrate_layout(setup.ROOT.parent, reverse=True)
""")
        self.assertEqual(json.loads(config.read_text()), original)
        self.assert_local_runtime(repository, retained)
        for name, data in paths.items():
            path = repository / name
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity[name])
        # Existing destinations are never replaced, including during a same-pin resume.
        (root / config.name).write_text("user-owned destination")
        result = subprocess.run(self.command(self.old), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((root / config.name).read_text(), "user-owned destination")
        self.assertEqual(json.loads(config.read_text()), original)

    def test_handover_recognizes_flat_and_terminal_checkouts_but_runs_independent_bundle(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import json, os, shutil
from pathlib import Path
from strata_cli import handover
components = Path.cwd().parent.parent / "components"
target = components / "control/new"
(target / "strata_control").mkdir(parents=True)
handover.bundled_python(target).parent.mkdir(parents=True)
handover.bundled_python(target).symlink_to(__import__("sys").executable)
(target / "strata.py").write_text("raise SystemExit(23)\n")
(target / "VERSION").write_text("9.0.0")
(target.parent / "active.json").write_text(json.dumps({"folder": "new"}))
env = dict(os.environ, STRATA_COMPONENTS_DIR=str(components))
env.pop(handover.ENV_OFF, None)
env.pop(handover.ENV_GUARD, None)
env.pop(handover.ENV_CHECKOUT, None)
calls = []
def execute(python, command, child_env):
    import subprocess
    calls.append(subprocess.run(command, env=child_env).returncode)
original = handover.__file__
for terminal in (False, True):
    checkout = Path.cwd().parent.parent / ("flat-checkout" if not terminal else "split-checkout")
    (checkout / ".git").mkdir(parents=True)
    (checkout / "engine").mkdir()
    shutil.copyfile(Path.cwd().parent / "engine/CMakeLists.txt", checkout / "engine/CMakeLists.txt")
    module = checkout / ("terminal/strata_cli" if terminal else "strata_cli") / "handover.py"
    module.parent.mkdir(parents=True)
    shutil.copyfile(original, module)
    handover.__file__ = str(module)
    assert handover.running_from_checkout()
    assert handover.maybe_hand_over(["--version"], environ=env, running="0.1.0", execv=execute) is None
    assert calls == []
bundle = Path.cwd().parent.parent / "independent/strata_cli/handover.py"
bundle.parent.mkdir(parents=True)
shutil.copyfile(original, bundle)
handover.__file__ = str(bundle)
assert not handover.running_from_checkout()
handover.maybe_hand_over(["--version"], environ=env, running="0.1.0", execv=execute)
assert calls == [23], calls
''')

    @unittest.skipUnless(os.name == "posix", "SYCL shell autostart")
    def test_sycl_autostart_consumes_real_script_from_setup_home(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import importlib.util, json, os, subprocess
from pathlib import Path
import setup as S
path = S.ROOT.parent / "engine/sycl/setup_intel.py"
spec = importlib.util.spec_from_file_location("intel", path)
intel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intel)
intel.intel_devices = lambda: ([{"driver": "xe", "devid": "e223", "vram_gb": 32}], [])
intel.sycl_engine = lambda: (Path("/fixture/strata"), None)
intel.sycl_version = lambda: "fixture"
S.ram_gb = lambda: 64
cfg = S.home() / "strata-fixture.json"
cfg.write_text(json.dumps({"backend": "sycl", "args": []}))
script = S.write_run_script("fixture", cfg, 9123, False)
assert script.parent == S.home()
observed = S.home() / "autostart-observed.json"
(S.ROOT / "serve/server.py").write_text("import json, os, sys\nfrom pathlib import Path\n"
    + "Path(" + repr(str(observed)) + ").write_text(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n")
def main():
    S.start(cfg)
    return 0
S.main = main
def execute(binary, argv):
    assert binary == "/bin/sh"
    subprocess.run(argv, check=True)
intel.os.execv = execute
try:
    intel.install([])
except SystemExit as error:
    assert error.code == 0
actual = json.loads(observed.read_text())
assert Path(actual["cwd"]).resolve() == S.ROOT
assert actual["args"] == ["--engine", "strata", "--config", str(cfg), "--port", "9123"]
''')

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "SYCL Bash recorder, no Docker or GPU")
    def test_sycl_default_data_mount_custom_mount_and_selected_binary_use_actual_shell(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r"""
import importlib.util, json, os, shlex, subprocess, sys
from pathlib import Path
from types import SimpleNamespace
import setup as S
repository = S.ROOT.parent
os.environ.pop("STRATA_SYCL_ROOT", None)
spec = importlib.util.spec_from_file_location("intel_mount_fixture", repository / "engine/sycl/setup_intel.py")
intel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intel)
data, _ = S.data_folder_for(SimpleNamespace(yes=True))
assert data == repository.parent / "Strata-data", data
assert not data.is_relative_to(repository)
assert intel.MOUNT == repository.parent
assert intel.sycl_path(data) == "/work/Strata-data"
docker = repository.parent / "docker-recorder/docker"
docker.parent.mkdir()
record = docker.parent / "arguments.json"
docker.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\n"
    + "if sys.argv[1] == 'run': Path(" + repr(str(record)) + ").write_text(json.dumps(sys.argv[1:]))\n")
docker.chmod(0o700)
wrapper = repository / "engine/sycl/serve/strata-sycl.sh"
for mount in (None, repository.parent.parent, repository):
    actual_mount = repository.parent if mount is None else mount
    if mount is None:
        os.environ.pop("STRATA_SYCL_ROOT", None)
    else:
        os.environ["STRATA_SYCL_ROOT"] = str(mount)
    spec.loader.exec_module(intel)
    assert intel.MOUNT == actual_mount
    selected_data = data if data.is_relative_to(actual_mount) else repository / "custom-data"
    selected_data.mkdir(exist_ok=True)
    data_argument = intel.sycl_path(selected_data)
    for binary in ("build-sycl-aot/chosen strata", "/work/custom binaries/chosen strata"):
        env = dict(os.environ, PATH=str(docker.parent) + os.pathsep + os.environ["PATH"], STRATA_SYCL_BIN=binary)
        env.pop("STRATA_SYCL_ROOT", None)
        if mount is not None:
            env["STRATA_SYCL_ROOT"] = str(mount)
        subprocess.run(["bash", str(wrapper), "--native", data_argument, "value's spaces"],
                       cwd=repository.parent.parent, env=env, check=True, capture_output=True, text=True)
        argv = json.loads(record.read_text())
        actual_mount = repository.parent if mount is None else mount
        assert str(actual_mount) + ":/work" in argv, argv
        tokens = shlex.split(argv[-1])
        expected_cwd = "/work/" + (repository / "engine").relative_to(actual_mount).as_posix()
        assert tokens[:4] == ["cd", expected_cwd, "&&", "exec"], tokens
        assert tokens[4:] == [binary, "--native", data_argument, "value's spaces"], tokens
""")

    def test_native_layout_preserves_profiles_and_reuses_external_marks(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import json, os
import setup
import strata_managed_state
from strata_control import profiles
repository = setup.ROOT.parent
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(repository.parent)})
source = repository / "strata-profile.json"
other = repository.parent / "other-install/strata-profile.json"
other.parent.mkdir()
config = {"exe": "/fixture/engine", "tokenizer": "/fixture/tokenizer", "args": []}
source.write_text(json.dumps(config))
other.write_text(json.dumps(config))
for name, path in (("managed", source), ("independent", other)):
    profiles.create(name, str(path))
    profiles.set_values(name, ["port=9123", "parallel=3"])
independent = profiles.load("independent")
initial, initial_revision = profiles.load("managed")
profiles.set_values("managed", ["port=9234"])
updated, updated_revision = profiles.load("managed")
profiles.rollback("managed", initial_revision)
assert profiles.load("managed")[0]["overrides"] == initial["overrides"]
immutable = {p: (p.read_bytes(), p.stat().st_mtime_ns)
             for p in (profiles.profile_dir() / ".history").rglob("*.json")}
external = repository.parent / "external/model.gguf"
external.parent.mkdir()
external.write_bytes(b"complete external weights")
setup.ROOT = repository
setup._OWN_DIRS = {external.parent.resolve()}
setup.mark(external, "verified external weights")
identity = setup._kept_mark(external).stat().st_ino
setup.ROOT = repository / "terminal"
for reverse in (False, True, False):
    strata_managed_state.migrate_layout(repository, reverse=reverse)
    for target, expected in ((updated_revision, updated), (initial_revision, initial)):
        profiles.rollback("managed", target)
        assert profiles.load("managed")[0]["overrides"] == expected["overrides"]
    for path, original in immutable.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original
        assert profiles._revision(path.read_bytes()) == path.stem
    destination = source if reverse else setup.ROOT / source.name
    resolved, profile, revision = profiles.resolve("managed")
    assert resolved == destination, (resolved, destination)
    assert profiles.read_run_config(resolved)["args"] == []
    assert profile["overrides"] == {"port": 9123, "parallel": 3}
    assert profiles.load("independent") == independent
    saved_root = setup.ROOT
    setup.ROOT = repository if reverse else repository / "terminal"
    assert setup.done(external)
    assert setup.mark_text(external) == "verified external weights"
    assert setup._kept_mark(external).stat().st_ino == identity
    setup.ROOT = saved_root
''')

    def test_native_split_sycl_normalization_preserves_actual_default_mount_and_binary(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import json
from pathlib import Path
import strata_managed_state as state
from strata_control.cfg_paths import engine_binary, engine_argument_path
repository = Path.cwd().parent
wrapper = repository / "engine/sycl/serve/strata-sycl.sh"
data = repository.parent / "Strata-data"
data.mkdir()
model = data / "model.gguf"
model.write_bytes(b"existing payload")
binary = repository / "engine/build-sycl-aot/strata"
binary.parent.mkdir()
binary.write_bytes(b"selected engine")
config = {"backend": "sycl", "exe": str(wrapper), "args": ["--native", "/work/Strata-data/model.gguf"], "env": {}}
first = state.normalize_sycl_config(config, repository)
assert Path(first["env"]["STRATA_SYCL_ROOT"]) == repository.parent
assert Path(engine_binary(first["exe"], first)) == binary
assert engine_argument_path(first["args"][1], first["exe"], first) == model
assert state.normalize_sycl_config(first, repository) == first
assert model.read_bytes() == b"existing payload"
''')

    def test_host_absolute_sycl_binary_under_work_is_not_decoded_as_container_argument(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
from pathlib import Path
import strata_managed_state as state
from strata_control.cfg_paths import engine_binary, engine_argument_path
repository = Path("/work/state/source")
selected = "/work/state/source/engine/build/strata"
config = {"backend": "sycl", "exe": str(state.DIRECTORY / "strata-sycl.sh"), "args": [],
          "env": {"STRATA_SYCL_HERE": str(repository / "engine"), "STRATA_SYCL_ROOT": "/work/state",
                  "STRATA_SYCL_CWD": "/work/source/engine", "STRATA_SYCL_BIN": selected}}
assert engine_binary(config["exe"], config) == selected
assert engine_argument_path("/work/source/models/pack", config["exe"], config) == repository / "models/pack"
for _ in range(2):
    config = state.sycl_config(config, repository / "terminal", repository / "terminal", repository, False, lambda value: value)
    assert config["env"]["STRATA_SYCL_BIN"] == selected
    assert engine_binary(config["exe"], config) == selected
''')

    @unittest.skipUnless(sys.platform == "darwin", "Historical Darwin selected runtime")
    def test_historical_selected_runtime_validator_uses_flat_engine_root(self):
        self.make_cross_pin_sources()
        root = self.prepare_cross_pin(self.old, overlay=False)
        (root / "requirements.txt").write_text("")
        self.make_runtime_model(root)
        (root / "engine/BUILD.json").write_text(json.dumps({"version": "0.1.46", "source": "prebuilt"}))
        (root / ".venv/bin").mkdir(parents=True)
        (root / ".venv/bin/python").symlink_to(sys.executable)
        result = subprocess.run([sys.executable, WORKSPACE, "--selected-runtime", str(root),
                                 str(root / "strata-fixture.json")], cwd=root, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_cmake_relocated_same_generator_is_fresh_and_matching_roots_are_noop(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import setup
build = setup.ROOT / "build"
build.mkdir()
payload = build / "user-cache"
payload.write_bytes(b"preserved payload")
identity = payload.stat().st_ino
cache = build / "CMakeCache.txt"
metadata = build / "CMakeFiles"
for source, cached_build, fresh in ((setup.ROOT.parent, build, True),
                                   (setup.ROOT.parent / "engine", setup.ROOT.parent / "build", True),
                                   (setup.ROOT.parent, setup.ROOT.parent / "build", True),
                                   (setup.ROOT.parent / "engine", build, False)):
    metadata.mkdir(exist_ok=True)
    (metadata / "fixture").write_text("metadata")
    cache.write_text("CMAKE_GENERATOR:INTERNAL=Ninja\n"
                     + f"CMAKE_HOME_DIRECTORY:INTERNAL={source}\n"
                     + f"CMAKE_CACHEFILE_DIR:INTERNAL={cached_build}\n")
    before = cache.read_bytes()
    assert setup.fresh_if_other_generator(build, "Ninja", src=setup.ROOT.parent / "engine") is fresh
    assert cache.exists() is (not fresh)
    assert metadata.exists() is (not fresh)
    if not fresh:
        assert cache.read_bytes() == before
    assert payload.read_bytes() == b"preserved payload"
    assert payload.stat().st_ino == identity
''')

    def test_source_overlay_replacement_at_same_revision_publishes_requested_delta(self):
        root = self.prepare(self.old)
        overlay = self.base / "replacement.patch"
        delta = "diff --git a/terminal/code.py b/terminal/code.py\n--- a/terminal/code.py\n+++ b/terminal/code.py\n@@ -1 +1 @@\n-old source\n+overlay A\n"
        env = dict(self.env, TEST_SOURCE_PATCH=str(overlay))
        for value in ("A", "B"):
            overlay.write_text(Path(SOURCE_PATCH).read_bytes().decode("utf-8") + delta.replace("overlay A", "overlay " + value))
            result = subprocess.run(self.command(self.old), env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / "code.py").read_text(), "overlay " + value + "\n")
            self.assertEqual((root.parent / ".git/strata-source.patch").read_text(), overlay.read_text())

    def test_layout_checkpoint_restores_profiles_and_runtime_on_distinct_devices(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import errno, json, os
from pathlib import Path
from unittest.mock import patch
import strata_managed_state as state
repository = Path.cwd().parent
directory = repository.parent / "separate-profile-device"
directory.mkdir()
os.environ["STRATA_PROFILE_DIR"] = str(directory)
profile = directory / "independent.json"
profile.write_bytes(b"original profile")
metadata = directory / ".source-relocations.json"
metadata.write_bytes(b"original mapping")
config = Path.cwd() / "strata-checkpoint.json"
config.write_bytes(b"original config")
files = (profile, metadata, config)
before = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mode) for p in files}
native_lstat, native_link = Path.lstat, os.link
def device_stat(path, *args, **kwargs):
    result = list(native_lstat(path, *args, **kwargs))
    result[2] = 2 if path.is_relative_to(directory) else 1
    return os.stat_result(result)
def link(source, destination, *args, **kwargs):
    source, destination = Path(source), Path(destination)
    if source.is_relative_to(directory) != destination.is_relative_to(directory):
        raise OSError(errno.EXDEV, "cross-device link")
    return native_link(source, destination, *args, **kwargs)
with patch.object(Path, "lstat", device_stat), patch.object(os, "link", link):
    with state.layout_checkpoint(repository) as restore:
        replacement = directory / "replacement"
        replacement.write_bytes(b"replacement profile")
        os.replace(replacement, profile)
        metadata.write_bytes(b"changed mapping")
        config.write_bytes(b"changed config")
        restore()
    # Success cleanup also removes temporary links from the profiles' device.
    with state.layout_checkpoint(repository):
        pass
for path, expected in before.items():
    assert (path.read_bytes(), path.stat().st_ino, path.stat().st_mode) == expected
assert not list(directory.glob("strata-layout-*"))
assert not list((repository / ".git").glob("strata-layout-*"))
assert "STRATA_PROFILE_NAMESPACE_FD" not in os.environ
''')

    def test_sycl_numeric_mtp_depth_survives_forward_reverse_and_normalization(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
from pathlib import Path
import strata_managed_state as state
from strata_control.cfg_paths import engine_argument_path
repository = Path.cwd().parent
wrapper = repository / "engine/sycl/serve/strata-sycl.sh"
mount = repository.parent
for depth in ("0", "2", "12"):
    cfg = {"backend": "sycl", "exe": str(wrapper), "args": ["--mtp", depth, "--pack", "/work/source/packs/model"],
           "env": {"STRATA_SYCL_HERE": str(repository), "STRATA_SYCL_ROOT": str(mount),
                   "STRATA_SYCL_CWD": "/work/source", "STRATA_SYCL_BIN": str(repository / "engine/strata")}}
    forward = state.sycl_config(cfg, repository, repository / "terminal", repository, False,
                                state.rebaser({(repository / "packs", repository / "terminal/packs")}))
    assert forward["args"][:2] == ["--mtp", depth]
    assert engine_argument_path(forward["args"][3], forward["exe"], forward) == repository / "terminal/packs/model"
    assert state.normalize_sycl_config(forward, repository)["args"][:2] == ["--mtp", depth]
    reverse = state.sycl_config(forward, repository / "terminal", repository, repository, True,
                                state.rebaser({(repository / "terminal/packs", repository / "packs")}))
    assert reverse["args"][:2] == ["--mtp", depth]
    assert engine_argument_path(reverse["args"][3], reverse["exe"], reverse) == repository / "packs/model"
''')

    def test_relative_runtime_links_preserve_external_moved_and_dangling_targets_on_failure_and_reverse(self):
        self.make_cross_pin_sources()
        self.env["STRATA_PROFILE_DIR"] = str(self.base / "relative profiles' namespace")
        root = self.prepare_cross_pin(self.new, overlay=False)
        external = root.parent.parent / "external runtime's payload"
        external.mkdir()
        self.make_local_runtime(external)
        self.run_source_script(root, r'''
import json, os, subprocess, sys
from pathlib import Path
import setup
import strata_managed_state as state
from strata_control import profiles
from strata_control.cfg_paths import engine_argument_path
repository = setup.ROOT.parent
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(repository.parent)})
external = repository.parent / "external runtime's payload"
shared = repository.parent / "shared models' payload"
shared.mkdir()
(shared / "weights.gguf").write_bytes(b"external model bytes")
(repository / "models").symlink_to(os.path.relpath(shared, repository), target_is_directory=True)
(repository / ".venv").symlink_to(os.path.relpath(external / ".venv", repository), target_is_directory=True)
(repository / "packs").mkdir()
(repository / "packs/index.txt").write_bytes(b"migrated pack bytes")
(repository / "mtp").symlink_to("packs", target_is_directory=True)
missing = repository.parent / "missing models' target"
(repository / "marks").symlink_to(os.path.relpath(missing, repository), target_is_directory=True)
(repository / "build-sycl-aot").mkdir()
(repository / "build-sycl-aot/interpreter").symlink_to(sys.executable)
(repository / "python/bin").mkdir(parents=True)
(repository / "python/bin/python3").symlink_to("../../build-sycl-aot/interpreter")
config = repository / "strata-relative.json"
config.write_text(json.dumps({"exe": str(repository / "python/bin/python3"), "cwd": str(repository),
                              "tokenizer": "/fixture/tokenizer",
                              "args": ["--native", str(repository / "models/weights.gguf"),
                                       "--pack", str(repository / "mtp")]}))
for name in ("relative-first", "relative-second"):
    profiles.create(name, str(config))
    profiles.set_values(name, ["port=9123"])
external_bytes = {path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino)
                  for base in (external, shared) for path in base.rglob("*") if path.is_file()}
payload_inode = (repository / "packs/index.txt").stat().st_ino
link_names = ("models", ".venv", "mtp", "marks", "python/bin/python3")
original_links = {name: os.readlink(repository / name) for name in link_names}
for reverse in (False, True):
    source, target = (setup.ROOT, repository) if reverse else (repository, setup.ROOT)
    links = {name: (os.readlink(source / name), (source / name).lstat().st_ino) for name in link_names}
    current = {path: path.read_bytes() for path in profiles.profile_dir().rglob("*.json")}
    history = {path: (path.read_bytes(), path.stat().st_mtime_ns)
               for path in (profiles.profile_dir() / ".history").rglob("*.json")}
    before_config = (source / config.name).read_bytes()
    real_save = profiles._save_locked
    saves = []
    def refuse_second(name, proposed, **kwargs):
        saves.append(name)
        if len(saves) == 2:
            raise OSError("relative-link profile publication refused")
        return real_save(name, proposed, **kwargs)
    profiles._save_locked = refuse_second
    try:
        try:
            state.migrate_layout(repository, reverse=reverse)
        except RuntimeError as error:
            assert "relative-link profile publication refused" in str(error), error
        else:
            raise AssertionError("a failed publication committed relative links")
    finally:
        profiles._save_locked = real_save
    assert len(saves) == 2, saves
    assert (source / config.name).read_bytes() == before_config
    assert {path: path.read_bytes() for path in profiles.profile_dir().rglob("*.json")} == current
    for path, before in history.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    for name, before in links.items():
        assert (os.readlink(source / name), (source / name).lstat().st_ino) == before, name
        assert not (target / name).exists() and not (target / name).is_symlink(), name
    state.migrate_layout(repository, reverse=reverse)
    resolved, profile, revision = profiles.resolve("relative-first")
    assert resolved == target / config.name, (resolved, target)
    cfg = profiles.read_run_config(resolved)
    assert engine_argument_path(cfg["args"][1], cfg["exe"], cfg).read_bytes() == b"external model bytes"
    assert (engine_argument_path(cfg["args"][3], cfg["exe"], cfg) / "index.txt").read_bytes() == b"migrated pack bytes"
    assert (target / "models").resolve() == shared
    assert (target / ".venv").resolve() == external / ".venv"
    assert (target / "mtp").resolve() == target / "packs"
    assert (target / "marks").is_symlink() and not (target / "marks").exists()
    assert (target / "marks").resolve() == missing
    assert (target / "packs/index.txt").stat().st_ino == payload_inode
    assert subprocess.check_output([str(target / "python/bin/python3"), "-c", "print('relative interpreter')"],
                                   text=True).strip() == "relative interpreter"
    assert subprocess.check_output([str(target / ".venv/bin/relocation-fixture")],
                                   text=True).strip() == "retained package"
    for path, before in external_bytes.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) == before, path
assert {name: os.readlink(repository / name) for name in link_names} == original_links
''')

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Native SYCL shell recorder, no Docker daemon")
    def test_real_cross_pin_sycl_repeated_dense_and_embedding_gguf_operands_preserve_numeric_mtp(self):
        self.make_cross_pin_sources()
        flat = self.prepare_cross_pin(self.old, overlay=False)
        payloads = {"models/native.gguf": b"native", "models/dense-1.gguf": b"dense one",
                    "models/dense-2.gguf": b"dense two", "models/embedding-1.gguf": b"embedding one",
                    "models/embedding-2.gguf": b"embedding two"}
        identities = {}
        for name, data in payloads.items():
            path = flat / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            identities[name] = (path.stat().st_dev, path.stat().st_ino)
        binary = flat / "build-sycl-aot/strata"
        binary.parent.mkdir()
        binary.write_bytes(b"selected SYCL engine")
        binary.chmod(0o700)
        operands = [("--native", "models/native.gguf"), ("--native-dense-gguf", "models/dense-1.gguf"),
                    ("--embd-gguf", "models/embedding-1.gguf"), ("--native-dense-gguf", "models/dense-2.gguf"),
                    ("--embd-gguf", "models/embedding-2.gguf")]
        argv = [item for flag, name in operands for item in (flag, "/work/source/" + name)]
        argv += ["--mtp", "2", "--prompt", "/work/source/models/keep literal"]
        config = flat / "strata-gguf-operands.json"
        config.write_text(json.dumps({"backend": "sycl", "exe": str(flat / "sycl/serve/strata-sycl.sh"),
                                     "cwd": str(flat), "env": {"STRATA_SYCL_BIN": "build-sycl-aot/strata"}, "args": argv}))
        docker = self.base / "gguf docker's recorder/docker"
        docker.parent.mkdir()
        record = docker.parent / "arguments.json"
        docker.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\n"
                          + "if sys.argv[1]=='run': Path(" + repr(str(record)) + ").write_text(json.dumps(sys.argv[1:]))\n")
        docker.chmod(0o700)
        def consume(root):
            cfg = json.loads((root / config.name).read_text())
            result = subprocess.run(["bash", cfg["exe"], *cfg["args"]], cwd=root,
                                    env=dict(self.env, PATH=str(docker.parent) + os.pathsep + self.env["PATH"], **cfg["env"]),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            command = json.loads(record.read_text())
            mount = Path(command[command.index("-v") + 1].removesuffix(":/work"))
            tokens = shlex.split(command[-1])
            actual = tokens[tokens.index("exec") + 2:]
            self.assertEqual(actual, cfg["args"])
            for index, (flag, name) in enumerate(operands):
                self.assertEqual(actual[index * 2], flag)
                host = mount / Path(actual[index * 2 + 1]).relative_to("/work")
                self.assertEqual(host.resolve(), (root / name).resolve())
                self.assertEqual(host.read_bytes(), payloads[name])
                self.assertEqual((host.stat().st_dev, host.stat().st_ino), identities[name])
            self.assertEqual(actual[-4:], ["--mtp", "2", "--prompt", "/work/source/models/keep literal"])
            self.run_source_script(root, "from pathlib import Path\nfrom serve.runconfig import load\n"
                + "from strata_control.cfg_paths import engine_argument_path\n"
                + "cfg=load(" + repr(str(root / config.name)) + ")\n"
                + "expected=" + repr([(flag, str(root / name)) for flag, name in operands]) + "\n"
                + "for i, (flag, path) in enumerate(expected):\n"
                + "    assert cfg['args'][i*2] == flag\n"
                + "    assert engine_argument_path(cfg['args'][i*2+1], cfg['exe'], cfg).resolve() == Path(path).resolve()\n"
                + "assert cfg['args'][-4:] == ['--mtp','2','--prompt','/work/source/models/keep literal']\n")
        consume(flat)  # Both extra flags start as valid container operands, not host-absolute auto-generation.
        split = self.prepare_cross_pin(self.new, overlay=False)
        consume(split)
        self.assertEqual(self.prepare_cross_pin(self.new, overlay=False), split)
        consume(split)
        self.assertEqual(self.prepare_cross_pin(self.old, overlay=False), flat)
        consume(flat)

    def test_real_forward_receipt_failure_restores_payload_metadata_and_retry(self):
        self.make_cross_pin_sources()
        flat = self.prepare_cross_pin(self.old)
        retained = self.make_local_runtime(flat)
        payloads = {"models/receipt.gguf": b"model payload", "engine/strata": b"engine payload",
                    "engine/.previous/strata": b"previous payload", "build/user-cache": b"cache payload",
                    "packs/receipt/index.txt": b"pack payload"}
        identity = {}
        for name, data in payloads.items():
            path = flat / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            identity[name] = (path.stat().st_dev, path.stat().st_ino)
        config = flat / "strata-receipt.json"
        config.write_text(json.dumps({"exe": str(flat / "engine/strata"), "cwd": str(flat),
                                     "tokenizer": "/fixture/tokenizer", "args": ["--native", "models/receipt.gguf"]}))
        self.env["STRATA_PROFILE_DIR"] = str(self.base / "receipt profiles")
        self.cross_pin_cli(self.old, "profile", "create", "receipt", "--from-config", str(config), "--output", "json")
        self.cross_pin_cli(self.old, "profile", "set", "receipt", "port=9123", "--output", "json")
        result = subprocess.run([sys.executable, "-c", "import setup; setup.write_run_script('receipt', "
            + repr(str(config)) + ", 9123, False); setup.WIN=True; setup.write_run_script('receipt', "
            + repr(str(config)) + ", 9123, False)"], cwd=flat, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        approval = flat / ".git/strata-engine-rollback.json"
        runner = r"""
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('workspace', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
root = Path(sys.argv[2])
if sys.argv[3] == 'approval':
    (root / '.git/strata-engine-rollback.json').write_text(json.dumps({'revision': sys.argv[4],
        'engines': {'engine': {'files': module.engine_identity(root / 'engine'), 'sources': {}}}}) + '\n')
elif sys.argv[3] == 'validate-approval':
    saved = json.loads((root / '.git/strata-engine-rollback.json').read_text())
    assert saved['revision'] == sys.argv[4], 'approval revision was not restored'
    assert 'engine' in saved['engines'], 'approved engine was dropped'
    assert saved['engines']['engine']['files'] == module.engine_identity(root / 'engine'), 'approval identity is stale'
    assert module.engine_rollbacks(root, sys.argv[4]) == saved['engines'], 'restored approval is not accepted'
else:
    publish = module.publish_source_patch
    def fault(path, text):
        if path.name == module.SOURCE_REQUEST:
            assert (root / 'terminal/models/receipt.gguf').read_bytes() == b'model payload'
            raise OSError('receipt publication after accepted forward migration')
        return publish(path, text)
    module.publish_source_patch = fault
    try:
        module.prepare_workspace(sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    except OSError as error:
        assert str(error) == 'receipt publication after accepted forward migration'
    else:
        raise AssertionError('receipt fault did not fire')
"""
        result = subprocess.run([sys.executable, "-c", runner, WORKSPACE, str(flat), "approval", self.old],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        profiles = Path(self.env["STRATA_PROFILE_DIR"])
        paths = [config, flat / "run-receipt.sh", flat / "run-receipt.bat", approval,
                 flat / ".git/strata-source.patch", flat / ".git/strata-source-request.json"]
        paths += list(profiles.rglob("*.json"))
        paths += [flat / ".venv/pyvenv.cfg", flat / ".python/bin/python", flat / ".python/lib"]
        paths += [path for path in (flat / ".venv/bin").iterdir() if path.is_file() or path.is_symlink()]
        def snapshot(path):
            data = os.readlink(path) if path.is_symlink() else path.read_bytes()
            info = path.lstat()
            return (data, info.st_dev, info.st_ino)
        before = {path: snapshot(path) for path in paths}
        result = subprocess.run([sys.executable, "-c", runner, WORKSPACE, str(flat), str(self.state),
                                 self.new, str(self.repository), SOURCE_PATCH], env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Cannot restore source transaction", result.stderr)
        self.assertEqual(subprocess.check_output(["git", "-C", str(flat), "rev-parse", "HEAD"], text=True).strip(), self.old)
        self.assertFalse((flat / "terminal/setup.py").exists())
        for path in paths:
            after = snapshot(path)
            self.assertEqual(after[1:], before[path][1:], f"Restored device/inode differs: {path}")
            if path != approval:
                self.assertTrue(after[0] == before[path][0], f"Restored bytes/link target differ: {path}")
        # Checkout refreshes tracked engine-source mtimes; approvals must attest those real identities.
        result = subprocess.run([sys.executable, "-c", runner, WORKSPACE, str(flat), "validate-approval", self.old],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(profiles.rglob("*.json")), {path for path in paths if path.is_relative_to(profiles)})
        for name, data in payloads.items():
            path = flat / name
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity[name])
            self.assertFalse((flat / "terminal" / name).exists())
        self.assert_local_runtime(flat, retained)
        self.assertTrue(self.cross_pin_cli(self.old, "profile", "history", "receipt", "--output", "json")["ok"])
        split = self.prepare_cross_pin(self.new)
        self.assertEqual(split, flat / "terminal")
        self.assert_local_runtime(split, retained)
        for name, data in payloads.items():
            self.assertEqual((split / name).read_bytes(), data)
            self.assertEqual(((split / name).stat().st_dev, (split / name).stat().st_ino), identity[name])
        self.assertTrue(self.cross_pin_cli(self.new, "profile", "history", "receipt", "--output", "json")["ok"])

    def test_relative_sycl_launchers_use_config_coordinates_outside_process_cwd(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import json
import os
from pathlib import Path
import setup
import strata_managed_state as state
from strata_control.cfg_paths import engine_argument_path, engine_binary
repository = setup.ROOT.parent
outside = repository.parent / "ambient-directory"
outside.mkdir()
os.chdir(outside)
external = repository.parent / "independent-relative"
external.mkdir()
external_config = {"exe": "sycl/serve/strata-sycl.sh", "cwd": str(external),
                   "args": ["--native", "/work/independent-relative/model.gguf"], "env": {}}
assert state.normalize_sycl_config(external_config, repository) is external_config
# Old and current wrapper spellings share the same explicit launch coordinates.
for exe in ("sycl/serve/strata-sycl.sh", "engine/sycl/serve/strata-sycl.sh"):
    config = {"exe": exe, "cwd": str(repository),
              "args": ["--native", "/work/" + repository.name + "/model.gguf"],
              "env": {"STRATA_SYCL_ROOT": ".."}}
    normalized = state.normalize_sycl_config(config, repository)
    assert normalized["exe"] == str(state.DIRECTORY / "strata-sycl.sh")
    assert normalized["env"]["STRATA_SYCL_ROOT"] == str(repository.parent)
    assert engine_argument_path(normalized["args"][1], normalized["exe"], normalized) == repository / "model.gguf"
    assert state.normalize_sycl_config(normalized, repository) == normalized
# A native doctor file without cwd uses its known config directory, not ambient cwd.
config = {"exe": "../engine/sycl/serve/strata-sycl.sh", "args": [], "env": {}}
normalized = state.normalize_sycl_config(config, repository, base=setup.ROOT)
assert normalized["exe"] == str(state.DIRECTORY / "strata-sycl.sh")
assert engine_binary(normalized["exe"], normalized) == str(repository / "engine/build-sycl-aot/strata")
assert state.normalize_sycl_config(normalized, repository) == normalized
# Migration supplies the parent of each actual config, including existing destination configs.
(repository / "models").mkdir()
(repository / "models/relative.gguf").write_bytes(b"relative payload")
managed = {"exe": "sycl/serve/strata-sycl.sh", "cwd": str(repository),
           "args": ["--native", "/work/" + repository.name + "/models/relative.gguf"],
           "env": {"STRATA_SYCL_ROOT": ".."}}
(repository / "strata-relative.json").write_text(json.dumps(managed))
(repository / "strata-external-relative.json").write_text(json.dumps(external_config))
(setup.ROOT / "strata-relative-existing.json").write_text(json.dumps(config))
for reverse in (False, True):
    state.migrate_layout(repository, reverse=reverse)
    destination = repository if reverse else setup.ROOT
    changed = json.loads((destination / "strata-relative.json").read_text())
    argument = engine_argument_path(changed["args"][1], changed["exe"], changed)
    assert argument == destination / "models/relative.gguf"
    assert argument.read_bytes() == b"relative payload"
    assert changed["exe"] == str(state.DIRECTORY / "strata-sycl.sh")
    assert json.loads((destination / "strata-external-relative.json").read_text()) == external_config
    if reverse:
        # Reverse migration precedes checkout; normalization observes the returned flat source.
        marker = setup.ROOT / "setup.py"
        saved_marker = setup.ROOT / "setup.py.fixture-split"
        marker.rename(saved_marker)
        try:
            assert state.normalize_sycl_config(changed, repository) == changed
        finally:
            saved_marker.rename(marker)
    else:
        assert state.normalize_sycl_config(changed, repository) == changed
    existing = json.loads((destination / "strata-relative-existing.json").read_text())
    assert existing["exe"] == str(state.DIRECTORY / "strata-sycl.sh")
''')

    def test_real_flat_to_split_invalid_destination_transport_restores_entire_source_transaction(self):
        self.make_cross_pin_sources()
        flat = self.prepare_cross_pin(self.old)
        retained = self.make_local_runtime(flat)
        payloads = {"models/retained.gguf": b"retained model", "engine/strata": b"approved current engine",
                    "engine/.previous/strata": b"approved previous engine", "build/user-cache": b"user cache"}
        identities = {}
        for name, data in payloads.items():
            path = flat / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            identities[name] = (path.stat().st_dev, path.stat().st_ino)
        config = flat / "strata-transaction.json"
        config.write_text(json.dumps({"exe": str(flat / "engine/strata"), "cwd": str(flat),
                                     "tokenizer": "/fixture/tokenizer", "args": ["--native", "models/retained.gguf"]}))
        self.env["STRATA_PROFILE_DIR"] = str(self.base / "transaction profiles' history")
        self.cross_pin_cli(self.old, "profile", "create", "transaction", "--from-config", str(config), "--output", "json")
        self.cross_pin_cli(self.old, "profile", "set", "transaction", "port=9123", "--output", "json")
        profiles = Path(self.env["STRATA_PROFILE_DIR"])
        metadata = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in profiles.rglob("*.json")}
        ledger = flat / ".git/strata-source.patch"
        previous_ledger = ledger.read_bytes()
        receipts = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in (flat / ".git/strata-source-patches").iterdir()}
        marker = flat / ".git/strata-runtime-revision"
        marker.write_text(self.old + "\n")
        approval = flat / ".git/strata-engine-rollback.json"
        script = "import importlib.util,json; from pathlib import Path; "
        script += "spec=importlib.util.spec_from_file_location('workspace', " + repr(WORKSPACE) + "); "
        script += "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        script += "Path(" + repr(str(approval)) + ").write_text(json.dumps({'revision':" + repr(self.old)
        script += ", 'engines':{'engine':{'files':module.engine_identity(Path(" + repr(str(flat / "engine"))
        script += ")), 'sources':{}}}})+'\\n')"
        result = subprocess.run([sys.executable, "-c", script], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        old_approval = json.loads(approval.read_text())
        source_files = {flat / name: (flat / name).read_bytes() for name in ("setup.py", "strata.py", "strata_cli/cli.py")}
        old_config = config.read_bytes()
        invalid = flat / "terminal/strata-invalid-sycl.json"
        invalid.parent.mkdir()
        invalid.write_text(json.dumps({"backend": "sycl", "exe": str(WORKSPACE_LIB / "strata-sycl.sh"), "args": [],
            "env": {"STRATA_SYCL_HERE": str(flat / "engine"), "STRATA_SYCL_ROOT": str(flat.parent),
                    "STRATA_SYCL_CWD": "/work/../outside"}}))
        bad_bytes, bad_inode = invalid.read_bytes(), invalid.stat().st_ino
        result = subprocess.run(self.command(self.new), env=self.env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STRATA_SYCL_CWD", result.stderr)
        self.assertEqual(subprocess.check_output(["git", "-C", str(flat), "rev-parse", "HEAD"], text=True).strip(), self.old)
        self.assertEqual(ledger.read_bytes(), previous_ledger)
        subprocess.run(["git", "-C", str(flat), "apply", "--reverse", "--check", "-"],
                       input=previous_ledger, env=self.env, capture_output=True, check=True)
        self.assertEqual(marker.read_text(), self.old + "\n")
        self.assertEqual(json.loads(approval.read_text()), old_approval)
        self.assertEqual(config.read_bytes(), old_config)
        self.assertEqual((invalid.read_bytes(), invalid.stat().st_ino), (bad_bytes, bad_inode))
        self.assertFalse((flat / "terminal/setup.py").exists())
        for path, data in source_files.items():
            self.assertEqual(path.read_bytes(), data)
        for name, data in payloads.items():
            path = flat / name
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), identities[name])
            self.assertFalse((flat / "terminal" / name).exists())
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in profiles.rglob("*.json")}, metadata)
        for path, before in receipts.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assert_local_runtime(flat, retained)
        # A new interpreter consumes the returned old source API and CLI, never a cached current setup module.
        result = subprocess.run([sys.executable, "-c", "import setup\nfrom pathlib import Path\n"
            + "from strata_control import profiles\nassert setup.ROOT == Path(" + repr(str(flat)) + ")\n"
            + "assert Path(setup.__file__).read_bytes() == Path(" + repr(str(OLD_UPSTREAM_SOURCE / "setup.py")) + ").read_bytes()\n"
            + "assert (setup.ROOT/'models/retained.gguf').read_bytes() == b'retained model'\n"
            + "assert profiles.resolve('transaction')[0] == setup.ROOT/'strata-transaction.json'\n"
            + "import importlib.util\nspec=importlib.util.spec_from_file_location('restored_workspace', " + repr(WORKSPACE) + ")\n"
            + "workspace=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(workspace)\n"
            + "assert workspace.engine_rollbacks(setup.ROOT," + repr(self.old) + ") == " + repr(old_approval["engines"]) + "\n"],
            cwd=flat, env=dict(self.env, STRATA_MANAGED_SOURCE=str(flat)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.cross_pin_cli(self.old, "profile", "history", "transaction", "--output", "json")["ok"])

    def test_real_cross_pin_transitions_preserve_runtime_profiles_scripts_and_old_consumer_history(self):
        self.make_cross_pin_sources()
        state = self.state
        profiles_dir = self.base / "cross-profiles"
        self.env["STRATA_PROFILE_DIR"] = str(profiles_dir)
        recorder = self.base / "script-consumer.py"
        observed = self.base / "script-observed.json"
        recorder.write_text("import json, os, sys\nfrom pathlib import Path\n"
            + "cfg=json.loads(Path(sys.argv[sys.argv.index('--config')+1]).read_text())\n"
            + "pack=Path(cfg['args'][cfg['args'].index('--pack')+1]) / 'index.txt'\n"
            + "Path(" + repr(str(observed)) + ").write_text(json.dumps({'cwd':os.getcwd(),'pack':pack.read_text()}))\n")
        for mode in ("accepted", "native", "interrupted", "removed"):
            with self.subTest(mode=mode):
                self.state = state / mode
                overlay = mode != "native"
                flat = self.prepare_cross_pin(self.old, overlay=overlay)
                self.assertFalse((flat / "terminal/setup.py").exists())
                self.assertEqual((flat / "setup.py").read_bytes(), (OLD_UPSTREAM_SOURCE / "setup.py").read_bytes())
                ledger = flat / ".git/strata-source.patch"
                old_ledger = ledger.read_bytes() if overlay else None
                old_receipts = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                                for p in (flat / ".git/strata-source-patches").glob("*")}
                retained = self.make_local_runtime(flat)
                payloads = {"engine/strata": b"old engine", "engine/.previous/strata": b"previous engine",
                            "build/user-cache": b"unrelated cache", "models/model.gguf": b"model payload",
                            "packs/fixture/index.txt": b"relative pack payload"}
                identity = {}
                for name, payload in payloads.items():
                    path = flat / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
                    identity[name] = (path.stat().st_dev, path.stat().st_ino)
                config = flat / "strata-cross.json"
                config.write_text(json.dumps({"exe": str(flat / "engine/strata"), "tokenizer": "/fixture/tokenizer",
                    "args": ["--pack", "packs/fixture", "--native", "models/model.gguf"]}))
                name = "cross-" + mode
                self.cross_pin_cli(self.old, "profile", "create", name, "--from-config", str(config), "--output", "json", overlay=overlay)
                self.cross_pin_cli(self.old, "profile", "set", name, "port=9123", "--output", "json", overlay=overlay)
                def generate_script(root):
                    script = "import setup; setup.write_run_script('cross', " + repr(str(root / config.name)) + ", 9123, False); "
                    script += "setup.WIN=True; setup.write_run_script('cross', " + repr(str(root / config.name)) + ", 9123, False)"
                    result = subprocess.run([sys.executable, "-c", script], cwd=root, env=self.env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    path = root / "run-cross.sh"
                    path.write_bytes(path.read_bytes().replace(str(root / "serve/server.py").encode(), str(recorder).encode()))
                def consume_script(root):
                    result = subprocess.run(["sh", str(root / "run-cross.sh")], cwd=self.base,
                                            env=self.env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(observed.read_text()), {"cwd": str(root), "pack": "relative pack payload"})
                    bat = (root / "run-cross.bat").read_bytes()
                    self.assertIn(('cd /d "' + str(root) + '"').encode() + b"\r\n", bat)
                    self.assertNotIn(b"\n", bat.replace(b"\r\n", b""))
                generate_script(flat)
                consume_script(flat)
                split = self.prepare_cross_pin(self.new, overlay=overlay)
                self.assertEqual(split, flat / "terminal")
                self.assert_local_runtime(split, retained)
                consume_script(split)
                generate_script(split)
                consume_script(split)
                changed = self.cross_pin_cli(self.new, "profile", "set", name, "port=9234", "--output", "json", overlay=overlay)
                split_revision = changed["previous_revision"]
                history = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (profiles_dir / ".history" / name).glob("*.json")}
                if mode == "removed":
                    overlay = False
                    self.assertEqual(self.prepare_cross_pin(self.new, overlay=False), split)
                    self.assertEqual((split / "setup.py").read_bytes(), (UPSTREAM_SOURCE / "terminal/setup.py").read_bytes())
                    self.cross_pin_cli(self.new, "profile", "rollback", name, "--to", split_revision, "--output", "json", overlay=False)
                # The returned old guard cannot accept cache metadata belonging to the split checkout.
                build = split / "build"
                (build / "CMakeFiles").mkdir()
                (build / "CMakeFiles/fixture").write_bytes(b"relocated metadata")
                (build / "CMakeCache.txt").write_text("CMAKE_GENERATOR:INTERNAL=Ninja\n"
                    + f"CMAKE_HOME_DIRECTORY:INTERNAL={flat / 'engine'}\n"
                    + f"CMAKE_CACHEFILE_DIR:INTERNAL={build}\n")
                if mode == "interrupted":
                    subprocess.run(["git", "-C", str(flat), "apply", "--reverse", "-"],
                                   input=ledger.read_bytes(), env=self.env, check=True, capture_output=True)
                    self.assertEqual((split / "setup.py").read_bytes(), (UPSTREAM_SOURCE / "terminal/setup.py").read_bytes())
                restored = self.prepare_cross_pin(self.old, overlay=overlay)
                self.assertEqual(restored, flat)
                self.assert_local_runtime(flat, retained)
                consume_script(flat)
                self.assertFalse((flat / "build/CMakeCache.txt").exists())
                self.assertFalse((flat / "build/CMakeFiles").exists())
                result = subprocess.run([sys.executable, "-c", "import setup; assert not setup.fresh_if_other_generator(setup.ROOT/'build', 'Ninja')"],
                                        cwd=flat, env=self.env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                # This is the exact old CLI after checkout, in a fresh interpreter, not a cached head profiles module.
                rolled = self.cross_pin_cli(self.old, "profile", "rollback", name, "--to", split_revision, "--output", "json", overlay=overlay)
                self.assertEqual(rolled["profile"]["source_config"], str(config))
                self.assertEqual(rolled["profile"]["overrides"]["port"], 9123)
                self.cross_pin_cli(self.old, "profile", "history", name, "--output", "json", overlay=overlay)
                for path, expected in history.items():
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), expected)
                    self.assertEqual(__import__("hashlib").sha256(path.read_bytes()).hexdigest()[:16], path.stem)
                if overlay:
                    self.assertEqual(ledger.read_bytes(), old_ledger)
                else:
                    self.assertFalse(ledger.exists())
                for path, expected in old_receipts.items():
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), expected)
                for relative, payload in payloads.items():
                    path = flat / relative
                    self.assertEqual(path.read_bytes(), payload)
                    self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity[relative])
                    self.assertFalse((split / relative).exists())

    def test_real_sycl_cross_pin_mapping_preserves_effective_mount_arguments_and_selected_binary(self):
        self.make_cross_pin_sources()
        state = self.state
        for custom in (False, True):
            with self.subTest(custom_mount=custom):
                self.state = state / ("custom-mount" if custom else "default-mount")
                flat = self.prepare_cross_pin(self.old)
                mount = flat.parent
                payloads = {"models/model.gguf": b"model", "packs/fixture/index.txt": b"pack",
                            "build-sycl-aot/chosen strata": b"selected SYCL engine"}
                payloads.update({"models/tokenizer/" + name: b"tokenizer fixture"
                                 for name in ("vocab.json", "merges.txt", "token_type.json")})
                identities = {}
                for relative, payload in payloads.items():
                    path = flat / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
                    if relative.startswith("build-sycl"):
                        path.chmod(0o755)
                    identities[relative] = (path.stat().st_dev, path.stat().st_ino)
                configurations = {}
                for style in ("relative", "container", "environment"):
                    environment = {"STRATA_SYCL_ROOT": str(mount)} if custom else {}
                    environment["STRATA_PROMPT"] = "/work/unrelated-text-stays-literal"
                    binary = "build-sycl-aot/chosen strata" if style != "container" else "/work/" + (flat / "build-sycl-aot/chosen strata").relative_to(mount).as_posix()
                    if style != "environment":
                        environment["STRATA_SYCL_BIN"] = binary
                    else:
                        self.env["STRATA_SYCL_BIN"] = binary
                    config = flat / ("strata-sycl-" + style + ".json")
                    script = "import importlib.util,json; from pathlib import Path; "
                    script += "spec=importlib.util.spec_from_file_location('native_old_intel', 'sycl/setup_intel.py'); "
                    script += "intel=importlib.util.module_from_spec(spec); spec.loader.exec_module(intel); "
                    script += "config={'backend':'sycl','exe':str(Path.cwd()/'sycl/serve/strata-sycl.sh'), 'tokenizer':str(Path.cwd()/'models/tokenizer'), 'env':" + repr(environment) + ", "
                    script += "'args':['--native',intel.sycl_path(Path.cwd()/'models/model.gguf'), '--pack',intel.sycl_path(Path.cwd()/'packs/fixture'), "
                    script += "'--control-vector-scaled',intel.sycl_path(Path.cwd()/'models/model.gguf')+':0.5', '--prompt','/work/unrelated-text-stays-literal']}; "
                    script += "Path(" + repr(str(config)) + ").write_text(json.dumps(config))"
                    native_env = dict(self.env)
                    native_env.pop("STRATA_SYCL_ROOT", None)
                    if custom:
                        native_env["STRATA_SYCL_ROOT"] = str(mount)
                    result = subprocess.run([sys.executable, "-c", script], cwd=flat, env=native_env,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    configurations[style] = json.loads(config.read_text())
                self.assertEqual(self.prepare_cross_pin(self.old, overlay=False), flat)
                for style in configurations:
                    self.assert_cross_pin_sycl_consumers(self.old, flat, flat / ("strata-sycl-" + style + ".json"),
                        flat / "build-sycl-aot/chosen strata", flat / "models/model.gguf", flat / "packs/fixture", overlay=False)
                split = self.prepare_cross_pin(self.new)
                for style in configurations:
                    config_path = split / ("strata-sycl-" + style + ".json")
                    config = json.loads(config_path.read_text())
                    self.assertEqual(config["exe"], str(WORKSPACE_LIB / "strata-sycl.sh"))
                    self.assertEqual(config["env"]["STRATA_SYCL_HERE"], str(flat / "engine"))
                    self.assertEqual(Path(config["env"]["STRATA_SYCL_BIN"]), flat / "engine/build-sycl-aot/chosen strata")
                    prefix = "/work/" + split.relative_to(mount).as_posix()
                    self.assertEqual(config["args"][1], prefix + "/models/model.gguf")
                    self.assertEqual(config["args"][3], prefix + "/packs/fixture")
                    self.assertEqual(config["args"][5], prefix + "/models/model.gguf:0.5")
                    self.assertEqual(config["args"][7], "/work/unrelated-text-stays-literal")
                    self.assertEqual(config["env"]["STRATA_PROMPT"], "/work/unrelated-text-stays-literal")
                    self.assert_cross_pin_sycl_consumers(self.new, split, config_path,
                        flat / "engine/build-sycl-aot/chosen strata", split / "models/model.gguf", split / "packs/fixture")
                self.assertEqual(self.prepare_cross_pin(self.new, overlay=False), split)
                self.assertEqual((split / "setup.py").read_bytes(), (UPSTREAM_SOURCE / "terminal/setup.py").read_bytes())
                for style in configurations:
                    self.assert_cross_pin_sycl_consumers(self.new, split, split / ("strata-sycl-" + style + ".json"),
                        flat / "engine/build-sycl-aot/chosen strata", split / "models/model.gguf", split / "packs/fixture", overlay=False)
                self.assertEqual(self.prepare_cross_pin(self.old), flat)
                for style, original in configurations.items():
                    config_path = flat / ("strata-sycl-" + style + ".json")
                    config = json.loads(config_path.read_text())
                    self.assertEqual(config["exe"], str(WORKSPACE_LIB / "strata-sycl.sh"))
                    self.assertEqual(config["args"], original["args"])
                    self.assertEqual(config["env"]["STRATA_SYCL_HERE"], str(flat))
                    self.assertEqual(Path(config["env"]["STRATA_SYCL_BIN"]), flat / "build-sycl-aot/chosen strata")
                    self.assertEqual(config["env"]["STRATA_PROMPT"], original["env"]["STRATA_PROMPT"])
                    if custom:
                        self.assertEqual(config["env"]["STRATA_SYCL_ROOT"], original["env"]["STRATA_SYCL_ROOT"])
                    self.assert_cross_pin_sycl_consumers(self.old, flat, config_path,
                        flat / "build-sycl-aot/chosen strata", flat / "models/model.gguf", flat / "packs/fixture")
                for relative, payload in payloads.items():
                    path = flat / relative
                    self.assertEqual(path.read_bytes(), payload)
                    self.assertEqual((path.stat().st_dev, path.stat().st_ino), identities[relative])
                self.env.pop("STRATA_SYCL_BIN", None)


    @unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Native SYCL Bash recorder, no Docker or GPU")
    def test_real_sycl_custom_mirror_runs_old_new_and_reverse_shell_consumers(self):
        self.make_cross_pin_sources()
        flat = self.prepare_cross_pin(self.old)
        mount = flat.parent / "custom mirror's mount"
        mirrored = mount / flat.name
        payloads = {"build-sycl-aot/strata": b"mirror selected engine", "models/model.gguf": b"mirror model",
                    "packs/fixture/index.txt": b"mirror pack"}
        payloads.update({"models/tokenizer/" + name: b"tokenizer fixture"
                         for name in ("vocab.json", "merges.txt", "token_type.json")})
        originals = {}
        for name, payload in payloads.items():
            path = mirrored / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            if name.startswith("build-sycl"):
                path.chmod(0o755)
            originals[path] = (payload, path.stat().st_dev, path.stat().st_ino)
        config = flat / "strata-mirror.json"
        script = "import importlib.util,json; from pathlib import Path; "
        script += "spec=importlib.util.spec_from_file_location('native_mirror_intel','sycl/setup_intel.py'); "
        script += "intel=importlib.util.module_from_spec(spec); spec.loader.exec_module(intel); "
        script += "Path(" + repr(str(config)) + ").write_text(json.dumps({'backend':'sycl', "
        script += "'exe':str(Path.cwd()/'sycl/serve/strata-sycl.sh'),'tokenizer':" + repr(str(mirrored / "models/tokenizer")) + ",'env':{'STRATA_SYCL_ROOT':" + repr(str(mount)) + ",'STRATA_SYCL_BIN':'build-sycl-aot/strata'},"
        script += "'args':['--native',intel.sycl_path(" + repr(str(mirrored / "models/model.gguf")) + "), '--pack',intel.sycl_path(" + repr(str(mirrored / "packs/fixture")) + ")]}))"
        result = subprocess.run([sys.executable, "-c", script], cwd=flat,
                                env=dict(self.env, STRATA_SYCL_ROOT=str(mount)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        original_config = json.loads(config.read_text())
        docker = self.base / "mirror-docker-recorder/docker"
        docker.parent.mkdir()
        record = docker.parent / "arguments.json"
        docker.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\n"
            + "if sys.argv[1]=='run': Path(" + repr(str(record)) + ").write_text(json.dumps(sys.argv[1:]))\n")
        docker.chmod(0o700)
        def consume(root):
            cfg = json.loads((root / config.name).read_text())
            env = dict(self.env, PATH=str(docker.parent) + os.pathsep + self.env["PATH"], **cfg["env"])
            result = subprocess.run(["bash", cfg["exe"], *cfg["args"]], cwd=self.base,
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            argv = json.loads(record.read_text())
            self.assertIn(str(mount) + ":/work", argv)
            tokens = shlex.split(argv[-1])
            self.assertEqual(tokens[:4], ["cd", "/work/source", "&&", "exec"])
            executable = Path(tokens[4])
            host = mount / executable.relative_to("/work") if executable.is_absolute() else mirrored / executable
            self.assertEqual(host, mirrored / "build-sycl-aot/strata")
            self.assertEqual(tokens[5:], cfg["args"])
        consume(flat)  # The old native wrapper actually supports this existing mirror, before managed normalization.
        self.assertEqual(self.prepare_cross_pin(self.old, overlay=False), flat)
        self.assert_cross_pin_sycl_consumers(self.old, flat, config, mirrored / "build-sycl-aot/strata",
            mirrored / "models/model.gguf", mirrored / "packs/fixture", overlay=False)
        consume(flat)
        split = self.prepare_cross_pin(self.new)
        migrated = json.loads((split / config.name).read_text())
        self.assertEqual(migrated["exe"], str(WORKSPACE_LIB / "strata-sycl.sh"))
        self.assertEqual(migrated["env"]["STRATA_SYCL_HERE"], str(flat / "engine"))
        self.assertEqual(migrated["env"]["STRATA_SYCL_CWD"], "/work/source")
        self.assertEqual(Path(migrated["env"]["STRATA_SYCL_BIN"]), mirrored / "build-sycl-aot/strata")
        self.assertEqual(migrated["args"], original_config["args"])
        consume(split)
        self.assert_cross_pin_sycl_consumers(self.new, split, split / config.name, mirrored / "build-sycl-aot/strata",
            mirrored / "models/model.gguf", mirrored / "packs/fixture")
        self.assertEqual(self.prepare_cross_pin(self.new, overlay=False), split)
        self.assert_cross_pin_sycl_consumers(self.new, split, split / config.name, mirrored / "build-sycl-aot/strata",
            mirrored / "models/model.gguf", mirrored / "packs/fixture", overlay=False)
        consume(split)
        self.assertEqual(self.prepare_cross_pin(self.old, overlay=False), flat)
        restored = json.loads(config.read_text())
        self.assertEqual(restored["exe"], str(WORKSPACE_LIB / "strata-sycl.sh"))
        self.assertEqual(restored["args"], original_config["args"])
        self.assertEqual(restored["env"]["STRATA_SYCL_ROOT"], original_config["env"]["STRATA_SYCL_ROOT"])
        self.assertEqual(restored["env"]["STRATA_SYCL_HERE"], str(flat))
        self.assertEqual(Path(restored["env"]["STRATA_SYCL_BIN"]), mirrored / "build-sycl-aot/strata")
        consume(flat)
        self.assert_cross_pin_sycl_consumers(self.old, flat, config, mirrored / "build-sycl-aot/strata",
            mirrored / "models/model.gguf", mirrored / "packs/fixture", overlay=False)
        for path, expected in originals.items():
            self.assertEqual((path.read_bytes(), path.stat().st_dev, path.stat().st_ino), expected)


    def test_real_checkout_failure_retains_semantic_engine_rollback_approval(self):
        self.make_cross_pin_sources()
        flat = self.prepare_cross_pin(self.old)
        split = self.prepare_cross_pin(self.new)
        retained = self.make_local_runtime(split)
        paths = {"engine/strata": b"deliberately older engine", "engine/.previous/strata": b"newer engine",
                 "build/user-cache": b"retained cache", "models/model.gguf": b"model"}
        identity = {}
        for relative, payload in paths.items():
            path = split / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            identity[relative] = (path.stat().st_dev, path.stat().st_ino)
        module = self.workspace_module()
        entry = {"files": module.engine_identity(split / "engine"), "sources": {}, "operator_reason": "deliberate rollback"}
        approval = flat / ".git/strata-engine-rollback.json"
        approval.write_text(json.dumps({"revision": self.new, "engines": {"engine": entry}}))
        self.assertIn("engine", module.engine_rollbacks(split, self.new))
        config = split / "strata-approved.json"
        expected = {"exe": str(split / "engine/strata"), "cwd": str(split), "args": ["--native", str(split / "models/model.gguf")]}
        config.write_text(json.dumps(expected))
        source = split / "setup.py"
        original = source.read_bytes()
        source.write_bytes(original + b"\n# user-owned checkout conflict\n")
        ledger = (flat / ".git/strata-source.patch").read_bytes()
        request_receipt = flat / ".git/strata-source-request.json"
        accepted_request = request_receipt.read_bytes()
        refused = subprocess.run(self.command(self.old), env=self.env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(subprocess.check_output(["git", "-C", str(flat), "rev-parse", "HEAD"], text=True).strip(), self.new)
        self.assertEqual(source.read_bytes(), original + b"\n# user-owned checkout conflict\n")
        self.assertEqual((flat / ".git/strata-source.patch").read_bytes(), ledger)
        self.assertEqual(request_receipt.read_bytes(), accepted_request)
        self.assertEqual(json.loads(config.read_text()), expected)
        accepted = module.engine_rollbacks(split, self.new)
        self.assertIn("engine", accepted, "failed checkout revoked the operator's accepted engine")
        self.assertEqual(accepted["engine"]["operator_reason"], "deliberate rollback")
        self.assertEqual(accepted["engine"]["files"], module.engine_identity(split / "engine"))
        self.assert_local_runtime(split, retained)
        for relative, payload in paths.items():
            path = split / relative
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity[relative])
        source.write_bytes(original)
        self.prepare_cross_pin(self.old)
        self.assertFalse(approval.exists(), "accepted source transition retained an approval for the old namespace")

    def test_native_split_fallback_repeats_active_passive_and_setup_handoffs(self):
        requested = self.base / "requested.patch"
        requested.write_bytes(Path(SOURCE_PATCH).read_bytes() +
            b"diff --git a/terminal/code.py b/terminal/code.py\n"
            b"--- a/terminal/code.py\n+++ b/terminal/code.py\n@@ -1 +1 @@\n-old source\n+managed source\n")
        self.env["TEST_SOURCE_PATCH"] = str(requested)
        self.prepare(self.old)
        root = self.prepare(self.new)
        ledger = root.parent / ".git/strata-source.patch"
        self.assertFalse(ledger.exists())
        receipt = root.parent / ".git/strata-source-request.json"
        accepted = receipt.read_bytes()
        source = (root / "setup.py").read_bytes()
        for _ in range(2):
            self.prepare(self.new)
            for args in (["profile", "list"], ["connection", "list"]):
                result = subprocess.run(self.command(self.new) + ["run", *args], env=self.env,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
            context = {"state": str(self.state), "revision": self.new, "remote": str(self.repository),
                       "source_patch": str(requested), "data_directory": None, "models_directory": None}
            module = self.workspace_module()
            with module.workspace_lock(self.state) as (_, lock):
                for entry in ("--managed-setup", "--source-exec"):
                    result = subprocess.run([sys.executable, WORKSPACE, entry, "--help"],
                        env=dict(self.env, STRATA_WORKSPACE_LOCK_FD=str(lock.fileno()),
                                 STRATA_WORKSPACE_CONTEXT=json.dumps(context)),
                        pass_fds=(lock.fileno(),), capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--setup", result.stdout)
            self.assertEqual(receipt.read_bytes(), accepted)
            self.assertEqual((root / "setup.py").read_bytes(), source)
            self.assertFalse(ledger.exists())
            self.assertFalse((root / ".venv").exists())
        replacement = self.base / "new-invalid-request.patch"
        replacement.write_bytes(requested.read_bytes() + b"\n# different request\n")
        refused = subprocess.run(self.command(self.new), env=dict(self.env, TEST_SOURCE_PATCH=str(replacement)),
                                 capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(receipt.read_bytes(), accepted)
        self.assertEqual((root / "setup.py").read_bytes(), source)

    def test_cached_historical_fallback_repeats_active_and_passive_offline(self):
        self.make_cross_pin_sources()
        flat = self.prepare_cross_pin(self.old)
        historical = (flat / ".git/strata-source.patch").read_bytes()
        self.prepare_cross_pin(self.new)
        self.repository.rename(self.base / "offline-remote")
        self.env["TEST_SOURCE_PATCH"] = SOURCE_PATCH
        self.prepare(self.old)
        root = flat
        receipt = flat / ".git/strata-source-request.json"
        accepted = receipt.read_bytes()
        for _ in range(2):
            self.prepare(self.old)
            for args in (["profile", "list"], ["connection", "list"]):
                result = subprocess.run(self.command(self.old) + ["run", *args], env=self.env,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((flat / ".git/strata-source.patch").read_bytes(), historical)
            self.assertEqual(receipt.read_bytes(), accepted)
            self.assertFalse((root / ".venv").exists())

    def test_incompatible_same_pin_delta_refuses_before_retiring_accepted_overlay(self):
        root = self.prepare(self.old)
        ledger = root.parent / ".git/strata-source.patch"
        accepted = ledger.read_bytes()
        setup = (root / "setup.py").read_bytes()
        receipts = {p: p.read_bytes() for p in (root.parent / ".git/strata-source-patches").glob("*")}
        replacement = self.base / "incompatible.patch"
        replacement.write_bytes(accepted + b"diff --git a/terminal/code.py b/terminal/code.py\n"
            b"--- a/terminal/code.py\n+++ b/terminal/code.py\n@@ -1 +1 @@\n-never the pristine source\n+requested delta\n")
        result = subprocess.run(self.command(self.old), env=dict(self.env, TEST_SOURCE_PATCH=str(replacement)),
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(ledger.read_bytes(), accepted)
        self.assertEqual((root / "setup.py").read_bytes(), setup)
        self.assertEqual((root / "code.py").read_text(), "old source\n")
        self.assertEqual({p: p.read_bytes() for p in (root.parent / ".git/strata-source-patches").glob("*")}, receipts)

    def test_source_patch_revision_idempotence_edits_and_offline_unpatched_rollback(self):
        root = self.prepare(self.old)
        ledger = root.parent / ".git/strata-source.patch"
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())
        stamp = (root / "setup.py").stat().st_mtime_ns
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.old)
        self.prepare(self.old)
        self.assertEqual((root / "setup.py").stat().st_mtime_ns, stamp)
        self.assertEqual(marker.read_text(), self.old)
        with (root / "setup.py").open("a") as source:
            source.write("\n# user-owned note outside managed hunks\n")
        self.prepare(self.new)
        self.assertTrue((root / "setup.py").read_text().endswith("# user-owned note outside managed hunks\n"))
        self.assertEqual(subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), self.new)
        self.repository.rename(self.base / "offline")
        self.prepare(self.old)
        self.assertTrue(ledger.exists())
        result = subprocess.run(self.command(self.old), env=dict(self.env, TEST_SOURCE_PATCH=""),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(ledger.exists())
        self.assertTrue((root / "setup.py").read_text().endswith("# user-owned note outside managed hunks\n"))
        self.prepare(self.old)
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())

    def test_source_patch_recovers_published_ledger_and_refuses_conflicting_edits(self):
        root = self.prepare(self.old)
        ledger = root.parent / ".git/strata-source.patch"
        subprocess.run(["git", "-C", str(root.parent), "apply", "--reverse", "-"],
                       input=ledger.read_bytes().decode("utf-8"), text=True, env=self.env, check=True)
        # A ledger published before apply is safe to resume, including across a pin change.
        self.prepare(self.new)
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())
        source = root / "setup.py"
        source.write_text(source.read_text().replace(
            "def ready_where(models_dir: Path, f, data_dir=None, checkpoint_dir=None)",
            "def ready_where(models_dir: Path, f, data_dir='user edit', checkpoint_dir=None)",
        ))
        expected = source.read_bytes()
        result = subprocess.run(self.command(self.old), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot reconcile source patch", result.stderr)
        self.assertEqual(source.read_bytes(), expected)
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())
        self.assertEqual(subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), self.new)

    def test_native_profile_publication_failure_restores_layout_and_profile_revisions(self):
        self.state = self.base / "publication's workspace with spaces"
        root = self.prepare(self.old)
        retained = self.make_local_runtime(root.parent)
        self.run_source_script(root, r'''
import json, os, subprocess
import setup
import strata_managed_state
from strata_control import profiles
repository = setup.ROOT.parent
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(repository.parent)})
config = repository / "strata-transaction.json"
config.write_text(json.dumps({"exe": str(repository / "engine/strata"),
                              "tokenizer": "/fixture/tokenizer", "cwd": str(repository), "args": []}))
for name in ("first", "second"):
    profiles.create(name, str(config))
    profiles.set_values(name, ["port=9123", "parallel=3"])
payload = repository / "engine/.previous/strata"
payload.parent.mkdir(parents=True)
payload.write_bytes(b"previous engine")
cache = repository / "build/user-cache"
cache.parent.mkdir()
cache.write_bytes(b"user cache")
for reverse in (False, True):
    source = setup.ROOT if reverse else repository
    destination = repository if reverse else setup.ROOT
    paths = [source / "strata-transaction.json", source / "engine/.previous/strata", source / "build/user-cache"]
    paths += [source / ".venv/pyvenv.cfg", source / ".venv/bin/relocation-fixture"]
    originals = [(p, p.read_bytes(), p.stat().st_ino) for p in paths]
    current = {name: profiles.load(name) for name in ("first", "second")}
    profile_bytes = {p: p.read_bytes() for p in profiles.profile_dir().rglob("*.json")}
    links = {p.relative_to(source): os.readlink(p) for p in (source / ".venv/bin").iterdir()
             if p.is_symlink()}
    real_save = profiles._save_locked
    saves = []
    def fail_second(name, proposed, **kwargs):
        saves.append(name)
        if len(saves) == 2:
            raise OSError("fixture profile publication refused")
        return real_save(name, proposed, **kwargs)
    profiles._save_locked = fail_second
    try:
        try:
            strata_managed_state.migrate_layout(repository, reverse=reverse)
        except RuntimeError as error:
            assert "fixture profile publication refused" in str(error), error
        else:
            raise AssertionError("migration certified a failed profile publication")
    finally:
        profiles._save_locked = real_save
    assert len(saves) == 2, saves
    result = subprocess.run([str(source / ".venv/bin/relocation-fixture")],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "retained package"
    runtime = subprocess.check_output([str(source / ".venv/bin/python"), "-c",
        "import json,sys; print(json.dumps([sys.prefix,sys.base_prefix]))"], text=True)
    assert json.loads(runtime) == [str(source / ".venv"), str(source / ".python")]
    activated = subprocess.check_output(["sh", "-c", '. "$1"; "$VIRTUAL_ENV/bin/relocation-fixture"; '
        'python -c "import json,sys; print(json.dumps([sys.prefix,sys.base_prefix]))"',
        "failure-activation", str(source / ".venv/bin/activate")], text=True)
    lines = activated.splitlines()
    assert lines[0] == "retained package"
    assert json.loads(lines[1]) == [str(source / ".venv"), str(source / ".python")]
    for path, data, inode in originals:
        assert path.read_bytes() == data
        assert path.stat().st_ino == inode
        assert not (destination / path.relative_to(source)).exists()
    assert {p.relative_to(source): os.readlink(p) for p in (source / ".venv/bin").iterdir()
            if p.is_symlink()} == links
    for name, expected in current.items():
        assert profiles.load(name) == expected
        resolved, profile, revision = profiles.resolve(name)
        assert resolved == paths[0]
        assert profiles.read_run_config(resolved)["cwd"] == str(source)
        assert profile["overrides"] == {"port": 9123, "parallel": 3}
    assert {p: p.read_bytes() for p in profiles.profile_dir().rglob("*.json")} == profile_bytes
    strata_managed_state.migrate_layout(repository, reverse=reverse)
''')
        self.assert_local_runtime(root.parent, retained)

    def test_profile_create_waits_for_relocation_and_never_publishes_dangling_source(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r"""
import errno, fcntl, json, os, signal, socket
from pathlib import Path
from strata_control import profiles
source = Path("../strata-race.json").resolve()
destination = Path("strata-race.json").resolve()
config = {"exe": "/fixture/engine", "tokenizer": "/fixture/tokenizer", "args": []}
source.write_text(json.dumps(config))
profiles.create("existing", str(source))
parent, child = socket.socketpair()
parent.settimeout(15)
pid = None
reaped = False
try:
    pid = os.fork()
    if pid == 0:
        parent.close()
        child.settimeout(15)
        assert child.recv(1) == b"g"
        native_flock = fcntl.flock
        announced = False
        def observed_flock(fd, operation):
            global announced
            if operation & fcntl.LOCK_EX and not operation & fcntl.LOCK_NB:
                try:
                    return native_flock(fd, operation | fcntl.LOCK_NB)
                except OSError as error:
                    if error.errno not in (errno.EAGAIN, errno.EACCES):
                        raise
                    if not announced:
                        child.sendall(b"b")
                        announced = True
            return native_flock(fd, operation)
        fcntl.flock = observed_flock
        # A second installation has no managed workspace lease to serialize it.
        os.environ.pop("STRATA_WORKSPACE_CONTEXT", None)
        try:
            profiles.create("concurrent", str(source))
            resolved, _, _ = profiles.resolve("concurrent")
            result = {"created": True, "resolved": str(resolved), "exists": resolved.is_file()}
        except profiles.ProfileError:
            result = {"created": False}
        except BaseException as error:
            result = {"error": repr(error)}
        child.sendall(json.dumps(result).encode())
        child.close()
        os._exit(0)
    child.close()
    with profiles.relocate_sources([(source, destination)]) as publish:
        parent.sendall(b"g")
        # Sent only after a real nonblocking flock fails: no scheduler/timing assumption.
        assert parent.recv(1) == b"b", "create did not block on the relocation namespace"
        source.rename(destination)
        publish()
    result = json.loads(parent.recv(65536))
    assert "error" not in result, result
    if result["created"]:
        assert result["exists"] and result["resolved"] == str(destination), result
    else:
        assert not (profiles.profile_dir() / "concurrent.json").exists()
    assert profiles.resolve("existing")[0] == destination
    waited, status = os.waitpid(pid, 0)
    reaped = True
    assert waited == pid and status == 0, status
finally:
    parent.close()
    child.close()
    if pid is not None and pid > 0 and not reaped:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)
""")

    def test_native_without_overlay_prepares_and_removal_migrates_real_payloads(self):
        def native_prepare():
            result = subprocess.run(self.command(self.old), env=dict(self.env, TEST_SOURCE_PATCH=""),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return Path(result.stdout.strip())
        root = native_prepare()
        for overlay in (False, True):
            if overlay:
                self.assertEqual(self.prepare(self.old), root)
            source = root.parent / "models/native.gguf"
            source.parent.mkdir(exist_ok=True)
            source.write_bytes(b"native retained payload")
            inode = source.stat().st_ino
            config = root.parent / "strata-native.json"
            config.write_text(json.dumps({"exe": "/fixture/engine", "args": [str(source)]}))
            self.assertEqual(native_prepare(), root)
            destination = root / "models/native.gguf"
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_bytes(), b"native retained payload")
            self.assertEqual(destination.stat().st_ino, inode)
            self.assertEqual(json.loads((root / config.name).read_text())["args"], [str(destination)])
            self.assertEqual((root / "setup.py").read_bytes(), (Path(UPSTREAM) / "setup.py").read_bytes())
            self.assertFalse((root.parent / ".git/strata-source.patch").exists())
            destination.unlink()
            destination.parent.rmdir()
            (root / config.name).unlink()

    def test_flat_checkout_refusal_after_reverse_restores_managed_runtime(self):
        self.state = self.base / "refusal's workspace with spaces"
        self.git("mv", "terminal/setup.py", "setup.py")
        self.git("mv", "terminal/code.py", "code.py")
        legacy = self.commit()
        overlay = self.base / "legacy.patch"
        overlay.write_text("diff --git a/code.py b/code.py\n--- a/code.py\n+++ b/code.py\n"
                           "@@ -1 +1 @@\n-new source\n+accepted legacy overlay\n")
        accepted = subprocess.run(self.command(legacy), env=dict(self.env, TEST_SOURCE_PATCH=str(overlay)),
                                  capture_output=True, text=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        repository = Path(accepted.stdout.strip()).parent
        self.assertEqual((repository / "code.py").read_text(), "accepted legacy overlay\n")
        root = self.prepare(self.old)
        self.assertEqual(root.parent, repository)
        ledger = repository / ".git/strata-source.patch"
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())
        payloads = {"engine/strata": b"current", "engine/.previous/strata": b"previous",
                    "build/user-cache": b"user cache", "models/user.gguf": b"user model"}
        identities = {}
        for name, data in payloads.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            identities[name] = (path.stat().st_dev, path.stat().st_ino)
        retained = self.make_local_runtime(root)
        config = root / "strata-refused.json"
        expected = {"exe": str(root / "engine/strata"), "cwd": str(root), "args": []}
        config.write_text(json.dumps(expected))
        (root / "code.py").write_text("user-owned tracked conflict\n")
        refused = subprocess.run(self.command(legacy), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual((root / "code.py").read_text(), "user-owned tracked conflict\n")
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())
        self.assertEqual(subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"],
                                                text=True).strip(), self.old)
        self.assertEqual(json.loads(config.read_text()), expected)
        self.assertFalse((repository / config.name).exists())
        self.assert_local_runtime(root, retained)
        self.assertFalse((repository / ".venv").exists())
        for name, data in payloads.items():
            path = root / name
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), identities[name])
            self.assertFalse((repository / name).exists())

    def test_source_patch_checkout_failure_restores_old_overlay_and_keeps_user_changes(self):
        root = self.prepare(self.old)
        ledger = root.parent / ".git/strata-source.patch"
        payloads = {"engine/strata": b"current", "engine/.previous/strata": b"previous",
                    "build/user-cache": b"user cache", "models/user.gguf": b"user model"}
        identities = {}
        for name, data in payloads.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            identities[name] = (path.stat().st_dev, path.stat().st_ino)
        python = root / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        interpreter = python.lstat().st_ino
        config = root / "strata-rollback.json"
        expected = {"exe": str(root / "engine/strata"), "cwd": str(root), "args": []}
        config.write_text(json.dumps(expected))
        (root / "code.py").write_text("user-owned conflicting source\n")
        result = subprocess.run(self.command(self.new), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((root / "code.py").read_text(), "user-owned conflicting source\n")
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())
        self.assertEqual(subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), self.old)
        subprocess.run(["git", "-C", str(root.parent), "apply", "--reverse", "--check", "-"],
                       input=ledger.read_bytes().decode("utf-8"), text=True, env=self.env, check=True)
        for name, data in payloads.items():
            path = root / name
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual((path.stat().st_dev, path.stat().st_ino), identities[name])
            self.assertFalse((root.parent / name).exists())
        self.assertEqual(python.lstat().st_ino, interpreter)
        self.assertEqual(json.loads(config.read_text()), expected)
        self.assertFalse((root.parent / ".venv").exists())

    def test_initial_bootstrap_failure_never_certifies_runtime(self):
        root = self.prepare(self.old)
        marker = root.parent / ".git/strata-runtime-revision"
        self.assertFalse(marker.exists())
        setup = setup_wrapper(root)
        setup.write_text(f'''#!{shutil.which("sh")}
cd "$(dirname "$0")" || exit 8
if [ -f terminal/setup.py ]; then cd terminal || exit 8; fi
attempts=0
test ! -f bootstrap-attempts || read -r attempts < bootstrap-attempts
printf '%s\\n' "$((attempts + 1))" > bootstrap-attempts
exit 9
''')
        setup.chmod(0o700)
        for attempt in (1, 2):
            result = subprocess.run(self.command(self.old) + ["run", "source"], env=self.env,
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
        self.repository.rename(self.base / "remote-offline")
        self.assertEqual(self.prepare(self.new), root)
        self.assertEqual((root / "code.py").read_text(), "new source\n")
        self.assertEqual(self.prepare(self.old), root)
        self.assertEqual((root / "removed.py").read_text(), "obsolete source\n")
        for name, text in expected.items():
            self.assertEqual((root / name).read_text(), text, name)

    def test_setup_resumes_interrupted_initialization_before_inspecting_parser(self):
        setup = setup_wrapper(self.repo)
        setup.write_text(f'#!{shutil.which("sh")}\nexec "{sys.executable}" "$(dirname "$0")/terminal/setup.py" "$@"\n')
        setup.chmod(0o700)
        revision = self.commit()
        for stage in ("directory", "initialized", "fetched"):
            with self.subTest(stage=stage):
                self.state = self.base / stage
                source = self.state / "source"
                source.mkdir(parents=True)
                if stage != "directory":
                    subprocess.run(["git", "-C", str(source), "init", "--quiet"],
                                   env=self.env, check=True)
                if stage == "fetched":
                    subprocess.run(["git", "-C", str(source), "fetch", "--quiet",
                                    str(self.repository), revision], env=self.env, check=True)
                owned = source / "user-notes.txt"
                owned.write_text("keep user data\n")
                result = subprocess.run(self.command(revision) + ["run", "source", "--setup", "--help"],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--data-dir", result.stdout)
                self.assertEqual(subprocess.check_output(
                    ["git", "-C", str(source), "rev-parse", "HEAD"], env=self.env, text=True).strip(),
                    revision)
                self.assertEqual(owned.read_text(), "keep user data\n")
                self.assertFalse((source / ".git/strata-runtime-revision").exists())

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
        self.env["TEST_SOURCE_PATCH"] = ""
        root = self.prepare(self.old)
        del self.env["TEST_SOURCE_PATCH"]
        legacy = root.parent.with_name(f"source-{self.old}")
        root.parent.rename(legacy)
        source = self.state / "source"
        source.symlink_to(legacy.name, target_is_directory=True)
        config = legacy / "terminal/strata-user.json"
        expected = '{"custom": "preserve"}'
        config.write_text(expected)
        subprocess.run(["git", "-C", str(legacy), "check-ignore", "--quiet", "terminal/" + config.name],
                       env=self.env, check=True)
        shutil.rmtree(legacy / ".git")
        self.assertFalse((legacy / ".git").exists())
        (self.repo / "code.py").write_text("third source\n")
        revision = self.commit()
        self.assertEqual(self.prepare(revision), legacy / "terminal")
        self.assertTrue(source.is_symlink())
        self.assertEqual(os.readlink(source), legacy.name)
        self.assertTrue((legacy / ".git").is_dir())
        self.assertEqual((legacy / "terminal/code.py").read_text(), "third source\n")
        self.assertFalse((legacy / "terminal/removed.py").exists())
        self.assertEqual(config.read_text(), expected)
        self.repository.rename(self.base / "remote-offline")
        self.assertEqual(self.prepare(self.old), legacy / "terminal")
        self.assertEqual((legacy / "terminal/code.py").read_text(), "old source\n")
        self.assertEqual((legacy / "terminal/removed.py").read_text(), "obsolete source\n")
        self.assertEqual(config.read_text(), expected)

    def test_settings_do_not_select_the_workspace(self):
        self.state.mkdir()
        candidate = self.state / f"source-{self.old}"
        subprocess.run(["git", "clone", "--quiet", str(self.repository), str(candidate)],
                       env=self.env, check=True)
        subprocess.run(["git", "-C", str(candidate), "checkout", "--quiet", self.old],
                       env=self.env, check=True)
        config = candidate / "terminal/strata-user.json"
        expected = '{"custom": "preserve"}'
        config.write_text(expected)
        settings = Path(self.env["XDG_CONFIG_HOME"]) / "strata/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"installs": [str(candidate)]}))
        root = self.prepare(self.new)
        self.assertEqual(root, self.state / "source/terminal")
        self.assertFalse(root.is_symlink())
        self.assertEqual((root / "code.py").read_text(), "new source\n")
        self.assertEqual(config.read_text(), expected)
        self.assertEqual((candidate / "terminal/code.py").read_text(), "old source\n")

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
        self.assertIn(f"Workspace link {source} is broken", result.stderr)
        self.assertIn("restore its target or remove the link and retry", result.stderr)

    def test_uninitialised_tree_outside_revision_pattern_reports_repair(self):
        root = self.prepare(self.old)
        candidate = root.parent.with_name(f"source-{self.old}-custom")
        root.parent.rename(candidate)
        source = self.state / "source"
        source.symlink_to(candidate.name, target_is_directory=True)
        config = candidate / "terminal/strata-user.json"
        expected = '{"custom": "preserve"}'
        config.write_text(expected)
        shutil.rmtree(candidate / ".git")
        result = subprocess.run(self.command(self.new), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(source.is_symlink())
        self.assertEqual(os.readlink(source), candidate.name)
        self.assertEqual((candidate / "terminal/code.py").read_text(), "old source\n")
        self.assertEqual((candidate / "terminal/removed.py").read_text(), "obsolete source\n")
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
        self.git("add", "--force", "terminal/build/user-cache")
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
        self.repository.rename(self.base / "remote-offline")
        self.assertEqual(self.prepare(self.old), root)
        self.assertEqual((root / "code.py").read_text(), "old source\n")

    def make_runtime_source(self, root):
        # Keep the actual setup parser and lifecycle; replace only external acquisition boundaries.
        (root / "requirements.txt").write_text("pip\n")
        script = setup_wrapper(root)
        script.write_text(f'''#!/bin/sh
cd "$(dirname "$0")" || exit 8
if [ -f terminal/setup.py ]; then cd terminal || exit 8; fi
exec "{sys.executable}" -c 'import os,setup,sys; sys.exit(setup.bootstrap_runtime() if os.environ.get("STRATA_BOOTSTRAP_ONLY") == "1" else setup.main())' "$@"
''')
        script.chmod(0o700)
        source = root / "setup.py"
        source.write_text(source.read_text() + '''

# Test fixture: inject hardware/acquisition boundaries after the real setup module loads.
if __name__ != "__main__" and (ROOT / "setup-fixture.py").exists():
    _fixture = (ROOT / "setup-fixture.py").read_text()
    _prefix, _separator, _tail = _fixture.partition("sys.exit(setup.main())")
    if not _separator:
        _prefix, _separator, _tail = _fixture.partition("result = setup.main()")
    if not _separator:
        raise RuntimeError("Fixture has no real setup.main boundary")
    _scope = {}
    exec(_prefix, _scope)
    _real_main = main
    def main(argv=None, *, after_parse=None):
        result = _real_main(argv, after_parse=after_parse)
        exec(_tail.replace("sys.exit(result)", ""), dict(_scope, result=result))
        return result
''')

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

    def workspace_module(self):
        spec = importlib.util.spec_from_file_location("workspace_under_test", WORKSPACE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_native_root_help_errors_and_source_passthrough(self):
        self.env["STRATA_CONTROL_INSTALL"] = "1"
        root = self.prepare(self.old)
        command = self.command(self.old) + ["run"]
        for argv, code in ((["--help"], 0), ([], 2), (["unknown-command"], 2),
                           (["--setup"], 2), (["--family", "qwen"], 2), (["--update"], 2),
                           (["--version"], 0), (["install", "--help"], 0),
                           (["source", "--help"], 0)):
            with self.subTest(argv=argv):
                result = subprocess.run(command + argv, env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                if argv == ["--help"]:
                    for word in ("source", "launch", "serve", "status", "monitor", "update", "models"):
                        self.assertIn(word, result.stdout)
                if argv == ["source", "--help"]:
                    self.assertIn("--family", result.stdout)
                    self.assertIn("usage: strata source", result.stdout)
                self.assertFalse((root / ".venv").exists())
                self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())
        self.run_source_script(root, '''
from strata_cli.cli import parse_args, _run
import setup
raw = ["--api-key", "--version", "--inspect", "status", "--", "kept"]
a = parse_args(["source", *raw])
assert a.setup_args == raw
assert a.raw_argv == ["source", *raw]
setup.main = lambda argv: 37 if argv == raw else 99
assert _run(a) == 37
assert parse_args(["serve", "--config", "status", "--port", "123"]).port == 123
for argv in (["source", "--context", "not-an-int"], ["source", "--backend", "unknown"]):
    try:
        setup.main = __import__("importlib").reload(setup).main
        setup.main(argv[1:], after_parse=lambda a, argv: 0)
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("the real setup parser accepted invalid argv")
''')

    def mock_server(self, root, script):
        """Isolate the backend without replacing files owned by the source overlay."""
        fixture = root / "server-fixture.py"
        fixture.write_text(script)
        loader = (
            "import sys, importlib.util, serve\n"
            f"_server_spec = importlib.util.spec_from_file_location('serve.server', {str(fixture)!r})\n"
            "_server_spec.loader = importlib.util.LazyLoader(_server_spec.loader)\n"
            "_server_module = importlib.util.module_from_spec(_server_spec)\n"
            f"_server_module.__file__ = {str(root / 'serve/server.py')!r}\n"
            "serve.server = sys.modules['serve.server'] = _server_module\n"
            "_server_spec.loader.exec_module(_server_module)\n"
        )
        entry = root / self.env.get("TEST_TERMINAL_CLI", "strata.py")
        source = entry.read_text()
        future = "from __future__ import annotations\n"
        self.write_terminal(root, source.replace(future, future + loader, 1) if future in source else loader + source)

    def service_script(self, root, script):
        """Replace only the direct-entry service boundary; keep native patch contexts intact."""
        server = root / "serve/server.py"
        prefix = (
            'if __name__ == "__main__":\n'
            "    import sys\n    from pathlib import Path\n"
            "    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
            "    from strata_control import acquisition\n"
            "    with acquisition.source_observation():\n"
            "        acquisition.service_ready()\n"
            + "".join("        " + line + "\n" for line in script.splitlines())
            + "        raise SystemExit(0)\n"
        )
        future = "from __future__ import annotations\n"
        server.write_text(server.read_text().replace(future, future + prefix, 1))

    def write_terminal(self, root, script):
        """Keep the native entry intact; replace only the test's terminal/service boundary."""
        entry = root / "terminal-fixture.py"
        self.env["TEST_TERMINAL_CLI"] = entry.name
        bootstrap = root / "terminal_fixture_bootstrap.py"
        bootstrap.write_text(f'''
import subprocess as _fixture_subprocess
_fixture_popen_original = _fixture_subprocess.Popen
def _fixture_popen(command, *args, **kwargs):
    if isinstance(command, (list, tuple)) and len(command) > 1 and str(command[1]) == {str(root / "strata.py")!r}:
        command = [command[0], {str(entry)!r}, *command[2:]]
    return _fixture_popen_original(command, *args, **kwargs)
_fixture_subprocess.Popen = _fixture_popen
''')
        entry.write_text("import terminal_fixture_bootstrap\n" + script)

    def make_terminal(self, root, before=""):
        if not (root / "serve").exists():
            shutil.copytree(Path(UPSTREAM) / "serve", root / "serve", copy_function=shutil.copyfile)
        if not (root / "tools/gguf_reader.py").exists():
            shutil.copyfile(Path(UPSTREAM) / "tools/gguf_reader.py", root / "tools/gguf_reader.py")
        self.write_terminal(root,
            "import sys\nfrom pathlib import Path\nfrom strata_cli import cli\n"
            + before + "\nraise SystemExit(cli.main())\n")
        if not (root / ".venv/bin/python").exists():
            (root / ".venv/bin").mkdir(parents=True, exist_ok=True)
            (root / ".venv/bin/python").symlink_to(sys.executable)
        script = setup_wrapper(root)
        if script.read_text() == (UPSTREAM_SOURCE / "setup.sh").read_text():
            self.make_runtime_source(root)
            (root / "setup-fixture.py").write_text(
                "import setup,sys\nsetup.pip_install = lambda *a, **kw: None\n"
                "setup.update_installed_engine = lambda *a: None\nsys.exit(setup.main())\n")

    def test_terminal_preserves_relative_config_and_upstream_version_action(self):
        root = self.prepare(self.old)
        self.make_terminal(root)
        config = self.make_runtime_model(root)
        (self.base / "model.json").write_text(json.dumps(config))
        command = self.command(self.old) + ["run", "serve", "--config", "./model.json",
                                           "--engine", "mock", "--plan", "--output", "json"]
        result = subprocess.run(command, cwd=self.base, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        for args in (["--vers"], ["--version", "filename.json"]):
            with self.subTest(args=args):
                result = subprocess.run(self.command(self.old) + ["run", *args], cwd=self.base,
                                        env=self.env, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith("strata "), result.stdout)
                self.assertIn("python ", result.stdout)

    def test_native_old_and_split_long_observers_release_source_after_imports_and_ui_ready(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import hashlib
        import threading
        self.make_cross_pin_sources()
        self.env["STRATA_PROFILE_DIR"] = str(self.base / "native observers' empty profiles")
        state = self.state
        class Telemetry(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"schema_version": 1, "instance": {"id": "native-observer"},
                                   "activity": {"last_seq": 0, "events": []}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        telemetry = ThreadingHTTPServer(("127.0.0.1", 0), Telemetry)
        thread = threading.Thread(target=telemetry.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(telemetry.server_close)
        self.addCleanup(telemetry.shutdown)
        url = "http://127.0.0.1:" + str(telemetry.server_port)
        def reap(process, *, group=False):
            if process.poll() is None:
                if group:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            process.communicate(timeout=10)
        bootstrap = self.base / "native observer's bootstrap"
        bootstrap.mkdir()
        (bootstrap / "observer-bootstrap.py").write_text(r'''
from strata_managed_state import install_consumer
install_consumer()
import os, sys
if os.environ.get("NATIVE_GATE") and "--native-observer" in sys.argv:
    import ast, hashlib, importlib.abc, importlib.machinery, json, socket
    from pathlib import Path
    root = Path(sys.argv[2])
    mode = sys.argv[4]
    loaded = {}
    after_ready = False
    def gate(label):
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(30)
            peer.connect(os.environ["NATIVE_GATE"])
            peer.sendall(json.dumps({"phase": label, "pid": os.getpid(), "imports": loaded}).encode() + b"\n")
            assert peer.recv(1) == b"g"
    class SourceLoader(importlib.abc.Loader):
        def __init__(self, original, fullname, filename):
            self.original, self.fullname, self.filename = original, fullname, filename
        def create_module(self, spec):
            return self.original.create_module(spec)
        def exec_module(self, module):
            assert not after_ready, ("mutable checkout import after native readiness", self.fullname)
            if self.fullname == "strata_cli.cli":
                gate("i")
            loaded[self.fullname] = hashlib.sha256(Path(self.filename).read_bytes()).hexdigest()
            self.original.exec_module(module)
            if mode == "logs" and self.fullname == "strata_cli.logs":
                gate("u")
    class Sources(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if not fullname.startswith(("strata_cli.", "strata_control.", "serve.")):
                return None
            if fullname in {"strata_control.profiles", "strata_control.cfg_paths", "strata_control.doctor"}:
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is not None and spec.origin and Path(spec.origin).is_relative_to(root):
                spec.loader = SourceLoader(spec.loader, fullname, spec.origin)
                return spec
    sys.meta_path.insert(0, Sources())
    logs_file = str(root / "strata_cli/logs.py")
    poll = next(node.lineno for node in ast.walk(ast.parse(Path(logs_file).read_text()))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "time" and node.func.attr == "sleep")
    loop_seen = False
    profile_events = 0
    def original_profile(frame, event, arg):
        global profile_events
        profile_events += 1
    def trace(frame, event, arg):
        global after_ready, loop_seen
        filename, name = frame.f_code.co_filename, frame.f_code.co_name
        if (mode == "monitor" and filename == str(root / "strata_cli/launch/monitor_ext.py")
                and name == "__init__" and event == "return"):
            gate("u")
        if not loop_seen and ((mode == "logs" and filename == logs_file and name == "run"
                               and event == "line" and frame.f_lineno == poll)
                              or (mode == "monitor" and filename == str(root / "strata_cli/monitor.py")
                                  and name == "on_mount" and event == "return")):
            loop_seen = after_ready = True
            assert sys.getprofile() is original_profile and profile_events > 0
            gate("l")
        return trace
    sys.setprofile(original_profile)
    sys.settrace(trace)
''')
        writer_script = r'''
import contextlib, fcntl, importlib.util, json, os, socket, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("native_writer", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
state, remote, revision, patch = Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5] or None
def gate(label, wait=True):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(30)
        peer.connect(os.environ["NATIVE_GATE"])
        peer.sendall(json.dumps({"phase": label, "pid": os.getpid()}).encode() + b"\n")
        if wait:
            assert peer.recv(1) == b"g"
original = module.source_publication_lock
calls = 0
@contextlib.contextmanager
def publication(state, *, shared=False):
    global calls
    calls += 1
    if calls == 2:
        gate("p")  # The real mutator holds acquisition, but has finished its protected source inspection.
    with original(state, shared=shared) as lock:
        yield lock
module.source_publication_lock = publication
with module.workspace_lock(state) as (_, lock):
    with (state / ".source-publication.lock").open("a") as publication_lock:
        try:
            fcntl.flock(publication_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            gate("w", wait=False)
        else:
            raise AssertionError("native observer imports were not protected by a real reader")
    module._prepare_workspace(state, revision, remote, patch, lock_fd=lock.fileno())
'''
        for label, revision, overlay in (("old-native", self.old, False), ("old-accepted", self.old, True),
                                          ("split-native", self.new, False)):
            for mode in ("logs", "monitor"):
                with self.subTest(pin=label, command=mode), tempfile.TemporaryDirectory(prefix="s339-", dir="/tmp") as sockets:
                    self.state = state / (label + "-" + mode)
                    root = self.prepare_cross_pin(revision, overlay=overlay)
                    interpreter = root / ".venv/bin/python"
                    interpreter.parent.mkdir(parents=True)
                    interpreter.write_text("#!" + sys.executable + "\nimport runpy,sys\n"
                        + "entry,args=sys.argv[1],sys.argv[2:]\nsys.argv=[entry,*args]\n"
                        + "runpy.run_path(" + repr(str(bootstrap / "observer-bootstrap.py")) + ")\n"
                        + "runpy.run_path(entry,run_name='__main__')\n")
                    interpreter.chmod(0o700)
                    repository = root.parent if root.name == "terminal" else root
                    selected = self.legacy_overlay if revision == self.old else Path(SOURCE_PATCH)
                    ordinary = dict(self.env, TEST_SOURCE_PATCH=str(selected) if overlay else "")
                    address = str(Path(sockets) / "g")
                    env = dict(ordinary, NATIVE_GATE=address, TERM="xterm-256color",
                               PYTHONPATH=str(WORKSPACE_LIB))
                    command = self.command(revision) + ["run", mode, "--url", url, "--timeout", "1"]
                    if mode == "logs":
                        command += ["--follow", "--output", "jsonl"]
                    else:
                        command += ["--color", "never", "--glyphs", "ascii"]
                    with socket.socket(socket.AF_UNIX) as server:
                        server.bind(address)
                        server.listen(8)
                        server.settimeout(30)
                        def event():
                            peer, _ = server.accept()
                            peer.settimeout(30)
                            self.addCleanup(peer.close)
                            raw = b""
                            while not raw.endswith(b"\n"):
                                part = peer.recv(65536)
                                self.assertTrue(part, raw)
                                raw += part
                            return peer, json.loads(raw)
                        master = slave = None
                        if mode == "monitor":
                            master, slave = pty.openpty()
                            self.addCleanup(os.close, master)
                        observer = subprocess.Popen(command, env=env, cwd=self.base,
                            stdin=slave if slave is not None else subprocess.DEVNULL,
                            stdout=slave if slave is not None else subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
                        self.addCleanup(reap, observer, group=True)
                        if slave is not None:
                            os.close(slave)
                            drain = subprocess.Popen([sys.executable, "-c", "import os,sys\n"
                                + "while True:\n    try: data=os.read(int(sys.argv[1]),65536)\n"
                                + "    except OSError: break\n    if not data: break\n", str(master)],
                                pass_fds=(master,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            self.addCleanup(reap, drain)
                        imported, observed = event()
                        self.assertEqual(observed["phase"], "i")
                        self.assertEqual(observed["pid"], observer.pid)
                        with (self.state / ".source-publication.lock").open("a") as lock:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        target = self.new if revision == self.old else self.old
                        target_patch = str(SOURCE_PATCH) if overlay and target == self.new else ""
                        writer = subprocess.Popen([sys.executable, "-c", writer_script, WORKSPACE, str(self.state),
                            str(self.repository), target, target_patch], env=dict(ordinary, NATIVE_GATE=address),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
                        self.addCleanup(reap, writer, group=True)
                        waiting, message = event()
                        self.assertEqual(message["phase"], "w")
                        self.assertEqual(message["pid"], writer.pid)
                        waiting.close()
                        self.assert_workspace_locked()
                        imported.sendall(b"g")
                        imported.close()
                        initialized, observed = event()
                        self.assertEqual(observed["phase"], "u")
                        self.assertEqual(subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip(), revision)
                        with (self.state / ".source-publication.lock").open("a") as lock:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        def observers_answer():
                            for args in (["status", "--output", "json", "--url", url], ["--version"], ["launch", "--stop"]):
                                result = subprocess.run(self.command(revision) + ["run", *args], env=ordinary,
                                                        capture_output=True, text=True, timeout=30)
                                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                                if args[0] == "status":
                                    self.assertEqual(json.loads(result.stdout)["snapshot"]["instance"]["id"], "native-observer")
                                elif args[0] == "--version":
                                    self.assertTrue(result.stdout.startswith("strata "), result.stdout)
                                else:
                                    self.assertIn("Nothing from", result.stdout)
                        observers_answer()  # A writer really contends with this reader; native status/version/stop still answer.
                        refused = subprocess.run(self.command(revision) + ["run", "logs", "--follow", "--output", "json", "--url", url],
                                                 env=ordinary, capture_output=True, text=True, timeout=30)
                        self.assertEqual(refused.returncode, 2, refused.stderr + refused.stdout)
                        self.assertEqual(json.loads(refused.stdout)["error"]["message"], "--follow requires human or jsonl output")
                        initialized.sendall(b"g")
                        initialized.close()
                        phases = {}
                        for _ in range(2):
                            peer, message = event()
                            self.assertIn(message["phase"], ("l", "p"))
                            self.assertNotIn(message["phase"], phases)
                            phases[message["phase"]] = (peer, message)
                        looping, observed = phases["l"]
                        pending, _ = phases["p"]
                        self.assertIsNone(observer.poll())
                        self.assert_workspace_locked()
                        with (self.state / ".source-publication.lock").open("a") as lock:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        raw = OLD_UPSTREAM_SOURCE if revision == self.old else UPSTREAM_SOURCE / "terminal"
                        self.assertEqual(observed["imports"]["strata_cli.cli"], hashlib.sha256((raw / "strata_cli/cli.py").read_bytes()).hexdigest())
                        if mode == "monitor":
                            for name in ("strata_cli.monitor", "strata_cli.launch.monitor_ext", "strata_control.retired"):
                                self.assertIn(name, observed["imports"])
                        observers_answer()  # Acquisition remains held while the native long loop has released publication.
                        pending.sendall(b"g")
                        pending.close()
                        stdout, stderr = writer.communicate(timeout=60)
                        self.assertEqual(writer.returncode, 0, stderr + stdout)
                        self.assertEqual(subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"], text=True).strip(), target)
                        looping.sendall(b"g")
                        looping.close()
                        if mode == "monitor":
                            os.write(master, b"q")
                        else:
                            observer.send_signal(signal.SIGINT)
                        stdout, stderr = observer.communicate(timeout=30)
                        self.assertEqual(observer.returncode, 0, stderr + (stdout or ""))
                        if mode == "monitor":
                            drain.wait(timeout=10)

    def assert_observers_answer(self, revision):
        for args in (["status", "--output", "json"], ["monitor", "--once", "--output", "json"]):
            result = subprocess.run(self.command(revision) +
                                    ["run", *args, "--url", "http://127.0.0.1:1", "--timeout", "0.2"],
                                    env=self.env, capture_output=True, text=True, timeout=30)
            # A closed local endpoint exercises the real client without a network service.
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertFalse(json.loads(result.stdout)["ok"])

    def test_logs_follow_releases_lock_after_preparation_and_on_prepared_source(self):
        root = self.prepare(self.old)
        self.make_terminal(root, f'''
import os
from strata_cli import logs
from strata_cli.client import Endpoint
Endpoint.snapshot = lambda *a, **k: {{
    "instance": {{"id": "fixture"}},
    "activity": {{"available": True, "last_seq": 0, "events": []}}}}
def pause(interval):
    assert not any(key in os.environ for key in (
        "STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT"))
    exec({GATE!r}, {{}})
    raise KeyboardInterrupt
logs.time.sleep = pause
''')
        # Published but unapplied overlay: the first observer must prepare under the lock.
        subprocess.run(["git", "-C", str(root.parent), "apply", "--reverse", SOURCE_PATCH],
                       env=self.env, check=True)
        for phase in ("preparation-required", "already-prepared"):
            with self.subTest(phase=phase):
                process, pid, peer = self.gated_process(self.command(self.old) + [
                    "run", "logs", "--follow", "--url", "http://127.0.0.1:1"])
                self.assertEqual(pid, process.pid)
                self.assertIsNone(process.poll())
                self.assert_workspace_unlocked()
                peer.sendall(b"q")
                process.communicate(timeout=30)

    def test_terminal_service_releases_lock_and_observers_answer(self):
        root = self.prepare(self.old)
        self.make_terminal(root, f'''
from serve import server
def service(args, **kwargs):
    exec({GATE!r}, {{}})
    return 0
server.main = service
''')
        self.make_runtime_model(root)
        process, pid, peer = self.gated_process(self.command(self.old) +
            ["run", "serve", "--config", str(root / "strata-fixture.json"), "--engine", "mock"])
        self.assertEqual(pid, process.pid)
        self.assert_workspace_unlocked()
        self.assert_observers_answer(self.old)
        peer.sendall(b"q")
        process.wait(timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr.read())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux installer")
    def test_install_update_reenters_managed_refresh_and_validates_runtime(self):
        root = self.make_updater_workspace()
        self.make_terminal(root)
        alias = self.base / "managed source alias"
        alias.symlink_to(root, target_is_directory=True)
        self.env["STRATA_INSTALL_DIR"] = str(alias)
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.old + "\n")
        (root.parent / ".git/strata-engine-rollback.json").write_text("{}")
        command = self.command(self.old) + ["run", "install", "--update", "--build"]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text(), self.old + "\n")
        self.assertEqual((root / "update-attempts").read_text(), "1")
        self.assertFalse((root.parent / ".git/strata-engine-rollback.json").exists())
        (root / "tokenizer/vocab.json").unlink()
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=90)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux installer")
    def test_install_setup_preserves_directory_defaults_cli_values_and_option_values(self):
        root = self.make_acquisition_workspace()
        self.make_terminal(root)
        data, models, override = (self.base / name for name in ("install data", "default GGUF", "CLI GGUF"))
        env = dict(self.env, TEST_DATA_DIRECTORY=str(data), TEST_MODELS_DIRECTORY=str(models))
        result = subprocess.run(self.command(self.old) +
            ["run", "install", "--yes", "--no-browser", "--context", "8192", "--vision", "no",
             "--experimental-speed-projection", "off", "--models-dir", str(override), "--api-key=--version"],
            env=env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads((root / "destinations.json").read_text())
        self.assertEqual(Path(actual["data"]), data)
        self.assertEqual(Path(actual["models"]).parent, override)
        self.assertEqual(actual["api_key"], "--version")
        self.assertFalse(models.exists())
        self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())

    def test_cold_external_install_help_uses_terminal_parser_without_bootstrap(self):
        root = self.prepare(self.old)
        external = self.base / "cold external install"
        external.mkdir()
        shutil.copyfile(Path(UPSTREAM) / "setup.py", external / "setup.py")
        shell = (UPSTREAM_SOURCE / "setup.sh").read_text()
        shell = shell.replace('cd "$(dirname "$0")" || exit 1',
                              'cd "$(dirname "$0")" || exit 1\n'
                              'printf forbidden > acquisition-attempted\nexit 79')
        (external / "setup.sh").write_text(shell)
        env = dict(self.env, STRATA_INSTALL_DIR=str(external), STRATA_NO_ACQUIRE="1", PIP_NO_INDEX="1")
        command = self.command(self.old) + ["run", "install"]
        for help_flag in ("--help", "-h", "--h", "--he", "--hel"):
            for args in (["--update", help_flag], [help_flag, "--update"],
                         ["--family", "qwen4-test", help_flag],
                         ["--api-key=--help", "--update", help_flag]):
                with self.subTest(args=args):
                    result = subprocess.run(command + args, env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("usage: strata install", result.stdout)
                    self.assertIn("--update", result.stdout)
                    self.assertNotIn("--context", result.stdout)
                    self.assertFalse((external / "acquisition-attempted").exists())
                    self.assertFalse((external / ".venv").exists())
                    self.assertFalse((root / ".venv").exists())
        for flag in ("--help=invalid", "--hel=invalid", "-h=invalid"):
            with self.subTest(flag=flag):
                result = subprocess.run(command + ["--update", flag], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse((external / "acquisition-attempted").exists())
                self.assertFalse((external / ".venv").exists())
        self.run_source_script(root, '''
import contextlib, io
from strata_cli.cli import parse_args
import setup
for raw, expected in ((["install", "--api-key=--help"], ["--api-key=--help"]),
                      (["install", "--update", "--", "--help"], ["--", "--help"]),
                      (["install", "--", "--hel"], ["--", "--hel"])):
    with contextlib.redirect_stdout(io.StringIO()) as output:
        a = parse_args(raw)
    assert not output.getvalue()
    assert a.raw_argv == raw
    assert a.setup_args == expected
    if expected[0] == "--":
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            try:
                setup.main(a.setup_args, after_parse=lambda *_: (_ for _ in ()).throw(
                    AssertionError("separator syntax reached operational setup")))
            except SystemExit as error:
                assert error.code == 2
                assert not output.getvalue()
            else:
                raise AssertionError("separator was interpreted as help")
''')

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux installer")
    def test_external_install_owns_runtime_engine_and_private_environment(self):
        root = self.make_updater_workspace()
        self.make_terminal(root, '''
import os
os.environ["TEST_PARENT_LOCK_FD"] = os.environ["STRATA_WORKSPACE_LOCK_FD"]
''')
        external = self.base / "external install with spaces"
        shutil.copytree(root, external, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
        subprocess.run([sys.executable, "-m", "venv", str(external / ".venv")],
                       env=self.env, check=True)
        self.make_runtime_model(external)
        (external / "requirements.txt").write_text("external_probe==1.0\n")
        wheel = self.base / "external_probe-1.0-py3-none-any.whl"
        files = {
            "external_probe/__init__.py": "VALUE = 'external runtime'\n",
            "external_probe-1.0.dist-info/METADATA": (
                "Metadata-Version: 2.1\nName: external-probe\nVersion: 1.0\n"),
            "external_probe-1.0.dist-info/WHEEL": (
                "Wheel-Version: 1.0\nGenerator: strata-check\nRoot-Is-Purelib: true\nTag: py3-none-any\n"),
        }
        files["external_probe-1.0.dist-info/RECORD"] = "".join(f"{name},,\n" for name in files)
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        candidate = self.base / "local engine"
        candidate.mkdir()
        (candidate / "strata").write_text("external replacement")
        (candidate / "strata").chmod(0o700)
        (candidate / "BUILD.json").write_text('{"version":"0.1.46","source":"prebuilt"}')
        (external / "setup-fixture.py").write_text('''
import fcntl, json, os, sys
from pathlib import Path
import setup
assert Path(sys.prefix) == setup.ROOT / ".venv", sys.prefix
for key in ("STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT", "STRATA_WORKSPACE_LOCK_FD",
            "STRATA_BOOTSTRAP_ONLY", "STRATA_RUNTIME_READY"):
    assert key not in os.environ, key
lock_path = Path(os.environ["TEST_WORKSPACE_LOCK_PATH"])
try:
    inherited = os.fstat(int(os.environ["TEST_PARENT_LOCK_FD"]))
except OSError:
    pass
else:
    expected = lock_path.stat()
    assert (inherited.st_dev, inherited.st_ino) != (expected.st_dev, expected.st_ino)
with lock_path.open("a") as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        raise AssertionError("external child released the parent's workspace lock")
original_update = setup.update_install
def update(have, a):
    assert a.data_dir is None
    assert a.models_dir != os.environ["TEST_MODELS_DIRECTORY"]
    assert not a.separate_model_artifacts
    result = original_update(have, a)
    import external_probe
    assert external_probe.VALUE == "external runtime"
    return result
setup.update_install = update
setup.update_installed_engine = lambda url: setup.install_unpacked(Path(url), setup.engine_dir())
original_upgrade = setup.upgrade_config
def upgrade(path, cfg):
    cfg = original_upgrade(path, cfg)
    cfg["external_updated"] = True
    setup.write_config(path, cfg)
    return cfg
setup.upgrade_config = upgrade
sys.exit(setup.main())
''')
        wrapper = external / "setup.sh"
        wrapper.write_text((UPSTREAM_SOURCE / "setup.sh").read_text())
        source = external / "setup.py"
        entry = '\nif __name__ == "__main__":\n'
        source.write_text(source.read_text().replace(entry, '''
if __name__ == "__main__":
    sys.modules["setup"] = sys.modules[__name__]
    exec((ROOT / "setup-fixture.py").read_text().partition("sys.exit(setup.main())")[0])
''' + entry, 1))
        # A bundle-shaped managed checkout must not put an external source install in Control mode.
        (root / "python").mkdir()
        (root / "VERSION").write_text("managed bundle shape\n")
        (root.parent / ".git/strata-runtime-revision").write_text(self.old + "\n")
        (root.parent / ".git/strata-engine-rollback.json").write_text('{"caller":"preserved"}')
        (root / ".venv/.strata-pip.json").write_text('["managed-only"]')
        paths = [root / "strata-fixture.json", root.parent / ".git/strata-runtime-revision",
                 root.parent / ".git/strata-engine-rollback.json", root / ".venv/.strata-pip.json",
                 *[p for p in (root / "engine").rglob("*") if p.is_file()]]
        expected = {p: p.read_bytes() for p in paths}
        env = dict(self.env, STRATA_INSTALL_DIR=os.path.relpath(external, self.base),
                   TEST_WORKSPACE_LOCK_PATH=str(self.state / ".source.lock"),
                   TEST_DATA_DIRECTORY=str(self.base / "unused managed data"),
                   TEST_MODELS_DIRECTORY=str(self.base / "unused managed models"),
                   STRATA_BOOTSTRAP_ONLY="1", STRATA_RUNTIME_READY=str(root),
                   PIP_NO_INDEX="1", PIP_FIND_LINKS=str(self.base), PYTHONNOUSERSITE="1")
        command = self.command(self.old) + ["run", "install", "--update", "--prebuilt", str(candidate)]
        for mode in ("wrapper", "runtime"):
            with self.subTest(mode=mode):
                if mode == "runtime":
                    wrapper.unlink()
                    (external / "engine/strata").write_text("replace again")
                    (candidate / "strata").write_text("external replacement")
                    (candidate / "strata").chmod(0o700)
                    (candidate / "BUILD.json").write_text('{"version":"0.1.46","source":"prebuilt"}')
                result = subprocess.run(command, env=env, cwd=self.base,
                                        capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((external / "engine/strata").read_text(), "external replacement")
                self.assertTrue(json.loads((external / "strata-fixture.json").read_text())["external_updated"])
                self.assertIn("external_probe==1.0",
                              json.loads((external / ".venv/.strata-pip.json").read_text()))
                self.assertEqual({p: p.read_bytes() for p in paths}, expected)
                self.assertFalse((root / "update-attempts").exists())
                self.assertFalse(any((root / ".venv/lib").glob("*/site-packages/external_probe")))
                self.assertFalse((self.base / "unused managed data").exists())
                self.assertFalse((self.base / "unused managed models").exists())
        missing = self.base / "external without runtime"
        missing.mkdir()
        shutil.copyfile(external / "setup.py", missing / "setup.py")
        result = subprocess.run(command, env=dict(env, STRATA_INSTALL_DIR=str(missing)), cwd=self.base,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertIn("no setup.sh or executable runtime", result.stderr)
        self.assertEqual({p: p.read_bytes() for p in paths}, expected)

    def assert_mutator_child_keeps_lock(self, command, *, intermediate=None):
        process, child_pid, peer = self.gated_process(command)
        self.assertNotEqual(child_pid, process.pid)
        self.assert_workspace_locked()
        observer = subprocess.Popen(self.command(self.old), env=self.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup_observer():
            if observer.poll() is None:
                observer.kill()
            observer.communicate(timeout=10)
        self.addCleanup(cleanup_observer)
        self.assertRaises(subprocess.TimeoutExpired, observer.wait, timeout=0.2)
        self.assert_observers_answer(self.old)
        process.kill()
        process.wait(timeout=30)
        if intermediate is not None:
            os.kill(int(intermediate.read_text()), signal.SIGKILL)
        self.assert_workspace_locked()
        peer.sendall(b"q")
        peer.close()
        stdout, stderr = observer.communicate(timeout=30)
        self.assertEqual(observer.returncode, 0, stderr)
        self.assertEqual(Path(stdout.strip()), (self.state / "source/terminal").resolve())
        self.assert_workspace_unlocked()

    def test_install_mutation_child_keeps_lock_after_helper_dies(self):
        root = self.prepare(self.old)
        self.make_terminal(root)
        self.make_runtime_model(root)
        gate = self.base / "install-gate.py"
        gate.write_text(GATE)
        (setup_wrapper(root)).write_text(f'exec "{sys.executable}" "{gate}"\n')
        self.assert_mutator_child_keeps_lock(self.command(self.old) + ["run", "install", "--update"])

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux launcher")
    def test_launch_model_nested_mutator_keeps_lock_after_parents_die(self):
        root = self.prepare(self.old)
        installer = self.base / "launch-installer"
        installer.mkdir()
        gate = root / "tools/launch-gate.py"
        gate.write_text(GATE)
        intermediate = self.base / "installer-pid"
        (installer / "setup.py").write_text(f'''
import importlib.util, os, sys
from pathlib import Path
sys.path.insert(0, {str(root)!r})
Path({str(intermediate)!r}).write_text(str(os.getpid()))
spec = importlib.util.spec_from_file_location("managed_installer", {str(root / "setup.py")!r})
setup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = setup
spec.loader.exec_module(setup)
setup.run([sys.executable, {str(gate)!r}])
''')
        self.make_terminal(root, f'''
from types import SimpleNamespace
from strata_cli.launch.runner import Runner
from strata_cli.launch.settings import LaunchSettings
original_run = cli._run
def run(a):
    if a.command != "launch":
        return original_run(a)
    catalog = SimpleNamespace(src=Path({str(installer)!r}), root=Path({str(root)!r}), rows=lambda: [])
    catalog.launch_directories = lambda *args, **kwargs: SimpleNamespace(elsewhere=(), moving_sources=())
    catalog.mcp = SimpleNamespace(install_progress=lambda lines: {{}}, combined_progress=lambda progress, job: progress)
    runner = Runner(LaunchSettings(family="qwen", model="IQ3_S"), catalog=catalog)
    runner.check_own_files = lambda: None
    runner.resolved_vision = lambda: None
    runner.installed_state = lambda: (None, None)
    runner.intel_chosen = lambda: False
    runner.beside_refused = lambda: None
    runner.multi_file = lambda: True
    runner.setup_args = lambda: ["--setup"]
    runner.progress_job = lambda **kwargs: {{}}
    runner.ensure_model()
    return 0
cli._run = run
''')
        self.assert_mutator_child_keeps_lock(self.command(self.old) + ["run", "launch"],
                                             intermediate=intermediate)

    def test_launch_engine_mutator_keeps_lock_after_parent_dies(self):
        root = self.prepare(self.old)
        gate = self.base / "engine-gate.py"
        gate.write_text(GATE)
        self.make_terminal(root, f'''
from strata_cli.launch.runner import Runner
from strata_cli.launch.settings import LaunchSettings
from strata_control import engine_component
original_run = cli._run
def run(a):
    if a.command != "launch":
        return original_run(a)
    engine_component.status = lambda *args: {{"usable": False}}
    runner = Runner(LaunchSettings(family="qwen", model="IQ3_S"))
    runner.warn_wsl_amd = lambda: None
    runner.multi_file = lambda: False
    runner.model_shape = lambda: None
    runner._cli = lambda *args: [sys.executable, {str(gate)!r}]
    runner.ensure_engine()
    return 0
cli._run = run
''')
        self.assert_mutator_child_keeps_lock(self.command(self.old) + ["run", "launch"])

    def test_monitor_update_workers_lock_both_doors_and_release_after_failure(self):
        self.monitor_update_worker_case()

    def test_monitor_update_uses_cached_retirement_after_source_rollback(self):
        self.monitor_update_worker_case(rollback_source=True)

    def monitor_update_worker_case(self, *, rollback_source=False):
        if rollback_source:
            # The source publisher removes a module the live monitor's native updater imports later.
            (self.repo / "strata_control/retired.py").unlink()
            rollback_revision = self.commit()
        observed_revision = rollback_revision if rollback_source else self.old
        for door in ("launch", "monitor"):
            with self.subTest(door=door):
                self.state = self.base / door
                root = self.prepare(self.old)
                old_engine = root / "components/engine/1.0-linux-x86_64-cuda/strata"
                new_engine = old_engine.parent.parent / "2.0-linux-x86_64-cuda/strata"
                new_engine.parent.mkdir(parents=True)
                new_engine.write_bytes(b"engine=0.1.46\n")
                (root / "launch-model.json").write_text(json.dumps({"exe": str(old_engine), "args": ["--parallel", "1"]}))
                self.make_terminal(root, f'''
import contextlib, fcntl, json, os, socket, threading, types
from strata_control import acquisition, cfg_paths, engine_update, profiles, runtime, updater
# Replace rendering only; keep LaunchMonitor, its worker and both command entry points.
for name in ("textual", "textual.app", "textual.binding", "textual.widgets", "rich", "rich.text",
             "strata_cli.monitor", "strata_cli.overview", "strata_cli.launch.screens", "strata_cli.launch.widgets"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["textual.app"].App = object
sys.modules["textual.binding"].Binding = lambda *args, **kwargs: None
sys.modules["textual.widgets"].Static = object
sys.modules["rich.text"].Text = object
screens = sys.modules["strata_cli.launch.screens"]
for name in ("AccessScreen", "AdvancedScreen", "CardsScreen", "ConfirmScreen", "ContextScreen",
             "DraftingScreen", "FolderScreen", "ModelScreen", "ParallelScreen", "PicturesScreen",
             "RunScreen", "SaveScreen", "StartScreen", "TuningScreen", "flow_for"):
    setattr(screens, name, object)
widgets = sys.modules["strata_cli.launch.widgets"]
widgets.CSS, widgets.Glyphs, widgets.DARK, widgets.LIGHT = "", object, None, None
protocol = ("STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT")
state = Path({str(self.state)!r})
config = Path({str(root / "launch-model.json")!r})
old = Path({str(root / "components/engine/1.0-linux-x86_64-cuda/strata")!r})
new = old.parent.parent / "2.0-linux-x86_64-cuda" / old.name
os.environ["STRATA_COMPONENTS_DIR"] = str(old.parent.parent.parent)
def assert_locked():
    with (state / ".source.lock").open("a") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        raise AssertionError("monitor mutation lost workspace lock")
class MonitorBase:
    def __init__(self, *args, **kwargs):
        self.closing, self.is_mounted, self.view = False, False, 0
    def call_from_thread(self, function):
        function()
    def _paint(self):
        pass
    def run(self):
        assert self.workspace_state == str(state), (self.workspace_state, str(state), {{key: os.environ.get(key) for key in protocol}})
        assert not any(key in os.environ for key in protocol)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(os.environ["GATE_SOCKET"])
        listener.listen(1)
        with open(os.environ["GATE_READY"], "w") as ready:
            ready.write(str(os.getpid()))
        with listener.accept()[0] as peer:
            peer.sendall(b"r")
            assert peer.recv(1) == b"b"
            self._update_worker()
            assert "workspace is busy" in self.selection_notice
            assert not self.updating
            assert not any(key in os.environ for key in protocol)
            peer.sendall(b"b")
            assert peer.recv(1) == b"u"
            if {rollback_source!r}:
                assert not (Path({str(root)!r}) / "strata_control/retired.py").exists()
            reached, resume = threading.Event(), threading.Event()
            atomic = profiles._atomic
            def publish(path, data):
                assert_locked()
                reached.set()
                assert resume.wait(90), "test did not release config publication"
                atomic(path, data)
            profiles._atomic = publish
            engine_update.build_context = lambda *args: types.SimpleNamespace()
            model = types.SimpleNamespace(profile="fixture", label="fixture", to_dict=lambda: {{"name": "fixture"}})
            def update(ctx, **kwargs):
                assert_locked()
                with updater.update_lock(config.parent):
                    ctx.gate.stopped = [model]
                    notes, problems = cfg_paths.repair([config])
                    assert len(notes) == 1 and not problems, (notes, problems)
                    assert json.loads(config.read_text())["exe"] == str(new)
                    raise updater.UpdateError("fixture update failure after mutation")
            updater.run_update = update
            runtime._repair_config_paths = lambda *args: (None, None)
            runtime._check_start_candidate = lambda *args: ({{}}, [])
            runtime._engine_preflight = lambda *args: None
            runtime._paths = lambda *args: (None, None, config.parent / "runtime.log")
            profiles._lock = lambda *args: contextlib.nullcontext()
            runtime.procs.end_leftovers = lambda **kwargs: None
            runtime._await_start = lambda *args: {{}}
            children = []
            runtime._read_state = lambda *args, pending_ok=False: {{}} if children else None
            popen = __import__("subprocess").Popen
            def spawn(command, **kwargs):
                fd = int(os.environ["STRATA_WORKSPACE_LOCK_FD"])
                assert not os.get_inheritable(fd)
                code = ("import os; assert not any(k in os.environ for k in " + repr(protocol) + "); "
                        "fd=" + str(fd) + "; identity=" + repr((os.fstat(fd).st_dev, os.fstat(fd).st_ino)) + "\\n"
                        "try: st=os.fstat(fd)\\n"
                        "except OSError: pass\\n"
                        "else: assert (st.st_dev, st.st_ino) != identity\\n")
                child = popen([sys.executable, "-c", code], **kwargs)
                children.append(child)
                return child
            def restart(model):
                assert_locked()
                __import__("subprocess").Popen = spawn
                try:
                    runtime.start("fixture", wait=0)
                    assert children[0].wait(timeout=30) == 0
                finally:
                    __import__("subprocess").Popen = popen
                assert_locked()
                return True, "fixture restarted"
            engine_update.start_model = restart
            self._ask_from_thread = lambda *args: True
            self.action_update_engine()
            assert reached.wait(30)
            peer.sendall(b"w")
            assert peer.recv(1) == b"p"
            resume.set()
            for thread in threading.enumerate():
                if thread.name == "strata-engine-update":
                    thread.join(30)
                    assert not thread.is_alive()
            assert not self.updating
            assert "fixture update failure" in self.selection_notice
            assert not any(key in os.environ for key in protocol)
            assert self.next_poll_at == 0.0
            assert (config.parent / "runtime.log").exists()
            profiles._atomic = atomic
            # A later update still works after the failed one and its model restart.
            updater.run_update = lambda ctx, **kwargs: {{"exit_code": 0, "results": []}}
            peer.sendall(b"f")
            assert peer.recv(1) == b"u"
            self._update_worker()
            assert self.selection_notice == "Nothing needed updating.", self.selection_notice
            peer.sendall(b"d")
            assert peer.recv(1) == b"q"
sys.modules["strata_cli.monitor"].MonitorApp = MonitorBase
original_run = cli._run
def run(a):
    if a.command == "launch":
        from strata_cli.launch.app import run_monitor
        return run_monitor({{"url": "http://127.0.0.1:1", "port": 1}})
    if a.command == "monitor" and not a.once:
        sys.stdout.isatty = lambda: True
    return original_run(a)
cli._run = run
''')
                process, pid, peer = self.gated_process(self.command(self.old) +
                    ["run", door, "--url", "http://127.0.0.1:1"] if door == "monitor" else
                    self.command(self.old) + ["run", door])
                peer.settimeout(60)
                self.assertEqual(pid, process.pid)
                self.assert_workspace_unlocked()
                if rollback_source:
                    self.assertEqual(self.prepare(rollback_revision), root)
                    self.assertFalse((root / "strata_control/retired.py").exists())
                with (self.state / ".source.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    peer.sendall(b"b")
                    self.assertEqual(peer.recv(1), b"b")
                    self.assert_observers_answer(observed_revision)
                peer.sendall(b"u")
                self.assertEqual(peer.recv(1), b"w")
                self.assert_workspace_locked()
                contender = subprocess.Popen(self.command(observed_revision), env=self.env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                def cleanup_contender(process=contender):
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=10)
                self.addCleanup(cleanup_contender)
                self.assertRaises(subprocess.TimeoutExpired, contender.wait, timeout=0.2)
                self.assert_observers_answer(observed_revision)
                peer.sendall(b"p")
                response = peer.recv(1)
                if response != b"f":
                    stdout, stderr = process.communicate(timeout=30)
                    self.fail(f"Monitor worker stopped before completion: {stdout}\n{stderr}")
                stdout, stderr = contender.communicate(timeout=30)
                self.assertEqual(contender.returncode, 0, stderr)
                self.assertEqual(Path(stdout.strip()), root)
                # Let the queued prepare finish before testing a later successful monitor update.
                peer.sendall(b"u")
                self.assertEqual(peer.recv(1), b"d")
                self.assert_workspace_unlocked()
                from importlib.util import module_from_spec, spec_from_file_location
                spec = spec_from_file_location("test_workspace", WORKSPACE)
                workspace = module_from_spec(spec)
                spec.loader.exec_module(workspace)
                with workspace.workspace_lock(self.state):
                    # The queued launch can now publish its settings without a stale update overwriting them.
                    config = root / "launch-model.json"
                    actual = json.loads(config.read_text())
                    actual["args"] = ["--parallel", "8"]
                    subprocess.run([sys.executable, "-c",
                        "import json,sys; from pathlib import Path; "
                        "from strata_cli.launch.runner import write_private; "
                        "write_private(Path(sys.argv[1]), json.loads(sys.argv[2]))",
                        str(config), json.dumps(actual)], cwd=root, env=self.env, check=True, timeout=10)
                peer.sendall(b"q")
                process.wait(timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr.read())
                self.assertEqual(json.loads(config.read_text())["args"], ["--parallel", "8"])

    def make_intel_boundary(self, root, body):
        original = root.parent / "engine/sycl/setup_intel.py"
        original.rename(root.parent / "engine/sycl/intel_real.py")
        original.write_text(f'''
import importlib.util, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "terminal"))
import setup as S
fd = int(os.environ["STRATA_WORKSPACE_LOCK_FD"])
identity = os.stat(Path({str(self.state)!r}) / ".source.lock")
inherited = os.fstat(fd)
assert (inherited.st_dev, inherited.st_ino) == (identity.st_dev, identity.st_ino)
assert os.getpid() == int(os.environ["INTEL_SETUP_PID"])
assert sys.argv[1:] == ["--fixture"]
spec = importlib.util.spec_from_file_location("intel_real", Path(__file__).with_name("intel_real.py"))
intel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intel)
# Restore the tracked patch target before any queued launcher checks patch ownership.
Path(__file__).write_bytes(Path(__file__).with_name("intel_real.py").read_bytes())
intel.intel_gpus = lambda: [{{"driver": "xe", "devid": "e223", "vram_gb": 32}}]
intel.sycl_engine = lambda: (Path("/fixture/strata"), None)
intel.sycl_version = lambda: "fixture"
S.ram_gb = lambda: 64
{body}
intel.install(sys.argv[1:])
''')

    def intel_command(self, root, fd, backend):
        return [sys.executable, "-c", f'''
import fcntl, json, os, sys
from pathlib import Path
sys.path.insert(0, {str(root)!r})
import setup
lock = os.open({str(self.state / ".source.lock")!r}, os.O_RDWR)
fcntl.flock(lock, fcntl.LOCK_EX)
if lock != {fd}:
    os.dup2(lock, {fd})
    os.close(lock)
os.set_inheritable({fd}, True)
os.environ.update(STRATA_WORKSPACE_LOCK_FD=str({fd}), STRATA_WORKSPACE_HELPER="fixture",
                  STRATA_WORKSPACE_CONTEXT=json.dumps({{"state": {str(self.state)!r}}}),
                  INTEL_SETUP_PID=str(os.getpid()))
setup.sycl_setup({backend!r} + ["--fixture"])
raise AssertionError("SYCL handoff returned instead of replacing setup")
''']

    def test_sycl_exec_preserves_low_and_high_lock_fds_and_mutating_children(self):
        for fd, backend in ((3, ["--backend", "sycl"]), (100, ["--backend=sycl"])):
            with self.subTest(fd=fd):
                self.state = self.base / str(fd)
                root = self.prepare(self.old)
                self.make_terminal(root)
                gate = root / "tools/intel-gate.py"
                gate.write_text('''
import os
from pathlib import Path
fd = int(os.environ["STRATA_WORKSPACE_LOCK_FD"])
actual = os.fstat(fd)
expected = os.stat(Path(__file__).resolve().parents[3] / ".source.lock")
assert (actual.st_dev, actual.st_ino) == (expected.st_dev, expected.st_ino)
''' + GATE)
                self.make_intel_boundary(root, f'''
def main():
    return S.run([sys.executable, {str(gate)!r}]).returncode
S.main = main
''')
                self.assert_mutator_child_keeps_lock(self.intel_command(root, fd, backend))

    def test_sycl_service_drops_protocol_without_unlocking_surviving_mutator(self):
        root = self.prepare(self.old)
        self.make_terminal(root)
        child_socket = self.base / "intel-child.sock"
        child = root / "tools/intel-survivor.py"
        child.write_text(f'''
import os, socket
fd = int(os.environ["STRATA_WORKSPACE_LOCK_FD"])
assert os.fstat(fd).st_ino == os.stat({str(self.state / ".source.lock")!r}).st_ino
listener = socket.socket(socket.AF_UNIX)
listener.bind({str(child_socket)!r})
listener.listen(1)
print("ready", flush=True)
with listener.accept()[0] as peer:
    peer.sendall(b"r")
    peer.recv(1)
''')
        service = root / "tools/intel-service.py"
        service.write_text('''
import os
assert not any(key in os.environ for key in (
    "STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT"))
assert os.getpid() == int(os.environ["INTEL_SETUP_PID"])
try:
    actual = os.fstat(100)
except OSError:
    pass
else:
    raise AssertionError("service inherited acquisition FD")
''' + GATE)
        (root / "run-fixture.sh").write_text(f'exec "{sys.executable}" "{service}"\n')
        config = root / "strata-fixture.json"
        config.write_text('{"backend": "sycl"}')
        self.make_intel_boundary(root, f'''
import subprocess
def main():
    child = subprocess.Popen([sys.executable, {str(child)!r}], pass_fds=S.acquisition.workspace_fds(),
                             stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "ready"
    S.start(Path({str(config)!r}))
    raise AssertionError("service handoff returned")
S.main = main
''')
        process, pid, peer = self.gated_process(self.intel_command(root, 100, ["--backend", "sycl"]))
        self.assertEqual(pid, process.pid)
        self.assert_workspace_locked()
        self.assert_observers_answer(self.old)
        with socket.socket(socket.AF_UNIX) as survivor:
            survivor.settimeout(10)
            survivor.connect(str(child_socket))
            self.assertEqual(survivor.recv(1), b"r")
            survivor.sendall(b"q")
        self.assert_workspace_unlocked()
        peer.sendall(b"q")
        process.wait(timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr.read())

    def test_sycl_non_sycl_start_keeps_original_delegation(self):
        root = self.prepare(self.old)
        config = root / "strata-fixture.json"
        config.write_text('{"backend": "cpu"}')
        self.make_intel_boundary(root, f'''
def original_start(path, *args, **kwargs):
    assert Path(path) == Path({str(config)!r})
    assert args == ("positional",) and kwargs == {{"open_browser": False}}
    assert S.acquisition.workspace_fds() == (100,)
    assert os.fstat(100).st_ino == identity.st_ino
    return 17
S.start = original_start
S.main = lambda: S.start(Path({str(config)!r}), "positional", open_browser=False)
''')
        result = subprocess.run(self.intel_command(root, 100, ["--backend=sycl"]),
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assert_workspace_unlocked()

    def test_detached_runtime_drops_lock_protocol_without_unlocking_launcher(self):
        root = self.prepare(self.old)
        gate = self.base / "runtime-gate.py"
        gate.write_text('''
import os
assert not any(key in os.environ for key in (
    "STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT"))
''' + GATE)
        self.make_terminal(root, f'''
import contextlib, subprocess
from strata_control import runtime, profiles
original_run = cli._run
def run(a):
    if a.command != "launch":
        return original_run(a)
    runtime._repair_config_paths = lambda *args: (None, None)
    runtime._check_start_candidate = lambda *args: ({{}}, [])
    runtime._engine_preflight = lambda *args: None
    runtime._paths = lambda *args: (None, None, Path({str(self.base / "runtime.log")!r}))
    profiles._lock = lambda *args: contextlib.nullcontext()
    runtime.procs.end_leftovers = lambda **kwargs: None
    children = []
    runtime._read_state = lambda *args, pending_ok=False: {{}} if children else None
    popen = subprocess.Popen
    def spawn(command, **kwargs):
        child = popen([sys.executable, {str(gate)!r}], **kwargs)
        children.append(child)
        return child
    subprocess.Popen = spawn
    try:
        runtime.start("fixture", wait=0)
    finally:
        subprocess.Popen = popen
    return children[0].wait()
cli._run = run
''')
        process, child_pid, peer = self.gated_process(self.command(self.old) + ["run", "launch"])
        self.assertNotEqual(child_pid, process.pid)
        self.assert_workspace_locked()
        process.kill()
        process.wait(timeout=30)
        self.assert_workspace_unlocked()
        self.assert_observers_answer(self.old)
        peer.sendall(b"q")
        peer.close()

    @unittest.skipUnless(sys.platform == "linux", "Detached POSIX runtime source leases")
    def test_async_runtime_hands_source_lease_to_initial_and_restarted_backend(self):
        state = self.state
        for completion in ("ready", "terminated"):
            with self.subTest(completion=completion):
                self.state = state / completion
                root = self.prepare(self.old)
                self.make_terminal(root, '''
import subprocess
from strata_control import acquisition, runtime
runtime._engine_preflight = lambda plan: None
original_popen = subprocess.Popen
def spawn(command, **kwargs):
    child = original_popen(command, **kwargs)
    if "strata_control.runtime" in command:
        (Path(__file__).resolve().parent / "owned-test-host").write_text(str(child.pid))
        # A second reader closes before Popen returns to runtime.start's owning scope.
        # It must not adopt and close the descriptor still owned by that scope.
        with acquisition.source_lease(acquisition.workspace_state()):
            pass
    return child
subprocess.Popen = spawn
''')
                shutil.copyfile(Path(UPSTREAM) / "tools/strata_tokenizer.py", root / "tools/strata_tokenizer.py")
                cfg = self.make_runtime_model(root)
                cfg.update(tokenizer=str(root / "no-tokenizer"), port=0, api_key="none")
                (root / "strata-fixture.json").write_text(json.dumps(cfg))
                gate = self.base / ("runtime-import-" + completion)
                gate.mkdir()
                address = gate / "gate.sock"
                (gate / "sitecustomize.py").write_text('''
import importlib.abc, json, os, socket, sys
from pathlib import Path
if "strata_control.runtime" in sys.orig_argv:
    from strata_cli import cli
    original = cli._launch_plan
    def plan(*args, **kwargs):
        result, argv = original(*args, **kwargs)
        argv[argv.index("--engine") + 1] = "mock"
        return result, argv
    cli._launch_plan = plan
elif "serve.server" in sys.orig_argv:
    class ImportGate(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "strata_control.acquisition":
                sys.meta_path.remove(self)
                state = Path(os.environ["TEST_RUNTIME_STATE"])
                source = os.stat(state / ".source-publication.lock")
                workspace = os.stat(state / ".source.lock")
                inherited = []
                for descriptor in os.listdir("/proc/self/fd"):
                    try:
                        info = os.fstat(int(descriptor))
                    except OSError:
                        continue
                    inherited.append((info.st_dev, info.st_ino))
                payload = {"pid": os.getpid(),
                           "source": (source.st_dev, source.st_ino) in inherited,
                           "workspace": (workspace.st_dev, workspace.st_ino) in inherited,
                           "private": any(k in os.environ for k in (
                               "STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT"))}
                with socket.socket(socket.AF_UNIX) as peer:
                    peer.connect(os.environ["TEST_RUNTIME_GATE"])
                    peer.sendall(json.dumps(payload).encode() + b"\\n")
                    peer.recv(1)
            return None
    sys.meta_path.insert(0, ImportGate())
''')
                env = dict(self.env, PYTHONPATH=os.pathsep.join((str(gate), str(root), UPSTREAM)),
                           HOME=str(gate / "home"), XDG_CONFIG_HOME=str(gate / "config"),
                           XDG_STATE_HOME=str(gate / "state"),
                           TEST_RUNTIME_GATE=str(address), TEST_RUNTIME_STATE=str(self.state))
                created = subprocess.run([sys.executable, "-c",
                    "from strata_control import profiles; profiles.create('source-lease', 'strata-fixture.json')"],
                    cwd=root, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(created.returncode, 0, created.stderr)
                pids = []
                def terminate_owned(pids=pids, owner=root / "owned-test-host"):
                    if owner.exists():
                        pid = int(owner.read_text())
                        if pid not in pids:
                            pids.append(pid)
                    for pid in reversed(pids):
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                self.addCleanup(terminate_owned)
                with socket.socket(socket.AF_UNIX) as listener:
                    listener.bind(str(address))
                    listener.listen(4)
                    listener.settimeout(30)
                    started = subprocess.run(self.command(self.old) + [
                        "run", "runtime", "start", "--profile", "source-lease", "--wait", "0", "--output", "json"],
                        env=env, cwd=self.base, capture_output=True, text=True, timeout=40)
                    self.assertEqual(started.returncode, 0, started.stderr)
                    self.assertEqual(json.loads(started.stdout)["state"], "starting")
                    snapshot = subprocess.run([sys.executable, "-c",
                        "import json; from strata_control import runtime; print(json.dumps(runtime._read_state('source-lease')))"],
                        env=env, cwd=root, capture_output=True, text=True, timeout=30)
                    self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
                    pids.append(json.loads(snapshot.stdout)["host_pid"])
                    for revision in ((self.new, self.old) if completion == "ready" else (self.new,)):
                        peer, _ = listener.accept()
                        peer.settimeout(30)
                        payload = json.loads(peer.recv(4096))
                        pids.append(payload["pid"])
                        self.assertTrue(payload["source"], payload)
                        self.assertFalse(payload["workspace"], payload)
                        self.assertFalse(payload["private"], payload)
                        self.assert_workspace_unlocked()
                        with (self.state / ".source-publication.lock").open("a") as lock:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        writer_script = '''
import contextlib, importlib.util, sys
spec = importlib.util.spec_from_file_location("writer", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original = module.source_publication_lock
@contextlib.contextmanager
def publishing(*args, **kwargs):
    print("publication", flush=True)
    with original(*args, **kwargs) as lock:
        yield lock
module.source_publication_lock = publishing
module.prepare_workspace(sys.argv[2], sys.argv[3], remote=sys.argv[4], source_patch=sys.argv[5])
print("published", flush=True)
'''
                        writer = subprocess.Popen([sys.executable, "-c", writer_script, WORKSPACE,
                            str(self.state), revision, str(self.repository), SOURCE_PATCH],
                            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        self.addCleanup(lambda p=writer: p.poll() is None and p.kill())
                        self.assertEqual(writer.stdout.readline().strip(), "publication")
                        self.assertFalse(select.select([writer.stdout], [], [], 0.2)[0],
                                         "source writer passed a backend that has not imported acquisition")
                        if completion == "terminated":
                            os.kill(payload["pid"], signal.SIGKILL)
                        else:
                            peer.sendall(b"go")
                        peer.close()
                        stdout, stderr = writer.communicate(timeout=40)
                        self.assertEqual(writer.returncode, 0, stderr)
                        self.assertIn("published", stdout)
                        with (self.state / ".source-publication.lock").open("a") as lock:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        if completion == "ready" and revision == self.new:
                            # The owner persists only the state identity; a later native restart reacquires its own reader.
                            ready = subprocess.run([sys.executable, "-c",
                                "import json; from strata_control import runtime; print(json.dumps(runtime._await_start('source-lease', 30)))"],
                                env=env, cwd=root, capture_output=True, text=True, timeout=40)
                            self.assertEqual(ready.returncode, 0, ready.stderr)
                            self.assertTrue(json.loads(ready.stdout)["ok"], ready.stdout)
                            restart = subprocess.Popen([sys.executable, "-c",
                                "import json; from strata_control import runtime; print(json.dumps(runtime.restart('source-lease', timeout=60, startup_wait=30)))"],
                                env=env, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                            self.addCleanup(lambda p=restart: p.poll() is None and p.kill())
                    if completion == "ready":
                        stdout, stderr = restart.communicate(timeout=60)
                        self.assertEqual(restart.returncode, 0, stderr)
                        self.assertTrue(json.loads(stdout)["ok"], stdout)
                        stopped = subprocess.run([sys.executable, "-c",
                            "from strata_control import runtime; runtime.stop('source-lease', timeout=15)"],
                            env=env, cwd=root, capture_output=True, text=True, timeout=25)
                        self.assertEqual(stopped.returncode, 0, stopped.stderr)
                terminate_owned()

    def make_updater_workspace(self):
        root = self.prepare(self.old)
        self.make_runtime_source(root)
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], env=self.env, check=True)
        setup = root / "setup-fixture.py"
        setup.write_text(f'''
import sys
from pathlib import Path
import setup
setup.pip_install = lambda *args, **kwargs: None
original_update = setup.update_install
def update(have, a):
    attempts = setup.ROOT / "update-attempts"
    attempts.write_text(str(int(attempts.read_text()) + 1) if attempts.exists() else "1")
    return original_update(have, a)
setup.update_install = update
def install(url):
    candidate = setup.ROOT / "engine/default" if url == setup.PREBUILT_URL else Path(url)
    if (candidate / "strata").exists():
        setup.install_unpacked(candidate, setup.engine_dir())
setup.update_installed_engine = install
sys.exit(setup.main())
''')
        self.make_runtime_model(root)
        for name, version in ((".previous", "A"), ("default", "C"), ("custom", "D")):
            folder = root / "engine" / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "strata").write_text(version)
            (folder / "strata").chmod(0o700)
            (folder / "BUILD.json").write_text(json.dumps({"version": "0.1.46", "source": "prebuilt"}))
        return root

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_configured_directories_do_not_mutate_installed_plain_start(self):
        root = self.make_updater_workspace()
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.old + "\n")
        destination = self.base / "new downloads"
        models_destination = self.base / "new GGUFs"
        remembered = self.base / "existing models"
        remembered.mkdir()
        model = remembered / "keep.bin"
        model.write_bytes(b"existing model")
        settings = Path(self.env["XDG_CONFIG_HOME"]) / "strata/settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"data_dir": str(remembered), "custom": "keep"}))
        expected_settings = settings.read_bytes()
        expected_config = (root / "strata-fixture.json").read_bytes()
        script = root / "setup-fixture.py"
        script.write_text(script.read_text().replace(
            "sys.exit(setup.main())",
            'setup.engine_update_note = lambda: None\n'
            'setup.start = lambda *args, **kwargs: 0\n'
            'sys.exit(setup.main())',
        ))
        env = dict(self.env, TEST_DATA_DIRECTORY=str(destination),
                   TEST_MODELS_DIRECTORY=str(models_destination))
        for args in (["--no-browser"], ["--no-browser", "--api-key=--setup"]):
            with self.subTest(args=args):
                result = subprocess.run(self.command(self.old) + ["run", "source", *args],
                                        env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(destination.exists())
                self.assertFalse(models_destination.exists())
                self.assertEqual(settings.read_bytes(), expected_settings)
                self.assertEqual((root / "strata-fixture.json").read_bytes(), expected_config)
                self.assertEqual(model.read_bytes(), b"existing model")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_directory_defaults_leave_check_update_and_calibration_to_upstream(self):
        root = self.make_updater_workspace()
        (root.parent / ".git/strata-runtime-revision").write_text(self.old + "\n")
        script = root / "setup-fixture.py"
        script.write_text(script.read_text().replace(
            "sys.exit(setup.main())",
            '''parse = setup.argparse.ArgumentParser.parse_args
def parsed(parser, *args, **kwargs):
    a = parse(parser, *args, **kwargs)
    assert a.data_dir is None and a.models_dir is None
    assert not a.separate_model_artifacts
    (setup.ROOT / "parsed-command").write_text("ok")
    return a
setup.argparse.ArgumentParser.parse_args = parsed
setup.gpus = lambda: sys.exit(0)
setup.engine_update_note = lambda: None
setup.calibrate_config = lambda config: True
sys.exit(setup.main())''',
        ))
        data = self.base / "unused data"
        models = self.base / "unused models"
        env = dict(self.env, TEST_DATA_DIRECTORY=str(data), TEST_MODELS_DIRECTORY=str(models))
        for args in (["--check"], ["--update"], ["--calibrate", "--no-start"], ["--rollback-engine"]):
            with self.subTest(args=args):
                (root / "parsed-command").unlink(missing_ok=True)
                result = subprocess.run(self.command(self.old) + ["run", "source", *args], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "parsed-command").read_text(), "ok")
                self.assertFalse(data.exists())
                self.assertFalse(models.exists())

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
                result = subprocess.run(self.command(self.new) + ["run", "source", *args], env=self.env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "engine/strata").read_text(), "B" if build else "D")
                self.assertEqual((root / "engine/.previous/strata").read_text(), "A" if build else "B")
                self.assertEqual((root / "engine/default/strata").read_text(), "C")
                self.assertEqual((root.parent / ".git/strata-runtime-revision").read_text().strip(), self.new)
                if not build:
                    candidate = root / source
                    (candidate / "strata").write_text("E")
                    (candidate / "strata").chmod(0o700)
                    (candidate / "BUILD.json").write_text(json.dumps({"version": "0.1.46", "source": "prebuilt"}))
                    result = subprocess.run(self.command(self.new) + ["run", "source", *args], env=self.env,
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
                (root.parent / ".git/strata-runtime-revision").write_text(self.old)
                config = (root / "strata-fixture.json").read_bytes()
                result = subprocess.run(self.command(self.new) + ["run", "source", flag], env=self.env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "engine/strata").read_text(), "B")
                self.assertEqual((root / "engine/.previous/strata").read_text(), "A")
                self.assertEqual((root / "engine/default/strata").read_text(), "C")
                self.assertEqual((root / "strata-fixture.json").read_bytes(), config)
                self.assertEqual((root.parent / ".git/strata-runtime-revision").read_text().strip(), self.old)

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux bootstrap; Darwin dispatches to Metal")
    def test_engine_rollback_precedes_pending_runtime_refresh(self):
        state = self.state
        for flag in ("--rollback-engine", "--rollback-eng"):
            with self.subTest(flag=flag):
                self.state = state / flag.removeprefix("--")
                root = self.prepare(self.old)
                setup = setup_wrapper(root)
                setup.write_text(f'''#!{shutil.which("sh")}
cd "$(dirname "$0")" || exit 8
if [ -f terminal/setup.py ]; then cd terminal || exit 8; fi
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
                marker = root.parent / ".git/strata-runtime-revision"
                marker.write_text(self.old)
                command = self.command(self.new) + ["run", "source", flag]
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

    def make_rollback_workspace(self):
        root = self.make_updater_workspace()
        self.prepare(self.new)
        (root / "engine/.previous/BUILD.json").write_text(json.dumps({
            "version": "0.1.45", "source": "prebuilt",
        }))
        (root.parent / ".git/strata-runtime-revision").write_text(self.new)
        config = root / "strata-fixture.json"
        values = json.loads(config.read_text())
        values.update(backend="hip", open_browser=False)
        config.write_text(json.dumps(values))
        self.service_script(root, GATE)
        script = setup_wrapper(root)
        script.write_text(script.read_text().replace(
            f'exec "{sys.executable}"', f'exec "{root / ".venv/bin/python"}"',
        ))
        return root

    def start_rollback_workspace(self, root, *args):
        process, pid, peer = self.gated_process(
            self.command(self.new) + ["run", "source", "--no-browser", *args],
        )
        self.assertEqual(pid, process.pid)
        self.assert_workspace_unlocked()
        peer.sendall(b"q")
        process.wait(timeout=10)
        self.assertEqual(process.returncode, 0)
        peer.close()
        self.assert_workspace_unlocked()

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_calibration_preserves_rollback_and_runtime_certificate(self):
        state = self.state
        for certificate in ("current", "pending", "missing"):
            with self.subTest(certificate=certificate):
                self.state = state / certificate
                root = self.make_rollback_workspace()
                (root / "strata-fixture.json").rename(root / "strata-Q2_0.json")
                script = root / "setup-fixture.py"
                script.write_text(script.read_text().replace(
                    "sys.exit(setup.main())",
                    'def calibrate(config):\n'
                    '    (setup.ROOT / "calibrated-model").write_text(config.name)\n'
                    '    return True\n'
                    'setup.calibrate_config = calibrate\n'
                    'sys.exit(setup.main())',
                ))
                result = subprocess.run(self.command(self.new) + ["run", "source", "--rollback-engine"],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                approval = root.parent / ".git/strata-engine-rollback.json"
                approved = approval.read_bytes()
                marker = root.parent / ".git/strata-runtime-revision"
                if certificate == "pending":
                    marker.write_text(self.old)
                elif certificate == "missing":
                    marker.unlink()
                certified = marker.read_bytes() if marker.exists() else None
                for args in (
                    ["--calibrate", "--no-start"],
                    ["--cal", "--no-st", "--model=Q2_0", "--family=qwen"],
                ):
                    result = subprocess.run(self.command(self.new) + ["run", "source", *args, "--yes"],
                                            env=self.env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((root / "calibrated-model").read_text(), "strata-Q2_0.json")
                    self.assertEqual(approval.read_bytes(), approved)
                    self.assertEqual(marker.read_bytes() if marker.exists() else None, certified)
                    self.assertEqual((root / "engine/strata").read_text(), "A")
                    self.assertFalse((root / "update-attempts").exists())
                self.start_rollback_workspace(root, "--calibrate", "--model=Q2_0", "--family=qwen")
                self.assertEqual((root / "engine/strata").read_text(), "A")
                if certificate == "current":
                    self.assertFalse((root / "update-attempts").exists())
                else:
                    self.assertEqual((root / "update-attempts").read_text(), "1")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_explicit_update_takes_precedence_over_calibration(self):
        root = self.make_rollback_workspace()
        result = subprocess.run(self.command(self.new) + ["run", "source", "--rollback-engine"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            self.command(self.new) + ["run", "source", "--calibrate", "--update",
                                      "--prebuilt=" + str(root / "engine/custom")],
            env=self.env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((root / "engine/strata").read_text(), "D")
        self.assertFalse((root.parent / ".git/strata-engine-rollback.json").exists())
        self.assertEqual((root / "update-attempts").read_text(), "1")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_engine_rollback_survives_normal_launch_and_explicit_update(self):
        state = self.state
        for available, certificate in ((True, "current"), (False, "pending"), (True, "missing")):
            with self.subTest(replacement_available=available, certificate=certificate):
                self.state = state / certificate
                root = self.make_rollback_workspace()
                marker = root.parent / ".git/strata-runtime-revision"
                if certificate == "pending":
                    marker.write_text(self.old)
                elif certificate == "missing":
                    marker.unlink()
                if not available:
                    shutil.rmtree(root / "engine/default")
                result = subprocess.run(self.command(self.new) + ["run", "source", "--rollback-eng"],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                refreshes = 0 if certificate == "current" else 1
                for _ in range(2):
                    self.start_rollback_workspace(root)
                    self.assertEqual((root / "engine/strata").read_text(), "A")
                    if refreshes:
                        self.assertEqual((root / "update-attempts").read_text(), str(refreshes))
                    else:
                        self.assertFalse((root / "update-attempts").exists())
                    self.assertEqual(marker.read_text().strip(), self.new)
                result = subprocess.run(
                    self.command(self.new) + ["run", "source", "--update", "--prebuilt=" + str(root / "engine/custom")],
                    env=self.env, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "engine/strata").read_text(), "D")
                self.assertFalse((root.parent / ".git/strata-engine-rollback.json").exists())
                self.start_rollback_workspace(root)
                self.assertEqual((root / "update-attempts").read_text(), str(refreshes + 1))

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_rollback_approval_does_not_mask_missing_prerequisites(self):
        state = self.state
        for missing in ("tokenizer", "python", "other-engine"):
            with self.subTest(missing=missing):
                self.state = state / missing
                root = self.make_rollback_workspace()
                result = subprocess.run(self.command(self.new) + ["run", "source", "--rollback-engine"],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                if missing == "tokenizer":
                    (root / "tokenizer/vocab.json").unlink()
                elif missing == "python":
                    (root / "requirements.txt").write_text("pip==0\n")
                else:
                    other = root / "engine/other"
                    other.mkdir()
                    (other / "strata").write_text("unapproved")
                    (other / "strata").chmod(0o700)
                    (other / "BUILD.json").write_text(json.dumps({"version": "0.1.45"}))
                    config = json.loads((root / "strata-fixture.json").read_text())
                    config["exe"] = str(other / "strata")
                    (root / "strata-other.json").write_text(json.dumps(config))
                for args in ([], ["--calibrate"]):
                    result = subprocess.run(self.command(self.new) + ["run", "source", "--no-browser", *args],
                                            env=self.env, capture_output=True, text=True, timeout=30)
                    self.assertNotEqual(result.returncode, 0)
                self.assertEqual((root / "engine/strata").read_text(), "A")
                self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())
                self.assertTrue((root.parent / ".git/strata-engine-rollback.json").exists())
                self.assertIn({"tokenizer": "vocab.json", "python": "requires ==0",
                               "other-engine": "engine/other/strata"}[missing], result.stderr)
                # The real updater may repair prerequisites, but must not reacquire the engine.
                self.assertEqual((root / "update-attempts").read_text(), "2")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_failed_or_noop_rollback_does_not_approve_old_engine(self):
        state = self.state
        for noop in (True, False):
            with self.subTest(noop=noop):
                self.state = state / str(noop)
                root = self.make_rollback_workspace()
                (root / "engine/BUILD.json").write_text(json.dumps({
                    "version": "0.1.45", "source": "prebuilt",
                }))
                args = ["--rollback-engine", "--help"] if noop else ["--rollback-engine"]
                if not noop:
                    shutil.rmtree(root / "engine/.previous")
                result = subprocess.run(self.command(self.new) + ["run", "source", *args],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0 if noop else 1)
                self.assertFalse((root.parent / ".git/strata-engine-rollback.json").exists())
                self.start_rollback_workspace(root)
                self.assertEqual((root / "engine/strata").read_text(), "C")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_source_or_payload_change_retires_rollback_approval(self):
        state = self.state
        for change in ("source", "payload", "setup", "failed-update"):
            with self.subTest(change=change):
                self.state = state / change
                root = self.make_rollback_workspace()
                result = subprocess.run(self.command(self.new) + ["run", "source", "--rollback-engine"],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                if change == "source":
                    for revision in (self.old, self.new):
                        result = subprocess.run(self.command(revision) + ["run", "source", "--help"],
                                                env=self.env, capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, 0, result.stderr)
                elif change == "payload":
                    executable = root / "engine/strata"
                    info = executable.stat()
                    executable.write_text("X")
                    os.utime(executable, ns=(info.st_atime_ns, info.st_mtime_ns))
                else:
                    script = setup_wrapper(root)
                    original = script.read_text()
                    script.write_text(f"#!{shutil.which('sh')}\nexit 9\n")
                    flag = "--setu" if change == "setup" else "--update"
                    result = subprocess.run(
                        [sys.executable, WORKSPACE, str(self.state), self.new, "", "", SOURCE_PATCH, "source", flag],
                        env=self.env, capture_output=True, text=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 9, result.stderr)
                    script.write_text(original)
                self.start_rollback_workspace(root)
                self.assertEqual((root / "engine/strata").read_text(), "C")
                self.assertFalse((root.parent / ".git/strata-engine-rollback.json").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_automatic_python_repair_preserves_rolled_back_engine(self):
        root = self.make_rollback_workspace()
        wheel = self.base / "rollback_probe-1.0-py3-none-any.whl"
        files = {
            "rollback_probe/__init__.py": "",
            "rollback_probe-1.0.dist-info/METADATA": (
                "Metadata-Version: 2.1\nName: rollback-probe\nVersion: 1.0\n"
            ),
            "rollback_probe-1.0.dist-info/WHEEL": (
                "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
            ),
        }
        files["rollback_probe-1.0.dist-info/RECORD"] = "".join(f"{name},,\n" for name in files)
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        self.env.update(PIP_NO_INDEX="1", PIP_FIND_LINKS=str(self.base))
        (root / "requirements.txt").write_text("pip\nrollback-probe==1.0\n")
        script = root / "setup-fixture.py"
        script.write_text(script.read_text().replace(
            "setup.pip_install = lambda *args, **kwargs: None\n", "",
        ))
        self.service_script(root, "import rollback_probe\n" + GATE)
        result = subprocess.run(self.command(self.new) + ["run", "source", "--rollback-engine"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.start_rollback_workspace(root)
        self.assertEqual((root / "engine/strata").read_text(), "A")
        self.assertFalse((root / "update-attempts").exists())
        self.assertIn("rollback-probe==1.0", json.loads((root / ".venv/.strata-pip.json").read_text()))
        self.assertEqual((root.parent / ".git/strata-runtime-revision").read_text().strip(), self.new)
        self.start_rollback_workspace(root)
        self.assertEqual((root / "engine/strata").read_text(), "A")
        self.assertFalse((root / "update-attempts").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_rollback_approvals_are_per_toolkit(self):
        root = self.make_rollback_workspace()
        shutil.copytree(root / "engine", root / "engine-cuda12")
        config = json.loads((root / "strata-fixture.json").read_text())
        config["exe"] = str(root / "engine-cuda12/strata")
        (root / "strata-cuda12.json").write_text(json.dumps(config))
        for args in (["--rollback-engine"], ["--rollback-engine", "--cuda=12"]):
            result = subprocess.run(self.command(self.new) + ["run", "source", *args],
                                    env=self.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.start_rollback_workspace(root, "--yes")
        for directory in ("engine", "engine-cuda12"):
            self.assertEqual((root / directory / "strata").read_text(), "A")
        self.assertFalse((root / "update-attempts").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_versionless_rollback_never_certifies_runtime(self):
        root = self.make_rollback_workspace()
        (root / "engine/.previous/BUILD.json").write_text('{"source": "prebuilt"}')
        shutil.rmtree(root / "engine/default")
        result = subprocess.run(self.command(self.new) + ["run", "source", "--rollback-engine"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = subprocess.run(
            [str(root / ".venv/bin/python"), WORKSPACE, "--runtime-status", str(root)],
            env=self.env, cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(status.returncode, 0)
        result = subprocess.run(self.command(self.new) + ["run", "source", "--no-browser"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((root / "engine/strata").read_text(), "A")
        self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_local_rollback_preserves_same_revision_source_checks(self):
        root = self.make_rollback_workspace()
        shutil.copyfile(UPSTREAM_SOURCE / "engine/CMakeLists.txt", root / "CMakeLists.txt")
        (root / "engine/.previous/BUILD.json").write_text(json.dumps({
            "version": "0.1.45", "source": "local", "src": "previous-source", "vision": "none",
        }))
        result = subprocess.run(self.command(self.new) + ["run", "source", "--rollback-engine"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.start_rollback_workspace(root)
        self.assertEqual((root / "engine/strata").read_text(), "A")
        source = root / "CMakeLists.txt"
        source.write_text(source.read_text() + "\n# local source changed\n")
        self.start_rollback_workspace(root)
        self.assertEqual((root / "engine/strata").read_text(), "C")
        self.assertFalse((root.parent / ".git/strata-engine-rollback.json").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_zero_exit_partial_update_retries_same_revision_and_reuses_valid_runtime(self):
        root = self.make_updater_workspace()
        marker = root.parent / ".git/strata-runtime-revision"
        (root / "engine/BUILD.json").write_text(json.dumps({"version": "0.1.12", "source": "prebuilt"}))
        # Missing update source leaves the installed engine unchanged; upstream still returns zero.
        command = self.command(self.new) + ["run", "source", "--prebuilt=missing"]
        config = (root / "strata-fixture.json").read_bytes()
        for attempt in (1, 2):
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
            self.assertEqual((root / "update-attempts").read_text(), str(attempt))
            self.assertEqual((root / "strata-fixture.json").read_bytes(), config)
        valid = self.command(self.new) + ["run", "source", "--update", "--prebuilt=" + str(root / "engine/custom")]
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
        marker = root.parent / ".git/strata-runtime-revision"
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
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text().strip(), self.new)

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
        result = subprocess.run(self.command(self.new) + ["run", "source", "--update", "--build"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(other / "strata"), result.stderr)
        self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())

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

    @unittest.skipUnless(sys.platform == "linux", "Native SYCL wrapper paths")
    def test_selected_sycl_uses_real_engine_and_effective_container_mount(self):
        root = self.make_updater_workspace()
        self.make_terminal(root)
        shutil.copytree(UPSTREAM_SOURCE / "engine/sycl/serve", root.parent / "engine/sycl/serve", copy_function=shutil.copyfile)
        (root.parent / "engine/sycl/serve/strata-sycl.sh").chmod(0o700)
        self.run_source_script(root, '''
import json, os, shutil, subprocess, sys
from pathlib import Path
import setup
sys.path.insert(0, str(setup.engine_src()))
from sycl import setup_intel as intel
from strata_control import doctor
from strata_control.cfg_paths import engine_binary
root = Path.cwd()
engine_root = setup.engine_src()
mount = root.parent.parent / "custom mount"
mount.mkdir()
intel.MOUNT = mount
pack = mount / "pack"
pack.mkdir()
vector = mount / "vector.bin"
vector.write_bytes(b"vector")
exe = engine_root / "custom-build/strata"
exe.parent.mkdir()
exe.write_bytes(b"engine=0.1.46\\n")
exe.chmod(0o700)
# Reader metadata must not stand in for the engine version.
reader = root / "engine-sycl"
reader.mkdir()
(reader / "BUILD.json").write_text('{"version":"0.1.99"}')
cfg = json.loads((root / "strata-fixture.json").read_text())
vision = {}
for key in ("exe", "mmproj", "model"):
    host = reader / key
    host.write_bytes(b"host reader payload")
    vision[key] = str(host)
cfg["vision"] = vision
cfg["args"] = ["--pack", str(pack), "--control-vector-scaled", str(vector) + ":0.5",
               "--max-context", "4096", "--kv", "int8", "--prefill", "2048"]
cfg = intel.to_sycl(cfg, exe, 64, {}, vram_gb=16, driver="xe", fit=False)
mounted_engine = mount / engine_root.name / "custom-build/strata"
mounted_engine.parent.mkdir(parents=True)
mounted_engine.write_bytes(b"engine=0.1.46\\n")
mounted_engine.chmod(0o700)
exe.write_bytes(b"engine=0.1.12\\n")
cfg["args"] += ["--mtp", "2"]
cfg["sycl_root"] = "/descriptive-only"
os.environ["STRATA_SYCL_ROOT"] = "/wrong-ambient-mount"
os.environ["STRATA_SYCL_BIN"] = "wrong-ambient-binary"
assert engine_binary(cfg["exe"], cfg) == str(mounted_engine)
path = root.parent.parent / "external-sycl.json"
path.write_text(json.dumps(cfg))
report = doctor.inspect(path)
assert all(c["status"] == "ok" for c in report["components"] if c["required"]), report
assert next(c["path"] for c in report["components"] if c["name"] == "pack") == str(pack)
for key, value in vision.items():
    assert next(c["path"] for c in report["components"] if c["name"] == "vision/" + key) == value
# Empty saved environment values mask ambient overrides, then the shell uses its defaults.
default_engine = engine_root / "build-sycl-aot/strata"
default_engine.parent.mkdir()
default_engine.write_bytes(b"engine=0.1.46\\n")
default_engine.chmod(0o700)
default_pack = root.parent / "default-pack"
default_pack.mkdir()
saved_env, saved_args = cfg["env"].copy(), cfg["args"].copy()
cfg["env"].update(STRATA_SYCL_ROOT="", STRATA_SYCL_BIN="")
cfg["args"][cfg["args"].index("--pack") + 1] = "/work/default-pack"
# The scale/vector argument still refers to the custom mount; omit it for this default-mount case.
index = cfg["args"].index("--control-vector-scaled")
del cfg["args"][index:index + 2]
path.write_text(json.dumps(cfg))
report = doctor.inspect(path)
assert engine_binary(cfg["exe"], cfg) == str(default_engine)
assert next(c["path"] for c in report["components"] if c["name"] == "pack") == str(default_pack)
assert all(c["status"] == "ok" for c in report["components"] if c["required"]), report
cfg["env"], cfg["args"] = saved_env, saved_args
# Relative engine arguments use the wrapper's cd, not the caller/config directory.
relative = mount / engine_root.name / "relative-pack"
relative.mkdir(parents=True)
cfg["args"][cfg["args"].index("--pack") + 1] = "relative-pack"
path.write_text(json.dumps(cfg))
assert next(c["path"] for c in doctor.inspect(path)["components"] if c["name"] == "pack") == str(relative)
cfg["args"][cfg["args"].index("--pack") + 1] = "/work"
path.write_text(json.dumps(cfg))
assert next(c["path"] for c in doctor.inspect(path)["components"] if c["name"] == "pack") == str(mount)
# Capture the real Bash wrapper's Docker invocation, without Docker or a GPU.
recorders = root.parent.parent / "docker-recorder"
recorders.mkdir()
record = recorders / "invocation.json"
docker = recorders / "docker"
docker.write_text("#!" + sys.executable + "\\nimport json, os, sys\\n"
                  "from pathlib import Path\\n"
                  "if sys.argv[1] == 'run': Path(os.environ['DOCKER_RECORD']).write_text(json.dumps(sys.argv[1:]))\\n")
docker.chmod(0o700)
engine_cwd = root.parent.parent / "engine-cwd"
engine_cwd.mkdir()
cfg["cwd"] = str(engine_cwd)
cfg["env"]["STRATA_SYCL_ROOT"] = os.path.relpath(mount, engine_cwd)
cfg["env"]["STRATA_SYCL_BIN"] = "/work/" + engine_root.name + "/custom-build/strata"
path.write_text(json.dumps(cfg))
assert engine_binary(cfg["exe"], cfg) == str(mounted_engine)
assert next(c["path"] for c in doctor.inspect(path)["components"] if c["name"] == "engine") == str(mounted_engine)
subprocess.run([shutil.which("bash"), cfg["exe"], "--pack", "/work/pack"], cwd=engine_cwd,
               env={**os.environ, **cfg["env"], "PATH": str(recorders) + os.pathsep + os.environ["PATH"],
                    "DOCKER_RECORD": str(record)}, check=True)
command = json.loads(record.read_text())
volume = next(command[i + 1] for i, value in enumerate(command[:-1]) if value == "-v" and command[i + 1].endswith(":/work"))
assert (engine_cwd / volume[:-6]).resolve() == mount
assert command[-1] == "cd /work/" + engine_root.name + " && exec " + cfg["env"]["STRATA_SYCL_BIN"] + " --pack /work/pack"
cfg["env"] = saved_env
cfg["args"][cfg["args"].index("--pack") + 1] = "/work/pack"
path.write_text(json.dumps(cfg))
''')
        selected = self.state / "external-sycl.json"
        reached = self.base / "sycl-serve-reached"
        self.mock_server(root, f'''
from pathlib import Path
api_key_of = lambda key: key
explicit_no_key = lambda key: not key
key_list = lambda key: [key]
engine_args = lambda cfg: cfg["args"]
def main(argv, **kwargs):
    Path({str(reached)!r}).write_text("serve")
    return 0
''')
        result = subprocess.run(self.command(self.old) + ["run", "serve", "--config", str(selected),
                                                         "--engine", "mock", "--port", "0"],
                                env=self.env, cwd=self.base, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(reached.read_text(), "serve")
        saved = selected.read_bytes()
        engine = self.state / "custom mount" / "engine" / "custom-build/strata"
        (root / "engine/custom-build/strata").write_bytes(b"engine=0.1.46\n")
        checker = [str(root / ".venv/bin/python"), WORKSPACE, "--selected-runtime", str(root), str(selected)]
        for payload in (b"engine=0.1.12\n", b"not executable", None):
            with self.subTest(engine=payload):
                if payload is None:
                    engine.unlink()
                else:
                    engine.write_bytes(payload)
                    engine.chmod(0o600 if payload == b"not executable" else 0o700)
                result = subprocess.run(checker, env=self.env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn(str(engine), result.stderr)
        self.assertEqual(selected.read_bytes(), saved)
        engine.write_bytes(b"engine=0.1.46\n")
        engine.chmod(0o700)
        wrapper = root.parent / "engine/sycl/serve/strata-sycl.sh"
        launcher = wrapper.read_bytes()
        wrapper.parent.chmod(wrapper.parent.stat().st_mode | 0o200)
        for failure in ("empty", "nonexecutable", "missing"):
            with self.subTest(launcher=failure):
                if failure == "empty":
                    wrapper.write_bytes(b"")
                elif failure == "nonexecutable":
                    wrapper.chmod(0o600)
                else:
                    wrapper.unlink()
                result = subprocess.run(checker, env=self.env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn(str(wrapper), result.stderr)
                wrapper.write_bytes(launcher)
                wrapper.chmod(0o700)

    @unittest.skipUnless(sys.platform == "linux", "Native split engine executable policy")
    def test_manifest_listed_split_executable_keeps_native_integrity_policy(self):
        root = self.make_updater_workspace()
        engine = root / "engine"
        main, auxiliary, payload = engine / "strata", engine / "strata-split-2", engine / "weights.bin"
        main.write_bytes(b"engine=0.1.46\nmain")
        auxiliary.write_bytes(b"engine=0.1.46\nsplit")
        auxiliary.chmod(0o700)
        payload.write_bytes(b"unrelated payload")
        import hashlib
        manifest = {
            "schema_version": 1, "id": "strata-engine", "version": "0.1.46",
            "platform": "linux-x86_64", "backend": "cpu", "entrypoint": "strata",
            "files": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "bytes": path.stat().st_size} for path in (main, auxiliary, payload)],
        }
        (engine / "engine-component.json").write_text(json.dumps(manifest))
        self.run_source_script(root, '''
import json
from pathlib import Path
from strata_control import engine_component as ec, split_engine
root = Path.cwd()
base = json.loads((root / "strata-fixture.json").read_text())
base["cwd"] = str(root)
native = root / "tiny-native.gguf"
native.write_bytes(b"GGUFfixture")
draft = root / "tiny-draft.pack"
draft.write_bytes(b"draft")
exe = split_engine.exe_finder(base)(2)
assert exe == str(root / "engine/strata-split-2")
cfg = split_engine.split_config(base, split_engine.Decision(True, [], cards=2),
    exe=exe, native=str(native), mtp_dir=None, draft_vocab="en", context=8192,
    dflash2_pack=str(draft))
(root / "selected-split.json").write_text(json.dumps(cfg))
component = ec.read_manifest(root / "engine")
hashed = []
original = ec._hash_settled
def record(path, digest):
    hashed.append(path.name)
    return original(path, digest)
ec._hash_settled = record
ec.verify(component, executable="strata-split-2")
assert hashed == ["strata", "strata-split-2"], hashed
hashed.clear()
ec.verify(component, full=True)
assert hashed == ["strata", "strata-split-2", "weights.bin"], hashed
''')
        selected = root / "selected-split.json"
        checker = [str(root / ".venv/bin/python"), WORKSPACE, "--selected-runtime", str(root), str(selected)]
        result = subprocess.run(checker, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        original = auxiliary.read_bytes()
        for failure in ("tampered", "unlisted", "nonexecutable", "symlink", "main-tampered", "signature", "old"):
            with self.subTest(failure=failure):
                cfg = json.loads(selected.read_text())
                env = self.env
                if failure == "tampered":
                    auxiliary.write_bytes(original[:-1] + b"X")
                elif failure == "unlisted":
                    unlisted = engine / "strata-unlisted"
                    unlisted.write_bytes(original)
                    unlisted.chmod(0o700)
                    cfg["exe"] = str(unlisted)
                elif failure == "nonexecutable":
                    auxiliary.chmod(0o600)
                elif failure == "symlink":
                    auxiliary.unlink()
                    auxiliary.symlink_to(main)
                elif failure == "main-tampered":
                    main.write_bytes(main.read_bytes()[:-1] + b"X")
                elif failure == "signature":
                    env = dict(self.env, STRATA_REQUIRE_SIGNED_COMPONENTS="1")
                elif failure == "old":
                    manifest["version"] = "0.1.12"
                    (engine / "engine-component.json").write_text(json.dumps(manifest))
                selected.write_text(json.dumps(cfg))
                result = subprocess.run(checker, env=env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
                auxiliary.unlink()
                auxiliary.write_bytes(original)
                auxiliary.chmod(0o700)
                main.write_bytes(b"engine=0.1.46\nmain")
                cfg["exe"] = str(auxiliary)
                selected.write_text(json.dumps(cfg))
                manifest["version"] = "0.1.46"
                (engine / "engine-component.json").write_text(json.dumps(manifest))

    def make_runtime_component(self, version):
        import hashlib
        host_platform = "linux-" + os.uname().machine
        directory = Path(self.env["STRATA_COMPONENTS_DIR"]) / "engine" / f"{version}-{host_platform}-cpu"
        directory.mkdir(parents=True, exist_ok=True)
        executable = directory / "strata"
        shutil.copyfile(shutil.which("true"), executable)
        executable.chmod(0o700)
        payload = executable.read_bytes()
        manifest = {
            "schema_version": 1, "id": "strata-engine", "version": version,
            "platform": host_platform, "backend": "cpu", "min_runtime": "0.1.0",
            "entrypoint": "strata",
            "files": [{"path": "strata", "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}],
        }
        (directory / "engine-component.json").write_text(json.dumps(manifest))
        return directory

    def make_component_workspace(self):
        root = self.make_updater_workspace()
        self.prepare(self.new)
        self.env["STRATA_COMPONENTS_DIR"] = str(root.parent / "components")
        # Exercise the resolver's runtime constraint when the Control version is known.
        (root / "VERSION").write_text("0.2.0\n")
        config = json.loads((root / "strata-fixture.json").read_text())
        config.update(exe="component:strata-engine", backend="cpu", open_browser=False)
        (root / "strata-fixture.json").write_text(json.dumps(config))
        return root, self.make_runtime_component("0.1.45")

    @unittest.skipUnless(sys.platform == "linux" and os.uname().machine == "x86_64", "Native CPU component support is Linux x86_64")
    def test_component_reference_preserves_compatibility_and_explicit_pin(self):
        root, lower = self.make_component_workspace()
        self.make_runtime_component("0.1.46")
        resolve = [
            str(root / ".venv/bin/python"), "-c",
            "from strata_control import engine_component as e; print(e.resolve(backend='cpu').version)",
        ]
        result = subprocess.run(resolve, cwd=root, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0.1.46")
        state = Path(self.env["STRATA_COMPONENTS_DIR"]) / ".updates/state.json"
        state.parent.mkdir()
        state.write_text(json.dumps({"engine": {"pinned": lower.name}}))
        result = subprocess.run(resolve, cwd=root, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0.1.45")
        # Optional legacy metadata must not override a usable component manifest.
        (lower / "BUILD.json").write_text("{invalid")
        refresh = [sys.executable, "-c", RUNNER, WORKSPACE, str(root), self.new, "", "refresh"]
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.new)
        for _ in range(2):
            result = subprocess.run(refresh, env=self.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(marker.read_text().strip(), self.new)
            self.assertFalse((root / "update-attempts").exists())

    @unittest.skipUnless(sys.platform == "linux", "Native Linux component fixture")
    def test_component_reference_keeps_prerequisite_and_resolver_rejections(self):
        state = self.state
        for broken in ("runtime", "manifest", "entrypoint", "tokenizer"):
            with self.subTest(broken=broken):
                self.state = state / broken
                root, component = self.make_component_workspace()
                manifest = component / "engine-component.json"
                if broken == "runtime":
                    value = json.loads(manifest.read_text())
                    value["min_runtime"] = "999.0.0"
                    manifest.write_text(json.dumps(value))
                elif broken == "manifest":
                    manifest.write_text("{invalid")
                elif broken == "entrypoint":
                    executable = component / "strata"
                    payload = executable.read_bytes()
                    executable.write_bytes(bytes([payload[0] ^ 1]) + payload[1:])
                else:
                    (root / "tokenizer/vocab.json").unlink()
                marker = root.parent / ".git/strata-runtime-revision"
                marker.write_text(self.new)
                refresh = [sys.executable, "-c", RUNNER, WORKSPACE, str(root), self.new, "", "refresh", "--build"]
                result = subprocess.run(refresh, env=self.env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists())

    @unittest.skipUnless(sys.platform == "linux", "Native Linux component fixture")
    def test_component_reference_does_not_exempt_legacy_alias_in_either_order(self):
        root, component = self.make_component_workspace()
        reference = root / "strata-fixture.json"
        config = json.loads(reference.read_text())
        config["exe"] = str(component / "strata")
        legacy = root / "strata-legacy.json"
        legacy.write_text(json.dumps(config))
        command = [str(root / ".venv/bin/python"), WORKSPACE, "--runtime-status", str(root)]
        for first, second in ((reference, legacy), (legacy, reference)):
            with self.subTest(first=first.name):
                os.utime(first, (20, 20))
                os.utime(second, (10, 10))
                result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("engine version 0.1.45", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_failed_explicit_update_invalidates_existing_same_revision_certificate(self):
        root = self.make_updater_workspace()
        self.prepare(self.new)
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.new)
        receipt = root.parent / ".git/strata-source-refresh-revision"
        receipt.write_text(self.new)
        setup = setup_wrapper(root)
        setup.write_text(f"#!{shutil.which('sh')}\nexit 9\n")
        result = subprocess.run([sys.executable, WORKSPACE, str(self.state), self.new, "", "", SOURCE_PATCH, "source", "--update"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 9)
        self.assertFalse(marker.exists())
        self.assertFalse(receipt.exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_runtime_validation_rejects_missing_and_stale_python_distribution(self):
        root = self.make_updater_workspace()
        command = self.command(self.new) + ["run", "source", "--update", "--build"]
        marker = root.parent / ".git/strata-runtime-revision"
        for requirement, diagnostic in (("strata-missing-runtime==1", "Python package missing"),
                                        ("pip==0", "requires ==0")):
            (root / "requirements.txt").write_text(requirement + "\n")
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(diagnostic, result.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((root.parent / ".git/strata-source-refresh-revision").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_runtime_validation_rejects_failed_local_build_stamp(self):
        root = self.make_updater_workspace()
        shutil.copyfile(UPSTREAM_SOURCE / "engine/CMakeLists.txt", root / "CMakeLists.txt")
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
        result = subprocess.run(self.command(self.new) + ["run", "source", "--update", "--build"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("compiled engine does not match this source", result.stderr)
        self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())


    def gated_process(self, command):
        self.env.pop("STRATA_EXECV", None)
        gate = Path(tempfile.mkdtemp(prefix="gate-", dir=self.base))
        self.addCleanup(shutil.rmtree, gate)
        ready = gate / "ready"
        os.mkfifo(ready)
        descriptor = os.open(ready, os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, descriptor)
        self.env["GATE_READY"] = str(ready)
        self.env["GATE_SOCKET"] = str(gate / "socket")
        process = subprocess.Popen(command, env=self.env, start_new_session=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def cleanup():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=10)

        self.addCleanup(cleanup)
        for _ in range(600):
            readable, _, _ = select.select([descriptor], [], [], 0.2)
            if readable or process.poll() is not None:
                break
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
        (setup_wrapper(root)).write_text(f'exec "{sys.executable}" "{gate}"\n')
        marker = root.parent / ".git/strata-runtime-revision"
        command = self.command(self.new) + ["run", "source"]
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
        setup = setup_wrapper(root)
        setup.write_text(f'#!{shutil.which("sh")}\nexec "{probe}"\n')
        setup.chmod(0o700)
        self.write_terminal(root,
            "import subprocess,sys\nfrom strata_cli import cli\n"
            + f"cli._run = lambda a: subprocess.call([{str(probe)!r}])\n"
            + "raise SystemExit(cli.main())\n")
        cache = self.base / "binary-cache"
        run("nix", "copy", "--to", f"file://{cache}", store)
        run("nix-store", "--delete", store)
        self.assertFalse(os.access(python, os.X_OK))
        self.env["NIX_CONFIG"] += f"substituters = file://{cache}\n"
        result = subprocess.run(self.command(self.new) + ["run", "launch"], env=self.env,
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
        marker = root.parent / ".git/strata-runtime-revision"
        marker.unlink(missing_ok=True)
        failed = subprocess.run(self.command(self.new) + ["run", "launch"], env=self.env,
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
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.new)
        gate = self.base / "updater.py"
        gate.write_text(GATE)
        setup = setup_wrapper(root)
        setup.write_text(f'#!{shutil.which("sh")}\nexec "{sys.executable}" "{gate}"\n')
        setup.chmod(0o700)
        process, child_pid, peer = self.gated_process(self.command(self.new) + ["run", "source"])
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
        (root / "setup-fixture.py").write_text(
            "import setup,sys\nsetup.start = lambda *a, **kw: 0\n"
            "setup.engine_update_note = lambda: None\nsys.exit(setup.main())\n")
        marker = root.parent / ".git/strata-runtime-revision"
        config = root / "strata-user.json"
        allow_success = self.base / "allow-success"
        setup = setup_wrapper(root)
        setup.write_text(f'''#!{shutil.which("sh")}
cd "$(dirname "$0")" || exit 8
if [ -f terminal/setup.py ]; then cd terminal || exit 8; fi
if [ "${{STRATA_BOOTSTRAP_ONLY:-}}" = 1 ] && .venv/bin/python -m pip --version >/dev/null 2>&1; then
    exit 0
fi
if [ "${{STRATA_BOOTSTRAP_ONLY:-}}" = 1 ] || [ "${{1:-}}" = --update ]; then
    "{sys.executable}" -m venv .venv || exit 8
    test -f "{allow_success}" || exit 7
fi
''')
        setup.chmod(0o700)
        command = self.command(self.new) + ["run", "source", "--build", "--no-browser"]
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
    def test_upstream_server_exec_keeps_pid_releases_lock_and_observers_answer(self):
        # Keep the actual setup/start path, not the unrelated C++ tree, docs or Git metadata.
        shutil.copyfile(UPSTREAM_SOURCE / "setup.sh", self.repository / "setup.sh")
        for name in ("requirements.txt", "requirements-monitor.txt"):
            shutil.copyfile(Path(UPSTREAM) / name, self.repo / name)
        shutil.copyfile(UPSTREAM_SOURCE / "engine/CMakeLists.txt", self.repository / "engine/CMakeLists.txt")
        for directory, _, _ in os.walk(self.repo):
            Path(directory).chmod(0o700)
        self.service_script(self.repo,
            "import os,sys\nfrom pathlib import Path\n"
            "assert 'STRATA_RUNTIME_READY' not in os.environ\n"
            "assert Path(sys.executable).parent.parent == Path(__file__).resolve().parents[1] / '.venv'\n"
            + GATE)
        setup = setup_wrapper(self.repo)
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
        command = self.command(revision) + ["run", "source", "--build", "--no-browser"]
        self.env["PIP_NO_INDEX"] = "1"
        self.env["STRATA_RUNTIME_READY"] = str(root)
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], env=self.env, check=True)
        self.make_terminal(root)
        process, server_pid, peer = self.gated_process(command)
        self.assertEqual(server_pid, process.pid)
        self.assert_workspace_unlocked()
        self.assert_observers_answer(revision)
        process.terminate()
        self.assertEqual(peer.recv(1), b"t")
        self.assert_workspace_unlocked()
        process.kill()
        process.wait(timeout=10)
        peer.close()
        self.assert_workspace_unlocked()

    def run_terminal_pty(self, command, env, *, input_data=None):
        master, slave = pty.openpty()
        process = subprocess.Popen(command, env=env, stdin=slave if input_data is not None else subprocess.DEVNULL,
                                   stdout=slave, stderr=slave)
        os.close(slave)
        if input_data is not None:
            os.write(master, input_data)
        output = bytearray()
        deadline = time.monotonic() + 90
        try:
            while True:
                if time.monotonic() >= deadline:
                    self.fail("PTY invocation did not finish")
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    output.extend(data)
                elif process.poll() is not None:
                    break
            return process.wait(timeout=10), output.decode(errors="replace")
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux bootstrap")
    def test_monitor_retries_real_partial_bootstrap_before_loading_ui(self):
        root = self.prepare(self.old)
        shell = (UPSTREAM_SOURCE / "setup.sh").read_text()
        shell = shell.replace('exec .venv/bin/python setup.py "$@"',
                              'printf x >> bootstrap-attempts\nexec .venv/bin/python setup.py "$@"')
        (setup_wrapper(root)).write_text(shell)
        (root / "requirements.txt").write_text("strata-missing-monitor-fixture==1.0\n")
        env = dict(self.env, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1", TERM="xterm")
        command = self.command(self.old) + ["run", "monitor", "--url", "http://127.0.0.1:1"]
        for attempt in (1, 2):
            code, output = self.run_terminal_pty(command, env)
            self.assertEqual(code, 1, output)
            self.assertIn("strata-missing-monitor-fixture", output)
            self.assertEqual((root / "bootstrap-attempts").read_text(), "x" * attempt)
            self.assertTrue(os.access(root / ".venv/bin/python", os.X_OK))
            self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())
            self.assertNotIn("install the monitor", output)
        self.assert_workspace_unlocked()

    def test_monitor_probe_preserves_non_import_errors_without_bootstrap(self):
        root = self.prepare(self.old)
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")],
                       env=self.env, check=True)
        monitor = root / "strata_cli/monitor.py"
        monitor.write_text(monitor.read_text().replace(
            "from __future__ import annotations",
            'from __future__ import annotations\nraise RuntimeError("monitor consumer failure")', 1))
        bootstrap = root / "unexpected-bootstrap"
        shell = setup_wrapper(root)
        shell.write_text(shell.read_text().replace(
            "\n", "\nprintf started > " + shlex.quote(str(bootstrap)) + "\n", 1))
        code, output = self.run_terminal_pty(self.command(self.old) + ["run", "monitor"], self.env)
        self.assertEqual(code, 1, output)
        self.assertIn("monitor consumer failure", output)
        self.assertFalse(bootstrap.exists(), output)
        self.assertFalse((root / ".venv/.strata-pip.json").exists())

    def test_invalid_monitor_semantics_never_bootstrap_cold_or_warm(self):
        cases = [
            (["--json"], "JSON monitor output requires --once; interactive monitor uses a terminal", True),
            (["--output", "json"], "JSON monitor output requires --once; interactive monitor uses a terminal", True),
            (["--json", "--interval", "0.1"], "--interval must be 0.5–30 seconds and --requests must be 1–50", True),
            (["--requests", "51"], "--interval must be 0.5–30 seconds and --requests must be 1–50", False),
            ([], "interactive monitor needs a terminal; use --once or strata status --json", False),
        ]
        state = self.state
        for warm in (False, True):
            for index, (argv, message, machine) in enumerate(cases):
                self.state = state / str(warm) / str(index)
                root = self.prepare(self.old) if warm else self.state / "source/terminal"
                with self.subTest(warm=warm, argv=argv):
                    result = subprocess.run(self.command(self.old) + ["run", "monitor", *argv],
                                            env=dict(self.env, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1"),
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
                    if machine:
                        self.assertEqual(json.loads(result.stdout),
                                         {"schema_version": 1, "ok": False,
                                          "error": {"code": 2, "message": message}})
                    else:
                        self.assertEqual(result.stderr.strip(), "strata: " + message)
                    self.assertFalse((root / ".venv").exists())
                    self.assertFalse((self.state / ".python-root").exists())
                    self.assertFalse((root.parent / ".git/strata-source-refresh-revision").exists())
                    self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())

    def test_invalid_serve_semantics_never_bootstrap_cold_or_warm(self):
        cases = [
            (["--output", "json"], "json"),
            (["--plan", "--output", "jsonl"], "jsonl"),
            (["--port", "-1"], "human"),
            (["--parallel", "0", "--output", "jsonl"], "jsonl"),
            (["--max-queue", "4097"], "human"),
            (["--queue-timeout", "nan"], "human"),
            (["--shutdown-timeout", "301"], "human"),
            (["--batch-groups", "0"], "human"),
            (["--batch-groups", "invalid"], "human"),
            (["--batch-groups", "9" * 5000, "--plan", "--output", "json"], "json"),
            (["--json"], "json"),
            (["--json", "--output", "jsonl"], "jsonl"),
        ]
        state = self.state
        for warm in (False, True):
            self.state = state / ("warm" if warm else "cold")
            root = self.make_updater_workspace() if warm else self.prepare(self.old)
            if not warm:
                self.make_runtime_model(root)
            self.prepare(self.new)
            config = root / "strata-fixture.json"
            before = config.read_bytes()
            markers = [root.parent / ".git" / name for name in ("strata-runtime-revision", "strata-source-refresh-revision")]
            for marker in markers:
                marker.write_text(self.old + "\n")
            env = dict(self.env, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1", STRATA_NO_ACQUIRE="1", PYTHONINTMAXSTRDIGITS="4300")
            for flags, output in cases:
                with self.subTest(warm=warm, flags=flags):
                    result = subprocess.run(self.command(self.new) + ["run", "serve", "--config", str(config), *flags],
                                            env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
                    if output == "json":
                        self.assertEqual(json.loads(result.stdout)["error"]["code"], 2)
                    elif output == "jsonl":
                        event = json.loads(result.stdout)
                        self.assertEqual((event["event"], event["exit_code"]), ("failed", 2))
                    self.assertEqual(config.read_bytes(), before)
                    self.assertTrue(all(marker.read_text().strip() == self.old for marker in markers))
                    self.assertEqual((root / ".venv").exists(), warm)
                    self.assertFalse((root / "update-attempts").exists())
                    self.assertFalse((self.state / ".python-root").exists())

    def test_cold_metadata_and_plans_never_bootstrap(self):
        root = self.prepare(self.old)
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.old + "\n")
        self.make_runtime_model(root)
        self.env.update(PIP_NO_INDEX="1", PYTHONNOUSERSITE="1", STRATA_NO_ACQUIRE="1")
        cases = [
            (["status", "--url", "http://127.0.0.1:1", "--timeout", "0.1", "--output", "json"], 3),
            (["monitor", "--once", "--url", "http://127.0.0.1:1", "--timeout", "0.1", "--output", "json"], 3),
            (["components", "backends"], 0),
            (["models", "list"], 0),
            (["profile", "list"], 0),
            (["launch", "--status"], 0),
            (["launch", "--list-presets"], 0),
            (["launch", "--plan", "--family", "qwen", "--model", "Q2_0", "--output", "json"], 0),
            (["serve", "--config", "missing.json", "--plan"], 5),
            # Alias result semantics stay upstream-owned; only acquisition invariants matter here.
            (["serve", "--config", str(root / "strata-fixture.json"), "--engine", "mock", "--json"], None),
            (["serve", "--profile", "missing-profile", "--json"], None),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                result = subprocess.run(self.command(self.new) + ["run", *argv], env=self.env,
                                        capture_output=True, text=True, timeout=90)
                if expected is not None:
                    self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse((root / ".venv").exists())
                self.assertFalse((self.state / ".python-root").exists())
                self.assertEqual(marker.read_text().strip(), self.old)

    def test_launch_semantic_errors_preserve_native_results_without_runtime(self):
        root = self.prepare(self.old)
        setup = setup_wrapper(root)
        setup.write_text('#!/bin/sh\nprintf x >> "$(dirname "$0")/terminal/bootstrap-attempts"\nexit 19\n')
        setup.chmod(0o700)
        self.write_terminal(root, '''
import socket
from strata_cli import cli
from strata_cli.launch.catalog import Catalog
original_catalog = Catalog.__init__
def catalog(self, src=None, root=None, hardware=None):
    return original_catalog(self, src=src, root=root,
        hardware={"gpus": [], "ram_gb": 256, "disk_free_gb": 512, "os": "linux", "cpu": {"avx2": True}})
Catalog.__init__ = catalog
def no_network(*args, **kwargs):
    raise AssertionError("invalid launch attempted network acquisition")
socket.socket.connect = no_network
raise SystemExit(cli.main())
''')
        env = dict(self.env, STRATA_INSTALL_DIR=str(root), PIP_NO_INDEX="1")
        env.pop("STRATA_TEST_MISSING_KEY", None)
        for key in ("STRATA_WORKSPACE_CONTEXT", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_LOCK_FD",
                    "STRATA_SOURCE_LOCK_FD", "STRATA_LAUNCH_RUNTIME_READY"):
            env.pop(key, None)
        choices = ["--family", "qwen", "--model", "Q2_0", "--no-tui"]
        self.run_source_script(root, '''
from strata_cli.launch import store
from strata_cli.launch.settings import LaunchSettings
store.save(LaunchSettings(family="qwen", model="Q2_0", parallel=9), "invalid-parallel")
''')
        cases = [
            ["--backend", "not-a-backend"], ["--model", "not-a-model"],
            ["--preset", "missing-preset"], ["--model-path", str(self.base / "missing.gguf")],
            [*choices, "--parallel", "9"], [*choices, "--port", "70000"],
            [*choices, "--api-key-env", "STRATA_TEST_MISSING_KEY"],
            [*choices, "--gpu", "0", "--gpu-roles", "0=worker"],
            ["--preset", "invalid-parallel", "--no-tui"], [],
        ]
        expected = []
        for options in cases:
            argv = ["launch", *options, "--output", "json"]
            result = subprocess.run([sys.executable, str(root / self.env["TEST_TERMINAL_CLI"]), *argv],
                                    cwd=self.base, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
            if result.stdout:
                self.assertFalse(json.loads(result.stdout)["ok"])
            else:
                self.assertIn("usage: strata launch", result.stderr)
            expected.append((argv, result.stdout, result.stderr))
        for options in (["--backend", "not-a-backend"], ["--preset", "missing-preset"]):
            argv = ["--quiet", "launch", *options]
            result = subprocess.run([sys.executable, str(root / self.env["TEST_TERMINAL_CLI"]), *argv],
                                    cwd=self.base, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
            self.assertEqual(result.stdout, "")
            self.assertIn("strata:", result.stderr)
            expected.append((argv, result.stdout, result.stderr))
        receipts = [root.parent / ".git/strata-runtime-revision", root.parent / ".git/strata-source-refresh-revision"]
        for path in receipts:
            path.write_text("keep existing runtime receipt\n")
        for state in ("cold", "working", "pipless", "unusable"):
            with self.subTest(runtime=state):
                shutil.rmtree(root / ".venv", ignore_errors=True)
                if state == "pipless":
                    self.make_venv_without_pip(root)
                elif state in {"working", "unusable"}:
                    interpreter = root / ".venv/bin/python"
                    interpreter.parent.mkdir(parents=True)
                    if state == "working":
                        interpreter.symlink_to(sys.executable)
                    else:
                        interpreter.write_text("#!/bin/sh\nexit 61\n")
                        interpreter.chmod(0o700)
                before = {path: path.read_bytes() for path in receipts}
                for argv, stdout, stderr in expected:
                    with self.subTest(argv=argv):
                        result = subprocess.run(self.command(self.old) + ["run", *argv], cwd=self.base,
                                                env=env, capture_output=True, text=True, timeout=30)
                        self.assertEqual((result.returncode, result.stdout, result.stderr),
                                         (2, stdout, stderr))
                        self.assertEqual({path: path.read_bytes() for path in receipts}, before)
                        self.assertFalse((root / "bootstrap-attempts").exists())
                if state == "cold":
                    self.assertFalse((root / ".venv").exists())
                elif state == "pipless":
                    self.assertFalse((root / ".venv/.strata-pip.json").exists())

    def test_launch_private_handoff_preserves_single_output_key_and_start(self):
        root = self.make_native_lifecycle_workspace()
        (root / "allow-update").touch()
        setup = setup_wrapper(root)
        first, separator, body = setup.read_text().partition("\n")
        setup.write_text(first + separator + (
            'if [ "${STRATA_BOOTSTRAP_ONLY:-}" = 1 ]; then printf x >> "$(dirname "$0")/terminal/bootstrap-attempts"; fi\n'
        ) + body)
        entry = root / self.env["TEST_TERMINAL_CLI"]
        entry.write_text(entry.read_text().replace("raise SystemExit(cli.main())", '''
import os, sys
from strata_cli.launch import access
from strata_control import models_move
models_move.interrupted = lambda *_: {"pending": True}
Runner.check_own_files = lambda self: self.emit("model", "Identified fixture model.", None)
original_key = access.new_key
def new_key():
    key = original_key()
    with (ROOT / "generated-keys").open("a") as output:
        output.write(key + "\\n")
    return key
access.new_key = new_key
original_start = Runner.start
def start(self):
    assert Path(sys.executable).absolute() == (ROOT / ".venv/bin/python").absolute()
    assert "STRATA_LAUNCH_RUNTIME_READY" not in os.environ
    with (ROOT / "starts").open("a") as output:
        output.write("start\\n")
    return original_start(self)
Runner.start = start
if os.environ.get("TEST_WRONG_LAUNCH_PYTHON") and "STRATA_LAUNCH_RUNTIME_READY" in os.environ:
    receipt = json.loads(os.environ["STRATA_LAUNCH_RUNTIME_READY"])
    receipt["python"] = sys._base_executable
    os.environ["STRATA_LAUNCH_RUNTIME_READY"] = json.dumps(receipt)
raise SystemExit(cli.main())
'''))
        env = dict(self.env, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1", STRATA_INSTALL_DIR=str(root))
        command = self.command(self.old) + [
            "run", "launch", "--family", "qwen", "--model", "Q2_0", "--no-tui", "--yes",
            "--access", "lan", "--api-key", "existing-fixture-key", "--new-key", "--save-preset", "once",
        ]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=240)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout.count("A move of your models was interrupted."), 1)
        self.assertEqual(result.stdout.count("Identified fixture model."), 1)
        self.assertEqual((root / "starts").read_text(), "start\n")
        self.assertEqual((root / "bootstrap-attempts").read_text(), "x")
        keys = (root / "generated-keys").read_text().splitlines()
        self.assertEqual(len(keys), 1)
        self.run_source_script(root, f'''
from strata_cli.launch import store
assert store.load("once").api_key == {keys[0]!r}
assert [preset.name for preset in store.list_presets()] == ["once"]
''')
        failed = subprocess.run([*command, "--output", "json"],
                                env=dict(env, TEST_WRONG_LAUNCH_PYTHON="1"),
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(failed.returncode, 2, failed.stderr + failed.stdout)
        self.assertIn("interpreter", json.loads(failed.stdout)["error"]["message"])
        self.assertEqual((root / "starts").read_text(), "start\n")
        self.assertEqual((root / "generated-keys").read_text().splitlines(), keys)
        self.assertEqual((root / "bootstrap-attempts").read_text(), "xx")

    def test_guided_launch_missing_screens_keeps_one_handoff_and_native_cancel(self):
        root = self.make_updater_workspace()
        self.write_terminal(root, '''
import sys
from pathlib import Path
from strata_cli import cli
from strata_cli.launch import cmd
ROOT = Path(__file__).resolve().parent
def screens_missing():
    assert Path(sys.executable).absolute() == (ROOT / ".venv/bin/python").absolute()
    return "textual"
cmd._screens_missing = screens_missing
def defaults(settings, catalog):
    settings.family, settings.model, settings.context = "qwen", "Q2_0", 8192
    return settings, []
cmd.apply_defaults = defaults
raise SystemExit(cli.main())
''')
        env = dict(self.env, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1",
                   STRATA_INSTALL_DIR=str(root), TERM="xterm")
        code, output = self.run_terminal_pty(self.command(self.old) + ["run", "launch"], env, input_data=b"n\n")
        self.assertEqual(code, 0, output)
        self.assertEqual(output.count("The screens need a Python package"), 1, output)
        self.assertEqual(output.count("Start it now?"), 1, output)
        self.assertEqual(output.count("Nothing was changed."), 1, output)
        self.assert_workspace_unlocked()

    def make_native_lifecycle_workspace(self):
        root = self.prepare(self.old)
        self.make_runtime_source(root)
        # Use upstream's actual environment creation and pip implementation, without external wheels.
        shell = (UPSTREAM_SOURCE / "setup.sh").read_text()
        shell = shell.replace('exec .venv/bin/python setup.py "$@"',
                              """exec .venv/bin/python -c 'import os,setup,sys; sys.exit(setup.bootstrap_runtime() if os.environ.get("STRATA_BOOTSTRAP_ONLY") == "1" else setup.main())' "$@" """)
        (setup_wrapper(root)).write_text(shell)
        (root / "setup-fixture.py").write_text('''
import json, sys
from pathlib import Path
import setup
def engine(url):
    attempts = setup.ROOT / "update-attempts"
    attempts.write_text(str(int(attempts.read_text()) + 1) if attempts.exists() else "1")
    if (setup.ROOT / "allow-update").exists():
        (setup.ROOT / "engine/BUILD.json").write_text(json.dumps({"version": "0.1.46", "source": "prebuilt"}))
setup.update_installed_engine = engine
original_upgrade = setup.upgrade_config
def upgrade(path, cfg):
    cfg = original_upgrade(path, cfg)
    cfg["managed_source"] = (setup.ROOT / "code.py").read_text().strip()
    setup.write_config(path, cfg)
    return cfg
setup.upgrade_config = upgrade
sys.exit(setup.main())
''')
        self.write_terminal(root, '''
import json
from pathlib import Path
from strata_cli import cli
from strata_cli.launch import cmd
from strata_cli.launch.runner import Runner
ROOT = Path(__file__).resolve().parent
def defaults(s, catalog):
    for key, value in dict(context=8192, gpus=[0], parallel=1, split_engine="off",
                           drafting="off", mtp="off", tune="skip").items():
        setattr(s, key, value)
    return s, []
cmd.apply_defaults = defaults
Runner.check_serving = lambda self: None
def engine(self):
    if not (ROOT / "allow-update").exists():
        self.engine_problem = "fixture engine is not available yet"
Runner.ensure_engine = engine
def model(self):
    config = self.catalog.root / "strata-Q2_0.json"
    if not config.exists():
        engine = self.catalog.root / "engine"
        engine.mkdir()
        (engine / "strata").write_text("local fixture engine")
        (engine / "strata").chmod(0o700)
        (engine / "BUILD.json").write_text(json.dumps({"version": "0.1.46", "source": "prebuilt"}))
        tokenizer = self.catalog.root / "tokenizer"
        tokenizer.mkdir()
        for name in ("vocab.json", "merges.txt", "token_type.json"):
            (tokenizer / name).write_text("{}")
        config.write_text(json.dumps({"exe": str(engine / "strata"), "args": [], "backend": "cuda",
                                      "tokenizer": str(tokenizer), "custom": "preserved"}))
    return config
Runner.ensure_model = model
Runner.ensure_drafter = lambda self, base: None
def tune(self):
    (ROOT / "tune-reached").write_text("validated")
Runner.tune = tune
Runner.start = lambda self: (ROOT / "action-reached").write_text("Runner.start")
Runner.save_choices = lambda self: None
Runner.open_access = lambda self: None
raise SystemExit(cli.main())
''')
        (root / "serve").mkdir(exist_ok=True)
        self.mock_server(root, '''
import json, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
assert (ROOT.parent / ".git/strata-runtime-revision").read_text().strip() == os.environ["EXPECTED_REVISION"]
assert json.loads((ROOT / "strata-Q2_0.json").read_text())["managed_source"] == "new source"
(ROOT / "action-reached").write_text("serve import")
api_key_of = lambda key: key
explicit_no_key = lambda key: not key
key_list = lambda key: [key]
engine_args = lambda cfg: cfg["args"]
def main(argv, **kwargs):
    (ROOT / "action-reached").write_text("serve main")
    return 0
''')
        return root

    @unittest.skipUnless(sys.platform == "linux", "Native launch acquisition and selected validation")
    def test_launch_repairs_selected_without_certifying_unrelated_inventory(self):
        root = self.make_updater_workspace()
        self.prepare(self.new)
        config = root / "strata-fixture.json"
        cfg = json.loads(config.read_text())
        pack = root / "missing-pack"
        cfg["args"] = ["--pack", str(pack)]
        config.write_text(json.dumps(cfg))
        other = root / "engine-unrelated"
        other.mkdir()
        shutil.copyfile(root / "engine/strata", other / "strata")
        (other / "strata").chmod(0o700)
        valid_build = (root / "engine/BUILD.json").read_text()
        (other / "BUILD.json").write_text(valid_build)
        unrelated = dict(cfg, exe=str(other / "strata"), args=["--native", str(root / "unrelated-missing.gguf")])
        (root / "strata-unrelated.json").write_text(json.dumps(unrelated))
        script = '''
import importlib.util, json, os, sys
from pathlib import Path
from strata_control import acquisition, engine_component as ec
from strata_cli.launch.catalog import Catalog
from strata_cli.launch import runner as native
from strata_cli.launch.settings import LaunchSettings
spec = importlib.util.spec_from_file_location("workspace", sys.argv[1])
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)
root, revision, invalid = Path.cwd(), sys.argv[2], sys.argv[3] == "invalid"
base = root / "strata-fixture.json"
with workspace.workspace_lock(root.parent) as (_, lock):
    os.environ["STRATA_WORKSPACE_LOCK_FD"] = str(lock.fileno())
    os.environ["STRATA_WORKSPACE_HELPER"] = sys.argv[1]
    os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent.parent), "revision": revision})
    workspace.prepare_launch_runtime(root, revision, lock.fileno())
    settings = LaunchSettings(family="qwen", model="Q2_0", name="selected-repair", vision="off",
        context=8192, gpus=[0], parallel=1, split_engine="off", drafting="off", mtp="off", tune="skip")
    catalog = Catalog(src=root, root=root, hardware={"gpus": [], "ram_gb": 64, "disk_free_gb": 1})
    runner = native.Runner(settings, catalog=catalog)
    ec.status = lambda *a, **kw: {"usable": True, "engine": {"version": "0.1.46", "backend": "cpu"}}
    native.desc_matches = lambda desc, settings: True
    runner.installed_state = lambda: (base, {})
    runner.intel_chosen = lambda: False
    runner.progress_job = lambda **kwargs: {}
    runner.ensure_drafter = lambda base: None
    # Keep Runner.ensure_engine, ensure_model, build_config, ensure_profile and run.
    # Replace only the model install process with a local payload writer.
    spawn = runner._spawn
    def acquire(argv, **kwargs):
        assert "setup.py" in argv[1], argv
        attempt = root / "native-acquisitions"
        attempt.write_text(attempt.read_text() + "x" if attempt.exists() else "x")
        return spawn([sys.executable, "-c",
            "from pathlib import Path; p=Path('missing-pack'); p.mkdir(); (p/'index.txt').write_text('ready')"],
            cwd=str(root), env=runner._env())
    runner._spawn = acquire
    build = runner.build_config
    def derived(base):
        path = build(base)
        if invalid:
            cfg = json.loads(path.read_text())
            cfg["tokenizer"] = str(root / "invalid-selected-tokenizer")
            path.write_text(json.dumps(cfg))
        return path
    runner.build_config = derived
    def tune():
        selected = json.loads(runner.config_path.read_text())
        assert Path(selected["args"][selected["args"].index("--pack") + 1]).is_dir()
        assert (root.parent / ".git/strata-source-refresh-revision").read_text().strip() == revision
        assert not (root.parent / ".git/strata-runtime-revision").exists()
        (root / "tuned").write_text("selected validated")
    runner.tune = tune
    try:
        result = runner.run(start=False)
    except native.LaunchError as error:
        print(error, file=sys.stderr)
        raise SystemExit(error.code)
    assert Path(result.config) == runner.config_path
'''
        command = [str(root / ".venv/bin/python"), "-c", script, WORKSPACE, self.new]
        receipt = root.parent / ".git/strata-source-refresh-revision"
        certificate = root.parent / ".git/strata-runtime-revision"
        for attempt in (1, 2):
            result = subprocess.run(command + ["valid"], env=self.env, cwd=root,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual((root / "native-acquisitions").read_text(), "x")
            self.assertEqual((root / "update-attempts").read_text(), "1")
            self.assertEqual(receipt.read_text().strip(), self.new)
            self.assertFalse(certificate.exists())
            self.assertEqual((root / "tuned").read_text(), "selected validated")
        for invalid_metadata in ("{ interrupted", "[]", "null"):
            with self.subTest(unrelated_metadata=invalid_metadata):
                (other / "BUILD.json").write_text(invalid_metadata)
                selected = subprocess.run([str(root / ".venv/bin/python"), WORKSPACE, "--selected-runtime",
                                           str(root), str(config)], env=self.env, cwd=root,
                                          capture_output=True, text=True, timeout=30)
                inventory = subprocess.run([str(root / ".venv/bin/python"), WORKSPACE, "--runtime-status", str(root)],
                                           env=self.env, cwd=root, capture_output=True, text=True, timeout=30)
                self.assertEqual(selected.returncode, 0, selected.stderr)
                self.assertEqual(inventory.returncode, 75, inventory.stderr)
                self.assertIn("BUILD.json", inventory.stderr)
                result = subprocess.run(command + ["valid"], env=self.env, cwd=root,
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual((root / "native-acquisitions").read_text(), "x")
                self.assertEqual((root / "update-attempts").read_text(), "1")
                self.assertEqual(receipt.read_text().strip(), self.new)
                self.assertFalse(certificate.exists())
        (other / "BUILD.json").write_text(valid_build)
        (root / "tuned").unlink()
        for updates in (1, 2):
            result = subprocess.run(command + ["invalid"], env=self.env, cwd=root,
                                    capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("invalid-selected-tokenizer", result.stderr)
            self.assertFalse((root / "tuned").exists())
            self.assertFalse(receipt.exists())
            self.assertFalse(certificate.exists())
            self.assertEqual((root / "update-attempts").read_text(), str(updates))
        (root / "engine/BUILD.json").write_text("{ interrupted selected metadata")
        receipt.write_text(self.new + "\n")
        result = subprocess.run(command + ["valid"], env=self.env, cwd=root,
                                capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("BUILD.json", result.stderr)
        self.assertFalse((root / "tuned").exists())
        self.assertFalse(receipt.exists())
        self.assertFalse(certificate.exists())
        (root / "engine/BUILD.json").write_text(valid_build)
        receipt.write_text(self.new + "\n")
        doctor = root / "strata_control/doctor.py"
        doctor.write_text(doctor.read_text() + '''
if "--runtime-status" in __import__("sys").argv:
    def inspect(*args, **kwargs):
        raise RuntimeError("unexpected inventory failure fixture")
''')
        result = subprocess.run(command + ["valid"], env=self.env, cwd=root,
                                capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("unexpected inventory failure fixture", result.stderr)
        self.assertFalse((root / "tuned").exists())
        self.assertFalse(certificate.exists())

    def test_native_pin_refresh_precedes_launch(self):
        self.assert_native_lifecycle("launch")

    def test_native_pin_refresh_precedes_serve(self):
        self.assert_native_lifecycle("serve")

    def test_external_launch_and_serve_do_not_reconcile_unrelated_managed_models(self):
        root = self.make_updater_workspace()
        (root / "tokenizer/vocab.json").unlink()
        reached = self.base / "external-action"
        self.make_terminal(root, f'''
import json
from types import SimpleNamespace
from strata_cli.launch import cmd
from strata_cli.launch.runner import Runner
cmd.apply_defaults = lambda s, catalog: (s, [])
def run(self):
    config = json.loads((self.catalog.root / "strata-Q2_0.json").read_text())
    assert config["model_name"] == "external"
    Path({str(reached)!r}).write_text("launch")
    return SimpleNamespace(serving=False, profile=None, engine_problem=None, final_text="prepared")
Runner.run = run
''')
        self.mock_server(root, f'''
import json
from pathlib import Path
api_key_of = lambda key: key
explicit_no_key = lambda key: not key
key_list = lambda key: [key]
engine_args = lambda cfg: cfg["args"]
def main(argv, **kwargs):
    config = json.loads(Path(argv[argv.index("--config") + 1]).read_text())
    assert config["model_name"] == "external"
    Path({str(reached)!r}).write_text("serve")
    return 0
''')
        external = self.base / "external installation"
        external.mkdir()
        config = self.make_runtime_model(external, "Q2_0")
        config["model_name"] = "external"
        target = external / "strata-Q2_0.json"
        target.write_text(json.dumps(config))
        alias = self.base / "external alias"
        alias.symlink_to(external, target_is_directory=True)
        config_alias = root / "external-profile.json"
        config_alias.symlink_to(target)
        self.run_source_script(root, f'''
from strata_control import profiles
profiles.create("external-model", {str(target)!r})
''')
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.old + "\n")
        protected = (marker, root / "strata-fixture.json",
                     root / "engine/strata", root / "engine/BUILD.json")
        before = {path: path.read_bytes() for path in protected}
        launch = ["launch", "--family", "qwen", "--model", "Q2_0", "--no-tui", "--output", "json"]
        serve = ["serve", "--engine", "mock", "--port", "0"]
        cases = [
            ("launch-external", launch, external, "launch"),
            ("launch-canonical-alias", launch, alias, "launch"),
            ("serve-config-overrides-install-env", [*serve, "--config", str(target)], root, "serve"),
            ("serve-named-profile", [*serve, "--profile", "external-model"], root, "serve"),
            ("serve-relative-cross-root-symlink",
             [*serve, "--config", os.path.relpath(config_alias, self.base)], root, "serve"),
        ]
        for name, argv, install, action in cases:
            with self.subTest(case=name):
                reached.unlink(missing_ok=True)
                result = subprocess.run(self.command(self.new) + ["run", *argv], cwd=self.base,
                                        env=dict(self.env, STRATA_INSTALL_DIR=str(install), PIP_NO_INDEX="1"),
                                        capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(reached.read_text(), action)
                self.assertFalse((root / "update-attempts").exists())
                self.assertEqual({path: path.read_bytes() for path in protected}, before)
        missing = subprocess.run(self.command(self.new) + [
            "run", *serve, "--profile", "missing-profile", "--output", "jsonl"],
            env=dict(self.env, PIP_NO_INDEX="1"), capture_output=True, text=True, timeout=90)
        self.assertEqual(missing.returncode, 5, missing.stderr + missing.stdout)
        self.assertEqual(json.loads(missing.stdout)["event"], "failed")
        self.assertFalse((root / "update-attempts").exists())
        self.assertEqual({path: path.read_bytes() for path in protected}, before)

    def assert_native_lifecycle(self, door):
        state = self.state
        self.state = state / door
        root = self.make_native_lifecycle_workspace()
        env = dict(self.env, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1", EXPECTED_REVISION=self.new)
        launch = ["run", "launch", "--family", "qwen", "--model", "Q2_0", "--no-tui", "--output", "json"]
        first = subprocess.run(self.command(self.old) + launch, env=env,
                               capture_output=True, text=True, timeout=240)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertTrue((root / ".venv/bin/python").exists())
        self.assertTrue((root / ".venv/.strata-pip.json").exists())
        self.assertTrue((root / "strata-Q2_0.json").exists())
        self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())
        action = root / "action-reached"
        if door == "serve":
            # The explicit serve profile, not this installation override, owns reconciliation.
            env["STRATA_INSTALL_DIR"] = str(self.base / "unrelated external installation")
        argv = launch if door == "launch" else [
            "run", "serve", "--config", str(root / "strata-Q2_0.json"), "--engine", "mock"]
        # Launch defers inventory validation until after native acquisition.
        (root / "allow-update").touch()
        succeeded = subprocess.run(self.command(self.new) + argv, env=env,
                                   capture_output=True, text=True, timeout=120)
        self.assertEqual(succeeded.returncode, 0, succeeded.stderr + succeeded.stdout)
        self.assertEqual((root / "update-attempts").read_text(), "1")
        self.assertEqual(action.read_text(), "Runner.start" if door == "launch" else "serve main")
        self.assertEqual((root.parent / ".git/strata-runtime-revision").read_text().strip(), self.new)
        self.assertEqual(json.loads((root / "strata-Q2_0.json").read_text())["custom"], "preserved")
        if door == "launch":
            alias = self.base / "managed source alias"
            alias.symlink_to(root, target_is_directory=True)
            env["STRATA_INSTALL_DIR"] = str(alias)
            reused = subprocess.run(self.command(self.new) + argv, env=env,
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(reused.returncode, 0, reused.stderr + reused.stdout)
            self.assertEqual((root / "update-attempts").read_text(), "1")

    def test_first_status_recovers_initial_and_migrated_patch_publication(self):
        state = self.state
        for phase in ("initial", "migration"):
            with self.subTest(phase=phase):
                self.state = state / phase
                if phase == "initial":
                    self.env["TEST_SOURCE_PATCH"] = ""
                else:
                    previous = self.base / "previous-overlay.patch"
                    previous.write_text(Path(SOURCE_PATCH).read_bytes().decode("utf-8") + (
                        "diff --git a/terminal/code.py b/terminal/code.py\n--- a/terminal/code.py\n+++ b/terminal/code.py\n"
                        "@@ -1 +1 @@\n-old source\n+older overlay source\n"))
                    self.env["TEST_SOURCE_PATCH"] = str(previous)
                root = self.prepare(self.old)
                del self.env["TEST_SOURCE_PATCH"]
                note = root / "user-owned.txt"
                note.write_text("preserved across publication recovery\n")
                interrupted = subprocess.run([sys.executable, "-c", '''
import importlib.util, os, pathlib, sys
spec = importlib.util.spec_from_file_location("workspace", sys.argv[1])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
apply = helper.apply_source_patch
def interrupt(root, text, *, reverse=False):
    if not reverse:
        os._exit(23)  # Abrupt termination leaves the published journal, unlike a synchronous error.
    return apply(root, text, reverse=reverse)
helper.apply_source_patch = interrupt
helper.prepare_workspace(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
''', WORKSPACE, str(self.state), self.old, str(self.repository), SOURCE_PATCH],
                    env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(interrupted.returncode, 23)
                self.assertEqual((root.parent / ".git/strata-source.patch").read_text(), Path(SOURCE_PATCH).read_text())
                # No version/preparation command may repair the tree before this first real JSON client.
                for _ in range(2):
                    result = subprocess.run(self.command(self.old) + [
                        "run", "status", "--url", "http://127.0.0.1:1", "--timeout", "0.1", "--output", "json"],
                        env=self.env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertFalse(json.loads(result.stdout)["ok"])
                    self.assertEqual(note.read_text(), "preserved across publication recovery\n")
                    self.assertFalse((root / ".venv").exists())

    def test_previous_overlay_is_replaced_before_native_parser_import(self):
        self.env["TEST_SOURCE_PATCH"] = ""
        root = self.prepare(self.old)
        del self.env["TEST_SOURCE_PATCH"]
        result = subprocess.run(self.command(self.new) + [
            "run", "status", "--url", "http://127.0.0.1:1", "--timeout", "0.1", "--output", "json"],
            env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual((root.parent / ".git/strata-source.patch").read_text(), Path(SOURCE_PATCH).read_text())
        self.assertFalse((root / ".venv").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux launch acquisition")
    def test_launch_defaults_follow_canonical_installation_ownership(self):
        root = self.make_acquisition_workspace()
        external = self.base / "external installation"
        external.mkdir()
        external_alias = self.base / "external alias"
        external_alias.symlink_to(external, target_is_directory=True)
        managed_alias = self.base / "managed alias"
        managed_alias.symlink_to(root, target_is_directory=True)
        caller_data = external / "caller data"
        cli_data = self.base / "CLI data"
        nix_data, nix_models = self.base / "Nix data", self.base / "Nix GGUF"
        remembered = Path(self.env["XDG_CONFIG_HOME"]) / "strata/settings.json"
        remembered.parent.mkdir(parents=True)
        remembered.write_text(json.dumps({"data_dir": str(caller_data)}))
        context = json.dumps({"state": str(self.state), "data_directory": str(nix_data),
                              "models_directory": str(nix_models)})
        producer = '''
import json, os
from strata_cli.launch.catalog import Catalog
from strata_cli.launch.runner import Runner
from strata_cli.launch.settings import LaunchSettings
runner = Runner(LaunchSettings(family="qwen", model="Q2_0", context=8192, mtp="on",
                              data_dir=os.environ.get("TEST_CLI_DATA")), catalog=Catalog())
runner.resolved_drafting = lambda *_: "mtp"
runner.vision_word = lambda: "no"
runner.installed_card_args = lambda: []
print(json.dumps(runner.setup_args()))
'''
        consumer = '''
import inspect, json, socket, sys
import setup
def no_network(*args, **kwargs):
    raise AssertionError("unexpected network acquisition")
socket.socket.connect = no_network
socket.create_connection = no_network
def capture(url, destination, *args, **kwargs):
    scope = inspect.currentframe().f_back.f_locals
    print("DESTINATION=" + json.dumps({"home": str(setup.home()), "data": str(scope["data"]),
        "models": str(scope["models_dir"]), "download": str(destination)}), flush=True)
    raise SystemExit(37)
setup.download = capture
raise SystemExit(setup.main(sys.argv[1:]))
'''
        cases = (
            ("external", external, True, None, False),
            ("external-alias", external_alias, True, None, False),
            ("managed", root, True, None, True),
            ("managed-alias", managed_alias, True, None, True),
            ("no-context", external, False, None, False),
            ("external-cli", external, True, cli_data, False),
            ("managed-cli", root, True, cli_data, True),
        )
        for name, target, with_context, explicit_data, managed in cases:
            with self.subTest(case=name):
                env = dict(self.env, STRATA_INSTALL_DIR=str(target), PIP_NO_INDEX="1")
                env.pop("STRATA_WORKSPACE_CONTEXT", None)
                env.pop("TEST_CLI_DATA", None)
                if with_context:
                    env["STRATA_WORKSPACE_CONTEXT"] = context
                if explicit_data is not None:
                    env["TEST_CLI_DATA"] = str(explicit_data)
                result = subprocess.run([sys.executable, "-c", producer], cwd=root, env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                argv = json.loads(result.stdout)
                result = subprocess.run([sys.executable, "-c", consumer, *argv], cwd=root,
                                        env=dict(env, STRATA_CONTROL_INSTALL="1", PYTHONNOUSERSITE="1"),
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 37, result.stderr + result.stdout)
                actual = next(json.loads(line.partition("=")[2]) for line in result.stdout.splitlines()
                              if line.startswith("DESTINATION="))
                expected_data = explicit_data or (nix_data if managed else caller_data)
                expected_models = nix_models if managed else expected_data / "models"
                self.assertEqual(Path(actual["home"]).resolve(), target.resolve())
                self.assertEqual(Path(actual["data"]), expected_data)
                self.assertEqual(Path(actual["models"]), expected_models / "Q2_0")
                self.assertTrue(Path(actual["download"]).is_relative_to(expected_models))

    def test_launch_runner_defaults_and_source_sycl_defaults_use_real_parsers(self):
        root = self.make_acquisition_workspace()
        self.run_source_script(root, '''
import json, os
from pathlib import Path
from strata_cli.launch import settings
from strata_cli.launch.catalog import Catalog
from strata_cli.launch.runner import Runner
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(Path.cwd().parent),
    "data_directory": "/nix-data", "models_directory": "/nix-models"})
cat = Catalog()
assert cat.root == Path.cwd()
runner = Runner(settings.LaunchSettings(family="qwen", model="Q2_0"), catalog=cat)
runner.resolved_drafting = lambda *a: "off"
runner.vision_word = lambda: "off"
runner.installed_card_args = lambda: []
argv = runner.setup_args()
assert argv[argv.index("--data-dir") + 1] == "/nix-data"
assert argv[argv.index("--models-dir") + 1] == "/nix-models"
assert "--set-default-data-dir" not in argv and "--move-data" not in argv
runner.s.data_dir = "/cli-data"
argv = runner.setup_args()
assert argv[argv.index("--data-dir") + 1] == "/cli-data"
assert "--set-default-data-dir" in argv
''')
        script = root / "setup-fixture.py"
        script.write_text(script.read_text().replace("sys.exit(setup.main())", '''
original_sycl = setup.sycl_setup
def sycl(argv):
    def capture(executable, command):
        (setup.ROOT / "sycl-defaults.json").write_text(json.dumps(command[2:]))
        raise SystemExit(0)
    setup.os.execv = capture
    return original_sycl(argv)
setup.sycl_setup = sycl
sys.exit(setup.main())
'''))
        # The actual setup parser hook must forward injected defaults to SYCL's delegated argv.
        env = dict(self.env, TEST_DATA_DIRECTORY="/nix-data", TEST_MODELS_DIRECTORY="/nix-models")
        result = subprocess.run(self.command(self.old) + ["run", "source", "--setup", "--backend", "sycl"],
                                env=env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads((root / "sycl-defaults.json").read_text())
        self.assertEqual(argv[argv.index("--data-dir") + 1], "/nix-data")
        self.assertEqual(argv[argv.index("--models-dir") + 1], "/nix-models")
        self.assertIn("--separate-model-artifacts", argv)

    def test_real_setup_hook_accepts_signed_feed_and_help_never_fetches(self):
        self.env["STRATA_CONTROL_INSTALL"] = "1"
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import contextlib, io, json, os, socket
from pathlib import Path
import setup
from strata_control import feed as feedmod, signing
sys.path.append(str(Path(''' + repr(UPSTREAM) + ''') / "tools"))
from test_setup_feed_models import flash_next
directory = Path.cwd() / "local-feed"
directory.mkdir()
key = signing.generate_key()
keys = directory / "keys.json"
keys.write_text(json.dumps({"keys": [signing.public_part(key)]}))
os.environ["STRATA_UPDATE_TRUSTED_KEYS"] = str(keys)
os.environ["STRATA_COMPONENTS_DIR"] = str(directory / "components")
payload = json.dumps({"schema_version": 1, "feed": "strata-updates", "channel": "stable",
    "sequence": 1, "generated_at": "2026-11-06T00:00:00Z", "expires_at": None,
    "models": {"packages": [flash_next()]}}).encode()
(directory / feedmod.FEED_NAME).write_bytes(payload)
(directory / (feedmod.FEED_NAME + ".sig")).write_text(json.dumps(signing.sign_bytes(key, payload)))
setup.feed_engine_families = lambda: {"qwen4exp"}
setup.own_files_in = lambda *args: (_ for _ in ()).throw(AssertionError("hook ran too late"))
def no_network(*args, **kwargs):
    raise AssertionError("help or local feed opened a network connection")
socket.socket.connect = no_network
socket.create_connection = no_network
original_feed_setup = setup.feed_models_setup
original_require = setup.acquisition.require
def no_side_effect(*args, **kwargs):
    raise AssertionError("help performed feed discovery, acquisition, or after_parse")
setup.feed_models_setup = no_side_effect
setup.acquisition.require = no_side_effect
for flag in ("--help", "-h", "--hel"):
    for args in ([flag, "--family", "qwen4-test", "--feed", str(directory)],
                 ["--family", "qwen4-test", "--feed", str(directory), flag]):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            try:
                setup.main(args, after_parse=no_side_effect)
            except SystemExit as error:
                assert error.code == 0
                assert "--family" in output.getvalue()
            else:
                raise AssertionError("help did not exit")
for args in (["--h"], ["--family", "qwen", "--", "--help"]):
    with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
        try:
            setup.main(args, after_parse=no_side_effect)
        except SystemExit as error:
            assert error.code == 2
            assert not output.getvalue()
        else:
            raise AssertionError("invalid help syntax succeeded")
setup.feed_models_setup = original_feed_setup
setup.acquisition.require = original_require
def after(a, argv):
    assert a.family == "qwen4-test" and a.model == "Q4_K_M" and a.context == 8192
    assert argv[-2:] == ["--cont", "8192"]
    return 37
assert setup.main(["--family", "qwen4-test", "--model", "Q4_K_M", "--feed", str(directory),
                   "--gguf-dir", "/must-not-touch", "--cont", "8192"], after_parse=after) == 37
with contextlib.redirect_stderr(io.StringIO()) as errors:
    try:
        setup.main(["--family", "qwen4-test", "--model", "invalid-model", "--feed", str(directory)],
                   after_parse=no_side_effect)
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("invalid operation succeeded")
''')

    def test_observers_refresh_pin_before_parsing_and_bypass_same_pin_mutation_lock(self):
        root = self.prepare(self.old)
        cli = self.repo / "strata_cli/cli.py"
        anchor = "    return ap\n"
        self.assertEqual(cli.read_text().count(anchor), 1)
        cli.write_text(cli.read_text().replace(anchor,
            '    for name in ("status", "monitor", "logs", "connection"):\n'
            '        sp.choices[name].add_argument("--new-pin-flag", action="store_true")\n' + anchor))
        revision = self.commit()
        self.write_terminal(root, '''
import json
from strata_cli import cli
def dispatch(a):
    print(json.dumps({"command": a.command, "new_flag": getattr(a, "new_pin_flag", None)}))
    return 0
cli._run = dispatch
raise SystemExit(cli.main())
''')
        requests = [
            ("status", ["--new-pin-flag"], True),
            ("monitor", ["--once", "--new-pin-flag"], True),
            ("logs", ["--new-pin-flag"], True),
            ("connection", ["--new-pin-flag", "list"], True),
            ("status", [], False),
        ]
        for command, args, expected in requests:
            with self.subTest(command=command, args=args):
                self.prepare(self.old)
                result = subprocess.run(self.command(revision) + ["run", command, *args],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"command": command, "new_flag": expected})
                self.assertEqual(subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), revision)
                self.assertFalse((root / ".venv").exists())
                self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())
        with (self.state / ".source.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for command, args in (("status", []), ("monitor", ["--once"]), ("logs", []), ("connection", ["list"])):
                with self.subTest(same_pin=command):
                    result = subprocess.run(self.command(revision) + ["run", command, *args],
                                            env=self.env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {"command": command, "new_flag": False})
        self.assertFalse((root / ".venv").exists())
        self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())

    def test_new_pin_parser_is_loaded_before_new_native_command(self):
        root = self.prepare(self.old)
        cli = self.repo / "strata_cli/cli.py"
        anchor = '    sp = ap.add_subparsers(dest="command", required=True)'
        cli.write_text(cli.read_text().replace(anchor, anchor + '\n    sp.add_parser("new-native-command")'))
        revision = self.commit()
        self.write_terminal(root,
            "from pathlib import Path\nfrom strata_cli import cli\n"
            "cli._run = lambda a: 0 if a.command == 'new-native-command' else 99\n"
            "raise SystemExit(cli.main())\n")
        result = subprocess.run(self.command(revision) + ["run", "new-native-command"],
                                env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), revision)
        self.assertFalse((root / ".venv").exists())

    def test_benchmark_service_drops_protocol_but_controller_keeps_lease(self):
        root = self.prepare(self.old)
        observation = self.base / "service.json"
        self.make_terminal(root, '''
import os
if sys.argv[1:2] != ["serve"]:
    from strata_cli import bench_standard
    bench_standard.Target.get = lambda *args, **kwargs: None
''')
        config = self.make_runtime_model(root)
        config["port"] = 1
        target = root / "strata-fixture.json"
        target.write_text(json.dumps(config))
        self.mock_server(root, '''
import fcntl, json, os
from pathlib import Path
api_key_of = lambda key: key
explicit_no_key = lambda key: not key
key_list = lambda key: [key]
engine_args = lambda cfg: cfg["args"]
def main(argv, **kwargs):
    from strata_control import acquisition
    acquisition.service_ready()
    protocol = ("STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER",
                "STRATA_WORKSPACE_CONTEXT", "STRATA_SOURCE_LOCK_FD")
    with (Path(__file__).resolve().parents[3] / ".source.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            controller_locked = False
        except BlockingIOError:
            controller_locked = True
    Path(os.environ["SERVICE_OBSERVATION"]).write_text(json.dumps({
        "protocol": {key: os.environ[key] for key in protocol if key in os.environ},
        "controller_locked": controller_locked}))
    return 76
''')
        result = subprocess.run(
            self.command(self.old) + ["run", "bench", "run", "--profile", str(target),
                                     "--out", str(self.base / "results"), "--skip-model-hash",
                                     "--load-timeout", "5", "--output", "json"],
            env=dict(self.env, SERVICE_OBSERVATION=str(observation)),
            cwd=self.base, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 6, result.stderr)
        self.assertEqual(json.loads(observation.read_text()), {"protocol": {}, "controller_locked": True})

    def test_native_derived_profile_refreshes_and_migrates_managed_runtime(self):
        root = self.make_updater_workspace()
        self.make_terminal(root)
        config = root / "strata-fixture.json"
        base = json.loads(config.read_text())
        base["args"] = ["--prefill", "2048"]
        config.write_text(json.dumps(base))
        producer = '''
import json
from pathlib import Path
from strata_cli.launch.catalog import Catalog
from strata_cli.launch.runner import Runner
from strata_cli.launch.settings import LaunchSettings
root = Path.cwd()
settings = LaunchSettings(family="qwen", model="Q2_0", name="managed-source-profile",
    context=8192, gpus=[0], parallel=1, split_engine="off", drafting="off", mtp="off", tune="skip")
catalog = Catalog(src=root, root=root, hardware={"gpus": [], "ram_gb": 64, "disk_free_gb": 1})
runner = Runner(settings, catalog=catalog)
config = runner.build_config(root / "strata-fixture.json")
runner.ensure_profile(config)
print(json.dumps({"profile": runner.profile, "config": str(config)}))
'''
        produced = subprocess.run([sys.executable, "-c", producer], env=self.env, cwd=root,
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(produced.returncode, 0, produced.stderr)
        profile = json.loads(produced.stdout)
        selected = Path(profile["config"])
        before = json.loads(selected.read_text())
        self.assertNotEqual(selected.parent, root)
        self.assertEqual(Path(before["exe"]), root / "engine/strata")
        self.mock_server(root, '''
from pathlib import Path
api_key_of = lambda key: key
explicit_no_key = lambda key: not key
key_list = lambda key: [key]
engine_args = lambda cfg: cfg["args"]
def main(argv, **kwargs):
    Path("service-reached").write_text(argv[argv.index("--config") + 1])
    return 0
''')
        (root / "engine/BUILD.json").write_text('{"version":"0.1.12","source":"prebuilt"}')
        marker = root.parent / ".git/strata-runtime-revision"
        marker.write_text(self.old + "\n")
        subprocess.run(["git", "-C", str(root), "fetch", "--quiet", "--depth=1", str(self.repository), self.new],
                       env=self.env, check=True, capture_output=True, text=True, timeout=30)
        for reference in (profile["profile"], str(selected)):
            result = subprocess.run(self.command(self.new) + ["run", "serve", "--profile", reference,
                                                              "--engine", "mock", "--port", "0"],
                                    env=self.env, cwd=self.base, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            upgraded = json.loads(selected.read_text())
            self.assertEqual(upgraded["args"][upgraded["args"].index("--prefill") + 1], "auto")
            for key in ("exe", "tokenizer", "custom", "key"):
                self.assertEqual(upgraded.get(key), before.get(key))
            self.assertEqual(marker.read_text().strip(), self.new)
            self.assertEqual((root / "update-attempts").read_text(), "1")
            self.assertEqual(Path((self.base / "service-reached").read_text()), selected)
            # An already-certified engine must still migrate a stale selected launch config.
            upgraded["args"][upgraded["args"].index("--prefill") + 1] = "2048"
            selected.write_text(json.dumps(upgraded))

    def test_observer_source_lease_spans_exec_and_consumer_before_publication(self):
        root = self.prepare(self.old)
        address = self.base / "source-gate.sock"
        self.make_terminal(root, '''
import os, socket
from strata_cli.client import Endpoint
def gate(label):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.settimeout(20)
        peer.connect(os.environ["SOURCE_GATE"])
        peer.sendall(label)
        peer.recv(1)
gate(b"f")
snapshot = Endpoint.snapshot
def consume(self):
    gate(b"c")
    return snapshot(self)
Endpoint.snapshot = consume
''')
        writer_script = '''
import contextlib, fcntl, importlib.util, os, socket, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("writer_workspace", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
state, remote, revision, patch = Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
original = module.apply_source_patch
def publish(root, text, *, reverse=False):
    with (state / ".source-publication.lock").open("a") as reader:
        try:
            fcntl.flock(reader, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError("source publication is not exclusive")
    return original(root, text, reverse=reverse)
module.apply_source_patch = publish
with module.workspace_lock(state) as (_, lock):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.connect(os.environ["SOURCE_GATE"])
        peer.sendall(b"w")
    module._prepare_workspace(state, revision, remote, patch, lock_fd=lock.fileno())
'''
        env = dict(self.env, SOURCE_GATE=str(address))
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(address))
            server.listen(3)
            server.settimeout(20)
            observer = subprocess.Popen(
                self.command(self.old) + ["run", "status", "--json", "--url", "http://127.0.0.1:1",
                                         "--timeout", "0.2"],
                env=env, cwd=self.base, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.addCleanup(lambda: observer.poll() is None and observer.kill())
            for phase in (b"f", b"c"):
                peer, _ = server.accept()
                peer.settimeout(20)
                self.assertEqual(peer.recv(1), phase)
                with (self.state / ".source-publication.lock").open("a") as exclusive:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(exclusive, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if phase == b"f":
                    peer.sendall(b"g")
                    peer.close()
            writer = subprocess.Popen(
                [sys.executable, "-c", writer_script, WORKSPACE, str(self.state), str(self.repository), self.new, SOURCE_PATCH],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.addCleanup(lambda: writer.poll() is None and writer.kill())
            ready, _ = server.accept()
            with ready:
                self.assertEqual(ready.recv(1), b"w")
            self.assertEqual((root / "code.py").read_text(), "old source\n")
            peer.sendall(b"g")
            peer.close()
            stdout, stderr = observer.communicate(timeout=30)
            self.assertEqual(observer.returncode, 3, stderr)
            self.assertFalse(json.loads(stdout)["ok"])
            stdout, stderr = writer.communicate(timeout=30)
            self.assertEqual(writer.returncode, 0, stderr)
        self.assertEqual((root / "code.py").read_text(), "new source\n")

    def test_progress_counts_split_downloads_and_keeps_vision_destination(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import json, os
from pathlib import Path
from types import SimpleNamespace as NS
import setup
from tools import strata_mcp as mcp
from strata_cli.launch.runner import Runner
from strata_cli.launch.catalog import Catalog
from strata_cli.launch.settings import LaunchSettings
root = Path.cwd()
base = root.parent.parent
for family, model in (("qwen", "Q2_0"), ("nvfp4", "NVFP4"), ("nvfp4", "NVFP4-QAD")):
    data, models, native = (base / model / name for name in ("data", "gguf", "native"))
    os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({
        "state": str(root.parent.parent), "data_directory": str(data), "models_directory": str(models)})
    total = float(setup.MODELS[model]["download_gb"])
    cat = Catalog(src=root, root=root, hardware={})
    cat.data_dir_choice = lambda: (native, "default")
    cat.rows = lambda: [NS(family=family, model=model, download_gb=total)]
    cat.strata._setup = setup
    cat.strata._setup_tried = True
    runner = Runner(LaunchSettings(family=family, model=model, context=8192,
        vision="off", mtp="off", drafting="off", gpus=[0]), catalog=cat)
    runner.resolved_drafting = lambda *_: "off"
    job = runner.progress_job()
    files = job["files"]
    if family == "qwen":
        assert all(Path(f["path"]).is_relative_to(models) for f in files), files
    else:
        roles = setup.ready_needed(model, models, data)
        for file, role in zip(files, roles):
            expected_root = models if role[0] in ("dense", "embd", "ple") else data
            assert Path(file["path"]).is_relative_to(expected_root), (file, role)
    logical = 0
    for file in files:
        path = Path(file["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        size = min(file["bytes"] or 1_000_000_000, 1_000_000_000 // len(files))
        with part.open("wb") as stream:
            stream.truncate(size)
        logical += size
        assert part.stat().st_blocks == 0
    shown = mcp.combined_progress({"step": "5/7: downloading"}, job)
    assert shown["download"]["done_gb"] > 0, shown
    assert abs(shown["download"]["done_gb"] - logical / 1e9) <= 0.1, shown
    if family == "qwen":
        legacy = base / "reused-model"
        folder = legacy / "models/Q2_0"
        folder.mkdir(parents=True)
        for i in range(1, setup.model_shards(setup.FAMILIES[family], model) + 1):
            path = folder / setup.model_file(setup.FAMILIES[family], model, i)
            path.write_bytes(b"verified fixture")
            setup.mark(path)
        tracked = mcp.expected_files(setup, family, model, models, True, data_dir=data, elsewhere=[legacy])
        assert all(Path(f["path"]).parent == folder for f in tracked if f["role"] == "model"), tracked
        assert next(Path(f["path"]) for f in tracked if f["role"] == "vision").parent == models
''')
    def test_launch_plan_reuses_effective_completed_partial_and_retained_shards(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import contextlib, io, json, os, socket
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
from strata_cli import cli
from strata_cli.launch import catalog as C, cmd, settings as S
from strata_cli.launch.runner import Runner
from strata_control import drafting, engine_component
root = Path.cwd()
base = root.parent.parent / "plan-layouts"
base.mkdir()
def forbidden(*args, **kwargs):
    raise AssertionError("read-only plan acquired or changed model data")
cat = C.Catalog(src=root, root=root, hardware={})
mod = cat.strata.setup_module()
row = C.ModelRow(family="qwen", family_title="Qwen", model="IQ3_XXS", id="iq3_xxs", about="",
    download_gb=1.0, need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits",
    experimental=False, images=False, installed=False)
cat.rows = lambda: [row]
mod.data_folder = mod.data_folder_for = forbidden
with contextlib.ExitStack() as guards:
    guards.enter_context(patch.object(socket.socket, "connect", forbidden))
    guards.enter_context(patch.object(mod.acquisition, "require", forbidden))
    guards.enter_context(patch.object(drafting, "detect_hardware", return_value=("cpu", [])))
    guards.enter_context(patch.object(engine_component, "status", return_value={"usable": True, "engine": {"backend": "cpu"}}))
    guards.enter_context(patch.object(Runner, "intel_chosen", return_value=False))
    guards.enter_context(patch.object(Runner, "preflight_words", return_value=[]))
    guards.enter_context(patch.object(Runner, "drafting_plan_line", return_value=""))
    guards.enter_context(patch.object(C, "Catalog", return_value=cat))
    guards.enter_context(patch.object(cmd, "apply_defaults", side_effect=lambda s, c: (s, [])))
    for scenario in ("native", "data", "models", "both", "explicit", "retained"):
        home = base / scenario
        native, data, models = (home / name for name in ("native", "data", "gguf"))
        context = {"state": str(root.parent.parent)}
        if scenario in ("data", "both", "explicit", "retained"):
            context["data_directory"] = str(data)
        if scenario in ("models", "both", "explicit", "retained"):
            context["models_directory"] = str(models)
        if scenario == "explicit":
            data = home / "cli-data"
        if scenario in ("native", "models"):
            data = native
        if scenario in ("native", "data"):
            models = data / "models"
        os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps(context)
        cat.data_dir_choice = lambda: (native, "default")
        retained = home / "retained"
        mod.load_settings = lambda: {"data_dir": str(retained)} if scenario == "retained" else {}
        selected = retained / "models/IQ3_XXS" if scenario == "retained" else models / "IQ3_XXS"
        selected.mkdir(parents=True)
        shards = [selected / mod.model_file(mod.FAMILIES["qwen"], "IQ3_XXS", i)
                  for i in range(1, mod.model_shards(mod.FAMILIES["qwen"], "IQ3_XXS") + 1)]
        for shard in shards:
            with shard.open("wb") as stream:
                stream.truncate(500_000_000)
            mod.mark(shard)
        s = S.LaunchSettings(family="qwen", model="iq3_xxs", context=8192, vision="off", mtp="off",
                            drafting="off", no_key=True, data_dir=str(data) if scenario == "explicit" else None)
        before = asdict(s)
        runner = Runner(s, catalog=cat, hardware={})
        args = runner.setup_args()
        assert "--set-default-data-dir" in args if scenario == "explicit" else "--set-default-data-dir" not in args
        assert "--move-data" not in args
        job = runner.progress_job()
        assert [Path(f["path"]) for f in job["files"] if f["role"] == "model"] == shards, job
        assert runner.model_state().remaining_gb == 0
        assert runner.download_plan()["gb"] == 0
        assert asdict(s) == before
        public = ["launch", "--family", "qwen", "--model", "iq3_xxs", "--context", "8192",
                  "--vision", "off", "--mtp", "off", "--drafting", "off", "--no-api-key", "--plan", "--output", "json"]
        if scenario == "explicit":
            public += ["--data-dir", str(data)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert cmd.run_launch(cli.parse_args(public)) == 0
        plan = json.loads(output.getvalue())["plan"]
        assert plan["download"]["gb"] == 0, plan
        assert plan["settings"]["data_dir"] == (str(data) if scenario == "explicit" else None)
        if scenario != "retained":
            last = shards[-1]
            last.unlink()
            part = last.with_name(last.name + ".part")
            with part.open("wb") as stream:
                stream.truncate(250_000_000)
            assert runner.model_state().remaining_gb == 0.5, runner.model_state()
            with part.open("wb") as stream:
                stream.truncate(500_000_000)
            # A full logical size with an unfinished chunk ledger is not completed data.
            assert mod._save_pieces(part, 500_000_000, set())
            ledger = part.with_name(part.name + ".chunks")
            assert runner.model_state().remaining_gb == 0.5
            part.unlink()
            ledger.unlink()
            stale = shards[0].with_name(shards[0].name + ".part")
            with stale.open("wb") as stream:
                stream.truncate(500_000_000)
            assert runner.model_state().remaining_gb == 0.5
            stale.unlink()
        assert asdict(s) == before
''')

    def test_real_cross_pin_linked_engine_preserves_external_payload_and_profile_routes(self):
        self.make_cross_pin_sources()
        state = self.state
        for overlay in (False, True):
            with self.subTest(overlay=overlay):
                self.state = state / ('overlay' if overlay else 'native')
                profiles_dir = self.base / ('linked-profiles-overlay' if overlay else 'linked-profiles-native')
                self.env['STRATA_PROFILE_DIR'] = str(profiles_dir)
                flat = self.prepare_cross_pin(self.old, overlay=overlay)
                retained = self.make_local_runtime(flat)
                external = flat.parent / 'external-engine'
                external.mkdir()
                binary = external / 'strata'
                binary.write_bytes(b'external engine payload\n')
                userdata = external / 'user-cache'
                userdata.write_bytes(b'never copy or delete this payload\n')
                identities = {p: (p.stat().st_dev, p.stat().st_ino, p.read_bytes()) for p in (binary, userdata)}
                (flat / 'engine').symlink_to('../external-engine')
                config = flat / 'strata-linked.json'
                config.write_text(json.dumps({'exe': str(flat / 'engine/strata'), 'cwd': str(flat),
                                             'tokenizer': '/fixture/tokenizer', 'args': []}))
                self.cross_pin_cli(self.old, 'profile', 'create', 'linked', '--from-config', str(config),
                                   '--output', 'json', overlay=overlay)
                for revision, expected in ((self.new, flat / 'terminal'), (self.old, flat),
                                           (self.new, flat / 'terminal')):
                    root = self.prepare_cross_pin(revision, overlay=overlay)
                    self.assertEqual(root, expected)
                    self.assert_local_runtime(root, retained)
                    self.assertTrue((root / 'engine').is_symlink())
                    self.assertEqual((root / 'engine').resolve(), external)
                    if revision == self.new:
                        self.assertFalse((flat / 'engine').is_symlink())
                        self.assertEqual((flat / 'engine/CMakeLists.txt').read_bytes(),
                                         (UPSTREAM_SOURCE / 'engine/CMakeLists.txt').read_bytes())
                    mapped = json.loads((root / config.name).read_text())
                    self.assertEqual(Path(mapped['exe']), root / 'engine/strata')
                    self.assertEqual(Path(mapped['exe']).resolve(), binary)
                    self.assertEqual(mapped['cwd'], str(root))
                    selected = self.cross_pin_cli(revision, 'profile', 'set', 'linked', 'port=9123',
                                                  '--output', 'json', overlay=overlay)
                    self.assertEqual(selected['profile']['source_config'], str(root / config.name))
                    for path, identity in identities.items():
                        self.assertEqual((path.stat().st_dev, path.stat().st_ino, path.read_bytes()), identity)

    def test_real_cross_pin_linked_engine_refused_checkout_restores_original_link_and_userdata(self):
        self.make_cross_pin_sources()
        self.env['STRATA_PROFILE_DIR'] = str(self.base / 'linked-refusal-profiles')
        flat = self.prepare_cross_pin(self.old)
        retained = self.make_local_runtime(flat)
        external = flat.parent / 'external-engine'
        external.mkdir()
        binary = external / 'strata'
        binary.write_bytes(b'external engine bytes\n')
        userdata = external / 'user-cache'
        userdata.write_bytes(b'precious userdata\n')
        link = flat / 'engine'
        link.symlink_to('../external-engine')
        link_identity = (link.lstat().st_dev, link.lstat().st_ino, os.readlink(link))
        identities = {p: (p.stat().st_dev, p.stat().st_ino, p.read_bytes()) for p in (binary, userdata)}
        config = flat / 'strata-linked.json'
        config.write_text(json.dumps({'exe': str(flat / 'engine/strata'), 'cwd': str(flat),
                                     'tokenizer': '/fixture/tokenizer', 'args': []}))
        self.cross_pin_cli(self.old, 'profile', 'create', 'linked', '--from-config', str(config), '--output', 'json')
        profiles = Path(self.env['STRATA_PROFILE_DIR'])
        metadata = {p: (p.stat().st_ino, p.read_bytes()) for p in profiles.glob('*.json')}
        config_before = (config.stat().st_ino, config.read_bytes())
        conflict = flat / 'terminal/strata_cli/cli.py'
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(b'ignored unrelated userdata\n')
        with (flat / '.git/info/exclude').open('a') as stream:
            stream.write('\n/terminal/strata_cli/cli.py\n')
        failed = subprocess.run(self.command(self.new), env=dict(self.env, TEST_SOURCE_PATCH=str(SOURCE_PATCH)),
                                capture_output=True, text=True, timeout=60)
        self.assertNotEqual(failed.returncode, 0, failed.stderr + failed.stdout)
        self.assertIn('overwritten by checkout', failed.stderr)
        self.assertEqual((link.lstat().st_dev, link.lstat().st_ino, os.readlink(link)), link_identity)
        self.assertEqual(link.resolve(), external)
        self.assertEqual((config.stat().st_ino, config.read_bytes()), config_before)
        for path, identity in metadata.items():
            self.assertEqual((path.stat().st_ino, path.read_bytes()), identity)
        for path, identity in identities.items():
            self.assertEqual((path.stat().st_dev, path.stat().st_ino, path.read_bytes()), identity)
        self.assertEqual(conflict.read_bytes(), b'ignored unrelated userdata\n')
        self.assert_local_runtime(flat, retained)
        self.assertEqual(subprocess.check_output(['git', '-C', str(flat), 'rev-parse', 'HEAD'], text=True).strip(), self.old)
        conflict.unlink()  # The fixture's own blocker; successful retry must not need Git refusal suppression.
        split = self.prepare_cross_pin(self.new)
        self.assertEqual((split / 'engine').resolve(), external)
        self.assertEqual(self.prepare_cross_pin(self.old), flat)
        self.assertEqual(link.resolve(), external)

    def test_profile_doctor_and_start_repair_preserve_external_sycl_coordinates(self):
        root = self.prepare(self.old)
        self.run_source_script(root, r'''
import json, os, shutil
from pathlib import Path
import setup
import strata_managed_state as state
from strata_control import profiles, doctor, cfg_paths, runtime
repository = setup.ROOT.parent
external = repository.parent / 'independent-coordinates'
external.mkdir()
wrapper = external / 'sycl/serve/strata-sycl.sh'
wrapper.parent.mkdir(parents=True)
shutil.copy2(repository / 'engine/sycl/serve/strata-sycl.sh', wrapper)
wrapper.chmod(0o755)
binary = external / 'build-sycl-aot/strata'
binary.parent.mkdir()
binary.write_bytes(b'independent engine')
binary.chmod(0o755)
tokenizer = external / 'tokenizer'
tokenizer.mkdir()
for name in ('vocab.json', 'merges.txt', 'token_type.json'):
    (tokenizer / name).write_text('{}')
os.environ['STRATA_PROFILE_DIR'] = str(repository.parent / 'coordinate-profiles')
for name in tuple(os.environ):
    if name.startswith('STRATA_SYCL_'):
        os.environ.pop(name)
# Deliberately leave ambient cwd inside managed runtime: ownership follows the file.
paths = []
originals = {}
for style in ('relative', 'absolute', 'explicit-cwd'):
    config = {'exe': str(wrapper) if style == 'absolute' else 'sycl/serve/strata-sycl.sh',
              'tokenizer': str(tokenizer), 'args': [], 'backend': 'sycl', 'env': {}}
    if style == 'explicit-cwd':
        config['cwd'] = str(external)
    path = external / ('strata-' + style + '.json')
    path.write_text(json.dumps(config) + '\n')
    path.chmod(0o440)
    stat = path.stat()
    originals[path] = (path.read_bytes(), stat.st_mode, stat.st_dev, stat.st_ino)
    paths.append(path)
    profiles.create('external-' + style, str(path))
    assert profiles.read_run_config(path) == config
    report = doctor.inspect(path)
    assert next(c['path'] for c in report['components'] if c['name'] == 'engine') == str(binary), report
    assert next(c['status'] for c in report['components'] if c['name'] == 'engine') == 'ok', report
    assert cfg_paths.repair([path]) == ([], [])
unknown = {'exe': 'sycl/serve/strata-sycl.sh', 'tokenizer': str(tokenizer), 'args': []}
assert cfg_paths.resolve_config(unknown) == (unknown, [], [])
# Calling the real start preparation repairs ALL saved profiles, not only the selected one.
assert runtime._repair_config_paths('external-relative') == (None, None)
plan, digest = runtime._start_candidate('external-relative')
assert Path(plan['source_config']) == paths[0]
assert digest == __import__('hashlib').sha256(paths[0].read_bytes()).hexdigest()
assert profiles.read_run_config(Path(plan['source_config']))['exe'] == 'sycl/serve/strata-sycl.sh'
for path, before in originals.items():
    stat = path.stat()
    assert (path.read_bytes(), stat.st_mode, stat.st_dev, stat.st_ino) == before
# Managed positive control: config-directory coordinates still select the stable transport.
managed_binary = repository / 'engine/build-sycl-aot/strata'
managed_binary.parent.mkdir(exist_ok=True)
managed_binary.write_bytes(b'managed engine')
managed_binary.chmod(0o755)
model = repository / 'models/coordinate.gguf'
model.parent.mkdir(exist_ok=True)
model.write_bytes(b'inert managed GGUF payload')
managed = {'exe': '../engine/sycl/serve/strata-sycl.sh', 'tokenizer': str(tokenizer),
           'args': ['--native', '/work/' + repository.name + '/models/coordinate.gguf'],
           'backend': 'sycl', 'env': {}}
path = setup.ROOT / 'strata-managed-coordinates.json'
path.write_text(json.dumps(managed))
normalized = profiles.read_run_config(path)
assert normalized['exe'] == str(state.DIRECTORY / 'strata-sycl.sh')
assert Path(cfg_paths.engine_binary(normalized['exe'], normalized)) == managed_binary
assert 'cwd' not in normalized
report = doctor.inspect(path)
assert next(c['path'] for c in report['components'] if c['name'] == 'engine') == str(managed_binary), report
assert cfg_paths.repair([path])[0]
assert json.loads(path.read_text()) == normalized
profiles.create('managed-coordinates', str(path))
plan, digest = runtime._start_candidate('managed-coordinates')
assert plan['engine_exe'] == normalized['exe'], plan
assert plan['source_config'] == str(path), plan
server_args = plan['server_argv']
assert server_args[server_args.index('--engine') + 1] == 'strata', plan
assert server_args[server_args.index('--config') + 1] == str(path), plan
routed = profiles.read_run_config(Path(server_args[server_args.index('--config') + 1]))
assert routed == normalized
assert Path(cfg_paths.engine_binary(routed['exe'], routed)) == managed_binary
assert managed_binary.is_file() and os.access(managed_binary, os.X_OK)
assert Path(routed['exe']).is_file() and os.access(routed['exe'], os.X_OK)
operand = plan['engine_argv'][plan['engine_argv'].index('--native') + 1]
assert cfg_paths.engine_argument_path(operand, plan['engine_exe'], routed) == model
assert model.read_bytes() == b'inert managed GGUF payload'
assert digest == __import__('hashlib').sha256(path.read_bytes()).hexdigest()
''')

    def test_models_explain_public_launch_directories_and_native_case_lookup_are_read_only(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import json, os, subprocess, sys
from pathlib import Path
from strata_cli.launch.catalog import Catalog
from strata_cli.models_explain import explain, words
root = Path.cwd()
os.environ["STRATA_INSTALL_DIR"] = str(root)
os.environ.pop("STRATA_WORKSPACE_CONTEXT", None)
cat = Catalog(src=root, root=root, hardware={})
assert not hasattr(cat, "data_dir_for")
native = cat.launch_directories("qwen", "iq3_xxs")
assert native.models_argument is None
base = root.parent.parent / "explain-fixtures"
base.mkdir()
data, models, explicit = (base / name for name in ("data", "separate-models", "explicit"))
def public(*args, human=False):
    result = subprocess.run([sys.executable, str(root / "strata.py"), "models", "explain",
        "qwen/iq3_xxs", *args, "--output", "human" if human else "json"],
        capture_output=True, text=True, env=os.environ)
    assert result.returncode == 0, result.stderr + result.stdout
    return result.stdout if human else json.loads(result.stdout)
def check(expected_models, **kwargs):
    before = {str(p): p.read_bytes() for p in base.rglob("*") if p.is_file()}
    result = explain("qwen/iq3_xxs", catalog=cat, **kwargs)
    assert result["models_dir"] == str(expected_models), result
    trace = cat.model_folder_trace(Path(result["data_dir"]), "qwen", "IQ3_XXS",
        models_dir=expected_models)
    assert result["folder"] == str(trace["folder"]) and result["rule"] == trace["rule"], result
    assert result["tried"] == [{"path": str(t["path"]), "rule": t["rule"], "exists": t["exists"]} for t in trace["tried"]]
    args = ["--data-dir", str(kwargs["data_dir"])] if kwargs else []
    assert public(*args) == {"schema_version": 1, "ok": True, **result}
    assert public(*args, human=True).strip() == words(result)
    assert {str(p): p.read_bytes() for p in base.rglob("*") if p.is_file()} == before
    return result
# No managed context: use native defaults and the canonical fallback.
result = check(native.models_dir)
assert result["rule"] == "fallback" and not result["found"]
# The override goes through the same launch policy, not a private explain shortcut.
folder = explicit / "models/iq3_xxs"
folder.mkdir(parents=True)
(folder / "weights.gguf").write_bytes(b"inert weights")
(folder / "mmproj-reader.gguf").write_bytes(b"reader")
result = check(folder.parent, data_dir=str(explicit))
assert result["rule"] == ("exact" if (folder.parent / "IQ3_XXS").is_dir() else "lower")
assert result["weights_bytes"] == len(b"inert weights")
assert len(result["gguf_files"]) == 2
# Managed GGUF storage is independent of the data folder, including overrides.
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent.parent),
    "data_directory": str(data), "models_directory": str(models)})
folder = models / "iQ3_xXs"
folder.mkdir(parents=True)
(folder / "weights.gguf").write_bytes(b"separate inert weights")
result = check(models)
assert result["rule"] == ("exact" if (models / "IQ3_XXS").is_dir() else "case")
assert result["data_dir"] == str(data)
result = check(models, data_dir=str(explicit))
assert result["data_dir"] == str(explicit) and result["models_dir"] == str(models)
(folder / "weights.gguf").unlink()
folder.rmdir()
(models / "unrelated").mkdir()
result = check(models)
assert result["rule"] == "fallback" and result["other_folders"] == ["unrelated"]
assert not data.exists()
''')

    def test_launch_directory_policy_preserves_native_ownership_and_helper_forecasts(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import json, os
from pathlib import Path
from strata_cli.launch.catalog import Catalog
from strata_cli.launch.runner import Runner
from strata_cli.launch.settings import LaunchSettings
from strata_control import drafting, engine_component
root = Path.cwd()
base = root.parent.parent / "policy"
base.mkdir()
native, data, models = (base / name for name in ("native", "managed-data", "managed-models"))
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent.parent),
    "data_directory": str(data), "models_directory": str(models)})
cat = Catalog(src=root, root=root, hardware={})
mod = cat.strata.setup_module()
cat.data_dir_choice = lambda: (native, "default")
def forbidden(*args, **kwargs):
    raise AssertionError("directory resolution wrote data")
mod.data_folder = mod.data_folder_for = mod.save_settings = forbidden
mod.acquisition.require = forbidden
drafting.detect_hardware = lambda: ("cpu", [])
engine_component.status = lambda *args: {"usable": True, "engine": {"backend": "cpu"}}
new = cat.launch_directories("qwen", "iq3_xxs")
assert new.data_dir == data and new.models_dir == models
assert not data.exists() and not models.exists()
own = base / "own/models/IQ3_XXS"
own.mkdir(parents=True)
(own / "first.gguf").write_bytes(b"own")
chosen = cat.launch_directories("qwen", "iq3_xxs", model_path=str(own))
assert chosen.data_dir == base / "own" and chosen.models_dir == models
installed = base / "installed"
pack = installed / "packs/iq3_xxs"
pack.mkdir(parents=True)
(pack / "native_experts.txt").write_text("ready")
config = root / "strata-iq3_xxs.json"
config.write_text(json.dumps({"exe": "engine", "args": ["--pack", str(pack), "--native", str(own / "first.gguf")]}))
assert cat.launch_directories("qwen", "iq3_xxs").data_dir == installed
explicit = cat.launch_directories("qwen", "iq3_xxs", data_dir=base / "explicit")
assert explicit.data_dir == base / "explicit"
config.unlink()
cat.data_dir_choice = lambda: (native, "setting")
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent.parent), "models_directory": str(models)})
assert cat.launch_directories("qwen", "iq3_xxs").setup_data_dir == native
external = base / "external"
external.mkdir()
alias = base / "external-alias"
alias.symlink_to(external, target_is_directory=True)
other = Catalog(src=root, root=alias, hardware={})
other.data_dir_choice = lambda: (native, "default")
assert other.launch_directories("qwen", "iq3_xxs").data_dir == native
assert other.launch_directories("qwen", "iq3_xxs").models_argument is None
# Helpers use the managed data root and the independent models root.
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent.parent),
    "data_directory": str(data), "models_directory": str(models)})
(data / "mtp/rt").mkdir(parents=True)
(data / "mtp/rt/experts.bin").write_bytes(b"mtp")
models.mkdir()
(models / mod.FAMILIES["qwen"]["mmproj"]).write_bytes(b"reader")
runner = Runner(LaunchSettings(family="qwen", model="IQ3_XXS", vision="on", mtp="on", drafting="mtp"), catalog=cat)
state = runner.model_state()
assert {p.kind for p in state.parts} == {"weights"}, state
assert {p["kind"] for p in runner.download_plan()["parts"]} == {"weights"}
assert runner.drafting_inputs({})["data_dir"] == data
# Finished model files need no download credit from their sizes or leftover partial files.
layout = cat.launch_directories("qwen", "IQ3_XXS")
for shard in layout.layout[3]:
    shard.parent.mkdir(parents=True, exist_ok=True)
    shard.write_bytes(b"complete model")
    mod.mark(shard)
(data / "mtp/rt/experts.bin").unlink()
state = runner.model_state()
parts = [part for part in state.parts if part.gb > 0]
assert {part.kind for part in parts} == {"mtp"}, state
assert layout.download_directory(part.kind for part in parts) == data
plan = runner.download_plan()
assert {part["kind"] for part in plan["parts"]} == {"mtp"}, plan
assert layout.download_directory(part["kind"] for part in plan["parts"] if part["gb"] > 0) == data
(data / "mtp/rt/experts.bin").write_bytes(b"mtp")
(models / mod.FAMILIES["qwen"]["mmproj"]).unlink()
state = runner.model_state()
parts = [part for part in state.parts if part.gb > 0]
assert {part.kind for part in parts} == {"mmproj"}, state
assert layout.download_directory(part.kind for part in parts) == models
plan = runner.download_plan()
assert {part["kind"] for part in plan["parts"]} == {"mmproj"}, plan
assert layout.download_directory(part["kind"] for part in plan["parts"] if part["gb"] > 0) == models
assert not native.exists()
''')

    def test_folder_enter_preserves_explicit_choice_without_saving_implicit_default(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import asyncio, json, os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from textual.app import App
from textual.widgets import Input
from strata_cli.launch.app import Ctx
from strata_cli.launch.catalog import Catalog, ModelRow
from strata_cli.launch.settings import LaunchSettings
from strata_cli.launch.screens import FolderScreen
from strata_cli.launch.widgets import CSS
from strata_control import drafting
root = Path.cwd()
base = root.parent.parent / "folder-choice"
base.mkdir()
managed, explicit = base / "managed", base / "explicit"
managed.mkdir()
explicit.mkdir()
settings_file = base / "settings.json"
settings_file.write_text("{}")
os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root), STRATA_SETTINGS_FILE=str(settings_file),
    STRATA_WORKSPACE_CONTEXT=json.dumps({"state": str(root.parent.parent), "data_directory": str(managed)}))
cat = Catalog(src=root, root=root, hardware={})
row = ModelRow(family="qwen", family_title="Qwen", model="IQ3_XXS", id="iq3_xxs", about="",
    download_gb=1, need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits",
    experimental=False, images=False, installed=False)
cat.rows = lambda: [row]
async def exercise(choice, typed=None, expected=None):
    settings = LaunchSettings(family="qwen", model="IQ3_XXS", context=8192, data_dir=choice,
                              vision="off", mtp="off", drafting="off")
    ctx = Ctx(cat, NS(usable_gpus=[], main_vram_gb=0, other_vendor_note=""), [row], settings)
    class Surface(App):
        CSS = CSS
        def __init__(self):
            super().__init__()
            self.ctx = ctx
            self.advanced = False
        def on_mount(self):
            self.push_screen(FolderScreen())
        def advance(self):
            self.advanced = True
    app = Surface()
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#folderpath", Input).value == (choice or str(managed))
        if typed is not None:
            app.screen.query_one("#folderpath", Input).value = typed
        await pilot.press("enter")
        await pilot.pause()
        assert app.advanced
        result = expected if typed is not None else choice
        assert settings.data_dir == result
        selected = cat.launch_directories(settings.family, settings.model, data_dir=settings.data_dir)
        assert selected.data_dir == (Path(result) if result else managed)
with patch.object(drafting, "detect_hardware", return_value=("cpu", [])):
    asyncio.run(exercise(str(explicit)))
    asyncio.run(exercise(str(managed)))
    asyncio.run(exercise(str(explicit), typed=str(managed)))
    asyncio.run(exercise(None))
''')


    def test_installed_move_plan_credits_only_complete_native_destinations(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import contextlib, io, json, os, socket, subprocess
from pathlib import Path
from unittest.mock import patch
from strata_cli import cli
from strata_cli.launch import catalog as C, cmd
from strata_cli.launch.runner import Runner
from strata_control import drafting, engine_component
root = Path.cwd()
base = root.parent.parent / "installed-move"
base.mkdir()
for scenario in ("move", "split", "missing-sibling", "unfinished-destination"):
    home = base / scenario
    old, new, models = (home / name for name in ("old", "new", "gguf"))
    for path in (old, new, models):
        path.mkdir(parents=True)
    settings = home / "settings.json"
    settings.write_text(json.dumps({"data_dir": str(old)}))
    os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root), STRATA_SETTINGS_FILE=str(settings),
        STRATA_WORKSPACE_CONTEXT=json.dumps({"state": str(root.parent.parent),
            **({"models_directory": str(models)} if scenario == "split" else {})}))
    cat = C.Catalog(src=root, root=root, hardware={})
    mod = cat.strata.setup_module()
    family, model = "qwen", "IQ3_XXS"
    row = C.ModelRow(family=family, family_title="Qwen", model=model, id="iq3_xxs", about="", download_gb=1,
        need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits",
        experimental=False, images=False, installed=True)
    cat.rows = lambda: [row]
    folder = old / "models" / model
    folder.mkdir(parents=True)
    shards = [folder / mod.model_file(mod.FAMILIES[family], model, index)
              for index in range(1, mod.model_shards(mod.FAMILIES[family], model) + 1)]
    for shard in shards:
        shard.write_bytes(b"completed fixture")
        mod.mark(shard)
    pack = old / "packs/iq3_xxs"
    pack.mkdir(parents=True)
    config = root / "strata-iq3_xxs.json"
    config.write_text(json.dumps({"exe": str(root / "engine/strata"), "args": ["--native", str(shards[0]), "--pack", str(pack)]}))
    cat.strata.describe_config = lambda path: {"images": "off"}
    if scenario == "missing-sibling":
        shards[-1].unlink()
    if scenario == "unfinished-destination":
        destination = new / shards[-1].relative_to(old)
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"unfinished conflict")
    def forbidden(*args, **kwargs):
        raise AssertionError("plan attempted acquisition or data mutation")
    def plan():
        output = io.StringIO()
        before = (settings.read_bytes(), config.read_bytes())
        with patch.object(mod, "data_folder", side_effect=forbidden), patch.object(mod, "data_folder_for", side_effect=forbidden), \
                patch.object(mod, "save_settings", side_effect=forbidden), contextlib.redirect_stdout(output):
            assert cmd.run_launch(cli.parse_args(["launch", "--family", family, "--model", model, "--context", "8192",
                "--data-dir", str(new), "--move-data", "--vision", "off", "--mtp", "off", "--drafting", "off",
                "--no-api-key", "--plan", "--output", "json"])) == 0
        assert before == (settings.read_bytes(), config.read_bytes())
        return json.loads(output.getvalue())["plan"]["download"]["gb"]
    with contextlib.ExitStack() as guards:
        guards.enter_context(patch.object(subprocess, "Popen", side_effect=forbidden))
        guards.enter_context(patch.object(socket.socket, "connect", side_effect=forbidden))
        guards.enter_context(patch.object(mod.acquisition, "require", side_effect=forbidden))
        guards.enter_context(patch.object(drafting, "detect_hardware", return_value=("cpu", [])))
        guards.enter_context(patch.object(engine_component, "status", return_value={"usable": True, "engine": {"backend": "cpu"}}))
        for name, value in (("intel_chosen", False), ("preflight_words", []), ("drafting_plan_line", "")):
            guards.enter_context(patch.object(Runner, name, return_value=value))
        guards.enter_context(patch.object(C, "Catalog", return_value=cat))
        guards.enter_context(patch.object(cmd, "apply_defaults", side_effect=lambda s, c: (s, [])))
        if scenario == "move":
            assert plan() == 0
            assert all(shard.exists() for shard in shards)
            with contextlib.redirect_stdout(io.StringIO()):
                mod.data_folder(str(new), move=True, yes=True, set_default=True)
            assert all((new / shard.relative_to(old)).is_file() and mod.done(new / shard.relative_to(old)) for shard in shards)
            assert plan() == 0
        else:
            assert plan() > 0, scenario
    config.unlink()
''')

    def test_own_file_move_plan_reuses_helper_before_and_after_native_move(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import contextlib, io, json, os, socket, subprocess
from pathlib import Path
from unittest.mock import patch
from strata_cli import cli
from strata_cli.launch import catalog as C, cmd
from strata_cli.launch.runner import Runner
from strata_control import discovery, drafting, engine_component
from tests.terminal.test_own_files import gguf_bytes
root = Path.cwd()
base = root.parent.parent / "own-move"
base.mkdir()
for name in list(os.environ):
    if name.startswith("STRATA_"):
        os.environ.pop(name)
os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root),
                  STRATA_COMPONENTS_DIR=str(base / "components"))
def forbidden(*args, **kwargs):
    raise AssertionError("plan attempted acquisition or data mutation")
for scenario, has_helper, collision in (("move", True, False), ("collision", True, True), ("missing", False, False)):
    home = base / scenario
    old, new, own = (home / name for name in ("old", "new", "own/IQ3_XXS"))
    for folder in (old, new, own):
        folder.mkdir(parents=True)
    settings = home / "settings.json"
    settings.write_text(json.dumps({"data_dir": str(old), "unrelated": "preserved"}))
    os.environ["STRATA_SETTINGS_FILE"] = str(settings)
    cat = C.Catalog(src=root, root=root, hardware={})
    mod = cat.strata.setup_module()
    helper = old / "mtp/rt/experts.bin"
    payload = b"native MTP presence fixture"
    if has_helper:
        helper.parent.mkdir(parents=True)
        helper.write_bytes(payload)
    if collision:
        (new / "mtp").mkdir()
    pack = new / "packs/iq3_xxs"
    pack.mkdir(parents=True)
    (pack / "native_experts.txt").write_bytes(b"prepared pack fixture")
    for index in range(1, mod.model_shards(mod.FAMILIES["qwen"], "IQ3_XXS") + 1):
        (own / mod.model_file(mod.FAMILIES["qwen"], "IQ3_XXS", index)).write_bytes(gguf_bytes(["IQ3_XXS"]))
    assert mod.same_drive(old, new)
    row = C.ModelRow(family="qwen", family_title="Qwen", model="IQ3_XXS", id="iq3_xxs", about="",
        download_gb=1.0, need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits",
        experimental=False, images=False, installed=False)
    cat.rows = lambda: [row]
    command = ["launch", "--family", "qwen", "--model", "IQ3_XXS", "--context", "8192",
        "--data-dir", str(new), "--model-path", str(own), "--move-data", "--plan", "--output", "json",
        "--vision", "off", "--mtp", "on", "--drafting", "mtp", "--no-api-key"]
    def snapshot():
        return {str(path.relative_to(home)): path.read_bytes() if path.is_file() else None
                for path in home.rglob("*")}
    def public_plan():
        before = snapshot()
        output = io.StringIO()
        with patch.object(mod, "data_folder", side_effect=forbidden), \
                patch.object(mod, "data_folder_for", side_effect=forbidden), \
                patch.object(mod, "save_settings", side_effect=forbidden), \
                contextlib.redirect_stdout(output):
            assert cmd.run_launch(cli.parse_args(command)) == 0
        plan = json.loads(output.getvalue())["plan"]
        assert snapshot() == before, scenario
        assert plan["download"]["gb"] == (0 if has_helper else 5.2), (scenario, plan)
        assert ("mtp" in {part["kind"] for part in plan["download"]["parts"]}) == (not has_helper), (scenario, plan)
    with contextlib.ExitStack() as guards:
        guards.enter_context(patch.object(subprocess, "Popen", side_effect=forbidden))
        guards.enter_context(patch.object(socket.socket, "connect", side_effect=forbidden))
        guards.enter_context(patch.object(mod.acquisition, "require", side_effect=forbidden))
        guards.enter_context(patch.object(drafting, "detect_hardware", return_value=("cpu", [])))
        guards.enter_context(patch.object(engine_component, "status", return_value={"usable": True, "engine": {"backend": "cpu"}}))
        guards.enter_context(patch.object(Runner, "intel_chosen", return_value=False))
        guards.enter_context(patch.object(Runner, "preflight_words", return_value=[]))
        guards.enter_context(patch.object(Runner, "drafting_plan_line", return_value=""))
        guards.enter_context(patch.object(C, "Catalog", return_value=cat))
        guards.enter_context(patch.object(cmd, "apply_defaults", side_effect=lambda s, c: (s, [])))
        public_plan()
        with contextlib.redirect_stdout(io.StringIO()):
            dest, elsewhere = mod.data_folder(str(new), move=True, yes=True, set_default=True)
        assert dest == new
        if has_helper:
            expected = helper if collision else new / "mtp/rt/experts.bin"
            assert expected.read_bytes() == payload, scenario
            assert discovery.mtp_layer_in(dest, *elsewhere) == expected.parent, scenario
            assert helper.exists() == collision, scenario
            if collision:
                assert old in elsewhere
        else:
            assert discovery.mtp_layer_in(dest, *elsewhere) is None
        saved = json.loads(settings.read_text())
        assert saved["data_dir"] == str(new) and saved["unrelated"] == "preserved", saved
        # Collision reuse belongs to this setup call's returned roots, not a later invocation.
        if not collision:
            public_plan()
''')

    @unittest.skipUnless(sys.platform == "linux", "Detached benchmark source leases")
    def test_benchmark_child_keeps_only_source_lease_after_controller_dies(self):
        state = self.state
        for completion in ("ready", "terminated"):
            with self.subTest(completion=completion):
                self.state = state / completion
                root = self.prepare(self.old)
                self.make_terminal(root)
                self.make_runtime_model(root)
                selected = root / "strata-fixture.json"
                self.mock_server(root, '''
import json, os, socket
from strata_control import acquisition
api_key_of = lambda key: key
explicit_no_key = lambda key: not key
key_list = lambda key: [key]
engine_args = lambda cfg: cfg["args"]
def main(argv, **kwargs):
    acquisition.service_ready()
    with socket.socket(socket.AF_UNIX) as peer:
        peer.connect(os.environ["BENCH_GATE"])
        peer.sendall(json.dumps({"ready": True}).encode())
        peer.recv(1)
    return 0
''')
                boot = self.base / ("bench-import-" + completion)
                boot.mkdir()
                address = boot / "gate.sock"
                (boot / "sitecustomize.py").write_text('''
import importlib.abc, json, os, socket, sys
from pathlib import Path
if "serve" in sys.orig_argv and any(arg.endswith(("/strata.py", "/terminal-fixture.py")) for arg in sys.orig_argv):
    class ImportGate(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != "strata_control.acquisition":
                return None
            sys.meta_path.remove(self)
            identities = []
            for name in os.listdir("/proc/self/fd"):
                try:
                    st = os.fstat(int(name))
                    identities.append((st.st_dev, st.st_ino))
                except OSError:
                    pass
            state = Path(os.environ["BENCH_STATE"])
            held = {}
            for name in (".source.lock", ".source-publication.lock"):
                st = (state / name).stat()
                held[name] = (st.st_dev, st.st_ino) in identities
            payload = {"pid": os.getpid(), "held": held,
                       "private": any(key in os.environ for key in (
                           "STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT"))}
            with socket.socket(socket.AF_UNIX) as peer:
                peer.connect(os.environ["BENCH_GATE"])
                peer.sendall(json.dumps(payload).encode())
                peer.recv(1)
            return None
    sys.meta_path.insert(0, ImportGate())
''')
                controller_code = '''
import importlib.util, json, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("workspace", sys.argv[1])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
import terminal_fixture_bootstrap
with helper.workspace_lock(sys.argv[2]) as (state, lock):
    os.environ["STRATA_WORKSPACE_LOCK_FD"] = str(lock.fileno())
    os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(state)})
    os.environ["STRATA_WORKSPACE_HELPER"] = sys.argv[1]
    os.set_inheritable(lock.fileno(), True)
    from strata_cli.bench_standard import start_engine, Target
    start_engine(sys.argv[3], Target("http://127.0.0.1:1", None), Path(sys.argv[4]), lambda text: None, 30)
'''
                env = dict(self.env, PYTHONPATH=os.pathsep.join((str(boot), str(root), UPSTREAM)),
                           BENCH_STATE=str(self.state), BENCH_GATE=str(address))
                with socket.socket(socket.AF_UNIX) as listener:
                    listener.bind(str(address))
                    listener.listen(2)
                    listener.settimeout(30)
                    controller = subprocess.Popen([sys.executable, "-c", controller_code, WORKSPACE,
                        str(self.state), str(selected), str(boot / "engine.log")], cwd=root, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.addCleanup(lambda p=controller: p.poll() is None and p.kill())
                    peer, _ = listener.accept()
                    peer.settimeout(30)
                    self.addCleanup(peer.close)
                    payload = json.loads(peer.recv(4096))
                    descriptor = os.pidfd_open(payload["pid"])
                    def cleanup_child(fd=descriptor):
                        try:
                            if not select.select([fd], [], [], 0)[0]:
                                signal.pidfd_send_signal(fd, signal.SIGKILL)
                        finally:
                            os.close(fd)
                    self.addCleanup(cleanup_child)
                    self.assertEqual(payload["held"], {".source.lock": False, ".source-publication.lock": True})
                    self.assertFalse(payload["private"], payload)
                    self.assert_workspace_locked()
                    controller.kill()
                    controller.communicate(timeout=10)
                    self.assertFalse(select.select([descriptor], [], [], 0)[0])
                    self.assert_workspace_unlocked()
                    with (self.state / ".source-publication.lock").open("a") as lock:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    writer_code = '''
import contextlib, importlib.util, sys
spec = importlib.util.spec_from_file_location("workspace", sys.argv[1])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
original = helper.source_publication_lock
@contextlib.contextmanager
def publishing(*args, **kwargs):
    print("publication", flush=True)
    with original(*args, **kwargs) as lock:
        yield lock
helper.source_publication_lock = publishing
helper.prepare_workspace(sys.argv[2], sys.argv[3], remote=sys.argv[4], source_patch=sys.argv[5])
print("published", flush=True)
'''
                    writer = subprocess.Popen([sys.executable, "-c", writer_code, WORKSPACE,
                        str(self.state), self.new, str(self.repository), SOURCE_PATCH], env=self.env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.addCleanup(lambda p=writer: p.poll() is None and p.kill())
                    self.assertEqual(writer.stdout.readline().strip(), "publication")
                    self.assertFalse(select.select([writer.stdout], [], [], 0.2)[0])
                    ready_peer = None
                    if completion == "terminated":
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    else:
                        peer.sendall(b"go")
                        ready_peer, _ = listener.accept()
                        ready_peer.settimeout(30)
                        self.addCleanup(ready_peer.close)
                        self.assertEqual(json.loads(ready_peer.recv(4096)), {"ready": True})
                        self.assertFalse(select.select([descriptor], [], [], 0)[0])
                    peer.close()
                    stdout, stderr = writer.communicate(timeout=30)
                    self.assertEqual(writer.returncode, 0, stdout + stderr)
                    self.assertIn("published", stdout)
                    if ready_peer is not None:
                        ready_peer.sendall(b"end")
                    self.assertTrue(select.select([descriptor], [], [], 15)[0])

    @unittest.skipUnless(sys.platform == "linux", "Native stop and updater lifecycle")
    def test_native_stop_bypasses_waiting_updater_with_parser_precedence(self):
        root = self.prepare(self.old)
        self.make_terminal(root, '''
import os
from strata_control import runtime, updater
from strata_cli import update_cmd
runtime._engine_preflight = lambda plan: None
updater.detect_hardware = lambda: {}
original_context = updater.Context
def context(*args, **kwargs):
    value = original_context(*args, **kwargs)
    value.poll = .05
    return value
updater.Context = context
factory = update_cmd._emit_factory
def observed_factory(*args, **kwargs):
    emit = factory(*args, **kwargs)
    def observed(event):
        emit(event)
        if event.get("event") == "waiting":
            Path(os.environ["UPDATE_WAITING"]).write_text("waiting")
    return observed
update_cmd._emit_factory = observed_factory
''')
        shutil.copyfile(Path(UPSTREAM) / "tools/strata_tokenizer.py", root / "tools/strata_tokenizer.py")
        config = self.make_runtime_model(root)
        config.update(tokenizer=str(root / "no-tokenizer"), port=0, api_key="none")
        (root / "strata-fixture.json").write_text(json.dumps(config))
        boot = self.base / "stop-owner"
        boot.mkdir()
        (boot / "sitecustomize.py").write_text('''
import sys
if "strata_control.runtime" in sys.orig_argv:
    from strata_cli import cli
    original = cli._launch_plan
    def plan(*args, **kwargs):
        result, argv = original(*args, **kwargs)
        argv[argv.index("--engine") + 1] = "mock"
        return result, argv
    cli._launch_plan = plan
''')
        components = self.base / "components"
        (components / ".updates").mkdir(parents=True)
        (components / ".updates/state.json").write_text(json.dumps({"engine": {"previous": "missing-previous"}}))
        waiting = self.base / "updater-waiting"
        env = dict(self.env, PYTHONPATH=os.pathsep.join((str(boot), str(root), UPSTREAM)),
                   UPDATE_WAITING=str(waiting))
        created = subprocess.run([sys.executable, "-c",
            "from strata_control import profiles; profiles.create('launch-stop-fixture', 'strata-fixture.json')"],
            cwd=root, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(created.returncode, 0, created.stderr)
        for stop in (["runtime", "stop", "--profile", "launch-stop-fixture", "--wait", "8", "--output", "json"],
                     ["launch", "--preset", "stop-fixture", "--sto", "--restart"],
                     ["launch", "--preset", "stop-fixture", "--stop", "--plan"]):
            with self.subTest(stop=stop):
                waiting.unlink(missing_ok=True)
                owned, updater = [], None
                try:
                    started = subprocess.run(self.command(self.old) + ["run", "runtime", "start",
                        "--profile", "launch-stop-fixture", "--wait", "20", "--shutdown-timeout", "2", "--output", "json"],
                        cwd=root, env=env, capture_output=True, text=True, timeout=35)
                    snapshot = json.loads(started.stdout)
                    for key in ("host_pid", "child_pid"):
                        if snapshot.get(key):
                            owned.append(os.pidfd_open(snapshot[key]))
                    self.assertEqual(started.returncode, 0, started.stderr + started.stdout)
                    updater = subprocess.Popen(self.command(self.old) + ["run", "components", "rollback",
                        "--components-dir", str(components), "--wait", "12", "--output", "jsonl"],
                        cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    deadline = time.monotonic() + 30
                    while not waiting.exists() and updater.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.02)
                    if not waiting.exists():
                        if updater.poll() is None:
                            updater.kill()
                        stdout, stderr = updater.communicate(timeout=10)
                        self.fail(f"updater never reached native serving wait; exit={updater.returncode}\n{stdout}\n{stderr}")
                    self.assert_workspace_locked()
                    stopped = subprocess.run(self.command(self.old) + ["run", *stop], cwd=root, env=env,
                                             capture_output=True, text=True, timeout=10)
                    self.assertEqual(stopped.returncode, 0, stopped.stderr + stopped.stdout)
                    stdout, stderr = updater.communicate(timeout=10)
                    self.assertEqual(updater.returncode, 5, stdout + stderr)
                    self.assertIn("missing-previous", stdout + stderr)
                    self.assertNotIn("timed out", stdout + stderr)
                    self.assert_workspace_unlocked()
                finally:
                    if updater is not None:
                        if updater.poll() is None:
                            updater.kill()
                        updater.communicate(timeout=10)
                    for fd in reversed(owned):
                        try:
                            if not select.select([fd], [], [], 0)[0]:
                                signal.pidfd_send_signal(fd, signal.SIGKILL)
                            select.select([fd], [], [], 10)
                        finally:
                            os.close(fd)

    def test_launch_ready_forecasts_share_split_and_retained_native_layout(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import json, os
from pathlib import Path
from strata_cli.launch.catalog import Catalog
from strata_cli.launch.runner import Runner
from strata_cli.launch.settings import LaunchSettings
from strata_control import drafting, engine_component
root = Path.cwd()
base = root.parent.parent / "ready-plans"
cat = Catalog(src=root, root=root, hardware={})
mod = cat.strata.setup_module()
drafting.detect_hardware = lambda: ("cpu", [])
engine_component.status = lambda *args: {"usable": True, "engine": {"backend": "cpu"}}
def forbidden(*args, **kwargs):
    raise AssertionError("read-only ready forecast acquired or moved files")
mod.data_folder = mod.data_folder_for = mod.save_settings = forbidden
mod.acquisition.require = forbidden
def seed(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture")
    mod.mark(path, text)
for model in ("NVFP4", "NVFP4-QAD"):
    data, models, native = (base / model / part for part in ("data", "gguf", "native"))
    cat.data_dir_choice = lambda: (native, "default")
    os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent.parent),
        "data_directory": str(data), "models_directory": str(models)})
    runner = Runner(LaunchSettings(family="nvfp4", model=model.lower(), vision="off", mtp="off", drafting="off"), catalog=cat)
    selected = cat.launch_directories("nvfp4", model.lower())
    assert selected.layout[0] == models and selected.layout[1] == data
    for item in mod.ready_files(model):
        seed(mod.ready_where(models, item, data), "sha256 " + item[5])
    if mod.MODELS[model].get("prepare"):
        # Real producer completion marks, not network files. Completed preparation no longer needs source tensors.
        prepared = mod.ready_paths(model, models, data)
        for path in (prepared["dense"], prepared["ple"], prepared["pack"] / "index.txt", prepared["mtp"] / "rt/experts.bin"):
            seed(path)
        for path in (prepared["ple"].with_name("ple-nvfp4.gguf.done"), prepared["dense"].with_name("dense.gguf.done"),
                     prepared["pack"].parent / "pack.done", prepared["mtp"].parent / "draft.done"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("prepared")
        assert mod.prepared_done(model, models, data)
        for item in mod.ready_files(model):
            if item[3].startswith("tensors/"):
                mod.ready_where(models, item, data).unlink()
    selected = cat.launch_directories("nvfp4", model.lower())
    assert not any(path.suffix == ".safetensors" for path in selected.layout[3]) if mod.MODELS[model].get("prepare") else True
    assert runner.model_state().remaining_gb == 0, (model, runner.model_state())
    assert runner.download_plan()["gb"] == 0
    assert runner.ready_pack_gap() is None
    job = runner.progress_job()
    assert [Path(f["path"]) for f in job["files"] if f["role"] == "model"] == selected.layout[3]
    missing = next(item for item in mod.ready_needed(model, models, data) if item[0] not in ("dense", "ple", "embd"))
    path = mod.ready_where(models, missing, data)
    path.unlink()
    gap = runner.ready_pack_gap()
    assert gap is not None and Path(gap["folder"]) == path.parent, gap
    assert runner.catalog.launch_directories("nvfp4", model).download_dir == path.parent
    seed(path, "sha256 " + missing[5])
    # A complete legacy layout stays in place even when a new models root is configured.
    legacy = data / "models"
    for item in mod.ready_files(model):
        seed(mod.ready_where(legacy, item), "sha256 " + item[5])
    if mod.MODELS[model].get("prepare"):
        prepared = mod.ready_paths(model, legacy)
        for path in (prepared["dense"], prepared["ple"], prepared["pack"] / "index.txt", prepared["mtp"] / "rt/experts.bin"):
            seed(path)
        for path in (prepared["ple"].with_name("ple-nvfp4.gguf.done"), prepared["dense"].with_name("dense.gguf.done"),
                     prepared["pack"].parent / "pack.done", prepared["mtp"].parent / "draft.done"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("prepared")
        for item in mod.ready_files(model):
            if item[3].startswith("tensors/"):
                mod.ready_where(legacy, item).unlink()
    os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent.parent),
        "data_directory": str(data), "models_directory": str(models.parent / "new-gguf")})
    selected = cat.launch_directories("nvfp4", model)
    assert selected.layout[0] == legacy and selected.layout[1] is None, selected
    assert runner.model_state().remaining_gb == 0
    assert runner.ready_pack_gap() is None
''')

    @unittest.skipUnless(sys.platform == "linux", "Native parser lock precedence")
    def test_stop_flags_do_not_bypass_prior_preset_actions_or_restart(self):
        root = self.prepare(self.old)
        self.make_terminal(root)
        presets = self.base / "stop-presets"
        env = dict(self.env, STRATA_LAUNCH_PRESET_DIR=str(presets))
        saved = subprocess.run([sys.executable, "-c",
            "from strata_cli.launch import store, settings; store.save(settings.LaunchSettings(name='precedence'))"],
            cwd=root, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(saved.returncode, 0, saved.stderr)
        for argv, code in ((["launch", "--stop", "--list-presets", "--output", "json"], 0),
                           (["launch", "--stop", "--delete-preset", "precedence"], 0),
                           (["runtime", "restart", "--profile", "missing", "--plan", "--output", "json"], 3)):
            with self.subTest(argv=argv):
                with (self.state / ".source.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    process = subprocess.Popen(self.command(self.old) + ["run", *argv], env=env, cwd=root,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.addCleanup(lambda p=process: p.poll() is None and p.kill())
                    deadline = time.monotonic() + 8
                    while process.poll() is None and time.monotonic() < deadline:
                        if "lock" in Path(f"/proc/{process.pid}/wchan").read_text():
                            break
                        time.sleep(.02)
                    self.assertIsNone(process.poll())
                    self.assertIn("lock", Path(f"/proc/{process.pid}/wchan").read_text())
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, code, stdout + stderr)
                if "--list-presets" in argv:
                    self.assertEqual(json.loads(stdout)["presets"][0]["name"], "precedence")
                elif "--delete-preset" in argv:
                    self.assertFalse((presets / "precedence.json").exists())
        with (self.state / ".source.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            invalid = subprocess.run(self.command(self.old) + ["run", "launch", "--st"], env=env, cwd=root,
                                     capture_output=True, text=True, timeout=10)
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("ambiguous option: --st", invalid.stderr)

    def test_new_pin_launch_and_runtime_options_prepare_before_native_parser(self):
        state = self.state
        launch = self.repo / "strata_cli/launch/cmd.py"
        source = launch.read_text()
        anchor = '    m.add_argument("--stop", action="store_true"'
        self.assertIn(anchor, source)
        launch.write_text(source.replace(anchor,
            '    m.add_argument("--new-pin-option", action="store_true")\n' + anchor, 1))
        cli = self.repo / "strata_cli/cli.py"
        source = cli.read_text()
        anchor = '    runtime_stop.add_argument("--profile", required=True)'
        self.assertIn(anchor, source)
        cli.write_text(source.replace(anchor,
            '    runtime_stop.add_argument("--new-pin-option", action="store_true")\n' + anchor, 1))
        revision = self.commit()
        for argv, code in ((["launch", "--stop", "--new-pin-option"], 0),
                           (["runtime", "stop", "--profile", "missing-new-pin-profile",
                             "--new-pin-option", "--output", "json"], 5)):
            with self.subTest(argv=argv):
                self.state = state / argv[0]
                root = self.prepare(self.old)
                self.make_terminal(root)
                result = subprocess.run(self.command(revision) + ["run", *argv], env=self.env, cwd=root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertNotIn("unrecognized arguments", result.stdout + result.stderr)
                self.assertEqual((root / "code.py").read_text(), "new source\n")



    def test_reconfigured_installations_reuse_native_sources_without_retargeting_downloads(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import contextlib, io, json, os
from pathlib import Path
from types import SimpleNamespace as NS
from strata_cli.launch.catalog import Catalog, ModelRow
from strata_cli.launch.settings import LaunchSettings
from strata_cli.launch.runner import Runner, desc_matches
from tools.strata_mcp import expected_files
root = Path.cwd()
base = root.parent.parent / "reconfigured"
base.mkdir()
engine = root / "engine/strata"
engine.parent.mkdir()
engine.write_bytes(b"engine=0.1.46\\n")
engine.chmod(0o700)
for family, model in (("qwen", "IQ3_XXS"), ("qwen36", "UD-Q4_K_XL")):
    home = base / family
    data, requested = home / "data", home / "requested"
    data.mkdir(parents=True)
    requested.mkdir()
    settings_file = home / "settings.json"
    settings_file.write_text(json.dumps({"data_dir": str(data)}))
    os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root),
        STRATA_SETTINGS_FILE=str(settings_file), STRATA_WORKSPACE_CONTEXT=json.dumps({
            "state": str(root.parent.parent), "data_directory": str(data), "models_directory": str(requested)}))
    cat = Catalog(src=root, root=root, hardware={})
    mod = cat.strata.setup_module()
    tag = cat.tag_of(family, model)
    row = ModelRow(family=family, family_title=family, model=model, id=tag, about="",
        download_gb=1, need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits",
        experimental=False, images=False, installed=True)
    cat.rows = lambda: [row]
    def select(models, retained=(), vision=False):
        return expected_files(mod, family, model, models, vision, data_dir=data, elsewhere=retained)
    old_files = select(data / "models")
    assert old_files
    for item in old_files:
        path = Path(item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as target:
            target.truncate(item["bytes"] or 32)
        mod.mark(path)
    pack = data / "packs" / tag
    pack.mkdir(parents=True)
    args = ["--pack", str(pack), "--max-context", "8192", "--kv", "fp16"]
    args += ["--native", old_files[0]["path"]]
    config = root / ("strata-" + tag + ".json")
    config.write_text(json.dumps({"exe": str(engine), "args": args}))
    s = LaunchSettings(family=family, model=model, context=32768, vision="off", mtp="off", drafting="off")
    runner = Runner(s, catalog=cat)
    installed, desc = runner.installed_state()
    assert installed == config and not desc_matches(desc, s)
    assert runner.model_state().remaining_gb == 0
    argv = runner.setup_args()
    assert Path(argv[argv.index("--models-dir") + 1]) == requested
    with contextlib.redirect_stdout(io.StringIO()):
        actual_data, retained = mod.data_folder_for(NS(data_dir=str(data), move_data=False,
            yes=True, set_default_data_dir=False, separate_model_artifacts=True))
    assert actual_data == data
    selected = select(requested, retained)
    assert {item["path"] for item in selected} == {item["path"] for item in old_files}
    assert all(mod.download_complete(Path(item["path"]), own=item.get("accept_unmarked", False)) for item in selected)
    pictures = select(requested, retained, vision=True)
    reader = next(item for item in pictures if item["role"] == "vision")
    assert Path(reader["path"]).is_relative_to(requested), reader
    # A complete explicitly requested set stays ahead of retained files.
    requested_files = select(requested)
    for item in requested_files:
        path = Path(item["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as target:
            target.truncate(item["bytes"] or 32)
        mod.mark(path)
    assert {item["path"] for item in select(requested, retained)} == {item["path"] for item in requested_files}
    config.unlink()
''')

    def test_own_path_forecasts_and_progress_follow_native_completion(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import json, os
from pathlib import Path
from strata_cli.launch.catalog import Catalog, ModelRow
from strata_cli.launch import modelstate
from tools.strata_mcp import expected_files, files_progress
root = Path.cwd()
base = root.parent.parent / "own-path-completion"
base.mkdir()
for scenario in ("requested", "retained", "unmarked", "marker-only"):
    home = base / scenario
    data, models = home / "data", home / "gguf"
    data.mkdir(parents=True)
    models.mkdir()
    settings = home / "settings.json"
    settings.write_text(json.dumps({"data_dir": str(data)}))
    os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root),
        STRATA_SETTINGS_FILE=str(settings), STRATA_WORKSPACE_CONTEXT=json.dumps({
            "state": str(root.parent.parent), "data_directory": str(data), "models_directory": str(models)}))
    cat = Catalog(src=root, root=root, hardware={})
    mod = cat.strata.setup_module()
    family, model = "qwen36", "UD-Q4_K_XL"
    native = mod.own_path_download_layout(family, model, models)
    path = (data / "models" / native["gguf"].parent.name / native["gguf"].name
            if scenario == "retained" else native["gguf"])
    path.parent.mkdir(parents=True)
    if scenario != "marker-only":
        with path.open("wb") as target:
            target.truncate(native["bytes"])
    if scenario != "unmarked":
        mod.mark(path)
    row = ModelRow(family=family, family_title=family, model=model, id="qwen36", about="",
        download_gb=native["bytes"] / 1e9, need_vram_gb=0, need_ram_gb=1, spill_gb=0,
        verdict="fits", words="fits", experimental=False, images=False, installed=False)
    cat.rows = lambda: [row]
    dirs = cat.launch_directories(family, model)
    selected = mod.own_path_download_layout(family, model, models, elsewhere=dirs.elsewhere)
    complete = mod.download_complete(selected["gguf"])
    state = modelstate.assess(cat, family, model, vision="off", mtp="off", drafting="off", directories=dirs)
    assert state.remaining_gb == (0 if complete else native["bytes"] / 1e9), scenario
    assert complete == (scenario in ("requested", "retained"))
    files = expected_files(mod, family, model, models, False, data_dir=data, elsewhere=dirs.elsewhere)
    assert Path(files[0]["path"]) == selected["gguf"]
    if scenario == "unmarked":
        before = files_progress({}, {}, files, setup_module=mod)
        mod.mark(path)
        after = files_progress({}, {}, files, setup_module=mod)
        assert before["parts"][0]["state"] != "done"
        assert after["parts"][0]["state"] == "done"
''')

    def test_native_preset_edit_keeps_explicit_folder_equal_to_default(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import asyncio, json, os
from pathlib import Path
from strata_cli.launch.app import Ctx, LaunchApp
from strata_cli.launch.catalog import Catalog, Computer, ModelRow
from strata_cli.launch.settings import LaunchSettings
from strata_cli.launch import store
from strata_cli.launch.screens import ModelScreen, FolderScreen, ContextScreen
from strata_cli.launch.runner import Runner
root = Path.cwd()
data = root.parent.parent / "preset-data"
data.mkdir()
settings = root.parent.parent / "preset-settings.json"
settings.write_text("{}")
os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root), STRATA_SETTINGS_FILE=str(settings),
    STRATA_LAUNCH_PRESET_DIR=str(root.parent.parent / "presets"),
    STRATA_WORKSPACE_CONTEXT=json.dumps({"state": str(root.parent.parent), "data_directory": str(data)}))
cat = Catalog(src=root, root=root, hardware={})
row = ModelRow(family="qwen", family_title="Qwen", model="IQ3_XXS", id="iq3_xxs", about="",
    download_gb=1, need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits",
    experimental=False, images=False, installed=False)
cat.rows = lambda: [row]
store.save(LaunchSettings(family="qwen", model="IQ3_XXS", context=8192, data_dir=str(data),
                         vision="off", mtp="off", drafting="off"), "folder-equal")
ctx = Ctx(cat, Computer(ram_gb=64, gpus=[], disk_free_gb=100), [row], LaunchSettings())
async def edit():
    app = LaunchApp(ctx, auto_run=False)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, ModelScreen)
        assert ctx.settings.data_dir == str(data)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, FolderScreen)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ContextScreen)
        assert ctx.settings.data_dir == str(data)
        assert "--set-default-data-dir" in Runner(ctx.settings, catalog=cat).setup_args()
asyncio.run(edit())
''')


    def test_launch_progress_follows_native_automatic_migration(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import json, os, socket
from pathlib import Path
from strata_cli.launch.catalog import Catalog, ModelRow
from strata_cli.launch.settings import LaunchSettings
from strata_cli.launch.runner import Runner
root = Path.cwd()
base = root.parent.parent / "migration-progress"
base.mkdir()
requested = base / "requested"
requested.mkdir()
settings = base / "settings.json"
settings.write_text("{}")
os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root), STRATA_SETTINGS_FILE=str(settings),
    STRATA_WORKSPACE_CONTEXT=json.dumps({"state": str(root.parent.parent), "models_directory": str(requested)}))
cat = Catalog(src=root, root=root, hardware={})
mod = cat.strata.setup_module()
family, model = "qwen", "IQ3_XXS"
tag = cat.tag_of(family, model)
count = mod.model_shards(mod.FAMILIES[family], model)
folder = root / "models" / model
folder.mkdir(parents=True)
for index in range(1, count + 1):
    path = folder / mod.model_file(mod.FAMILIES[family], model, index)
    with path.open("wb") as stream:
        stream.truncate(1_000_000_000)
    assert path.stat().st_blocks == 0
    mod.mark(path)
row = ModelRow(family=family, family_title="Qwen", model=model, id=tag, about="", download_gb=count,
    need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits",
    experimental=False, images=False, installed=False)
cat.rows = lambda: [row]
config = root / ("strata-" + tag + ".json")
producer = base / "native-progress.py"
producer.write_text(r"""
import json, socket, sys
from pathlib import Path
import setup as mod
root = Path.cwd()
with socket.socket(socket.AF_UNIX) as gate:
    gate.connect(sys.argv[2])
    assert gate.recv(1) == b"g"
parsed = []
assert mod.main(sys.argv[3:], after_parse=lambda a, argv: (parsed.append(a), 0)[1]) == 0
a = parsed[0]
mod.step(3, "installing dependencies")
mod.say("engine: 1.0 / 2.0 GB (50%)")
mod.step(4, "preparing the engine")
data, retained = mod.data_folder_for(a)
layout = mod.model_download_layout(a.family, a.model, Path(a.models_dir), data_dir=data, elsewhere=retained)
assert all(path.is_file() and mod.done(path) for path in layout[3])
mod.step(5, "downloading model")
for path in layout[3]:
    mod.ok(str(path) + ": already downloaded")
mod.step(6, "writing config")
pack = data / "packs" / "fixture"
pack.mkdir(parents=True)
Path(sys.argv[1]).write_text(json.dumps({"exe": sys.executable,
    "args": ["--native", str(layout[3][0]), "--pack", str(pack), "--max-context", "8192", "--kv", "fp16"]}))
""")
events, observed = [], []
runner = Runner(LaunchSettings(family=family, model=model, context=8192, vision="off", mtp="off", drafting="off"),
    catalog=cat, emit=events.append)
spawn, read_lines, combined = runner._spawn, runner._read_lines, cat.mcp.combined_progress
gate_path = base / "migration.sock"
def spawn_fixture(argv, **kwargs):
    return spawn([argv[0], str(producer), str(config), str(gate_path), *argv[2:]], **kwargs)
def read_fixture(process):
    # Hold migration until stdout consumption begins; earlier snapshots must observe the original paths.
    with listener.accept()[0] as gate:
        gate.sendall(b"g")
    yield from read_lines(process)
def observe(prog, job, **kwargs):
    result = combined(prog, job, **kwargs)
    observed.append((str(prog.get("step") or ""), json.loads(json.dumps(job)), json.loads(json.dumps(result))))
    return result
runner._spawn, runner._read_lines, cat.mcp.combined_progress = spawn_fixture, read_fixture, observe
try:
    with socket.socket(socket.AF_UNIX) as listener:
        listener.settimeout(15)
        listener.bind(str(gate_path))
        listener.listen(1)
        assert runner.ensure_model() == config
finally:
    runner._stop_children()
    cat.mcp.combined_progress = combined
downloads = [(job, shown) for step, job, shown in observed if step.startswith("5/")]
assert downloads
for job, shown in downloads:
    part = next(part for part in shown["parts"] if part["kind"] == "model")
    assert part["state"] == "done" and part["files_done"] == part["files_total"] == count, part
    assert part["done_gb"] == part["total_gb"] == count, part
    assert all(Path(item["path"]).is_file() and not Path(item["path"]).is_relative_to(requested) for item in job["files"])
before = [job for step, job, shown in observed if step.startswith(("3/", "4/"))]
assert before and all(not job for job in before), before
assert all(job == downloads[-1][0] for step, job, shown in observed if step.startswith("6/"))
shown = [event for event in events if str(event.data.get("step") or "").startswith("5/") and event.pct is not None]
assert shown and all(event.pct == 100 for event in shown), shown
assert events[-1].pct == 100
assert not folder.exists()
''')

    def test_launch_progress_keeps_retained_sources_when_saving_data_directory(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import json, os, socket
from pathlib import Path
from strata_cli.launch.catalog import Catalog, ModelRow
from strata_cli.launch.settings import LaunchSettings
from strata_cli.launch.runner import Runner
root = Path.cwd()
base = root.parent.parent / "retained-progress"
old, data, models = base / "arbitrary-storage/retained-data", base / "new-data", base / "requested-gguf"
for path in (old, data, models):
    path.mkdir(parents=True)
settings = base / "settings.json"
settings.write_text(json.dumps({"data_dir": str(old)}))
os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root), STRATA_SETTINGS_FILE=str(settings),
    STRATA_WORKSPACE_CONTEXT=json.dumps({"state": str(root.parent.parent), "models_directory": str(models)}))
cat = Catalog(src=root, root=root, hardware={"ram_gb": 64, "gpus": []})
mod = cat.strata.setup_module()
family, model = "qwen36", "UD-Q4_K_XL"
fam = mod.OWN_PATH_FAMILIES[family]
filename = fam["file"].format(q=model)
retained = old / "models" / (fam["tag"] + model) / filename
retained.parent.mkdir(parents=True)
size, sha = fam["sha256"][filename]
with retained.open("wb") as stream:
    stream.truncate(size)
assert retained.stat().st_blocks == 0
mod.mark(retained, "sha256 " + sha)
tag = cat.tag_of(family, model)
row = ModelRow(family=family, family_title="Qwen3.6", model=model, id=tag, about="", download_gb=size / 1e9,
    need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits",
    experimental=False, images=False, installed=False)
cat.rows = lambda: [row]
config = root / ("strata-" + tag + ".json")
selection = base / "selection.json"
producer = base / "native-progress.py"
producer.write_text(r"""
import json, socket, sys
from pathlib import Path
import setup as mod
parsed = []
assert mod.main(sys.argv[4:], after_parse=lambda a, argv: (parsed.append(a), 0)[1]) == 0
a = parsed[0]
mod.step(3, "installing dependencies")
mod.step(4, "preparing the engine")
data, elsewhere = mod.data_folder_for(a)
selected = mod.own_path_download_layout(a.family, a.model, Path(a.models_dir), gguf_dir=a.gguf_dir, elsewhere=elsewhere)
Path(sys.argv[3]).write_text(json.dumps({"selected": str(selected["gguf"]),
    "complete": mod.download_complete(selected["gguf"]), "settings": mod.load_settings()}))
with socket.socket(socket.AF_UNIX) as gate:
    gate.settimeout(15)
    gate.connect(sys.argv[2])
    mod.step(5, "downloading model")
    mod.ok(str(selected["gguf"]) + ": already downloaded")
    assert gate.recv(1) == b"g"
mod.step(6, "writing config")
pack = data / "packs" / "fixture"
pack.mkdir(parents=True)
Path(sys.argv[1]).write_text(json.dumps({"exe": sys.executable,
    "args": ["--native", str(selected["gguf"]), "--pack", str(pack), "--max-context", "8192", "--kv", "fp16"]}))
""")
events, observed = [], []
acknowledged = False
gate_path = base / "selection.sock"
def emit(event):
    global acknowledged
    events.append(event)
    if str(event.data.get("step") or "").startswith("5/") and not acknowledged:
        # Observe progress before the installed config can make the retained model discoverable.
        assert not config.exists()
        with listener.accept()[0] as gate:
            gate.sendall(b"g")
        acknowledged = True
runner = Runner(LaunchSettings(family=family, model=model, context=8192, data_dir=str(data),
    vision="off", mtp="off", drafting="off"), catalog=cat, emit=emit)
spawn, combined = runner._spawn, cat.mcp.combined_progress
def spawn_fixture(argv, **kwargs):
    return spawn([argv[0], str(producer), str(config), str(gate_path), str(selection), *argv[2:]], **kwargs)
def observe(prog, job, **kwargs):
    shown = combined(prog, job, **kwargs)
    if str(prog.get("step") or "").startswith("5/"):
        observed.append(json.loads(json.dumps({"job": job, "shown": shown})))
    return shown
runner._spawn, cat.mcp.combined_progress = spawn_fixture, observe
try:
    with socket.socket(socket.AF_UNIX) as listener:
        listener.settimeout(15)
        listener.bind(str(gate_path))
        listener.listen(1)
        assert runner.ensure_model() == config
finally:
    runner._stop_children()
    cat.mcp.combined_progress = combined
actual = json.loads(selection.read_text())
assert actual["selected"] == str(retained) and actual["complete"], actual
assert actual["settings"]["data_dir"] == str(data), actual
assert acknowledged and observed
for snapshot in observed:
    part = next(part for part in snapshot["shown"]["parts"] if part["kind"] == "model")
    assert part["state"] == "done" and part["files_done"] == part["files_total"] == 1, part
    assert part["done_gb"] == part["total_gb"] > 0, part
    assert [item["path"] for item in snapshot["job"]["files"] if item.get("role", "model") == "model"] == [str(retained)]
shown = [event for event in events if str(event.data.get("step") or "").startswith("5/") and event.pct is not None]
assert shown and all(event.pct == 100 for event in shown), shown
assert events[-1].pct == 100
assert retained.is_file() and not (models / (fam["tag"] + model) / filename).exists()
''')

    def test_family_preparation_keeps_selected_sources_after_saving_data_directory(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import contextlib, io, json, os, shutil, socket, subprocess
from pathlib import Path
from unittest.mock import patch
root = Path.cwd()
base = root.parent.parent / "family-preparation"
base.mkdir()
os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root))
import setup
@HARDWARE@
card["count"] = 1
setup.ram_gb = lambda: 2000
setup.gpu_compute_mode = lambda *args: None
setup.gpu_drives_display = lambda *args: False
setup.rotational_disk = lambda *args: None
setup.free_gb = lambda *args: 1000.0
setup.cpu_sockets = lambda: []
setup.disk_room_problem = lambda *args: None
class Prepared(Exception):
    pass
def forbidden(*args, **kwargs):
    raise AssertionError("unexpected acquisition, process or network")
for family, model, vision in (("qwen36", "UD-Q4_K_XL", "no"),
                              ("qwen36", "UD-Q4_K_XL", "yes")):
    for move in (False, True):
        name = f"{family}-{vision}-{move}"
        data, models = base / name / "data", base / name / "gguf"
        data.mkdir(parents=True)
        models.mkdir()
        settings = base / name / "settings.json"
        settings.write_text(json.dumps({"data_dir": str(root)}))
        os.environ["STRATA_SETTINGS_FILE"] = str(settings)
        fam = setup.OWN_PATH_FAMILIES[family]
        folder = root / "models" / (fam["tag"] + model)
        originals = [folder / fam["file"].format(q=model)]
        if vision == "yes":
            originals.append(folder / fam["mmproj"])
        for path in originals:
            path.parent.mkdir(parents=True, exist_ok=True)
            size, sha = fam["sha256"][path.name]
            with path.open("wb") as stream:
                stream.truncate(size)
            assert path.stat().st_blocks == 0
            setup.mark(path, "sha256 " + sha)
        # Explicit moves select the merged folder; keep uses retained files without moving them.
        selected_models = data / "models" if move else models
        expected = [data / path.relative_to(root) if move else path for path in originals]
        reached = []
        def prepare(command, **kwargs):
            assert all(path.is_file() and setup.done(path) for path in expected), (name, command)
            assert all((data / path.relative_to(root)).exists() == move for path in originals), name
            assert json.loads(settings.read_text())["data_dir"] == str(data)
            assert command[command.index("--out") + 1] == str(data / "packs" / (fam["tag"] + model).lower()), command
            assert command[command.index("--gguf") + 1] == str(expected[0]), command
            reached.append(True)
            raise Prepared()
        with contextlib.ExitStack() as guards:
            guards.enter_context(patch.object(setup, "run", side_effect=prepare))
            guards.enter_context(patch.object(setup, "download", side_effect=forbidden))
            guards.enter_context(patch.object(setup, "engine_step",
                side_effect=lambda a, gpu, hip, amd, tk, choice: (root, root / "engine", {"version": "99.0.0"}, [], gpu, choice)))
            guards.enter_context(patch.object(setup, "engine_families", return_value=[setup.OWN_PATH_FAMILIES["qwen36"]["arch"]]))
            guards.enter_context(patch.object(subprocess, "Popen", side_effect=forbidden))
            guards.enter_context(patch.object(socket.socket, "connect", side_effect=forbidden))
            guards.enter_context(patch.object(socket, "create_connection", side_effect=forbidden))
            argv = ["--family", family, "--model", model, "--context", "8192", "--vision", vision,
                    "--models-dir", str(selected_models), "--data-dir", str(data), "--set-default-data-dir",
                    "--separate-model-artifacts", "--no-start", "--yes", *(["--move-data"] if move else [])]
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    setup.main(argv)
                except Prepared:
                    pass
            assert reached, name
        shutil.rmtree(root / "models", ignore_errors=True)
        shutil.rmtree(data / "models", ignore_errors=True)
'''.replace("@HARDWARE@", HARDWARE_SETUP))



    def test_darwin_control_forecast_filtered_arguments_and_destinations(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import contextlib, hashlib, io, json, os, socket, sys
from pathlib import Path
from unittest.mock import patch
from strata_cli.launch.catalog import Catalog, ModelRow
from strata_cli.launch.runner import Runner
from strata_cli.launch.settings import LaunchSettings
from strata_control import drafting, engine_component as ec, mac_fit
root = Path.cwd()
base = root.parent.parent / "darwin-control"
base.mkdir()
components = base / "components"
engine = components / "engine/99.0.0-macos-arm64-metal"
engine.mkdir(parents=True)
# A real local payload and manifest exercise native component selection and integrity without execution.
import shutil
shutil.copyfile(shutil.which("true"), engine / "strata")
(engine / "strata").chmod(0o700)
payload = (engine / "strata").read_bytes()
(engine / ec.MANIFEST).write_text(json.dumps({"schema_version": 1, "id": ec.COMPONENT_ID,
    "version": "99.0.0", "platform": "macos-arm64", "backend": "metal", "entrypoint": "strata",
    "files": [{"path": "strata", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}]}))
os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root),
    STRATA_COMPONENTS_DIR=str(components), STRATA_ENGINE_BACKEND="metal")
import setup
row = ModelRow(family="qwen", family_title="Qwen", model="Q2_0", id="q2_0", about="",
    download_gb=setup.MODELS["Q2_0"]["download_gb"], need_vram_gb=0, need_ram_gb=1,
    spill_gb=0, verdict="fits", words="fits", experimental=False, images=False, installed=False)
class Selected(Exception):
    pass
for case, explicit, split in (("managed", False, True), ("explicit", True, True), ("native", False, False)):
    data, models, override = (base / case / name for name in ("data", "GGUF's folder", "explicit"))
    settings = base / case / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}")
    os.environ.update(STRATA_SETTINGS_FILE=str(settings), STRATA_WORKSPACE_CONTEXT=json.dumps({
        "state": str(root.parent.parent), "data_directory": str(data),
        "models_directory": str(models) if split else None}))
    cat = Catalog(src=root, root=root, hardware={"mac": True, "ram_gb": 256, "gpus": []})
    cat.rows = lambda: [row]
    s = LaunchSettings(family="qwen", model="Q2_0", context=8192, vision="off", drafting="off", mtp="off",
        data_dir=str(override) if explicit else None, tune="skip")
    runner = Runner(s, catalog=cat)
    expected_data = override if explicit else data
    expected_models = models if split else expected_data / "models"
    selected = []
    def download(url, destination, *args, **kwargs):
        selected.append(Path(destination))
        raise Selected()
    def forbidden(*args, **kwargs):
        raise AssertionError("Darwin directory selection acquired, built or connected")
    with contextlib.ExitStack() as guards:
        guards.enter_context(patch.object(sys, "platform", "darwin"))
        guards.enter_context(patch.object(ec, "host_platform", return_value="macos-arm64"))
        guards.enter_context(patch.object(drafting, "detect_hardware", return_value=("metal", [])))
        guards.enter_context(patch.object(mac_fit, "mac_info", return_value={
            "chip": "Test Apple Silicon", "ram_gb": 256, "macos": "27.0", "rosetta_python": False}))
        guards.enter_context(patch.object(mac_fit, "mac_problems", return_value=[]))
        guards.enter_context(patch.object(setup, "download", side_effect=download))
        guards.enter_context(patch.object(setup, "run", side_effect=forbidden))
        guards.enter_context(patch.object(socket.socket, "connect", side_effect=forbidden))
        guards.enter_context(patch.object(socket, "create_connection", side_effect=forbidden))
        directories = cat.launch_directories(s.family, s.model, data_dir=s.data_dir)
        assert directories.data_dir == expected_data and directories.models_dir == expected_models
        assert not expected_data.exists() and not expected_models.exists()
        plan = runner.download_plan()
        assert plan["gb"] > 0 and not expected_data.exists() and not expected_models.exists()
        argv = runner.setup_args()
        assert argv[argv.index("--data-dir") + 1] == str(expected_data), argv
        assert ("--models-dir" in argv) == split, argv
        assert ("--separate-model-artifacts" in argv) == split, argv
        assert "--move-data" not in argv
        if split:
            assert argv[argv.index("--models-dir") + 1] == str(expected_models), argv
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                setup.main(argv)
            except Selected:
                pass
            else:
                raise AssertionError("native Control setup did not reach the selected download")
        expected = expected_models / "Q2_0" / setup.model_file(setup.FAMILIES["qwen"], "Q2_0", 1)
        assert selected == [expected], (selected, expected)
        if split:
            assert not (expected_data / "models/Q2_0").exists()

# Native setup and progress must consume the same complete source, not just the requested root.
def seed_shards(folder, family, model, finished):
    folder.mkdir(parents=True, exist_ok=True)
    fam = setup.FAMILIES[family]
    paths = [folder / setup.model_file(fam, model, i)
             for i in range(1, setup.model_shards(fam, model) + 1)]
    for i, path in enumerate(paths, 1):
        with path.open("wb") as stream:
            stream.truncate(1_000_000)
        if i in finished:
            setup.mark(path)
    return paths

for family, model in (("qwen", "Q2_0"), ("unsloth", "UD-Q4_K_XL"), ("gyro", "Gyro-S")):
    fam = setup.FAMILIES[family]
    count = setup.model_shards(fam, model)
    complete = tuple(range(1, count + 1))
    for case in ("retained", "requested-partial", "requested-complete", "remembered", "incomplete", "personal"):
        home = base / (family + "-" + case)
        data, models, personal = (home / name for name in ("data", "requested", "personal"))
        retained = home / "old-data" if case == "remembered" else data
        source = retained / "models" / (fam["tag"] + model)
        requested = models / (fam["tag"] + model)
        source_finished = (count,) if case == "incomplete" and count > 1 else () if case == "incomplete" else complete
        source_files = seed_shards(source, family, model, source_finished)
        requested_files = [requested / path.name for path in source_files]
        if case == "requested-complete":
            seed_shards(requested, family, model, complete)
        elif case in ("requested-partial", "incomplete"):
            seed_shards(requested, family, model, tuple(range(1, count)))
        own = seed_shards(personal, family, model, ()) if case == "personal" else None
        settings = home / "settings.json"
        settings.write_text(json.dumps({"data_dir": str(retained)}))
        os.environ.update(STRATA_SETTINGS_FILE=str(settings), STRATA_WORKSPACE_CONTEXT=json.dumps({
            "state": str(root.parent.parent), "data_directory": str(data), "models_directory": str(models)}))
        cat = Catalog(src=root, root=root, hardware={"mac": True, "ram_gb": 256, "gpus": []})
        row = ModelRow(family=family, family_title=fam["title"], model=model, id=cat.tag_of(family, model), about="",
            download_gb=setup.MODELS[model]["download_gb"], need_vram_gb=0, need_ram_gb=1,
            spill_gb=0, verdict="fits", words="fits", experimental=False, images=False, installed=False)
        cat.rows = lambda: [row]
        s = LaunchSettings(family=family, model=model, context=8192, vision="off", drafting="off", mtp="off",
            data_dir=str(data), model_path=str(personal) if own else None, tune="skip")
        runner = Runner(s, catalog=cat)
        expected = own if own else requested_files if case in ("requested-complete", "incomplete") else source_files
        downloads, checked = [], []
        def download_selected(url, destination, *args, **kwargs):
            downloads.append(Path(destination))
            raise Selected()
        def check_selected(files):
            checked.extend(files)
            raise Selected()
        with contextlib.ExitStack() as guards:
            guards.enter_context(patch.object(sys, "platform", "darwin"))
            guards.enter_context(patch.object(ec, "host_platform", return_value="macos-arm64"))
            guards.enter_context(patch.object(drafting, "detect_hardware", return_value=("metal", [])))
            guards.enter_context(patch.object(mac_fit, "mac_info", return_value={
                "chip": "Test Apple Silicon", "ram_gb": 256, "macos": "27.0", "rosetta_python": False}))
            guards.enter_context(patch.object(mac_fit, "mac_problems", return_value=[]))
            guards.enter_context(patch.object(setup, "download", side_effect=download_selected))
            guards.enter_context(patch.object(setup, "check_shards", side_effect=check_selected))
            guards.enter_context(patch.object(setup, "run", side_effect=forbidden))
            guards.enter_context(patch.object(socket.socket, "connect", side_effect=forbidden))
            guards.enter_context(patch.object(socket, "create_connection", side_effect=forbidden))
            before = settings.read_bytes()
            plan = runner.download_plan()
            job = runner.progress_job()
            if own:
                assert Path(job["folder"]) == personal, (family, case, job)
            else:
                assert [Path(item["path"]) for item in job["files"] if item.get("role", "model") == "model"] == expected, (family, case, job)
            assert settings.read_bytes() == before
            assert (plan["gb"] > 0) == (case == "incomplete"), (family, case, plan)
            argv = runner.setup_args()
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    setup.main(argv)
                except Selected:
                    pass
                else:
                    raise AssertionError("native setup skipped the selected file boundary")
            if case == "incomplete":
                assert downloads == [requested_files[-1]] and not checked, (family, case, downloads, checked)
            else:
                assert not downloads and checked == expected, (family, case, downloads, checked, expected)
        assert all(path.exists() and path.stat().st_size == 1_000_000 for path in source_files)
        if case in ("retained", "remembered"):
            assert not requested.exists(), (family, case)

''')


    @unittest.skipUnless(sys.platform == "linux", "Native Linux source acquisition")
    def test_retired_configs_do_not_select_managed_install_runtime(self):
        root = self.make_acquisition_workspace()
        retired = root / "strata-deepseek-v4.1-flash-ist-das-2.00bpw.json"
        retained = json.dumps({"arch": "deepseek41", "exe": "engine-dsv41/strata-dsv41", "args": []}).encode()
        retired.write_bytes(retained)
        data, models = self.base / "new data", self.base / "new GGUF"
        result = subprocess.run(self.command(self.old) + ["run", "source", "--yes", "--no-browser",
            "--context", "8192", "--vision", "no", "--experimental-speed-projection", "off"],
            env=dict(self.env, TEST_DATA_DIRECTORY=str(data), TEST_MODELS_DIRECTORY=str(models)),
            capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        selected = json.loads((root / "destinations.json").read_text())
        self.assertEqual(Path(selected["data"]), data)
        self.assertTrue(Path(selected["models"]).is_relative_to(models))
        self.assertEqual(retired.read_bytes(), retained)
        self.assertFalse((root.parent / ".git/strata-runtime-revision").exists())



    def test_managed_download_progress_requires_native_completion(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import types
from pathlib import Path
from strata_cli.launch.catalog import Catalog
root = Path.cwd()
cat = Catalog(src=root, root=root, hardware={})
mod = cat.strata.setup_module()
base = root.parent.parent / "native-completion"
for family, model in (("qwen", "Q2_0"), ("unsloth", "UD-Q4_K_XL"), ("gyro", "Gyro-S")):
    count = mod.model_shards(mod.FAMILIES[family], model)
    cases = ("unmarked", "marked", "residual-part", "active-part", "missing") + (("mixed",) if count > 1 else ())
    for case in cases:
        models = base / family / case
        files = cat.mcp.expected_files(mod, family, model, models, False)
        for i, item in enumerate(files):
            path = Path(item["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as stream:
                stream.truncate(100_000_000)  # Keep the native 0.05 GB display gate observable.
            if case in ("marked", "residual-part", "missing") or (case == "mixed" and i == 0):
                mod.mark(path)
        first = Path(files[0]["path"])
        if case in ("residual-part", "active-part"):
            first.with_name(first.name + ".part").write_bytes(b"partial")
        if case == "missing":
            first.unlink()  # A finish mark without its final file is not complete.
        job = {"files": files, "total_gb": count * 0.1}
        shown = cat.mcp.combined_progress(cat.mcp.install_progress(["=== Step 5: downloading model ==="]), job, setup_module=mod)
        part = next(p for p in shown["parts"] if p["kind"] == "model")
        native = sum(mod.download_complete(Path(item["path"])) for item in files)
        assert part["files_done"] == native, (family, case, shown)
        if case in ("marked", "residual-part"):
            assert shown["download"]["percent"] == 100 and part["state"] == "done", (family, case, shown)
        else:
            assert shown["download"]["percent"] < 99.5 and part["state"] != "done", (family, case, shown)
        if case == "active-part":
            assert part["state"] == "downloading", (family, case, shown)
personal = base / "personal.gguf"
with personal.open("wb") as stream:
    stream.truncate(100_000_000)
for helper, accept in ((mod, True), (None, False), (types.SimpleNamespace(), False)):
    job = {"files": [{"path": str(personal), "bytes": 100_000_000, "role": "model", "accept_unmarked": accept}], "total_gb": 0.1}
    shown = cat.mcp.combined_progress({"step": "5/7: downloading"}, job, setup_module=helper)
    assert shown["download"]["percent"] == 100 and shown["parts"][0]["state"] == "done", shown
''')

    def test_launch_progress_does_not_latch_incomplete_files_as_already(self):
        root = self.prepare(self.old)
        self.run_source_script(root, '''
import json, os, socket, tempfile
from pathlib import Path
from strata_cli.launch.catalog import Catalog, ModelRow
from strata_cli.launch.settings import LaunchSettings
from strata_cli.launch.runner import Runner
root = Path.cwd()
base = root.parent.parent / "completion-latch"
base.mkdir()
for complete in (False, True):
    home = base / ("complete" if complete else "incomplete")
    models, data = home / "models", home / "data"
    settings = home / "settings.json"
    home.mkdir()
    settings.write_text("{}")
    os.environ.update(STRATA_CONTROL_INSTALL="1", STRATA_INSTALL_DIR=str(root), STRATA_SETTINGS_FILE=str(settings),
        STRATA_WORKSPACE_CONTEXT=json.dumps({"state": str(root.parent.parent), "data_directory": str(data), "models_directory": str(models)}))
    cat = Catalog(src=root, root=root, hardware={})
    mod = cat.strata.setup_module()
    family, model = "qwen", "Q2_0"
    tag = cat.tag_of(family, model)
    files = [models / model / mod.model_file(mod.FAMILIES[family], model, i)
             for i in range(1, mod.model_shards(mod.FAMILIES[family], model) + 1)]
    files[0].parent.mkdir(parents=True)
    for path in files:
        with path.open("wb") as stream:
            stream.truncate(100_000_000)
        if complete:
            mod.mark(path)
    row = ModelRow(family=family, family_title="Qwen", model=model, id=tag, about="", download_gb=len(files) * 0.1,
        need_vram_gb=0, need_ram_gb=1, spill_gb=0, verdict="fits", words="fits", experimental=False, images=False, installed=False)
    cat.rows = lambda: [row]
    config = root / ("strata-" + tag + ".json")
    producer = home / "producer.py"
    producer.write_text(r"""
import json, socket, sys
from pathlib import Path
import setup as mod
parsed = []
assert mod.main(sys.argv[3:], after_parse=lambda a, argv: (parsed.append(a), 0)[1]) == 0
a = parsed[0]
data, retained = mod.data_folder_for(a)
layout = mod.model_download_layout(a.family, a.model, Path(a.models_dir), data_dir=data, elsewhere=retained)
with socket.socket(socket.AF_UNIX) as gate:
    gate.connect(sys.argv[2])
    mod.step(5, "downloading model")
    sys.stdout.flush()
    assert gate.recv(1) == b"g"  # No completion or config publication before the first visible event.
for path in layout[3]:
    mod.mark(path)
mod.step(6, "writing config")
pack = data / "packs" / "fixture"
pack.mkdir(parents=True)
Path(sys.argv[1]).write_text(json.dumps({"exe": sys.executable,
    "args": ["--native", str(layout[3][0]), "--pack", str(pack), "--max-context", "8192", "--kv", "fp16"]}))
""")
    events, peer, observed = [], {}, []
    def emit(event):
        events.append(event)
        if str(event.data.get("step") or "").startswith("5/") and event.pct is not None and not observed:
            observed.append(event)
            peer["socket"].sendall(b"g")
    runner = Runner(LaunchSettings(family=family, model=model, context=8192, vision="off", mtp="off", drafting="off"), catalog=cat, emit=emit)
    spawn, read_lines = runner._spawn, runner._read_lines
    gate_directory = Path(tempfile.mkdtemp(prefix="strata-progress-", dir="/tmp")).resolve()
    gate_path = gate_directory / "gate.sock"
    def spawn_fixture(argv, **kwargs):
        return spawn([argv[0], str(producer), str(config), str(gate_path), *argv[2:]], **kwargs)
    def read_fixture(process):
        with listener.accept()[0] as gate:
            gate.settimeout(30)
            peer["socket"] = gate
            yield from read_lines(process)
    runner._spawn, runner._read_lines = spawn_fixture, read_fixture
    try:
        with socket.socket(socket.AF_UNIX) as listener:
            listener.settimeout(15)
            listener.bind(str(gate_path))
            listener.listen(1)
            assert runner.ensure_model() == config
    finally:
        runner._stop_children()
        gate_path.unlink(missing_ok=True)
        gate_directory.rmdir()
    assert observed
    first = observed[0]
    if complete:
        assert first.pct == 100 and "already on this computer" in first.text, first
    else:
        assert first.pct < 99.5 and "already on this computer" not in first.text, first
    config.unlink()
''')

unittest.main()
