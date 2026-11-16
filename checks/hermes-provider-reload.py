"""Consumer regressions for frozen provider versions, using the installed interpreter."""

import builtins
import concurrent.futures
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest


DECLARATION = '''from pathlib import Path
import json
from providers import register_provider
from providers.base import ProviderProfile
VERSION = json.loads(Path(__file__).with_name("version.json").read_text())["version"]
class ReviewProfile(ProviderProfile):
{headers}
{gate}
if VERSION != "empty":
    register_provider(ReviewProfile(name="review-provider", aliases=("review-alias",),
                                   base_url="https://" + VERSION + ".invalid"))
{tail}
'''

DEFAULT_HEADERS = '''    def request_headers(self, *, base_url, model="", user_initiated=False):
        version = json.loads(Path(__file__).with_name("version.json").read_text())["version"]
        return {"X-Version": version}
'''

HOST_GATE = '''import os, sys
if os.environ.get("HERMES_PLUGIN_HOST_PROCESS") == "1" and "--extract-profiles" not in sys.argv:
    home = Path(os.environ["HERMES_HOME"])
    with (home / ("entered-" + VERSION)).open("w") as stream:
        stream.write("x")
    with (home / ("release-" + VERSION)).open("r") as stream:
        stream.read(1)
'''


def remove_fixture(path):
    """Only restore access in test-owned source fixtures, never in runtime snapshots."""
    for directory, _, _ in os.walk(path, followlinks=False):
        Path(directory).chmod(0o700)
    shutil.rmtree(path)


class Fixture:
    def __init__(self, root, plugin, mode="in_process"):
        self.root = root
        self.plugin = plugin
        self.mode = mode
        self.home = root / "home"
        (self.home / "plugins").mkdir(parents=True)
        (self.home / "config.yaml").write_text(f"plugins:\n  isolation: {mode}\n")
        self.link = self.home / "plugins" / "review-provider"
        os.environ.clear()
        os.environ.update(HOME=str(root), HERMES_HOME=str(self.home), PATH=os.defpath,
                          HERMES_DISABLE_LAZY_INSTALLS="1")
        self.stamp = (plugin / "__init__.py").stat().st_mtime_ns
        import providers
        from providers import plugin_reload
        self.providers = providers
        self.reloader = plugin_reload
        self.generation_number = 0

    def generation(self, version, *, gate="", tail="", headers=DEFAULT_HEADERS, mutable=False):
        path = self.root / f"generation-{self.generation_number}"
        self.generation_number += 1
        path.mkdir()
        (path / "plugin.yaml").write_text("name: review-provider\nkind: model-provider\n")
        (path / "version.json").write_text(json.dumps({"version": version}))
        (path / "__init__.py").write_text(DECLARATION.format(gate=gate, tail=tail, headers=headers))
        (path / "empty-directory").mkdir()
        for item in path.iterdir():
            os.utime(item, ns=(self.stamp, self.stamp))
            item.chmod(0o755 if item.is_dir() else 0o644)
        os.utime(path, ns=(self.stamp, self.stamp))
        if not mutable:
            for item in path.iterdir():
                item.chmod(0o555 if item.is_dir() else 0o444)
            path.chmod(0o555)
        return path

    def install(self, path):
        self.link.unlink(missing_ok=True)
        self.link.symlink_to(path, target_is_directory=True)

    def profile(self):
        profile = self.providers.get_provider_profile("review-provider")
        assert profile is not None, self.providers.plugin_load_error("review-provider")
        return profile

    def headers(self, profile):
        return profile.request_headers(base_url=profile.base_url)["X-Version"]

    def refresh(self):
        self.providers.refresh_bound_home()

    def host(self):
        from hermes_cli.plugins import get_plugin_manager
        return get_plugin_manager()._running_plugin_host()

    def stop_host(self):
        host = self.host()
        if host is not None:
            host.shutdown()

    def close(self):
        if self.mode == "host":
            self.stop_host()
        self.reloader._cleanup_snapshots()
        remove_fixture(self.root)


