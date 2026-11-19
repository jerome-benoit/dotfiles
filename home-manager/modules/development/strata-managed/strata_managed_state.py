"""Source-independent state operations for managed Strata checkouts.

Managed profile, path and inventory consumers are selected only inside the managed
source package; independent installations retain every native module/API.
Payload moves are renames. Only configs, launch scripts and interpreter metadata
are edited in place, with exact-byte restoration on failure.
"""

from contextlib import contextmanager
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
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
SYCL_PATH_FLAGS = {"--pack", "--native", "--ple-gguf", "--expert-profile", "--mtp", "--control-vector-scaled"}


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


def external_environment(environ):
    """Remove only this managed bootstrap when handing execution to an independent installation."""
    env = dict(environ)
    for key in ("STRATA_MANAGED_SOURCE", "STRATA_PROFILE_NAMESPACE_FD", "STRATA_WORKSPACE_HELPER",
                "STRATA_WORKSPACE_CONTEXT", "STRATA_WORKSPACE_LOCK_FD", "STRATA_SOURCE_LOCK_FD",
                "STRATA_BOOTSTRAP_ONLY", "STRATA_RUNTIME_READY", "STRATA_LAUNCH_RUNTIME_READY"):
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


def sycl_config(config, source, destination, repository, reverse, rebase):
    """Publish a stable transport from the actual old wrapper's mount/cwd, never a /work text swap."""
    wrapper = Path(str(config.get("exe", "")))
    if wrapper.name != "strata-sycl.sh":
        return config
    previous = dict(config.get("env") or {})
    transport_keys = {"STRATA_SYCL_ROOT", "STRATA_SYCL_CWD", "STRATA_SYCL_BIN", "STRATA_SYCL_HERE"}
    environment = {key: (value if key in transport_keys else rebase(value) if isinstance(value, str) else value)
                   for key, value in previous.items()}
    moving = source != destination
    old_here = (Path(previous["STRATA_SYCL_HERE"]) if previous.get("STRATA_SYCL_HERE")
                else wrapper.resolve().parents[2])
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
    old_cwd = Path(config.get("cwd") or source)
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


def normalize_sycl_config(config, repository):
    repository = Path(repository).resolve()
    wrapper = Path(str(config.get("exe", "")))
    if wrapper.name != "strata-sycl.sh":
        return config
    previous_here = (config.get("env") or {}).get("STRATA_SYCL_HERE")
    if not wrapper.resolve().is_relative_to(repository) and (not previous_here or Path(previous_here) not in (repository, repository / "engine")):
        return config                          # An independent installation retains its own transport.
    runtime = repository / "terminal" if (repository / "terminal/setup.py").is_file() else repository
    return sycl_config(config, runtime, runtime, repository, False, lambda value: value)


def normalize_sycl_configs(repository):
    repository = Path(repository).resolve()
    runtime = repository / "terminal" if (repository / "terminal/setup.py").is_file() else repository
    originals = {}
    try:
        for path in sorted(runtime.glob("strata-*.json")):
            before = path.read_bytes()
            try:
                config = json.loads(before.decode("utf-8-sig"))
            except (UnicodeError, ValueError):
                continue                       # Native dispatch owns malformed/unselected config errors.
            if not isinstance(config, dict):
                continue
            mapped = normalize_sycl_config(config, repository)
            if mapped != config:
                originals[path] = before
                path.write_bytes((json.dumps(mapped, indent=2) + "\n").encode("utf-8"))
    except BaseException:
        for path, before in originals.items():
            path.write_bytes(before)
        raise


def interpreter_entries(root):
    def walk_error(error):
        raise error

    yield root
    if not root.is_symlink():
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            for name in dirs + files:
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
def layout_checkpoint(repository, *, enabled=True):
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
    with namespace.open("a+b") as lock, tempfile.TemporaryDirectory(prefix="strata-layout-", dir=repository / ".git") as temporary:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before_fd = os.environ.get("STRATA_PROFILE_NAMESPACE_FD")
        os.environ["STRATA_PROFILE_NAMESPACE_FD"] = str(lock.fileno())
        try:
            paths = {path for path in directory.glob("*.json") if path.is_file() and not path.is_symlink()}
            metadata = directory / ".source-relocations.json"
            if metadata.exists():
                paths.add(metadata)
            metadata_existed = metadata.exists()
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
            originals = []
            for index, path in enumerate(sorted(paths)):
                backup = Path(temporary) / str(index)
                info = path.lstat()
                payload = None if path.is_symlink() else path.read_bytes()
                os.link(path, backup, follow_symlinks=False)
                originals.append((path, backup, payload, info.st_mode))

            def restore():
                for path, backup, payload, mode in originals:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.is_symlink() or not path.exists() or path.lstat().st_ino != backup.lstat().st_ino:
                        os.replace(backup, path)
                    if payload is not None:
                        if path.read_bytes() != payload:
                            path.write_bytes(payload)
                        os.chmod(path, mode)
                if not metadata_existed:
                    metadata.unlink(missing_ok=True)
                for path in set((directory / ".history").glob("*/*.json")) - history:
                    path.unlink()

            yield restore
        finally:
            if before_fd is None:
                os.environ.pop("STRATA_PROFILE_NAMESPACE_FD", None)
            else:
                os.environ["STRATA_PROFILE_NAMESPACE_FD"] = before_fd


