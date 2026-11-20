"""Protect native pins without modifying their parser or checkout functions.

Both supported native CLIs dispatch through ``cli._run``. Temporary, thread-scoped
profile hooks observe their real readiness calls without replacing checkout code.
Logs and screens release after imports/UI construction; foreground servers release
after their actual ready publication or initialized steady-state loop entry.
Their deferred service helpers are loaded before either boundary. Native runtime
producers hand a separate reader to the Host, which protects its startup workers
and server descendants independently of a wait-zero producer's lifetime.
Active dispatch and monitor update workers retain acquisition only through their
own native preparation, never in the read-only Host they start.
"""

import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time


# These imports are deferred by the pinned Service's SAVE, load, telemetry and
# exit paths. Optional Rich/Textual clients are deliberately not server helpers.
_SERVER_DEFERRED_MODULES = (
    "serve.session_save_retry", "serve.loader_diag", "serve.cache_drop",
    "serve.telemetry", "strata_control.own_path_fit", "strata_control.presets",
)


def _preload_server(root):
    for name in _SERVER_DEFERRED_MODULES:
        importlib.import_module(name)
    if (root / "serve/server_parts/engines.py").is_file():
        # Only the split pin's engine diagnostics defer this Linux helper.
        importlib.import_module("serve.oomd_pacer")


def _server_ready(root, frame, event, result):
    """One native readiness rule for CLI foreground and module server entries."""
    ready = sys.modules.get("serve.ready")
    if (event == "return" and ready is not None
            and getattr(ready, "__file__", None) == str(root / "serve/ready.py")
            and frame.f_globals is ready.__dict__
            and frame.f_code is getattr(getattr(ready, "publish", None), "__code__", None)):
        path, payload = frame.f_locals["path"], frame.f_locals["payload"]
        try:
            return json.loads(path.read_text()) == payload
        except (OSError, ValueError):
            return False
    # Human/quiet foreground mode has no file or lifecycle callback. Both pins
    # enter this sole _main sleep only after binding HTTP and initializing svc.
    # A requested file must succeed above; never turn failed publication into ready.
    return (event == "c_call" and result is time.sleep
            and frame.f_code.co_filename == str(root / "serve/server.py")
            and frame.f_code is getattr(frame.f_globals.get("_main"), "__code__", None)
            and frame.f_locals.get("ready_path") is None
            and frame.f_locals.get("httpd") is not None
            and frame.f_locals.get("svc") is not None)

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


class _MonitorMutation:
    """Own update leases at native thread/flow boundaries, never patch native methods."""

    def __init__(self, root):
        import threading
        self.context = os.environ.get("STRATA_WORKSPACE_CONTEXT")
        self.helper = os.environ.get("STRATA_WORKSPACE_HELPER")
        self.thread = threading.Thread
        self.process = subprocess.Popen
        self.local = threading.local()
        owner = self

        class WorkerThread(owner.thread):
            def run(self):
                module = sys.modules.get("strata_cli.launch.monitor_ext")
                worker = getattr(getattr(module, "LaunchMonitor", None), "_update_worker", None)
                if (owner.context is None or getattr(self._target, "__func__", None) is not worker
                        or worker.__code__.co_filename != str(root / "strata_cli/launch/monitor_ext.py")):
                    return super().run()
                previous = sys.getprofile()

                def entering(frame, event, result):
                    if (event == "call" and _native_call(frame, "strata_control.engine_update", "run_flow",
                            str(root / "strata_control/engine_update.py"))
                            and frame.f_back.f_code is worker.__code__):
                        import fcntl
                        state = Path(json.loads(owner.context)["state"])
                        lease = (state / ".source.lock").open("a")
                        try:
                            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            lease.close()
                            raise RuntimeError("Workspace is busy; retry the engine update after the current operation finishes")
                        owner.local.lease = lease
                        os.set_inheritable(lease.fileno(), False)
                    if previous is not None:
                        previous(frame, event, result)

                sys.setprofile(entering)
                try:
                    return super().run()
                finally:
                    sys.setprofile(previous)
                    lease = getattr(owner.local, "lease", None)
                    if lease is not None:
                        lease.close()
                        del owner.local.lease

        class WorkerProcess(owner.process):
            def __init__(self, args, *positional, **options):
                import strata_managed_state as managed_state
                lease = getattr(owner.local, "lease", None)
                command = args
                if lease is not None:
                    fd = lease.fileno()
                    held = os.fstat(fd)
                    state = Path(json.loads(owner.context)["state"])
                    expected = (state / ".source.lock").stat()
                    if (held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino):
                        raise RuntimeError("Native update descriptor does not belong to this workspace")
                    env = dict(options.get("env") or os.environ)
                    env.update(STRATA_WORKSPACE_LOCK_FD=str(fd), STRATA_WORKSPACE_CONTEXT=owner.context,
                               STRATA_WORKSPACE_HELPER=owner.helper,
                               STRATA_ACQUISITION_BOOTSTRAP=f"{held.st_dev}:{held.st_ino}")
                    independent = False
                    if isinstance(command, (list, tuple)) and len(command) >= 2 and Path(command[1]).name == "setup.py":
                        target = (Path(options.get("cwd") or os.getcwd()) / command[1]).resolve()
                        independent = target != (root / "setup.py").resolve()
                        if not independent:
                            command = [command[0], owner.helper, "--native-setup", str(root), *command[2:]]
                    if independent:
                        options["env"] = managed_state.external_environment(env)
                    elif env.get("STRATA_NO_ACQUIRE") != "1":
                        options["env"] = managed_state.source_environment(env, root)
                        options["pass_fds"] = tuple(dict.fromkeys((*options.get("pass_fds", ()), fd)))
                    if (isinstance(command, (list, tuple)) and list(command[1:3]) == ["-m", "strata_control.runtime"]
                            and "--host" in command[3:] and Path(options.get("cwd") or os.getcwd()).resolve() == root):
                        with _source_reader(state) as reader:
                            command, options = _module_spawn(state, owner.helper, command, options, reader)
                            super().__init__(command, *positional, **options)
                        return
                super().__init__(command, *positional, **options)

        self.managed_thread = WorkerThread
        self.managed_process = WorkerProcess

    def install(self):
        import threading
        threading.Thread = self.managed_thread
        subprocess.Popen = self.managed_process

    def close(self):
        import threading
        if threading.Thread is self.managed_thread:
            threading.Thread = self.thread
        if subprocess.Popen is self.managed_process:
            subprocess.Popen = self.process


