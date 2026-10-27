"""Exercise generated registrations through a lexical profile, not source text.

Usage: caveman-profiles.py PACKAGE ABSOLUTE_GIT ABSOLUTE_NODE TYPEBOX_PACKAGE FILTERED_PROFILE NESTED_PROFILE

A/B are owned copies of the installed payload and native executables, with the
same CLI version. Removing A models unavailable executable generations, not a
Nix rebuild or garbage collection. Native host discovery uses real Node version
probes under host names; event harnesses exercise the generated integrations,
not a running Claude/Codex/Gemini/Hermes/OpenCode/Pi application. No host SDK is
fabricated. Host-delegated installers and OpenClaw's SDK need separate host E2E.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib
import yaml


PACKAGE = Path(sys.argv[1]).absolute()
GIT = Path(sys.argv[2])
NODE = Path(sys.argv[3])
TYPEBOX = Path(sys.argv[4])
PROFILES = (Path(sys.argv[5]), Path(sys.argv[6]))
SERVERS = {
    "caveman": "caveman_retrieve",
    "caveman-browse": "browser_snapshot",
    "caveman-cloud": "caveman_context",
    "caveman-delegate": "caveman_delegate",
}
DIRECT_MCP = ("codex", "gemini", "hermes", "opencode", "kilo", "qwen")
NATIVE = ("claude", "codex", "gemini", "hermes", "opencode", "pi", "aider")
COMPANIONS = {
    "caveman-proxy": "CAVEMAN_PROXY_BIN",
    "caveman-engine": "CAVEMAN_ENGINE_BIN",
    "caveman-mcp": "CAVEMAN_MCP_BIN",
    "caveman-browse": "CAVEMAN_BROWSE_BIN",
    "caveman-shrink": "CAVEMAN_SHRINK_BIN",
    "cavemem": "CAVEMEM_BIN",
}


def execute(argv, env, *, data=None, cwd=None, check=True):
    result = subprocess.run(
        [str(value) for value in argv], env=env, cwd=cwd,
        input=data, capture_output=True, timeout=45,
    )
    if check and result.returncode:
        raise AssertionError(
            f"{argv!r}: exit {result.returncode}\n"
            f"stdout: {result.stdout.decode(errors='replace')}\n"
            f"stderr: {result.stderr.decode(errors='replace')}"
        )
    return result


def put(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)
    return path


def load(path):
    return json.loads(path.read_text())


def mcp_exchange(argv, server, env, cwd, *, extra_requests=()):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "profile-check", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        *extra_requests,
    ]
    result = execute(argv, env, cwd=cwd,
                     data=b"".join((json.dumps(item) + "\n").encode() for item in requests))
    replies = {item["id"]: item for line in result.stdout.splitlines()
               if (item := json.loads(line)).get("id") is not None}
    assert "error" not in replies[1], replies
    assert replies[1]["result"]["protocolVersion"], replies
    tools = replies[2]["result"]["tools"]
    assert SERVERS[server] in {tool["name"] for tool in tools}, replies
    return replies


def native_executable(path):
    """Unwrap only fixture inputs; never edit the installed package/store."""
    path = path.resolve()
    for _ in range(8):
        with path.open("rb") as stream:
            magic = stream.read(2)
        if magic != b"#!":
            return path
        lines = path.read_text().splitlines()
        candidates = []
        for line in lines:
            if line.lstrip().startswith("exec "):
                candidates.extend(
                    Path(token) for token in shlex.split(line)
                    if token.startswith("/") and Path(token).is_file()
                )
        assert candidates, f"Cannot find executable behind {path}"
        path = candidates[0].resolve()
    raise AssertionError(f"Wrapper cycle at {path}")


def shell_interpreter():
    first = (PACKAGE / "bin/caveman").read_text().splitlines()[0]
    return shlex.split(first.removeprefix("#!").strip())[0]


def short_native_state():
    """Keep native.sock within Darwin's 103-byte pathname limit."""
    for parent in dict.fromkeys((tempfile.gettempdir(), "/tmp")):
        state = Path(tempfile.mkdtemp(prefix="cv-", dir=parent)).resolve()
        if len(os.fsencode(state / "run/native.sock")) <= 103:
            return state
        shutil.rmtree(state)
    raise AssertionError("Cannot allocate a native state directory with a socket path within 103 bytes")


class Fixture:
    def __init__(self, root, *, cave):
        self.root = root
        self.home = root / "home"
        self.home.mkdir(parents=True)
        self.cave = cave
        self.profile = root / "profile space ' quote"
        self.hosts = root / "host-probes"
        self.hosts.mkdir()
        # These are actual version probes, not host emulators. No MCP command is
        # ever delegated to them. Native writers themselves own the file writes.
        for name in NATIVE:
            (self.hosts / name).symlink_to(NODE)
        self.env = {
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "CAVEMAN_HOME": str(self.cave),
            "PATH": str(self.hosts), "CAVE_NO_KEYCHAIN": "1",
            "CAVEMAN_OFFLINE": "1", "CAVEMAN_NIX_MANAGED": "1",
            "CAVEMAN_TELEMETRY": "0", "DO_NOT_TRACK": "1",
            "CI": "1", "NO_COLOR": "1", "TERM": "dumb",
            "CAVEMAN_CORE": "true", "CAVEMAN_NATIVE_PROFILE": "full-safe",
            # A nonlocal route suppresses background local proxy startup. Native
            # Core and command-output rewriting still execute locally. The
            # callback's native socket may be absent; Core output must not be.
            "CAVE_GATEWAY_URL": "https://gateway.example.invalid",
        }
        self.a = self.generation("generation-A")
        self.b = self.generation("generation-B")
        self.switch(self.a)
        self.repo = root / "repository"
        self.repo.mkdir()
        self.git("init", "--initial-branch=main")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-m", "profile fixture\n\n" + "fixture detail\n" * 160)
        self.command = "git log -1 --format=%B"
        self.original_log = self.git("log", "-1", "--format=%B").stdout
        self.original = json.dumps({"rows": [{"id": i, "label": "café"} for i in range(128)]}).encode()
        report = self.cli("tools", "compress", "--type", "json", data=self.original)
        self.handle = json.loads(report.stderr)["recovery_handle"]
        assert report.stdout != self.original

    def generation(self, name):
        out = self.root / name
        private = out / "lib/caveman"
        private.mkdir(parents=True)
        (out / "bin").mkdir()
        shutil.copytree(PACKAGE / "lib/caveman/dist", private / "dist")
        for directory, _, _ in os.walk(private / "dist"):
            Path(directory).chmod(0o755)
        shutil.copy2(native_executable(NODE), private / ".node-real")
        (private / ".node-real").chmod(0o755)
        put(private / "package.json", '{"type":"module"}\n')
        for name in COMPANIONS:
            if name == "caveman-browse":
                put(out / "bin" / name, f"#!{shell_interpreter()}\nexec "
                    + shlex.join([str(PACKAGE / "bin" / name)]) + ' "$@"\n', 0o755)
            else:
                shutil.copy2(native_executable(PACKAGE / "bin" / name), out / "bin" / name)
                (out / "bin" / name).chmod(0o755)
        exports = {
            "CAVEMAN_NIX_MANAGED": "1",
            "CAVEMAN_REGISTRATION_ROOT": str(self.profile),
            **{variable: str(out / "bin" / name) for name, variable in COMPANIONS.items()},
        }
        setup = "\n".join(f"export {key}={shlex.quote(value)}" for key, value in exports.items())
        setup += f'\nexport PATH={shlex.quote(str(out / "bin") + ":" + str(GIT.parent))}:"${{PATH:-}}"\n'
        for destination, suffix in [
            (out / "bin/caveman", [str(private / "dist/index.js")]),
            (private / "node", []),
        ]:
            put(destination, f"#!{shell_interpreter()}\n{setup}\nexec "
                + shlex.join([str(private / ".node-real"), *suffix]) + ' "$@"\n', 0o755)
        (out / "bin/cave").symlink_to("caveman")
        return out

    def switch(self, target):
        if self.profile.is_symlink():
            self.profile.unlink()
        self.profile.symlink_to(target, target_is_directory=True)

    def cli(self, *args, data=None, check=True, env=None):
        return execute([self.profile / "bin/caveman", *args], env or self.env,
                       data=data, cwd=self.repo if hasattr(self, "repo") else self.root, check=check)

    def git(self, *args):
        return execute([GIT, "-c", "core.hooksPath=/dev/null", *args],
                       {**self.env, "GIT_CONFIG_NOSYSTEM": "1"}, cwd=self.repo)

    def node(self, source, *args, env=None):
        return execute([self.profile / "lib/caveman/.node-real", "--input-type=module", "-e", source, *args],
                       env or self.env, cwd=self.repo)

    def unavailable_a(self):
        shutil.rmtree(self.a)
        assert not self.a.exists()

    def paths(self, agent):
        home = self.home
        return {
            "claude": home / ".claude.json",
            "codex": home / ".codex/config.toml",
            "gemini": home / ".gemini/settings.json",
            "hermes": home / ".hermes/config.yaml",
            "opencode": home / ".config/opencode/opencode.json",
            "kilo": home / ".config/kilo/kilo.json",
            "qwen": home / ".qwen/settings.json",
        }[agent]

    def registration(self, agent, server="caveman"):
        path = self.paths(agent)
        if agent == "codex":
            entry = tomllib.loads(path.read_text())["mcp_servers"][server]
        elif agent == "hermes":
            entry = yaml.safe_load(path.read_text())["mcp_servers"][server]
        else:
            document = load(path)
            section = "mcp" if agent in ("opencode", "kilo") else "mcpServers"
            entry = document[section][server]
        command = entry["command"]
        return command if isinstance(command, list) else [command, *entry.get("args", [])]

    def mcp(self, argv, server, *, recover=False, env=None):
        requests = []
        if recover:
            requests.append({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "caveman_retrieve", "arguments": {"recovery_handle": self.handle},
            }})
        replies = mcp_exchange(argv, server, env or {**self.env, "PATH": ""},
                               self.repo, extra_requests=requests)
        if recover:
            response = replies[3]["result"]
            assert not response.get("isError"), response
            recovered = "".join(item.get("text", "") for item in response["content"])
            assert recovered.encode() == self.original, response
        return replies

    def hooks(self, agent, event, token):
        path = {
            "claude": self.home / ".claude/settings.json",
            "codex": self.home / ".codex/hooks.json",
            "gemini": self.home / ".gemini/settings.json",
        }[agent]
        return [hook["command"] for entry in load(path)["hooks"][event]
                for hook in entry.get("hooks", [entry]) if token in hook.get("command", "")]

    def callback(self, command, payload):
        return execute(shlex.split(command), {**self.env, "PATH": ""}, cwd=self.repo,
                       data=json.dumps(payload).encode())

    def assert_rewritten(self, rewritten):
        assert rewritten != self.command, rewritten
        argv = shlex.split(rewritten)
        assert "shrink" in argv, argv
        result = execute(argv, {**self.env, "PATH": ""}, cwd=self.repo)
        report = json.loads(result.stderr)
        assert result.stdout != self.original_log and report["recovery_handle"], report
        assert self.cli("tools", "retrieve", report["recovery_handle"]).stdout == self.original_log


