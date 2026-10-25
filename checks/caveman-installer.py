"""Offline acceptance for the packaged standalone installer.

Usage: python caveman-installer.py PACKAGE NODE SHELL [UPSTREAM_SOURCE]

This exercises real copying/preparation and hook writers, not fake host managers.
The exported writers are the same functions called after a successful skills
manager install. Calling them directly deliberately does not claim that npx or a
host discovered, installed, trusted, enabled, or ran the integration.

Lifetime cases copy the source, CLI dist, and genuine Node/Bash executables into
owned A/B generations. Deleting all of A models unavailable package paths, not
Nix garbage collection; external shared libraries and closure tools remain.
Callback harnesses observe real events, mode files, and MCP recovery, not a
running host application's discovery or trust decisions.
"""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile


package = Path(sys.argv[1]).absolute()
node = sys.argv[2]
shell = sys.argv[3]
upstream = Path(sys.argv[4]) if len(sys.argv) > 4 else None
source = package / "share/caveman/source"


def snapshot(root):
    """Include foreign bytes, link targets, and permissions, but not timestamps."""
    if not root.exists():
        return {}
    result = {}
    for target in sorted(root.rglob("*")):
        mode = stat.S_IMODE(target.lstat().st_mode)
        if target.is_symlink():
            value = ("link", mode, os.readlink(target))
        elif target.is_dir():
            value = ("directory", mode)
        else:
            value = ("file", mode, target.read_bytes())
        result[str(target.relative_to(root))] = value
    return result


def payload_bytes(root):
    """Copies use private directory modes; compare all actual file bytes."""
    return {
        relative: (value[0], *value[2:])
        for relative, value in snapshot(root).items()
    }


def call(arguments, env, cwd, *, data=None, success=True):
    result = subprocess.run(
        [str(argument) for argument in arguments], env=env, cwd=cwd,
        input=data, capture_output=True, timeout=40,
    )
    if success:
        assert result.returncode == 0, (
            arguments, result.returncode, result.stdout.decode(), result.stderr.decode()
        )
    return result


def native_executable(path):
    """Unwrap fixture inputs without changing the installed package or store."""
    path = Path(path).resolve()
    for _ in range(8):
        with path.open("rb") as stream:
            if stream.read(2) != b"#!":
                return path
        candidates = [
            Path(token)
            for line in path.read_text().splitlines()
            if line.lstrip().startswith("exec ")
            for token in shlex.split(line)
            if token.startswith("/") and Path(token).is_file()
        ]
        assert candidates, f"Cannot find native executable behind {path}"
        path = candidates[0].resolve()
    raise AssertionError(f"Wrapper cycle at {path}")


def writable_copy(original, destination):
    shutil.copytree(original, destination)
    for directory, _, files in os.walk(destination):
        Path(directory).chmod(0o755)
        for name in files:
            target = Path(directory) / name
            target.chmod(stat.S_IMODE(target.stat().st_mode) | 0o600)


