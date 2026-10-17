"""Exercise the installed CLI, shared recovery store and Nix ownership boundary."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


package = Path(sys.argv[1])

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

print("Caveman: managed installs refused; CLI/engine/MCP byte-exact recovery and TOON round trip passed")
