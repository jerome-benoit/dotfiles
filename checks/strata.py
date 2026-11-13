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
UPSTREAM = str(Path(sys.argv.pop(1)).resolve())
LAUNCHERS = json.loads(Path(sys.argv.pop(1)).read_text())
SOURCE_PATCH = str(Path(sys.argv.pop(1)).resolve())
RUNNER = """
import importlib.util, pathlib, subprocess, sys
spec = importlib.util.spec_from_file_location('workspace', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
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
              source_patch=__import__("os").environ.get("TEST_SOURCE_PATCH", @SOURCE_PATCH@) or None))
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


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "remote"
        self.repo.mkdir()
        self.env = dict(os.environ, HOME=str(self.base / "home"),
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
        (self.repo / ".gitignore").write_text(".venv/\nengine/\nbuild/\nstrata-*.json\n")
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
        shutil.copyfile(Path(UPSTREAM) / "setup.sh", self.repo / "setup.sh")
        for directory, _, _ in os.walk(self.repo / "strata_control"):
            Path(directory).chmod(0o700)
        (self.repo / "tools").mkdir()
        shutil.copyfile(Path(UPSTREAM) / "tools/nvfp4_local_pack.py", self.repo / "tools/nvfp4_local_pack.py")
        shutil.copyfile(Path(UPSTREAM) / "tools/iq_pack.py", self.repo / "tools/iq_pack.py")
        shutil.copyfile(Path(UPSTREAM) / "tools/strata_mcp.py", self.repo / "tools/strata_mcp.py")
        shutil.copyfile(Path(UPSTREAM) / "tools/gguf_reader.py", self.repo / "tools/gguf_reader.py")
        (self.repo / "sycl").mkdir()
        shutil.copyfile(Path(UPSTREAM) / "sycl/setup_intel.py", self.repo / "sycl/setup_intel.py")
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
                self.assertFalse((root / ".git/strata-runtime-revision").exists())
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
        result = subprocess.run(
            [sys.executable, "-c", "import sys\nsys.path.append(" + repr(UPSTREAM) + ")\n" + script],
            env=self.env, cwd=root, capture_output=True, text=True, timeout=30,
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

    def test_source_patch_revision_idempotence_edits_and_offline_unpatched_rollback(self):
        root = self.prepare(self.old)
        ledger = root / ".git/strata-source.patch"
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())
        stamp = (root / "setup.py").stat().st_mtime_ns
        marker = root / ".git/strata-runtime-revision"
        marker.write_text(self.old)
        self.prepare(self.old)
        self.assertEqual((root / "setup.py").stat().st_mtime_ns, stamp)
        self.assertEqual(marker.read_text(), self.old)
        with (root / "setup.py").open("a") as source:
            source.write("\n# user-owned note outside managed hunks\n")
        self.prepare(self.new)
        self.assertTrue((root / "setup.py").read_text().endswith("# user-owned note outside managed hunks\n"))
        self.assertEqual(subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), self.new)
        self.repo.rename(self.base / "offline")
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
        ledger = root / ".git/strata-source.patch"
        subprocess.run(["git", "-C", str(root), "apply", "--reverse", "-"],
                       input=ledger.read_text(), text=True, env=self.env, check=True)
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

    def test_source_patch_checkout_failure_restores_old_overlay_and_keeps_user_changes(self):
        root = self.prepare(self.old)
        ledger = root / ".git/strata-source.patch"
        (root / "code.py").write_text("user-owned conflicting source\n")
        result = subprocess.run(self.command(self.new), env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((root / "code.py").read_text(), "user-owned conflicting source\n")
        self.assertEqual(ledger.read_text(), Path(SOURCE_PATCH).read_text())
        self.assertEqual(subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(), self.old)
        subprocess.run(["git", "-C", str(root), "apply", "--reverse", "--check", "-"],
                       input=ledger.read_text(), text=True, env=self.env, check=True)

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
        self.repo.rename(self.base / "remote-offline")
        self.assertEqual(self.prepare(self.new), root)
        self.assertEqual((root / "code.py").read_text(), "new source\n")
        self.assertEqual(self.prepare(self.old), root)
        self.assertEqual((root / "removed.py").read_text(), "obsolete source\n")
        for name, text in expected.items():
            self.assertEqual((root / name).read_text(), text, name)

    def test_setup_resumes_interrupted_initialization_before_inspecting_parser(self):
        setup = self.repo / "setup.sh"
        setup.write_text(f'#!{shutil.which("sh")}\nexec "{sys.executable}" "$(dirname "$0")/setup.py" "$@"\n')
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
                                    str(self.repo), revision], env=self.env, check=True)
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
        # Keep the actual setup parser and lifecycle; replace only external acquisition boundaries.
        (root / "requirements.txt").write_text("pip\n")
        script = root / "setup.sh"
        script.write_text(f'''#!/bin/sh
cd "$(dirname "$0")" || exit 8
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
                self.assertFalse((root / ".git/strata-runtime-revision").exists())
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
        entry = root / "strata.py"
        source = entry.read_text()
        future = "from __future__ import annotations\n"
        entry.write_text(source.replace(future, future + loader, 1) if future in source else loader + source)

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

    def make_terminal(self, root, before=""):
        if not (root / "serve").exists():
            shutil.copytree(Path(UPSTREAM) / "serve", root / "serve", copy_function=shutil.copyfile)
        if not (root / "tools/gguf_reader.py").exists():
            shutil.copyfile(Path(UPSTREAM) / "tools/gguf_reader.py", root / "tools/gguf_reader.py")
        (root / "strata.py").write_text(
            "import sys\nfrom pathlib import Path\nfrom strata_cli import cli\n"
            + before + "\nraise SystemExit(cli.main())\n")
        if not (root / ".venv/bin/python").exists():
            (root / ".venv/bin").mkdir(parents=True, exist_ok=True)
            (root / ".venv/bin/python").symlink_to(sys.executable)
        script = root / "setup.sh"
        if script.read_text() == (Path(UPSTREAM) / "setup.sh").read_text():
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
        subprocess.run(["git", "-C", str(root), "apply", "--reverse", SOURCE_PATCH],
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
        marker = root / ".git/strata-runtime-revision"
        marker.write_text(self.old + "\n")
        (root / ".git/strata-engine-rollback.json").write_text("{}")
        command = self.command(self.old) + ["run", "install", "--update", "--build"]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text(), self.old + "\n")
        self.assertEqual((root / "update-attempts").read_text(), "1")
        self.assertFalse((root / ".git/strata-engine-rollback.json").exists())
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
        self.assertFalse((root / ".git/strata-runtime-revision").exists())

    def test_cold_external_install_help_uses_terminal_parser_without_bootstrap(self):
        root = self.prepare(self.old)
        external = self.base / "cold external install"
        external.mkdir()
        shutil.copyfile(Path(UPSTREAM) / "setup.py", external / "setup.py")
        shell = (Path(UPSTREAM) / "setup.sh").read_text()
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
        wrapper.write_text((Path(UPSTREAM) / "setup.sh").read_text())
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
        (root / ".git/strata-runtime-revision").write_text(self.old + "\n")
        (root / ".git/strata-engine-rollback.json").write_text('{"caller":"preserved"}')
        (root / ".venv/.strata-pip.json").write_text('["managed-only"]')
        paths = [root / "strata-fixture.json", root / ".git/strata-runtime-revision",
                 root / ".git/strata-engine-rollback.json", root / ".venv/.strata-pip.json",
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
        self.assertEqual(Path(stdout.strip()), (self.state / "source").resolve())
        self.assert_workspace_unlocked()

    def test_install_mutation_child_keeps_lock_after_helper_dies(self):
        root = self.prepare(self.old)
        self.make_terminal(root)
        self.make_runtime_model(root)
        gate = self.base / "install-gate.py"
        gate.write_text(GATE)
        (root / "setup.sh").write_text(f'exec "{sys.executable}" "{gate}"\n')
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
    catalog.mcp = SimpleNamespace(install_progress=lambda lines: {{}}, combined_progress=lambda progress, job: progress)
    runner = Runner(LaunchSettings(family="qwen", model="IQ3_S"), catalog=catalog)
    runner.check_own_files = lambda: None
    runner.resolved_vision = lambda: None
    runner.installed_state = lambda: (None, None)
    runner.intel_chosen = lambda: False
    runner.beside_refused = lambda: None
    runner.multi_file = lambda: True
    runner.setup_args = lambda: ["--setup"]
    runner.progress_job = lambda: {{}}
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
        for door in ("launch", "monitor"):
            with self.subTest(door=door):
                self.state = self.base / door
                root = self.prepare(self.old)
                self.make_terminal(root, f'''
import contextlib, fcntl, json, os, socket, threading, types
from strata_control import acquisition, dsv41_paths, engine_update, profiles, runtime, updater
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
             "RunScreen", "SaveScreen", "SpeedScreen", "StartScreen", "TuningScreen", "flow_for"):
    setattr(screens, name, object)
widgets = sys.modules["strata_cli.launch.widgets"]
widgets.CSS, widgets.Glyphs, widgets.DARK, widgets.LIGHT = "", object, None, None
protocol = ("STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT")
state = Path({str(self.state)!r})
config = Path({str(root / "launch-model.json")!r})
old = Path({str(root / "engine-dsv41/1.0-linux-x86_64-cuda/strata-dsv41")!r})
new = old.parent.parent / "2.0-linux-x86_64-cuda" / old.name
config.write_text(json.dumps({{"exe": str(old), "args": ["--parallel", "1"]}}))
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
        assert self.workspace_state == str(state)
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
                    assert dsv41_paths.repoint_all([config], new) == 1
                    raise updater.UpdateError("fixture update failure after mutation")
            updater.run_update = update
            runtime._repair_config_paths = lambda *args: (None, None)
            runtime._repair_dsv41_paths = lambda *args: None
            runtime._check_start_candidate = lambda *args: ({{}}, [])
            runtime._engine_preflight = lambda *args: None
            runtime._paths = lambda *args: (None, None, config.parent / "runtime.log")
            profiles._lock = lambda *args: contextlib.nullcontext()
            runtime.procs.end_leftovers = lambda **kwargs: None
            runtime._await_start = lambda *args: {{}}
            children = []
            runtime._read_state = lambda *args: {{}} if children else None
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
                with (self.state / ".source.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    peer.sendall(b"b")
                    self.assertEqual(peer.recv(1), b"b")
                    self.assert_observers_answer(self.old)
                peer.sendall(b"u")
                self.assertEqual(peer.recv(1), b"w")
                self.assert_workspace_locked()
                contender = subprocess.Popen(self.command(self.old), env=self.env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                def cleanup_contender(process=contender):
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=10)
                self.addCleanup(cleanup_contender)
                self.assertRaises(subprocess.TimeoutExpired, contender.wait, timeout=0.2)
                self.assert_observers_answer(self.old)
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
        original = root / "sycl/setup_intel.py"
        original.rename(root / "sycl/intel_real.py")
        original.write_text(f'''
import importlib.util, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
expected = os.stat(Path(__file__).resolve().parents[2] / ".source.lock")
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
    runtime._repair_dsv41_paths = lambda *args: None
    runtime._check_start_candidate = lambda *args: ({{}}, [])
    runtime._engine_preflight = lambda *args: None
    runtime._paths = lambda *args: (None, None, Path({str(self.base / "runtime.log")!r}))
    profiles._lock = lambda *args: contextlib.nullcontext()
    runtime.procs.end_leftovers = lambda **kwargs: None
    children = []
    runtime._read_state = lambda *args: {{}} if children else None
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
    with original(*args, **kwargs):
        yield
module.source_publication_lock = publishing
module.prepare_workspace(sys.argv[2], sys.argv[3], remote=sys.argv[4], source_patch=sys.argv[5])
print("published", flush=True)
'''
                        writer = subprocess.Popen([sys.executable, "-c", writer_script, WORKSPACE,
                            str(self.state), revision, str(self.repo), SOURCE_PATCH],
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
        marker = root / ".git/strata-runtime-revision"
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
        (root / ".git/strata-runtime-revision").write_text(self.old + "\n")
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
                self.assertEqual((root / ".git/strata-runtime-revision").read_text().strip(), self.new)
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
                (root / ".git/strata-runtime-revision").write_text(self.old)
                config = (root / "strata-fixture.json").read_bytes()
                result = subprocess.run(self.command(self.new) + ["run", "source", flag], env=self.env,
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
        (root / ".git/strata-runtime-revision").write_text(self.new)
        config = root / "strata-fixture.json"
        values = json.loads(config.read_text())
        values.update(backend="hip", open_browser=False)
        config.write_text(json.dumps(values))
        self.service_script(root, GATE)
        script = root / "setup.sh"
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
                approval = root / ".git/strata-engine-rollback.json"
                approved = approval.read_bytes()
                marker = root / ".git/strata-runtime-revision"
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
        self.assertFalse((root / ".git/strata-engine-rollback.json").exists())
        self.assertEqual((root / "update-attempts").read_text(), "1")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_engine_rollback_survives_normal_launch_and_explicit_update(self):
        state = self.state
        for available, certificate in ((True, "current"), (False, "pending"), (True, "missing")):
            with self.subTest(replacement_available=available, certificate=certificate):
                self.state = state / certificate
                root = self.make_rollback_workspace()
                marker = root / ".git/strata-runtime-revision"
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
                self.assertFalse((root / ".git/strata-engine-rollback.json").exists())
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
                self.assertFalse((root / ".git/strata-runtime-revision").exists())
                self.assertTrue((root / ".git/strata-engine-rollback.json").exists())
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
                self.assertFalse((root / ".git/strata-engine-rollback.json").exists())
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
                    script = root / "setup.sh"
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
                self.assertFalse((root / ".git/strata-engine-rollback.json").exists())

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
        self.assertEqual((root / ".git/strata-runtime-revision").read_text().strip(), self.new)
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
        self.assertFalse((root / ".git/strata-runtime-revision").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_local_rollback_preserves_same_revision_source_checks(self):
        root = self.make_rollback_workspace()
        shutil.copyfile(Path(UPSTREAM) / "CMakeLists.txt", root / "CMakeLists.txt")
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
        self.assertFalse((root / ".git/strata-engine-rollback.json").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI; Darwin dispatches to Metal")
    def test_zero_exit_partial_update_retries_same_revision_and_reuses_valid_runtime(self):
        root = self.make_updater_workspace()
        marker = root / ".git/strata-runtime-revision"
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

    @unittest.skipUnless(sys.platform == "linux", "Native SYCL wrapper paths")
    def test_selected_sycl_uses_real_engine_and_effective_container_mount(self):
        root = self.make_updater_workspace()
        self.make_terminal(root)
        shutil.copytree(Path(UPSTREAM) / "sycl/serve", root / "sycl/serve", copy_function=shutil.copyfile)
        (root / "sycl/serve/strata-sycl.sh").chmod(0o700)
        self.run_source_script(root, '''
import json, os, shutil, subprocess, sys
from pathlib import Path
from sycl import setup_intel as intel
from strata_control import doctor
from strata_control.cfg_paths import engine_binary
root = Path.cwd()
mount = root.parent.parent / "custom mount"
mount.mkdir()
intel.MOUNT = mount
pack = mount / "pack"
pack.mkdir()
vector = mount / "vector.bin"
vector.write_bytes(b"vector")
exe = root / "custom-build/strata"
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
mounted_engine = mount / root.name / "custom-build/strata"
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
default_engine = root / "build-sycl-aot/strata"
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
relative = mount / root.name / "relative-pack"
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
cfg["env"]["STRATA_SYCL_BIN"] = "/work/" + root.name + "/custom-build/strata"
path.write_text(json.dumps(cfg))
assert engine_binary(cfg["exe"], cfg) == str(mounted_engine)
assert next(c["path"] for c in doctor.inspect(path)["components"] if c["name"] == "engine") == str(mounted_engine)
subprocess.run([shutil.which("bash"), cfg["exe"], "--pack", "/work/pack"], cwd=engine_cwd,
               env={**os.environ, **cfg["env"], "PATH": str(recorders) + os.pathsep + os.environ["PATH"],
                    "DOCKER_RECORD": str(record)}, check=True)
command = json.loads(record.read_text())
volume = next(command[i + 1] for i, value in enumerate(command[:-1]) if value == "-v" and command[i + 1].endswith(":/work"))
assert (engine_cwd / volume[:-6]).resolve() == mount
assert command[-1] == "cd /work/" + root.name + " && exec " + cfg["env"]["STRATA_SYCL_BIN"] + " --pack /work/pack"
cfg["env"] = saved_env
cfg["args"][cfg["args"].index("--pack") + 1] = "/work/pack"
path.write_text(json.dumps(cfg))
''')
        selected = self.base / "external-sycl.json"
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
        engine = self.base / "custom mount" / root.name / "custom-build/strata"
        (root / "custom-build/strata").write_bytes(b"engine=0.1.46\n")
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
        wrapper = root / "sycl/serve/strata-sycl.sh"
        launcher = wrapper.read_bytes()
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
        directory = Path(self.env["STRATA_COMPONENTS_DIR"]) / "engine" / f"{version}-linux-x86_64-cpu"
        directory.mkdir(parents=True, exist_ok=True)
        executable = directory / "strata"
        shutil.copyfile(shutil.which("true"), executable)
        executable.chmod(0o700)
        payload = executable.read_bytes()
        manifest = {
            "schema_version": 1, "id": "strata-engine", "version": version,
            "platform": "linux-x86_64", "backend": "cpu", "min_runtime": "0.1.0",
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

    @unittest.skipUnless(sys.platform == "linux", "Native Linux component fixture")
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
        marker = root / ".git/strata-runtime-revision"
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
                marker = root / ".git/strata-runtime-revision"
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
        marker = root / ".git/strata-runtime-revision"
        marker.write_text(self.new)
        receipt = root / ".git/strata-source-refresh-revision"
        receipt.write_text(self.new)
        setup = root / "setup.sh"
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
        marker = root / ".git/strata-runtime-revision"
        for requirement, diagnostic in (("strata-missing-runtime==1", "Python package missing"),
                                        ("pip==0", "requires ==0")):
            (root / "requirements.txt").write_text(requirement + "\n")
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(diagnostic, result.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((root / ".git/strata-source-refresh-revision").exists())

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
        result = subprocess.run(self.command(self.new) + ["run", "source", "--update", "--build"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("compiled engine does not match this source", result.stderr)
        self.assertFalse((root / ".git/strata-runtime-revision").exists())


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
        (root / "setup.sh").write_text(f'exec "{sys.executable}" "{gate}"\n')
        marker = root / ".git/strata-runtime-revision"
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
        setup = root / "setup.sh"
        setup.write_text(f'#!{shutil.which("sh")}\nexec "{probe}"\n')
        setup.chmod(0o700)
        (root / "strata.py").write_text(
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
        marker = root / ".git/strata-runtime-revision"
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
        marker = root / ".git/strata-runtime-revision"
        marker.write_text(self.new)
        gate = self.base / "updater.py"
        gate.write_text(GATE)
        setup = root / "setup.sh"
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
        marker = root / ".git/strata-runtime-revision"
        config = root / "strata-user.json"
        allow_success = self.base / "allow-success"
        setup = root / "setup.sh"
        setup.write_text(f'''#!{shutil.which("sh")}
cd "$(dirname "$0")" || exit 8
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
        for name in ("setup.sh", "requirements.txt", "requirements-monitor.txt", "CMakeLists.txt"):
            shutil.copyfile(Path(UPSTREAM) / name, self.repo / name)
        for directory, _, _ in os.walk(self.repo):
            Path(directory).chmod(0o700)
        self.service_script(self.repo,
            "import os,sys\nfrom pathlib import Path\n"
            "assert 'STRATA_RUNTIME_READY' not in os.environ\n"
            "assert Path(sys.executable).parent.parent == Path(__file__).resolve().parents[1] / '.venv'\n"
            + GATE)
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

    def run_terminal_pty(self, command, env):
        master, slave = pty.openpty()
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave)
        os.close(slave)
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
        shell = (Path(UPSTREAM) / "setup.sh").read_text()
        shell = shell.replace('cd "$(dirname "$0")" || exit 1',
                              'cd "$(dirname "$0")" || exit 1\nprintf x >> bootstrap-attempts')
        (root / "setup.sh").write_text(shell)
        (root / "requirements.txt").write_text("strata-missing-monitor-fixture==1.0\n")
        env = dict(self.env, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1", TERM="xterm")
        command = self.command(self.old) + ["run", "monitor", "--url", "http://127.0.0.1:1"]
        for attempt in (1, 2):
            code, output = self.run_terminal_pty(command, env)
            self.assertEqual(code, 1, output)
            self.assertIn("strata-missing-monitor-fixture", output)
            self.assertEqual((root / "bootstrap-attempts").read_text(), "x" * attempt)
            self.assertTrue(os.access(root / ".venv/bin/python", os.X_OK))
            self.assertFalse((root / ".git/strata-runtime-revision").exists())
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
        shell = root / "setup.sh"
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
                root = self.prepare(self.old) if warm else self.state / "source"
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
                    self.assertFalse((root / ".git/strata-source-refresh-revision").exists())
                    self.assertFalse((root / ".git/strata-runtime-revision").exists())

    def test_cold_metadata_and_plans_never_bootstrap(self):
        root = self.prepare(self.old)
        marker = root / ".git/strata-runtime-revision"
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

    def make_native_lifecycle_workspace(self):
        root = self.prepare(self.old)
        self.make_runtime_source(root)
        # Use upstream's actual environment creation and pip implementation, without external wheels.
        shell = (Path(UPSTREAM) / "setup.sh").read_text()
        shell = shell.replace('exec .venv/bin/python setup.py "$@"',
                              """exec .venv/bin/python -c 'import os,setup,sys; sys.exit(setup.bootstrap_runtime() if os.environ.get("STRATA_BOOTSTRAP_ONLY") == "1" else setup.main())' "$@" """)
        (root / "setup.sh").write_text(shell)
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
        (root / "strata.py").write_text('''
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
assert (ROOT / ".git/strata-runtime-revision").read_text().strip() == os.environ["EXPECTED_REVISION"]
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
        unrelated = dict(cfg, args=["--native", str(root / "unrelated-missing.gguf")])
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
    os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent), "revision": revision})
    workspace.prepare_launch_runtime(root, revision, lock.fileno())
    settings = LaunchSettings(family="qwen", model="Q2_0", name="selected-repair", vision="off",
        context=8192, gpus=[0], parallel=1, split_engine="off", drafting="off", mtp="off", tune="skip")
    catalog = Catalog(src=root, root=root, hardware={"gpus": [], "ram_gb": 64, "disk_free_gb": 1})
    runner = native.Runner(settings, catalog=catalog)
    ec.status = lambda *a, **kw: {"usable": True, "engine": {"version": "0.1.46", "backend": "cpu"}}
    native.desc_matches = lambda desc, settings: True
    runner.installed_state = lambda: (base, {})
    runner.intel_chosen = lambda: False
    runner.progress_job = lambda: {}
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
        assert (root / ".git/strata-source-refresh-revision").read_text().strip() == revision
        assert not (root / ".git/strata-runtime-revision").exists()
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
        receipt = root / ".git/strata-source-refresh-revision"
        certificate = root / ".git/strata-runtime-revision"
        for attempt in (1, 2):
            result = subprocess.run(command + ["valid"], env=self.env, cwd=root,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual((root / "native-acquisitions").read_text(), "x")
            self.assertEqual((root / "update-attempts").read_text(), "1")
            self.assertEqual(receipt.read_text().strip(), self.new)
            self.assertFalse(certificate.exists())
            self.assertEqual((root / "tuned").read_text(), "selected validated")
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
        marker = root / ".git/strata-runtime-revision"
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
        self.assertFalse((root / ".git/strata-runtime-revision").exists())
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
        self.assertEqual((root / ".git/strata-runtime-revision").read_text().strip(), self.new)
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
                    previous.write_text(Path(SOURCE_PATCH).read_text() + (
                        "diff --git a/code.py b/code.py\n--- a/code.py\n+++ b/code.py\n"
                        "@@ -1 +1 @@\n-old source\n+older overlay source\n"))
                    self.env["TEST_SOURCE_PATCH"] = str(previous)
                root = self.prepare(self.old)
                del self.env["TEST_SOURCE_PATCH"]
                note = root / "user-owned.txt"
                note.write_text("preserved across publication recovery\n")
                interrupted = subprocess.run([sys.executable, "-c", '''
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location("workspace", sys.argv[1])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
apply = helper.apply_source_patch
def interrupt(root, text, *, reverse=False):
    if not reverse:
        raise RuntimeError("injected interruption after journal publication")
    return apply(root, text, reverse=reverse)
helper.apply_source_patch = interrupt
helper.prepare_workspace(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
''', WORKSPACE, str(self.state), self.old, str(self.repo), SOURCE_PATCH],
                    env=self.env, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(interrupted.returncode, 0)
                self.assertIn("injected interruption after journal publication", interrupted.stderr)
                self.assertEqual((root / ".git/strata-source.patch").read_text(), Path(SOURCE_PATCH).read_text())
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
        self.assertEqual((root / ".git/strata-source.patch").read_text(), Path(SOURCE_PATCH).read_text())
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

    def test_new_pin_parser_is_loaded_before_new_native_command(self):
        root = self.prepare(self.old)
        cli = self.repo / "strata_cli/cli.py"
        anchor = '    sp = ap.add_subparsers(dest="command", required=True)'
        cli.write_text(cli.read_text().replace(anchor, anchor + '\n    sp.add_parser("new-native-command")'))
        revision = self.commit()
        (root / "strata.py").write_text(
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
    with (Path(__file__).resolve().parents[2] / ".source.lock").open("a") as lock:
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
        marker = root / ".git/strata-runtime-revision"
        marker.write_text(self.old + "\n")
        subprocess.run(["git", "-C", str(root), "fetch", "--quiet", "--depth=1", str(self.repo), self.new],
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
with module.workspace_lock(state):
    with socket.socket(socket.AF_UNIX) as peer:
        peer.connect(os.environ["SOURCE_GATE"])
        peer.sendall(b"w")
    module._prepare_workspace(state, revision, remote, patch)
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
                [sys.executable, "-c", writer_script, WORKSPACE, str(self.state), str(self.repo), self.new, SOURCE_PATCH],
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
        "state": str(root.parent), "data_directory": str(data), "models_directory": str(models)})
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
    guards.enter_context(patch.object(Runner, "speed_line", return_value=""))
    guards.enter_context(patch.object(C, "Catalog", return_value=cat))
    guards.enter_context(patch.object(cmd, "apply_defaults", side_effect=lambda s, c: (s, [])))
    for scenario in ("native", "data", "models", "both", "explicit", "retained"):
        home = base / scenario
        native, data, models = (home / name for name in ("native", "data", "gguf"))
        context = {"state": str(root.parent)}
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
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent),
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
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent), "models_directory": str(models)})
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
os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent),
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
        guards.enter_context(patch.object(Runner, "speed_line", return_value=""))
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
if "serve" in sys.orig_argv and any(arg.endswith("/strata.py") for arg in sys.orig_argv):
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
    with original(*args, **kwargs):
        yield
helper.source_publication_lock = publishing
helper.prepare_workspace(sys.argv[2], sys.argv[3], remote=sys.argv[4], source_patch=sys.argv[5])
print("published", flush=True)
'''
                    writer = subprocess.Popen([sys.executable, "-c", writer_code, WORKSPACE,
                        str(self.state), self.new, str(self.repo), SOURCE_PATCH], env=self.env,
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
    os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent),
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
    os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(root.parent),
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



unittest.main()
