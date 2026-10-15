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
    if git(root, "cat-file", "-e", f"{revision}^{{commit}}", check=False).returncode:
        git(root, "fetch", "--quiet", "--depth=1", remote, revision)
    git(root, "checkout", "--quiet", "--no-overwrite-ignore", "--detach", revision)
    return root


def prepare_workspace(state, revision, remote=REMOTE):
    with workspace_lock(state) as (state, _):
        return _prepare_workspace(state, revision, remote)


def refresh_runtime(root, revision, lock_fd):
    marker = root / ".git" / RUNTIME_REVISION
    if marker.exists() and marker.read_text().strip() == revision:
        return
    subprocess.run(
        ["sh", str(root / "setup.sh"), "--update"],
        check=True, stdout=sys.stderr, pass_fds=(lock_fd,),
    )
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(revision + "\n")
    temporary.replace(marker)


def run_workspace(state, revision, args):
    with workspace_lock(state) as (state, lock):
        root = _prepare_workspace(state, revision, REMOTE)
        venv = root / ".venv"
        if venv.is_dir() and not os.access(venv / "bin/python", os.X_OK):
            shutil.rmtree(venv)
            (root / ".git" / RUNTIME_REVISION).unlink(missing_ok=True)
        refresh_runtime(root, revision, lock.fileno())
        os.environ["STRATA_EXECV"] = "1"
        os.set_inheritable(lock.fileno(), True)
        os.execv(root / "setup.sh", [str(root / "setup.sh"), *args])


if __name__ == "__main__":
    try:
        run_workspace(sys.argv[1], sys.argv[2], sys.argv[3:])
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
