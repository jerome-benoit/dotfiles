"""Source-independent state operations for managed Strata checkouts.

Managed profile, path and inventory consumers are selected only inside the managed
source package; independent installations retain every native module/API.
Payload moves are journaled renames; staged engine links project references without a second physical move.
Only configs, launch scripts and interpreter metadata are edited, with exact-byte restoration on failure.
"""

from contextlib import ExitStack, contextmanager
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import sys
import tempfile


DIRECTORY = Path(__file__).resolve().parent
LAYOUT_FILES = ("strata-*.json", "strata-*.log", "run-*.bat", "run-*.sh", "build-strata*.bat")
LAYOUT_DIRS = ("models", "packs", "mtp", "marks", ".strata-mcp", "engine-sycl", "engine-cuda12", ".rocm-win",
               ".venv", ".python", "python")
TERMINAL_BUILDS = ("build", "build-cuda12", "build-hip", "build-vision-hip", "build-vision",
                   "build-vision-cuda12", "build-vision-sycl", "build-image-cuda", "build-image-hip", "build-image-cpu")
ENGINE_BUILDS = ("build-metal", "build-sycl", "build-sycl-aot")
ENGINE_SOURCE = {"src", "include", "cmake", "metal", "sycl", "spark", "third_party", "tests", "bench",
                 "CMakeLists.txt", "CMakePresets.json"}
TERMINAL_ENTRIES = ("strata.py", "setup.py", "serve", "strata_cli", "strata_control", "tools", "data", "ref", "bin",
                    ".venv", ".python", "python")
# Transaction-owned backups must never become payloads or link-edit consumers.
TRANSACTION_PREFIXES = (".strata-layout-", ".strata-links-", ".strata-link-", ".strata-cmake-",
                        "strata-links-", "strata-engine-link-")
SYCL_PATH_FLAGS = {"--pack", "--native", "--native-dense-gguf", "--embd-gguf",
                   "--ple-gguf", "--expert-profile", "--mtp", "--control-vector-scaled"}


class ManagedConsumers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in {"strata_control.profiles", "strata_control.cfg_paths", "strata_control.doctor"} or path is None:
            return None
        repository = os.environ.get("STRATA_MANAGED_SOURCE")
        if not repository:
            return None
        repository = Path(repository).resolve()
        packages = {repository / "strata_control", repository / "terminal" / "strata_control"}
        if not any(Path(item).resolve() in packages for item in path):
            return None
        return importlib.util.spec_from_file_location(fullname, DIRECTORY / (fullname.rsplit(".", 1)[1] + ".py"))


def install_consumer():
    """Install a lazy, package-scoped consumer; never import checkout code at Python startup."""
    if not any(isinstance(finder, ManagedConsumers) for finder in sys.meta_path):
        sys.meta_path.insert(0, ManagedConsumers())


def enable_source(root):
    repository = root.parent if root.name == "terminal" and (root.parent / ".git").is_dir() else root
    os.environ["STRATA_MANAGED_SOURCE"] = str(repository.resolve())
    paths = os.environ.get("PYTHONPATH", "").split(os.pathsep)
    os.environ["PYTHONPATH"] = os.pathsep.join([str(DIRECTORY), *(p for p in paths if p and p != str(DIRECTORY))])
    install_consumer()


def install_acquisition(*, native_setup=False):
    """Propagate one validated acquisition lease through native setup subprocesses.

    Python descendants re-install this adapter through the stable bootstrap.
    Other executables retain the descriptor until exit, but their own spawns
    are outside Python's subprocess boundary.
    """
    import subprocess

    marker = os.environ.get("STRATA_ACQUISITION_BOOTSTRAP")
    if not native_setup and marker is None:
        return
    value = os.environ.get("STRATA_WORKSPACE_LOCK_FD")
    if value is None:
        raise RuntimeError("Native acquisition bootstrap has no workspace descriptor")
    descriptor = int(value)
    held = os.fstat(descriptor)
    identity = f"{held.st_dev}:{held.st_ino}"
    if descriptor < 3 or not stat.S_ISREG(held.st_mode) or (marker is not None and marker != identity):
        raise RuntimeError("Native acquisition descriptor identity is invalid")
    context = os.environ.get("STRATA_WORKSPACE_CONTEXT")
    if context is not None:
        expected = (Path(json.loads(context)["state"]) / ".source.lock").stat()
        if (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
            raise RuntimeError("Native acquisition descriptor does not belong to this workspace")
    os.set_inheritable(descriptor, False)
    os.environ["STRATA_ACQUISITION_BOOTSTRAP"] = identity
    original = subprocess.Popen
    if getattr(original, "_strata_acquisition_identity", None) == (descriptor, identity):
        return
    repository = Path(os.environ["STRATA_MANAGED_SOURCE"]).resolve()

    def without_acquisition(env):
        env = dict(env)
        for key in ("STRATA_ACQUISITION_BOOTSTRAP", "STRATA_WORKSPACE_LOCK_FD",
                    "STRATA_WORKSPACE_CONTEXT", "STRATA_WORKSPACE_HELPER"):
            env.pop(key, None)
        return env

    class AcquisitionProcess(original):
        _strata_acquisition_identity = (descriptor, identity)

        def __init__(self, args, *positional, **options):
            env = dict(os.environ if options.get("env") is None else options["env"])
            independent = False
            if isinstance(args, (list, tuple)) and len(args) >= 2 and Path(args[1]).name == "setup.py":
                target = Path(options.get("cwd") or os.getcwd()) / args[1]
                independent = target.resolve() not in (repository / "setup.py", repository / "terminal/setup.py")
            if independent:
                options["env"] = external_environment(env)
                options["pass_fds"] = tuple(fd for fd in options.get("pass_fds", ()) if fd != descriptor)
            elif env.get("STRATA_NO_ACQUIRE") == "1":
                # Native setup.start marks the server read-only before spawning it.
                # Retain source-reader/consumer bootstrap, not the mutation lease.
                options["env"] = without_acquisition(env)
                options["pass_fds"] = tuple(fd for fd in options.get("pass_fds", ()) if fd != descriptor)
            elif env.get("STRATA_ACQUISITION_BOOTSTRAP") == identity:
                current = os.fstat(descriptor)
                if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
                    raise RuntimeError("Native acquisition descriptor changed before spawn")
                options["pass_fds"] = tuple(dict.fromkeys((*options.get("pass_fds", ()), descriptor)))
                options["env"] = source_environment(env, repository)
            super().__init__(args, *positional, **options)

    subprocess.Popen = AcquisitionProcess
    original_execve = os.execve

    def acquisition_execve(path, args, env):
        # Preserve native intentional exec and argv while removing stale protocol
        # for read-only services; the non-inheritable descriptor closes at exec.
        if env.get("STRATA_NO_ACQUIRE") == "1":
            env = without_acquisition(env)
        return original_execve(path, args, env)

    os.execve = acquisition_execve


def external_environment(environ):
    """Remove only this managed bootstrap when handing execution to an independent installation."""
    env = dict(environ)
    for key in ("STRATA_MANAGED_SOURCE", "STRATA_PROFILE_NAMESPACE_FD", "STRATA_WORKSPACE_HELPER",
                "STRATA_WORKSPACE_CONTEXT", "STRATA_WORKSPACE_LOCK_FD", "STRATA_SOURCE_LOCK_FD",
                "STRATA_BOOTSTRAP_ONLY", "STRATA_RUNTIME_READY", "STRATA_LAUNCH_RUNTIME_READY",
                "STRATA_ACQUISITION_BOOTSTRAP"):
        env.pop(key, None)
    paths = [path for path in env.get("PYTHONPATH", "").split(os.pathsep) if path and Path(path).resolve() != DIRECTORY]
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths)
    else:
        env.pop("PYTHONPATH", None)
    return env


