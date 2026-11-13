"""Manage Strata's pinned, writable checkout and its runtime under the user's state directory.

Keep revision refs for offline rollback, serialize source/runtime changes, and root Nix Python.
One `strata` name reaches both upstream programs: a subcommand is upstream's Terminal, options (or nothing)
are upstream's setup. The shape of argv decides, and both shapes are read from the checkout.
A runtime revision records validated local prerequisites, not merely an updater's exit status.
Component references retain upstream compatibility and pins; raw paths use legacy freshness rules.
Validation does not prove GPU compatibility, model integrity, or successful inference.
"""

from contextlib import contextmanager
import argparse
import ast
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
    if not source.exists():
        if source.is_symlink():
            raise RuntimeError(
                f"Workspace link {source} is broken; restore its target or remove the link and retry"
            )
        source.mkdir(mode=0o700)
    root = source.resolve()
    if not (root / ".git").exists():
        git(root, "init", "--quiet")
    if git(root, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode:
        # A pre-existing source symlink can target an uninitialised source-<sha>
        # tree; index that tree instead of checking out over its untracked files.
        match = re.fullmatch(r"source-([0-9a-f]{40})", root.name)
        initial = match[1] if match else revision
        git(root, "fetch", "--quiet", "--depth=1", remote, initial)
        if match:
            git(root, "reset", "--quiet", "--mixed", "FETCH_HEAD")
        else:
            try:
                git(root, "checkout", "--quiet", "--no-overwrite-ignore", "--detach", "FETCH_HEAD")
            except subprocess.CalledProcessError:
                raise RuntimeError(
                    f"Cannot initialise workspace {root}; move it aside and retry"
                ) from None
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
        if git(root, "cat-file", "-e", f"{revision}^{{commit}}", check=False).returncode:
            git(root, "fetch", "--quiet", "--depth=1", remote, revision)
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


def check_runtime(root):
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
    configs = setup.installed_configs()
    if not configs:
        raise RuntimeError("No Strata model is installed; run strata --setup before strata --update")

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
        report = doctor.inspect(config)
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
              f"{setup.REQUIREMENTS}), close the model, check the updater's errors, then run strata --update."
              "\nNo runtime revision was certified; the next normal launch will retry."
        )


def runtime_status(root, lock_fd):
    python = root / "python/bin/python3"
    if not os.access(python, os.X_OK):
        python = root / ".venv/bin/python"
    if not os.access(python, os.X_OK):
        return subprocess.CompletedProcess(
            [], 1, "", f"Runtime interpreter {python} is unavailable; run strata --setup, then retry strata --update"
        )
    return subprocess.run(
        [str(python), str(Path(__file__).resolve()), "--runtime-status", str(root)],
        cwd=root, capture_output=True, text=True, pass_fds=(lock_fd,),
    )


def refresh_runtime(root, revision, lock_fd, args, *, force=False):
    marker = root / ".git" / RUNTIME_REVISION
    rollback_path = root / ".git" / ENGINE_ROLLBACK
    if force:
        rollback_path.unlink(missing_ok=True)
    rollbacks = engine_rollbacks(root, revision) if not force else {}
    current = marker.exists() and marker.read_text().strip() == revision
    status = None
    if not force and (current or rollbacks):
        status = runtime_status(root, lock_fd)
        if status.returncode == 0 and current:
            return
    if status is None or status.returncode:
        marker.unlink(missing_ok=True)
        if not rollbacks:
            rollback_path.unlink(missing_ok=True)
        # Upstream --build skips engine acquisition during --update;
        # Python/config repair still runs without replacing rolled-back engines.
        repair_args = [*args, "--build"] if rollbacks else args
        subprocess.run(
            ["sh", str(root / "setup.sh"), "--update", *repair_args],
            check=True, stdout=sys.stderr, pass_fds=(lock_fd,),
        )
        status = runtime_status(root, lock_fd)
        if status.returncode:
            raise RuntimeError(status.stderr.strip() or status.stdout.strip() or
                               "Strata runtime validation failed; run strata --update after repairing the runtime")
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


def _function(tree, name):
    """A top-level function of a parsed source file, or None."""
    return next((node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == name), None)


def _flags(node):
    """The literal string arguments of a parser call: option strings, or a positional's name."""
    return [flag.value for flag in node.args if isinstance(flag, ast.Constant) and isinstance(flag.value, str)]