def rollback(fixture):
    one, two = fixture.generation("one"), fixture.generation("second")
    fixture.install(one)
    old = fixture.profile()
    assert fixture.headers(old) == "one"
    fixture.install(two)
    fixture.refresh()
    assert fixture.headers(fixture.profile()) == "second"
    fixture.install(one)
    fixture.refresh()
    restored = fixture.profile()
    assert fixture.headers(restored) == "one"
    assert fixture.providers.get_provider_profile("review-alias") is restored
    assert fixture.headers(old) == "one"
    assert fixture.providers.plugin_load_error("review-provider") == ""
    return {"rollback": restored.base_url}


def resource_identity(fixture):
    one, two = fixture.generation("1"), fixture.generation("2")
    for name in ("__init__.py", "plugin.yaml", "version.json"):
        assert (one / name).stat().st_size == (two / name).stat().st_size
        assert (one / name).stat().st_mtime_ns == (two / name).stat().st_mtime_ns
    assert (one / "__init__.py").read_bytes() == (two / "__init__.py").read_bytes()
    fixture.install(one)
    old = fixture.profile()
    fixture.install(two)
    fixture.refresh()
    new = fixture.profile()
    assert new.base_url == "https://2.invalid" and fixture.headers(new) == "2"
    remove_fixture(one)  # simulate collection of the previous installation, not its frozen copy
    assert fixture.headers(old) == "1"
    return {"new_resource": fixture.headers(new), "old_resource": fixture.headers(old)}


def removal_and_failure(fixture):
    one = fixture.generation("one")
    broken = fixture.generation("broken", tail='raise RuntimeError("broken release")')
    empty = fixture.generation("empty")
    fixture.install(one)
    old = fixture.profile()
    fixture.install(broken)
    fixture.refresh()
    assert fixture.profile() is old
    assert "broken release" in fixture.providers.plugin_load_error("review-provider")
    fixture.install(empty)
    fixture.refresh()
    assert fixture.providers.get_provider_profile("review-provider") is None
    assert fixture.providers.get_provider_profile("review-alias") is None
    fixture.install(one)
    fixture.refresh()
    assert fixture.headers(fixture.profile()) == "one"
    assert fixture.providers.get_provider_profile("review-alias") is fixture.profile()
    assert not list(fixture.reloader._snapshot_root.glob(".copy-*"))
    return {"failed_update_retained": old.base_url, "empty_version_removed_alias": True}


def overlapping_import(fixture, kind):
    gate = types.ModuleType("provider_test_gate")
    gate.entered, gate.release = threading.Event(), threading.Event()
    gate.calls = 0

    def pause():
        gate.calls += 1
        gate.entered.set()
        if not gate.release.wait(15):
            raise RuntimeError("provider import gate timed out")

    gate.pause = pause
    sys.modules[gate.__name__] = gate
    one = fixture.generation("one")
    two = fixture.generation("second", tail="import provider_test_gate\nprovider_test_gate.pause()")
    fixture.install(one)
    old = fixture.profile()
    generation = fixture.providers._REGISTRY_GENERATION
    fixture.install(two)
    errors = []

    def refresh():
        try:
            fixture.refresh()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=refresh, daemon=True)
    worker.start()
    try:
        assert gate.entered.wait(15), "new import never reached its registration gate"
        assert fixture.profile() is old, "partial import replaced the live profile"
        assert fixture.providers._REGISTRY_GENERATION == generation
        if kind == "same":
            fixture.refresh()
            assert fixture.profile() is old
        elif kind == "newer":
            newer = fixture.generation("newest")
            fixture.install(newer)
            fixture.refresh()
            assert fixture.headers(fixture.profile()) == "newest"
        else:
            fixture.install(one)
            fixture.refresh()
            assert fixture.profile() is old
    finally:
        gate.release.set()
        worker.join(15)
    assert not worker.is_alive(), "import deadlocked"
    assert not errors, errors
    expected = {"same": "second", "newer": "newest", "rollback": "one"}[kind]
    assert fixture.headers(fixture.profile()) == expected
    assert gate.calls == 1
    assert not list(fixture.reloader._snapshot_root.glob(".copy-*"))
    return {"after_overlap": expected, "complete_imports": gate.calls}