def source_environment(environ, installation):
    """Retain the lazy bootstrap only for the managed installation, even after native PYTHONPATH resets."""
    env = dict(environ)
    repository = env.get("STRATA_MANAGED_SOURCE")
    if repository is None:
        return env
    repository = Path(repository).resolve()
    if Path(installation).resolve() not in (repository, repository / "terminal"):
        return external_environment(env)
    paths = env.get("PYTHONPATH", "").split(os.pathsep)
    env["PYTHONPATH"] = os.pathsep.join([str(DIRECTORY), *(path for path in paths if path and path != str(DIRECTORY))])
    return env


def rebaser(swaps):
    replacements = {sa: sb for a, b in swaps
                    for sa, sb in ((str(a), str(b)), (str(a).replace("\\", "/"), str(b).replace("\\", "/")))}
    pattern = "|".join(re.escape(path) for path in sorted(replacements, key=lambda path: -len(path)))

    def rebase(text):
        return re.sub("(" + pattern + r")(?=$|[\\/\"'\s;,])", lambda match: replacements[match[1]], text)

    return rebase


def shell_rebaser(swaps, rebase):
    """Handle shlex.quote encodings in activation/pip wrappers, not arbitrary package strings."""
    quoted = {shlex.quote(str(a))[1:-1]: shlex.quote(str(b))[1:-1] for a, b in swaps if "'" in str(a)}
    pattern = "|".join(re.escape(path) for path in sorted(quoted, key=lambda path: -len(path)))

    def transform(text):
        if pattern:
            text = re.sub("(" + pattern + r")(?=$|[\\/\"'\s;,])", lambda match: quoted[match[1]], text)
        return rebase(text)

    return transform


def rebase_script(text, source, destination, rebase):
    # Match only a complete cd operand: ROOT is not a generic Git-prefix replacement.
    pattern = re.compile(r"(?im)^(?P<prefix>[ \t]*cd[ \t]+(?:/d[ \t]+|--[ \t]+)?)"
                         r"(?P<path>[^\r\n]*?)(?P<suffix>[ \t]*\r?$)")

    def replace(match):
        raw = match["path"]
        value = raw[1:-1] if raw[:1] == '"' and raw[-1:] == '"' else raw
        if value != str(source):
            try:
                operands = shlex.split(raw)
            except ValueError:
                return match[0]
            value = operands[0] if len(operands) == 1 else None
        if value != str(source):
            return match[0]
        path = '"' + str(destination) + '"' if raw[:1] == '"' else shlex.quote(str(destination))
        return match["prefix"] + path + match["suffix"]

    return rebase(pattern.sub(replace, text))


def _sycl_cwd(config, base):
    """Resolve config coordinates against its known source, never the helper's cwd."""
    cwd = Path(config.get("cwd") or base).expanduser()
    return (cwd if cwd.is_absolute() else base / cwd).resolve()


def _sycl_wrapper(config, base):
    wrapper = Path(str(config.get("exe", ""))).expanduser()
    return (wrapper if wrapper.is_absolute() else _sycl_cwd(config, base) / wrapper).resolve()


