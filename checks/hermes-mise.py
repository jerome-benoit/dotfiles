"""Exercise the packaged Hermes local terminal through its generated gateway."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile


NONINTERACTIVE_GUARD = 'case "$-" in *i*) exit 91;; esac\n'


def run(argv, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=90, **kwargs)
    assert result.returncode == 0, (argv, result.returncode, result.stdout, result.stderr)
    return result


def activation_count(home):
    log = home / "mise-activations"
    return len(log.read_text().splitlines()) if log.exists() else 0


def consumer(case):
    import tools.environments.local as local
    from tools.process_registry import ProcessRegistry

    home = Path(os.environ["HOME"])
    config = Path(os.environ["HERMES_HOME"]) / "config.yaml"
    enabled = case["enabled"]
    assert os.environ.get("HERMES_NIX_MISE_SHIMS") == ("1" if enabled else None)
    expected = case["versions"] if enabled else ["login-node", "login-node"]
    shims = case["shims"]
    if case["gateway"]:
        for project, version in zip(case["projects"], expected):
            observed = run(["node", "--version"], cwd=project)
            assert observed.stdout.strip() == version, observed.stdout
        path = os.environ["PATH"].split(":")
        assert path.index(str(home / "login bin")) < path.index(case["profile"] + "/.nix-profile/bin")
        assert path.index(case["profile"] + "/.nix-profile/bin") < path.index(str(home / "inherited bin"))
        if enabled:
            assert path.index(shims) < path.index(str(home / "login bin"))
        else:
            assert shims not in path

    def session(mode):
        before = config.read_bytes()
        activations = activation_count(home)
        terminal = local.LocalEnvironment(cwd=case["projects"][0], timeout=15)
        try:
            assert terminal._snapshot_ready, "the real login snapshot must succeed"
            assert Path(terminal._snapshot_path).is_file()

            def execute(command):
                result = terminal.execute(command)
                assert result["returncode"] == 0, result
                return result["output"].strip()

            assert execute("node --version") == expected[0]
            assert execute("cd " + shlex.quote(case["projects"][1]) + "; node --version") == expected[1]
            assert execute("node --version") == expected[1], "cwd must persist across execute calls"
            assert Path(terminal.cwd) == Path(case["projects"][1])
            node = execute("command -v node")
            assert node == str(Path(shims if enabled else home / "login bin") / "node"), node
            path = execute('printf "%s" "$PATH"').split(":")
            if enabled:
                assert path.index(shims) < path.index(str(home / "login bin")), path
            else:
                assert shims not in path, path
            markers = execute(
                'printf "%s|%s|%s|%s" "${HERMES_PROFILE_READY-}" '
                '"${HERMES_BASH_PROFILE_READY-}" "${HERMES_BASHRC_READY-}" '
                '"${HERMES_EXPLICIT_ORDER-}"'
            )
            if mode == "default":
                assert markers == "profile|login|bashrc|", markers
                assert execute('printf "%s" "$HERMES_PROFILE_ORDER"') == "PBR"
            elif mode in ("explicit", "configFile", "reloaded"):
                assert markers == "|login||first:last", markers
            else:
                assert markers == "|login||", markers
        finally:
            terminal.cleanup()
        assert config.read_bytes() == before, "terminal initialization must not rewrite YAML"
        assert activation_count(home) == activations + int(enabled)

    # Keep non-zero execution observable without the success-only helper above.
    def status_session():
        terminal = local.LocalEnvironment(cwd=case["projects"][0], timeout=15)
        try:
            assert terminal._snapshot_ready
            assert terminal.execute("exit 37")["returncode"] == 37
        finally:
            terminal.cleanup()

    if case["config_file"]:
        original = config.read_bytes()
        session("configFile")
        assert config.read_bytes() == original
    else:
        configurations = (
            ("default", "# runtime default\nterminal:\n  auto_source_bashrc: true\n"),
            ("explicit", 'terminal:\n  shell_init_files: ["~/explicit-first", "~/explicit-last"]\n'),
            ("no-extra", "terminal:\n  auto_source_bashrc: false\n"),
            ("reloaded", 'terminal:\n  auto_source_bashrc: false\n  shell_init_files: ["~/explicit-first", "~/explicit-last"]\n# runtime edit\n'),
        )
        for mode, contents in configurations:
            config.write_text(contents)
            session(mode)
        status_session()

    # Upstream background shells are interactive. Use dedicated fixture profiles
    # without weakening the non-interactive gateway/foreground assertion.
    profiles = {home / name: (home / name).read_text() for name in (".bash_profile", ".zprofile")}
    for profile, contents in profiles.items():
        profile.write_text(contents.removeprefix(NONINTERACTIVE_GUARD))
    registry = ProcessRegistry()
    try:
        for restore in (True, False):
            before = activation_count(home)
            process = registry.spawn_local(
                "node --version", cwd=case["projects"][0], restore_login_path=restore,
            )
            result = registry.wait(process.id, timeout=20)
            assert result["status"] == "exited" and process.exit_code == 0, result
            expected_node = expected[0] if restore else "login-node"
            assert expected_node in result["output"].splitlines(), result
            assert activation_count(home) == before + int(enabled and restore)
    finally:
        registry.kill_all()
        for profile, contents in profiles.items():
            profile.write_text(contents)
    if enabled:
        # Fail only after terminal init files, not in the already-valid gateway.
        profile = home / "explicit-last"
        original_profile = profile.read_bytes()
        original_config = config.read_bytes()
        sentinel = home / "must-not-execute"
        profile.write_bytes(original_profile + b"export HERMES_TEST_FAIL_MISE=1\n")
        terminal = None
        try:
            terminal = local.LocalEnvironment(cwd=case["projects"][0], timeout=15)
            assert not terminal._snapshot_ready
            assert not terminal._prefer_nonlogin, "failed profile initialization must not be bypassed"
            result = terminal.execute("printf ran > " + shlex.quote(str(sentinel)))
            assert result["returncode"] == 43 and not sentinel.exists(), result
            assert config.read_bytes() == original_config
        finally:
            if terminal is not None:
                terminal.cleanup()
            profile.write_bytes(original_profile)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--consumer")
    parser.add_argument("--gateway")
    parser.add_argument("--disabled-gateway")
    parser.add_argument("--null-gateway")
    parser.add_argument("--python")
    parser.add_argument("--mise")
    parser.add_argument("--node", nargs=2, action="append")
    parser.add_argument("--shell", action="append")
    parser.add_argument("--runtime-path")
    parser.add_argument("--runtime-shell")
    parser.add_argument("--profile")
    parser.add_argument("--config-setup")
    parser.add_argument("--config-file")
    parser.add_argument("--activation-library")
    args = parser.parse_args()
    if args.consumer:
        consumer(json.loads(args.consumer))
        return
    driver = str(Path(__file__).resolve())
    # mise deliberately excludes canonical /nix paths from shim activation.
    # Use a user-like home, not TMPDIR when Darwin builds place it under /nix.
    with tempfile.TemporaryDirectory(prefix="hermes-mise-", dir="/tmp") as temporary:
        root = Path(temporary).resolve()
        for layout in ("default", "xdg", "data", "settings", "override"):
            home = root / layout
            home.mkdir()
            hermes_home = home / ".hermes"
            hermes_home.mkdir()
            config_home = home / "config"
            config_home.mkdir()
            data = home / ".local/share/mise"
            exports = {"XDG_CONFIG_HOME": str(config_home)}
            if layout == "xdg":
                exports["XDG_DATA_HOME"] = str(home / "xdg data")
                data = home / "xdg data/mise"
            elif layout in ("data", "settings", "override"):
                exports["XDG_DATA_HOME"] = str(home / "unused xdg")
                exports["MISE_DATA_DIR"] = str(home / "mise data")
                data = home / "mise data"
            shims = data / "shims"
            settings = config_home / "mise/config.toml"
            settings.parent.mkdir()
            if layout in ("settings", "override"):
                shims = home / "configured shims"
                settings.write_text("[settings]\nshims_dir = " + json.dumps(str(shims)) + "\n")
            if layout == "override":
                exports["MISE_SHIMS_DIR"] = str(home / "override shims")
                shims = home / "override shims"
            environment = {
                "HOME": str(home), "HERMES_HOME": str(hermes_home),
                "PATH": args.runtime_path, "LC_ALL": "C",
                "MISE_CACHE_DIR": str(home / "cache"), "MISE_STATE_DIR": str(home / "state"),
                "MISE_NOT_FOUND_AUTO_INSTALL": "false", "MISE_NOT_FOUND_SYSTEM_FALLBACK": "false",
                "MISE_TRUSTED_CONFIG_PATHS": str(home), "MISE_OFFLINE": "true",
            }
            setup_environment = dict(environment, **exports)
            projects = []
            for version, installation in args.node:
                run([args.mise, "link", "node@" + version, installation], env=setup_environment, cwd=home)
                project = home / version
                project.mkdir()
                (project / ".tool-versions").write_text("node " + version + "\n")
                projects.append(str(project))
            run([args.mise, "reshim"], env=setup_environment, cwd=home)
            login_bin, inherited_bin = home / "login bin", home / "inherited bin"
            login_bin.mkdir()
            inherited_bin.mkdir()
            for directory, body in ((login_bin, "printf 'login-node\\n'"), (inherited_bin, "exit 94")):
                node = directory / "node"
                node.write_text("#!" + args.runtime_shell + "\n" + body + "\n")
                node.chmod(0o755)
            login = (
                NONINTERACTIVE_GUARD
                + 'export PATH="$HOME/login bin"\nexport HERMES_BASH_PROFILE_READY=login\n'
                + 'export HERMES_PROFILE_ORDER="${HERMES_PROFILE_ORDER-}B"\n'
                + "\n".join("export " + name + "=" + shlex.quote(value) for name, value in exports.items())
                + "\n"
            )
            for filename in (".zprofile", ".bash_profile"):
                (home / filename).write_text(login)
            (home / ".profile").write_text(
                "export HERMES_PROFILE_READY=profile\nexport HERMES_PROFILE_ORDER=P\n"
            )
            (home / ".bashrc").write_text(
                'export HERMES_BASHRC_READY=bashrc\n'
                'export HERMES_PROFILE_ORDER="${HERMES_PROFILE_ORDER-}R"\n'
            )
            (home / "explicit-first").write_text("export HERMES_EXPLICIT_ORDER=first\n")
            (home / "explicit-last").write_text(
                'export HERMES_EXPLICIT_ORDER="${HERMES_EXPLICIT_ORDER}:last"\n'
                'export PATH="$HOME/login bin"\n'
            )
            for shell in args.shell:
                runtime_environment = dict(
                    environment, PATH=str(inherited_bin) + ":" + args.runtime_path,
                    HERMES_TEST_SHELL=shell,
                )
                case = {
                    "projects": projects, "versions": ["v" + version for version, _ in args.node],
                    "shims": str(shims), "config_file": False,
                    "profile": args.profile,
                }
                for gateway, enabled in (
                    (args.gateway, True), (args.disabled_gateway, False), (args.null_gateway, False),
                    (None, False),
                ):
                    case["gateway"] = gateway is not None
                    case["enabled"] = enabled
                    command = [args.python, "-I", "-B", driver, "--consumer", json.dumps(case)]
                    run(([gateway] if gateway else []) + command, env=runtime_environment, cwd=home)
                # Exercise the actual configFile activation, including its settings override.
                setup = Path(args.config_setup).read_text().replace("/__hermes_mise_check__/home", str(home))
                prelude = "source " + shlex.quote(args.activation_library) + "\n"
                run([args.runtime_shell, "-euc", prelude + setup],
                    env=dict(runtime_environment, DRY_RUN_CMD=""), cwd=home)
                config_path = hermes_home / "config.yaml"
                original = Path(args.config_file).read_bytes()
                assert config_path.read_bytes() == original
                case.update(enabled=True, config_file=True, gateway=True)
                run([args.gateway, args.python, "-I", "-B", driver, "--consumer", json.dumps(case)],
                    env=runtime_environment, cwd=home)
                assert config_path.read_bytes() == original
                failure = subprocess.run(
                    [args.gateway, args.python, "-c", "raise SystemExit(0)"],
                    env=dict(runtime_environment, HERMES_TEST_FAIL_MISE="1"),
                    cwd=home, capture_output=True, text=True, timeout=15,
                )
                assert failure.returncode == 43, (failure.returncode, failure.stdout, failure.stderr)
    print("gateway mise: real packaged snapshots, Node 22/24/24, Bash/Zsh, five shim layouts, "
          "runtime/configFile profiles, background opt-in and disabled/null/outside isolation passed")


if __name__ == "__main__":
    main()