def mcp_lifetime(f):
    # Six direct installer schemas plus Claude's native writer make seven real
    # agent configurations. Claude/OpenClaw's delegated MCP CLI is not mocked.
    for agent in DIRECT_MCP:
        for server in SERVERS:
            f.cli("tools", "mcp", "install", agent, "--server", server)
            argv = f.registration(agent, server)
            f.mcp(argv, server, recover=server == "caveman")
    f.cli("enable", "claude")
    f.mcp(f.registration("claude"), "caveman", recover=True)
    before = {
        agent: {server: f.registration(agent, server) for server in SERVERS}
        for agent in DIRECT_MCP
    }
    # Both generations have exactly the same version and payload bytes.
    assert (f.a / "lib/caveman/dist/index.js").read_bytes() == (f.b / "lib/caveman/dist/index.js").read_bytes()
    version = f.cli("--version").stdout
    f.switch(f.b)
    assert f.cli("--version").stdout == version
    f.unavailable_a()
    for agent in (*DIRECT_MCP, "claude"):
        for server in SERVERS if agent != "claude" else ("caveman",):
            argv = f.registration(agent, server)
            assert not any(str(f.a) in part for part in argv), argv
            f.mcp(argv, server, recover=server == "caveman")
    # Reinstall preserves every server invocation. Legacy serializers may
    # normalize document whitespace without changing any registration.
    for agent in DIRECT_MCP:
        for server in SERVERS:
            f.cli("tools", "mcp", "install", agent, "--server", server)
        assert {server: f.registration(agent, server) for server in SERVERS} == before[agent]
        f.mcp(f.registration(agent), "caveman", recover=True)
    # Roll back copied payloads through the lexical profile, without Nix activation.
    f.a = f.generation("generation-A")
    f.switch(f.a)
    assert f.cli("--version").stdout == version
    f.mcp(f.registration("gemini"), "caveman", recover=True)


def custom_delegate(f):
    # Explicit Delegate payloads must survive profile changes unchanged.
    override = f.root / "delegate source ' custom.mjs"
    shutil.copy2(PACKAGE / "lib/caveman/dist/caveman-delegate-mcp.mjs", override)
    shutil.copy2(PACKAGE / "lib/caveman/dist/portable-process.mjs", f.root / "portable-process.mjs")
    environment = {**f.env, "CAVEMAN_DELEGATE_MCP": str(override)}
    f.cli("tools", "mcp", "install", "gemini", "--server", "caveman-delegate", env=environment)
    argv = f.registration("gemini", "caveman-delegate")
    assert argv == [str(f.profile / "lib/caveman/node"), str(override)], argv
    f.mcp(argv, "caveman-delegate")
    f.switch(f.b)
    f.unavailable_a()
    f.mcp(argv, "caveman-delegate")


def shrink_callbacks(f):
    for agent in ("claude", "gemini", "opencode", "hermes", "openclaw", "codex"):
        f.cli("tools", "hooks", "install", agent)
    callbacks = {}
    for agent, event in (("claude", "PreToolUse"), ("gemini", "BeforeTool")):
        values = f.hooks(agent, event, "shrink-hook")
        assert len(values) == 1, (agent, values)
        callbacks[agent] = values[0]
    # Codex does not support shell-command rewriting.
    codex_hooks = f.home / ".codex/hooks.json"
    if codex_hooks.exists():
        assert not f.hooks("codex", "PreToolUse", "shrink-hook")
    f.switch(f.b)
    f.unavailable_a()
    for agent, command in callbacks.items():
        payload = {"tool_name": "Bash" if agent == "claude" else "run_shell_command",
                   "tool_input": {"command": f.command}}
        response = json.loads(f.callback(command, payload).stdout)
        input_key = "updatedInput" if agent == "claude" else "tool_input"
        f.assert_rewritten(response["hookSpecificOutput"][input_key]["command"])
    plugin = f.home / ".config/opencode/plugins/caveman-shrink.js"
    source = r'''
import {pathToFileURL} from "node:url";
const module = await import(pathToFileURL(process.argv[1]));
const hooks = await module.CavemanShrink();
const output = {args:{command:process.argv[2]}};
await hooks["tool.execute.before"]({tool:"bash"}, output);
console.log(JSON.stringify(output));
'''
    output = json.loads(f.node(source, plugin, f.command, env={**f.env, "PATH": ""}).stdout)
    f.assert_rewritten(output["args"]["command"])
    # Load Hermes' actual generated Python module with its public register API.
    hermes = f.home / ".hermes/plugins/caveman_shrink/__init__.py"
    spec = importlib.util.spec_from_file_location("generated_hermes_shrink", hermes)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registered = {}
    class Host:
        def register_hook(self, name, handler):
            registered[name] = handler
    module.register(Host())
    old = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update({**f.env, "PATH": "", "CAVE_HERMES_SHRINK_MIN_BYTES": "1"})
        compressed = registered["transform_terminal_output"](command=f.command, output=f.original_log.decode())
    finally:
        os.environ.clear()
        os.environ.update(old)
    assert isinstance(compressed, str) and compressed != f.original_log.decode(), compressed
    handle = re.search(r"ccr_[A-Za-z0-9_-]+", compressed)
    assert handle, compressed
    assert f.cli("tools", "retrieve", handle[0]).stdout == f.original_log
    # OpenClaw installation uses the CLI; execution requires its plugin-sdk/plugin-entry.
    assert (f.cave / "openclaw/plugins/caveman-shrink/openclaw.plugin.json").is_file()
    for agent in ("claude", "gemini", "opencode", "hermes", "openclaw"):
        f.cli("tools", "hooks", "uninstall", agent)
    assert not plugin.exists()
    assert not hermes.exists()
    assert not (f.cave / "openclaw/plugins/caveman-shrink/index.mjs").exists()


