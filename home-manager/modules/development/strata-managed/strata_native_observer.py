"""Consume source readers for native pins without modifying their parser or functions.

Both supported native CLIs dispatch through ``cli._run``. Their logs entry and
Textual run call are the short-read boundary: imports and the UI constructor have
finished, but no long polling/event loop has begun. A temporary Python profile
hook observes those calls; it never substitutes a checkout function or module.
An error before readiness leaves imports protected until exit closes the reader.
"""

import importlib
import os
import runpy
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
