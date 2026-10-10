import base64
import json
import shlex
import socketserver
import subprocess
import sys
import tempfile
import threading
import tomllib
from pathlib import Path


def check_credentials(source, expected):
    text = Path(source).read_text()
    account = tomllib.loads(text)["accounts"]["primary"]
    for protocol in ("imap", "smtp"):
        received = []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(5)
                if protocol == "imap":
                    self.wfile.write(b"* OK synthetic IMAP ready\r\n")
                    while line := self.rfile.readline():
                        tag, command, *args = line.decode().strip().split(" ", 2)
                        if command.upper() == "CAPABILITY":
                            self.wfile.write(
                                b"* CAPABILITY IMAP4rev1\r\n"
                                + tag.encode()
                                + b" OK capability\r\n"
                            )
                        elif command.upper() == "LOGIN":
                            received.append(shlex.split(args[0])[1])
                            self.wfile.write(tag.encode() + b" NO synthetic rejection\r\n")
                            return
                        else:
                            self.wfile.write(tag.encode() + b" BAD unsupported\r\n")
                else:
                    self.wfile.write(b"220 localhost synthetic SMTP\r\n")
                    while line := self.rfile.readline():
                        parts = line.decode().strip().split(" ", 2)
                        command = parts[0].upper()
                        if command == "EHLO":
                            self.wfile.write(b"250-localhost\r\n250 AUTH LOGIN\r\n")
                        elif command == "AUTH" and parts[1].upper() == "LOGIN":
                            if len(parts) < 3:
                                self.wfile.write(b"334 VXNlcm5hbWU6\r\n")
                                self.rfile.readline()
                            self.wfile.write(b"334 UGFzc3dvcmQ6\r\n")
                            received.append(
                                base64.b64decode(self.rfile.readline().strip()).decode()
                            )
                            self.wfile.write(b"535 synthetic rejection\r\n")
                            return
                        elif command == "QUIT":
                            self.wfile.write(b"221 bye\r\n")
                            return
                        else:
                            self.wfile.write(b"500 unsupported\r\n")

        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            with tempfile.TemporaryDirectory() as directory:
                local = Path(directory) / "config.toml"
                local.write_text(
                    text.replace(
                        account[protocol]["server"],
                        f"{protocol}://127.0.0.1:{server.server_address[1]}",
                    )
                )
                try:
                    result = subprocess.run(
                        [
                            "himalaya", "-c", str(local), "-a", "primary", "--json",
                            "account", "check", "--backend", protocol,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                finally:
                    server.shutdown()
                    thread.join()
            assert received == [expected], (protocol, received, result.stdout, result.stderr)
            assert result.returncode == 0, (result.stdout, result.stderr)
            # Refuse authentication after observing the real client's credential.
            report = json.loads(result.stdout)
            assert report["backends"][0]["backend"] == protocol, report
            assert report["backends"][0]["ok"] is False, report
            print(f"HIMALAYA_ARGV_OK: {protocol}; literal credential preserved")


if __name__ == "__main__":
    check_credentials(sys.argv[1], sys.argv[2])