def native_contexts(f):
    contexts = {}
    for agent in ("claude", "codex", "gemini"):
        commands = f.hooks(agent, "SessionStart", "native-hook")
        assert len(commands) == 1, commands
        result = json.loads(f.callback(commands[0], {
            "hook_event_name": "SessionStart", "session_id": "profile-" + agent,
            "cwd": str(f.repo), "source": "startup",
        }).stdout)
        contexts[agent] = result["hookSpecificOutput"]["additionalContext"]
    source = r'''
import {pathToFileURL} from "node:url";
const plugin = await import(pathToFileURL(process.argv[1]));
const output = {system:[]};
if (plugin.CavemanNative) {
  const hooks = await plugin.CavemanNative();
  await hooks["experimental.chat.system.transform"]({sessionID:"profile-opencode"}, output);
  await hooks.dispose();
} else {
  const hooks = new Map();
  const dispose = await plugin.default.setup({
    location:{directory:process.cwd(), workspaceID:"profile"},
    event:{async *subscribe(){}},
    session:{async hook(name, handler){hooks.set(name, handler);}},
    tool:{async hook(){}},
  });
  await hooks.get("context")({sessionID:"profile-opencode", system:output.system});
  output.system = output.system.map(item => item.text);
  dispose();
}
console.log(JSON.stringify(output));
'''
    opencode = f.home / ".config/opencode/plugins/caveman-native.js"
    contexts["opencode"] = json.loads(f.node(source, opencode, env={**f.env, "PATH": ""}).stdout)
    hermes = f.home / ".hermes/plugins/caveman_native/__init__.py"
    spec = importlib.util.spec_from_file_location("generated_hermes_native", hermes)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handlers = {}
    class Host:
        def register_hook(self, name, handler):
            handlers[name] = handler
    module.register(Host())
    old = os.environ.copy()
    previous_cwd = os.getcwd()
    try:
        os.environ.clear()
        os.environ.update({**f.env, "PATH": ""})
        os.chdir(f.repo)
        response = handlers["pre_llm_call"](session_id="profile-hermes", user_message="Review profile durability")
    finally:
        os.chdir(previous_cwd)
        os.environ.clear()
        os.environ.update(old)
    contexts["hermes"] = response["context"]
    return contexts


def hermes_yaml(f):
    # Both real writers must preserve Hermes' directive and existing list shape.
    config = f.paths("hermes")
    for native in (False, True):
        for width in (2, 4):
            put(config, "# user header\n\n%YAML 1.1\n---\nplugins:\n  enabled:\n"
                + " " * width + "- existing\n_config_version: 52\n")
            arguments = ("enable", "hermes") if native else ("tools", "hooks", "install", "hermes")
            plugin = "caveman_native" if native else "caveman_shrink"
            for _ in range(2):
                f.cli(*arguments)
                document = yaml.safe_load(config.read_text())
                assert document["plugins"]["enabled"] == [plugin, "existing"], document
                assert document["_config_version"] == 52, document
                if native:
                    assert document["model"]["base_url"] == f.env["CAVE_GATEWAY_URL"] + "/w/hermes/v1"
            if native:
                f.cli("disable", "hermes")
            else:
                f.cli("tools", "hooks", "uninstall", "hermes")


