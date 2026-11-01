"""Exercise the installed CLI, shared recovery store and Nix ownership boundary."""

from datetime import datetime, timedelta, timezone
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time


package = Path(sys.argv[1])
git = sys.argv[2]
node = sys.argv[3]
blocks = Path(sys.argv[4])

with tempfile.TemporaryDirectory(prefix="caveman-check-") as temporary:
    root = Path(temporary)
    home = root / "home"
    home.mkdir()
    profile_path = root / "profile"
    profile_path.symlink_to(package, target_is_directory=True)
    cave = home / ".caveman"
    env = {
        "PATH": str(profile_path / "bin"),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "CAVEMAN_HOME": str(cave),
        "CAVEMAN_REGISTRATION_ROOT": str(profile_path),
        "CAVE_NO_KEYCHAIN": "1",
        "CAVEMAN_OFFLINE": "1",
        "CI": "1",
        "NO_COLOR": "1",
        "TERM": "dumb",
    }

    def run(binary, *arguments, data=None, check=True, cwd=None, environment=None):
        result = subprocess.run(
            [str(profile_path / "bin" / binary), *arguments],
            input=data,
            env=environment if environment is not None else env,
            cwd=cwd or root,
            capture_output=True,
            timeout=30,
        )
        if check and result.returncode:
            raise AssertionError(
                f"{binary} {arguments} exited {result.returncode}: {result.stderr.decode()}"
            )
        return result

    # The package manager must retain ownership even for explicit install/update.
    # Refuse before creating an executable cache or touching an agent profile.
    for arguments in [("update",), ("setup", "--install")]:
        result = run("caveman", *arguments, check=False)
        assert result.returncode != 0, arguments
        assert b"managed by Nix" in result.stderr, result.stderr
        assert not (cave / "bin").exists(), arguments
        assert not (cave / "cli").exists(), arguments
        for profile in [".claude", ".codex", ".omp", ".pi", ".hermes"]:
            assert not (home / profile).exists(), profile

    # CLI -> engine compression must retain a byte-exact original that another
    # executable (the MCP server) can recover from the same persistent store.
    original = json.dumps(
        {"results": [{"id": item} for item in range(1, 65)], "error": None}
    ).encode()
    compressed = run("caveman", "tools", "compress", "--type", "json", data=original)
    report = json.loads(compressed.stderr)
    handle = report["recovery_handle"]
    assert handle and compressed.stdout != original, report
    assert run("caveman", "tools", "retrieve", handle).stdout == original
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "caveman_retrieve", "arguments": {"recovery_handle": handle}},
    }
    mcp = run("caveman-mcp", data=(json.dumps(request) + "\n").encode())
    responses = (json.loads(line) for line in mcp.stdout.splitlines())
    response = next(record for record in responses if record.get("id") == 1)
    assert "error" not in response, response
    result = response["result"]
    assert not result.get("isError"), result
    recovered = "".join(item.get("text", "") for item in result["content"])
    assert recovered.encode() == original, result

    # Lossless structured conversion must preserve Unicode and JSON values.
    document = {"name": "café", "rows": [{"id": 1, "ok": False}, {"id": 2, "ok": True}]}
    encoded = run("caveman-engine", "toon", "encode", data=json.dumps(document).encode()).stdout
    decoded = run("caveman-engine", "toon", "decode", data=encoded).stdout
    assert json.loads(decoded) == document

    # A standalone proxy must retain commit-based analysis without Git on the
    # caller's PATH. Only fixture preparation receives an absolute Git path.
    repo = root / "repo"
    repo.mkdir()
    first = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)
    second = first + timedelta(days=1)

    def timestamp(value):
        return value.isoformat().replace("+00:00", "Z")

    def fixture_git(*arguments, dates=None):
        subprocess.run(
            [git, "-c", "core.hooksPath=/dev/null", *arguments],
            env={**env, "GIT_CONFIG_NOSYSTEM": "1", **(dates or {})},
            cwd=repo,
            capture_output=True,
            check=True,
            timeout=10,
        )

    fixture_git("-c", "init.defaultBranch=main", "init", ".")
    fixture_git(
        "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "--allow-empty", "-m",
        "Fixture\n\n" + "wrapper recovery fixture line\n" * 64,
        dates={"GIT_AUTHOR_DATE": timestamp(first), "GIT_COMMITTER_DATE": timestamp(first)},
    )
    sessions = home / ".claude/projects/fixture"
    sessions.mkdir(parents=True)
    for index in range(8):
        record = {
            "type": "assistant",
            "cwd": str(repo),
            "timestamp": timestamp(first if index < 4 else second),
            "message": {
                "id": f"fixture-{index}",
                "model": "claude-sonnet-4",
                "usage": {"input_tokens": 20000},
            },
        }
        (sessions / f"session-{index}.jsonl").write_text(json.dumps(record) + "\n")
    plan = json.loads(run(
        "caveman-proxy", "learn", "scan", "--sources", "claude",
        "--since", "30d", "--no-remember",
    ).stdout)
    assert plan["sessions_by_source"]["claude"] == 8, plan
    outcome = next(sink for sink in plan["sinks"] if sink["sink_id"] == "session_outcomes")
    evidence = outcome["evidence"]
    assert evidence["repositories_measured"] == 1, evidence
    assert evidence["sessions_measured"] == 8, evidence
    assert evidence["with_commit"]["sessions"] == 4, evidence
    assert evidence["without_commit"]["sessions"] == 4, evidence
    assert evidence["without_commit"]["tokens"] == 80000, evidence
    assert evidence["without_commit_token_share_pct"] == 50, evidence

    settings = home / ".claude/settings.json"
    # Durable CLI callbacks must keep the wrapper when the caller has no PATH.
    callback_env = {**env, "PATH": ""}
    run("caveman", "tools", "hooks", "install", "claude", environment=callback_env)
    callback_settings = json.loads(settings.read_text())
    callback = next(
        hook["command"]
        for entry in callback_settings["hooks"]["PreToolUse"]
        if entry["matcher"] == "Bash"
        for hook in entry["hooks"]
    )
    command = "git log -1 --format=%B"
    rewritten = subprocess.run(
        shlex.split(callback),
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}).encode(),
        env=callback_env, cwd=repo, capture_output=True, check=True, timeout=30,
    )
    invocation = json.loads(rewritten.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
    shrunk = subprocess.run(
        shlex.split(invocation),
        env=callback_env, cwd=repo, capture_output=True, check=True, timeout=30,
    )
    callback_report = json.loads(shrunk.stderr)
    callback_handle = callback_report["recovery_handle"]
    assert callback_handle and callback_handle.encode() in shrunk.stdout, callback_report
    original_log = subprocess.run(
        [git, "log", "-1", "--format=%B"],
        env=callback_env, cwd=repo, capture_output=True, check=True, timeout=10,
    ).stdout
    assert run(
        "caveman", "tools", "retrieve", callback_handle, environment=callback_env,
    ).stdout == original_log

    # Runtime rewrites are not persistent registrations. They must work from
    # a store launcher without a profile, retaining the executing wrapper's tools.
    for registration_root in (None, str(profile_path)):
        runtime_env = {**callback_env, "CAVEMAN_NATIVE_PROFILE": "full-safe"}
        runtime_env.pop("CAVEMAN_REGISTRATION_ROOT", None)
        if registration_root is not None:
            runtime_env["CAVEMAN_REGISTRATION_ROOT"] = registration_root
        response = subprocess.run(
            [str(package / "bin/caveman"), "shrink-hook"],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}).encode(),
            env=runtime_env, cwd=repo, capture_output=True, check=True, timeout=30,
        )
        runtime_command = json.loads(response.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
        result = subprocess.run(
            shlex.split(runtime_command), env=runtime_env, cwd=repo,
            capture_output=True, check=True, timeout=30,
        )
        report = json.loads(result.stderr)
        assert result.stdout != original_log
        assert run(
            "caveman", "tools", "retrieve", report["recovery_handle"], environment=runtime_env,
        ).stdout == original_log

    # Execute the command actually registered for the harness. A copied native
    # executable loses Git and writes its events under a different repository id.
    foreign_hook = {"matcher": "Read", "hooks": [{"type": "command", "command": "echo preserve"}]}
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [foreign_hook]}}))
    stable_hook = home / ".local/share/caveman-blocks/bin/caveman-blocks"
    run("caveman-blocks", "init", cwd=repo)
    assert not stable_hook.exists(), "init must not install a hook"
    run("caveman-blocks", "hooks", "install", "--harness", "claude-code", cwd=repo)
    configured = json.loads(settings.read_text())
    assert foreign_hook in configured["hooks"]["PreToolUse"], configured
    commands = [
        hook["command"]
        for group in configured["hooks"]["PreToolUse"]
        for hook in group["hooks"]
        if "caveman-blocks" in hook["command"]
    ]
    hook_command = shlex.split(commands[0])

    def send_event(index):
        event = {
            "session_id": "fixture-session",
            "tool_use_id": f"fixture-call-{index}",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(repo),
            "tool_input": {"command": f"caveman-blocks run json-peek --path sample-{index}.json"},
        }
        run(hook_command[0], *hook_command[1:], data=json.dumps(event).encode(), cwd=repo)

    def assert_recorded_calls(count):
        stats = run("caveman-blocks", "stats", cwd=repo).stdout.decode()
        assert int(re.search(r"^sessions seen\s+(\d+)", stats, re.M)[1]) == 1, stats
        assert int(re.search(r"^block calls\s+(\d+)", stats, re.M)[1]) == count, stats

    send_event(1)
    assert_recorded_calls(1)
    run("caveman-blocks", "hooks", "install", "--harness", "claude-code", cwd=repo)
    assert_recorded_calls(1)

    # Seed upstream's same-version raw copy, then refresh through the wrapper.
    native_blocks = blocks.resolve().with_name(".caveman-blocks-wrapped")
    stable_hook.unlink()
    run(str(native_blocks), "hooks", "install", "--harness", "claude-code", cwd=repo)
    assert not stable_hook.is_symlink()
    run("caveman-blocks", "doctor", cwd=repo)
    send_event(2)
    assert_recorded_calls(2)

    # Explicit refresh repairs a collected generation; read-only sync must not.
    stable_hook.unlink()
    missing_target = str(root / "removed-generation/bin/caveman-blocks")
    stable_hook.symlink_to(missing_target)
    run("caveman-blocks", "sync", "--check", cwd=repo, check=False)
    assert os.readlink(stable_hook) == missing_target
    run("caveman-blocks", "doctor", cwd=repo)
    send_event(3)
    assert_recorded_calls(3)
    # Running the installed launcher must not rewrite its link to itself.
    selected_wrapper = os.readlink(stable_hook)
    for index, selected_root in enumerate((None, str(stable_hook.parent.parent)), start=4):
        launcher_env = {**env}
        launcher_env.pop("CAVEMAN_REGISTRATION_ROOT")
        if selected_root is not None:
            launcher_env["CAVEMAN_REGISTRATION_ROOT"] = selected_root
        run(str(stable_hook), "doctor", cwd=repo, environment=launcher_env, check=False)
        assert os.readlink(stable_hook) == selected_wrapper
        send_event(index)
        assert_recorded_calls(index)
    run("caveman-blocks", "hooks", "uninstall", "--harness", "claude-code", cwd=repo)
    assert json.loads(settings.read_text())["hooks"]["PreToolUse"] == [foreign_hook]
    assert_recorded_calls(5)

    # OpenCode 2 returns structured shell output plus content parts. Hints must
    # reach those parts without changing exit metadata or leaking from failed calls.
    run("caveman-blocks", "add", "json-peek", cwd=repo)
    run("caveman-blocks", "hooks", "install", "--harness", "opencode", cwd=repo)
    plugin = home / ".config/opencode/plugins/caveman-blocks.js"
    (repo / "nested").mkdir()
    (repo / "~literal").mkdir()
    run(node, "--input-type=module", "-", str(plugin), str(repo), cwd=root, data=r"""
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { CavemanBlocks, default: plugin } = await import(pathToFileURL(process.argv[2]));
const hooks = new Map();
const directory = process.argv[3];
assert.notEqual(process.cwd(), directory);
await plugin.setup({
  location: { directory },
  tool: { hook: async (name, callback) => hooks.set(name, callback) },
});
const command = "python3 - <<'EOF'\nimport json\nd=json.load(open('x.json'))\nprint(d.keys())\nEOF";
const before = (id, command, sessionID = `fixture-${id}`, messageID = `msg_${id}`, workdir) => hooks.get("execute.before")({
  tool: "shell", sessionID, messageID, id, input: { command, workdir },
});
const after = (id, result, sessionID = `fixture-${id}`, messageID = `msg_${id}`) => ({
  tool: "shell", sessionID, messageID, id, status: "completed", result,
});
const hint = "Blocks: json-peek covers this. Next time: caveman-blocks run json-peek --path <path>";
const legacy = await CavemanBlocks({ directory });
const beforeV1 = (callID, command, sessionID, workdir) => legacy["tool.execute.before"]({
  tool: "bash", sessionID, callID,
}, { args: { command, workdir } });
const afterV1 = async (callID, sessionID) => {
  const output = { output: "legacy output", metadata: { exit: 7 } };
  await legacy["tool.execute.after"]({ tool: "bash", sessionID, callID }, output);
  assert.deepEqual(output.metadata, { exit: 7 });
  return output.output;
};
await beforeV1("shared", command, "legacy-a");
await beforeV1("shared", "printf ok", "legacy-b");
assert.equal(await afterV1("shared", "legacy-b"), "legacy output");
assert.equal(await afterV1("shared", "legacy-a"), `legacy output\n\n${hint}`);
assert.equal(await afterV1("shared", "legacy-a"), "legacy output");
await beforeV1("shared", command, "legacy-a");
await beforeV1("shared", command, "legacy-b");
await beforeV1("shared", "printf ok", "legacy-a");
assert.equal(await afterV1("shared", "legacy-a"), "legacy output");
assert.equal(await afterV1("shared", "legacy-b"), `legacy output\n\n${hint}`);
await beforeV1("invalid", command, "legacy-invalid");
await beforeV1("invalid", command, "legacy-invalid", { invalid: true });
assert.equal(await afterV1("invalid", "legacy-invalid"), "legacy output");
await before("matched", command);
await before("plain", "printf ok");
const output = { output: "stderr\n", exit: 7, truncated: false, status: "completed" };
const result = {
  output,
  content: [{ type: "text", text: output.output }],
  metadata: { status: "completed", exit: 7, truncated: false },
};
const matched = after("matched", result);
await hooks.get("execute.after")(matched);
assert.strictEqual(matched.result.output, output);
assert.deepEqual(matched.result.metadata, result.metadata);
assert.deepEqual(matched.result.content, [...result.content, { type: "text", text: hint }]);
const plain = after("plain", result);
await hooks.get("execute.after")(plain);
assert.deepEqual(plain.result, result);
await before("failed", command);
await hooks.get("execute.after")({
  tool: "shell", sessionID: "fixture-failed", messageID: "msg_failed", id: "failed", status: "error",
  error: new Error("tool failed"),
});
const retried = after("failed", result);
await hooks.get("execute.after")(retried);
assert.deepEqual(retried.result, result);
// One plugin serves multiple sessions; provider call IDs are not server-wide IDs.
await before("shared", command, "session-a");
await before("shared", "printf ok", "session-b");
const otherSession = after("shared", result, "session-b");
await hooks.get("execute.after")(otherSession);
assert.deepEqual(otherSession.result, result);
const matchingSession = after("shared", result, "session-a");
await hooks.get("execute.after")(matchingSession);
assert.deepEqual(matchingSession.result.content, [...result.content, { type: "text", text: hint }]);
await before("shared", command, "session-a");
await before("shared", command, "session-b");
await hooks.get("execute.after")({
  tool: "shell", sessionID: "session-b", messageID: "msg_shared", id: "shared", status: "error",
  error: new Error("other session failed"),
});
const survivingSession = after("shared", result, "session-a");
await hooks.get("execute.after")(survivingSession);
assert.deepEqual(survivingSession.result.content, [...result.content, { type: "text", text: hint }]);
const failedSession = after("shared", result, "session-b");
await hooks.get("execute.after")(failedSession);
assert.deepEqual(failedSession.result, result);
// Interrupted tools have no after event; call IDs can recur in a later message.
await before("reused", command, "session-cancel", "msg_interrupted");
await before("reused", "printf ok", "session-cancel", "msg_resumed");
const resumed = after("reused", result, "session-cancel", "msg_resumed");
await hooks.get("execute.after")(resumed);
assert.deepEqual(resumed.result, result);
await before("reused", command, "session-cancel", "msg_next");
const late = after("reused", result, "session-cancel", "msg_interrupted");
await hooks.get("execute.after")(late);
const next = after("reused", result, "session-cancel", "msg_next");
await hooks.get("execute.after")(next);
assert.deepEqual(next.result.content, [...result.content, { type: "text", text: hint }]);
const duplicate = after("reused", result, "session-cancel", "msg_next");
await hooks.get("execute.after")(duplicate);
assert.deepEqual(duplicate.result, result);
// The server cwd differs from the location. Home expansion follows POSIX rules.
for (const [workdir, matches] of [
  [undefined, true], ["", true], [directory, true], [".", true], ["nested", true],
  [process.cwd(), false], ["..", false], ["~", false],
  ["~/../repo", true], ["~/..", false], ["~literal", true],
]) {
  const sessionID = `session-cwd-${workdir}`;
  await before("cwd", command, sessionID, `msg_${workdir}`, workdir);
  const event = after("cwd", result, sessionID, `msg_${workdir}`);
  await hooks.get("execute.after")(event);
  assert.deepEqual(event.result.content, matches
    ? [...result.content, { type: "text", text: hint }]
    : result.content, `workdir=${workdir}`);
  assert.strictEqual(event.result.output, output);
  assert.deepEqual(event.result.metadata, result.metadata);
  await beforeV1("cwd", command, sessionID, workdir);
  assert.equal(await afterV1("cwd", sessionID),
    matches ? `legacy output\n\n${hint}` : "legacy output", `v1 workdir=${workdir}`);
}
console.log("OpenCode 1/2: output, metadata, invocation isolation and location workdirs passed");
""".encode())
    run("caveman-blocks", "hooks", "uninstall", "--harness", "opencode", cwd=repo)
    foreign_root = home / ".config/opencode/foreign.json"
    foreign_root.write_text('{"foreign":true}\n')
    for additions in (
        {"XDG_CONFIG_HOME": None},
        {"XDG_CONFIG_HOME": None, "OPENCODE_CONFIG_DIR": ""},
        {"XDG_CONFIG_HOME": str(root / "blocks xdg ' $literal")},
        {"XDG_CONFIG_HOME": str(root / "blocks empty xdg ' $literal"), "OPENCODE_CONFIG_DIR": ""},
        {"XDG_CONFIG_HOME": str(root / "blocks unused-xdg"),
         "OPENCODE_CONFIG_DIR": str(root / "blocks override ' $literal")},
    ):
        selected_env = {key: value for key, value in {**env, **additions}.items() if value is not None}
        expected = Path(selected_env.get("OPENCODE_CONFIG_DIR") or
                        str(Path(selected_env.get("XDG_CONFIG_HOME") or home / ".config") / "opencode"))
        run("caveman-blocks", "hooks", "install", "--harness", "opencode", cwd=repo, environment=selected_env)
        selected_plugin = expected / "plugins/caveman-blocks.js"
        assert selected_plugin.exists()
        report = json.loads(run("caveman-blocks", "hooks", "status", "--harness", "opencode", "--json",
                                cwd=repo, environment=selected_env).stdout)
        assert report["harnesses"][0]["installed"] is True, report
        assert report["harnesses"][0]["config"] == str(selected_plugin), report
        if expected != plugin.parent.parent:
            assert not plugin.exists()
        run("caveman-blocks", "hooks", "uninstall", "--harness", "opencode", cwd=repo, environment=selected_env)
        assert not selected_plugin.exists()
        assert foreign_root.read_text() == '{"foreign":true}\n'
        run("caveman-blocks", "hooks", "install", "--harness", "claude-code",
            cwd=repo, environment=selected_env)
        claude_report = json.loads(run(
            "caveman-blocks", "hooks", "status", "--harness", "claude-code", "--json",
            cwd=repo, environment=selected_env).stdout)
        assert claude_report["harnesses"][0]["installed"] is True, claude_report
        run("caveman-blocks", "hooks", "uninstall", "--harness", "claude-code",
            cwd=repo, environment=selected_env)
    relative_env = {**env, "OPENCODE_CONFIG_DIR": "relative-opencode"}
    refusal = run("caveman-blocks", "hooks", "install", "--harness", "opencode",
                  cwd=repo, environment=relative_env, check=False)
    assert refusal.returncode != 0 and b"must be absolute" in refusal.stderr
    assert not (repo / "relative-opencode").exists()
    assert foreign_root.read_text() == '{"foreign":true}\n'

    # A persisted native hook bypasses the CLI wrapper. With only the package
    # on PATH it must revive, identify and stop its own proxy, including on Darwin.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    hook_env = {
        **env,
        "CAVE_GATEWAY_URL": f"http://127.0.0.1:{port}",
        "CAVEMAN_LISTEN": f"127.0.0.1:{port}",
        "DO_NOT_TRACK": "1",
        "CAVEMAN_TELEMETRY": "0",
    }
    event = {
        "hook_event_name": "SessionStart",
        "session_id": "native-hook-fixture",
        "cwd": str(repo),
    }
    owned_state = None
    try:
        try:
            revival = run(
                "caveman-proxy", "native-hook", "claude",
                "--adapter", str(package / "lib/caveman/dist/native-hook-fast.js"),
                "--node", node, data=json.dumps(event).encode(), environment=hook_env,
            )
            deadline = time.monotonic() + 10
            while True:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                try:
                    connection.request("GET", "/health/live")
                    response = connection.getresponse()
                    health = json.loads(response.read())
                    assert response.status == 200, health
                    assert health["ok"] is True, health
                    assert health["service"] == "caveman-proxy", health
                    assert health["schema"] == "caveman.proxy.health.v1", health
                    state = json.loads((cave / "run" / f"{port}.json").read_text())
                    assert state["instance_token"] == response.getheader("X-Caveman-Instance"), state
                    owned_state = state
                    assert state["recovery_via_mcp"] is True, state
                    break
                except (OSError, http.client.HTTPException) as error:
                    if time.monotonic() >= deadline:
                        raise AssertionError(
                            f"native hook did not revive proxy: {revival.stderr.decode()}"
                        ) from error
                    time.sleep(0.05)
                finally:
                    connection.close()
            status = json.loads(run(
                "caveman-proxy", "status", "--json", "--port", str(port), environment=hook_env,
            ).stdout)
            assert status["owner"] in {"wrap", "start"}, status
            assert status["pid"] == state["pid"], status
        finally:
            run("caveman", "stop", environment=hook_env)
        with socket.socket() as stopped:
            stopped.settimeout(1)
            assert stopped.connect_ex(("127.0.0.1", port)) != 0, "proxy still listening after stop"
    finally:
        # A failed ownership check makes stop leave the listener alone. Clean up
        # only our proven fixture, after the normal assertions, without hiding them.
        if owned_state is not None:
            with socket.socket() as remaining:
                remaining.settimeout(1)
                listening = remaining.connect_ex(("127.0.0.1", port)) == 0
            if listening:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                try:
                    connection.request(
                        "POST", "/caveman/shutdown",
                        headers={"X-Caveman-Shutdown": owned_state["shutdown_token"]},
                    )
                    connection.getresponse().read()
                except (OSError, http.client.HTTPException) as error:
                    print(f"fixture shutdown failed: {error}", file=sys.stderr)
                finally:
                    connection.close()
                deadline = time.monotonic() + 7
                while True:
                    with socket.socket() as remaining:
                        remaining.settimeout(1)
                        if remaining.connect_ex(("127.0.0.1", port)) != 0:
                            break
                    if time.monotonic() >= deadline:
                        print("fixture proxy still listening after cleanup", file=sys.stderr)
                        break
                    time.sleep(0.05)

print("Caveman: ownership, recovery, proxy analysis, Blocks hooks and native proxy revival passed")
