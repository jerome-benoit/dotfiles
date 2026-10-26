{
  pkgs,
  home-manager,
  inputs,
}:
let
  lib = pkgs.lib;
  fixtureHome = "/home/development-check";
  configure =
    settings:
    home-manager.lib.homeManagerConfiguration {
      inherit pkgs;
      extraSpecialArgs = { inherit inputs; };
      modules = [
        ../home-manager/modules/core/lib.nix
        ../home-manager/modules/themes/default.nix
        ../home-manager/modules/development/aoe.nix
        ../home-manager/modules/development/herdr.nix
        ../home-manager/modules/development/opencode.nix
        ../home-manager/modules/development/caveman.nix
        {
          home = {
            username = "development-check";
            homeDirectory = fixtureHome;
            stateVersion = "26.05";
          };
        }
        settings
      ];
    };
  seeded =
    (configure {
      modules.development = {
        aoe = {
          enable = true;
          package = pkgs.hello;
          theme = "dracula";
          defaultTool = "codex";
        };
        herdr = {
          enable = true;
          package = pkgs.hello;
          theme = "nord";
        };
        caveman = {
          enable = true;
          package = pkgs.hello;
        };
      };
    }).config;
  desktop =
    settings:
    (configure {
      modules.development.opencode = {
        enable = true;
        enableDesktop = true;
      }
      // settings;
    }).config;
  overridden = desktop { desktopPackage = pkgs.hello; };
  optedOut = desktop { desktopPackage = null; };
  disabled = desktop { enableDesktop = false; };
  scripts = pkgs.writeText "development-activation-fixtures.json" (
    builtins.toJSON {
      inherit fixtureHome;
      runHelper = "${home-manager}/lib/bash/home-manager.sh";
      caveman = {
        script = seeded.home.activation.cavemanBlocksProfile.data;
        profileDirectory = seeded.home.profileDirectory;
      };
      aoe = {
        script = seeded.home.activation.aoeConfig.data;
        directory =
          if pkgs.stdenv.hostPlatform.isDarwin then ".agent-of-empires" else ".config/agent-of-empires";
        expected = {
          theme.name = "dracula";
          session.default_tool = "codex";
        };
      };
      herdr = {
        script = seeded.home.activation.herdrConfig.data;
        directory = ".config/herdr";
        expected = {
          onboarding = false;
          theme.name = "nord";
        };
      };
    }
  );