def hermes_semantic_ownership(f):
    # Only Hermes is enabled here: another host's registration would conceal a
    # false negative in the global recovery status after Hermes rewrites YAML.
    config = f.paths("hermes")
    journal_path = f.cave / "integrations/hermes.json"
    plain_plugins = ["3d-tools", "1password", "1.2.3", "1e3-tools",
                     "0x10-plugin", "2026-10-27-plugin", "-helper", "?helper",
                     ":helper", "-1-helper", "-0x10-plugin", "team:helper", "team#helper"]
    foreign_servers = {
        name: {"command": "/foreign/mcp", "args": [name]}
        for name in ("foreign", "team/github", "my server", "équipe/工具", "team:github", "team#github")
    }
    original = {
        "model": {"provider": "anthropic", "base_url": "https://api.anthropic.com",
                  "default": "claude-sonnet-4-5", "foreign": {"keep": ["café", 7]}},
        "plugins": {"enabled": ["existing", "café", *plain_plugins], "foreign": {"keep": True}},
        "mcp_servers": foreign_servers,
        "_config_version": 52,
    }
    put(config, yaml.safe_dump(original, sort_keys=False, allow_unicode=True))
    # Nonlocal routing isolates YAML ownership from proxy startup.
    f.cli("enable", "hermes")
    journal_before = journal_path.read_bytes()
    document = yaml.safe_load(config.read_text())
    document["model"]["later_field"] = {"keep": "later model data"}
    document["plugins"]["enabled"].append("later-plugin")
    document["plugins"]["later_field"] = {"keep": "later plugin data"}
    document["mcp_servers"]["later"] = {"url": "https://foreign.example.invalid/mcp"}
    normalized = yaml.safe_dump(document, allow_unicode=True)
    # YAML quoting is not JSON quoting: Hermes/PyYAML may emit all three forms.
    normalized = normalized.replace("provider: custom", r'provider: "\x63\u0075\U00000073tom"')
    put(config, normalized)
    for arguments in (("doctor", "hermes"), ("doctor", "hermes", "--fix")):
        report = json.loads(f.cli(*arguments).stdout)
        assert report["state"] == "installed", report
        assert report["components"]["routing"] and report["components"]["mcp_recovery"], report
        owned_config = next(item for item in report["files"] if item["file"] == str(config))
        assert owned_config["owned"] and not owned_config["exact"], report
        assert config.read_text() == normalized
        assert journal_path.read_bytes() == journal_before
    assert not (f.cave / "mcp/hermes.json").exists()
    status = json.loads(f.cli("status", "--json").stdout)
    assert not any(item["id"] == "mcp-missing" for item in status["off_states"]), status
    f.mcp(f.registration("hermes", "caveman-native"), "caveman", recover=True)
    # Real edits and ambiguous shapes must fail before any config, generated
    # plugin, backup, or restoration journal is written.
    edits = []
    for label, key, value in (
        ("provider", "provider", "user-provider"),
        ("route", "base_url", "https://changed.example.invalid/v1"),
    ):
        changed = json.loads(json.dumps(document))
        changed["model"][key] = value
        edits.append((label, yaml.safe_dump(changed)))
    for label, key, value in (
        ("MCP command", "command", "/user/changed-command"),
        ("MCP enabled", "enabled", False),
        ("MCP extra field", "args", ["--user-added"]),
    ):
        changed = json.loads(json.dumps(document))
        changed["mcp_servers"]["caveman-native"][key] = value
        edits.append((label, yaml.safe_dump(changed)))
    changed = json.loads(json.dumps(document))
    changed["plugins"]["enabled"].remove("caveman_native")
    edits.append(("removed plugin", yaml.safe_dump(changed)))
    for path in (("plugins",), ("plugins", "enabled"), ("mcp_servers",), ("mcp_servers", "caveman-native")):
        missing = json.loads(json.dumps(document))
        parent = missing
        for key in path[:-1]:
            parent = parent[key]
        del parent[path[-1]]
        edits.append(("missing owned " + ".".join(path), yaml.safe_dump(missing)))
    changed["plugins"]["enabled"].extend(["caveman_native", "caveman_native"])
    edits.append(("duplicate plugin", yaml.safe_dump(changed)))
    edits.extend((
        ("duplicate route", normalized.replace("\nmodel:\n", "\nmodel:\n  provider: custom\n")),
        ("duplicate root", normalized + "model:\n  provider: custom\n"),
        ("duplicate MCP", normalized.replace("\nmcp_servers:\n", "\nmcp_servers:\n  caveman-native:\n    command: /foreign/mcp\n")),
        ("flow plugin list", normalized.replace(
            "  enabled:\n" + "".join("  " + line for line in yaml.safe_dump(document["plugins"]["enabled"], allow_unicode=True).splitlines(keepends=True)),
            "  enabled: " + json.dumps(document["plugins"]["enabled"], ensure_ascii=False) + "\n")),
        ("plain comment continuation", normalized.replace(
            "  provider: " + r'"\x63\u0075\U00000073tom"',
            "  provider: custom # end\n    foreign")),
        ("quoted comment continuation", normalized.replace(
            "  provider: " + r'"\x63\u0075\U00000073tom"',
            '  provider: "custom" # end\n    foreign')),
        ("tabbed first model key", normalized.replace("\n  base_url:", "\n  \tbase_url:")),
        ("tabbed owned item", normalized.replace("- caveman_native\n", "\t- caveman_native\n")),
        ("tabbed plain route", normalized.replace(
            "  provider: " + r'"\x63\u0075\U00000073tom"', "  provider:\n    \tcustom")),
        ("tabbed foreign structure", normalized.replace(
            "\nmodel:\n", "\nmodel:\n  notes: keep\n   \tprovider: anthropic\n")),
        ("insufficient block indentation", normalized + "custom_notes: |2\n \tkeep tab\n"),
        ("tab after block", normalized + "custom_notes: |\n  keep\n \tbad\n"),
        ("unclosed tabbed quote", normalized + 'custom_notes: "open\n  \tdata\n'),
    ))
    # Reject typed scalars without rejecting ordinary names that share a prefix.
    typed_scalars = ("+1_000", "0b10", "0x10", "012", "1:20", "1.0e+3",
                     ".5", "1:20.5", "2026-10-27", "2026-10-27T12:34:56Z", "true", "null",
                     "-1", "-0b10", "-0x10", "-1:20", "-.inf", "-.Inf", "-.INF")
    for scalar in typed_scalars:
        assert not isinstance(yaml.safe_load(scalar), str), scalar
    # Reject YAML 1.2 numbers and separated indicators too.
    for scalar in (*typed_scalars, "1e3", ".5e3", "0o10", "09", "-1e3", "-.5", "-.5e3", "-0o10",
                   "-", "?", ":", "- value", "? key", ": value"):
        edits.append(("typed plugin " + scalar, normalized.replace("- existing\n", "- " + scalar + "\n")))
    for key in ('"team/github"', "true", "012", "-1", "team # comment", "<<"):
        edits.append(("unsafe MCP key " + key, normalized.replace(
            "\nmcp_servers:\n", "\nmcp_servers:\n  " + key + ":\n    command: /foreign/mcp\n")))
    edits.append(("alias MCP key", "alias_key: &server_name team/alias\n" + normalized.replace(
        "\nmcp_servers:\n", "\nmcp_servers:\n  *server_name:\n    command: /foreign/mcp\n")))
    integration_files = [Path(item["file"]) for item in load(journal_path)["operations"]]
    for label, edited in edits:
        assert edited != normalized, label
        put(config, edited)
        snapshot = {path: path.read_bytes() for path in [
            *integration_files,
            *(path for path in (f.cave / "integrations").rglob("*") if path.is_file()),
        ]}
        report = json.loads(f.cli("doctor", "hermes", check=False).stdout)
        assert report["state"] == "degraded", (label, report)
        for arguments in (("doctor", "hermes", "--fix"), ("disable", "hermes")):
            result = f.cli(*arguments, check=False)
            assert result.returncode != 0, (label, arguments, result.stdout, result.stderr)
            assert all(path.read_bytes() == content for path, content in snapshot.items()), (label, arguments)
            assert {path for path in (f.cave / "integrations").rglob("*") if path.is_file()} == {
                path for path in snapshot if path.is_relative_to(f.cave / "integrations")
            }, (label, arguments)
    put(config, normalized)
    f.cli("disable", "hermes")
    expected = json.loads(json.dumps(document))
    expected["model"]["provider"] = original["model"]["provider"]
    expected["model"]["base_url"] = original["model"]["base_url"]
    expected["plugins"]["enabled"].remove("caveman_native")
    del expected["mcp_servers"]["caveman-native"]
    assert yaml.safe_load(config.read_text()) == expected, config.read_text()
    assert not journal_path.exists()
    assert not (f.home / ".hermes/plugins/caveman_native/__init__.py").exists()
    # Foreign children in generated sections must survive disable.
    commented_null = {"model": {"provider": "auto", "base_url": None}}
    wrapped = {
        "model": {"provider": "anthropic", "base_url": "https://api.anthropic.com",
                  "default": "claude-sonnet-4-5"},
        "plugins": {"enabled": ["existing", *plain_plugins], "foreign": {"keep": True}},
        "mcp_servers": foreign_servers,
    }
    for previous in ({}, {"model": {"provider": "auto", "base_url": None}}, commented_null,
                     {"model": {"provider": "anthropic", "base_url": "null"}},
                     {"model": {"provider": "anthropic", "base_url": "~"}},
                     {"model": original["model"]}, wrapped, {
        "model": original["model"],
        "plugins": {"enabled": ["caveman_native", "existing"]},
        "mcp_servers": {"caveman-native": {"command": "/foreign/mcp", "enabled": True}},
    }):
        seed = yaml.safe_dump(previous, indent=4, allow_unicode=True) if previous else ""
        if previous is commented_null:
            seed = seed.replace("base_url: null", "base_url: # user endpoint unset")
        if previous is wrapped:
            seed = seed.replace("provider: anthropic", 'provider: "anthro\\\n        pic"')
            seed = seed.replace("base_url: https://api.anthropic.com",
                                'base_url: "https://api.\\\n        anthropic.com"')
            for name in plain_plugins:
                seed = seed.replace("- " + name + "\n", "- " + json.dumps(name) + "\n")
            for name in foreign_servers:
                seed = seed.replace("    " + name + ":", "    " + json.dumps(name) + ":")
        put(config, seed)
        f.cli("enable", "hermes")
        active = yaml.safe_load(config.read_text())
        active["model"]["later_field"] = "keep model field"
        active["plugins"]["enabled"].append("later-plugin")
        active["plugins"]["foreign"] = {"keep": True}
        active["mcp_servers"]["foreign"] = {"command": "/foreign/later"}
        normalized = yaml.safe_dump(active, indent=4, allow_unicode=True)
        if previous is wrapped:
            assert all("- " + name + "\n" in normalized for name in plain_plugins)
        # Quoted roots and owned child keys are accepted YAML, not new sections.
        for key in ("model", "plugins", "mcp_servers", "provider", "base_url",
                    "enabled", "caveman-native"):
            normalized = re.sub(r"(?m)^(\s*)" + re.escape(key) + ":",
                                lambda match: match[1] + '"' + key + '":', normalized)
        normalized = normalized.replace('"model":\n', '"model":\n    # preserve foreign model note\n')
        put(config, normalized)
        payload = f.home / ".hermes/plugins/caveman_native/__init__.py"
        if previous is wrapped:
            healthy = json.loads(f.cli("doctor", "hermes").stdout)
            assert healthy["state"] == "installed", healthy
            assert healthy["components"]["routing"] and healthy["components"]["mcp_recovery"], healthy
        payload.unlink()
        degraded = json.loads(f.cli("doctor", "hermes", check=False).stdout)
        assert degraded["state"] == "degraded", degraded
        f.cli("doctor", "hermes", "--fix")
        assert payload.is_file()
        assert "# preserve foreign model note" in config.read_text()
        repaired = yaml.safe_load(config.read_text())
        assert repaired == active, (repaired, active)
        assert repaired["model"]["base_url"] == f.env["CAVE_GATEWAY_URL"] + "/w/hermes/v1"
        healthy = json.loads(f.cli("doctor", "hermes").stdout)
        assert healthy["state"] == "installed", healthy
        assert healthy["components"]["routing"] and healthy["components"]["mcp_recovery"], healthy
        repaired_bytes = config.read_bytes()
        repaired_journal = journal_path.read_bytes()
        f.cli("doctor", "hermes", "--fix")
        assert config.read_bytes() == repaired_bytes
        assert journal_path.read_bytes() == repaired_journal
        f.cli("disable", "hermes")
        expected = json.loads(json.dumps(active))
        for key in ("provider", "base_url"):
            if key in previous.get("model", {}):
                expected["model"][key] = previous["model"][key]
            else:
                del expected["model"][key]
        if "caveman_native" not in previous.get("plugins", {}).get("enabled", []):
            expected["plugins"]["enabled"].remove("caveman_native")
        if "caveman-native" not in previous.get("mcp_servers", {}):
            del expected["mcp_servers"]["caveman-native"]
        assert yaml.safe_load(config.read_text()) == expected, config.read_text()
        assert "# preserve foreign model note" in config.read_text()


