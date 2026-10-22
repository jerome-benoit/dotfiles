"""Build-time installCheck: prove ``prime-agent update --check`` stays read-only.

Invoked as ``python3 prime-agent-update-readonly.py <prime-agent-binary>`` from
the Nix installCheck. Serves a fake release manifest on loopback and asserts
that, across offline/skip/channel permutations, the wrapper performs only the
expected read-only HTTP calls, never writes ``~/.prime/agent/settings.json``,
and never creates ``~/.local``. ``HOME`` and ``TMPDIR`` come from the environment.
"""

import http.server
import json
import os
import pathlib
import subprocess
import sys
import threading

binary = sys.argv[1]
settings = pathlib.Path(os.environ["HOME"]) / ".prime/agent/settings.json"
before = settings.read_bytes()
requests = []


class ManifestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append(self.path)
        if self.path not in ("/latest.json", "/beta.json"):
            self.send_error(404)
            return
        version = "999.0.0" if self.path == "/latest.json" else "999.0.0-beta.1"
        self.send_response(200)
        self.end_headers()
        # Nix rebuilds sources; published platform archives are not required.
        self.wfile.write(json.dumps({"version": version}).encode())

    def log_message(self, *args):
        pass


with http.server.ThreadingHTTPServer(("127.0.0.1", 0), ManifestHandler) as server:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for offline, skip, channel, expected in (
            ("0", None, "stable", ["/latest.json"]),
            (" Yes ", None, "stable", []),
            (None, None, "stable", ["/latest.json"]),
            ("0", "1", "stable", []),
            ("0", None, "nightly", ["/beta.json"]),
        ):
            env = {
                "HOME": os.environ["HOME"],
                "TMPDIR": os.environ["TMPDIR"],
                "PATH": "",
                "DO_NOT_TRACK": "1",
                "PRIME_AGENT_DOWNLOAD_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            }
            if offline is not None:
                env["PI_OFFLINE"] = offline
            if skip is not None:
                env["PI_SKIP_VERSION_CHECK"] = skip
            requests.clear()
            result = subprocess.run(
                [binary, "update", "--check", f"--{channel}"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            assert result.returncode == (0 if expected else 1), (result.stdout, result.stderr)
            assert requests == expected, requests
            assert settings.read_bytes() == before
            assert not (settings.parents[2] / ".local").exists()
            print(f"Read-only check: offline={offline!r}, skip={skip!r}, channel={channel}, HTTP={requests}")
    finally:
        server.shutdown()
        thread.join()