class Fixture:
    def __init__(self, root, *, lifetime=False):
        self.root = root
        self.home = root / "home"
        self.home.mkdir(parents=True)
        self.empty = root / "empty-path"
        self.empty.mkdir()
        self.env = {
            "HOME": str(self.home), "USERPROFILE": str(self.home),
            "PATH": str(self.empty), "TMPDIR": str(root),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "CAVEMAN_HOME": str(self.home / ".caveman"),
            "CAVEMAN_DEFAULT_MODE": "caveman", "CAVEMAN_OFFLINE": "1",
            "CAVE_NO_KEYCHAIN": "1", "CI": "1", "NO_COLOR": "1",
            "TERM": "dumb",
        }
        # Ordinary ownership cases exercise the shipped package directly.
        # Only lifetime cases need independent, writable executable generations.
        self.profile = root / "profile"
        self.env["CAVEMAN_REGISTRATION_ROOT"] = str(self.profile)
        self.generations = []
        self.source = source
        if lifetime:
            self.trace = root / "node-events.jsonl"
            observer = root / "observe-node.cjs"
            observer.write_text("""
const fs = require('node:fs');
const entry = process.argv[1];
fs.appendFileSync(process.env.CAVEMAN_TEST_NODE_EVENTS, JSON.stringify({
  executable: process.execPath,
  entry: entry && fs.existsSync(entry) ? fs.realpathSync(entry) : null,
}) + '\\n');
""")
            self.env["NODE_OPTIONS"] = "--require=" + str(observer)
            self.env["CAVEMAN_TEST_NODE_EVENTS"] = str(self.trace)
            self.generations.append(self.generation("generation-a"))
            self.profile.symlink_to(self.generations[0], target_is_directory=True)
            self.source = self.profile / "share/caveman/source"
            self.version = call(
                [self.profile / "bin/caveman", "--version"],
                {**self.env, "PATH": ""}, self.root,
            ).stdout
        else:
            self.profile.symlink_to(package, target_is_directory=True)

    def generation(self, name):
        location = self.root / name
        private = location / "share/caveman"
        private.mkdir(parents=True)
        (location / "bin").mkdir()
        writable_copy(source, private / "source")
        writable_copy(package / "share/caveman/dist", private / "dist")
        shutil.copy2(package / "lib/caveman/package.json", private / "package.json")
        (private / "package.json").chmod(0o644)
        node_launcher = (package / "share/caveman/node").read_text()
        launcher_shell = Path(shlex.split(node_launcher.splitlines()[0][2:])[0])
        launcher_node = next(
            Path(token) for line in node_launcher.splitlines()
            if line.lstrip().startswith("exec ")
            for token in shlex.split(line)
            if token.startswith("/") and Path(token).is_file()
        )
        interpreters = {
            native_executable(launcher_node): private / ".node-real",
            native_executable(launcher_shell): private / ".bash-real",
        }
        for original, copied in interpreters.items():
            shutil.copy2(original, copied)
            copied.chmod(0o755)
            assert not os.path.samefile(copied, original)
        replacements = {
            str(source.resolve()): str(private / "source"),
            str((package / "share/caveman/dist").resolve()): str(private / "dist"),
            str(package / "lib/caveman"): str(private),
            str(package): str(location),
            str(native_executable(node)): str(private / ".node-real"),
            str(Path(node)): str(private / ".node-real"),
            str(launcher_node): str(private / ".node-real"),
            str(native_executable(package / "share/caveman/bash")): str(private / ".bash-real"),
            str(launcher_shell): str(private / ".bash-real"),
        }
        # Preserve the shipped launchers' real closure environment, including
        # Bash's grep/sed/coreutils. Only owned payload/interpreter paths move;
        # shared native libraries and external closure tools remain in Nix.
        launchers = [
            entry.relative_to(package) for entry in (package / "bin").iterdir()
        ] + [Path("share/caveman/node"), Path("share/caveman/bash")]
        for relative in launchers:
            original_path = package / relative
            destination = location / relative
            with original_path.open("rb") as stream:
                is_script = stream.read(2) == b"#!"
            if not is_script:
                # Native companions are separate immutable closure inputs, not
                # the A/B JavaScript implementation or private interpreters.
                destination.symlink_to(original_path.resolve())
                continue
            text = original_path.read_text()
            for original, copied in sorted(replacements.items(), key=lambda item: -len(item[0])):
                text = text.replace(original, copied)
            destination.write_text(text)
            destination.chmod(0o755)
        return location

    def install(self, *arguments, success=True):
        return call(
            [self.profile / "bin/caveman-install", *arguments,
             "--non-interactive", "--no-color"], self.env, self.root, success=success,
        )

    def switch(self):
        assert len(self.generations) == 1
        self.generations.append(self.generation("generation-b"))
        self.profile.unlink()
        self.profile.symlink_to(self.generations[1], target_is_directory=True)
        shutil.rmtree(self.generations[0])
        assert not self.generations[0].exists()
        # Exercise the real private launcher and native executable, not merely
        # lexical profile spelling while the original interpreter stays live.
        actual = call(
            [self.profile / "share/caveman/node", "-p", "process.execPath"],
            {**self.env, "PATH": ""}, self.root,
        ).stdout.decode().strip()
        assert Path(actual) == self.generations[1] / "share/caveman/.node-real", actual
        actual_shell = call(
            [self.profile / "share/caveman/bash", "-c", 'printf "%s" "$BASH"'],
            {**self.env, "PATH": ""}, self.root,
        ).stdout.decode()
        assert Path(actual_shell).resolve() == self.generations[1] / "share/caveman/.bash-real", actual_shell
        before = len(self.node_events())
        version = call(
            [self.profile / "bin/caveman", "--version"],
            {**self.env, "PATH": ""}, self.root,
        ).stdout
        assert version == self.version
        events = self.node_events()[before:]
        self.assert_current_node(events)
        assert any(
            event["entry"] == str(self.generations[1] / "share/caveman/dist/index.js")
            for event in events
        ), events

    def node_events(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def assert_current_node(self, events):
        expected = self.generations[-1] / "share/caveman/.node-real"
        assert events and all(Path(event["executable"]) == expected for event in events), events

    def writer(self, name):
        # No manager substitutes: run the real owning preparation function.
        program = """
const installer = require(process.argv[1] + '/installer/install.js');
const ctx = {
  repoRoot: process.argv[1], configDir: process.env.CLAUDE_CONFIG_DIR,
  opts: {withHooks: true, force: false, dryRun: false},
  results: {installed: [], skipped: [], failed: [], detected: 0},
  note: () => {}, warn: message => process.stderr.write(message + '\\n'),
};
Promise.resolve(installer[process.argv[2]](ctx)).then(value => {
  if (ctx.results.failed.length) throw new Error(JSON.stringify(ctx.results.failed));
  if (process.argv[2] === 'installHooks' && value !== 'ok') throw new Error(String(value));
}).catch(error => { console.error(error); process.exitCode = 1; });
"""
        interpreter = self.profile / "share/caveman/node" if self.generations else node
        return call([interpreter, "-e", program, self.source, name], self.env, self.root)

    def command(self, command, *, environment=None, mode="caveman", payload=None):
        assert str(self.profile / "share/caveman/node") in command, command
        assert self.generations and str(self.generations[0]) not in command, command
        env = {**self.env, "PATH": "", "CAVEMAN_DEFAULT_MODE": mode, **(environment or {})}
        data = json.dumps({
            "cwd": str(self.root), "workspace_roots": [str(self.root)],
            "source": "startup", "session_id": "installer-acceptance",
            **(payload or {}),
        }).encode()
        before = len(self.node_events())
        result = call(
            [self.profile / "share/caveman/.bash-real", "-c", command],
            env, self.root, data=data,
        )
        self.assert_current_node(self.node_events()[before:])
        return result.stdout.decode()


def ruleset(mode="caveman"):
    text = (source / "skills" / mode / "SKILL.md").read_text()
    return re.sub(r"^---[\s\S]*?---\s*", "", text).rstrip()


def assert_context(output, key=None, mode="caveman"):
    text = json.loads(output)[key] if key else output
    assert text.strip(), output
    assert ruleset(mode) in text, text[:300]


def claude_events(fixture, hooks, config_dir, *, environment=None, prepared=False):
    """Run every emitted Claude callback and assert state/events, not exit 0."""
    def command(event, marker):
        return next(
            hook["command"] for group in hooks[event] for hook in group["hooks"]
            if marker in hook["command"]
        )

    activate = command("SessionStart", "caveman-activate")
    output = fixture.command(activate, environment=environment)
    assert output.strip(), output
    if prepared:
        assert_context(output)
    flag = config_dir / ".caveman-sessions/installer-acceptance.mode"
    assert flag.read_text().strip() == "caveman"
    tracker = command("UserPromptSubmit", "caveman-mode-tracker")
    output = json.loads(fixture.command(
        tracker, environment=environment, payload={"prompt": "/ultracave"},
    ))["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit", output
    assert output["additionalContext"].strip(), output
    assert flag.read_text().strip() == "ultracave"
    if prepared:
        assert_context(output["additionalContext"], mode="ultracave")
    subagent = command("SubagentStart", "caveman-activate")
    output = json.loads(fixture.command(subagent, environment=environment))["hookSpecificOutput"]
    assert output["hookEventName"] == "SubagentStart", output
    assert output["additionalContext"].strip(), output
    assert flag.read_text().strip() == "ultracave"
    if prepared:
        assert_context(output["additionalContext"], mode="ultracave")
    transcript = fixture.root / "installer-acceptance.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant", "message": {
            "id": "observed-response", "model": "protocol-fixture",
            "usage": {"output_tokens": 37, "cache_read_input_tokens": 11},
        },
    }) + "\n")
    fixture.command(
        command("SessionEnd", "caveman-stats"), environment=environment,
        payload={"transcript_path": str(transcript)},
    )
    rows = [
        json.loads(line)
        for line in (config_dir / ".caveman-history.jsonl").read_text().splitlines()
    ]
    assert rows[-1]["session_id"] == "installer-acceptance", rows
    assert rows[-1]["output_tokens"] == 37, rows
    assert rows[-1]["cache_read_input_tokens"] == 11, rows