def sycl_config(config, source, destination, repository, reverse, rebase, *, base=None):
    """Publish a stable transport from the actual old wrapper's mount/cwd, never a /work text swap."""
    base = Path(base if base is not None else source)
    wrapper = _sycl_wrapper(config, base)
    if Path(str(config.get("exe", ""))).name != "strata-sycl.sh":
        return config
    previous = dict(config.get("env") or {})
    transport_keys = {"STRATA_SYCL_ROOT", "STRATA_SYCL_CWD", "STRATA_SYCL_BIN", "STRATA_SYCL_HERE"}
    environment = {key: (value if key in transport_keys else rebase(value) if isinstance(value, str) else value)
                   for key, value in previous.items()}
    moving = source != destination
    old_cwd = _sycl_cwd(config, base)
    selected_here = previous.get("STRATA_SYCL_HERE")
    old_here = ((old_cwd / Path(selected_here).expanduser()).resolve() if selected_here
                else wrapper.parents[2])
    stable = bool(previous.get("STRATA_SYCL_HERE"))
    fixed = stable
    wrapper_text = wrapper.read_text(encoding="utf-8", errors="replace") if wrapper.is_file() else ""
    if not fixed and (reverse or not moving):
        if not wrapper.is_file() and not reverse and (repository / "terminal/setup.py").is_file():
            fixed = True       # A git checkout removed the new engine-source wrapper: it had that layout.
        elif wrapper.is_file():
            # Native flat wrappers always launch from the mounted checkout basename (including custom mirrors);
            # the engine-source wrapper and the stable transport launch from their explicit root.
            fixed = 'repo_in=/work/$(basename "$here")' not in wrapper_text
    # Relative host environment coordinates use the launch cwd, as the native wrapper does.
    # The native wrapper reads these from the process environment, so a config value stands in for it;
    # the default mount is the root its script computes from the engine root, one or two levels above.
    mount_value = previous.get("STRATA_SYCL_ROOT", os.environ.get("STRATA_SYCL_ROOT"))
    deep_root = 'dirname "$(dirname "$here")"' in wrapper_text
    old_mount = Path(mount_value).expanduser() if mount_value else (old_here.parent.parent if deep_root else old_here.parent)
    if not old_mount.is_absolute():
        old_mount = old_cwd / old_mount
    old_mount = old_mount.resolve()
    new_mount = Path(rebase(str(old_mount))).resolve() if mount_value else repository.parent
    environment["STRATA_SYCL_ROOT"] = str(new_mount)
    selected_cwd = previous.get("STRATA_SYCL_CWD", os.environ.get("STRATA_SYCL_CWD"))
    if fixed and selected_cwd:
        container_cwd = PurePosixPath(selected_cwd)
        if not container_cwd.is_relative_to("/work") or ".." in container_cwd.parts:
            raise RuntimeError("STRATA_SYCL_CWD must be a normalized container path within /work")
        old_workdir = old_mount / container_cwd.relative_to("/work")
    else:
        old_workdir = old_here if fixed else old_mount / old_here.name
    here = repository / "engine" if not reverse and (repository / "terminal/setup.py").is_file() else repository
    new_workdir = here if here.is_relative_to(new_mount) else Path(rebase(str(old_workdir)))
    if not new_workdir.is_relative_to(new_mount):
        raise RuntimeError(f"Migrated SYCL working directory {new_workdir} is outside {new_mount}")
    environment["STRATA_SYCL_HERE"] = str(here)
    environment["STRATA_SYCL_CWD"] = "/work" + ("/" + new_workdir.relative_to(new_mount).as_posix()
                                                if new_workdir != new_mount else "")

    def host_path(raw):
        path = PurePosixPath(raw)
        if path.is_relative_to("/work"):
            host = old_mount / path.relative_to("/work")
        elif not path.is_absolute():
            host = old_workdir / str(path)
        else:
            host = Path(raw)
        return Path(os.path.normpath(rebase(str(host))))

    def container_path(raw):
        path = PurePosixPath(raw)
        if path.is_absolute() and not path.is_relative_to("/work"):
            return raw                         # e.g. /dev/shm is its own, unchanged mount.
        host = host_path(raw)
        if not host.is_relative_to(new_mount):
            raise RuntimeError(f"Migrated SYCL path {host} is outside its selected mount {new_mount}")
        return (os.path.relpath(host, new_workdir).replace(os.sep, "/") if not path.is_absolute()
                else "/work" + ("/" + host.relative_to(new_mount).as_posix() if host != new_mount else ""))

    args = [rebase(value) for value in config.get("args", [])]
    for index, flag in enumerate(config.get("args", [])[:-1]):
        if flag not in SYCL_PATH_FLAGS:
            continue
        value = config["args"][index + 1]
        if flag == "--mtp" and str(value).isdigit():
            continue  # Draft depth is a value, not a directory, just as in the doctor.
        path, separator, scale = value.rpartition(":") if flag == "--control-vector-scaled" else (value, "", "")
        args[index + 1] = container_path(path if separator else value) + (separator + scale if separator else "")
    binary = previous.get("STRATA_SYCL_BIN", os.environ.get("STRATA_SYCL_BIN")) or "build-sycl-aot/strata"
    selected_binary = (Path(os.path.normpath(rebase(str(Path(binary).expanduser()))))
                       if stable and Path(binary).is_absolute() else host_path(binary))
    if not selected_binary.is_relative_to(new_mount):
        raise RuntimeError(f"Selected SYCL binary {selected_binary} is outside its mount {new_mount}")
    # The wrapper resolves a relative binary against its working directory; name the payload host-absolute.
    environment["STRATA_SYCL_BIN"] = str(selected_binary)
    return dict(config, exe=str(DIRECTORY / "strata-sycl.sh"), args=args, env=environment)


def _model_config(data):
    try:
        config = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        return None                            # Native setup skips unselected user JSON.
    return config if isinstance(config, dict) and config.get("exe") and isinstance(config.get("args"), list) else None


def _managed_sycl_config(config, repository, base):
    wrapper = _sycl_wrapper(config, base)
    if Path(str(config.get("exe", ""))).name != "strata-sycl.sh":
        return False
    previous_here = (config.get("env") or {}).get("STRATA_SYCL_HERE")
    return (wrapper.is_relative_to(repository)
            or bool(previous_here and (_sycl_cwd(config, base) / Path(previous_here).expanduser()).resolve()
                    in (repository, repository / "engine")))


def normalize_sycl_config(config, repository, *, base=None):
    if base is None and not config.get("cwd") and not Path(str(config.get("exe", ""))).expanduser().is_absolute():
        return config                          # Unknown relative coordinates cannot establish managed ownership.
    repository = Path(repository).resolve()
    runtime = repository / "terminal" if (repository / "terminal/setup.py").is_file() else repository
    base = Path(base if base is not None else runtime)
    if not _managed_sycl_config(config, repository, base):
        return config                          # An independent installation retains its own transport.
    return sycl_config(config, runtime, runtime, repository, False, lambda value: value, base=base)


def canonical_config_paths(repository, paths=()):
    """Collect owned run configs and every internal saved selection, once per regular inode."""
    runtime = repository / "terminal" if (repository / "terminal/setup.py").is_file() else repository
    enable_source(runtime)
    sys.path.insert(0, str(runtime))
    from strata_control import profiles
    candidates = set(paths)
    candidates.update(profiles.source_config_paths())
    identities = set()
    result = []
    for candidate in sorted(candidates):
        path = candidate.resolve()
        if not path.is_relative_to(repository) or not path.is_file():
            continue
        info = path.stat()
        identity = (info.st_dev, info.st_ino)
        if identity not in identities:
            identities.add(identity)
            result.append(path)
    return result


