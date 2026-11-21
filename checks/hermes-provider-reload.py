"""Consumer regressions for frozen provider versions, using the installed interpreter."""

import builtins
import concurrent.futures
import errno
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
from unittest.mock import patch


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
                                   base_url="https://" + VERSION + ".invalid"{options}))
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

    def generation(self, version, *, gate="", tail="", headers=DEFAULT_HEADERS, mutable=False, mirror=False):
        path = self.root / f"generation-{self.generation_number}"
        self.generation_number += 1
        path.mkdir()
        (path / "plugin.yaml").write_text("name: review-provider\nkind: model-provider\n")
        (path / "version.json").write_text(json.dumps({"version": version}))
        options = ', auth_type="api_key", env_vars=("REVIEW_PROVIDER_API_KEY",)' if mirror else ""
        (path / "__init__.py").write_text(DECLARATION.format(gate=gate, tail=tail, headers=headers, options=options))
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


def linked_snapshot_storage(fixture):
    runtime = fixture.home / "runtime"
    fixture.generation("one", mutable=True).rename(runtime)
    storage = runtime / "snapshot-store"
    storage.mkdir()
    (runtime / "provider-plugins").symlink_to(storage.name, target_is_directory=True)
    assets = runtime / "assets" / "provider-plugins"
    assets.mkdir(parents=True)
    (assets / "asset.txt").write_text("plugin data, not snapshots")
    fixture.link.symlink_to("../runtime", target_is_directory=True)

    old = fixture.profile()
    reloader = fixture.reloader
    root = reloader._snapshot_root
    assert root.parent == storage.resolve()
    [copied] = root.glob("*/review-provider")
    fingerprint = reloader.tree_fingerprint(copied)
    assert copied.parent.name.endswith(f"_{fingerprint}")
    assert not (copied / "provider-plugins").exists()
    assert not (copied / "snapshot-store").exists()
    assert (copied / "assets" / "provider-plugins" / "asset.txt").read_text() == "plugin data, not snapshots"

    # Storage activity and an alias to an owned root must not create a new generation.
    (storage / "unrelated-state").write_text("persistent storage activity")
    (runtime / "owned-alias").symlink_to(root, target_is_directory=True)
    fixture.refresh()
    assert fixture.profile() is old
    assert list(root.glob("*/review-provider")) == [copied]

    # Retargeting the configured alias must not move live code or redirect cleanup.
    replacement = runtime / "next-snapshot-store"
    decoy = replacement / root.name
    decoy.mkdir(parents=True)
    (decoy / "marker").write_text("another store")
    alias = runtime / "provider-plugins"
    alias.unlink()
    alias.symlink_to(replacement.name, target_is_directory=True)
    fixture.refresh()
    assert fixture.profile() is old and fixture.headers(old) == "one"
    assert list(root.glob("*/review-provider")) == [copied]

    (runtime / "version.json").write_text(json.dumps({"version": "second"}))
    fixture.refresh()
    assert fixture.headers(fixture.profile()) == "second"
    assert fixture.headers(old) == "one"
    assert len(list(root.glob("*/review-provider"))) == 2
    assert not list(root.glob(".copy-*"))
    reloader._cleanup_snapshots()
    assert not root.exists()
    assert not list(storage.glob(f"{reloader._REAPING_PREFIX}*"))
    assert (decoy / "marker").read_text() == "another store"
    assert (storage / "unrelated-state").read_text() == "persistent storage activity"
    assert (assets / "asset.txt").read_text() == "plugin data, not snapshots"
    return {"linked_storage": "excluded", "retargeted_cleanup": "anchored",
            "retained_provider": "one", "new_provider": "second"}


def overlapping_snapshot_storage(fixture, *, equal):
    reloader = fixture.reloader
    storage = reloader._persistent_store()
    storage.parent.mkdir(parents=True, exist_ok=True)
    source = storage if equal else storage / "source"
    if not equal:
        storage.mkdir()
    fixture.generation("one", mutable=True).rename(source)
    fixture.install(source)

    artifact = storage / f"{reloader._UNSWEPT_PREFIX}old"
    artifact.mkdir()
    (artifact / "marker").write_text("old snapshot")
    (source / "snapshot-alias").symlink_to(artifact / "marker")
    (source / "store-alias").symlink_to(storage, target_is_directory=True)
    payload = source / "assets" / artifact.name
    payload.mkdir(parents=True)
    (payload / "marker").write_text("plugin payload")
    payload_file = source / f"{reloader._OWNED_PREFIX}asset.txt"
    payload_file.write_text("not a snapshot directory")

    old = fixture.profile()
    assert fixture.headers(old) == "one"
    root = reloader._snapshot_root
    assert root.parent == storage.resolve()
    [copied] = root.glob("*/review-provider")
    assert (copied / "assets" / artifact.name / "marker").read_text() == "plugin payload"
    assert (copied / payload_file.name).read_text() == "not a snapshot directory"
    for name in (root.name, reloader._SETUP_LOCK, artifact.name, "snapshot-alias", "store-alias"):
        assert not (copied / name).exists(), name

    (artifact / "marker").write_text("changed snapshot")
    (source / "active-root-alias").symlink_to(root, target_is_directory=True)
    fixture.refresh()
    assert fixture.profile() is old
    assert list(root.glob("*/review-provider")) == [copied]

    (source / "version.json").write_text(json.dumps({"version": "second"}))
    fixture.refresh()
    assert fixture.headers(fixture.profile()) == "second"
    assert fixture.headers(old) == "one"
    assert not list(root.glob(".copy-*"))
    return {"storage": "equal" if equal else "ancestor", "old_provider": "one", "new_provider": "second"}


