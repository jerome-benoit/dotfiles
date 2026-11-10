{
  pkgs,
  home-manager,
  inputs,
}:
let
  lib = import "${home-manager}/modules/lib/stdlib-extended.nix" pkgs.lib;
  fixtureHome = "/home/hermes-check";
  plugin = "${inputs.hermes-labs-plugins}/github-copilot";
  mkConfiguration =
    selectedPkgs:
    home-manager.lib.homeManagerConfiguration {
      pkgs = selectedPkgs;
      extraSpecialArgs = { inherit inputs; };
      modules = [
        inputs.hermes-agent.homeManagerModules.default
        inputs.sops-nix.homeManagerModules.sops
        ../home-manager/modules/core/lib.nix
        ../home-manager/modules/core/sops.nix
        ../home-manager/modules/development/hermes-agent.nix
        ({ lib, ... }: {
          options = {
            modules.core.gpu.acceleration = lib.mkOption {
              type = lib.types.str;
              default = "none";
            };
          };
          config = {
            home = {
              username = "hermes-check";
              homeDirectory = fixtureHome;
              stateVersion = "26.05";
            };
            modules.development.hermesAgent = {
              enable = true;
              plugins.github-copilot = plugin;
            };
            sops.secrets.hermes-env.path = "${fixtureHome}/secret.env";
          };
        })
      ];
    };
  configuration = mkConfiguration pkgs;
  evaluate = settings: configuration.extendModules { modules = [ settings ]; };
  accepts = settings: (builtins.tryEval (evaluate settings).activationPackage.drvPath).success;
  externalHomes = [
    "/srv/hermes"
    "${fixtureHome}-other/.hermes"
    "${fixtureHome}/../outside"
  ];
  nonCanonicalHomes = [
    ""
    "relative-hermes"
    "${fixtureHome}/.hermes/"
    "${fixtureHome}/./.hermes"
    "${fixtureHome}//.hermes"
    "${fixtureHome}/cache/../.hermes"
    "/home//hermes-check/.hermes"
  ];
  check = label: condition: lib.assertMsg condition "Hermes plugin regression: ${label}";
  # Run only the generated state/link fragments, never Home Manager activation or services.
  # An explicit config file avoids building the Hermes Python closure for this shell regression.
  smokeRoot = "/__hermes_activation_check__";
  smokeHome = "${smokeRoot}/home with spaces";
  smokeConfiguration = evaluate {
    home.homeDirectory = lib.mkForce smokeHome;
    modules.development.hermesAgent = {
      enableGateway = true;
      enableDashboard = true;
    };
    services.hermes-agent = {
      hermesHome = "${smokeHome}/custom hermes";
      workingDirectory = "${smokeHome}/working directory";
      configFile = pkgs.writeText "hermes-smoke-config.yaml" ''{"model": "smoke"}'';
      authFile = pkgs.writeText "hermes-smoke-auth.json" ''{"synthetic": true}'';
      documents."AGENTS.md" = "workspace document";
      hermesHomeFiles."SOUL.md" = "home document";
    };
    sops.secrets.hermes-env.path = lib.mkForce "${smokeHome}/secret env";
  };
  smokeActivation = smokeConfiguration.config.home.activation;
  smokeOrder = map (entry: entry.name) (lib.hm.dag.topoSort smokeActivation).result;
  startsBefore =
    first: second:
    lib.lists.findFirstIndex (name: name == first) null smokeOrder
    < lib.lists.findFirstIndex (name: name == second) null smokeOrder;
  startupOrder =
    startsBefore "hermesAgentSetup" "hermesAgentEnvironment"
    && (
      if pkgs.stdenv.hostPlatform.isLinux then
        startsBefore "hermesAgentEnvironment" "reloadSystemd" && startsBefore "reloadSystemd" "sops-nix"
      else
        startsBefore "sops-nix" "hermesAgentEnvironment"
        && startsBefore "hermesAgentEnvironment" "setupLaunchAgents"
    );
  wrappedVoicePython =
    pkgs.runCommand "hermes-voice-discovery-python"
      {
        nativeBuildInputs = [ pkgs.makeWrapper ];
      }
      ''
        mkdir -p "$out/bin"
        ln -s ${configuration.config.services.hermes-agent.package.hermesVenv}/bin/python "$out/bin/python"
        ${configuration.config.services.hermes-agent.package.postFixup}
      '';
  gatewayHome = pkgs.runCommand "hermes-gateway-home" { } ''
    mkdir -p "$out/.nix-profile/bin"
    printf '#!${pkgs.runtimeShell}\nprintf "profile\\n"\n' > "$out/.nix-profile/bin/profile-tool"
    chmod +x "$out/.nix-profile/bin/profile-tool"
  '';
  gatewayConfiguration =
    (mkConfiguration (
      pkgs.extend (
        _: previous: {
          getent = previous.writeShellScriptBin "getent" ''
            printf 'hermes-check:x:1000:1000:fixture:%s:%s\n' "$HOME" "$HERMES_TEST_SHELL"
          '';
        }
      )
    )).extendModules
      {
        modules = [
          ({ lib, ... }: {
            home.homeDirectory = lib.mkForce (builtins.unsafeDiscardStringContext "${gatewayHome}");
            sops.age.keyFile = lib.mkForce "${fixtureHome}/.config/sops/age/keys.txt";
          })
        ];
      };
