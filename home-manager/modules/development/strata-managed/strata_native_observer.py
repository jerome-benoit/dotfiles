"""Protect native pins without modifying their parser or checkout functions.

Both supported native CLIs dispatch through ``cli._run``. Their logs entry and
Textual run call are the short-read boundary: imports and the UI constructor have
finished, but no long polling/event loop has begun. A temporary Python profile
hook observes those calls; it never substitutes a checkout function or module.
An error before readiness leaves imports protected until exit closes the reader.
Active dispatch retains acquisition through native preparation and service readiness,
including Runner setup children. A scoped spawn adapter hands only managed setup
the lease; the real Runner return releases it before any steady-state monitor.
"""

import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

def acquisition_action(args):
    """Classify acquisition after the native parser, respecting launch early returns."""
    if args.command in {"install", "update"}:
        return True
    if args.command == "components":
        return getattr(args, "components_command", None) in {
            "update", "rollback", "install-file", "use", "remove"}
    return args.command == "launch" and not any(
        getattr(args, name, False) for name in
        ("list_presets", "delete_preset", "stop", "status", "plan"))



class _Parsed(BaseException):
    def __init__(self, args):
        self.args_namespace = args


def _entry(root, entry, args):
    sys.path.insert(0, str(root))
    sys.argv = [str(root / entry), *args]
    return runpy.run_path(str(root / entry), run_name="__main__")


def _native_call(frame, module, name, filename):
    loaded = sys.modules.get(module)
    return (frame is not None and frame.f_code.co_filename == filename and loaded is not None
            and loaded.__file__ == filename and frame.f_globals is loaded.__dict__
            and frame.f_code is getattr(getattr(loaded, name, None), "__code__", None))


def probe(root, entry, args):
    """Stop at native dispatch, after that pin's real parser/help/version handling."""
    cli = str(root / "strata_cli/cli.py")

    def parsed(frame, event, arg):
        if event == "call" and _native_call(frame, "strata_cli.cli", "_run", cli):
            raise _Parsed(frame.f_locals["a"])

    previous = sys.getprofile()
    sys.setprofile(parsed)
    try:
        _entry(root, entry, args)
        raise RuntimeError("Native Strata entry returned without reaching its protected parser dispatch")
    except _Parsed as result:
        return result.args_namespace
    finally:
        sys.setprofile(previous)


def run(root, entry, args):
    """Keep the inherited reader through native initialization, not its long loop."""
    descriptor = int(os.environ.pop("STRATA_SOURCE_LOCK_FD"))
    os.set_inheritable(descriptor, False)
    lease = os.fdopen(descriptor, "a")
    commands = str(root / "strata_cli/monitor_commands.py")
    logs = str(root / "strata_cli/logs.py")
    monitor_file = str(root / "strata_cli/monitor.py")
    previous = sys.getprofile()

    def ready(frame, event, arg):
        if event != "call" or frame.f_code.co_name != "run":
            return
        if _native_call(frame, "strata_cli.logs", "run", logs) and frame.f_locals.get("follow"):
            importlib.import_module("strata_control.longpath")
        elif _native_call(frame.f_back, "strata_cli.monitor_commands", "run", commands):
            app = frame.f_locals.get("self")
            monitor = sys.modules.get("strata_cli.monitor")
            if (monitor is None or monitor.__file__ != monitor_file
                    or monitor.MonitorApp not in type(app).__mro__
                    or frame.f_code is not getattr(getattr(type(app), "run", None), "__code__", None)):
                return
            modules = ["strata_cli.consoleinfo", "strata_cli.overview"]
            if type(frame.f_locals["self"]).__module__ == "strata_cli.launch.monitor_ext":
                modules += ["strata_control.engine_update", "strata_control.discovery", "strata_control.feed_models",
                            "strata_cli.update_cmd", "strata_control.runtime", "strata_control.cfg_paths",
                            "strata_control.signing", "strata_control.engine_component", "strata_control.updater",
                            "strata_control.retired"]
            for module in modules:
                importlib.import_module(module)
        else:
            return
        # Closing this reader must not unlock other processes sharing its file description.
        lease.close()
        sys.setprofile(previous)

    sys.setprofile(ready)
    try:
        _entry(root, entry, args)
    finally:
        sys.setprofile(previous)
        lease.close()