def case_variant_snapshot_storage(fixture):
    reloader = fixture.reloader
    storage = reloader._persistent_store().resolve()
    storage.mkdir(parents=True)
    source = storage / "source"
    fixture.generation("one", mutable=True).rename(source)
    fixture.install(source)
    artifact = storage / f"{reloader._UNSWEPT_PREFIX}old"
    artifact.mkdir()
    marker = artifact / "marker"
    marker.write_text("old snapshot")
    (source / "snapshot-alias").symlink_to(marker)
    (source / "store-alias").symlink_to(storage, target_is_directory=True)

    # Keep a resource whose name only resembles a reserved root on a sensitive volume.
    payload = source / artifact.name.upper()
    payload.mkdir()
    (payload / "marker").write_text("plugin payload")

    alternate_store = storage.with_name(storage.name.upper())
    alternate_artifact = alternate_store / artifact.name.upper()
    native = alternate_store.exists()
    if not native:
        # Exercise the same inode under both spellings on a case-sensitive test volume.
        alternate_store.symlink_to(storage.name, target_is_directory=True)
        alternate_artifact.symlink_to(artifact.name, target_is_directory=True)
        distinct_store = storage.with_name(storage.name.capitalize())
        distinct_store.mkdir()
        (distinct_store / "marker").write_text("distinct directory")
        (source / "distinct-store").symlink_to(distinct_store, target_is_directory=True)
    assert alternate_store.samefile(storage) and alternate_artifact.samefile(artifact)
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        resolved = real_resolve(path, *args, **kwargs)
        # POSIX resolve can return the supplied spelling rather than the on-disk spelling.
        if resolved == source:
            return alternate_store / source.name
        if resolved == storage and path.name == "store-alias":
            return alternate_store
        if resolved == marker:
            return alternate_artifact / marker.name
        if path.name == "active-root-alias":
            return alternate_store / resolved.name
        return resolved

    with patch.object(Path, "resolve", resolve):
        old = fixture.profile()
        assert fixture.headers(old) == "one"
        root = reloader._snapshot_root
        assert root.parent.samefile(storage)
        [copied] = root.glob("*/review-provider")
        assert (copied / payload.name / "marker").read_text() == "plugin payload"
        assert not (copied / "snapshot-alias").exists()
        assert not (copied / "store-alias").exists()
        if not native:
            assert (copied / "distinct-store" / "marker").read_text() == "distinct directory"
        (source / "active-root-alias").symlink_to(root, target_is_directory=True)
        marker.write_text("changed snapshot")
        fixture.refresh()
        assert fixture.profile() is old
        assert list(root.glob("*/review-provider")) == [copied]
    return {"case_variant": "native" if native else "same-inode simulation", "storage": "excluded"}


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
    assert not list(child_root.parent.glob(f"{fixture.reloader._REAPING_PREFIX}*")), (
        "forced host exit leaked a snapshot cleanup claim"
    )
    assert parent_root.is_dir(), "host exit removed parent-owned versions"
    return {"forced_host_cleanup": "complete"}


def host_cleanup_during_sweep(fixture):
    from hermes_cli.plugin_host_wire import PluginHostUnavailable

    (fixture.home / "plugins" / "github-copilot").symlink_to(fixture.plugin, target_is_directory=True)
    temp = fixture.home / "child-temp"
    temp.mkdir()
    entered = fixture.home / "reap-entered"
    os.mkfifo(entered)
    headers = '''
    def request_headers(self, *, base_url, model="", user_initiated=False):
        import errno, os, tempfile, threading
        import providers
        from pm import filesystem
        from providers import plugin_reload

        home = Path(os.environ["HERMES_HOME"])
        tempfile.tempdir = str(home / "child-temp")
        real_lock_path, reap = filesystem.lock_path, plugin_reload._reap_claim

        def lock_path(path, *, timeout):
            if path.name == plugin_reload._OWNER_LOCK:
                raise OSError(errno.ENOSPC, "injected host owner.lock failure")
            return real_lock_path(path, timeout=timeout)

        def slow_reap(claim):
            if (claim / "slow-reap-marker").exists():
                with (home / "reap-entered").open("wb", buffering=0) as signal:
                    signal.write(b"x")
                threading.Event().wait(30)
            reap(claim)

        filesystem.lock_path = lock_path
        plugin_reload._reap_claim = slow_reap
        providers.get_provider_profile("copilot")
        return {"X-Version": "unexpectedly completed"}
'''
    fixture.install(fixture.generation("one", headers=headers))
    profile = fixture.profile()
    reloader = fixture.reloader
    parent = reloader._snapshot_root
    dead = parent.parent / f"{reloader._OWNED_PREFIX}slow-regression"
    dead.mkdir()
    (dead / reloader._OWNER_LOCK).touch()
    (dead / "slow-reap-marker").touch()

    fd = os.open(entered, os.O_RDWR | os.O_NONBLOCK)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(fixture.headers, profile)
            try:
                assert select.select([fd], [], [], 15)[0], "host did not enter its slow snapshot sweep"
                assert os.read(fd, 1) == b"x"
                proc = fixture.host()._proc
                [child_root] = temp.glob(f"{reloader._TEMP_ROOT_PREFIX}*")
            finally:
                fixture.stop_host()
            assert proc.returncode == 0, f"host exited with status {proc.returncode} during the snapshot sweep"
            assert not child_root.exists(), "host exit leaked the temporary root allocated before the sweep"
            with unittest.TestCase().assertRaises(PluginHostUnavailable):
                pending.result(timeout=15)
    finally:
        os.close(fd)
    assert parent.is_dir(), "host exit removed parent-owned versions"
    return {"host_shutdown_during_sweep": "complete", "temporary_root": "removed"}