def mcp(fixture, argv, *requests):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "installer-check", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        *requests,
    ]
    result = call(
        argv, {**fixture.env, "PATH": ""}, fixture.root,
        data=b"".join((json.dumps(message) + "\n").encode() for message in messages),
    )
    replies = {
        item["id"]: item for line in result.stdout.splitlines()
        if (item := json.loads(line)).get("id") is not None
    }
    assert set(replies) == {message["id"] for message in messages if "id" in message}, replies
    assert all("error" not in reply for reply in replies.values()), replies
    assert replies[1]["result"]["protocolVersion"], replies
    assert {"caveman_compress", "caveman_retrieve"} <= {
        tool["name"] for tool in replies[2]["result"]["tools"]
    }, replies
    return replies


def tool_text(reply):
    result = reply["result"]
    assert not result.get("isError"), result
    return "".join(item.get("text", "") for item in result["content"])


with tempfile.TemporaryDirectory(prefix="caveman-installer-check-") as temporary:
    root = Path(temporary).resolve()

    # Package use is opt-in: help/list must not create a config, skill, journal,
    # plugin registration, or managed executable cache in the isolated HOME.
    fixture = Fixture(root / "no-implicit-setup")
    before = snapshot(fixture.home)
    call([package / "bin/caveman", "--help"], fixture.env, fixture.root)
    for argument in ("--help", "--list"):
        call([package / "bin/caveman-install", argument], fixture.env, fixture.root)
    assert snapshot(fixture.home) == before
    assert not (package / "bin/node").exists(), "Node must remain private"

    # On Linux, stale directories without a discovered executable are not host
    # detection. Darwin application discovery requires native platform coverage.
    if sys.platform == "linux":
        for directory in (".warp", ".qoder", ".gemini/antigravity", ".cursor"):
            (fixture.home / directory).mkdir(parents=True, exist_ok=True)
        before = snapshot(fixture.home)
        detected = fixture.install()
        assert b"no agents detected" in detected.stdout, detected.stdout
        assert snapshot(fixture.home) == before


    # Every native skills-only identity stays a full copy, not an invented MCP
    # registration. Each case also checks the original upstream default/override
    # resolver by running the unpatched installer when its source is supplied.
    native_cases = [
        ("continue", {}, ".continue/skills"),
        ("continue", {"CONTINUE_GLOBAL_DIR": "relative-continue"}, "@relative-continue/skills"),
        ("aider-desk", {}, ".aider-desk/skills"),
        ("aider-desk", {"AIDER_DESK_DIR": "alternate-desk"}, "alternate-desk/skills"),
        ("aider-desk", {"AIDER_DESK_HOME_DIR": "relative-desk", "AIDER_DESK_DIR": "ignored"}, "@relative-desk/skills"),
        ("antigravity", {}, ".gemini/antigravity/skills"),
        ("antigravity-2", {}, ".gemini/config/skills"),
        ("grok", {}, ".grok/skills"),
        ("grok", {"GROK_HOME": "relative-grok"}, "@relative-grok/skills"),
        ("iflow", {"IFLOW_HOME": "relative-iflow"}, "@relative-iflow/skills"),
        ("crush", {"CRUSH_SKILLS_DIR": "relative-crush-exact"}, "@relative-crush-exact"),
    ]
    skill_directories = sorted(
        entry.name for entry in (source / "skills").iterdir()
        if entry.is_dir() and (entry / "SKILL.md").is_file()
    )
    assert "caveman" in skill_directories and "cavecrew" in skill_directories
    for index, (identity, overrides, relative) in enumerate(native_cases):
        fixture = Fixture(root / f"native-{index}-{identity}")
        fixture.env.update(overrides)
        destination = (fixture.root / relative[1:]) if relative.startswith("@") else fixture.home / relative
        fixture.install("--only", identity)
        for skill in skill_directories:
            copied = destination / skill
            assert payload_bytes(copied) == payload_bytes(source / "skills" / skill), (identity, skill)
            assert not copied.is_symlink(), copied
        assert not list(fixture.home.rglob("*mcp*.json")), identity
        first = snapshot(fixture.home), snapshot(destination)
        fixture.install("--only", identity)
        assert (snapshot(fixture.home), snapshot(destination)) == first, identity
        if upstream:
            original = Fixture(root / f"upstream-{index}-{identity}")
            original.env.update(overrides)
            original.env.pop("CAVEMAN_REGISTRATION_ROOT")
            call([node, upstream / "installer/install.js", "--only", identity,
                  "--non-interactive", "--no-color"], original.env, original.root)
            original_destination = (original.root / relative[1:]) if relative.startswith("@") else original.home / relative
            assert snapshot(destination) == snapshot(original_destination), identity
        edited = destination / "caveman/SKILL.md"
        edited.chmod(0o600)
        edited.write_bytes(edited.read_bytes() + b"\nUser skill customization.\n")
        foreign = destination / "foreign/SKILL.md"
        foreign.parent.mkdir()
        foreign.write_bytes(b"Foreign skill bytes\x00\xff\n")
        foreign.chmod(0o640)
        protected = edited.read_bytes()
        journal = destination.parent / f".caveman-skills-{identity}-ownership.json"
        journal_before = journal.read_bytes()
        failure = fixture.install("--only", identity, success=False)
        assert failure.returncode != 0
        assert edited.read_bytes() == protected
        assert journal.read_bytes() == journal_before
        removal = fixture.install("--uninstall", success=False)
        assert removal.returncode != 0
        assert edited.read_bytes() == protected
        assert foreign.read_bytes() == b"Foreign skill bytes\x00\xff\n"
        assert stat.S_IMODE(foreign.stat().st_mode) == 0o640
        assert not (destination / "ultracave").exists()

    # --force means back up then restore user content, not seize it permanently.
    fixture = Fixture(root / "native-force-restore")
    custom = fixture.home / ".continue/skills/caveman/SKILL.md"
    custom.parent.mkdir(parents=True)
    custom.write_bytes(b"Original user skill\x00\xff\n")
    custom.chmod(0o640)
    fixture.install("--only", "continue", "--force")
    assert custom.read_bytes() == (source / "skills/caveman/SKILL.md").read_bytes()
    fixture.install("--uninstall")
    assert custom.read_bytes() == b"Original user skill\x00\xff\n"
    assert stat.S_IMODE(custom.stat().st_mode) == 0o640

    # Refuse both a symlinked payload and a symlinked discovery ancestor, even
    # with --force. Stable executable profile links are intentionally different.
    for ancestor in (False, True):
        fixture = Fixture(root / f"native-link-{ancestor}")
        external = fixture.root / "external"
        external.mkdir()
        (external / "sentinel").write_bytes(b"do not touch\x00\xff")
        destination = fixture.home / ".continue/skills"
        destination.parent.mkdir(parents=True)
        if ancestor:
            destination.symlink_to(external, target_is_directory=True)
        else:
            destination.mkdir()
            (destination / "caveman").symlink_to(external, target_is_directory=True)
        before = snapshot(fixture.home), snapshot(external)
        failure = fixture.install("--only", "continue", "--force", success=False)
        assert failure.returncode != 0, failure.stdout
        assert b"symbolic" in failure.stderr, failure.stderr
        assert (snapshot(fixture.home), snapshot(external)) == before

    # Real OMP preparation and the generated extension's actual event output.
    # The API object drives plugin callbacks; it does not impersonate the host
    # manager or claim that OMP discovered/loaded this prepared package.
    fixture = Fixture(root / "omp-preparation", lifetime=True)
    omp_plugin = fixture.home / ".omp/caveman-plugin"
    omp_program = """
const directory = process.argv[1];
const callbacks = new Map();
require(directory + '/index.cjs')({on: (name, callback) => callbacks.set(name, callback)});
Promise.resolve(callbacks.get('before_agent_start')({systemPrompt: ['foreign prompt']})).then(async result => {
  const duplicate = await callbacks.get('before_agent_start')(result);
  const badges = [];
  await callbacks.get('session_start')({}, {ui: {setStatus: (...args) => badges.push(args)}});
  process.stdout.write(JSON.stringify({result, duplicate: duplicate === undefined, badges}));
}).catch(error => { console.error(error); process.exitCode = 1; });
"""
    call(
        [fixture.profile / "share/caveman/node", "-e",
         "require(process.argv[1] + '/installer/install.js').writeOmpPluginPackage({repoRoot: process.argv[1]}, process.argv[2]);",
         fixture.source, omp_plugin],
        fixture.env, fixture.root,
    )
    fixture.switch()
    before_events = len(fixture.node_events())
    omp_output = json.loads(call(
        [fixture.profile / "share/caveman/node", "-e", omp_program, omp_plugin],
        {**fixture.env, "PATH": ""}, fixture.root,
    ).stdout)
    fixture.assert_current_node(fixture.node_events()[before_events:])
    assert omp_output["result"]["systemPrompt"][0] == "foreign prompt"
    assert (source / "src/rules/caveman-activate.md").read_text().strip() in (
        "\n".join(omp_output["result"]["systemPrompt"])
    )
    assert omp_output["duplicate"] is True
    assert omp_output["badges"] == [["caveman", "CAVEMAN"]]
    manifest = json.loads((omp_plugin / "package.json").read_text())
    assert manifest["name"] == "caveman"
    assert manifest["omp"]["extensions"] == ["./index.cjs"]
    assert (omp_plugin / "rules/caveman.md").read_bytes() == (source / "src/rules/caveman-activate.md").read_bytes()
    assert payload_bytes(omp_plugin / "skills/caveman") == payload_bytes(source / "skills/caveman")
    assert not (fixture.home / ".pi").exists(), "OMP and Pi are separate identities"

    # Native OpenCode plugin and commands use XDG, not another host's root.
    fixture = Fixture(root / "opencode", lifetime=True)
    fixture.env["XDG_CONFIG_HOME"] = str(fixture.root / "xdg config")
    opencode = Path(fixture.env["XDG_CONFIG_HOME"]) / "opencode"
    opencode.mkdir(parents=True)
    config = opencode / "opencode.json"
    original_config = {
        "plugin": ["foreign-plugin"],
        "provider": {"fixture": {"options": {"apiKey": "fixture-secret", "baseURL": "https://fixture.invalid"}}},
    }
    config.write_text(json.dumps(original_config) + "\n")
    config.chmod(0o640)
    agents = opencode / "AGENTS.md"
    agents.write_text("Foreign OpenCode rules.\n")
    fixture.install("--only", "opencode")
    installed_config = json.loads(config.read_text())
    assert installed_config["plugin"] == ["foreign-plugin", "./plugins/caveman"]
    assert installed_config["provider"] == original_config["provider"]
    assert "mcp" not in installed_config
    assert stat.S_IMODE(config.stat().st_mode) == 0o640
    for name in ("plugin.js", "server.js", "package.json"):
        assert (opencode / "plugins/caveman" / name).read_bytes() == (source / "src/plugins/opencode" / name).read_bytes()
    assert (opencode / "skills/caveman/SKILL.md").read_bytes() == (source / "skills/caveman/SKILL.md").read_bytes()
    assert agents.read_text().startswith("Foreign OpenCode rules.\n")
    before = snapshot(opencode)
    fixture.install("--only", "opencode")
    assert snapshot(opencode) == before
    fixture.switch()
    opencode_program = """
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const plugin = await import(pathToFileURL(process.argv[1]).href);
const callbacks = await plugin.CavemanPlugin({});
const state = () => readFileSync(process.argv[2], 'utf8').trim();
await callbacks.event({event: {type: 'session.created'}});
const started = state();
await callbacks['chat.message']({}, {parts: [{type: 'text', text: '/ultracave'}]});
const changed = state();
const output = {system: ['foreign prompt']};
await callbacks['experimental.chat.system.transform']({}, output);
await callbacks['experimental.chat.system.transform']({}, output);
process.stdout.write(JSON.stringify({started, changed, output}));
"""
    before_events = len(fixture.node_events())
    observed = json.loads(call(
        [fixture.profile / "share/caveman/node", "--input-type=module", "-e",
         opencode_program, opencode / "plugins/caveman/plugin.js", opencode / ".caveman-active"],
        {**fixture.env, "PATH": ""}, fixture.root,
    ).stdout)
    fixture.assert_current_node(fixture.node_events()[before_events:])
    assert observed["started"] == "caveman", observed
    assert observed["changed"] == "ultracave", observed
    context = "\n".join(observed["output"]["system"])
    assert context.startswith("foreign prompt"), context
    assert context.count(ruleset("ultracave")) == 1, context
    fixture.install("--uninstall")
    assert json.loads(config.read_text()) == original_config
    assert agents.read_text() == "Foreign OpenCode rules.\n"
    assert not (opencode / "plugins/caveman").exists()
    assert not (fixture.home / ".config/opencode").exists()

    # The public installer must persist the bundled JavaScript middleware, not
    # bare npx or the different native Go shrink command. The upstream launcher
    # only records argv and runs the genuine packaged MCP server over stdio.
    fixture = Fixture(root / "opencode-mcp-generation-switch", lifetime=True)
    upstream_server = fixture.root / "upstream-mcp"
    shutil.copy2(native_executable(package / "bin/caveman-mcp"), upstream_server)
    upstream_server.chmod(0o755)
    observed_arguments = fixture.root / "upstream-arguments.json"
    fixture.env.update(
        CAVEMAN_TEST_UPSTREAM=str(upstream_server),
        CAVEMAN_TEST_UPSTREAM_ARGUMENTS=str(observed_arguments),
    )
    upstream_launcher = """
const fs = require('node:fs');
const {spawnSync} = require('node:child_process');
fs.writeFileSync(process.env.CAVEMAN_TEST_UPSTREAM_ARGUMENTS, JSON.stringify({
  argv: process.argv.slice(1), executable: process.execPath,
}));
const result = spawnSync(process.env.CAVEMAN_TEST_UPSTREAM, [], {stdio: 'inherit'});
if (result.error) throw result.error;
process.exitCode = result.status === null ? 1 : result.status;
"""
    upstream_arguments = ["argument with spaces", "single ' quote", 'double " quote', "backslash\\tail"]
    upstream_argv = [
        str(fixture.profile / "share/caveman/node"), "-e", upstream_launcher,
        *upstream_arguments,
    ]
    fixture.install("--only", "opencode", "--with-mcp-shrink=" + json.dumps(upstream_argv))
    config_root = Path(fixture.env["XDG_CONFIG_HOME"]) / "opencode"
    configs = list(config_root.glob("opencode.json*"))
    assert len(configs) == 1, configs
    stored = json.loads(configs[0].read_text())["mcp"]["caveman-shrink"]
    assert stored["enabled"] is True, stored
    argv = stored["command"]
    assert isinstance(argv, list) and argv, stored
    fixture.switch()
    baseline = mcp(fixture, [upstream_server])
    original = json.dumps({
        "rows": [
            {"id": index, "label": "café", "detail": f"Recover exact record {index}: spaces, 'quotes', and \\slashes."}
            for index in range(128)
        ],
    }, ensure_ascii=False)
    before_events = len(fixture.node_events())
    compressed = mcp(fixture, argv, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "caveman_compress", "arguments": {"input": original, "content_type": "json"},
        },
    })
    events = fixture.node_events()[before_events:]
    fixture.assert_current_node(events)
    middleware = fixture.generations[1] / "share/caveman/source/src/mcp-servers/caveman-shrink/index.js"
    assert any(event["entry"] == str(middleware) for event in events), events
    observed = json.loads(observed_arguments.read_text())
    assert observed["argv"] == upstream_arguments, observed
    assert observed["executable"] == str(fixture.generations[1] / "share/caveman/.node-real"), observed
    descriptions = {
        tool["name"]: tool["description"] for tool in baseline[2]["result"]["tools"]
    }
    assert any(
        tool["description"] != descriptions[tool["name"]]
        for tool in compressed[2]["result"]["tools"]
    ), compressed[2]
    report = json.loads(tool_text(compressed[3]))
    assert report["compressed"] != original and report["recovery_handle"], report
    retrieved = mcp(fixture, argv, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "caveman_retrieve", "arguments": {"recovery_handle": report["recovery_handle"]},
        },
    })
    assert tool_text(retrieved[3]).encode() == original.encode(), retrieved[3]

    # Explicit overrides and host-native layout remain the original upstream
    # layout. Hermes is skills-only; it does not gain an MCP callback here.
    fixture = Fixture(root / "hermes")
    fixture.env["HERMES_HOME"] = "  $HOME/custom-hermes  "
    fixture.install("--only", "hermes")
    hermes = fixture.home / "custom-hermes/skills/productivity"
    assert (hermes / "caveman/SKILL.md").read_bytes() == (source / "skills/caveman/SKILL.md").read_bytes()
    assert not (fixture.home / ".hermes").exists()
    assert not list(fixture.home.rglob("*mcp*.json"))
    fixture.install("--uninstall")
    assert not (hermes / "caveman").exists()

    fixture = Fixture(root / "openclaw")
    workspace = fixture.root / "independent-workspace"
    workspace.mkdir()
    soul = workspace / "SOUL.md"
    soul.write_text("User-owned soul.\n")
    soul.chmod(0o640)
    fixture.env.update(OPENCLAW_WORKSPACE=str(workspace), OPENCLAW_STATE_DIR=str(fixture.root / "state"))
    fixture.install("--only", "openclaw")
    installed = workspace / "skills/caveman/SKILL.md"
    assert "always: true" in installed.read_text()
    assert ruleset() in installed.read_text()
    assert "User-owned soul.\n" in soul.read_text()
    assert "<!-- caveman-begin -->" in soul.read_text()
    assert stat.S_IMODE(soul.stat().st_mode) == 0o640
    assert not (fixture.root / "state/workspace").exists()
    before = snapshot(workspace)
    fixture.install("--only", "openclaw")
    assert snapshot(workspace) == before
    fixture.install("--uninstall")
    assert soul.read_text() == "User-owned soul.\n"
    assert stat.S_IMODE(soul.stat().st_mode) == 0o640
    assert not installed.exists()

    # Real owning hook writers, with all external-manager work excluded. Distinct
    # roots include spaces, shell metacharacters and a non-default XDG directory.
    fixture = Fixture(root / "hook-generation-switch", lifetime=True)
    roots = {
        "claude": fixture.root / "claude $profile",
        "codex": fixture.root / "codex $profile",
        "copilot": fixture.root / "copilot $profile",
        "cursor": fixture.home / ".cursor",
    }
    for directory in roots.values():
        directory.mkdir(parents=True)
    fixture.env.update(
        CLAUDE_CONFIG_DIR=str(roots["claude"]), CODEX_HOME=str(roots["codex"]),
        COPILOT_HOME=str(roots["copilot"]),
    )
    foreign_hook = {"matcher": "startup", "hooks": [{"type": "command", "command": "foreign-user-hook"}]}
    codex_hooks = roots["codex"] / "hooks.json"
    codex_hooks.write_text(json.dumps({"theme": "user", "hooks": {"SessionStart": [foreign_hook]}}) + "\n")
    codex_hooks.chmod(0o640)
    claude_settings = roots["claude"] / "settings.json"
    claude_settings.write_text(json.dumps({
        "env": {"ANTHROPIC_AUTH_TOKEN": "fixture-credential", "ANTHROPIC_BASE_URL": "https://fixture.invalid"},
        "statusLine": {"type": "command", "command": "foreign-statusline"},
        "hooks": {"SessionStart": [foreign_hook]},
    }) + "\n")
    claude_settings.chmod(0o640)
    foreign_copilot = roots["copilot"] / "hooks/user.json"
    foreign_copilot.parent.mkdir()
    foreign_copilot.write_bytes(b'{"version":1,"hooks":{}}\n')
    for writer in ("installHooks", "installCodexHook", "installCursorNative", "installCopilotCliHook"):
        fixture.writer(writer)
    claude = json.loads(claude_settings.read_text())
    codex = json.loads(codex_hooks.read_text())
    cursor = json.loads((roots["cursor"] / "hooks.json").read_text())
    copilot = json.loads((roots["copilot"] / "hooks/caveman.json").read_text())
    assert claude["env"]["ANTHROPIC_AUTH_TOKEN"] == "fixture-credential"
    assert claude["env"]["ANTHROPIC_BASE_URL"] == "https://fixture.invalid"
    assert claude["statusLine"]["command"] == "foreign-statusline"
    assert claude["hooks"]["SessionStart"][0] == foreign_hook
    assert codex["hooks"]["SessionStart"][0] == foreign_hook
    assert stat.S_IMODE(claude_settings.stat().st_mode) == 0o640
    assert stat.S_IMODE(codex_hooks.stat().st_mode) == 0o640
    commands = {
        "codex": next(entry["command"] for group in codex["hooks"]["SessionStart"] for entry in group["hooks"] if "codex-sessionstart" in entry["command"]),
        "cursor": cursor["hooks"]["sessionStart"][0]["command"],
        "copilot": copilot["hooks"]["sessionStart"][0]["bash"],
    }
    before = {identity: snapshot(directory) for identity, directory in roots.items()}
    for writer in ("installHooks", "installCodexHook", "installCursorNative", "installCopilotCliHook"):
        fixture.writer(writer)
    assert {identity: snapshot(directory) for identity, directory in roots.items()} == before
    fixture.switch()
    assert_context(fixture.command(commands["codex"]))
    assert_context(fixture.command(commands["cursor"]), "additional_context")
    assert_context(fixture.command(commands["copilot"]), "additionalContext")
    claude_events(fixture, claude["hooks"], roots["claude"])
    assert_context(fixture.command(commands["codex"], mode="ultracave"), mode="ultracave")
    assert fixture.command(commands["codex"], mode="off") == ""
    assert json.loads(fixture.command(commands["copilot"], mode="off")) == {}
    assert foreign_copilot.read_bytes() == b'{"version":1,"hooks":{}}\n'

    # Outside Nix, retain upstream PATH-candidate-first Node selection and the
    # process.execPath fallback. Both cases run real emitted Copilot context.
    for candidate_on_path in (False, True):
        fixture = Fixture(root / f"non-nix-node-{candidate_on_path}")
        fixture.env.pop("CAVEMAN_REGISTRATION_ROOT")
        copilot_root = fixture.root / "copilot"
        fixture.env["COPILOT_HOME"] = str(copilot_root)
        if candidate_on_path:
            candidate = fixture.empty / "node"
            candidate.symlink_to(node)
        else:
            candidate = Path(node).resolve()
        fixture.writer("installCopilotCliHook")
        command = json.loads((copilot_root / "hooks/caveman.json").read_text())["hooks"]["sessionStart"][0]["bash"]
        assert str(candidate) in command, command
        output = call(
            [shell, "-c", command], fixture.env, fixture.root,
            data=json.dumps({"cwd": str(fixture.root)}).encode(),
        ).stdout.decode()
        assert_context(output, "additionalContext")

    # The default Claude statusline is a separate interpreter surface. Test its
    # generated command and actual badge with no user shell tools on PATH.
    fixture = Fixture(root / "statusline-generation-switch", lifetime=True)
    claude_root = fixture.root / "claude status"
    claude_root.mkdir()
    fixture.env["CLAUDE_CONFIG_DIR"] = str(claude_root)
    fixture.writer("installHooks")
    settings = json.loads((claude_root / "settings.json").read_text())
    status_command = settings["statusLine"]["command"]
    assert str(fixture.profile / "share/caveman/bash") in status_command, status_command
    activation_command = next(
        entry["command"] for group in settings["hooks"]["SessionStart"]
        for entry in group["hooks"] if "caveman-activate" in entry["command"]
    )
    fixture.switch()
    assert fixture.command(activation_command).strip()
    assert (claude_root / ".caveman-sessions/installer-acceptance.mode").read_text().strip() == "caveman"
    badge = call(
        [fixture.profile / "share/caveman/.bash-real", "-c", status_command],
        {**fixture.env, "PATH": ""}, fixture.root,
        data=b'{"session_id":"installer-acceptance"}',
    ).stdout
    assert b"[CAVEMAN]" in badge, badge

    # Local plugin preparation does not invent ownership of host marketplace
    # state. Inspect real generated manifests and execute their registered hooks.
    for host in ("claude", "cursor"):
        fixture = Fixture(root / f"prepared-{host}", lifetime=True)
        destination = fixture.root / "mutable payload" / f"{host}-plugin"
        arguments = ("--prepare-plugin", host, "--plugin-dir", str(destination))
        fixture.install(*arguments)
        for skill in ("caveman", "ultracave", "megacave"):
            assert payload_bytes(destination / "skills" / skill) == payload_bytes(source / "skills" / skill)
        assert not (fixture.home / f".{host}").exists(), "preparation must not register with host"
        if host == "claude":
            marketplace = json.loads((destination / ".claude-plugin/marketplace.json").read_text())
            assert marketplace["name"] == "caveman-nix"
            manifest = json.loads((destination / ".claude-plugin/plugin.json").read_text())
            command = manifest["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        else:
            manifest = json.loads((destination / "hooks/hooks-cursor.json").read_text())
            command = manifest["hooks"]["sessionStart"][0]["command"]
        before = snapshot(destination)
        fixture.install(*arguments)
        assert snapshot(destination) == before
        fixture.switch()
        environment = {f"{host.upper()}_PLUGIN_ROOT": str(destination)}
        if host == "claude":
            config_dir = fixture.root / "claude-state"
            environment["CLAUDE_CONFIG_DIR"] = str(config_dir)
            claude_events(fixture, manifest["hooks"], config_dir, environment=environment, prepared=True)
        else:
            output = fixture.command(command, environment=environment)
            assert_context(output, "additional_context")
        modified = destination / "skills/caveman/SKILL.md"
        modified.chmod(0o600)
        modified.write_bytes(modified.read_bytes() + b"\nUser plugin customization.\n")
        before = snapshot(destination)
        journal = destination.parent / f".caveman-{host}-plugin-ownership.json"
        journal_before = journal.read_bytes()
        failure = fixture.install(*arguments, success=False)
        assert failure.returncode != 0 and b"ownership conflict" in failure.stderr, failure.stderr
        assert snapshot(destination) == before
        assert journal.read_bytes() == journal_before
        # Modified payload is not removed, even if a caller acknowledges detach.
        fixture.install(*arguments, "--uninstall", "--plugin-detached", success=False)
        assert snapshot(destination) == before
        fixture.install(*arguments, "--force")
        fixture.install(*arguments, "--uninstall", "--plugin-detached", success=False)
        assert modified.read_bytes().endswith(b"User plugin customization.\n")

    # Default preparation belongs to CAVEMAN_HOME, not a host-owned plugin
    # cache. An explicit detach acknowledgment permits manager-free cleanup.
    for host in ("claude", "cursor"):
        fixture = Fixture(root / f"plugin-clean-uninstall-{host}")
        fixture.install("--prepare-plugin", host)
        destination = Path(fixture.env["CAVEMAN_HOME"]) / f"{host}-plugin"
        assert (destination / "skills/caveman/SKILL.md").read_bytes() == (source / "skills/caveman/SKILL.md").read_bytes()
        journal = destination.parent / f".caveman-{host}-plugin-ownership.json"
        assert json.loads(journal.read_text())["integration"] == f"{host}-plugin"
        if host == "cursor":
            before = snapshot(destination)
            refusal = fixture.install("--prepare-plugin", host, "--uninstall", success=False)
            assert b"host" in refusal.stderr.lower(), refusal.stderr
            assert snapshot(destination) == before
        fixture.install("--prepare-plugin", host, "--uninstall", "--plugin-detached")
        assert not destination.exists() and not journal.exists()
        assert not (fixture.home / f".{host}").exists()

    for host in ("claude", "cursor"):
        fixture = Fixture(root / f"plugin-symlink-{host}")
        foreign = fixture.root / "foreign"
        foreign.mkdir()
        (foreign / "sentinel").write_bytes(b"foreign plugin\x00\xff")
        destination = fixture.root / "payload"
        destination.symlink_to(foreign, target_is_directory=True)
        before = snapshot(foreign)
        failure = fixture.install("--prepare-plugin", host, "--plugin-dir", str(destination), "--force", success=False)
        assert failure.returncode != 0 and b"symbolic" in failure.stderr, failure.stderr
        assert destination.is_symlink() and snapshot(foreign) == before

    for host in ("claude", "cursor"):
        fixture = Fixture(root / f"plugin-parent-symlink-{host}")
        foreign = fixture.root / "foreign"
        foreign.mkdir()
        (foreign / "sentinel").write_bytes(b"foreign parent\x00\xff")
        parent = fixture.root / "linked-parent"
        parent.symlink_to(foreign, target_is_directory=True)
        before = snapshot(foreign)
        failure = fixture.install(
            "--prepare-plugin", host, "--plugin-dir", str(parent / "payload"),
            "--force", success=False,
        )
        assert failure.returncode != 0 and b"real directory" in failure.stderr, failure.stderr
        assert parent.is_symlink() and snapshot(foreign) == before

    # Skills-only installations need no prepared-plugin ancestry or host.
    # Existing payload/journal safeguards are covered separately above.
    for aliased in ("HOME", "CAVEMAN_HOME"):
        fixture = Fixture(root / f"skills-only-aliased-{aliased}")
        alias = fixture.root / "home-alias"
        alias.symlink_to(fixture.home, target_is_directory=True)
        if aliased == "HOME":
            fixture.env.update(HOME=str(alias), USERPROFILE=str(alias))
        fixture.env["CAVEMAN_HOME"] = str(alias / ".caveman")
        foreign = fixture.home / "foreign.txt"
        foreign.write_bytes(b"unrelated user content\x00\xff")
        fixture.install("--only", "continue")
        assert (fixture.home / ".continue/skills/caveman/SKILL.md").is_file()
        fixture.install("--uninstall")
        assert not (fixture.home / ".continue/skills/caveman").exists()
        assert foreign.read_bytes() == b"unrelated user content\x00\xff"

    # Real filesystem refusal, not a fake permission error. Root bypasses POSIX
    # mode checks, so report that missing prerequisite rather than claim coverage.
    if os.geteuid() != 0:
        fixture = Fixture(root / "read-only")
        readonly = fixture.home / ".continue"
        readonly.mkdir()
        readonly.chmod(0o555)
        try:
            before = snapshot(fixture.home)
            failure = fixture.install("--only", "continue", success=False)
            assert failure.returncode != 0, failure.stdout
            assert snapshot(fixture.home) == before
        finally:
            readonly.chmod(0o755)
        for host in ("claude", "cursor"):
            fixture = Fixture(root / f"plugin-read-only-{host}")
            readonly = fixture.root / "read-only-parent"
            readonly.mkdir()
            readonly.chmod(0o555)
            try:
                before = snapshot(readonly)
                failure = fixture.install(
                    "--prepare-plugin", host, "--plugin-dir",
                    str(readonly / "payload"), success=False,
                )
                assert failure.returncode != 0, failure.stdout
                assert snapshot(readonly) == before
            finally:
                readonly.chmod(0o755)
    else:
        print("UNEXERCISED: read-only directory refusal requires a non-root test user")

print("Caveman installer: owned A/B payloads/interpreters, protected ownership, real callback events and MCP shrink recovery passed")
print("UNEXERCISED: real npx skills destinations/scopes and real host discovery/trust/enable/disable sessions; no network or host managers used")
print("UNEXERCISED: Darwin host behavior unless this check itself runs on Darwin; Windows remains outside the Nix platform scope")