in
assert lib.all (condition: condition) [
  (check "external Hermes homes fail before activation" (
    lib.all (hermesHome: !accepts { services.hermes-agent.hermesHome = hermesHome; }) externalHomes
  ))
  (check "ambiguous path spellings fail before activation" (
    lib.all (hermesHome: !accepts { services.hermes-agent.hermesHome = hermesHome; }) nonCanonicalHomes
  ))
  (check "non-canonical HOME fails before activation" (
    !accepts { home.homeDirectory = lib.mkForce "${fixtureHome}/../hermes-check"; }
  ))
  (check "canonical homes and custom subdirectories evaluate" (
    lib.all (hermesHome: accepts { services.hermes-agent.hermesHome = hermesHome; }) [
      fixtureHome
      "${fixtureHome}/.hermes"
      "${fixtureHome}/custom hermes"
    ]
  ))
  (check "root HOME retains valid plugin destinations" (
    lib.all
      (
        hermesHome:
        accepts {
          home.homeDirectory = lib.mkForce "/";
          services.hermes-agent.hermesHome = hermesHome;
        }
      )
      [
        "/"
        "/state/hermes"
      ]
  ))
  (check "empty plugins preserve existing Hermes home support" (
    lib.all (
      hermesHome:
      accepts {
        services.hermes-agent.hermesHome = hermesHome;
        modules.development.hermesAgent.plugins = lib.mkForce { };
      }
    ) (externalHomes ++ nonCanonicalHomes)
  ))
  (check "disabled integration does not restrict Hermes home" (
    lib.all (
      hermesHome:
      accepts {
        services.hermes-agent.hermesHome = hermesHome;
        modules.development.hermesAgent.enable = lib.mkForce false;
      }
    ) (externalHomes ++ nonCanonicalHomes)
  ))
  (check "real sops activation orders the link before service startup" startupOrder)
];
pkgs.runCommand "check-hermes-agent"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.coreutils
    ];
    setup = smokeActivation.hermesAgentSetup.data;
    environment = smokeActivation.hermesAgentEnvironment.data;
    passAsFile = [
      "setup"
      "environment"
    ];
  }
  ''
    ${lib.optionalString pkgs.stdenv.hostPlatform.isLinux ''
      # Same wrapper fixup and exact locked wheel; no compiler on caller PATH.
      PATH=${pkgs.coreutils}/bin ${wrappedVoicePython}/bin/python - <<'PY'
      import ctypes.util
      import sounddevice
      assert ctypes.util.find_library("portaudio")
      assert sounddevice._lib is not None
      PY
    ''}
    python3 - ${gatewayConfiguration.config.services.hermes-agent.package.integrationGatewayLogin} ${gatewayHome} <<'PY'
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tempfile

    gateway, profile = sys.argv[1:]
    arguments = ["two words", "single'quote", "", "$HOME; false", "%literal"]
    probe = """
    import json, os, shutil, sys
    print(json.dumps({
        "pid": os.getpid(), "argv": sys.argv[1:], "shell": os.environ["SHELL"],
        "login": os.environ["HERMES_LOGIN_READY"],
        "tools": {name: shutil.which(name) for name in
                  ("priority-tool", "profile-tool", "inherited-tool", "sh")},
    }))
    """
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary)
        login_bin, inherited_bin = home / "login bin", home / "inherited bin"
        for directory, names in (
            (login_bin, ["priority-tool"]),
            (inherited_bin, ["priority-tool", "inherited-tool"]),
        ):
            directory.mkdir()
            for name in names:
                executable = directory / name
                executable.write_text("#!${pkgs.runtimeShell}\nexit 0\n")
                executable.chmod(0o755)
        login = (
            'case "$-" in *i*) exit 91;; esac\n'
            'command -v sh >/dev/null || exit 92\n'
            'export HERMES_LOGIN_READY=1\nexport PATH="$HOME/login bin"\n'
        )
        for filename in (".zprofile", ".bash_profile"):
            (home / filename).write_text(login)
        for shell in ("${pkgs.zsh}/bin/zsh", "${pkgs.bash}/bin/bash"):
            environment = {
                "HOME": str(home), "PATH": str(inherited_bin), "LC_ALL": "C",
                "HERMES_TEST_SHELL": shell, "SHELL": "/not-the-account-shell",
            }
            process = subprocess.Popen(
                [gateway, sys.executable, "-c", probe, *arguments],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, (stdout, stderr)
            result = json.loads(stdout)
            assert result["pid"] == process.pid, "launcher must exec the gateway"
            assert result["argv"] == arguments and result["shell"] == shell
            assert result["login"] == "1"
            assert result["tools"]["priority-tool"] == str(login_bin / "priority-tool")
            assert result["tools"]["profile-tool"] == profile + "/.nix-profile/bin/profile-tool"
            assert result["tools"]["inherited-tool"] == str(inherited_bin / "inherited-tool")
            assert result["tools"]["sh"], "POSIX tools lost after login reset PATH"
            status = subprocess.run(
                [gateway, sys.executable, "-c", "raise SystemExit(37)"],
                env=environment, timeout=15,
            )
            assert status.returncode == 37
        environment["HERMES_TEST_SHELL"] = "${pkgs.coreutils}/bin/false"
        rejected = subprocess.run(
            [gateway, sys.executable, "-c", "raise SystemExit(0)"],
            env=environment, capture_output=True, text=True, timeout=15,
        )
        assert rejected.returncode == 1 and "POSIX-compatible login shell" in rejected.stderr
    print("gateway login: bash/zsh, PATH precedence, argv, exec and exit status passed")
    PY
    python3 - ${smokeConfiguration.config.services.hermes-agent.package.integrationSecretGate} ${gatewayConfiguration.config.services.hermes-agent.package.integrationGatewayLogin} <<'PY'
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tempfile
    import time
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        secret = root / "home with spaces/secret env"
        secret.parent.mkdir(parents=True)
        gate = root / "gate"
        gate.write_text(Path(sys.argv[1]).read_text().replace("${smokeRoot}", temporary))
        gate.chmod(0o755)
        login_marker = root / "login-ready"
        (root / ".zprofile").write_text('printf ready > "$HOME/login-ready"\n')
        environment = dict(
            os.environ, HOME=str(root),
            HERMES_TEST_SHELL="${pkgs.zsh}/bin/zsh", SHELL="/not-the-account-shell",
        )
        argv = ["two words", "' literal $HOME `false`", ""]
        child = subprocess.Popen(
            [str(gate), sys.argv[2], sys.executable, "-c",
             "import json,os,sys; print(json.dumps({'argv':sys.argv[1:],'pid':os.getpid()}))", *argv],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(0.2)
        assert child.poll() is None and not login_marker.exists(), "login started before secret"
        secret.write_text("SYNTHETIC=ready\n")
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == 0, stderr
        assert json.loads(stdout) == {"argv": argv, "pid": child.pid}, stdout
        assert login_marker.read_text() == "ready"
    PY
    python3 - "$setupPath" "$environmentPath" <<'PY'
    import os
    from pathlib import Path
    import shlex
    import stat
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory(prefix="hermes-activation-", dir=os.environ["TMPDIR"]) as temporary:
        root = Path(temporary)
        home = root / "home with spaces"
        state = home / "custom hermes"
        workspace = home / "working directory"
        secret = home / "secret env"
        setup, environment = [
            Path(path).read_text().replace("${smokeRoot}", temporary)
            for path in sys.argv[1:]
        ]
        prelude = "source " + shlex.quote("${home-manager}/lib/bash/home-manager.sh") + "\n"

        def activate(script, dry=False):
            env = os.environ.copy()
            env.pop("DRY_RUN", None)
            env["DRY_RUN_CMD"] = ""
            if dry:
                env["DRY_RUN"] = "1"
                env["DRY_RUN_CMD"] = "echo"
            subprocess.run(
                ["bash", "-euc", prelude + script],
                env=env, check=True, capture_output=True, text=True,
            )

        activate(setup + environment, dry=True)
        assert not home.exists(), "first dry run created Hermes state"

        activate(setup)
        activate(environment)
        link = state / ".env"
        assert link.is_symlink() and os.readlink(link) == str(secret)
        assert not link.exists(), "first activation must allow a not-yet-materialized sops target"
        assert (state / "config.yaml").read_text() == '{"model": "smoke"}'
        assert stat.S_IMODE((state / "config.yaml").stat().st_mode) == 0o600
        assert (state / ".managed").read_text() == "home-manager"
        assert (state / "SOUL.md").read_text() == "home document\n"
        assert (workspace / "AGENTS.md").read_text() == "workspace document\n"

        secret.write_text("SYNTHETIC_CREDENTIAL=first\n")
        secret.chmod(0o600)
        assert link.read_text() == secret.read_text()
        (state / "auth.json").write_text('{"runtime": true}')
        activate(setup + environment)
        assert (state / "auth.json").read_text() == '{"runtime": true}'
        secret.write_text("SYNTHETIC_CREDENTIAL=rotated\n")
        assert link.read_text() == secret.read_text(), "stable link did not follow secret refresh"
        before = {p: p.lstat().st_mtime_ns for p in home.rglob("*")}
        activate(setup + environment, dry=True)
        assert before == {p: p.lstat().st_mtime_ns for p in home.rglob("*")}
    PY
    touch "$out"
  ''