def another_snapshot_root(reloader):
    """Exercise allocation as a new process would, without replacing this fixture's live root."""
    with patch.multiple(reloader, _snapshot_root=None, _snapshot_creator_pid=None):
        return reloader._process_snapshot_root()


def persistent_cleanup(fixture):
    from hermes_constants import get_default_hermes_root

    fixture.install(fixture.generation("one"))
    profile = fixture.profile()
    live = fixture.reloader._snapshot_root
    assert live.parent == (get_default_hermes_root() / "runtime" / "provider-plugins").resolve()
    # Reclaim a crashed owner's immutable copy without touching a live owner.
    dead = live.parent / (fixture.reloader._OWNED_PREFIX + "regression-dead")
    dead.mkdir()
    (dead / fixture.reloader._OWNER_LOCK).touch()
    shutil.copytree(fixture.link.resolve(), dead / "review-provider")
    reloader = fixture.reloader
    interrupted = []

    def interrupted_delete(path):
        (path / reloader._OWNER_LOCK).unlink()
        interrupted.append(path)
        raise PermissionError("injected partial snapshot deletion")

    with unittest.TestCase().assertLogs(reloader.__name__, level="WARNING") as logs:
        with (
            patch.object(reloader.shutil, "rmtree", side_effect=interrupted_delete),
            patch.object(reloader.atexit, "register", wraps=reloader.atexit.register) as register,
        ):
            another = another_snapshot_root(reloader)
        owner_fd = register.call_args.args[2]
        register.assert_called_once_with(reloader._release_root, another, owner_fd, os.getpid())
    try:
        assert not dead.exists(), "sweep did not claim the dead root"
        assert os.fstat(owner_fd).st_ino == (another / reloader._OWNER_LOCK).stat().st_ino
        assert not reloader._owner_gone(another), "new root lost its owner lock"
        assert len(interrupted) == 1
        stale_claim = interrupted[0]
        assert stale_claim.name.startswith(reloader._REAPING_PREFIX) and stale_claim.is_dir()
        assert str(stale_claim) in logs.output[0] and "injected partial snapshot deletion" in logs.output[0]
        assert live.is_dir(), "sweep reclaimed a live owner's root"
        assert fixture.headers(profile) == "one"

        # Explicit host cleanup must leave a sweepable claim even after owner.lock is gone.
        with unittest.TestCase().assertLogs(reloader.__name__, level="WARNING") as logs:
            with patch.object(reloader.shutil, "rmtree", side_effect=interrupted_delete):
                reloader._cleanup_snapshots()
        assert len(interrupted) == 2
        exit_claim = interrupted[1]
        assert not live.exists(), "cleanup did not publish a claim"
        assert exit_claim.name.startswith(reloader._REAPING_PREFIX) and exit_claim.is_dir()
        assert str(exit_claim) in logs.output[0] and "injected partial snapshot deletion" in logs.output[0]

        recovered = another_snapshot_root(reloader)
        try:
            assert not any(path.name.startswith(reloader._REAPING_PREFIX) for path in live.parent.iterdir()), (
                "next sweep did not finish the partially removed read-only claims"
            )
            assert another.is_dir(), "recovery sweep reclaimed a live owner's root"
        finally:
            reloader._release_root(recovered, None, os.getpid())
    finally:
        reloader._release_root(another, None, os.getpid())
    return {"persistent_readonly_reclaim": "complete", "partial_removal_recovery": "complete"}


