"""Manage Strata's pinned, writable checkout and its runtime under the user's state directory.

Keep revision refs for offline rollback, serialize source/runtime changes, and root Nix Python.
The public Terminal grammar owns the root; `source` delegates raw arguments to setup's real parser.
Only real actions bootstrap Python or reconcile an installed runtime after a pin change.
A runtime revision records validated local prerequisites, not merely an updater's exit status.
Component references retain upstream compatibility and pins; raw paths use legacy freshness rules.
Validation does not prove GPU compatibility, model integrity, or successful inference.
"""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


REMOTE = "https://github.com/Niko1221/Strata.git"
RUNTIME_REVISION = "strata-runtime-revision"
ENGINE_ROLLBACK = "strata-engine-rollback.json"
ENGINE_DIRECTORIES = ("engine", "engine-cuda12")
SOURCE_PATCH = "strata-source.patch"
TERMINAL_CLI = "strata.py"


def git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        stdout=sys.stderr if check else subprocess.DEVNULL,
        stderr=sys.stderr if check else subprocess.DEVNULL,
    )


@contextmanager
def workspace_lock(state, *, inherited=False):
    state = Path(state).expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True)
    lock = (os.fdopen(int(os.environ["STRATA_WORKSPACE_LOCK_FD"]), "a") if inherited
            else (state / ".source.lock").open("a"))
    with lock:
        if not inherited:
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield state, lock


@contextmanager
def source_publication_lock(state, *, shared=False):
    """Protect source readers without tying observations to runtime acquisition."""
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".source-publication.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield lock