def listing_during_update(fixture):
    one = fixture.generation("one")
    two = fixture.generation("second", tail='register_provider(ProviderProfile(name="review-added", base_url="https://second.invalid"))')
    fixture.install(one)
    old = fixture.profile()
    fixture.providers.list_providers()
    entered, release, published = threading.Event(), threading.Event(), threading.Event()
    reader_errors, writer_errors, observed = [], [], []

    def read():
        try:
            observed.extend(fixture.providers.list_providers())
        except BaseException as error:
            reader_errors.append(error)

    def publish():
        try:
            fixture.refresh()
        except BaseException as error:
            writer_errors.append(error)
        finally:
            published.set()

    reader = threading.Thread(target=read, daemon=True)
    writer = threading.Thread(target=publish, daemon=True)

    def gated_id(profile):
        identity = builtins.id(profile)
        if threading.current_thread() is reader and profile is old and not entered.is_set():
            entered.set()
            if not release.wait(15):
                raise RuntimeError("provider list gate timed out")
        return identity

    # Delay a real identity lookup after the registry iterator yielded a profile.
    missing = object()
    previous_id = vars(fixture.providers).get("id", missing)
    fixture.providers.id = gated_id
    try:
        reader.start()
        assert entered.wait(15), "reader did not enter profile deduplication"
        fixture.install(two)
        writer.start()
        assert published.wait(15), "publication blocked behind the reader"
        assert not writer_errors, writer_errors
    finally:
        release.set()
        try:
            for worker in (reader, writer):
                if worker.ident is not None:
                    worker.join(15)
        finally:
            if previous_id is missing:
                del fixture.providers.id
            else:
                fixture.providers.id = previous_id
    assert not reader.is_alive() and not writer.is_alive(), "listing or publication deadlocked"
    assert not reader_errors, reader_errors
    before = {profile.name: profile for profile in observed if profile.name in ("review-provider", "review-added")}
    assert set(before) == {"review-provider"} and before["review-provider"] is old
    assert fixture.headers(old) == "one"
    current = fixture.profile()
    assert current is not old and fixture.headers(current) == "second"
    assert fixture.providers.get_provider_profile("review-alias") is current
    assert fixture.providers.get_provider_profile("review-added") is not None
    after = {profile.name for profile in fixture.providers.list_providers()}
    assert {"review-provider", "review-added"} <= after
    return {"concurrent_listing": "old snapshot", "published_version": fixture.headers(current)}


def reentrant_import(fixture):
    one = fixture.generation("one")
    fixture.install(one)
    old = fixture.profile()
    tail = ('from providers import get_provider_profile, list_providers\n'
            'assert get_provider_profile("review-provider").base_url == "https://one.invalid"\n'
            'assert any(p.name == "review-provider" for p in list_providers())')
    two = fixture.generation("second", tail=tail)
    fixture.install(two)
    fixture.refresh()
    assert fixture.headers(fixture.profile()) == "second" and fixture.headers(old) == "one"
    return {"reentrant_import": "complete"}


def hosted_versions(fixture, *, late=False):
    one, two = fixture.generation("one"), fixture.generation("second")
    fixture.install(one)
    old = fixture.profile()
    pid = None
    if not late:
        assert fixture.headers(old) == "one"
        pid = fixture.host()._proc.pid
    fixture.install(two)
    fixture.refresh()
    new = fixture.profile()
    assert new.base_url == "https://second.invalid" and fixture.headers(new) == "second"
    if pid is not None:
        assert fixture.host()._proc.pid == pid, "test must retain the real host"
    remove_fixture(one)
    assert fixture.headers(old) == "one", "late call read the replaced installation"
    fixture.stop_host()
    assert fixture.headers(old) == "one", "restarted host lost the old frozen version"
    assert fixture.headers(new) == "second"
    return {"new_hook": fixture.headers(new), "old_hook_after_restart": fixture.headers(old)}