def foreign_snapshot_owners(fixture):
    reloader = fixture.reloader
    live = reloader._process_snapshot_root()
    own = live.parent / f"{reloader._OWNED_PREFIX}same-uid"
    foreign_owned = live.parent / f"{reloader._OWNED_PREFIX}foreign-uid"
    foreign_claim = live.parent / f"{reloader._REAPING_PREFIX}foreign-uid"
    for path in (own, foreign_owned, foreign_claim):
        path.mkdir()
        (path / "marker").touch()
    for path in (own, foreign_owned):
        (path / reloader._OWNER_LOCK).touch()

    uid = live.stat().st_uid
    real_lstat = Path.lstat

    def lstat(path):
        info = real_lstat(path)
        if path in (foreign_owned, foreign_claim):
            return types.SimpleNamespace(st_mode=info.st_mode, st_uid=uid + 1)
        return info

    # Unprivileged checks can simulate foreign ownership without chown or root.
    with patch.object(os, "geteuid", return_value=uid, create=True), patch.object(Path, "lstat", lstat):
        recovered = another_snapshot_root(reloader)
    try:
        assert not own.exists(), "sweep did not reclaim the same UID's dead root"
        assert live.is_dir() and not reloader._owner_gone(live)
        assert (foreign_owned / "marker").is_file(), "sweep claimed a foreign UID's dead root"
        assert (foreign_claim / "marker").is_file(), "sweep stole a foreign UID's interrupted claim"
        assert list(live.parent.glob(f"{reloader._REAPING_PREFIX}*")) == [foreign_claim]
    finally:
        reloader._release_root(recovered, None, os.getpid())
    return {"foreign_roots_preserved": True, "same_uid_dead_root_reclaimed": True}


def owner_lock_failure(fixture):
    from pm import filesystem

    reloader = fixture.reloader
    live = another_snapshot_root(reloader)
    parent = live.parent
    real_lock_path = filesystem.lock_path
    failures = (
        None,
        InterruptedError(errno.EINTR, "injected owner.lock interruption"),
        KeyboardInterrupt("injected owner.lock cancellation"),
        OSError(errno.EINVAL, "injected owner.lock invalid operation"),
    )
    for lock_error in failures:
        def lock_path(path, *, timeout):
            if path.name == reloader._OWNER_LOCK:
                if lock_error is not None:
                    raise lock_error
                return None
            return real_lock_path(path, timeout=timeout)

        with (
            patch.object(filesystem, "lock_path", side_effect=lock_path),
            patch.object(reloader.shutil, "rmtree", side_effect=PermissionError("injected purge failure")) as purge,
            unittest.TestCase().assertLogs(reloader.__name__, level="WARNING") as logs,
            unittest.TestCase().assertRaisesRegex(
                type(lock_error) if lock_error is not None else OSError, r"owner\.lock"
            ) as caught,
        ):
            another_snapshot_root(reloader)
        if lock_error is not None:
            assert caught.exception is lock_error
        else:
            assert "is held by another process" in str(caught.exception)
        purge.assert_called_once()
        claim = purge.call_args.args[0]
        assert claim.name.startswith(reloader._REAPING_PREFIX) and claim.is_dir()
        assert str(claim) in logs.output[0] and "injected purge failure" in logs.output[0]
        assert list(parent.glob(f"{reloader._OWNED_PREFIX}*")) == [live]

        recovered = another_snapshot_root(reloader)
        assert not list(parent.glob(f"{reloader._REAPING_PREFIX}*")), "sweep left failed root cleanup claims"
        assert live.is_dir(), "sweep removed a live owner while recovering a failed root"
        reloader._release_root(recovered, None, os.getpid())
    return {"owner_lock_failure_recovery": "complete"}


def owner_lock_storage_fallback(fixture, storage_errno):
    from pm import filesystem

    reloader = fixture.reloader
    runtime = fixture.home / "runtime"
    fixture.generation("one", mutable=True).rename(runtime)
    parent = runtime / "snapshot-store"
    parent.mkdir()
    (runtime / "provider-plugins").symlink_to(parent.name, target_is_directory=True)
    parent = parent.resolve()
    live = another_snapshot_root(reloader)
    assert live.parent == parent
    dead = parent / f"{reloader._OWNED_PREFIX}regression-dead"
    dead.mkdir()
    (dead / reloader._OWNER_LOCK).touch()
    temp = runtime / "system-tmp"
    temp.mkdir()
    (temp / "ordinary").write_text("plugin resource")
    real_open = os.open
    attempted = []

    def open_file(path, flags, *args, **kwargs):
        if flags & os.O_CREAT and Path(path).name == reloader._OWNER_LOCK:
            lock = Path(path)
            assert lock.parent.parent == parent
            attempted.append(lock.parent)
            raise OSError(storage_errno, "injected owner.lock storage failure", str(lock))
        return real_open(path, flags, *args, **kwargs)

    fixture.install(runtime)
    with (
        patch.object(os, "open", side_effect=open_file),
        patch.object(tempfile, "tempdir", str(temp)),
        unittest.TestCase().assertLogs(reloader.__name__, level="WARNING") as logs,
    ):
        assert fixture.headers(fixture.profile()) == "one"

    [failed] = attempted
    assert not failed.exists() and not dead.exists()
    assert list(parent.glob(f"{reloader._OWNED_PREFIX}*")) == [live]
    assert not list(parent.glob(f"{reloader._REAPING_PREFIX}*"))
    assert not reloader._owner_gone(live)
    setup_fd = filesystem.lock_path(parent / reloader._SETUP_LOCK, timeout=0)
    assert setup_fd is not None, "fallback leaked the setup lock"
    os.close(setup_fd)
    assert any("using system temp" in line and "injected owner.lock storage failure" in line for line in logs.output)
    root = reloader._snapshot_root
    assert root.parent.samefile(temp)
    assert not (root / reloader._OWNER_LOCK).exists()
    [copied] = root.glob("*/review-provider")
    assert not (copied / "provider-plugins").exists()
    assert not (copied / parent.name).exists()
    [asset] = (copied / temp.name).iterdir()
    assert asset.name == "ordinary" and asset.read_text() == "plugin resource"
    assert fixture.providers.plugin_load_error("review-provider") == ""
    reloader._cleanup_snapshots()
    assert list(temp.iterdir()) == [temp / "ordinary"], "fallback leaked its temporary root"
    return {"owner_lock_error": errno.errorcode[storage_errno], "fallback_provider": "one",
            "snapshot_stores": "excluded", "cleanup": "complete"}


