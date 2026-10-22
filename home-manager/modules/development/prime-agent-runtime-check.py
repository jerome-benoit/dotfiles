"""Exercise kernel overrides and daemon generations in the installed Nix package."""

import json
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import tempfile
import time

binary = pathlib.Path(sys.argv[1]).resolve()
python = pathlib.Path(sys.argv[2])
git = pathlib.Path(sys.argv[3])


def run(command, env, cwd):
    return subprocess.run(
        [str(arg) for arg in command],
        env=env,
        cwd=cwd,
        input="",
        text=True,
        capture_output=True,
        timeout=30,
    )

def check_selected_sources(root, env):
    skills = root / "agent/skills"
    selected = skills / "edit"
    unique = skills / "nix-source-probe"
    for directory, name in [(selected, "edit"), (unique, "nix-source-probe")]:
        module = directory / "src" / name.replace("-", "_")
        module.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Selected source check\n---\nCall this Python skill.\n"
        )
        (directory / "pyproject.toml").write_text(
            f'[project]\nname="{name}"\nversion="0.1.0"\ndependencies=[]\n'
        )
    (unique / "src/nix_source_probe/helper.py").write_text("VALUE = 43\n")
    (unique / "src/nix_source_probe/__init__.py").write_text(
        "from .helper import VALUE\nasync def run(): return VALUE\n"
    )
    selected_module = selected / "src/edit/__init__.py"
    selected_code = (
        "from nix_source_probe import run as other_run\n"
        "async def run(): return {'source': 'user-edit', 'relative': await other_run()}\n"
    )
    selected_module.write_text(selected_code)
    result_file = root / "selected-source.json"
    code = (
        "import json, pathlib\n"
        f"pathlib.Path({str(result_file)!r}).write_text(json.dumps("
        "{'value': await edit(), 'file': edit.__file__, 'unique': await nix_source_probe()}))"
    )
    script = {"responses": [
        {"content": [{"type": "toolCall", "name": "ipython", "arguments": {"code": code}}]},
        "Source check complete",
    ]}
    result = run(
        [binary, "--no-session", "-p", "Check selected skill sources"],
        {**env, "PRIME_AGENT_FAUX_SCRIPT": json.dumps(script)},
        root,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert json.loads(result_file.read_text()) == {
        "value": {"source": "user-edit", "relative": 43},
        "file": str(selected_module),
        "unique": 43,
    }
    selected_module.write_text(
        "import nix_missing_dependency_for_source_check\nasync def run(): return 'wrong fallback'\n"
    )
    failure_file = root / "selected-failure.txt"
    code = (
        "import pathlib\n"
        "try:\n    await edit()\n"
        "except RuntimeError as error:\n"
        f"    pathlib.Path({str(failure_file)!r}).write_text(str(error))"
    )
    script["responses"][0]["content"][0]["arguments"]["code"] = code
    try:
        result = run(
            [binary, "--no-session", "-p", "Check selected source failure"],
            {**env, "PRIME_AGENT_FAUX_SCRIPT": json.dumps(script)},
            root,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "nix_missing_dependency_for_source_check" in failure_file.read_text()
    finally:
        selected_module.write_text(selected_code)
    print("Skills: selected user source wins; fresh and relative imports work; failed source never falls back")



def check_kernel(root, env):
    default = run([binary, "--prime-agent-bootstrap"], env, root)
    assert default.returncode == 0, (default.stdout, default.stderr)
    assert str(python) in default.stdout, default.stdout

    missing = str(root / "missing-python")
    invalid = run(
        [binary, "--prime-agent-bootstrap"],
        {**env, "PRIME_AGENT_KERNEL_PYTHON": missing},
        root,
    )
    assert invalid.returncode != 0, (invalid.stdout, invalid.stderr)
    assert missing in invalid.stdout + invalid.stderr

    venv = root / "kernel"
    created = run([python, "-m", "venv", "--without-pip", venv], env, root)
    assert created.returncode == 0, (created.stdout, created.stderr)
    alternate = venv / "bin/python3"
    site = run(
        [alternate, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        env,
        root,
    )
    assert site.returncode == 0, site.stderr
    paths = run(
        [python, "-c", "import json, sys; print(json.dumps([p for p in sys.path if p.endswith('site-packages')]))"],
        env,
        root,
    )
    assert paths.returncode == 0, paths.stderr

    skill = root / "agent/skills/nix-check"
    module = skill / "src/nix_check"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text("async def run(): return 42\n")
    (skill / "SKILL.md").write_text(
        "---\nname: nix-check\ndescription: Kernel environment check\n---\nCall await nix_check().\n"
    )
    (skill / "pyproject.toml").write_text(
        '[project]\nname="nix-check"\nversion="0.1.0"\ndependencies=[]\n'
    )
    # The alternate environment owns its import paths; no installation touches the store.
    (pathlib.Path(site.stdout.strip()) / "nix-check.pth").write_text(
        "\n".join([*json.loads(paths.stdout), str(skill / "src")]) + "\n"
    )
    result_file = root / "kernel-result.json"
    code = (
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(result_file)!r}).write_text("
        "json.dumps({'value': await nix_check(), 'prefix': sys.prefix}))"
    )
    script = {"responses": [
        {"content": [{"type": "toolCall", "name": "ipython", "arguments": {"code": code}}]},
        "Kernel check complete",
    ]}
    result = run(
        [binary, "--no-session", "-p", "Check the kernel environment"],
        {**env, "PRIME_AGENT_KERNEL_PYTHON": str(alternate), "PRIME_AGENT_FAUX_SCRIPT": json.dumps(script)},
        root,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result_file.is_file(), (result.stdout, result.stderr)
    assert json.loads(result_file.read_text()) == {"value": 42, "prefix": str(venv)}
    assert not (root / "agent/kernel-venv").exists()
    print("Kernel: packaged default works; invalid override fails; alternate environment executes its own skill")

def check_extension_updates(root, env):
    env = {key: value for key, value in env.items() if key != "PI_OFFLINE"}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
    work = root / "extension-work"
    work.mkdir()
    bare = root / "extension.git"
    source = "https://localhost/fixtures/extension"
    installed = root / "agent/git/localhost/fixtures/extension"
    installed.parent.mkdir(parents=True)

    def git_run(*args, cwd=work):
        result = run([git, *args], env, cwd)
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    def commit(message):
        git_run("add", "value.txt")
        git_run(
            "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-m", message,
        )
        return git_run("rev-parse", "HEAD")

    git_run("init", "--initial-branch=main")
    (work / "value.txt").write_text("one\n")
    first = commit("one")
    git_run("clone", "--bare", work, bare)
    git_run("clone", bare, installed)
    (root / "agent/settings.json").write_text(json.dumps({"packages": [source]}))
    assert git_run("rev-parse", "HEAD", cwd=installed) == first
    (work / "value.txt").write_text("two\n")
    second = commit("two")
    git_run("push", bare, "main")
    result = run([binary, "package", "update", source], env, root)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert git_run("rev-parse", "HEAD", cwd=installed) == second
    assert (installed / "value.txt").read_text() == "two\n"
    print("Extensions: default environment updates an unpinned Git package from its local origin")


def check_admission_race(root, env, hello, raw, other):
    address = root / "admission.sock"
    commands = []
    identities = []
    errors = []
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(address))
        listener.listen(2)
        listener.settimeout(10)

        def serve():
            try:
                for executable in [raw, other]:
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(10)
                        greeting = {
                            **hello,
                            "runtime": {**hello["runtime"], "executablePath": str(executable)},
                        }
                        connection.sendall((json.dumps(greeting) + "\n").encode())
                        identities.append(str(executable))
                        with connection.makefile("rb") as wire:
                            for line in wire:
                                if line.strip():
                                    commands.append(json.loads(line))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            result = run([binary, "--mode", "acp", "--daemon-socket", address], env, root)
            thread.join(timeout=15)
            assert not thread.is_alive(), "admission fixture did not finish"
            assert not errors, errors
            assert identities == [str(raw), str(other)], identities
            assert result.returncode != 0, (result.stdout, result.stderr)
            assert not commands, commands
        finally:
            listener.close()
            thread.join(timeout=11)
            address.unlink(missing_ok=True)
    print("Admission: replacement between probe and ACP connection receives no command")



def check_daemon(root, env):
    address = root / "daemon.sock"
    env = {**env, "PRIME_AGENT_DAEMON_SOCKET": str(address)}
    raw = binary.parent.parent / "libexec/prime-agent"
    alias = root / "same-generation"
    alias.symlink_to(raw)
    other = root / "other-generation"
    shutil.copyfile(raw, other)
    other.chmod(0o755)
    client_env = {
        **env,
        "PI_PACKAGE_DIR": str(binary.parent.parent / "share/prime-agent"),
        "PRIME_AGENT_KERNEL_PYTHON": str(python),
    }
    daemon = subprocess.Popen(
        [str(binary), "--mode", "daemon", "--daemon-socket", str(address)],
        env=env,
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    stream = socket.socket(socket.AF_UNIX)
    stream.settimeout(15)
    wire = None
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                stream.connect(str(address))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                assert daemon.poll() is None, daemon.stderr.read().decode()
                if time.monotonic() >= deadline:
                    raise TimeoutError("isolated daemon readiness")
                time.sleep(0.01)
        wire = stream.makefile("rwb", buffering=0)
        hello = json.loads(wire.readline())
        sequence = 0

        def request(command):
            nonlocal sequence
            sequence += 1
            rid = str(sequence)
            wire.write((json.dumps({
                "type": "command", "id": rid, "clientId": "nix-install-check",
                "protocol": hello["protocol"], "command": command,
            }) + "\n").encode())
            while True:
                frame = wire.readline()
                assert frame, "existing daemon connection closed"
                response = json.loads(frame)
                if response.get("id") == rid:
                    assert response.get("success"), response
                    return response.get("data")

        script_file = root / "daemon-script.json"
        script_file.write_text(json.dumps({"responses": ["Session preserved"]}))
        created = request({"type": "create", "config": {
            "cwd": str(root), "sessionDir": str(root / "sessions"), "script": str(script_file),
        }})
        session = created.get("activeSessionId") or created["id"]
        request({"type": "attach", "activeSessionId": session, "clientId": "nix-install-check"})
        before = request({"type": "get_state", "activeSessionId": session})
        assert before["attachedClients"] == 1 and before["isSessionActive"] is False, before

        refused = run([other, "--mode", "acp", "--daemon-socket", address], client_env, root)
        assert refused.returncode != 0, (refused.stdout, refused.stderr)
        assert daemon.poll() is None, "generation check stopped the existing daemon"
        after = request({"type": "get_state", "activeSessionId": session})
        assert after["sessionId"] == before["sessionId"], (before, after)
        assert after["workerInstanceId"] == before["workerInstanceId"], (before, after)
        assert after["attachedClients"] == before["attachedClients"], (before, after)

        accepted = run([alias, "--mode", "acp", "--daemon-socket", address], client_env, root)
        assert accepted.returncode == 0, (accepted.stdout, accepted.stderr)
        request({"type": "prompt_and_wait", "activeSessionId": session, "message": "Check preserved session"})
        state = request({"type": "get_state", "activeSessionId": session})
        assert state["sessionId"] == before["sessionId"], state
        assert state["workerInstanceId"] == before["workerInstanceId"], state
        assert daemon.poll() is None
        check_admission_race(root, client_env, hello, raw, other)
        print("Daemon: different executable refused; attached session preserved and usable; same executable alias accepted")
    finally:
        if wire is not None:
            wire.close()
        stream.close()
        try:
            stopped = run([binary, "shutdown", "--force", "--json"], env, root)
            assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
            daemon.wait(timeout=10)
        finally:
            daemon.stderr.close()


# Short absolute paths also fit native Darwin AF_UNIX limits inside Nix builds.
with tempfile.TemporaryDirectory(prefix="pa-check-", dir="/tmp") as temporary:
    root = pathlib.Path(temporary)
    env = {
        "HOME": str(root), "TMPDIR": str(root), "PATH": "",
        "XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_DATA_HOME": str(root / "data"), "PRIME_AGENT_CODING_AGENT_DIR": str(root / "agent"),
        "DO_NOT_TRACK": "1", "PI_OFFLINE": "1", "NO_COLOR": "1",
    }
    check_selected_sources(root, env)
    check_kernel(root, env)
    check_extension_updates(root, env)
    check_daemon(root, env)
