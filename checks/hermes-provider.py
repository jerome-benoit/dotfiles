"""Exercise provider discovery and snapshot cleanup for read-only plugin sources."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

from hermes_cli.home_data_layout import PROVIDER_PLUGIN_SNAPSHOT_PARTS


if len(sys.argv) == 2:
    plugin = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="hermes-provider-check-") as temporary:
        home = Path(temporary)
        state = home / "hermes"
        (state / "plugins").mkdir(parents=True)
        (state / "plugins" / "github-copilot").symlink_to(plugin, target_is_directory=True)
        (state / "config.yaml").write_text("model:\n  provider: nous\n")
        subprocess.run(
            [sys.executable, "-I", "-B", __file__, "--discover", str(state)],
            env={"HOME": str(home), "HERMES_HOME": str(state), "PATH": os.defpath},
            check=True,
        )
        store = state.joinpath(*PROVIDER_PLUGIN_SNAPSHOT_PARTS)
        leftovers = [entry for entry in store.iterdir() if entry.is_dir()]
        assert not leftovers, f"Provider snapshots left after exit: {leftovers}"
    print("Declarative Copilot discovery, offline request projection and snapshot cleanup passed")
else:
    flag, state = sys.argv[1:]
    assert flag == "--discover", flag

    import providers
    from providers.plugin_reload import _snapshot
    from hermes_cli.plugins import PluginManager

    PluginManager().discover_and_load(force=True)
    profile = providers.get_provider_profile("copilot")
    assert profile is not None, providers.plugin_load_error("github-copilot")
    assert providers.get_provider_profile("copilot-acp") is not None
    for model, effort, expected in (
        ("gpt-6-astra", "max", "max"),
        ("gemini-4-carbon", "max", "high"),
        ("claude-opus-5.5", "xhigh", "xhigh"),
    ):
        extra, top = profile.build_api_kwargs_extras(
            model=model,
            reasoning_config={"enabled": True, "effort": effort},
            supports_reasoning=True,
        )
        assert extra == {} and top == {"reasoning_effort": expected}, (model, extra, top)
        print(model, effort, "=>", top)
    assert profile.build_api_kwargs_extras(
        model="gemini-4-carbon",
        reasoning_config={"enabled": False, "effort": "high"},
        supports_reasoning=True,
    ) == ({}, {})
    store = Path(state).joinpath(*PROVIDER_PLUGIN_SNAPSHOT_PARTS)
    assert any(store.glob("*/*/github-copilot/__init__.py")), "Discovery did not create a snapshot"

    with tempfile.TemporaryDirectory(dir=state) as temporary:
        source = Path(temporary) / "broken-provider"
        source.mkdir()
        (source / "__init__.py").touch()
        (source / "missing-resource").symlink_to("absent")
        source.chmod(0o555)
        try:
            try:
                _snapshot(source, "broken-provider")
            except OSError:
                pass
            else:
                raise AssertionError("Snapshot unexpectedly accepted a dangling resource link")
            assert not list(store.glob("*/broken-provider/.copy-*")), "Partial snapshot left after failed copy"
        finally:
            source.chmod(0o755)