def block_persistent_snapshots(home, root):
    # A file blocks runtime creation regardless of the test user's privileges.
    (home / "runtime").write_text("not a directory")
    temp = root / "system-tmp"
    target = root / "system-tmp-real"
    target.mkdir()
    temp.symlink_to(target.name, target_is_directory=True)
    os.environ["TMPDIR"] = str(temp)
    tempfile.tempdir = None  # Recompute after creating the outer test fixture.
    return temp


def temporary_cleanup(fixture):
    from hermes_constants import get_default_hermes_root

    home = get_default_hermes_root()
    temp = block_persistent_snapshots(home, fixture.root)
    fixture.install(fixture.generation("one"))
    old = fixture.profile()
    fixture.install(fixture.generation("second"))
    fixture.refresh()
    assert fixture.headers(fixture.profile()) == "second"
    assert fixture.headers(old) == "one"
    assert fixture.providers.plugin_load_error("review-provider") == ""
    reloader = fixture.reloader
    root = reloader._snapshot_root
    assert root.parent.samefile(temp) and root.stat().st_mode & 0o077 == 0
    assert not (root / reloader._OWNER_LOCK).exists()
    with patch.object(reloader.os, "rename", wraps=reloader.os.rename) as rename:
        reloader._cleanup_snapshots()
    rename.assert_not_called()
    assert not list(temp.iterdir()), "explicit cleanup leaked temporary snapshots"
    assert (home / "runtime").read_text() == "not a directory"
    return {"fallback_provider": "second", "retained_provider": "one", "explicit_cleanup": "complete"}


def file_alias_storage_fallback(fixture):
    runtime = fixture.home / "runtime"
    fixture.generation("one", mutable=True).rename(runtime)
    resource = runtime / "provider-data.txt"
    resource.write_text("ordinary plugin resource")
    alias = runtime / "provider-plugins"
    alias.symlink_to(resource.name)
    fixture.install(runtime)
    temp = runtime / "system-tmp"
    temp.mkdir()
    with patch.object(tempfile, "tempdir", str(temp)):
        old = fixture.profile()
    root = fixture.reloader._snapshot_root
    assert root.parent.samefile(temp)
    [copied] = root.glob("*/review-provider")
    for name in (resource.name, alias.name):
        assert (copied / name).read_text() == "ordinary plugin resource"
    (runtime / "version.json").write_text(json.dumps({"version": "second"}))
    fixture.refresh()
    assert fixture.headers(fixture.profile()) == "second"
    assert fixture.headers(old) == "one"
    fixture.reloader._cleanup_snapshots()
    assert list(temp.iterdir()) == []
    assert alias.is_symlink() and alias.samefile(resource)
    assert resource.read_text() == "ordinary plugin resource"
    return {"file_alias": "copied as payload", "fallback_cleanup": "complete"}


def normal_exit(plugin, *, fallback=False):
    # Persistent copies live below the account root; retain it until exit so
    # fixture deletion cannot bypass the application's real cleanup hook.
    home = Path(tempfile.mkdtemp(prefix="provider-exit-home-"))
    (home / "plugins").mkdir()
    (home / "plugins" / "github-copilot").symlink_to(plugin, target_is_directory=True)
    (home / "config.yaml").write_text("model:\n  provider: nous\n")
    os.environ.clear()
    os.environ.update(HOME=str(home), HERMES_HOME=str(home), PATH=os.defpath,
                      HERMES_DISABLE_LAZY_INSTALLS="1")
    if fallback:
        temp = block_persistent_snapshots(home, home)
    import providers
    from providers import plugin_reload
    assert providers.get_provider_profile("copilot") is not None
    root = plugin_reload._snapshot_root
    if fallback:
        assert root.parent.samefile(temp) and root.stat().st_mode & 0o077 == 0
        assert not (root / plugin_reload._OWNER_LOCK).exists()
    print(json.dumps({
        "snapshot_root": str(root),
        "fixture_root": str(home),
        "reaping_prefix": plugin_reload._REAPING_PREFIX,
    }))
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