def normalize_sycl_configs(repository):
    repository = Path(repository).resolve()
    runtime = repository / "terminal" if (repository / "terminal/setup.py").is_file() else repository
    enable_source(runtime)
    sys.path.insert(0, str(runtime))
    from strata_control import profiles
    with profiles._source_references_lock():
        _normalize_sycl_configs(repository, runtime)


def _normalize_sycl_configs(repository, runtime):
    changes = []
    for path in canonical_config_paths(repository, runtime.glob("strata-*.json")):
        before = path.read_bytes()
        config = _model_config(before)
        if config is None:
            continue
        mapped = normalize_sycl_config(config, repository, base=path.parent)
        if mapped != config:
            changes.append((path, before, (json.dumps(mapped, indent=2) + "\n").encode("utf-8")))
    edited = []
    try:
        for path, before, after in changes:
            edited.append((path, before, path.stat()))
            path.write_bytes(after)
    except BaseException:
        for path, before, info in reversed(edited):
            path.write_bytes(before)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        raise


def interpreter_entries(root):
    def walk_error(error):
        raise error

    yield root
    if not root.is_symlink():
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            # Parent-local transaction snapshots are not runtime payloads.
            dirs[:] = [name for name in dirs if not name.startswith(TRANSACTION_PREFIXES)]
            for name in dirs + [name for name in files if not name.startswith(TRANSACTION_PREFIXES)]:
                yield Path(directory) / name


def write_runtime(entry, payload, link_mode, backup=None):
    if link_mode is None:
        entry.write_bytes(payload)              # Keep metadata permissions and inodes.
    else:
        if backup is not None:
            os.rename(entry, backup)            # Retain the original symlink inode for rollback.
        try:
            with tempfile.TemporaryDirectory(prefix=".strata-link-", dir=entry.parent) as temporary:
                link = Path(temporary) / "link"
                os.symlink(payload, link)
                if hasattr(os, "lchmod"):
                    os.lchmod(link, link_mode)
                os.replace(link, entry)
        except BaseException:
            if backup is not None and backup.is_symlink():
                os.replace(backup, entry)
            raise


def namespace_fds():
    value = os.environ.get("STRATA_PROFILE_NAMESPACE_FD")
    return (int(value),) if value is not None else ()