def hermes_plugin_scalars(f):
    config = f.paths("hermes")
    journal_path = f.cave / "integrations/hermes.json"
    payload = f.home / ".hermes/plugins/caveman_native/__init__.py"
    foreign = "true " + "foreign plugin " * 8 + "tail"
    original = {
        "model": {"provider": "anthropic", "base_url": "https://api.anthropic.com"},
        "plugins": {"enabled": [foreign, "sibling"]},
    }

    def replace_item(text, name, value):
        old = "- " + name + "\n"
        start = text.index(old)
        return text[:start] + "- " + value + "\n" + text[start + len(old):]

    for quote, width in (("", 2), ("'", 4), ('"', 4)):
        pad = " " * width
        first, rest = foreign.split(" ", 1)
        foreign_scalar = quote + first + "\n" + pad + "  " + rest + quote
        owned_scalar = '"caveman_\\\n' + pad + '  native"'
        note = pad + "# preserve plugin note\n"
        seed = yaml.safe_dump(original, indent=width, width=10_000)
        seed = replace_item(seed, foreign, foreign_scalar)
        assert yaml.safe_load(seed) == original
        put(config, seed)
        f.cli("enable", "hermes")
        active = yaml.safe_load(config.read_text())
        assert active["plugins"]["enabled"] == ["caveman_native", foreign, "sibling"]
        normalized = yaml.safe_dump(active, indent=width, width=10_000)
        normalized = replace_item(normalized, foreign, foreign_scalar)
        normalized = replace_item(normalized, "caveman_native", owned_scalar + "\n" + note.rstrip("\n"))
        assert yaml.safe_load(normalized) == active
        put(config, normalized)
        healthy = json.loads(f.cli("doctor", "hermes").stdout)
        assert healthy["state"] == "installed", healthy
        owned = next(item for item in healthy["files"] if item["file"] == str(config))
        assert owned["owned"] and not owned["exact"], healthy
        journal_before = journal_path.read_bytes()
        f.cli("doctor", "hermes", "--fix")
        assert config.read_text() == normalized and journal_path.read_bytes() == journal_before

        generated = [Path(item["file"]) for item in load(journal_path)["operations"]]
        for edited in (
            normalized.replace(owned_scalar, owned_scalar.replace("native", "changed")),
            normalized.replace("enabled:\n", "enabled:\n" + pad + "- caveman_native\n"),
        ):
            put(config, edited)
            snapshot = {path: path.read_bytes() for path in (
                config, *generated, *(f.cave / "integrations").rglob("*")
            ) if path.is_file()}
            report = json.loads(f.cli("doctor", "hermes", check=False).stdout)
            assert report["state"] == "degraded", report
            for arguments in (("doctor", "hermes", "--fix"), ("disable", "hermes")):
                result = f.cli(*arguments, check=False)
                assert result.returncode != 0, (arguments, result.stdout, result.stderr)
                assert all(path.read_bytes() == content for path, content in snapshot.items())
                assert {path for path in (f.cave / "integrations").rglob("*") if path.is_file()} == {
                    path for path in snapshot if path.is_relative_to(f.cave / "integrations")
                }
        put(config, normalized)
        payload.unlink()
        degraded = json.loads(f.cli("doctor", "hermes", check=False).stdout)
        assert degraded["state"] == "degraded", degraded
        f.cli("doctor", "hermes", "--fix")
        assert payload.is_file()
        assert yaml.safe_load(config.read_text()) == active
        assert note in config.read_text()
        repaired_bytes = config.read_bytes()
        repaired_journal = journal_path.read_bytes()
        f.cli("doctor", "hermes", "--fix")
        assert config.read_bytes() == repaired_bytes
        assert journal_path.read_bytes() == repaired_journal
        continued = replace_item(config.read_text(), "caveman_native", owned_scalar)
        assert yaml.safe_load(continued) == active
        put(config, continued)
        f.cli("disable", "hermes")
        assert yaml.safe_load(config.read_text()) == original, config.read_text()
        assert note in config.read_text()
        assert not payload.exists() and not journal_path.exists()


def hermes_foreign_markers(f):
    config = f.paths("hermes")
    journal_path = f.cave / "integrations/hermes.json"
    payload = f.home / ".hermes/plugins/caveman_native/__init__.py"
    markers = [
        "# >>> caveman:native-hermes-routing", "# <<< caveman:native-hermes-routing",
        "# >>> caveman:native-hermes-plugin", "# <<< caveman:native-hermes-plugin",
        "# >>> caveman:native-hermes-mcp", "# <<< caveman:native-hermes-mcp",
    ]

    def body(width, lines):
        return "".join(" " * width + line + "\n" for line in lines)

    content = ["before", *markers, "after"]
    quoted = json.dumps('before \\\\ "quote"')[:-1]
    fragments = (
        ("literal", "custom_notes: |\n" + body(2, content)),
        ("tabbed-literal", "custom_notes: |\n  \tkeep tab\n"),
        ("tabbed-quote", 'custom_notes: "before\n  \tkeep tab"\n'),
        ("folded", "custom_notes: >-\n" + body(2, content)),
        ("marker-first", "custom_notes: |2-\n" + body(2, markers)),
        ("next-line-header", "custom_notes:\n  |2-\n" + body(2, content)),
        ("property-line", "custom_notes:\n  &notes\n  |2-\n" + body(2, content)),
        ("sequence", "custom_notes:\n  - |2\n" + body(4, content)),
        ("compact-mapping", "custom_notes:\n  - text: >2-\n" + body(6, content)),
        ("single-quoted", "custom_notes: 'before ''quote''\n" + body(2, markers) + "  after'\n"),
        ("double-quoted", "custom_notes: " + quoted + "\n" + body(2, markers) + '  after"\n'),
        ("tagged", "custom_notes: !<tag:yaml.org,2002:str> " + quoted + "\n"
         + body(2, markers) + '  after"\n'),
        ("flow-quoted", "custom_notes: {\n  text: " + quoted + "\n"
         + body(2, markers) + '  after"\n  }\n'),
        ("flow-adjacent", 'custom_notes: {"text":' + quoted + "\n"
         + body(2, markers) + '  after"}\n'),
        ("quoted-key", "custom_notes:\n  ? 'before\n" + body(4, markers) + "    after'\n  : keep\n"),
        ("block-key", "custom_notes:\n  ? |2\n" + body(4, markers) + "  : keep\n"),
        ("deferred-sequence", "custom_notes:\n  -\n    |2\n" + body(4, markers)),
        ("deferred-plain", "custom_notes:\n  plain\n  [bracket\nforeign_block: |\n" + body(2, content)),
        ("property-deferred-plain", "custom_notes:\n  &notes !!str\n  plain\n  [bracket\nforeign_block: |\n"
         + body(2, content)),
        ("sequence-deferred-plain", "custom_notes:\n  -\n    plain\n    [bracket\nforeign_block: |\n"
         + body(2, content)),
        ("mapping-deferred-plain", "custom_notes:\n  - text:\n      plain\n      [bracket\nforeign_block: |\n"
         + body(2, content)),
    )
    original = {
        "model": {"provider": "anthropic", "base_url": "https://api.anthropic.com"},
        "plugins": {"enabled": ["existing"]},
    }
    seed = yaml.safe_dump(original, sort_keys=False)
    cases = [(label, fragment, False) for label, fragment in fragments]
    cases.append(("tabbed-model", "  notes: |2\n    \tkeep tab\n", True))
    for label, fragment, in_model in cases:
        if not in_model:
            fragment += "plain_note: don't [start]\n"

        def add_foreign(text):
            return text.replace("model:\n", "model:\n" + fragment, 1) if in_model else text + "\n" + fragment

        expected = yaml.safe_load(add_foreign(seed))
        put(config, seed)
        f.cli("enable", "hermes")
        put(config, add_foreign(config.read_text()))
        active = yaml.safe_load(config.read_text())
        healthy = json.loads(f.cli("doctor", "hermes").stdout)
        assert healthy["state"] == "installed", (label, healthy)
        assert next(item["owned"] for item in healthy["files"] if item["file"] == str(config))
        payload.unlink()
        degraded = json.loads(f.cli("doctor", "hermes", check=False).stdout)
        assert degraded["state"] == "degraded", (label, degraded)
        f.cli("doctor", "hermes", "--fix")
        assert payload.is_file(), label
        assert yaml.safe_load(config.read_text()) == active, label
        assert fragment in config.read_text(), label
        healthy = json.loads(f.cli("doctor", "hermes").stdout)
        assert healthy["state"] == "installed", (label, healthy)
        repaired, journal = config.read_bytes(), journal_path.read_bytes()
        f.cli("doctor", "hermes", "--fix")
        assert config.read_bytes() == repaired and journal_path.read_bytes() == journal, label
        f.cli("disable", "hermes")
        assert yaml.safe_load(config.read_text()) == expected, label
        assert fragment in config.read_text(), label
        assert not payload.exists() and not journal_path.exists(), label
        # Re-enable exercises producer preflight without an existing journal.
        f.cli("enable", "hermes")
        f.cli("disable", "hermes")
        assert yaml.safe_load(config.read_text()) == expected, label
        assert fragment in config.read_text(), label
    for text in (
        seed + "custom_notes: don't [start]\n" + markers[0] + "\n",
        seed + "custom_notes: [\n  " + markers[-1] + '\n  "keep"\n  ]\n',
        seed + "custom_notes:\n  - plain\n    'quote\n  " + markers[0] + "\n",
        seed + "custom_notes:\n  plain\n  'quote\n" + markers[0] + "\n",
        "model:\n  \tprovider: anthropic\n  base_url: https://api.anthropic.com\n",
        seed + 'custom_notes: "open\n  \tdata\n',
    ):
        put(config, text)
        before = config.read_bytes()
        snapshots = {p: p.read_bytes() for p in (f.cave / "integrations").rglob("*") if p.is_file()}
        result = f.cli("enable", "hermes", check=False)
        assert result.returncode != 0, (text, result.stdout, result.stderr)
        assert config.read_bytes() == before
        assert not payload.exists() and not journal_path.exists()
        assert {p: p.read_bytes() for p in (f.cave / "integrations").rglob("*") if p.is_file()} == snapshots