EXTRA_PROVIDER = 'register_provider(ProviderProfile(name="review-added", aliases=("review-added-alias",), base_url="https://four.invalid", auth_type="api_key", env_vars=("REVIEW_ADDED_API_KEY",)))'


def discovery_clock(fixture):
    # Control only provider cadence; thread deadlines keep their real clocks.
    original = fixture.providers.time
    clock = types.SimpleNamespace(now=original.monotonic())
    fixture.providers.time = types.SimpleNamespace(monotonic=lambda: clock.now, time_ns=original.time_ns)
    return clock, original


def discovery_gate():
    gate = types.ModuleType("provider_discovery_scope_gate")
    gate.entered = {name: threading.Event() for name in ("older", "newer")}
    gate.release = {name: threading.Event() for name in ("older", "newer")}
    def pause(name):
        gate.entered[name].set()
        if not gate.release[name].wait(15):
            raise RuntimeError("discovery import gate timed out")
    gate.pause = pause
    sys.modules[gate.__name__] = gate
    return gate


def discovery_completion_order(fixture, first, *, auth_first=False):
    fixture.install(fixture.generation("one", mirror=True))
    old = fixture.profile()
    from hermes_cli.auth import PROVIDER_REGISTRY
    assert PROVIDER_REGISTRY.get("review-provider").inference_base_url == "https://one.invalid"
    clock, original_time = discovery_clock(fixture)
    gate = discovery_gate()
    errors, workers = [], {}
    def refresh():
        try:
            fixture.refresh()
        except BaseException as error:
            errors.append(error)
    try:
        for name, version in (("older", "second"), ("newer", "newest")):
            tail = f'import provider_discovery_scope_gate as g\ng.pause("{name}")'
            fixture.install(fixture.generation(version, tail=tail, mirror=True))
            worker = workers[name] = threading.Thread(target=refresh, daemon=True)
            worker.start()
            assert gate.entered[name].wait(15), (name, errors)
        second = "newer" if first == "older" else "older"
        for name in (first, second):
            gate.release[name].set()
            workers[name].join(15)
            assert not workers[name].is_alive(), name
        assert not errors, errors
        current = fixture.providers.bound_profile_resolver()("review-provider")[0]
        assert current.base_url == "https://newest.invalid" and fixture.headers(current) == "newest"
        assert fixture.headers(old) == "one"
        fixture.install(fixture.generation("four", tail=EXTRA_PROVIDER, mirror=True))
        clock.now += fixture.providers._PLUGIN_DIR_STAMP_TTL_SECONDS + 1
        # Discovery must happen before any direct lookup or explicit refresh.
        if auth_first:
            assert PROVIDER_REGISTRY.get("review-provider").inference_base_url == "https://four.invalid"
        added = fixture.providers.bound_profile_resolver()("review-added")[0]
        assert added is not None and added.base_url == "https://four.invalid"
        assert fixture.providers.bound_profile_resolver()("review-added-alias")[0] is added
        current = fixture.providers.bound_profile_resolver()("review-provider")[0]
        assert fixture.headers(current) == "four" and fixture.headers(old) == "one"
        assert PROVIDER_REGISTRY.get("review-provider").inference_base_url == "https://four.invalid"
        assert PROVIDER_REGISTRY.get("review-added-alias").id == "review-added"
        return {"completion_order": [first, second], "future_resolver": added.base_url, "auth_first": auth_first}
    finally:
        for event in gate.release.values():
            event.set()
        for worker in workers.values():
            worker.join(15)
        fixture.providers.time = original_time
        sys.modules.pop(gate.__name__, None)