def patch_check(root, text, *, reverse=False):
    return subprocess.run(
        ["git", "-C", str(root), "apply", *(["--reverse"] if reverse else []), "--check", "-"],
        input=text, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def apply_source_patch(root, text, *, reverse=False):
    subprocess.run(
        ["git", "-C", str(root), "apply", *(["--reverse"] if reverse else []), "-"],
        input=text, text=True, check=True,
    )


def publish_source_patch(path, text):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def _prepare_workspace(state, revision, remote, source_patch=None):
    source = state / "source"
    with source_publication_lock(state):
        if not source.exists():
            if source.is_symlink():
                raise RuntimeError(
                    f"Workspace link {source} is broken; restore its target or remove the link and retry"
                )
            source.mkdir(mode=0o700)
        root = source.resolve()
        if not (root / ".git").exists():
            git(root, "init", "--quiet")
        initialise = git(root, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode != 0
    if initialise:
        # Fetching changes objects, not published Python files. Keep observers out of that wait.
        match = re.fullmatch(r"source-([0-9a-f]{40})", root.name)
        initial = match[1] if match else revision
        git(root, "fetch", "--quiet", "--depth=1", remote, initial)
        with source_publication_lock(state):
            if match:
                git(root, "reset", "--quiet", "--mixed", "FETCH_HEAD")
            else:
                try:
                    git(root, "checkout", "--quiet", "--no-overwrite-ignore", "--detach", "FETCH_HEAD")
                except subprocess.CalledProcessError:
                    raise RuntimeError(
                        f"Cannot initialise workspace {root}; move it aside and retry"
                    ) from None
    if git(root, "cat-file", "-e", f"{revision}^{{commit}}", check=False).returncode:
        git(root, "fetch", "--quiet", "--depth=1", remote, revision)
    with source_publication_lock(state):
        current = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        # Workaround: upstream pulls its configured branch, not a pinned revision.
        # Keep visited revisions reachable for GC-safe offline rollback.
        # Remove when upstream supports both revision pinning and GC-safe offline rollback.
        git(root, "update-ref", f"refs/strata/revisions/{current}", current)
        ledger = root / ".git" / SOURCE_PATCH
        previous = ledger.read_text() if ledger.exists() else None
        desired = Path(source_patch).read_text() if source_patch is not None else None
        applied = previous is not None and patch_check(root, previous, reverse=True)
        if previous is not None and not applied and not patch_check(root, previous):
            raise RuntimeError(f"Cannot reconcile source patch in {root}; preserve {ledger} and repair conflicting edits")
        if previous == desired and current == revision and applied:
            return root
        if applied:
            apply_source_patch(root, previous, reverse=True)
        ledger.unlink(missing_ok=True)
        try:
            git(root, "update-ref", f"refs/strata/revisions/{revision}", revision)
            git(root, "checkout", "--quiet", "--no-overwrite-ignore", "--detach", revision)
        except subprocess.CalledProcessError:
            try:
                head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
                if previous is not None:
                    if head != current or not patch_check(root, previous):
                        print(f"Cannot restore source patch in {root}; original checkout failure is preserved", file=sys.stderr)
                    else:
                        publish_source_patch(ledger, previous)
                        apply_source_patch(root, previous)
            except (OSError, subprocess.CalledProcessError) as restore_error:
                print(f"Cannot restore source patch in {root}: {restore_error}", file=sys.stderr)
            raise
        if current != revision:
            (root / ".git" / ENGINE_ROLLBACK).unlink(missing_ok=True)
        if desired is not None:
            if not patch_check(root, desired):
                raise RuntimeError(f"Cannot apply managed source patch in {root}; repair conflicting edits without discarding user files")
            publish_source_patch(ledger, desired)
            apply_source_patch(root, desired)
        return root


def prepare_workspace(state, revision, remote=REMOTE, source_patch=None):
    with workspace_lock(state) as (state, _):
        return _prepare_workspace(state, revision, remote, source_patch)


def model_configs(root):
    """Find the same run-config shape as upstream, without needing a bootstrapped interpreter."""
    configs = []
    for path in root.glob("strata-*.json"):
        if path.name.endswith(".shared-settings.json"):
            continue
        try:
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(cfg, dict) and cfg.get("exe") and isinstance(cfg.get("args"), list):
            configs.append(path)
    return configs


def engine_identity(directory):
    """Track unchanged payloads without hashing large binaries or mutable directories."""
    if not directory.is_dir():
        return {}
    files = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        info = path.stat()
        files[path.name] = [
            str(path.resolve()), info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_mode,
        ]
    return files


def engine_sources(root, vision=False):
    sys.path.insert(0, str(root))
    import setup

    names = ["ENGINE_SOURCES"] + (["VISION_SOURCES"] if vision else [])
    return {name: setup.source_hash(getattr(setup, name)) for name in names}


def engine_rollbacks(root, revision):
    try:
        saved = json.loads((root / ".git" / ENGINE_ROLLBACK).read_text())
    except (FileNotFoundError, ValueError):
        return {}
    if not isinstance(saved, dict) or saved.get("revision") != revision:
        return {}
    entries = saved.get("engines")
    if not isinstance(entries, dict):
        return {}
    approved = {}
    for name in ENGINE_DIRECTORIES:
        entry = entries.get(name)
        if not isinstance(entry, dict):
            continue
        files = engine_identity(root / name)
        if "strata" not in files or entry.get("files") != files:
            continue
        sources = entry.get("sources", {})
        if not isinstance(sources, dict):
            continue
        if sources and sources != engine_sources(root, "VISION_SOURCES" in sources):
            continue
        approved[name] = entry
    return approved


def record_engine_rollback(root, revision, before):
    approved = engine_rollbacks(root, revision)
    changed = False
    for name, (installed, previous) in before.items():
        files = engine_identity(root / name)
        current = files.get("strata")
        # A zero-exit help/inspect command is not proof of a rollback.
        if not current or not previous or current[1:3] != previous[1:3]:
            continue
        if installed and current[1:3] == installed[1:3]:
            continue
        metadata = root / name / "BUILD.json"
        try:
            build = json.loads(metadata.read_text()) if metadata.exists() else {}
        except ValueError:
            build = {}
        sources = {}
        if isinstance(build, dict) and (build.get("source") == "local" or build.get("backend") == "hip"):
            sources = engine_sources(root, build.get("vision", "none") != "none")
        approved[name] = {"files": files, "sources": sources}
        changed = True
    if changed:
        path = root / ".git" / ENGINE_ROLLBACK
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"revision": revision, "engines": approved}) + "\n")
        temporary.replace(path)


