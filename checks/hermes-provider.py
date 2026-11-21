"""Exercise Copilot discovery with writable directories and immutable plugin files."""

import os
from pathlib import Path
import sys
import tempfile

plugin = Path(sys.argv[1]).resolve()
sys.dont_write_bytecode = True

with tempfile.TemporaryDirectory(prefix="hermes-provider-check-") as temporary:
    home = Path(temporary)
    state = home / "hermes"
    destination = state / "plugins" / "github-copilot"
    # Home Manager recursively links files into user-owned directories.
    for directory, dirs, files in os.walk(plugin):
        source = Path(directory)
        target = destination / source.relative_to(plugin)
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            (target / name).symlink_to(source / name)
        for name in dirs:
            if (source / name).is_symlink():
                (target / name).symlink_to(source / name, target_is_directory=True)
    (state / "config.yaml").write_text("model:\n  provider: nous\n")
    os.environ.clear()
    os.environ.update(HOME=str(home), HERMES_HOME=str(state), PATH=os.defpath)

    import providers
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
    print("Declarative Copilot discovery and offline request projection passed")