def hosted_overlap(fixture):
    controls = {}
    for version in ("one", "second"):
        controls[version] = []
        for direction in ("entered", "release"):
            fifo = fixture.home / f"{direction}-{version}"
            os.mkfifo(fifo)
            controls[version].append(os.open(fifo, os.O_RDWR | os.O_NONBLOCK))
    one = fixture.generation("one", gate=HOST_GATE)
    two = fixture.generation("second", gate=HOST_GATE)
    fixture.install(one)
    old = fixture.profile()
    fixture.install(two)
    fixture.refresh()
    new = fixture.profile()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        try:
            first = pool.submit(fixture.headers, old)
            assert select.select([controls["one"][0]], [], [], 15)[0], "V1 host import did not start"
            assert os.read(controls["one"][0], 1) == b"x"
            second = pool.submit(fixture.headers, new)
            assert select.select([controls["second"][0]], [], [], 15)[0], "V2 host import did not overlap"
            assert os.read(controls["second"][0], 1) == b"x"
            os.write(controls["one"][1], b"x")
            assert first.result(timeout=15) == "one"
            os.write(controls["second"][1], b"x")
            assert second.result(timeout=15) == "second"
        finally:
            for entered, release in controls.values():
                os.write(release, b"x")
    for entered, release in controls.values():
        os.close(entered)
        os.close(release)
    return {"concurrent_host_versions": [fixture.headers(old), fixture.headers(new)]}


def host_cleanup(fixture):
    (fixture.home / "plugins" / "github-copilot").symlink_to(fixture.plugin, target_is_directory=True)
    extra = '''
    def request_headers(self, *, base_url, model="", user_initiated=False):
        import providers
        from providers import plugin_reload
        providers.get_provider_profile("copilot")
        return {"X-Child-Root": str(plugin_reload._snapshot_root)}
'''
    path = fixture.generation("one", headers=extra)
    fixture.install(path)
    profile = fixture.profile()
    response = profile.request_headers(base_url=profile.base_url)
    child_root = Path(response["X-Child-Root"])
    parent_root = fixture.reloader._snapshot_root
    assert child_root != parent_root and child_root.is_dir()
    fixture.stop_host()
    assert not child_root.exists(), "forced host exit leaked its owned snapshots"
    assert parent_root.is_dir(), "host exit removed parent-owned versions"
    return {"forced_host_cleanup": "complete"}


def normal_exit(plugin):
    with tempfile.TemporaryDirectory(prefix="provider-exit-home-") as temporary:
        home = Path(temporary)
        (home / "plugins").mkdir()
        (home / "plugins" / "github-copilot").symlink_to(plugin, target_is_directory=True)
        (home / "config.yaml").write_text("model:\n  provider: nous\n")
        os.environ.clear()
        os.environ.update(HOME=str(home), HERMES_HOME=str(home), PATH=os.defpath,
                          HERMES_DISABLE_LAZY_INSTALLS="1")
        import providers
        from providers import plugin_reload
        assert providers.get_provider_profile("copilot") is not None
        print(json.dumps({"snapshot_root": str(plugin_reload._snapshot_root)}))
    # No manual runtime cleanup: the outer process verifies the real atexit callback.




def activation_result(fixture, manager):
    from hermes_cli.plugins_activation import plugin_activation_summary, activation_hint
    key = next(key for key, loaded in manager._plugins.items() if loaded.manifest.name == "review-provider")
    summary = plugin_activation_summary(manager, key)
    hint = activation_hint({"gateway_reloaded": True, "activation": summary})
    return summary, hint


def activation_pending(fixture, fail):
    from hermes_cli.plugins import PluginManager
    gate = types.ModuleType("activation_test_gate")
    gate.entered, gate.release = threading.Event(), threading.Event()
    def pause():
        gate.entered.set()
        if not gate.release.wait(15):
            raise RuntimeError("activation gate timed out")
        if fail:
            raise RuntimeError("activation failed after deferred response")
    gate.pause = pause
    sys.modules[gate.__name__] = gate
    fixture.install(fixture.generation("one"))
    old = fixture.profile()
    fixture.install(fixture.generation("second", tail="import activation_test_gate\nactivation_test_gate.pause()"))
    worker = threading.Thread(target=fixture.refresh, daemon=True)
    worker.start()
    try:
        assert gate.entered.wait(15)
        manager = PluginManager()
        manager.discover_and_load(force=True)
        before, hint = activation_result(fixture, manager)
        assert "provider" not in before["activated_now"]
        assert before["deferred"]["provider"] == ["review-provider"]
        assert fixture.profile() is old
    finally:
        gate.release.set()
        worker.join(15)
    assert not worker.is_alive()
    after, final_hint = activation_result(fixture, manager)
    if fail:
        assert "activation failed after deferred response" in after["load_error"]
        assert "provider" not in after["activated_now"]
        assert fixture.profile() is old
    else:
        assert after["activated_now"]["provider"] == ["review-provider"]
        assert "provider" not in after["deferred"]
        assert fixture.headers(fixture.profile()) == "second"
    assert before["deferred"]["provider"] == ["review-provider"]
    return {"initial_hint": hint, "final_hint": final_hint}