def hermes_foreign_removal(f):
    config = f.paths("hermes")
    journal_path = f.cave / "integrations/hermes.json"
    original = {
        "model": {"provider": "anthropic", "base_url": "https://api.anthropic.com",
                  "foreign": {"keep": "model data"}},
        "plugins": {"enabled": ["caveman_native", "existing"], "foreign": {"keep": True}},
        "mcp_servers": {"caveman-native": {"command": "/foreign/mcp", "enabled": True},
                        "foreign": {"command": "/foreign/other"}},
    }
    for case in ("plugin", "enabled", "plugins", "mcp", "servers", "both", "empty-blocks"):
        for repair in (False, True):
            put(config, yaml.safe_dump(original, sort_keys=False))
            f.cli("enable", "hermes")
            operation = next(item for item in load(journal_path)["operations"] if item["kind"] == "hermes-config")
            assert operation["owned"]["plugin_block"] is None and operation["owned"]["mcp_block"] is None
            document = yaml.safe_load(config.read_text())
            if case in ("plugin", "both"):
                document["plugins"]["enabled"].remove("caveman_native")
            elif case == "enabled":
                del document["plugins"]["enabled"]
            elif case == "plugins":
                del document["plugins"]
            if case in ("mcp", "both"):
                del document["mcp_servers"]["caveman-native"]
            elif case == "servers":
                del document["mcp_servers"]
            if case == "empty-blocks":
                del document["plugins"], document["mcp_servers"]
            text = yaml.safe_dump(document, sort_keys=False)
            if case == "empty-blocks":
                text += "plugins: # user left empty\nmcp_servers: # user left empty\n"
            put(config, text)
            expected = yaml.safe_load(text)
            expected["model"].update(original["model"])
            snapshot, journal = config.read_bytes(), journal_path.read_bytes()
            result = f.cli("doctor", "hermes", check=False)
            report = json.loads(result.stdout)
            assert result.returncode == 1 and report["state"] == "degraded", (case, report)
            assert not report["components"]["lifecycle_hooks"] and not report["components"]["mcp_recovery"], report
            assert config.read_bytes() == snapshot and journal_path.read_bytes() == journal
            status = json.loads(f.cli("status", "--json").stdout)
            missing_mcp = any(item["id"] == "mcp-missing" for item in status["off_states"])
            assert missing_mcp == (case in ("mcp", "servers", "both", "empty-blocks")), (case, status)
            if repair:
                f.cli("doctor", "hermes", "--fix")
                report = json.loads(f.cli("doctor", "hermes").stdout)
                assert report["state"] == "installed", (case, report)
                operation = next(item for item in load(journal_path)["operations"] if item["kind"] == "hermes-config")
                for key, recreated in (
                    ("plugin_block", case in ("plugin", "enabled", "plugins", "both", "empty-blocks")),
                    ("mcp_block", case in ("mcp", "servers", "both", "empty-blocks")),
                ):
                    assert (isinstance(operation["owned"][key], str) if recreated else operation["owned"][key] is None), (case, key)
                repaired, repaired_journal = config.read_bytes(), journal_path.read_bytes()
                f.cli("doctor", "hermes", "--fix")
                assert config.read_bytes() == repaired and journal_path.read_bytes() == repaired_journal, case
            generated = [Path(item["file"]) for item in load(journal_path)["operations"]
                         if item["kind"] in ("hermes-plugin-manifest", "hermes-plugin-init")]
            f.cli("disable", "hermes")
            assert yaml.safe_load(config.read_text()) == expected, (case, repair, config.read_text())
            assert not journal_path.exists() and all(not path.exists() for path in generated), case
    # Missing foreign entries differ from unsupported present containers.
    for section, value in (("plugins", "{enabled: [caveman_native]}"), ("mcp_servers", "{}")):
        put(config, yaml.safe_dump(original, sort_keys=False))
        f.cli("enable", "hermes")
        document = yaml.safe_load(config.read_text())
        del document[section]
        put(config, yaml.safe_dump(document, sort_keys=False) + section + ": " + value + "\n")
        paths = [journal_path, *(Path(item["file"]) for item in load(journal_path)["operations"])]
        snapshot = {path: path.read_bytes() for path in paths}
        for arguments in (("doctor", "hermes", "--fix"), ("disable", "hermes")):
            result = f.cli(*arguments, check=False)
            assert result.returncode != 0, (section, arguments, result.stdout, result.stderr)
            assert all(path.read_bytes() == content for path, content in snapshot.items())
        document[section] = original[section]
        put(config, yaml.safe_dump(document, sort_keys=False))
        f.cli("disable", "hermes")


def native_integrations(f):
    # Gemini supports native routing through the local proxy, not a managed
    # gateway. These hooks read local context; no provider request is sent.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        f.env["CAVE_GATEWAY_URL"] = f"http://127.0.0.1:{reservation.getsockname()[1]}"
    for agent in NATIVE:
        f.cli("enable", agent)
    journals = {agent: f.cave / "integrations" / f"{agent}.json" for agent in NATIVE}
    # Exercise callbacks across generations; session stamps and repository
    # evidence can change between calls without changing the installation.
    native_contexts(f)
    f.switch(f.b)
    f.unavailable_a()
    native_contexts(f)
    f.cli("stop")
    pi_extension(f)
    opencode = f.home / ".config/opencode/plugins/caveman-native.js"
    hermes = f.home / ".hermes/plugins/caveman_native/__init__.py"
    # Aider is a route and a read-file integration, never an MCP client.
    aider = (f.home / ".aider.conf.yml").read_text()
    assert f.env["CAVE_GATEWAY_URL"] + "/w/aider/openai/v1" in aider, aider
    assert not (f.cave / "mcp/aider.json").exists()
    # Repair uses journal-aware upstream semantics. A deleted generated payload
    # is repairable; a user-owned payload must not be silently overwritten.
    opencode.unlink()
    f.cli("doctor", "opencode", "--fix")
    assert opencode.exists()
    native_contexts(f)
    owned_bytes = opencode.read_bytes()
    config = f.home / ".config/opencode/opencode.json"
    config_before = config.read_bytes()
    journal_before = journals["opencode"].read_bytes()
    opencode.write_bytes(owned_bytes + b"\n// user modification: retain this byte-for-byte\n")
    edited_bytes = opencode.read_bytes()
    for arguments in (("doctor", "opencode", "--fix"), ("disable", "opencode")):
        f.cli(*arguments, check=False)
        assert opencode.read_bytes() == edited_bytes
        assert config.read_bytes() == config_before
        assert journals["opencode"].read_bytes() == journal_before
    # Restore only the test's own added bytes, then exercise supported removal.
    opencode.write_bytes(owned_bytes)
    for agent in NATIVE:
        f.cli("disable", agent)
        assert not journals[agent].exists(), agent
    assert not opencode.exists()
    assert not hermes.exists()
    assert not (f.home / ".pi/agent/extensions/caveman-native.js").exists()