def discovery_callback_scope(fixture):
    fixture.install(fixture.generation("one", mirror=True))
    old = fixture.profile()
    from hermes_cli.auth import PROVIDER_REGISTRY
    assert PROVIDER_REGISTRY.get("review-provider").inference_base_url == "https://one.invalid"
    gate = discovery_gate()
    clock, original_time = discovery_clock(fixture)
    tail = '''
register_provider(ProviderProfile(name="review-staged", base_url="https://second.invalid", auth_type="api_key", env_vars=("REVIEW_STAGED_API_KEY",)))
from providers import bound_profile_resolver, list_providers, refresh_bound_home
from hermes_cli.auth import PROVIDER_REGISTRY
PROVIDER_REGISTRY.sync_before_first_read()
assert PROVIDER_REGISTRY.get("review-provider").inference_base_url == "https://one.invalid"
assert bound_profile_resolver()("review-provider")[0].base_url == "https://one.invalid"
assert bound_profile_resolver()("review-staged")[0] is None
assert not any(p.name == "review-staged" for p in list_providers())
refresh_bound_home()
import provider_discovery_scope_gate as g
g.pause("older")
'''
    fixture.install(fixture.generation("second", tail=tail, mirror=True))
    errors = []
    def refresh():
        try:
            fixture.refresh()
        except BaseException as error:
            errors.append(error)
    worker = threading.Thread(target=refresh, daemon=True)
    try:
        worker.start()
        assert gate.entered["older"].wait(15), errors
        extra = fixture.root / "independent-provider"
        extra.mkdir()
        (extra / "plugin.yaml").write_text("name: review-added\nkind: model-provider\n")
        (extra / "__init__.py").write_text("from providers import register_provider\nfrom providers.base import ProviderProfile\n" + EXTRA_PROVIDER)
        (fixture.home / "plugins" / "independent-provider").symlink_to(extra, target_is_directory=True)
        clock.now += fixture.providers._PLUGIN_DIR_STAMP_TTL_SECONDS + 1
        assert PROVIDER_REGISTRY.get("review-provider").inference_base_url == "https://one.invalid"
        added = fixture.providers.bound_profile_resolver()("review-added")[0]
        assert added is not None and added.base_url == "https://four.invalid"
        assert fixture.providers.bound_profile_resolver()("review-staged")[0] is None
        assert fixture.headers(old) == "one"
    finally:
        gate.release["older"].set()
        worker.join(15)
        fixture.providers.time = original_time
        sys.modules.pop(gate.__name__, None)
    assert not worker.is_alive() and not errors, errors
    assert PROVIDER_REGISTRY.get("review-provider").inference_base_url == "https://second.invalid"
    assert fixture.providers.get_provider_profile("review-staged") is not None
    assert fixture.providers.get_provider_profile("review-added") is added
    return {"import_callback": "previous publication", "observer": "independent discovery"}


def discovery_failure_scope(fixture, *, cancel=False):
    fixture.install(fixture.generation("one", mirror=True))
    old = fixture.profile()
    clock, original_time = discovery_clock(fixture)
    errors = []
    tail = 'raise SystemExit("cancelled import")' if cancel else 'raise RuntimeError("failed import")'
    fixture.install(fixture.generation("second", tail=tail, mirror=True))
    def refresh():
        try:
            fixture.refresh()
        except BaseException as error:
            errors.append(error)
    worker = threading.Thread(target=refresh, daemon=True)
    try:
        worker.start()
        worker.join(15)
        assert not worker.is_alive()
        if cancel:
            assert len(errors) == 1 and isinstance(errors[0], SystemExit), errors
        else:
            assert not errors and "failed import" in fixture.providers.plugin_load_error("review-provider")
        assert fixture.providers.bound_profile_resolver()("review-provider")[0] is old
        fixture.install(fixture.generation("four", tail=EXTRA_PROVIDER, mirror=True))
        clock.now += fixture.providers._PLUGIN_DIR_STAMP_TTL_SECONDS + 1
        added = fixture.providers.bound_profile_resolver()("review-added-alias")[0]
        assert added is not None and added.name == "review-added"
        assert fixture.headers(fixture.providers.bound_profile_resolver()("review-provider")[0]) == "four"
        assert fixture.headers(old) == "one"
        return {"cancelled": cancel, "recovery": added.base_url}
    finally:
        worker.join(15)
        fixture.providers.time = original_time


def discovery_global_guard(fixture):
    fixture.install(fixture.generation("one", mirror=True))
    from hermes_cli.auth import PROVIDER_REGISTRY
    PROVIDER_REGISTRY.sync_before_first_read()
    entered, release = threading.Event(), threading.Event()
    original_steps = fixture.providers._run_discovery_steps
    errors = []
    def paused_steps():
        entered.set()
        if not release.wait(15):
            raise RuntimeError("global discovery gate timed out")
        return original_steps()
    def discover():
        try:
            fixture.providers.list_providers()
        except BaseException as error:
            errors.append(error)
    fixture.providers._run_discovery_steps = paused_steps
    worker = threading.Thread(target=discover, daemon=True)
    try:
        worker.start()
        assert entered.wait(15), errors
        assert PROVIDER_REGISTRY.get("review-provider") is None
        assert dict.get(PROVIDER_REGISTRY, "review-provider") is None
    finally:
        release.set()
        worker.join(15)
        fixture.providers._run_discovery_steps = original_steps
    assert not worker.is_alive() and not errors, errors
    row = PROVIDER_REGISTRY.get("review-provider")
    assert row is not None and row.inference_base_url == "https://one.invalid"
    assert PROVIDER_REGISTRY.get("review-alias") is row
    assert fixture.headers(fixture.profile()) == "one"
    return {"global_pending_mirror": "deferred", "final_provider": row.id}