@contextmanager
def layout_checkpoint(repository, *, enabled=True, metadata_paths=(), metadata_directories=(), runtime_moves=None,
                      reference_moves=()):
    """Keep small original bytes/inodes and the profile namespace until a source transaction settles."""
    if not enabled:
        yield lambda: None
        return
    import fcntl
    repository = Path(repository).resolve()
    explicit = os.environ.get("STRATA_PROFILE_DIR")
    directory = (Path(explicit).expanduser() if explicit else
                 Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "strata" / "profiles")
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    namespace = directory.resolve() / ".source-references.namespace.lock"
    with namespace.open("a+b") as lock, ExitStack() as snapshots:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before_fd = os.environ.get("STRATA_PROFILE_NAMESPACE_FD")
        os.environ["STRATA_PROFILE_NAMESPACE_FD"] = str(lock.fileno())
        try:
            paths = {path for path in directory.glob("*.json") if path.is_file() and not path.is_symlink()}
            metadata = directory / ".source-relocations.json"
            # Receipts and engine approval rollback data share the outer source transaction.
            tracked = {metadata, *(repository / ".git" / name for name in
                        ("strata-source-request.json", "strata-source.patch", "strata-engine-rollback.json")),
                       *map(Path, metadata_paths)}
            absent = {path for path in tracked if not path.exists() and not path.is_symlink()}
            absent_directories = {Path(path) for path in metadata_directories if not Path(path).exists()}
            paths.update(tracked - absent)
            history = set((directory / ".history").glob("*/*.json"))
            for runtime in (repository, repository / "terminal"):
                paths.update(path for pattern in LAYOUT_FILES for path in runtime.glob(pattern) if path.is_file()
                             and (path.suffix == ".json" or path.name.startswith("run-")))
                for name in (".venv", ".python", "python"):
                    root = runtime / name
                    if not root.exists() and not root.is_symlink():
                        continue
                    for entry in interpreter_entries(root):
                        if entry.is_symlink():
                            paths.add(entry)
                        elif entry.is_file():
                            metadata_entry = entry == root / "pyvenv.cfg" or (entry.parent.name in ("bin", "Scripts")
                                             and entry.name.lower().startswith("activate"))
                            if not metadata_entry and entry.parent.name in ("bin", "Scripts"):
                                with entry.open("rb") as stream:
                                    metadata_entry = stream.read(2) == b"#!"
                            if metadata_entry:
                                paths.add(entry)
            # Writers follow config links, but ownership stops at the repository boundary.
            enable_source(repository / "terminal" if (repository / "terminal/setup.py").is_file() else repository)
            paths.update(canonical_config_paths(repository,
                         (path for path in paths if path.suffix == ".json" and path.name.startswith("strata-"))))
            moves = (runtime_pairs(repository) + runtime_pairs(repository, reverse=True)
                     if runtime_moves is None else runtime_moves)
            # Staging changes alias resolution; retain all related owned links, not a pre-stage edit prediction.
            links = (runtime_links(repository, moves, reference_moves=reference_moves) if reference_moves
                     else runtime_link_edits(repository, moves))
            paths.update(link[0] for link in links)
            for path in tuple(paths):
                if path.is_symlink() and path.name.startswith("strata-") and path.suffix == ".json":
                    target = path.resolve()
                    if target.is_relative_to(repository) and _model_config(path.read_bytes()) is not None:
                        paths.add(target)
            originals = []
            temporary_roots = {}
            payloads = {}
            for index, path in enumerate(sorted(paths)):
                info = path.lstat()
                # A parent directory is on the file's mount, including same-device bind mounts.
                anchor = path.parent
                if anchor not in temporary_roots:
                    temporary = tempfile.mkdtemp(prefix=".strata-layout-", dir=anchor)
                    parent_fd = os.open(anchor, os.O_RDONLY)
                    backup_fd = os.open(temporary, os.O_RDONLY)

                    def cleanup(parent_fd=parent_fd, backup_fd=backup_fd, name=Path(temporary).name):
                        try:
                            for entry in os.listdir(backup_fd):
                                os.unlink(entry, dir_fd=backup_fd)
                            os.rmdir(name, dir_fd=parent_fd)
                        finally:
                            os.close(backup_fd)
                            os.close(parent_fd)

                    snapshots.callback(cleanup)
                    temporary_roots[anchor] = backup_fd
                backup = (temporary_roots[anchor], str(index))
                identity = (info.st_dev, info.st_ino)
                if path.is_symlink():
                    payload = None
                else:
                    if identity not in payloads:
                        payloads[identity] = path.read_bytes()
                    payload = payloads[identity]
                os.link(path, backup[1], dst_dir_fd=backup[0], follow_symlinks=False)
                originals.append((path, backup, payload, info.st_mode, info.st_atime_ns, info.st_mtime_ns))

            def restore():
                errors = []

                def attempt(operation):
                    try:
                        operation()
                    except OSError as error:
                        errors.append(error)

                def restore_entry(path, backup, payload, mode, atime, mtime):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    backup_fd, backup_name = backup
                    original = os.stat(backup_name, dir_fd=backup_fd, follow_symlinks=False)
                    try:
                        current = path.lstat()
                    except FileNotFoundError:
                        current = None
                    if current is None or (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
                        replacement = backup_name + ".restore"
                        try:
                            os.unlink(replacement, dir_fd=backup_fd)
                        except FileNotFoundError:
                            pass
                        os.link(backup_name, replacement, src_dir_fd=backup_fd, dst_dir_fd=backup_fd,
                                follow_symlinks=False)
                        os.replace(replacement, path, src_dir_fd=backup_fd)
                    if payload is not None:
                        if path.read_bytes() != payload:
                            path.write_bytes(payload)
                        os.chmod(path, mode)
                        os.utime(path, ns=(atime, mtime))

                for path, backup, payload, mode, atime, mtime in originals:
                    attempt(lambda: restore_entry(path, backup, payload, mode, atime, mtime))
                for path in absent:
                    attempt(lambda: path.unlink(missing_ok=True))

                def clean_history():
                    for path in set((directory / ".history").glob("*/*.json")) - history:
                        attempt(lambda: path.unlink())

                attempt(clean_history)
                if absent_directories:
                    attempt(snapshots.close)
                    for path in sorted(absent_directories, key=lambda path: -len(path.parts)):
                        if path.exists():
                            attempt(path.rmdir)
                if errors:
                    raise RuntimeError("Cannot restore layout checkpoint: " + "; ".join(map(str, errors))) from errors[0]

            yield restore
        finally:
            if before_fd is None:
                os.environ.pop("STRATA_PROFILE_NAMESPACE_FD", None)
            else:
                os.environ["STRATA_PROFILE_NAMESPACE_FD"] = before_fd


def runtime_pairs(repository, *, reverse=False):
    """Describe owned entry identities, retaining links while source staging temporarily vacates their targets."""
    source, destination = ((repository / "terminal", repository) if reverse
                           else (repository, repository / "terminal"))
    pairs = [(path, destination / path.name) for pattern in LAYOUT_FILES
             for path in sorted(source.glob(pattern)) if path.is_file() or path.is_symlink()]
    pairs += [(source / name, destination / name) for name in (*LAYOUT_DIRS, *TERMINAL_BUILDS)
              if (source / name).is_dir() or (source / name).is_symlink()]
    engine = source / "engine"
    if engine.is_dir() and not engine.is_symlink():
        pairs += [(path, destination / "engine" / path.name) for path in sorted(engine.iterdir())
                  if path.name not in ENGINE_SOURCE and not path.name.startswith(("build", *TRANSACTION_PREFIXES))]
    pairs += [((repository / "engine" / name, repository / name) if reverse
               else (repository / name, repository / "engine" / name)) for name in ENGINE_BUILDS
              if ((repository / "engine" / name) if reverse else (repository / name)).is_dir()
              or ((repository / "engine" / name) if reverse else (repository / name)).is_symlink()]
    return pairs


def restore_runtime_moves(moves):
    """Undo only accepted renames, before source checkout and metadata restoration."""
    for source, destination in reversed(moves):
        if source.exists() or source.is_symlink():
            raise RuntimeError(f"Cannot restore moved runtime without replacing {source}")
        source.parent.mkdir(parents=True, exist_ok=True)
        os.rename(destination, source)


def relocated_path(path, pairs):
    for old, new in sorted(pairs, key=lambda pair: -len(pair[0].parts)):
        if path.is_relative_to(old):
            return new / path.relative_to(old)
    return path


def runtime_links(repository, pairs, *, reference_moves=()):
    """Inventory owned link locations, including stationary consumers of a staged engine alias."""
    roots = {source: destination for source, destination in pairs if source.is_symlink() or source.is_dir()}
    if reference_moves:
        # An unmoved owned payload can still refer to the engine alias being staged.
        for runtime in (repository, repository / "terminal"):
            candidates = [runtime / name for name in (*LAYOUT_DIRS, *TERMINAL_BUILDS, *ENGINE_BUILDS)]
            candidates.extend(path for pattern in LAYOUT_FILES for path in runtime.glob(pattern) if path.is_symlink())
            for entry in candidates:
                if entry not in roots and (entry.is_symlink() or entry.is_dir()):
                    roots[entry] = entry
        engine = repository / "engine"
        if engine.is_dir() and not engine.is_symlink():
            for name in ENGINE_BUILDS:
                entry = engine / name
                if entry not in roots and (entry.is_symlink() or entry.is_dir()):
                    roots[entry] = entry
    for source, destination in roots.items():
        for entry in interpreter_entries(source):
            if not entry.is_symlink():
                continue
            relocated = destination / entry.relative_to(source)
            before = os.readlink(entry)
            yield entry, relocated, before, entry.lstat().st_mode


def runtime_link_edits(repository, pairs, *, reference_moves=()):
    """Physical pairs move entries; logical projections move only their targets."""
    references = (*pairs, *reference_moves)
    for entry, relocated, before, mode in runtime_links(repository, pairs, reference_moves=reference_moves):
        target = Path(before) if os.path.isabs(before) else entry.parent / before
        lexical = Path(os.path.normpath(target))
        effective = target.resolve()
        mapped = relocated_path(lexical, references)
        # Keep chains and dangling targets; an unmoved alias may still reach a moved payload.
        if lexical.resolve() != effective or (mapped == lexical and relocated_path(effective, references) != effective):
            mapped = relocated_path(effective, references)
        after = str(mapped) if os.path.isabs(before) else os.path.relpath(mapped, relocated.parent)
        if after != before:
            yield entry, relocated, before, after, mode


@contextmanager
def engine_link_checkpoint(repository, *, reverse=False, enabled=True, tracked_engine=False):
    """Vacate only the runtime engine link before Git creates/removes tracked engine code.

    The external payload is never traversed or copied. Keep the original link inode
    until publication settles, so a refused checkout can restore its exact spelling.
    """
    repository = Path(repository).resolve()
    source, destination = ((repository / "terminal" / "engine", repository / "engine") if reverse
                           else (repository / "engine", repository / "terminal" / "engine"))

    class LinkStage:
        backup = None
        published = None
        created_parent = False

        def planned_reference_moves(self):
            return ((source, destination),) if enabled and source.is_symlink() else ()

        def reference_moves(self):
            return ((source, destination),) if self.backup is not None else ()

        def stage(self):
            if enabled and source.is_symlink():
                self.target = source.resolve(strict=True)
                self.spelling = os.readlink(source)
                lexical = Path(self.spelling)
                lexical = Path(os.path.normpath(lexical if lexical.is_absolute() else source.parent / lexical))
                pairs = runtime_pairs(repository, reverse=reverse)
                self.destination_target = relocated_path(lexical, pairs)
                if lexical.resolve() != self.target or (self.destination_target == lexical
                        and relocated_path(self.target, pairs) != self.target):
                    self.destination_target = relocated_path(self.target, pairs)
                self.backup = temporary / "engine"
                os.rename(source, self.backup)

        def publish(self):
            if self.backup is None:
                return
            if destination.exists() or destination.is_symlink():
                # Only the old revision's tracked engine directory can leave residue.
                # Never delete children or a pre-existing forward runtime destination.
                if not reverse or not tracked_engine or destination.is_symlink():
                    raise RuntimeError(f"Cannot replace existing engine destination: {destination}")
                destination.rmdir()
            self.created_parent = not destination.parent.exists()
            destination.parent.mkdir(parents=True, exist_ok=True)
            target = Path(self.spelling)
            if ((target.is_absolute() and target == self.destination_target)
                    or (not target.is_absolute() and
                        Path(os.path.normpath(destination.parent / target)) == self.destination_target)):
                os.link(self.backup, destination, follow_symlinks=False)
            else:
                destination.symlink_to(str(self.destination_target) if target.is_absolute()
                                       else os.path.relpath(self.destination_target, destination.parent))
            self.published = destination.lstat()

        def withdraw(self):
            if self.published is not None:
                current = destination.lstat()
                if (current.st_dev, current.st_ino) != (self.published.st_dev, self.published.st_ino):
                    raise RuntimeError(f"Engine link changed during source transaction: {destination}")
                destination.unlink()
                self.published = None

        def restore(self):
            if self.backup is None:
                return
            self.withdraw()
            if source.exists() or source.is_symlink():
                source.rmdir()                 # Only empty tracked-code residue is ours to remove.
            source.parent.mkdir(parents=True, exist_ok=True)
            os.rename(self.backup, source)
            self.backup = None
            if self.created_parent:
                try:
                    destination.parent.rmdir()
                except OSError:
                    pass                      # Preserve any unrelated entries created meanwhile.

    temporary = Path(tempfile.mkdtemp(prefix="strata-engine-link-", dir=repository / ".git"))
    stage = LinkStage()
    settled = False
    try:
        yield stage
        settled = True
    finally:
        if settled or stage.backup is None:
            shutil.rmtree(temporary)
        else:
            # A failed rollback must not discard the only remaining original link.
            print(f"Preserved engine link checkpoint for recovery: {temporary}", file=sys.stderr)


def migrate_layout(repository, *, reverse=False, reference_moves=()):
    repository = Path(repository).resolve()
    terminal = repository / "terminal"
    if not (terminal / "setup.py").is_file():
        normalize_sycl_configs(repository)
        return []
    source, destination = (terminal, repository) if reverse else (repository, terminal)
    enable_source(terminal)
    sys.path.insert(0, str(terminal))
    from strata_control import profiles

    pairs = runtime_pairs(repository, reverse=reverse)
    conflicts = [dst for src, dst in pairs if dst.exists() or dst.is_symlink()]
    if conflicts:
        raise RuntimeError("Cannot migrate managed runtime without replacing existing destinations: "
                           + ", ".join(map(str, conflicts)))
    with profiles.relocate_sources([], runtime_moves=pairs) as publish_profiles:
        return _migrate_payloads(repository, source, destination, pairs, publish_profiles,
                                 reverse=reverse, reference_moves=reference_moves)


def _migrate_payloads(repository, source, destination, pairs, publish_profiles, *, reverse, reference_moves):
    engine = source / "engine"
    originals = {src: src.read_bytes() for src, dst in pairs if src.is_file()
                 and (src.name.startswith("strata-") and src.suffix == ".json" or src.name.startswith("run-"))}
    paths = canonical_config_paths(repository,
            (path for runtime in (source, destination) for path in runtime.glob("strata-*.json")))
    originals.update((path, path.read_bytes()) for path in paths)
    configs = {path: config for path in paths if (config := _model_config(originals[path])) is not None}
    engine_paths = [((repository / "engine" / name, repository / name) if reverse
                     else (repository / name, repository / "engine" / name)) for name in ("metal", "sycl")]
    swaps = set(pairs + engine_paths)
    references = set(pairs) | set(reference_moves)
    swaps.update(reference_moves)
    swaps.update((source / name, destination / name) for name in TERMINAL_ENTRIES)
    if any(src.parent == engine for src, dst in pairs):
        swaps.add((engine, destination / "engine"))
    reference_rebase = rebaser(references) if references else lambda value: value
    rebase = rebaser(swaps)
    shell_rebase = shell_rebaser(swaps, rebase)

    def transform_config(config, path):
        base = path.parent
        managed = _managed_sycl_config(config, repository, base)
        independent = not managed and Path(str(config.get("exe", ""))).name == "strata-sycl.sh"
        old_cwd = _sycl_cwd(config, base)
        new_base = relocated_path(path, pairs).parent
        new_cwd = relocated_path(old_cwd, references)
        if not independent and old_cwd == source:
            new_cwd = destination

        def walk(value):
            if isinstance(value, dict):
                return {key: walk(item) for key, item in value.items()}
            if isinstance(value, list):
                return [walk(item) for item in value]
            return reference_rebase(value) if isinstance(value, str) else value

        rebased = walk(config)
        if config.get("cwd"):
            rebased["cwd"] = str(new_cwd)

        def reading_path(value, *, executable=False):
            if not isinstance(value, str) or not value or value.startswith("component:"):
                return value
            path = Path(value).expanduser()
            if executable and not path.is_absolute() and not os.path.dirname(value):
                return value                         # A bare executable is selected through PATH.
            lexical = Path(os.path.normpath(path if path.is_absolute() else old_cwd / path))
            mapped = relocated_path(lexical, references)
            if mapped == lexical:
                effective = lexical.resolve()
                projected = relocated_path(effective, references)
                if projected != effective:
                    mapped = projected
            if mapped == lexical and (path.is_absolute() or old_cwd == (new_cwd if config.get("cwd") else new_base)):
                return value
            return str(mapped) if path.is_absolute() else os.path.relpath(mapped, new_cwd if config.get("cwd") else new_base)

        rebased["tokenizer"] = reading_path(config.get("tokenizer"))
        if not managed:
            rebased["exe"] = reading_path(config.get("exe"), executable=True)
        if not managed and not independent:
            args = list(config.get("args", []))
            for index, flag in enumerate(config.get("args", [])[:-1]):
                if flag not in SYCL_PATH_FLAGS and flag not in ("--mmproj", "--model"):
                    continue
                value = args[index + 1]
                if flag == "--mtp" and str(value).isdigit():
                    continue
                path, separator, scale = value.rpartition(":") if flag == "--control-vector-scaled" else (value, "", "")
                if separator:
                    try:
                        float(scale)
                    except ValueError:
                        path, separator, scale = value, "", ""
                args[index + 1] = reading_path(path if separator else value) + separator + scale
            rebased["args"] = args
        # These native consumers resolve their file fields against the old config cwd.
        # Copy their other fields unchanged: descriptions and component names are not coordinates.
        for section, fields in (("vision", ("exe", "mmproj", "model")),
                                ("images", ("exe", "diffusion_model", "vae", "llm", "out_dir"))):
            original = config.get(section)
            if not isinstance(original, dict):
                continue
            native = dict(original)
            for key in fields:
                if key in original:
                    native[key] = reading_path(original[key], executable=key == "exe")
            if section == "images" and isinstance(original.get("args"), list):
                args = list(original["args"])
                for index, flag in enumerate(original["args"][:-1]):
                    if flag in ("--diffusion-model", "--vae", "--llm", "--prompt-file"):
                        # Image jobs have their own cwd, so read operands must be host-absolute.
                        value = reading_path(args[index + 1])
                        if isinstance(value, str) and value and not value.startswith("component:"):
                            value = str(Path(os.path.normpath((new_cwd if config.get("cwd") else new_base)
                                                             / Path(value).expanduser())))
                        args[index + 1] = value
                native["args"] = args
            rebased[section] = native
        if managed:
            mapped = sycl_config(config, source, destination, repository, reverse, rebase, base=base)
            rebased.update({key: mapped[key] for key in ("exe", "args", "env")})
        return rebased

    transformed = {}
    for src, config in configs.items():
        mapped = transform_config(config, src)
        if mapped != config:
            transformed[src] = (json.dumps(mapped, indent=2) + "\n").encode("utf-8")
    runtime_edits = []
    for src, after in transformed.items():
        runtime_edits.append((relocated_path(src, pairs), originals[src], after, None))
    for src, dst in pairs:
        if src in originals and src.suffix != ".json" and not src.is_symlink():
            text = originals[src].decode("utf-8", "surrogateescape")
            after = rebase_script(text, source, destination, shell_rebase).encode("utf-8", "surrogateescape")
            if after != originals[src]:
                runtime_edits.append((dst, originals[src], after, None))

    runtime_edits.extend((relocated, before, after, mode)
                         for entry, relocated, before, after, mode in
                         runtime_link_edits(repository, pairs, reference_moves=reference_moves))
    for src, dst in pairs:
        if src.name not in (".venv", ".python", "python") or src.is_symlink() or not src.is_dir():
            continue
        for entry in interpreter_entries(src):
            relocated = dst / entry.relative_to(src)
            if not entry.is_symlink() and entry.is_file():
                metadata = entry == src / "pyvenv.cfg" or (entry.parent.name in ("bin", "Scripts")
                           and entry.name.lower().startswith("activate"))
                if not metadata:
                    if entry.parent.name not in ("bin", "Scripts"):
                        continue
                    with entry.open("rb") as stream:
                        if stream.read(2) != b"#!":
                            continue
                before = entry.read_bytes()
                after = shell_rebase(before.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")
                if after != before:
                    runtime_edits.append((relocated, before, after, None))
    # Retarget file links before any writes through them; rollback restores bytes before links.
    runtime_edits.sort(key=lambda edit: edit[3] is None)
    moved = []
    edited = []
    with ExitStack() as snapshots:
        temporary_roots = {}
        approval = repository / ".git/strata-engine-rollback.json"
        approval_backup = None
        if approval.exists() or approval.is_symlink():
            temporary = Path(snapshots.enter_context(tempfile.TemporaryDirectory(prefix="strata-links-", dir=approval.parent)))
            approval_backup = temporary / "approval"
            os.link(approval, approval_backup, follow_symlinks=False)
        try:
            for src, dst in pairs:
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.rename(src, dst)
                moved.append((src, dst))
            for entry, before, after, mode in runtime_edits:
                backup = None
                if mode is not None:
                    anchor = entry.parent
                    if anchor not in temporary_roots:
                        temporary_roots[anchor] = Path(snapshots.enter_context(
                            tempfile.TemporaryDirectory(prefix=".strata-links-", dir=anchor)))
                    backup = temporary_roots[anchor] / str(len(edited))
                edited.append((entry, before, mode, backup, entry.stat() if mode is None else None))
                write_runtime(entry, after, mode, backup)
            publish_profiles()
            # A committed layout move retires old path identities; source rollback restores its snapshot.
            if moved:
                approval.unlink(missing_ok=True)
        except BaseException as error:
            rollback_errors = []

            def restore(action, *args):
                try:
                    action(*args)
                except BaseException as failure:
                    rollback_errors.append(failure)

            if approval_backup is not None and not approval.exists() and not approval.is_symlink():
                restore(os.replace, approval_backup, approval)
            for entry, before, mode, backup, info in reversed(edited):
                if mode is None:
                    restore(write_runtime, entry, before, None)
                    restore(lambda: os.utime(entry, ns=(info.st_atime_ns, info.st_mtime_ns)))
                elif backup is not None and backup.is_symlink():
                    restore(os.replace, backup, entry)
            # Backups inside a moved filesystem must disappear before their parents move back.
            restore(snapshots.close)
            for src, dst in reversed(moved):
                restore(os.rename, dst, src)
            detail = f"Managed runtime path migration failed: {error}"
            if rollback_errors:
                detail += "; runtime rollback errors: " + "; ".join(map(str, rollback_errors))
            raise RuntimeError(detail) from error
    return moved


class CMakeMetadataCheckpoint:
    """Hold original metadata by same-mount renames, even while its build parent moves."""

    def __init__(self):
        self.backups = []
        self.accepted = False

    def invalidate(self, repository):
        repository = Path(repository).resolve()
        for name in (*TERMINAL_BUILDS, *ENGINE_BUILDS):
            build = repository / name
            if not build.resolve().is_relative_to(repository):
                continue                         # A managed link does not own external build data.
            cache = build / "CMakeCache.txt"
            try:
                text = cache.read_text(encoding="utf-8", errors="surrogateescape")
            except FileNotFoundError:
                continue
            entries = dict(re.findall(r"^(CMAKE_(?:CACHEFILE_DIR|HOME_DIRECTORY)):[^=]*=(.*)$", text, re.M))
            home = entries.get("CMAKE_HOME_DIRECTORY")
            incompatible = (entries.get("CMAKE_CACHEFILE_DIR")
                            and Path(entries["CMAKE_CACHEFILE_DIR"]).resolve() != build.resolve())
            if home:
                source = Path(home).resolve()
                incompatible = incompatible or source.is_relative_to(repository / "terminal") or source == repository / "engine" \
                    or source.is_relative_to(repository / "engine" / "metal") or source.is_relative_to(repository / "engine" / "sycl")
            if not incompatible:
                continue
            parent_fd = os.open(build, os.O_RDONLY)
            try:
                temporary = Path(tempfile.mkdtemp(prefix=".strata-cmake-", dir=build))
                backup_fd = os.open(temporary, os.O_RDONLY)
            except BaseException:
                os.close(parent_fd)
                raise
            names = []
            self.backups.append((parent_fd, backup_fd, temporary, names))
            for entry in ("CMakeCache.txt", "CMakeFiles"):
                try:
                    os.rename(entry, entry, src_dir_fd=parent_fd, dst_dir_fd=backup_fd)
                except FileNotFoundError:
                    continue
                names.append(entry)

    def restore(self):
        errors = []
        for parent_fd, backup_fd, temporary, names in reversed(self.backups):
            for name in reversed(names[:]):
                try:
                    os.rename(name, name, src_dir_fd=backup_fd, dst_dir_fd=parent_fd)
                except OSError as error:
                    errors.append(error)
                    print(f"Cannot restore CMake metadata; backup recoverable at {temporary / name}: {error}",
                          file=sys.stderr)
                else:
                    names.remove(name)
        if errors:
            raise RuntimeError("Cannot restore CMake metadata: " + "; ".join(map(str, errors))) from errors[0]

    def accept(self):
        self.accepted = True

    def close(self):
        try:
            if not self.accepted:
                self.restore()
            for parent_fd, backup_fd, temporary, names in self.backups:
                for name in names[:]:
                    try:
                        info = os.stat(name, dir_fd=backup_fd, follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            shutil.rmtree(name, dir_fd=backup_fd)
                        else:
                            os.unlink(name, dir_fd=backup_fd)
                    except OSError as error:
                        print(f"CMake metadata cleanup incomplete; backup recoverable at {temporary / name}: {error}",
                              file=sys.stderr)
                    else:
                        names.remove(name)
                if not names:
                    try:
                        os.rmdir(temporary.name, dir_fd=parent_fd)
                    except OSError as error:
                        print(f"CMake metadata cleanup incomplete; backup recoverable at {temporary}: {error}",
                              file=sys.stderr)
        finally:
            for parent_fd, backup_fd, temporary, names in self.backups:
                os.close(backup_fd)
                os.close(parent_fd)
            self.backups.clear()


@contextmanager
def cmake_metadata_checkpoint():
    checkpoint = CMakeMetadataCheckpoint()
    try:
        yield checkpoint
    finally:
        checkpoint.close()


def invalidate_cmake_metadata(repository):
    """Retire incompatible roots only for an already accepted flat layout."""
    with cmake_metadata_checkpoint() as checkpoint:
        checkpoint.invalidate(repository)
        checkpoint.accept()
