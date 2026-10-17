"""Exercise the installed CLI, shared recovery store and Nix ownership boundary."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


package = Path(sys.argv[1])
git = sys.argv[2]

with tempfile.TemporaryDirectory(prefix="caveman-check-") as temporary:
    root = Path(temporary)
    home = root / "home"
    home.mkdir()
    cave = home / ".caveman"
    env = {
        "PATH": str(package / "bin"),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "CAVEMAN_HOME": str(cave),
        "CAVE_NO_KEYCHAIN": "1",
        "CAVEMAN_OFFLINE": "1",
        "CI": "1",
        "NO_COLOR": "1",
        "TERM": "dumb",
    }

    def run(binary, *arguments, data=None, check=True):
        result = subprocess.run(
            [str(package / "bin" / binary), *arguments],
            input=data,
            env=env,
            cwd=root,
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
        "commit", "--allow-empty", "-m", "Fixture",
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

print("Caveman: managed installs refused; CLI/MCP recovery, TOON and standalone proxy commit analysis passed")