def check_runtime(root, selected=()):
    """Run in the runtime interpreter; inspect local state without acquisition or engine execution."""
    from importlib import metadata
    from pip._vendor.packaging.requirements import Requirement

    sys.path.insert(0, str(root))
    import setup
    from strata_control import doctor, engine_component
    from strata_control.profiles import read_run_config

    problems = []
    rollbacks = {}
    if (root / ".git" / ENGINE_ROLLBACK).exists():
        revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        rollbacks = engine_rollbacks(root, revision)
    selected = {Path(path).resolve() for path in selected}
    configs = list(dict.fromkeys([*(path.resolve() for path in setup.installed_configs()), *sorted(selected)]))

    # Match pip_install's intentional compatibility policy for legacy bare-name stamps.
    stamp = Path(sys.prefix) / ".strata-pip.json"
    have = json.loads(stamp.read_text()) if stamp.exists() and setup.pip_stamp_is_ours(stamp) else []
    bare = {p.lower() for p in have if setup.req_name(p) == p.lower()}
    requirements = setup.runtime_packages()
    if sys.platform == "darwin":
        requirements = setup.requirement_lines() if setup.REQUIREMENTS.exists() else setup.PY_PACKAGES
    for line in requirements:
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = metadata.version(requirement.name)
        except metadata.PackageNotFoundError:
            problems.append(f"Python package missing: {requirement.name}")
            continue
        legacy = setup.req_name(line) in bare or (bare and "==" in line)
        if not legacy and not requirement.specifier.contains(version, prereleases=True):
            problems.append(f"Python package {requirement.name} is {version}; requires {requirement.specifier}")

    checked = set()
    for config in configs:
        report = doctor.inspect(config, cwd=os.getcwd() if config in selected else None)
        for component in report["components"]:
            if component["required"] and component["status"] in {"missing", "invalid"}:
                problems.append(f"{config.name}: {component['name']} {component['status']}: "
                                f"{component.get('path', component.get('reason', ''))}")
        # Component references use upstream compatibility checks and explicit pins,
        # not the legacy flat-engine version floor.
        if engine_component.is_reference(read_run_config(config)["exe"]):
            continue
        engine = next(component for component in report["components"] if component["name"] == "engine")
        exe = Path(engine["path"])
        if engine["status"] != "ok" or exe in checked:
            continue
        checked.add(exe)
        preserved = any(exe.resolve() == (root / name / "strata").resolve() for name in rollbacks)
        if sys.platform == "darwin" and exe.resolve() == (root / "build-metal/strata").resolve():
            from metal import setup_mac
            if not setup_mac.engine_current():
                problems.append(f"{exe}: Metal engine was not built for this source")
            continue
        info = exe.parent / "BUILD.json"
        meta = json.loads(info.read_text()) if info.exists() else {}
        manifest = exe.parent / engine_component.MANIFEST
        if manifest.exists():
            component = engine_component.read_manifest(exe.parent)
            if component.exe.resolve() != exe.resolve():
                problems.append(f"{exe}: component manifest names a different entrypoint")
                continue
            version = tuple(int(part) if part.isdigit() else 0
                            for part in re.split(r"[.\-+]", component.version))
        else:
            value = meta.get("version") or setup.binary_engine_version(exe) or ""
            version = tuple(int(part) for part in str(value).split(".")[:4] if part.isdigit())
        if not any(version) or (version < setup.MIN_ENGINE and not preserved):
            problems.append(f"{exe}: engine version {'.'.join(map(str, version)) or 'unknown'}; "
                            f"requires {'.'.join(map(str, setup.MIN_ENGINE))} or newer")
        managed = exe.parent.resolve() in {setup.engine_dir().resolve(), setup.engine_dir(12).resolve()}
        if managed and not preserved and (meta.get("source") == "local" or meta.get("backend") == "hip"):
            if meta.get("src") != setup.source_hash(setup.ENGINE_SOURCES) or setup.stale_binary(exe):
                problems.append(f"{exe}: compiled engine does not match this source")
            if meta.get("vision", "none") != "none" and \
                    meta.get("vision_src") != setup.source_hash(setup.VISION_SOURCES):
                problems.append(f"{exe}: vision engine does not match this source")
    if problems:
        raise RuntimeError(
            "Strata runtime is incomplete:\n  " + "\n  ".join(problems)
            + f"\nRepair the named files/packages (Python: {sys.executable} -m pip install -r "
              f"{setup.REQUIREMENTS}), close the model, check the updater's errors, then run strata source --update."
              "\nNo runtime revision was certified; the next normal launch will retry."
        )


