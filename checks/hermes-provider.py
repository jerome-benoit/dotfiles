"""Exercise Copilot discovery with writable directories and immutable plugin files."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

plugin, linked_plugin, lndir = sys.argv[1:]
sys.dont_write_bytecode = True

with tempfile.TemporaryDirectory(prefix="hermes-provider-check-") as temporary:
    home = Path(temporary)
    state = home / "hermes"
    destination = state / "plugins" / "github-copilot"

    def project(source, target):
        target.mkdir(parents=True)
        subprocess.run([lndir, "-silent", source, target], check=True)

    projection = home / "projected"
    project(linked_plugin, projection)
    assert (projection / "__init__.py").read_text() == "VALUE = 1\n"
    assets = projection / "assets"
    assert not assets.is_symlink() and os.access(assets, os.W_OK)
    assert (assets / "module.py").read_text() == "VALUE = 1\n"

    project(plugin, destination)
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