def run_active(root, entry, args):
    """Keep native mutators and their managed installer under the same acquisition lease.

    Adapt only managed setup and runtime-module spawns at their explicit boundaries.
    The stable entries restore native argv; no checkout function or parser is replaced.
    pass_fds transfers the open file description even though it is non-inheritable
    elsewhere. The child keeps it until exit, including after its CLI parent dies.
    Independent installers keep their native command and unmanaged environment.
    """
    import strata_managed_state as managed_state

    descriptor = int(os.environ["STRATA_WORKSPACE_LOCK_FD"])
    os.set_inheritable(descriptor, False)
    lease = os.fdopen(descriptor, "a")
    original = subprocess.Popen
    held = os.fstat(descriptor)
    state = Path(json.loads(os.environ["STRATA_WORKSPACE_CONTEXT"])["state"])
    expected = (state / ".source.lock").stat()
    if (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
        raise RuntimeError("Native acquisition descriptor does not belong to this workspace")
    installer = (root / "setup.py").resolve()
    helper = os.environ["STRATA_WORKSPACE_HELPER"]

    class ScopedNativeInstaller(original):
        def __init__(self, args, *positional, **options):
            command = args
            if (isinstance(command, (list, tuple)) and len(command) >= 2
                    and Path(command[1]).name == "setup.py"):
                cwd = Path(options.get("cwd") or os.getcwd())
                target = Path(command[1])
                target = (cwd / target).resolve() if not target.is_absolute() else target.resolve()
                if target == installer:
                    options["pass_fds"] = tuple(dict.fromkeys((*options.get("pass_fds", ()), descriptor)))
                    options["env"] = dict(options.get("env") or os.environ,
                                          STRATA_WORKSPACE_LOCK_FD=str(descriptor))
                    command = [command[0], helper, "--native-setup", str(root), *command[2:]]
                else:
                    options["env"] = managed_state.external_environment(options.get("env") or os.environ)
            if (isinstance(command, (list, tuple)) and list(command[1:3]) == ["-m", "strata_control.runtime"]
                    and "--host" in command[3:]
                    and Path(options.get("cwd") or os.getcwd()).resolve() == root):
                with _source_reader(state) as reader:
                    command, options = _module_spawn(state, helper, command, options, reader)
                    super().__init__(command, *positional, **options)
            else:
                super().__init__(command, *positional, **options)

    import threading
    previous = sys.getprofile()
    previous_thread = threading.getprofile()
    runner_file = str(root / "strata_cli/launch/runner.py")

    def prepared(frame, event, result):
        module = sys.modules.get("strata_cli.launch.runner")
        runner = getattr(module, "Runner", None)
        if (event == "return" and result is not None and runner is not None
                and frame.f_code.co_filename == runner_file
                and frame.f_globals is module.__dict__
                and frame.f_code is runner.run.__code__):
            # Runner returns only after preparation and, when requested, service
            # readiness. Preload the launch monitor before dropping protection.
            for name in ("strata_cli.launch.monitor_ext", "strata_cli.consoleinfo",
                         "strata_cli.overview"):
                importlib.import_module(name)
            lease.close()
            for key in ("STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER",
                        "STRATA_WORKSPACE_CONTEXT", "STRATA_ACQUISITION_BOOTSTRAP"):
                os.environ.pop(key, None)
            subprocess.Popen = original

    subprocess.Popen = ScopedNativeInstaller
    sys.setprofile(prepared)
    threading.setprofile(prepared)
    try:
        _entry(root, entry, args)
    finally:
        sys.setprofile(previous)
        threading.setprofile(previous_thread)
        subprocess.Popen = original
        lease.close()


def _source_reader(state):
    import fcntl
    reader = (state / ".source-publication.lock").open("a")
    try:
        fcntl.flock(reader, fcntl.LOCK_SH)
    except BaseException:
        reader.close()
        raise
    return reader


def _module_spawn(state, helper, command, options, reader):
    """Select the published module endpoint while its source is read-leased."""
    repository = (state / "source").resolve()
    root = repository / "terminal" if (repository / "terminal/strata.py").is_file() else repository
    python = command[0]
    if Path(python).absolute().is_relative_to(repository):
        # A surviving host may still name the previous flat/split interpreter.
        # Follow the same bundled/private interpreter convention as workspace.
        bundled = root / "python/bin/python3"
        python = bundled if os.access(bundled, os.X_OK) else root / ".venv/bin/python"
        if not os.access(python, os.X_OK):
            raise RuntimeError("Published native runtime interpreter is unavailable")
        python = str(python)
    options = dict(options)
    options["cwd"] = str(root)
    options["pass_fds"] = tuple(dict.fromkeys((*options.get("pass_fds", ()), reader.fileno())))
    options["env"] = dict(options.get("env") or os.environ,
                          STRATA_SOURCE_LOCK_FD=str(reader.fileno()),
                          STRATA_NATIVE_SOURCE_STATE=str(state),
                          STRATA_NATIVE_MODULE_HELPER=helper)
    for key in ("STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER", "STRATA_WORKSPACE_CONTEXT",
                "STRATA_ACQUISITION_BOOTSTRAP"):
        options["env"].pop(key, None)
    return [python, helper, "--native-module", str(root), command[2], *command[3:]], options


def run_module(root, module_name, args):
    """Enter actual native host/server modules with a reader bounded by readiness."""
    if module_name not in {"strata_control.runtime", "serve.server"}:
        raise RuntimeError("Unsupported native managed module")
    state = Path(os.environ["STRATA_NATIVE_SOURCE_STATE"])
    helper = os.environ["STRATA_NATIVE_MODULE_HELPER"]
    descriptor = int(os.environ.pop("STRATA_SOURCE_LOCK_FD"))
    os.set_inheritable(descriptor, False)
    reader = os.fdopen(descriptor, "a")
    expected = (state / ".source-publication.lock").stat()
    held = os.fstat(descriptor)
    if (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
        raise RuntimeError("Native module reader does not belong to this workspace")
    import threading

    previous_thread = threading.getprofile()
    reader_mutex = threading.Lock()
    thread_readers = {}
    finished = False

    def acquire_reader(name):
        identity = threading.get_ident()
        with reader_mutex:
            if finished or identity in thread_readers:
                return
            if name == "_startup" and not reader.closed:
                thread_readers[identity] = reader
                return
        # Do not hold the bookkeeping mutex while waiting for publication: a
        # different worker may need it to release the reader blocking that writer.
        acquired = _source_reader(state)
        with reader_mutex:
            if finished:
                acquired.close()
            else:
                thread_readers[identity] = acquired

    def release_reader():
        with reader_mutex:
            acquired = thread_readers.pop(threading.get_ident(), None)
        if acquired is not None:
            acquired.close()

    previous = sys.getprofile()
    profile_owner = threading.get_ident()
    original = subprocess.Popen
    filename = str(root / (module_name.replace(".", "/") + ".py"))

    def boundary(frame, event, result):
        inherited_profile = previous if threading.get_ident() == profile_owner else previous_thread
        if inherited_profile is not None:
            inherited_profile(frame, event, result)
        with reader_mutex:
            done = finished
        if done:
            sys.setprofile(previous_thread)
            return
        if module_name == "serve.server" and event == "return":
            ready = sys.modules.get("serve.ready")
            publish = getattr(ready, "publish", None)
            if (ready is not None and getattr(ready, "__file__", None) == str(root / "serve/ready.py")
                    and frame.f_code is getattr(publish, "__code__", None)
                    and frame.f_globals is ready.__dict__):
                # Publication follows all server initialization. Failed publication
                # retains protection until exit; it is not service readiness.
                path, payload = frame.f_locals["path"], frame.f_locals["payload"]
                try:
                    published = json.loads(path.read_text())
                except (OSError, ValueError):
                    return
                if published == payload:
                    with reader_mutex:
                        reader.close()
                return
        if frame.f_code.co_filename != filename or frame.f_globals.get("__name__") != "__main__":
            return
        if module_name == "strata_control.runtime":
            host = frame.f_globals.get("Host")
            name = frame.f_code.co_name
            if host is None or frame.f_code is not getattr(getattr(host, name, None), "__code__", None):
                return
            if event == "call" and name in {"_startup", "_restart", "_plan_restart", "_launch"}:
                acquire_reader(name)
            elif (event == "return" and name == "_wait_ready"
                  and isinstance(result, dict) and result.get("state") == "ready"):
                release_reader()
            elif event == "return" and name in {"_startup", "_restart", "_plan_restart"}:
                release_reader()

    class NativeServer(original):
        def __init__(self, args, *positional, **options):
            if (isinstance(args, (list, tuple)) and list(args[1:3]) == ["-m", "serve.server"]
                    and Path(options.get("cwd") or os.getcwd()).resolve() == root):
                with _source_reader(state) as child_reader:
                    command, options = _module_spawn(state, helper, args, options, child_reader)
                    super().__init__(command, *positional, **options)
            else:
                super().__init__(args, *positional, **options)

    if module_name == "strata_control.runtime":
        subprocess.Popen = NativeServer
    sys.path.insert(0, str(root))
    sys.argv = [module_name, *args]
    sys.setprofile(boundary)
    threading.setprofile(boundary)
    try:
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
    finally:
        sys.setprofile(previous)
        threading.setprofile(previous_thread)
        with reader_mutex:
            finished = True
            remaining = tuple(thread_readers.values())
            thread_readers.clear()
        for acquired in remaining:
            acquired.close()
        subprocess.Popen = original
        reader.close()