def terminal_words(root, args=()):
    """The words upstream's Terminal accepts: its subcommands, and the options it takes before one.

    Asked of the checkout's own parser, and run rather than read as text: upstream contributes subcommands from
    other modules (`launch_cmd.add_parsers(sp)` in strata_cli/cli.py), which a source scan would miss and then
    silently send `strata launch` to setup. Running it also means a new upstream subcommand routes with no change
    here, and the words cannot drift from upstream."""
    probe = """import argparse, contextlib, io, json, sys
sys.path.insert(0, sys.argv[1])
from strata_cli.cli import parser, _install_argv
p = parser()
sub = [action for action in p._actions if isinstance(action, argparse._SubParsersAction)]
words = {'commands': sorted(sub[0].choices) if sub else [],
         'options': sorted(p._option_string_actions), 'terminal': False, 'command': None}
args = sys.argv[2:]
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    try:
        option = p._parse_optional(args[0]) if args else None
        # Python 3.14 returns a list of option matches; earlier argparse returns one tuple.
        if isinstance(option, list):
            option = option[0] if len(option) == 1 else None
        candidate = bool(args and (args[0] in words['commands'] or
                         (option and option[0] and not {'-h', '--help'} & set(option[0].option_strings))))
        if candidate:
            words['terminal'] = True
            parsed, _ = p.parse_known_args(_install_argv(args))
            words['command'] = parsed.command
    except SystemExit:
        pass
print(json.dumps(words))
"""
    result = subprocess.run([sys.executable, "-c", probe, str(root), *args],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Cannot read upstream's Terminal arguments in {root}: "
                           f"{result.stderr.strip() or 'its parser did not run'}")
    words = json.loads(result.stdout)
    if not words["commands"]:
        raise RuntimeError("Upstream's Terminal declares no subcommands in strata_cli/cli.py")
    # Every parser, setup's included, carries -h/--help, so it says nothing about which program was meant: the
    # person who types `strata --help` in a source checkout gets upstream's setup, who wants the Terminal asks it.
    words["options"] = [option for option in words["options"] if option not in {"-h", "--help"}]
    return words


def cli_doors(root, args=()):
    """One `strata` name, two upstream programs: the Terminal's words, and the shape that keeps them apart.

    Upstream invokes its Terminal only by subcommand and its setup only by option. If upstream gives its setup a
    positional argument or subcommands, the two shapes overlap and this says so and stops, rather than guessing
    which program the person meant."""
    words = terminal_words(root, args)
    setup_main = _function(ast.parse((root / "setup.py").read_text()), "main")
    if setup_main is None:
        raise RuntimeError("Cannot inspect upstream setup's argument parser")
    for node in ast.walk(setup_main):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) \
                or node.func.attr not in {"add_argument", "add_subparsers"}:
            continue
        if node.func.attr == "add_subparsers" or any(not flag.startswith("-") for flag in _flags(node)):
            raise RuntimeError(
                "Upstream's setup takes a positional argument or subcommands, so `strata` can no longer tell a "
                "setup from a Terminal command by shape: give the two doors their own names again.")
    return words


def entry_point(root, args):
    """Which upstream program this argv means: 'terminal' or 'setup'."""
    return "terminal" if cli_doors(root, args)["terminal"] else "setup"


def setup_options(root, args):
    """Classify argv with upstream's option names and arities, without running setup."""
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    parser = Parser(add_help=False, argument_default=argparse.SUPPRESS)
    parser.add_argument("-h", "--help", action="store_true", dest="--help")
    main = _function(ast.parse((root / "setup.py").read_text()), "main")
    if main is None:
        raise RuntimeError("Cannot inspect upstream setup's argument parser")
    for node in ast.walk(main):
        if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
                or not isinstance(node.func.value, ast.Name) or node.func.value.id != "ap"
                or node.func.attr != "add_argument"):
            continue
        flags = [ast.literal_eval(flag) for flag in node.args]
        shape = {keyword.arg: ast.literal_eval(keyword.value) for keyword in node.keywords
                 if keyword.arg in {"action", "nargs"}}
        if shape.get("action", "store") not in {"store", "store_true", "store_false"}:
            raise RuntimeError("Unsupported upstream setup argument action")
        parser.add_argument(*flags, dest=flags[0], **shape)
    if not {"--data-dir", "--models-dir"} <= set(parser._option_string_actions):
        raise RuntimeError("Upstream setup no longer declares its download-directory options")
    try:
        return set(vars(parser.parse_args(args)))
    except ValueError:
        # Let upstream report unknown or ambiguous argument forms without refreshing.
        return {"--help"}