def reconcile_configs(root, configs):
    """Apply upstream's argument migrations to selected configs without rebuilding their launch choices."""
    sys.path.insert(0, str(root))
    import setup
    from strata_control.profiles import read_run_config

    caller = Path.cwd()
    try:
        for config in configs:
            path = Path(config).resolve()
            cfg = read_run_config(path)
            os.chdir(caller)
            os.chdir(cfg.get("cwd") or caller)
            setup.upgrade_config(path, cfg)
    finally:
        os.chdir(caller)


def runtime_status(root, lock_fd, configs=(), *, reconcile=False):
    python = root / "python/bin/python3"
    if not os.access(python, os.X_OK):
        python = root / ".venv/bin/python"
    if not os.access(python, os.X_OK):
        return subprocess.CompletedProcess(
            [], 1, "", f"Runtime interpreter {python} is unavailable; run strata source --setup, then retry strata source --update"
        )
    return subprocess.run(
        [str(python), str(Path(__file__).resolve()),
         "--reconcile-runtime" if reconcile else "--runtime-status", str(root), *map(str, configs)],
        cwd=Path.cwd() if configs else root, capture_output=True, text=True, pass_fds=(lock_fd,),
    )


def refresh_runtime(root, revision, lock_fd, args, *, force=False, configs=()):
    marker = root / ".git" / RUNTIME_REVISION
    rollback_path = root / ".git" / ENGINE_ROLLBACK
    if force:
        rollback_path.unlink(missing_ok=True)
    rollbacks = engine_rollbacks(root, revision) if not force else {}
    current = marker.exists() and marker.read_text().strip() == revision
    status = None
    if not force and (current or rollbacks):
        status = runtime_status(root, lock_fd, configs, reconcile=True)
        if status.returncode == 0 and current:
            return
    marker.unlink(missing_ok=True)
    if not rollbacks:
        rollback_path.unlink(missing_ok=True)
    if force or not current or status is None or status.returncode:
        # Upstream --build preserves approved rolled-back engines while repairing Python and configs.
        repair_args = [*args, "--build"] if rollbacks else args
        subprocess.run(
            ["sh", str(root / "setup.sh"), "--update", *repair_args],
            check=True, stdout=sys.stderr, pass_fds=(lock_fd,),
        )
        status = runtime_status(root, lock_fd, configs, reconcile=True)
        if status.returncode:
            raise RuntimeError(status.stderr.strip() or status.stdout.strip() or
                               "Strata runtime validation failed; run strata source --update after repairing the runtime")
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(revision + "\n")
    temporary.replace(marker)


# Workaround: upstream's ambient-Python venv can depend on a collectable Nix store path.
# Remove when every supported bootstrap path keeps its interpreter alive independently.
def retain_interpreter(state, venv):
    python = venv / "bin/python" if venv.is_dir() else Path(sys.executable)
    interpreter = python.resolve()
    store = Path(os.environ.get("NIX_STORE_DIR", "/nix/store"))
    root = state / ".python-root"
    if interpreter.is_relative_to(store):
        package = store / interpreter.relative_to(store).parts[0]
        if not root.is_symlink() or root.resolve() != package or not os.access(python, os.X_OK):
            subprocess.run(
                ["nix-store", "--realise", str(package), "--add-root", str(root)],
                check=True, stdout=sys.stderr,
            )
    elif root.is_symlink():
        root.unlink()
    if venv.is_dir() and not os.access(python, os.X_OK):
        raise RuntimeError(f"Interpreter {python} is unavailable; virtual environment preserved at {venv}")