def run(root, entry, args):
    """Keep the inherited reader through native initialization, not its long loop."""
    descriptor = int(os.environ.pop("STRATA_SOURCE_LOCK_FD"))
    os.set_inheritable(descriptor, False)
    lease = os.fdopen(descriptor, "a")
    commands = str(root / "strata_cli/monitor_commands.py")
    logs = str(root / "strata_cli/logs.py")
    monitor_file = str(root / "strata_cli/monitor.py")
    previous = sys.getprofile()
    original = subprocess.Popen
    state = os.environ.get("STRATA_NATIVE_SOURCE_STATE")
    helper = os.environ.get("STRATA_NATIVE_MODULE_HELPER")

    class NativeHost(original):
        def __init__(self, args, *positional, **options):
            if (state is not None and helper is not None
                    and isinstance(args, (list, tuple))
                    and list(args[1:3]) == ["-m", "strata_control.runtime"]
                    and "--host" in args[3:]
                    and Path(options.get("cwd") or os.getcwd()).resolve() == root):
                with _source_reader(Path(state)) as child_reader:
                    command, options = _module_spawn(Path(state), helper, args, options, child_reader)
                    super().__init__(command, *positional, **options)
            else:
                super().__init__(args, *positional, **options)

    subprocess.Popen = NativeHost
    mutation = _MonitorMutation(root)

    def ready(frame, event, arg):
        if previous is not None:
            previous(frame, event, arg)
        if not lease.closed and _server_ready(root, frame, event, arg):
            _preload_server(root)
            lease.close()
            sys.setprofile(previous)
            return
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
        mutation.install()
        sys.setprofile(previous)

    sys.setprofile(ready)
    try:
        _entry(root, entry, args)
    finally:
        sys.setprofile(previous)
        lease.close()
        mutation.close()
        subprocess.Popen = original