def pi_extension(f):
    # Remove global MCP and callback hints before loading the copied extension.
    # Its independent recovery resolution must find the selected profile itself.
    extension = f.home / ".pi/agent/extensions/caveman-native.js"
    modules = extension.parent.parent / "node_modules"
    modules.mkdir()
    (modules / "typebox").symlink_to(TYPEBOX, target_is_directory=True)
    source = r'''
import {pathToFileURL} from "node:url";
import {readFileSync} from "node:fs";
const events = new Map(), tools = new Map();
const pi = {
  on(name, handler) { events.set(name, handler); },
  registerTool(tool) { tools.set(tool.name, tool); },
  registerProvider() {},
  getActiveTools() { return ["caveman_retrieve"]; },
};
(await import(pathToFileURL(process.argv[1]))).default(pi);
const ctx = {hasUI:false, sessionManager:{getSessionId(){return "profile-pi";}}};
await events.get("session_start")({}, ctx);
const lifecycle = await events.get("before_agent_start")({prompt:"Review durability", systemPrompt:"host-system"}, ctx);
const recovered = await tools.get("caveman_retrieve").execute("profile-call", {recovery_handle:process.argv[2]});
let shrink;
if (process.argv[3]) {
  const text = readFileSync(process.argv[3], "utf8");
  const image = {type:"image", data:"aW1hZ2U=", mimeType:"image/png"};
  const patch = await events.get("tool_result")({
    toolName:"read_file", input:{path:process.argv[3]}, isError:false,
    content:[{type:"text", text}, image],
  });
  if (!patch || patch.content[0].text === text) throw new Error("Pi did not publish a real output replacement");
  if (JSON.stringify(patch.content[1]) !== JSON.stringify(image)) throw new Error("Pi changed nontext content");
  const handle = patch.content[0].text.match(/ccr:\/\/[A-Za-z0-9_-]+|ccr_[A-Za-z0-9_-]+/)?.[0];
  if (!handle) throw new Error("Pi replacement lacks recovery handle");
  const original = await tools.get("caveman_retrieve").execute("shrink-recover", {recovery_handle:handle});
  if (original.content.map(item => item.text || "").join("") !== text) throw new Error("Pi recovery changed original bytes");
  shrink = {replacement:patch.content[0].text, handle};
}
console.log(JSON.stringify({recovered, lifecycle, shrink, hook:process.env.CAVEMAN_PI_HOOK_CMD, mcp:process.env.CAVEMAN_MCP_BIN}));
await events.get("session_shutdown")?.({}, ctx);
'''
    environment = {key: value for key, value in f.env.items()
                   if key not in ("CAVEMAN_MCP_BIN", "CAVEMAN_PI_HOOK_CMD")}
    environment["PATH"] = ""
    result = json.loads(f.node(source, extension, f.handle, env=environment).stdout)
    assert "".join(item.get("text", "") for item in result["recovered"]["content"]).encode() == f.original
    assert json.loads(result["hook"]) == [str(f.profile / "bin/caveman")], result
    assert result["mcp"] == str(f.profile / "bin/caveman-mcp"), result
    assert result["lifecycle"]["systemPrompt"].startswith("host-system\n\n"), result
    assert "architecture" in result["lifecycle"]["systemPrompt"].lower(), result
    alternate = f.root / "independent-recovery"
    shutil.copy2(f.b / "bin/caveman-mcp", alternate)
    environment["CAVEMAN_MCP_BIN"] = str(alternate)
    environment["CAVEMAN_PI_HOOK_CMD"] = json.dumps([str(f.profile / "bin/cave")])
    result = json.loads(f.node(source, extension, f.handle, env=environment).stdout)
    assert result["mcp"] == str(alternate), result
    assert json.loads(result["hook"]) == [str(f.profile / "bin/cave")], result
    assert "".join(item.get("text", "") for item in result["recovered"]["content"]).encode() == f.original
    # Native Pi replacement must publish a recovery handle and recover exact bytes.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    local = {**environment, "CAVE_GATEWAY_URL": f"http://127.0.0.1:{port}",
             "CAVEMAN_LISTEN": f"127.0.0.1:{port}"}
    output = put(f.repo / "pi-tool-output.txt", "auth refresh details\n" * 300)
    try:
        result = json.loads(f.node(source, extension, f.handle, output, env=local).stdout)
        assert result["shrink"]["handle"], result
        handle = result["shrink"]["handle"].removeprefix("ccr://")
        assert f.cli("tools", "retrieve", handle).stdout == output.read_bytes()
    finally:
        f.cli("stop", env=local)


def native_registration_commands(f):
    # A lexical profile may contain spaces and /nix/store/ without being in it.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        f.env["CAVE_GATEWAY_URL"] = f"http://127.0.0.1:{reservation.getsockname()[1]}"
    profile_command = str(f.profile / "bin/caveman-mcp")
    store_command = str(PACKAGE / "bin/caveman-mcp")
    assert store_command.startswith("/nix/store/") and Path(store_command).is_file()
    for agent, kind in (
        ("opencode", "opencode-config"), ("claude", "claude-mcp"),
        ("gemini", "gemini-settings"), ("codex", "codex-config"),
        ("hermes", "hermes-config"),
    ):
        config = f.paths(agent)
        historical = None
        if agent in ("claude", "gemini", "opencode"):
            historical = {"command": [store_command] if agent == "opencode" else store_command}
            if agent == "opencode":
                historical.update(type="local", enabled=True)
            section = "mcp" if agent == "opencode" else "mcpServers"
            put(config, json.dumps({section: {"caveman": historical}}))
        f.cli("enable", agent)
        report = json.loads(f.cli("doctor", agent, "--fix").stdout)
        assert report["state"] == "installed", (agent, report)
        server = "caveman-native" if agent == "hermes" else "caveman"
        assert f.registration(agent, server)[0] == profile_command
        journal_path = f.cave / "integrations" / f"{agent}.json"
        journal = load(journal_path)
        operation = next(item for item in journal["operations"] if item["kind"] == kind)
        owned = operation["owned"]
        if historical is not None:
            assert owned["previous_mcp"] == historical
        # Keep file, ownership payload and digest concordant: only path identity
        # distinguishes this old registration from the healthy profile above.
        if agent in ("codex", "hermes"):
            field = "tables_block" if agent == "codex" else "mcp_block"
            block = owned[field]
            quoted = json.dumps(profile_command)
            assert quoted in block, (agent, block)
            replacement = block.replace(quoted, json.dumps(store_command))
            text = config.read_text()
            assert block in text, (agent, block)
            put(config, text.replace(block, replacement))
            owned[field] = replacement
        else:
            document = load(config)
            section = "mcp" if agent == "opencode" else "mcpServers"
            command = [store_command] if agent == "opencode" else store_command
            document[section]["caveman"]["command"] = command
            owned["installed_mcp"]["command"] = command
            put(config, json.dumps(document))
        operation["after_sha256"] = "sha256:" + hashlib.sha256(config.read_bytes()).hexdigest()
        put(journal_path, json.dumps(journal))
        result = f.cli("doctor", agent, check=False)
        assert result.returncode == 1, (agent, result)
        report = json.loads(result.stdout)
        entry = next(item for item in report["files"] if item["file"] == str(config))
        assert report["state"] == "degraded" and entry["exact"] and not entry["owned"], (agent, report)
        assert f.registration(agent, server)[0] == store_command
        report = json.loads(f.cli("doctor", agent, "--fix").stdout)
        assert report["state"] == "installed", (agent, report)
        assert f.registration(agent, server)[0] == profile_command
        if historical is not None:
            repaired = next(item for item in load(journal_path)["operations"] if item["kind"] == kind)
            assert repaired["owned"]["previous_mcp"] == historical


def ownership_controls(f):
    # Kilo/Qwen use transactional ownership and must retain permissions,
    # credentials, remote endpoints and foreign registrations through all verbs.
    for agent in ("kilo", "qwen"):
        path = f.paths(agent)
        section = "mcp" if agent == "kilo" else "mcpServers"
        foreign = {"url": "https://foreign.example.invalid/mcp", "headers": {"Authorization": "secret-fixture"}}
        document = {"apiKey": "credential-fixture", "endpoint": "https://provider.example.invalid/v1",
                    section: {"foreign": foreign}, "user": ["Unicode café", 7]}
        put(path, json.dumps(document) + "\n", 0o640)
        f.cli("tools", "mcp", "install", agent)
        marker = f.cave / "mcp" / f"{agent}.json"
        journal = marker.read_bytes()
        installed = load(path)
        assert installed[section]["foreign"] == foreign
        assert path.stat().st_mode & 0o777 == 0o640
        installed["laterUserEdit"] = {"keep": True}
        put(path, json.dumps(installed) + "\n", 0o640)
        f.cli("tools", "mcp", "install", agent)
        assert marker.read_bytes() == journal, agent
        f.cli("tools", "mcp", "uninstall", agent)
        expected = {**document, "laterUserEdit": {"keep": True}}
        assert load(path) == expected, (agent, load(path))
        assert path.stat().st_mode & 0o777 == 0o640
        assert not marker.exists()
        # A changed owned registration is no longer ours to delete or repair.
        f.cli("tools", "mcp", "install", agent)
        edited = load(path)
        owned = edited[section]["caveman"]
        owned["command"] = ["/user/changed-command"] if agent == "kilo" else "/user/changed-command"
        put(path, json.dumps(edited) + "\n", 0o640)
        bytes_before, journal_before = path.read_bytes(), marker.read_bytes()
        f.cli("tools", "mcp", "uninstall", agent, check=False)
        assert path.read_bytes() == bytes_before
        assert marker.read_bytes() == journal_before
    # A foreign OpenCode plugin causes preflight refusal before route writes.
    # Then force publication failure after host writes to exercise real rollback.
    config = f.home / ".config/opencode/opencode.json"
    plugin = f.home / ".config/opencode/plugins/caveman-native.js"
    original = '{"provider":{"foreign":{"options":{"apiKey":"keep-secret"}}}}\n'
    put(config, original, 0o640)
    put(plugin, "// independently owned plugin\n")
    result = f.cli("enable", "opencode", check=False)
    assert result.returncode != 0
    assert config.read_text() == original
    assert plugin.read_text() == "// independently owned plugin\n"
    assert not (f.cave / "integrations/opencode.json").exists()
    assert not (f.cave / "integrations/.pending-opencode.json").exists()
    plugin.unlink()
    publication = f.cave / "integrations/opencode.json"
    publication.mkdir()
    result = f.cli("enable", "opencode", check=False)
    assert result.returncode != 0
    assert config.read_text() == original
    assert config.stat().st_mode & 0o777 == 0o640
    assert not plugin.exists()
    assert publication.is_dir() and not any(publication.iterdir())
    assert not (f.cave / "integrations/.pending-opencode.json").exists()
    publication.rmdir()
    config.unlink()
    immutable = PACKAGE / "lib/caveman/package.json"
    immutable_bytes = immutable.read_bytes()
    config.symlink_to(immutable)
    result = f.cli("enable", "opencode", check=False)
    assert result.returncode != 0
    assert config.is_symlink() and config.resolve() == immutable.resolve()
    assert immutable.read_bytes() == immutable_bytes
    assert not (f.cave / "integrations/opencode.json").exists()
    assert not (f.cave / "integrations/.pending-opencode.json").exists()