def runtime_python(root):
    bundled = root / "python/bin/python3"
    return bundled if os.access(bundled, os.X_OK) else root / ".venv/bin/python"


def bootstrap_runtime(state, root, lock_fd):
    """Let upstream create its environment and install its own runtime requirements, without a model."""
    retain_interpreter(state, root / ".venv")
    venv = root / ".venv"
    python = runtime_python(root)
    if venv.is_dir() and python == venv / "bin/python" and subprocess.run(
        [str(python), "-m", "pip", "--version"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode:
        shutil.rmtree(venv)
        (root / ".git" / RUNTIME_REVISION).unlink(missing_ok=True)
        retain_interpreter(state, venv)
    try:
        subprocess.run(
            ["sh", str(root / "setup.sh")], check=True, stdout=sys.stderr,
            env=dict(os.environ, STRATA_BOOTSTRAP_ONLY="1"), pass_fds=(lock_fd,),
        )
    except BaseException:
        (root / ".git" / RUNTIME_REVISION).unlink(missing_ok=True)
        raise
    finally:
        retain_interpreter(state, root / ".venv")
    python = runtime_python(root)
    if not os.access(python, os.X_OK):
        raise RuntimeError(f"Strata bootstrap did not provide a runtime interpreter at {python}")
    return python


def observer_probe(root, args):
    """Use the real parser and UI constructor in an isolated interpreter, never a stale import cache."""
    sys.path.insert(0, str(root))
    from strata_control import acquisition
    with acquisition.source_observation():
        a = terminal_args(root, args)
        if a.command == "monitor" and runtime_action(a):
            try:
                from strata_cli.client import Endpoint
                from strata_cli.monitor import MonitorApp
                from strata_cli.launch.monitor_ext import LaunchMonitor
                LaunchMonitor(Endpoint("http://127.0.0.1", None, 3.0, ""), None,
                              info={}, ask_quit=False)
            except ImportError:
                return 72
    return 73


def exec_observer(root, python, args, lock, *, state):
    for key in ("STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT"):
        os.environ.pop(key, None)
    if args[:1] == ["monitor"]:
        os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(state)})
    os.set_inheritable(lock.fileno(), True)
    os.environ["STRATA_SOURCE_LOCK_FD"] = str(lock.fileno())
    os.execv(str(python), [str(python), str(root / TERMINAL_CLI), *args])


def terminal_args(root, args):
    sys.path.insert(0, str(root))
    from strata_cli.cli import parse_args
    return parse_args(args)


def runtime_action(a):
    """Opt in only actions whose execution needs Python runtime or screen dependencies."""
    if a.command == "launch":
        return not (a.plan or any(getattr(a, key, False)
                                 for key in ("status", "list_presets", "show_key", "stop", "delete_preset")))
    if a.command == "serve":
        return not (a.plan or a.json)
    if a.command == "monitor":
        return not a.once
    return a.command == "bench" and a.bench_command == "run" and not getattr(a, "plan", False)


def managed_runtime_configs(root, a):
    """Return selected configs for managed actions, or None for independent external runtimes."""
    root = root.resolve()
    if a.command == "launch":
        from strata_cli.launch.catalog import resolve_installation
        target, _ = resolve_installation()
        return [] if target.resolve() == root else None
    if a.command == "serve":
        from strata_control import doctor, engine_component, profiles
        try:
            config, _, _ = profiles.resolve(a.config)
            config = config.resolve()
            if config.parent == root:
                return [config]
            cfg = profiles.read_run_config(config)
        except profiles.ProfileError:
            return None  # Native dispatch reports the original typed profile error.
        if not engine_component.is_reference(cfg["exe"]):
            effective = dict(cfg, cwd=cfg.get("cwd") or os.getcwd())
            if doctor._location(cfg["exe"], effective, config).resolve().is_relative_to(root):
                return [config]
    return None