def run_workspace(state, revision, args, *, data_directory=None, models_directory=None, source_patch=None,
                  managed_setup=False):
    state = Path(state).expanduser().resolve()
    # Observation must not queue behind acquisition or serving. Only a checkout with HEAD can bypass
    # preparation; interrupted initialization must resume under the lock before importing its parser.
    source = state / "source"
    if (not managed_setup and (source / ".git").exists()
            and git(source, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0):
        words = cli_doors(source, args)
        if words["terminal"] and (words["command"] in {"status", "monitor", "logs", "connection"}
                                  or words["command"] is None):
            if words["command"] == "monitor":
                # Observation owns no lock; its opt-in update worker reacquires one.
                os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({"state": str(state)})
            python = source / ".venv/bin/python"
            os.execv(str(python), [str(python), str(source / TERMINAL_CLI), *args])
    with workspace_lock(state, inherited=managed_setup) as (state, lock):
        root = _prepare_workspace(state, revision, REMOTE, source_patch)
        os.environ["STRATA_WORKSPACE_LOCK_FD"] = str(lock.fileno())
        os.environ["STRATA_WORKSPACE_HELPER"] = str(Path(__file__).resolve())
        os.environ["STRATA_WORKSPACE_CONTEXT"] = json.dumps({
            "state": str(state), "revision": revision, "data_directory": data_directory,
            "models_directory": models_directory, "source_patch": source_patch, "remote": REMOTE,
        })
        os.set_inheritable(lock.fileno(), True)
        venv = root / ".venv"
        retain_interpreter(state, venv)
        python = venv / "bin/python"
        # The runtime marker is ours; invalidate it after dropping a pip-less venv.
        # Upstream recreates the venv, but --update must restore its dependencies before start.
        if venv.is_dir() and subprocess.run(
            [str(python), "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode != 0:
            shutil.rmtree(venv)
            (root / ".git" / RUNTIME_REVISION).unlink(missing_ok=True)
            retain_interpreter(state, venv)
        if not managed_setup and entry_point(root, args) == "terminal":
            # Install re-enters this helper with the same locked file description. Launch keeps the
            # lock through acquisition/config writes; upstream releases it at its service boundary.
            if not os.access(python, os.X_OK):
                raise RuntimeError(
                    f"Strata's Terminal runs in the checkout's environment at {python}, which is not set up yet: "
                    "run `strata --setup` first, then the Terminal again.")
            os.execv(str(python), [str(python), str(root / TERMINAL_CLI), *args])
            return
        requested = setup_options(root, args)
        explicit_update = "--update" in requested
        calibration_requested = (
            "--calibrate" in requested
            and not requested & {"--update", "--setup", "--check"}
            and bool(model_configs(root))
        )
        setup_requested = (
            bool(requested & {"--setup", "--model", "--family", "--no-start"})
            and not calibration_requested
        )
        standalone_requested = (calibration_requested and "--no-start" in requested) or bool(
            requested & {"--help", "--inspect", "--prepare-pack", "--rollback-engine"}
        ) or (
            "--check" in requested and not explicit_update
        )
        rollback_requested = "--rollback-engine" in requested
        rollback_path = root / ".git" / ENGINE_ROLLBACK
        if rollback_path.exists() and not engine_rollbacks(root, revision):
            rollback_path.unlink()
        if not standalone_requested and (explicit_update or setup_requested):
            rollback_path.unlink(missing_ok=True)
        # A new install or explicit setup must reach upstream's acquisition path.
        # Do not certify it here: the next launch validates the resulting runtime.
        try:
            if rollback_requested:
                before = {
                    name: (engine_identity(root / name).get("strata"),
                           engine_identity(root / name / ".previous").get("strata"))
                    for name in ENGINE_DIRECTORIES
                }
                subprocess.run(
                    [str(root / "setup.sh"), *args],
                    check=True, pass_fds=(lock.fileno(),),
                )
                record_engine_rollback(root, revision, before)
                return
            if not standalone_requested:
                if explicit_update or (not setup_requested and model_configs(root)):
                    refresh_runtime(root, revision, lock.fileno(), args, force=explicit_update)
                else:
                    (root / ".git" / RUNTIME_REVISION).unlink(missing_ok=True)
            # Directory defaults apply during setup, not when starting an installed model.
            # Parse actual upstream options so values and ambiguous prefixes do not
            # override defaults or change command classification.
            if (not standalone_requested and not explicit_update
                    and (setup_requested or not model_configs(root))):
                for flag, directory in (("--data-dir", data_directory),
                                        ("--models-dir", models_directory)):
                    if directory is not None and flag not in requested:
                        args = [*args, flag, directory]
                if models_directory is not None and "--separate-model-artifacts" not in requested:
                    args = [*args, "--separate-model-artifacts"]
        finally:
            # Even a partial updater may have created a new venv interpreter.
            retain_interpreter(state, venv)
        if explicit_update and not standalone_requested:
            return
        os.environ["STRATA_EXECV"] = "1"
        os.set_inheritable(lock.fileno(), True)
        os.execv(root / "setup.sh", [str(root / "setup.sh"), *args])


if __name__ == "__main__":
    try:
        if sys.argv[1] == "--managed-setup":
            context = json.loads(os.environ["STRATA_WORKSPACE_CONTEXT"])
            REMOTE = context.pop("remote")
            run_workspace(**context, args=sys.argv[2:], managed_setup=True)
        elif sys.argv[1] == "--runtime-status":
            check_runtime(Path(sys.argv[2]).resolve())
        else:
            run_workspace(sys.argv[1], sys.argv[2], sys.argv[6:],
                          data_directory=sys.argv[3] or None,
                          models_directory=sys.argv[4] or None,
                          source_patch=sys.argv[5] or None)
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
    except RuntimeError as error:
        sys.exit(str(error))
    except (OSError, ValueError, ImportError) as error:
        sys.exit(f"Cannot validate or prepare Strata runtime: {error}. "
                 "Repair the named file/package, or run strata --setup; then retry strata --update.")
