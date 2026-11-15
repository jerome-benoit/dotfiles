"""Exercise the selected Copilot provider through normal immutable-plugin discovery."""

import os
from pathlib import Path
import sys
import tempfile

plugin = Path(sys.argv[1]).resolve()
sys.dont_write_bytecode = True

with tempfile.TemporaryDirectory(prefix="hermes-provider-check-") as temporary:
    home = Path(temporary)
    state = home / "hermes"
    (state / "plugins").mkdir(parents=True)
    (state / "plugins" / "github-copilot").symlink_to(plugin, target_is_directory=True)
    (state / "config.yaml").write_text("model:\n  provider: nous\n")
    os.environ.clear()
    os.environ.update(HOME=str(home), HERMES_HOME=str(state), PATH=os.defpath)

    import providers
    from providers import plugin_reload

    fingerprint = plugin_reload.tree_fingerprint(plugin)
    try:
        profile = providers.get_provider_profile("copilot")
        assert profile is not None, providers.plugin_load_error("github-copilot")
        assert providers.get_provider_profile("copilot-acp") is not None
        assert plugin_reload._snapshot_root is not None, "immutable provider must be staged"
        snapshots = list(plugin_reload._snapshot_root.glob("*/github-copilot"))
        assert len(snapshots) == 1, snapshots
        assert snapshots[0].name == plugin.name
        assert plugin_reload.tree_fingerprint(snapshots[0]) == fingerprint
        assert os.stat(snapshots[0]).st_mode == os.stat(plugin).st_mode
        assert os.access(snapshots[0].parent, os.W_OK), "publication parent must stay writable"
        from hermes_cli.plugins import PluginManager

        PluginManager().discover_and_load(force=True)
        assert providers.get_provider_profile("copilot") is profile, "unchanged sweep must reuse the tree"
        assert plugin_reload.tree_fingerprint(plugin) == fingerprint, "discovery must not change the source"
        assert not list(plugin_reload._snapshot_root.glob(".copy-*")), "private staging tree leaked"
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
        print("Immutable Copilot discovery, unchanged forced reload and offline request projection passed")
    finally:
        # Only owned snapshots need writable directories for cleanup; never touch the Nix source.
        if plugin_reload._snapshot_root is not None:
            for directory, _, _ in os.walk(plugin_reload._snapshot_root):
                Path(directory).chmod(0o700)