def activation_scope(fixture):
    from hermes_cli.plugins import PluginManager
    fixture.install(fixture.generation("one"))
    fixture.profile()
    manager = PluginManager()
    manager.discover_and_load(force=True)
    different = fixture.root / "different-home"
    different.mkdir()
    os.environ["HERMES_HOME"] = str(different)
    try:
        summary, _ = activation_result(fixture, manager)
        assert summary["activated_now"]["provider"] == ["review-provider"]
        assert fixture.providers.plugin_activation_status(fixture.link, home=different) == ("inactive", "")
    finally:
        os.environ["HERMES_HOME"] = str(fixture.home)
    return {"manager_home": "ready", "ambient_home": "inactive"}


def activation_merge(fixture):
    import copy
    from unittest.mock import patch
    from hermes_cli import plugins_activation as activation
    ready = {"name": "review-provider", "key": "review-provider", "activated_now": {"provider": ["review-provider"]}, "deferred": {},
             "live_now": {"skills": [{"name": "keep-skill"}]}}
    pending = {"name": "review-provider", "key": "review-provider", "activated_now": {}, "deferred": {"provider": ["review-provider"]}}
    failed = {"name": "review-provider", "key": "review-provider", "activated_now": {}, "deferred": {}, "load_error": "gateway failed"}
    for backend, gateway in ((ready, pending), (ready, failed), (failed, ready)):
        with patch.object(activation, "load_and_go_live", return_value=copy.deepcopy(backend)), patch.object(
            activation, "reload_running_gateway", return_value={"reloaded": True, "activations": [copy.deepcopy(gateway)]}
        ):
            result = activation.activate_plugin_now("review-provider")
        observed = result["activation"]
        assert observed["activated_now"] == gateway["activated_now"]
        assert observed["deferred"] == gateway["deferred"]
        assert observed.get("load_error") == gateway.get("load_error")
        if "live_now" in backend:
            assert observed["live_now"] == backend["live_now"]
    return {"gateway_status_authoritative": True}


def interrupted_host(fixture):
    gate = ('import os, sys\n'
            'from .aux import READY\n'
            'if os.environ.get("HERMES_PLUGIN_HOST_PROCESS") == "1" and "--extract-profiles" not in sys.argv and '
            '(Path(os.environ["HERMES_HOME"]) / "interrupt-once").exists():\n'
            '    raise SystemExit("interrupted provider import")')
    one = fixture.generation("one")
    fixture.install(one)
    old = fixture.profile()
    assert fixture.headers(old) == "one"
    pid = fixture.host()._proc.pid
    two = fixture.generation("second", gate=gate, mutable=True)
    (two / "aux.py").write_text("READY = True\n")
    for path in two.iterdir():
        path.chmod(0o555 if path.is_dir() else 0o444)
    two.chmod(0o555)
    fixture.install(two)
    fixture.refresh()
    new = fixture.profile()
    marker = fixture.home / "interrupt-once"
    marker.touch()
    try:
        fixture.headers(new)
    except Exception as error:
        assert "SystemExit" in str(error) and "interrupted provider import" in str(error)
    else:
        raise AssertionError("first import must report the original SystemExit")
    marker.unlink()
    assert fixture.headers(new) == "second", "second call must recover without another failed call"
    assert fixture.host()._proc.pid == pid
    assert fixture.headers(old) == "one"
    return {"second_call": "second", "host_retained": True, "old_hook": "one"}


