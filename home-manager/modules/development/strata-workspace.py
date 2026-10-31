"""Manage Strata's pinned, writable checkout and its runtime under the user's state directory.

Keep revision refs for offline rollback, serialize source/runtime changes, and root Nix Python.
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


def git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        stdout=sys.stderr if check else subprocess.DEVNULL,
        stderr=sys.stderr if check else subprocess.DEVNULL,
    )


@contextmanager
def workspace_lock(state):
    state = Path(state).expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".source.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield state, lock


def _prepare_workspace(state, revision, remote):
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
    if git(root, "cat-file", "-e", f"{revision}^{{commit}}", check=False).returncode:
        git(root, "fetch", "--quiet", "--depth=1", remote, revision)
    git(root, "update-ref", f"refs/strata/revisions/{revision}", revision)
    git(root, "checkout", "--quiet", "--no-overwrite-ignore", "--detach", revision)
    return root


def prepare_workspace(state, revision, remote=REMOTE):
    with workspace_lock(state) as (state, _):
        return _prepare_workspace(state, revision, remote)


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


def run_workspace(state, revision, args):
    with workspace_lock(state) as (state, lock):
        root = _prepare_workspace(state, revision, REMOTE)
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
        options = [arg.partition("=")[0] for arg in args]
        requested = {
            flag for flag in ("--help", "--check", "--inspect", "--rollback-engine", "--update",
                              "--setup", "--model", "--family", "--no-start")
            if any(len(option) > 2 and flag.startswith(option) for option in options)
        }
        if any(option.startswith("-h") for option in options):
            requested.add("--help")
        explicit_update = "--update" in requested
        setup_requested = bool(requested & {"--setup", "--model", "--family", "--no-start"})
        standalone_requested = bool(requested & {"--help", "--inspect", "--rollback-engine"}) or (
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
        if sys.argv[1] == "--runtime-status":
            check_runtime(Path(sys.argv[2]).resolve())
        else:
            run_workspace(sys.argv[1], sys.argv[2], sys.argv[3:])
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
    except RuntimeError as error:
        sys.exit(str(error))
    except (OSError, ValueError, ImportError) as error:
        sys.exit(f"Cannot validate or prepare Strata runtime: {error}. "
                 "Repair the named file/package, or run strata --setup; then retry strata --update.")