def run_active(root, entry, args):
    """Keep native mutators and their managed installer under the same acquisition lease.

    Adapt only managed setup and runtime-module spawns at their explicit boundaries.
    The stable entries restore native argv; no checkout function or parser is replaced.
    pass_fds transfers the open file description without global inheritability.
    A true CLI install transfers ownership after spawn; Runner keeps its lease
    through its remaining preparation. Independent installers stay unmanaged.
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
    cli_file = str(root / "strata_cli/cli.py")

    def release_acquisition():
        lease.close()
        for key in ("STRATA_WORKSPACE_LOCK_FD", "STRATA_WORKSPACE_HELPER",
                    "STRATA_WORKSPACE_CONTEXT", "STRATA_ACQUISITION_BOOTSTRAP"):
            os.environ.pop(key, None)

    class ScopedNativeInstaller(original):
        def __init__(self, args, *positional, **options):
            command = args
            install_handoff = False
            if (isinstance(command, (list, tuple)) and len(command) >= 2
                    and Path(command[1]).name == "setup.py"):
                cwd = Path(options.get("cwd") or os.getcwd())
                target = Path(command[1])
                target = (cwd / target).resolve() if not target.is_absolute() else target.resolve()
                if target == installer:
                    caller = sys._getframe(1)
                    while caller is not None and caller.f_globals.get("__name__") == "subprocess":
                        caller = caller.f_back
                    install_handoff = _native_call(caller, "strata_cli.cli", "_install", cli_file)
                    options["pass_fds"] = tuple(dict.fromkeys((*options.get("pass_fds", ()), descriptor)))
                    options["env"] = dict(os.environ if options.get("env") is None else options["env"],
                                          STRATA_WORKSPACE_LOCK_FD=str(descriptor))
                    command = [command[0], helper, "--native-setup", str(root), *command[2:]]
                else:
                    options["env"] = managed_state.external_environment(
                        os.environ if options.get("env") is None else options["env"])
                    options["pass_fds"] = tuple(fd for fd in options.get("pass_fds", ()) if fd != descriptor)
            if (isinstance(command, (list, tuple)) and list(command[1:3]) == ["-m", "strata_control.runtime"]
                    and "--host" in command[3:]
                    and Path(options.get("cwd") or os.getcwd()).resolve() == root):
                with _source_reader(state) as reader:
                    command, options = _module_spawn(state, helper, command, options, reader)
                    super().__init__(command, *positional, **options)
            else:
                super().__init__(command, *positional, **options)
            if install_handoff:
                # Popen returned only after the managed child inherited the lease.
                # Closing this copy cannot unlock a surviving mutating descendant.
                release_acquisition()

    import threading
    previous = sys.getprofile()
    previous_thread = threading.getprofile()
    runner_file = str(root / "strata_cli/launch/runner.py")
    mutation = _MonitorMutation(root)

    def prepared(frame, event, result):
        module = sys.modules.get("strata_cli.launch.runner")
        runner = getattr(module, "Runner", None)
        if (event == "return" and result is not None and runner is not None
                and frame.f_code.co_filename == runner_file
                and frame.f_globals is module.__dict__
                and frame.f_code is runner.run.__code__):
            # Only the native interactive LaunchApp worker consumes UI modules.
            caller = frame.f_back
            app = sys.modules.get("strata_cli.launch.app")
            app_class = getattr(app, "LaunchApp", None)
            if (app_class is not None and caller is not None
                    and caller.f_code is app_class._work.__code__
                    and caller.f_code.co_filename == str(root / "strata_cli/launch/app.py")):
                for name in ("strata_cli.launch.monitor_ext", "strata_cli.consoleinfo",
                             "strata_cli.overview", "strata_control.engine_update",
                             "strata_control.updater", "strata_control.runtime",
                             "strata_control.discovery", "strata_control.feed_models",
                             "strata_cli.update_cmd", "strata_control.cfg_paths",
                             "strata_control.signing", "strata_control.engine_component",
                             "strata_control.retired"):
                    importlib.import_module(name)
            release_acquisition()
            subprocess.Popen = original
            mutation.install()

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
        mutation.close()


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
    # Native setup starts a script; Host starts a module. Route both through the
    # same protected server entry without changing the native server arguments.
    if len(command) >= 2 and command[1] != "-m":
        target = Path(command[1])
        cwd = Path(options.get("cwd") or os.getcwd())
        target = (cwd / target).resolve() if not target.is_absolute() else target.resolve()
        if target != root / "serve/server.py":
            raise RuntimeError("Unsupported native managed script")
        command = [command[0], "-m", "serve.server", *command[2:]]
    options = dict(options)
    options["cwd"] = str(root)
    env = dict(options.get("env") if options.get("env") is not None else os.environ)
    mutation_fd = env.get("STRATA_WORKSPACE_LOCK_FD")
    if mutation_fd is not None:
        # Remove only the protocol's validated acquisition description. Owner
        # pipes, source readers and unrelated pass_fds must survive this handoff.
        mutation_fd = int(mutation_fd)
        held = os.fstat(mutation_fd)
        expected = (state / ".source.lock").stat()
        context = json.loads(env["STRATA_WORKSPACE_CONTEXT"])
        marker = env.get("STRATA_ACQUISITION_BOOTSTRAP")
        if ((held.st_dev, held.st_ino) != (expected.st_dev, expected.st_ino)
                or Path(context["state"]).resolve() != state.resolve()
                or (marker is not None and marker != f"{held.st_dev}:{held.st_ino}")):
            raise RuntimeError("Native handoff acquisition descriptor does not belong to this workspace")
    options["pass_fds"] = tuple(dict.fromkeys((
        *(fd for fd in options.get("pass_fds", ()) if fd != mutation_fd), reader.fileno())))
    options["env"] = dict(env, STRATA_SOURCE_LOCK_FD=str(reader.fileno()),
                          STRATA_NATIVE_SOURCE_STATE=str(state), STRATA_NATIVE_MODULE_HELPER=helper)
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
        if done or (module_name == "serve.server" and reader.closed):
            sys.setprofile(inherited_profile)
            return
        if module_name == "serve.server" and not reader.closed and _server_ready(root, frame, event, result):
            _preload_server(root)
            with reader_mutex:
                reader.close()
            sys.setprofile(inherited_profile)
            threading.setprofile(previous_thread)
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
