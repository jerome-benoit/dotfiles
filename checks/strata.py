import fcntl
import importlib.util
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


WORKSPACE = str(Path(sys.argv.pop(1)).resolve())
UPSTREAM = str(Path(sys.argv.pop(1)).resolve())
LAUNCHERS = json.loads(Path(sys.argv.pop(1)).read_text())
SOURCE_PATCH = str(Path(sys.argv.pop(1)).resolve())
RUNNER = """
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('workspace', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if len(sys.argv) > 5 and sys.argv[5] == "run":
    module.REMOTE = sys.argv[4]
    module.run_workspace(sys.argv[2], sys.argv[3], sys.argv[6:] or ["--build", "--no-browser"],
                         data_directory=__import__("os").environ.get("TEST_DATA_DIRECTORY"),
                         models_directory=__import__("os").environ.get("TEST_MODELS_DIRECTORY"),
                         source_patch=__import__("os").environ.get("TEST_SOURCE_PATCH", @SOURCE_PATCH@) or None)
elif len(sys.argv) > 5:
    with module.workspace_lock(pathlib.Path(sys.argv[2]).parent) as (_, lock):
        module.refresh_runtime(pathlib.Path(sys.argv[2]), sys.argv[3], lock.fileno(), sys.argv[6:])
else:
    print(module.prepare_workspace(sys.argv[2], sys.argv[3], sys.argv[4],
          source_patch=__import__("os").environ.get("TEST_SOURCE_PATCH", @SOURCE_PATCH@) or None))
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
                        NIX_STORE_DIR=str(self.base / "nix-store"),
                        NIX_STATE_DIR=str(self.base / "nix-state"),
                        NIX_LOG_DIR=str(self.base / "nix-log"),
                        NIX_CONF_DIR=str(self.base / "nix-conf"),
                        NIX_REMOTE="local",
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
        for directory, _, _ in os.walk(self.repo / "strata_control"):
            Path(directory).chmod(0o700)
        (self.repo / "tools").mkdir()
        shutil.copyfile(Path(UPSTREAM) / "tools/nvfp4_local_pack.py", self.repo / "tools/nvfp4_local_pack.py")
        shutil.copyfile(Path(UPSTREAM) / "tools/iq_pack.py", self.repo / "tools/iq_pack.py")
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
                args = ["--models-dir", "/CLI's $(touch injected)", "--api-key=--setup"]
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
        script = root / "setup.sh"
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
                    self.command(self.old) + ["run", "--yes", "--no-browser", "--context", "8192",
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
        script = root / "setup.sh"
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
                result = subprocess.run(self.command(self.old) + ["run", *args], env=env,
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
        for name in ("gguf_reader.py", "image/qimage.py"):
            destination = root / "tools" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(UPSTREAM) / "tools" / name, destination)
        script = root / "setup.sh"
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
        args = ["run", "--yes", "--no-start", "--no-browser", "--context", "8192",
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
def run(command):
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
        # Preserve the tracked control package and patch targets across prepares.
        # Replacing them here would discard the managed source changes.
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

    def workspace_module(self):
        spec = importlib.util.spec_from_file_location("workspace_under_test", WORKSPACE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_one_name_reads_upstream_shapes_and_splits_the_two_programs(self):
        """The routing needs no hand-kept name list: upstream's Terminal is subcommand-shaped, its setup option-shaped."""
        module = self.workspace_module()
        doors = module.cli_doors(Path(UPSTREAM))
        self.assertTrue({"launch", "serve", "status", "monitor", "update", "models", "presets"}
                        <= set(doors["commands"]), doors["commands"])
        self.assertTrue(all(option.startswith("-") for option in doors["options"]), doors["options"])
        for argv, door in (([], "setup"),                                  # upstream's bare ./setup.sh
                           (["--yes", "--no-browser"], "setup"),
                           (["--family", "qwen", "--model", "IQ3_S", "--parallel", "4"], "setup"),
                           (["--update"], "setup"),                        # UPDATE.bat's door
                           (["--setup", "--help"], "setup"),
                           (["--help"], "setup"),                          # in a source checkout, setup owns --help
                           (["-h"], "setup"),
                           (["update"], "terminal"),                       # the Terminal's own updater
                           (["launch", "--plan", "--family", "qwen", "--parallel", "4"], "terminal"),
                           (["status"], "terminal"),
                           (["launch", "--stop"], "terminal"),
                           (["--version"], "terminal"),
                           (["--vers"], "terminal"),
                           (["--version", "filename.json"], "terminal"),
                           (["--version", "status"], "terminal")):
            with self.subTest(argv=argv):
                self.assertEqual(module.entry_point(Path(UPSTREAM), argv), door)

    def test_the_split_stops_when_upstream_makes_its_setup_ambiguous(self):
        module = self.workspace_module()
        original = (Path(UPSTREAM) / "setup.py").read_text()
        anchor = "    ap = argparse.ArgumentParser(description=__doc__"
        with tempfile.TemporaryDirectory() as where:
            root = Path(where)
            shutil.copytree(Path(UPSTREAM) / "strata_cli", root / "strata_cli", copy_function=shutil.copyfile)
            shutil.copytree(Path(UPSTREAM) / "strata_control", root / "strata_control",
                            copy_function=shutil.copyfile)
            for form in ('    ap.add_argument("model", nargs="?")', "    ap.add_subparsers(dest=\"command\")"):
                source = original.replace(anchor, f"{form}\n{anchor}", 1)
                self.assertNotEqual(source, original)
                (root / "setup.py").write_text(source)
                with self.subTest(form=form):
                    with self.assertRaises(RuntimeError) as error:
                        module.cli_doors(root)
                    self.assertIn("positional", str(error.exception))

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

    def assert_mutator_child_keeps_lock(self, command, *, intermediate=None):
        process, child_pid, peer = self.gated_process(command)
        self.assertNotEqual(child_pid, process.pid)
        self.assert_workspace_locked()
        observer = subprocess.Popen(self.command(self.old), env=self.env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: observer.poll() is None and observer.kill())
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

    def test_launch_monitor_releases_lock_before_monitor_loop(self):
        root = self.prepare(self.old)
        self.make_terminal(root, f'''
import types
# Replace optional UI rendering only. Import and run upstream's real launch monitor boundary.
sys.modules["textual"] = types.ModuleType("textual")
for name in ("textual.app", "textual.binding", "strata_cli.launch.screens",
             "strata_cli.launch.widgets", "strata_cli.launch.monitor_ext"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["textual.app"].App = object
sys.modules["textual.binding"].Binding = lambda *args, **kwargs: None
screens = sys.modules["strata_cli.launch.screens"]
for name in ("AccessScreen", "AdvancedScreen", "CardsScreen", "ConfirmScreen", "ContextScreen",
             "DraftingScreen", "FolderScreen", "ModelScreen", "ParallelScreen", "PicturesScreen",
             "RunScreen", "SaveScreen", "SpeedScreen", "StartScreen", "TuningScreen", "flow_for"):
    setattr(screens, name, object)
widgets = sys.modules["strata_cli.launch.widgets"]
widgets.CSS, widgets.Glyphs = "", object
class Monitor:
    stop_requested = False
    def __init__(self, *args, **kwargs):
        pass
    def run(self):
        exec({GATE!r})
sys.modules["strata_cli.launch.monitor_ext"].LaunchMonitor = Monitor
original_run = cli._run
def run(a):
    if a.command != "launch":
        return original_run(a)
    from strata_cli.launch import app
    return app.run_monitor({{"url": "http://127.0.0.1:1", "port": 1}})
cli._run = run
''')
        process, pid, peer = self.gated_process(self.command(self.old) + ["run", "launch"])
        self.assertEqual(pid, process.pid)
        self.assert_workspace_unlocked()
        self.assert_observers_answer(self.old)
        peer.sendall(b"q")
        process.wait(timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr.read())

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
if "--update" in sys.argv:
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
        script = root / "setup.sh"
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
                result = subprocess.run(self.command(self.old) + ["run", *args],
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
        script = root / "setup.sh"
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
                result = subprocess.run(self.command(self.old) + ["run", *args], env=env,
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
        (root / "serve").mkdir()
        (root / "serve/server.py").write_text(GATE)
        script = root / "setup.sh"
        script.write_text(script.read_text().replace(
            f'exec "{sys.executable}"', f'exec "{root / ".venv/bin/python"}"',
        ))
        return root

    def start_rollback_workspace(self, root, *args):
        process, pid, peer = self.gated_process(
            self.command(self.new) + ["run", "--no-browser", *args],
        )
        self.assertEqual(pid, process.pid)
        self.assert_workspace_locked()
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
                script = root / "setup.sh"
                script.write_text(script.read_text().replace(
                    "sys.exit(setup.main())",
                    'def calibrate(config):\n'
                    '    (setup.ROOT / "calibrated-model").write_text(config.name)\n'
                    '    return True\n'
                    'setup.calibrate_config = calibrate\n'
                    'sys.exit(setup.main())',
                ))
                result = subprocess.run(self.command(self.new) + ["run", "--rollback-engine"],
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
                    result = subprocess.run(self.command(self.new) + ["run", *args, "--yes"],
                                            env=self.env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((root / "calibrated-model").read_text(), "strata-Q2_0.json")
                    self.assertEqual(approval.read_bytes(), approved)
                    self.assertEqual(marker.read_bytes() if marker.exists() else None, certified)
                    self.assertEqual((root / "engine/strata").read_text(), "A")
                    self.assertFalse((root / "update-attempts").exists())
                self.start_rollback_workspace(root, "--calibrate", "--model=Q2_0", "--family=qwen")
                self.assertEqual((root / "engine/strata").read_text(), "A")
                self.assertFalse((root / "update-attempts").exists())

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_explicit_update_takes_precedence_over_calibration(self):
        root = self.make_rollback_workspace()
        result = subprocess.run(self.command(self.new) + ["run", "--rollback-engine"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            self.command(self.new) + ["run", "--calibrate", "--update",
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
                result = subprocess.run(self.command(self.new) + ["run", "--rollback-eng"],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                for _ in range(2):
                    self.start_rollback_workspace(root)
                    self.assertEqual((root / "engine/strata").read_text(), "A")
                    self.assertFalse((root / "update-attempts").exists())
                    self.assertEqual(marker.read_text().strip(), self.new)
                result = subprocess.run(
                    self.command(self.new) + ["run", "--update", "--prebuilt=" + str(root / "engine/custom")],
                    env=self.env, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "engine/strata").read_text(), "D")
                self.assertFalse((root / ".git/strata-engine-rollback.json").exists())
                self.start_rollback_workspace(root)
                self.assertEqual((root / "update-attempts").read_text(), "1")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_rollback_approval_does_not_mask_missing_prerequisites(self):
        state = self.state
        for missing in ("tokenizer", "python", "other-engine"):
            with self.subTest(missing=missing):
                self.state = state / missing
                root = self.make_rollback_workspace()
                result = subprocess.run(self.command(self.new) + ["run", "--rollback-engine"],
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
                    result = subprocess.run(self.command(self.new) + ["run", "--no-browser", *args],
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
                result = subprocess.run(self.command(self.new) + ["run", *args],
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
                result = subprocess.run(self.command(self.new) + ["run", "--rollback-engine"],
                                        env=self.env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                if change == "source":
                    for revision in (self.old, self.new):
                        result = subprocess.run(self.command(revision) + ["run", "--help"],
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
                        [sys.executable, WORKSPACE, str(self.state), self.new, "", "", SOURCE_PATCH, flag],
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
        script = root / "setup.sh"
        script.write_text(script.read_text().replace(
            "setup.pip_install = lambda *args, **kwargs: None\n", "",
        ))
        (root / "serve/server.py").write_text("import rollback_probe\n" + GATE)
        result = subprocess.run(self.command(self.new) + ["run", "--rollback-engine"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.start_rollback_workspace(root)
        self.assertEqual((root / "engine/strata").read_text(), "A")
        self.assertEqual((root / "update-attempts").read_text(), "1")
        self.assertEqual((root / ".git/strata-runtime-revision").read_text().strip(), self.new)
        self.start_rollback_workspace(root)
        self.assertEqual((root / "engine/strata").read_text(), "A")
        self.assertEqual((root / "update-attempts").read_text(), "1")

    @unittest.skipUnless(sys.platform == "linux", "Upstream Linux CLI")
    def test_rollback_approvals_are_per_toolkit(self):
        root = self.make_rollback_workspace()
        shutil.copytree(root / "engine", root / "engine-cuda12")
        config = json.loads((root / "strata-fixture.json").read_text())
        config["exe"] = str(root / "engine-cuda12/strata")
        (root / "strata-cuda12.json").write_text(json.dumps(config))
        for args in (["--rollback-engine"], ["--rollback-engine", "--cuda=12"]):
            result = subprocess.run(self.command(self.new) + ["run", *args],
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
        result = subprocess.run(self.command(self.new) + ["run", "--rollback-engine"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = subprocess.run(
            [str(root / ".venv/bin/python"), WORKSPACE, "--runtime-status", str(root)],
            env=self.env, cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(status.returncode, 0)
        result = subprocess.run(self.command(self.new) + ["run", "--no-browser"],
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
        result = subprocess.run(self.command(self.new) + ["run", "--rollback-engine"],
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
        setup = root / "setup.sh"
        setup.write_text(f"#!{shutil.which('sh')}\nexit 9\n")
        result = subprocess.run([sys.executable, WORKSPACE, str(self.state), self.new, "", "", SOURCE_PATCH, "--update"],
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
    def test_upstream_server_exec_keeps_pid_releases_lock_and_observers_answer(self):
        # Keep the actual setup/start path, not the unrelated C++ tree, docs or Git metadata.
        for name in ("setup.sh", "requirements.txt", "requirements-monitor.txt", "CMakeLists.txt"):
            shutil.copyfile(Path(UPSTREAM) / name, self.repo / name)
        shutil.copytree(Path(UPSTREAM) / "serve", self.repo / "serve", copy_function=shutil.copyfile)
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
        self.env["PIP_NO_INDEX"] = "1"
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


unittest.main()