def long_names(fixture):
    fixture.link = fixture.home / "plugins" / ("x" * 180)
    result = rollback(fixture)
    result["directory_name_length"] = len(fixture.link.name)
    assert not list(fixture.reloader._snapshot_root.glob(".copy-*"))
    return result
def run_case(case, plugin):
    if case == "normal-exit":
        normal_exit(plugin)
        return
    root = Path(tempfile.mkdtemp(prefix="provider-lifecycle-"))
    hosted = case in {"rollback-host", "host-live", "host-late", "host-overlap", "host-cleanup", "interrupt-host", "long-host"}
    fixture = Fixture(root, plugin, "host" if hosted else "in_process")
    try:
        if case.startswith("rollback"):
            result = rollback(fixture)
        elif case == "resources":
            result = resource_identity(fixture)
        elif case == "failure-removal":
            result = removal_and_failure(fixture)
        elif case.startswith("overlap-"):
            result = overlapping_import(fixture, case.removeprefix("overlap-"))
        elif case == "listing-update":
            result = listing_during_update(fixture)
        elif case == "reentrant":
            result = reentrant_import(fixture)
        elif case in {"host-live", "host-late"}:
            result = hosted_versions(fixture, late=case == "host-late")
        elif case == "host-overlap":
            result = hosted_overlap(fixture)
        elif case == "host-cleanup":
            result = host_cleanup(fixture)
        elif case in {"activation-success", "activation-failure"}:
            result = activation_pending(fixture, fail=case == "activation-failure")
        elif case == "activation-home":
            result = activation_scope(fixture)
        elif case == "activation-merge":
            result = activation_merge(fixture)
        elif case == "interrupt-host":
            result = interrupted_host(fixture)
        elif case in {"long-native", "long-host"}:
            result = long_names(fixture)
        else:
            raise ValueError(case)
        print(json.dumps(result))
    finally:
        fixture.close()


class ProviderLifecycle(unittest.TestCase):
    def run_case(self, case):
        process = subprocess.run(
            [sys.executable, "-I", "-B", __file__, "--case", case, str(PLUGIN)],
            env={"PATH": os.defpath}, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout.splitlines()[-1])
        if case == "normal-exit":
            self.assertFalse(Path(result["snapshot_root"]).exists(), result)
        print(case, result)

    def test_rollback(self):
        self.run_case("rollback")

    def test_rollback_host(self):
        self.run_case("rollback-host")

    def test_same_size_resources_and_old_lazy_reads(self):
        self.run_case("resources")

    def test_failed_and_empty_versions(self):
        self.run_case("failure-removal")

    def test_same_version_overlap(self):
        self.run_case("overlap-same")

    def test_newer_version_wins(self):
        self.run_case("overlap-newer")


    def test_list_during_completed_update(self):
        self.run_case("listing-update")
    def test_live_rollback_cancels_pending_update(self):
        self.run_case("overlap-rollback")

    def test_import_reentrance(self):
        self.run_case("reentrant")

    def test_host_keeps_each_version_and_restarts(self):
        self.run_case("host-live")

    def test_host_late_first_call(self):
        self.run_case("host-late")

    def test_concurrent_host_captures(self):
        self.run_case("host-overlap")

    def test_forced_host_cleanup(self):
        self.run_case("host-cleanup")

    def test_normal_exit_cleanup(self):
        self.run_case("normal-exit")

    def test_deferred_activation_then_success(self):
        self.run_case("activation-success")

    def test_deferred_activation_then_failure(self):
        self.run_case("activation-failure")

    def test_activation_manager_home(self):
        self.run_case("activation-home")

    def test_gateway_activation_merge(self):
        self.run_case("activation-merge")

    def test_interrupted_host_import_recovers_on_next_call(self):
        self.run_case("interrupt-host")

    def test_long_plugin_name(self):
        self.run_case("long-native")

    def test_long_plugin_name_hosted(self):
        self.run_case("long-host")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--case"]:
        run_case(sys.argv[2], Path(sys.argv[3]).resolve())
    else:
        PLUGIN = Path(sys.argv.pop(1)).resolve()
        unittest.main(verbosity=2)