def run_case(case, plugin):
    if case in {"normal-exit", "temporary-exit"}:
        normal_exit(plugin, fallback=case == "temporary-exit")
        return
    root = Path(tempfile.mkdtemp(prefix="provider-lifecycle-"))
    hosted = case in {"rollback-host", "host-live", "host-late", "host-overlap", "host-cleanup",
                      "host-cleanup-sweep", "interrupt-host", "long-host"}
    fixture = Fixture(root, plugin, "host" if hosted else "in_process")
    try:
        if case.startswith("rollback"):
            result = rollback(fixture)
        elif case == "resources":
            result = resource_identity(fixture)
        elif case == "linked-snapshot-storage":
            result = linked_snapshot_storage(fixture)
        elif case in {"equal-snapshot-storage", "ancestor-snapshot-storage"}:
            result = overlapping_snapshot_storage(fixture, equal=case.startswith("equal-"))
        elif case == "case-variant-snapshot-storage":
            result = case_variant_snapshot_storage(fixture)
        elif case == "file-alias-storage-fallback":
            result = file_alias_storage_fallback(fixture)
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
        elif case == "host-cleanup-sweep":
            result = host_cleanup_during_sweep(fixture)
        elif case == "persistent-cleanup":
            result = persistent_cleanup(fixture)
        elif case == "foreign-snapshot-owners":
            result = foreign_snapshot_owners(fixture)
        elif case == "temporary-cleanup":
            result = temporary_cleanup(fixture)
        elif case == "owner-lock-failure":
            result = owner_lock_failure(fixture)
        elif case.startswith("owner-lock-"):
            result = owner_lock_storage_fallback(fixture, getattr(errno, case.removeprefix("owner-lock-").upper()))
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
        elif case in {"discovery-old-first", "discovery-new-first", "discovery-auth"}:
            first = "newer" if case == "discovery-new-first" else "older"
            result = discovery_completion_order(fixture, first, auth_first=case == "discovery-auth")
        elif case == "discovery-callback":
            result = discovery_callback_scope(fixture)
        elif case in {"discovery-failure", "discovery-cancel"}:
            result = discovery_failure_scope(fixture, cancel=case == "discovery-cancel")
        elif case == "discovery-global":
            result = discovery_global_guard(fixture)
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
        if case in {"normal-exit", "temporary-exit"}:
            try:
                root = Path(result["snapshot_root"])
                self.assertFalse(root.exists(), result)
                self.assertEqual(list(root.parent.glob(f"{result['reaping_prefix']}*")), [])
                if case == "temporary-exit":
                    self.assertEqual(list(root.parent.iterdir()), [])
                    self.assertEqual((Path(result["fixture_root"]) / "runtime").read_text(), "not a directory")
            finally:
                remove_fixture(Path(result["fixture_root"]))
        print(case, result)

    def test_rollback(self):
        self.run_case("rollback")

    def test_rollback_host(self):
        self.run_case("rollback-host")

    def test_same_size_resources_and_old_lazy_reads(self):
        self.run_case("resources")

    def test_linked_provider_excludes_canonical_snapshot_storage(self):
        self.run_case("linked-snapshot-storage")

    def test_linked_provider_can_equal_snapshot_storage(self):
        self.run_case("equal-snapshot-storage")

    def test_linked_provider_can_be_inside_snapshot_storage(self):
        self.run_case("ancestor-snapshot-storage")

    def test_case_variant_snapshot_storage(self):
        self.run_case("case-variant-snapshot-storage")

    def test_file_alias_storage_fallback_preserves_payload(self):
        self.run_case("file-alias-storage-fallback")

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

    def test_forced_host_cleanup_during_slow_fallback_sweep(self):
        self.run_case("host-cleanup-sweep")

    def test_normal_exit_cleanup(self):
        self.run_case("normal-exit")

    def test_temporary_exit_cleanup(self):
        self.run_case("temporary-exit")

    def test_temporary_provider_and_explicit_cleanup(self):
        self.run_case("temporary-cleanup")

    def test_persistent_readonly_reclamation_preserves_live_owner(self):
        self.run_case("persistent-cleanup")

    def test_persistent_sweep_does_not_claim_foreign_uid_roots(self):
        self.run_case("foreign-snapshot-owners")

    def test_owner_lock_failure_recovers_after_purge_failure(self):
        self.run_case("owner-lock-failure")

    def test_owner_lock_access_error_uses_temporary_root(self):
        self.run_case("owner-lock-eacces")

    def test_owner_lock_space_error_uses_temporary_root(self):
        self.run_case("owner-lock-enospc")

    def test_owner_lock_quota_error_uses_temporary_root(self):
        self.run_case("owner-lock-edquot")

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

    def test_discovery_old_import_finishes_first(self):
        self.run_case("discovery-old-first")

    def test_discovery_new_import_finishes_first(self):
        self.run_case("discovery-new-first")

    def test_auth_discovers_after_overlapping_imports(self):
        self.run_case("discovery-auth")

    def test_import_callback_and_observer_contexts(self):
        self.run_case("discovery-callback")

    def test_failed_import_restores_discovery_context(self):
        self.run_case("discovery-failure")

    def test_cancelled_import_restores_discovery_context(self):
        self.run_case("discovery-cancel")

    def test_global_discovery_defers_pending_auth_mirror(self):
        self.run_case("discovery-global")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--case"]:
        run_case(sys.argv[2], Path(sys.argv[3]).resolve())
    else:
        PLUGIN = Path(sys.argv.pop(1)).resolve()
        unittest.main(verbosity=2)