def migrate_layout(repository, *, reverse=False):
    repository = Path(repository).resolve()
    terminal = repository / "terminal"
    if not (terminal / "setup.py").is_file():
        return []
    source, destination = (terminal, repository) if reverse else (repository, terminal)
    enable_source(terminal)
    sys.path.insert(0, str(terminal))
    from strata_control import profiles

    pairs = [(path, destination / path.name) for pattern in LAYOUT_FILES
             for path in sorted(source.glob(pattern)) if path.is_file()]
    pairs += [(source / name, destination / name) for name in (*LAYOUT_DIRS, *TERMINAL_BUILDS)
              if (source / name).is_dir() or (source / name).is_symlink()]
    engine = source / "engine"
    if engine.is_dir():
        pairs += [(path, destination / "engine" / path.name) for path in sorted(engine.iterdir())
                  if path.name not in ENGINE_SOURCE and not path.name.startswith("build")]
    pairs += [((repository / "engine" / name, repository / name) if reverse
               else (repository / name, repository / "engine" / name)) for name in ENGINE_BUILDS
              if ((repository / "engine" / name) if reverse else (repository / name)).is_dir()]
    conflicts = [dst for src, dst in pairs if dst.exists() or dst.is_symlink()]
    if conflicts:
        raise RuntimeError("Cannot migrate managed runtime without replacing existing destinations: "
                           + ", ".join(map(str, conflicts)))
    if not pairs:
        return []
    originals = {src: src.read_bytes() for src, dst in pairs if src.is_file()
                 and (src.name.startswith("strata-") and src.suffix == ".json" or src.name.startswith("run-"))}
    configs = {src: json.loads(data.decode("utf-8-sig")) for src, data in originals.items() if src.suffix == ".json"}
    config_moves = [(src, dst) for src, dst in pairs if src in configs]
    engine_paths = [((repository / "engine" / name, repository / name) if reverse
                     else (repository / name, repository / "engine" / name)) for name in ("metal", "sycl")]
    swaps = set(pairs + engine_paths)
    swaps.update((source / name, destination / name) for name in TERMINAL_ENTRIES)
    if any(src.parent == engine for src, dst in pairs):
        swaps.add((engine, destination / "engine"))
    rebase = rebaser(swaps)
    shell_rebase = shell_rebaser(swaps, rebase)

    def walk(value):
        if isinstance(value, dict):
            out = {key: walk(item) for key, item in value.items()}
            if value.get("cwd") == str(source):
                out["cwd"] = str(destination)
            return out
        return rebase(value) if isinstance(value, str) else [walk(item) for item in value] if isinstance(value, list) else value

    transformed = {}
    for src, config in configs.items():
        mapped = sycl_config(config, source, destination, repository, reverse, rebase)
        rebased = walk(config)
        if mapped is not config:
            rebased.update({key: mapped[key] for key in ("exe", "args", "env")})
        transformed[src] = (json.dumps(rebased, indent=2) + "\n").encode("utf-8")
    runtime_edits = []
    for src, dst in pairs:
        if src.name not in (".venv", ".python", "python"):
            continue
        for entry in interpreter_entries(src):
            relocated = dst / entry.relative_to(src)
            if entry.is_symlink():
                before = os.readlink(entry)
                after = rebase(before) if os.path.isabs(before) else before
                if after != before:
                    runtime_edits.append((relocated, before, after, entry.lstat().st_mode))
            elif entry.is_file():
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
    moved = []
    edited = []
    with tempfile.TemporaryDirectory(prefix="strata-links-", dir=repository / ".git") as temporary, \
            profiles.relocate_sources(config_moves) as publish_profiles:
        try:
            for src, dst in pairs:
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.rename(src, dst)
                moved.append((src, dst))
            for src, dst in moved:
                if src in transformed:
                    dst.write_bytes(transformed[src])
                elif src in originals:
                    text = originals[src].decode("utf-8", "surrogateescape")
                    dst.write_bytes(rebase_script(text, source, destination, shell_rebase).encode("utf-8", "surrogateescape"))
            for entry, before, after, mode in runtime_edits:
                backup = Path(temporary) / str(len(edited)) if mode is not None else None
                edited.append((entry, before, mode, backup))
                write_runtime(entry, after, mode, backup)
            publish_profiles()
            # A committed layout move retires old path identities; source rollback restores its snapshot.
            (repository / ".git/strata-engine-rollback.json").unlink(missing_ok=True)
        except BaseException as error:
            for entry, before, mode, backup in reversed(edited):
                if mode is None:
                    write_runtime(entry, before, None)
                elif backup.is_symlink():
                    os.replace(backup, entry)
            for src, dst in moved:
                if src in originals and dst.read_bytes() != originals[src]:
                    dst.write_bytes(originals[src])
            for src, dst in reversed(moved):
                os.rename(dst, src)
            raise RuntimeError(f"Managed runtime path migration failed: {error}") from error
    return moved


def invalidate_cmake_metadata(repository):
    """An old generator-only guard cannot consume relocated cache roots; keep all payloads."""
    repository = Path(repository).resolve()
    builds = {repository / name for name in (*TERMINAL_BUILDS, *ENGINE_BUILDS)}
    for build in builds:
        cache = build / "CMakeCache.txt"
        try:
            text = cache.read_text(encoding="utf-8", errors="surrogateescape")
        except FileNotFoundError:
            continue
        entries = dict(re.findall(r"^(CMAKE_(?:CACHEFILE_DIR|HOME_DIRECTORY)):[^=]*=(.*)$", text, re.M))
        home = entries.get("CMAKE_HOME_DIRECTORY")
        incompatible = (entries.get("CMAKE_CACHEFILE_DIR") and Path(entries["CMAKE_CACHEFILE_DIR"]).resolve() != build)
        if home:
            source = Path(home).resolve()
            incompatible = incompatible or source.is_relative_to(repository / "terminal") or source == repository / "engine" \
                or source.is_relative_to(repository / "engine" / "metal") or source.is_relative_to(repository / "engine" / "sycl")
        if incompatible:
            cache.unlink()
            shutil.rmtree(build / "CMakeFiles", ignore_errors=True)
