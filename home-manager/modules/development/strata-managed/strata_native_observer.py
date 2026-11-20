"""Protect native pins without modifying their parser or checkout functions.

Both supported native CLIs dispatch through ``cli._run``. Their logs entry and
Textual run call are the short-read boundary: imports and the UI constructor have
finished, but no long polling/event loop has begun. A temporary Python profile
hook observes those calls; it never substitutes a checkout function or module.
An error before readiness leaves imports protected until exit closes the reader.
Active dispatch instead retains acquisition and hands the native managed setup
child the same lease through a scoped stdlib spawn adapter and stable bootstrap.
"""

import importlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


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

    Only the native Python setup spawn is adapted. Its argv is restored by the
    stable helper's native setup entry; no checkout function or parser is replaced.
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

    class NativeInstaller(original):
        def __init__(self, command, *positional, **options):
            if (isinstance(command, (list, tuple)) and len(command) >= 2
                    and command[0] == sys.executable and Path(command[1]).name == "setup.py"):
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
            super().__init__(command, *positional, **options)

    subprocess.Popen = NativeInstaller
    try:
        _entry(root, entry, args)
    finally:
        subprocess.Popen = original
        lease.close()