def filtered_profiles(root):
    # Real filtered buildEnv outputs must publish the private payload. Copies
    # would hide both direct and nested profile filtering regressions.
    assert not (PACKAGE / "share/caveman").exists()
    for index, target in enumerate(PROFILES):
        profile = root / f"filtered profile {index} ' quote"
        profile.symlink_to(target, target_is_directory=True)
        private = profile / "lib/caveman"
        for relative in ("node", "bash", "dist/index.js", "package.json",
                         "source/installer/install.js", "source/package.json"):
            assert (private / relative).is_file(), private / relative
        for mode in ("automatic", "explicit", "private"):
            home = root / f"filtered-home-{index}-{mode}"
            home.mkdir()
            env = {
                "HOME": str(home), "USERPROFILE": str(home), "PATH": "",
                "XDG_CONFIG_HOME": str(home / ".config"),
                "CAVEMAN_HOME": str(home / ".caveman"), "CAVEMAN_OFFLINE": "1",
                "CAVE_NO_KEYCHAIN": "1", "CI": "1", "NO_COLOR": "1",
            }
            invocation = [profile / "bin/caveman"]
            if mode == "explicit":
                env["CAVEMAN_REGISTRATION_ROOT"] = str(profile)
                invocation = [PACKAGE / "bin/caveman"]
            elif mode == "private":
                invocation = [private / "node", private / "dist/index.js"]
            execute([*invocation, "tools", "mcp", "install", "gemini",
                     "--server", "caveman-delegate"], env, cwd=root)
            entry = load(home / ".gemini/settings.json")["mcpServers"]["caveman-delegate"]
            argv = [entry["command"], *entry.get("args", [])]
            assert argv == [str(private / "node"), str(private / "dist/caveman-delegate-mcp.mjs")], entry
            mcp_exchange(argv, "caveman-delegate", env, root)
        print(f"filtered profile behavioral coverage: {index}", flush=True)


def package_invocations(root):
    # Exercise the installed launcher itself, separate from synthetic generation
    # wrappers. Prefix spelling (including spaces/quotes) must survive PATH and
    # relative invocation. Do not realpath the profile symlink before launch.
    profile = root / "package profile ' quote"
    profile.symlink_to(PACKAGE, target_is_directory=True)
    child = root / "child"
    child.mkdir()
    for index, (invocation, cwd, search_path) in enumerate((
        ([profile / "bin/caveman"], root, str(profile / "bin")),
        (["caveman"], root, str(profile / "bin")),
        (["./" + profile.name + "/bin/caveman"], root, str(profile / "bin")),
        (["../" + profile.name + "/bin/caveman"], child, str(profile / "bin")),
        (["bin/caveman"], profile, str(profile / "bin")),
        (["caveman"], profile, "bin"),
    )):
        home = root / f"package-home-{index}"
        home.mkdir()
        env = {"HOME": str(home), "USERPROFILE": str(home), "PWD": str(cwd),
               "CAVEMAN_HOME": str(home / ".caveman"), "PATH": search_path,
               "CAVEMAN_OFFLINE": "1", "CAVE_NO_KEYCHAIN": "1", "CI": "1", "NO_COLOR": "1"}
        execute([*invocation, "tools", "mcp", "install", "gemini"], env, cwd=cwd)
        entry = load(home / ".gemini/settings.json")["mcpServers"]["caveman"]
        assert entry["command"] == str(profile / "bin/caveman-mcp"), (invocation, entry)
    # Explicit lexical root works for a direct-store invocation. No root and
    # store roots must refuse before config/journal mutation.
    for index, registration_root in enumerate((None, str(PACKAGE), str(profile))):
        home = root / f"store-home-{index}"
        home.mkdir()
        env = {"HOME": str(home), "CAVEMAN_HOME": str(home / ".caveman"),
               "PATH": "", "CI": "1", "CAVEMAN_OFFLINE": "1", "CAVE_NO_KEYCHAIN": "1"}
        if registration_root is not None:
            env["CAVEMAN_REGISTRATION_ROOT"] = registration_root
        result = execute([PACKAGE / "bin/caveman", "tools", "mcp", "install", "gemini"],
                         env, cwd=root, check=False)
        settings = home / ".gemini/settings.json"
        if registration_root == str(profile):
            assert result.returncode == 0, result.stderr
            assert load(settings)["mcpServers"]["caveman"]["command"] == str(profile / "bin/caveman-mcp")
        else:
            assert result.returncode != 0, (registration_root, result.stdout, result.stderr)
            assert not settings.exists()
            assert not (home / ".caveman/mcp/gemini.json").exists()
    # Aider has no serialized executable; a direct-store call needs no root.
    home = root / "store-aider-home"
    hosts = root / "aider-probe"
    home.mkdir()
    hosts.mkdir()
    (hosts / "aider").symlink_to(NODE)
    env = {"HOME": str(home), "CAVEMAN_HOME": str(home / ".caveman"),
           "PATH": str(hosts), "CI": "1", "CAVEMAN_OFFLINE": "1", "CAVE_NO_KEYCHAIN": "1",
           "CAVE_GATEWAY_URL": "https://gateway.example.invalid"}
    execute([PACKAGE / "bin/caveman", "enable", "aider"], env, cwd=root)
    config = (home / ".aider.conf.yml").read_text()
    assert "https://gateway.example.invalid/w/aider/openai/v1" in config
    assert "read:" in config
    journal = load(home / ".caveman/integrations/aider.json")
    core = next(item for item in journal["operations"] if item["kind"] == "aider-core")
    assert "correctness" in Path(core["file"]).read_text()
    assert not (home / ".caveman/mcp/aider.json").exists()
    execute([PACKAGE / "bin/caveman", "disable", "aider"], env, cwd=root)
    assert not (home / ".caveman/integrations/aider.json").exists()


def main():
    # Large executable copies stay on inherited TMPDIR. Only native state gets
    # a separate short path, shared throughout each scenario's A/B lifecycle.
    root = Path(tempfile.mkdtemp(prefix="caveman-profile-check-")).resolve()
    retain_root = False
    try:
        package_invocations(root)
        filtered_profiles(root)
        for name, case in (
            ("mcp", mcp_lifetime), ("delegate", custom_delegate),
            ("shrink", shrink_callbacks), ("native", native_integrations),
            ("ownership", ownership_controls),
            ("hermes-yaml", hermes_yaml),
            ("hermes-semantic", hermes_semantic_ownership),
            ("hermes-plugin-scalars", hermes_plugin_scalars),
            ("hermes-markers", hermes_foreign_markers),
            ("hermes-foreign-removal", hermes_foreign_removal),
            ("native-registration", native_registration_commands),
        ):
            state = short_native_state()
            fixture = None
            case_root = root / name
            if name == "native-registration":
                case_root /= "registration space /nix/store/fixture"
            try:
                fixture = Fixture(case_root, cave=state)
                case(fixture)
            finally:
                try:
                    # Construction only copies payloads and compresses locally.
                    # Runtime processes start inside the scenario itself.
                    if fixture is not None:
                        fixture.cli("stop")
                except BaseException as error:
                    retain_root = True
                    raise RuntimeError(
                        f"Cannot stop fixture processes; retained copies at {root} and state at {state}"
                    ) from error
                try:
                    if case_root.exists():
                        shutil.rmtree(case_root)
                finally:
                    shutil.rmtree(state)
            print(f"profile behavioral coverage: {name}", flush=True)
    finally:
        if not retain_root:
            shutil.rmtree(root)
    print("Limits: synthetic same-version copied generations; no Nix activation/GC or real host sessions.")
    print("Limits: Claude/OpenClaw delegated MCP installers and genuine OpenClaw SDK execution need host E2E.")
    print(f"Platform exercised: {sys.platform}; other native platforms need their own check execution.")


if __name__ == "__main__":
    main()