def source_exec(context, args):
    """Apply managed policy after setup's real parser, before its filesystem or acquisition work."""
    state = Path(context["state"])
    root = (state / "source").resolve()
    revision = context["revision"]
    lock_fd = int(os.environ["STRATA_WORKSPACE_LOCK_FD"])
    os.chdir(root)
    sys.path.insert(0, str(root))
    import setup

    def after_parse(a, argv):
        python = runtime_python(root)
        runtime_ready = (os.environ.pop("STRATA_RUNTIME_READY", None) == str(root)
                         and Path(sys.executable).absolute() == python)
        have = bool(model_configs(root))
        calibration = a.calibrate and not (a.update or a.setup or a.check) and have
        installing = bool(a.setup or a.model or a.family or a.no_start) and not calibration
        standalone = bool(a.inspect or a.prepare_pack or a.rollback_engine
                          or (a.check and not a.update) or (calibration and a.no_start))
        if standalone and os.access(python, os.X_OK) and Path(sys.executable).absolute() != python:
            os.execv(str(python), [str(python), str(Path(__file__).resolve()), "--source-exec", *argv])
        if not standalone and not a.update and (installing or not have):
            for name, flag, key in (("data_dir", "--data-dir", "data_directory"),
                                    ("models_dir", "--models-dir", "models_directory")):
                if getattr(a, name) is None and context.get(key) is not None:
                    setattr(a, name, context[key])
                    argv.extend([flag, context[key]])
            if context.get("models_directory") is not None and not a.separate_model_artifacts:
                a.separate_model_artifacts = True
                argv.append("--separate-model-artifacts")
        rollback = root / ".git" / ENGINE_ROLLBACK
        if rollback.exists() and not engine_rollbacks(root, revision):
            rollback.unlink()
        if not standalone and (a.update or installing):
            rollback.unlink(missing_ok=True)
        if a.update and not standalone:
            (root / ".git" / RUNTIME_REVISION).unlink(missing_ok=True)
        if not standalone and not runtime_ready:
            python = bootstrap_runtime(state, root, lock_fd)
            os.environ["STRATA_RUNTIME_READY"] = str(root)
            os.execv(str(python), [str(python), str(Path(__file__).resolve()), "--source-exec", *argv])
        if a.rollback_engine:
            before = {
                name: (engine_identity(root / name).get("strata"),
                       engine_identity(root / name / ".previous").get("strata"))
                for name in ENGINE_DIRECTORIES
            }
            try:
                subprocess.run(["sh", str(root / "setup.sh"), *argv],
                               check=True, pass_fds=(lock_fd,))
            finally:
                retain_interpreter(state, root / ".venv")
            record_engine_rollback(root, revision, before)
            return 0
        if not standalone:
            if a.update or (not installing and have):
                refresh_runtime(root, revision, lock_fd, argv, force=a.update)
            else:
                (root / ".git" / RUNTIME_REVISION).unlink(missing_ok=True)
        if a.update and not standalone:
            return 0
        os.environ["STRATA_EXECV"] = "1"
        return None

    try:
        return setup.main(args, after_parse=after_parse)
    except setup.acquisition.AcquisitionRefused as error:
        setup.say(f"\n  [X]  {error}")
        return error.exit_code
    except KeyboardInterrupt:
        setup.say("\nstopped.")
        return 1