in
assert overridden.modules.development.opencode.desktopPackage == pkgs.hello;
assert builtins.elem pkgs.hello overridden.home.packages;
assert optedOut.modules.development.opencode.desktopPackage == null;
assert map toString optedOut.home.packages == map toString disabled.home.packages;
pkgs.runCommand "check-development-integrations"
  {
    nativeBuildInputs = [ pkgs.python3 ];
  }
  ''
    python3 - ${scripts} <<'PY'
    import json
    import os
    from pathlib import Path
    import shlex
    import stat
    import subprocess
    import sys
    import tempfile
    import tomllib

    metadata = json.loads(Path(sys.argv[1]).read_text())
    with tempfile.TemporaryDirectory(prefix="development-check-") as temporary:
        root = Path(temporary)
        for name in ("aoe", "herdr"):
            fixture = metadata[name]
            for initial in ("absent", "directory", "user-file", "empty-file"):
                home = root / name / initial / "home with spaces"
                home.mkdir(parents=True)
                directory = home / fixture["directory"]
                target = directory / "config.toml"
                if initial != "absent":
                    directory.mkdir(parents=True)
                user_bytes = b"# user-owned configuration\n"
                if initial in ("user-file", "empty-file"):
                    target.write_bytes(user_bytes if initial == "user-file" else b"")
                    target.chmod(0o600)
                before = target.read_bytes() if target.exists() else None
                script = (
                    "umask 027\nsource " + shlex.quote(metadata["runHelper"]) + "\n"
                    + fixture["script"].replace(metadata["fixtureHome"], str(home))
                )
                environment = {
                    "HOME": str(home),
                    "PATH": "${lib.makeBinPath [ pkgs.coreutils ]}",
                    "NO_COLOR": "1",
                }
                def activate(dry=False):
                    result = subprocess.run(
                        ["${lib.getExe pkgs.bash}", "--noprofile", "--norc", "-euc", script],
                        env={**environment, **({"DRY_RUN": "1"} if dry else {})},
                        capture_output=True, text=True, timeout=10,
                    )
                    assert result.returncode == 0, (name, initial, dry, result.stderr)

                activate(dry=True)
                assert directory.exists() == (initial != "absent"), (name, initial)
                assert target.exists() == (before is not None), (name, initial)
                if before is not None:
                    assert target.read_bytes() == before
                    assert stat.S_IMODE(target.stat().st_mode) == 0o600
                activate()
                if before is None:
                    assert tomllib.loads(target.read_text()) == fixture["expected"]
                    assert stat.S_IMODE(target.stat().st_mode) == 0o640
                    target.write_bytes(user_bytes)
                    target.chmod(0o600)
                    before = user_bytes
                activate(dry=True)
                activate()
                assert target.read_bytes() == before, (name, initial)
                assert stat.S_IMODE(target.stat().st_mode) == 0o600
                print(f"{name}: {initial}: dry-run, seed and user edits preserved")

        # Both trees are owned and contain recognized legacy links. CDPATH must
        # not redirect the activation's checked relative walk into another tree.
        # Keep replacement paths shell-safe: the evaluated fixture paths need
        # no quoting, and this regression isolates CDPATH rather than quoting.
        home = root / "caveman" / "home"
        redirect = root / "caveman" / "redirect"
        home.mkdir(parents=True)
        redirect.mkdir()
        relative = Path(".local/share/caveman-blocks/bin/caveman-blocks")
        legacy = "${builtins.storeDir}/00000000000000000000000000000000-caveman-blocks-0.1.0/bin/caveman-blocks"
        hooks = [home / relative, redirect / relative]
        for hook in hooks:
            hook.parent.mkdir(parents=True)
            hook.symlink_to(legacy)
        original_inodes = [(hook.lstat().st_dev, hook.lstat().st_ino) for hook in hooks]
        profile = root / "caveman" / "selected-profile"
        binary = profile / "bin/caveman-blocks"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!${lib.getExe pkgs.bash}\nexit 0\n")
        binary.chmod(0o755)
        fixture = metadata["caveman"]
        script = (
            "source " + shlex.quote(metadata["runHelper"]) + "\n"
            + fixture["script"].replace(fixture["profileDirectory"], str(profile))
                .replace(metadata["fixtureHome"], str(home))
            + '\n[[ "$CDPATH" == "$EXPECTED_CDPATH" ]]\n'
        )
        environment = {
            "HOME": str(home),
            "PATH": "${lib.makeBinPath [ pkgs.coreutils ]}",
            "NO_COLOR": "1",
            "CDPATH": str(redirect) + ":.",
            "EXPECTED_CDPATH": str(redirect) + ":.",
        }
        def migrate(dry=False):
            result = subprocess.run(
                ["${lib.getExe pkgs.bash}", "--noprofile", "--norc", "-euc", script],
                env={**environment, **({"DRY_RUN": "1"} if dry else {})},
                cwd=root, capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0, (dry, result.stdout, result.stderr)

        migrate(dry=True)
        assert [os.readlink(hook) for hook in hooks] == [legacy, legacy]
        assert [(hook.lstat().st_dev, hook.lstat().st_ino) for hook in hooks] == original_inodes
        migrate()
        assert os.readlink(hooks[0]) == str(binary)
        assert os.readlink(hooks[1]) == legacy
        assert (hooks[1].lstat().st_dev, hooks[1].lstat().st_ino) == original_inodes[1]
        migrate(dry=True)
        migrate()
        assert os.readlink(hooks[0]) == str(binary)
        assert os.readlink(hooks[1]) == legacy
        assert (hooks[1].lstat().st_dev, hooks[1].lstat().st_ino) == original_inodes[1]
        print("caveman: CDPATH isolated; dry-run, migration and repeat preserve outside hook")
    PY
    touch "$out"
  ''
