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


def legacy_workspace(state, revision):
    candidates = [
        p for p in state.glob("source-*")
        if p.is_dir() and re.fullmatch(r"source-[0-9a-f]{40}", p.name)
    ]
    settings = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "strata/settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
        installs = data.get("installs", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        installs = []
    if isinstance(installs, list):
        for entry in installs:
            if isinstance(entry, str) and Path(entry) in candidates:
                return Path(entry)
    current = state / f"source-{revision}"
    if current in candidates:
        return current
    if candidates:
        return max(candidates, key=lambda p: max(
            [p.stat().st_mtime] + [c.stat().st_mtime for c in p.glob("strata-*.json")]
        ))
    return None


def _prepare_workspace(state, revision, remote):
    source = state / "source"
    if not source.exists():
        legacy = legacy_workspace(state, revision)
        if legacy is not None:
            source.symlink_to(legacy.name, target_is_directory=True)
        else:
            source.mkdir(mode=0o700)
    root = source.resolve()
    if not (root / ".git").exists():
        git(root, "init", "--quiet")
    if git(root, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode:
        match = re.fullmatch(r"source-([0-9a-f]{40})", root.name)
        initial = match[1] if match else revision
        git(root, "fetch", "--quiet", "--depth=1", remote, initial)
        if match:
            git(root, "reset", "--quiet", "--mixed", "FETCH_HEAD")
        else:
            git(root, "checkout", "--quiet", "--no-overwrite-ignore", "--detach", "FETCH_HEAD")
        marker = root / ".git" / RUNTIME_REVISION
        if not marker.exists():
            marker.write_bytes(subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"]))
    current = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    git(root, "update-ref", f"refs/strata/revisions/{current}", current)
    if git(root, "cat-file", "-e", f"{revision}^{{commit}}", check=False).returncode:
        git(root, "fetch", "--quiet", "--depth=1", remote, revision)
    git(root, "update-ref", f"refs/strata/revisions/{revision}", revision)
    git(root, "checkout", "--quiet", "--no-overwrite-ignore", "--detach", revision)
    return root


def prepare_workspace(state, revision, remote=REMOTE):
    with workspace_lock(state) as (state, _):
        return _prepare_workspace(state, revision, remote)


def refresh_runtime(root, revision, lock_fd, args, *, force=False):
    marker = root / ".git" / RUNTIME_REVISION
    if not force and marker.exists() and marker.read_text().strip() == revision:
        return
    subprocess.run(
        ["sh", str(root / "setup.sh"), "--update", *args],
        check=True, stdout=sys.stderr, pass_fds=(lock_fd,),
    )
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(revision + "\n")
    temporary.replace(marker)


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
            flag for flag in ("--help", "--check", "--inspect", "--rollback-engine", "--update")
            if any(len(option) > 2 and flag.startswith(option) for option in options)
        }
        if any(option.startswith("-h") for option in options):
            requested.add("--help")
        explicit_update = "--update" in requested
        standalone_requested = bool(requested & {"--help", "--inspect", "--rollback-engine"}) or (
            "--check" in requested and not explicit_update
        )
        if not standalone_requested:
            refresh_runtime(root, revision, lock.fileno(), args, force=explicit_update)
        retain_interpreter(state, venv)
        if explicit_update and not standalone_requested:
            return
        os.environ["STRATA_EXECV"] = "1"
        os.set_inheritable(lock.fileno(), True)
        os.execv(root / "setup.sh", [str(root / "setup.sh"), *args])


if __name__ == "__main__":
    try:
        run_workspace(sys.argv[1], sys.argv[2], sys.argv[3:])
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
    except RuntimeError as error:
        sys.exit(str(error))