def run_workspace(state, revision, args, *, data_directory=None, models_directory=None, source_patch=None,
                  managed_setup=False):
    state = Path(state).expanduser().resolve()
    source = state / "source"
    ledger = source / ".git" / SOURCE_PATCH
    # Hold a short source read lease through the guard, native parser, UI readiness and exec.
    if (not managed_setup and args and args[0] in {"status", "monitor", "logs", "connection"}
            and (source / ".git").exists() and source_patch is not None):
        with source_publication_lock(state, shared=True) as source_lock:
            if (ledger.is_file() and ledger.read_text() == Path(source_patch).read_text()
                    and git(source, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0
                    and patch_check(source, ledger.read_text(), reverse=True)):
                python = runtime_python(source)
                if not os.access(python, os.X_OK):
                    python = Path(sys.executable)
                probe = subprocess.run(
                    [str(python), str(Path(__file__).resolve()), "--observer-probe", str(source), *args],
                    env={**os.environ, "STRATA_SOURCE_LOCK_FD": str(source_lock.fileno())},
                    pass_fds=(source_lock.fileno(),),
                )
                if probe.returncode == 73:
                    exec_observer(source, python, args, source_lock, state=state)
                elif probe.returncode != 72:
                    probe.check_returncode()
                    return 0  # Native help finished in the probe.
    with workspace_lock(state, inherited=managed_setup) as (state, lock):
        root = _prepare_workspace(state, revision, REMOTE, source_patch)
        context = {
            "state": str(state), "revision": revision, "data_directory": data_directory,
            "models_directory": models_directory, "source_patch": source_patch, "remote": REMOTE,
        }
        os.environ["STRATA_WORKSPACE_LOCK_FD"] = str(lock.fileno())
        os.environ["STRATA_WORKSPACE_HELPER"] = str(Path(__file__).resolve())
        os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps(context)
        os.set_inheritable(lock.fileno(), True)
        if managed_setup:
            return source_exec(context, args)
        a = terminal_args(root, args)
        if a.command == "source":
            return source_exec(context, a.setup_args)
        python = runtime_python(root)
        if runtime_action(a):
            python = bootstrap_runtime(state, root, lock.fileno())
            configs = managed_runtime_configs(root, a)
            if configs is not None and (configs or model_configs(root)):
                refresh_runtime(root, revision, lock.fileno(), [], configs=configs)
        elif not os.access(python, os.X_OK):
            python = Path(sys.executable)
        if a.command in {"status", "monitor", "logs", "connection"}:
            with source_publication_lock(state, shared=True) as source_lock:
                # Close the owning object, not its raw descriptor; context cleanup stays idempotent.
                lock.close()
                exec_observer(root, python, args, source_lock, state=state)
        os.execv(str(python), [str(python), str(root / TERMINAL_CLI), *args])


if __name__ == "__main__":
    try:
        if sys.argv[1] in {"--managed-setup", "--source-exec"}:
            context = json.loads(os.environ["STRATA_WORKSPACE_CONTEXT"])
            REMOTE = context["remote"]
            if sys.argv[1] == "--source-exec":
                sys.exit(source_exec(context, sys.argv[2:]))
            context.pop("remote")
            sys.exit(run_workspace(**context, args=sys.argv[2:], managed_setup=True))
        elif sys.argv[1] == "--observer-probe":
            sys.exit(observer_probe(Path(sys.argv[2]).resolve(), sys.argv[3:]))
        elif sys.argv[1] in {"--runtime-status", "--reconcile-runtime"}:
            root = Path(sys.argv[2]).resolve()
            if sys.argv[1] == "--reconcile-runtime":
                reconcile_configs(root, sys.argv[3:])
            check_runtime(root, sys.argv[3:])
        else:
            sys.exit(run_workspace(sys.argv[1], sys.argv[2], sys.argv[6:],
                                   data_directory=sys.argv[3] or None,
                                   models_directory=sys.argv[4] or None,
                                   source_patch=sys.argv[5] or None))
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
    except RuntimeError as error:
        sys.exit(str(error))
    except (OSError, ValueError, ImportError) as error:
        sys.exit(f"Cannot validate or prepare Strata runtime: {error}. "
                 "Repair the named file/package, or run strata source --setup; then retry strata source --update.")
