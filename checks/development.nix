{
  pkgs,
  home-manager,
  inputs,
}:
let
  lib = pkgs.lib;
  fixtureHome = "/home/development-check";
  configureWith =
    selectedInputs: settings:
    home-manager.lib.homeManagerConfiguration {
      inherit pkgs;
      extraSpecialArgs = {
        inputs = selectedInputs;
      };
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
  configure = configureWith inputs;
  opencodeStages =
    map
      (
        name:
        let
          cli = pkgs.writeShellScriptBin "opencode" ''
            # ${name}
            exit 0
          '';
          selectedInputs = inputs // {
            opencode.packages.${pkgs.stdenv.hostPlatform.system} = {
              default = cli;
              opencode-desktop = lib.makeOverridable (_: pkgs.hello) { };
            };
          };
          config =
            (configureWith selectedInputs {
              modules.development.opencode = {
                enable = true;
                enableDesktop = true;
              };
            }).config;
          package = config.modules.development.opencode;
          source = pkgs.runCommand "opencode-stages-${name}" { } ''
            target=packages/desktop/src/main/service/cli-version.ts
            mkdir -p "$(dirname "$target")" "$out"
            cp ${inputs.opencode}/packages/desktop/src/main/service/cli-version.ts "$target"
            chmod u+w "$target"
            ${package.desktopPackage.postPatch}
            cp "$target" "$out/cli-version.ts"
          '';
        in
        "${source}/cli-version.ts"
      )
      [
        "first"
        "second"
      ];
  seeded =
    (configure {
      modules.development = {
        herdr = {
          enable = true;
          package = pkgs.hello;
          theme = "nord";
        };
      };
    }).config;
  aoeSeeded =
    (configure {
      home.homeDirectory = lib.mkForce "${fixtureHome}/aoe literal $missing ' $(touch aoe-shell-expanded)";
      # This option does not export XDG_CONFIG_HOME when XDG management is disabled.
      xdg.enable = false;
      xdg.configHome = "${fixtureHome}/not-exported-config-home";
      modules.development.aoe = {
        enable = true;
        package = pkgs.hello;
        theme = "dracula";
        defaultTool = "codex";
      };
    }).config;
  aoeManaged =
    (configure {
      home.homeDirectory = lib.mkForce "${fixtureHome}/managed home";
      xdg = {
        enable = true;
        configHome = "${fixtureHome}/managed XDG config";
      };
      modules.development.aoe = {
        enable = true;
        package = pkgs.hello;
        theme = "dracula";
        defaultTool = "codex";
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
  opencodePackages = (desktop { }).modules.development.opencode;
  overridden = desktop { desktopPackage = pkgs.hello; };
  optedOut = desktop { desktopPackage = null; };
  disabled = desktop { enableDesktop = false; };
  scripts = pkgs.writeText "development-activation-fixtures.json" (
    builtins.toJSON {
      inherit fixtureHome;
      inherit opencodeStages;
      runHelper = "${home-manager}/lib/bash/home-manager.sh";
      caveman =
        map
          (
            suffix:
            let
              config =
                (configure {
                  home.homeDirectory = lib.mkForce "${fixtureHome}/caveman/${suffix}";
                  modules.development.caveman = {
                    enable = true;
                    package = pkgs.hello;
                  };
                }).config;
            in
            {
              homeDirectory = config.home.homeDirectory;
              profileDirectory = config.home.profileDirectory;
              script = config.home.activation.cavemanBlocksProfile.data;
            }
          )
          [
            "plain"
            "$missing"
            "quote ' path"
            "$(touch caveman-shell-expanded)"
          ];
      aoe = {
        script = aoeSeeded.home.activation.aoeConfig.data;
        homeDirectory = aoeSeeded.home.homeDirectory;
        isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
      };
      aoeManaged = {
        script = aoeManaged.home.activation.aoeConfig.data;
        homeDirectory = aoeManaged.home.homeDirectory;
        configHome = aoeManaged.xdg.configHome;
      };
      aoeExports =
        map
          (
            value:
            let
              configured =
                (configure {
                  home.homeDirectory = lib.mkForce "${fixtureHome}/export home";
                  home.sessionVariables.XDG_CONFIG_HOME = value;
                  xdg.enable = false;
                  modules.development.aoe = {
                    enable = true;
                    package = pkgs.hello;
                    defaultTool = "codex";
                  };
                }).config;
            in
            {
              inherit value;
              script = configured.home.activation.aoeConfig.data;
              homeDirectory = configured.home.homeDirectory;
            }
          )
          [
            null
            "$HOME/expanded config"
          ];
      herdr = {
        script = seeded.home.activation.herdrConfig.data;
        directory = ".config/herdr";
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
    nativeBuildInputs = [
      pkgs.nodejs_22
      pkgs.python3
    ];
    passthru.tests.opencode-desktop =
      let
        cli = opencodePackages.opencodePackage;
        package = opencodePackages.desktopPackage;
        resources =
          if pkgs.stdenv.hostPlatform.isDarwin then
            "${package}/Applications/OpenCode.app/Contents/Resources"
          else
            "${package}/opt/opencode-desktop/resources";
      in
      pkgs.runCommand "check-opencode-desktop-bundle" { nativeBuildInputs = [ pkgs.python3 ]; } ''
        export HOME="$TMPDIR/home"
        export XDG_CONFIG_HOME="$HOME/.config"
        export XDG_DATA_HOME="$HOME/.local/share"
        export XDG_STATE_HOME="$HOME/.local/state"
        export XDG_CACHE_HOME="$HOME/.cache"
        mkdir -p "$HOME"
        python3 - ${lib.getExe cli} ${resources}/opencode-cli ${lib.escapeShellArg cli.version} <<'PY'
        from pathlib import Path
        import shutil
        import subprocess
        import sys
        import tempfile

        selected, bundled, expected = sys.argv[1:]
        manifest = Path(bundled).with_name("opencode-cli.version")
        assert manifest.read_text().strip() == expected, manifest.read_text()

        def version(executable):
            return subprocess.check_output([executable, "--version"], text=True, timeout=30).strip()

        selected_version = version(selected)
        assert expected in selected_version, selected_version
        assert version(bundled) == selected_version, "Desktop bundled a different CLI version"
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / "opencode"
            shutil.copy2(bundled, staged)
            assert version(staged) == selected_version, "Desktop's staged CLI cannot run independently"
        print("opencode: bundled CLI, version manifest and copied runtime agree")
        PY
        touch "$out"
      '';
  }
  ''
    node --experimental-strip-types --input-type=module - ${scripts} <<'JS'
    import assert from "node:assert/strict";
    import { readFileSync } from "node:fs";
    import { pathToFileURL } from "node:url";

    const fixtures = JSON.parse(readFileSync(process.argv[2], "utf8"));
    const [first, second] = await Promise.all(
      fixtures.opencodeStages.map((file) => import(pathToFileURL(file))),
    );
    for (const arch of ["x64", "arm64"]) {
      const current = first.stageName("2.0.32", arch);
      const rebuilt = second.stageName("2.0.32", arch);
      const adopted = first.stageName("2.0.31", arch);
      assert.notEqual(current, rebuilt, "a rebuilt CLI must not reuse the previous executable");
      const kept = first.keptStages("2.0.32", "2.0.31", arch);
      assert.ok(kept.includes(current), "cleanup must retain the bundled executable");
      assert.ok(kept.includes(adopted), "cleanup must retain the adopted version in this package namespace");
      assert.ok(!kept.includes(rebuilt), "cleanup must not retain a different package's obsolete stage");
    }
    assert.notEqual(first.stageName("2.0.32", "x64"), first.stageName("2.0.32", "arm64"));
    console.log("opencode: rebuilt CLI isolation, architecture isolation and stage retention passed");
    JS
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
        for name in ("herdr",):
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
                    tomllib.loads(target.read_text())
                    assert stat.S_IMODE(target.stat().st_mode) == 0o640
                    target.write_bytes(user_bytes)
                    target.chmod(0o600)
                    before = user_bytes
                activate(dry=True)
                activate()
                assert target.read_bytes() == before, (name, initial)
                assert stat.S_IMODE(target.stat().st_mode) == 0o600
                print(f"{name}: {initial}: dry-run, seed and user edits preserved")

        fixture = metadata["aoe"]
        # These cases follow AoE's consumer contract in src/session/mod.rs:
        # Linux always uses XDG; Darwin prefers existing XDG, then legacy,
        # then an absolute XDG environment opt-in, then its legacy default.
        for variable in ("unset", "empty", "relative", "absolute"):
            for layout in ("fresh", "xdg", "legacy", "both"):
                for initial in ("absent", "user-file", "empty-file", "dangling-symlink"):
                    case = (variable, layout, initial)
                    case_root = root / "aoe" / variable / layout / initial
                    home = Path(fixture["homeDirectory"].replace(metadata["fixtureHome"], str(case_root)))
                    home.mkdir(parents=True)
                    environment = {
                        "HOME": str(home),
                        "PATH": "${lib.makeBinPath [ pkgs.coreutils ]}",
                        "NO_COLOR": "1",
                    }
                    if variable != "unset":
                        environment["XDG_CONFIG_HOME"] = {
                            "empty": "",
                            "relative": "relative config",
                            "absolute": str(case_root / "XDG literal $missing ' $(touch aoe-shell-expanded)"),
                        }[variable]
                    env_xdg = environment.get("XDG_CONFIG_HOME", "")
                    absolute_env = env_xdg.startswith("/")
                    xdg = (Path(env_xdg) if absolute_env else home / ".config") / "agent-of-empires"
                    legacy = home / ".agent-of-empires"
                    if layout in ("xdg", "both"):
                        xdg.mkdir(parents=True)
                    if layout in ("legacy", "both"):
                        legacy.mkdir(parents=True)
                    if not fixture["isDarwin"] or layout in ("xdg", "both"):
                        directory = xdg
                    elif layout == "legacy" or not absolute_env:
                        directory = legacy
                    else:
                        directory = xdg
                    target = directory / "config.toml"
                    user_bytes = b"# user-owned configuration\n"
                    if initial != "absent":
                        directory.mkdir(parents=True, exist_ok=True)
                        if initial == "dangling-symlink":
                            target.symlink_to("missing-user-config")
                        else:
                            target.write_bytes(user_bytes if initial == "user-file" else b"")
                            target.chmod(0o600)
                    # The nonselected layout may contain a different user's config.
                    other = legacy if directory == xdg else xdg
                    other_target = other / "config.toml"
                    if other.exists():
                        other_target.write_bytes(b"# other layout remains untouched\n")
                        other_target.chmod(0o600)
                    before_paths = set(case_root.rglob("*"))
                    before_files = {
                        file: (file.read_bytes(), stat.S_IMODE(file.stat().st_mode))
                        for file in before_paths if file.is_file()
                    }
                    script = (
                        "umask 027\nsource " + shlex.quote(metadata["runHelper"]) + "\n"
                        + fixture["script"].replace(metadata["fixtureHome"], str(case_root))
                    )
                    def activate_aoe(dry=False):
                        result = subprocess.run(
                            ["${lib.getExe pkgs.bash}", "--noprofile", "--norc", "-euc", script],
                            env={**environment, **({"DRY_RUN": "1"} if dry else {})},
                            cwd=case_root, capture_output=True, text=True, timeout=10,
                        )
                        assert result.returncode == 0, (case, dry, result.stdout, result.stderr)
                        assert not (case_root / "aoe-shell-expanded").exists(), case

                    activate_aoe(dry=True)
                    assert set(case_root.rglob("*")) == before_paths, case
                    activate_aoe()
                    if initial == "absent":
                        seeded_config = tomllib.loads(target.read_text())
                        assert seeded_config["theme"]["name"] == "dracula", case
                        assert seeded_config["session"]["default_tool"] == "codex", case
                        assert stat.S_IMODE(target.stat().st_mode) == 0o640, case
                        target.write_bytes(user_bytes)
                        target.chmod(0o600)
                        before_files[target] = (user_bytes, 0o600)
                    activate_aoe(dry=True)
                    activate_aoe()
                    for file, (content, mode) in before_files.items():
                        assert file.read_bytes() == content, (case, file)
                        assert stat.S_IMODE(file.stat().st_mode) == mode, (case, file)
                    if initial == "dangling-symlink":
                        assert target.is_symlink() and os.readlink(target) == "missing-user-config", case
                        assert not target.exists(), case
                    assert not (case_root / "not-exported-config-home").exists(), case
                    assert other.exists() == (other in before_paths), case
                    assert not (case_root / "relative config").exists(), case
                    print(f"aoe: {case}: consumer path, dry-run and user data preserved")

        # A switch must seed the future managed environment, not an absent or stale export.
        for ambient in ("unset", "old"):
            fixture = metadata["aoeManaged"]
            case_root = root / "aoe-managed" / ambient
            home = Path(fixture["homeDirectory"].replace(metadata["fixtureHome"], str(case_root)))
            home.mkdir(parents=True)
            config_home = Path(fixture["configHome"].replace(metadata["fixtureHome"], str(case_root)))
            old = home / "previous-config"
            environment = {"HOME": str(home), "PATH": "${
              lib.makeBinPath [ pkgs.coreutils ]
            }", "NO_COLOR": "1"}
            if ambient == "old":
                environment["XDG_CONFIG_HOME"] = str(old)
            script = ("source " + shlex.quote(metadata["runHelper"]) + "\n"
                      + fixture["script"].replace(metadata["fixtureHome"], str(case_root)))
            for dry in (True, False):
                subprocess.run(
                    ["${lib.getExe pkgs.bash}", "--noprofile", "--norc", "-euc", script],
                    env={**environment, **({"DRY_RUN": "1"} if dry else {})},
                    cwd=case_root, check=True, capture_output=True, text=True, timeout=10,
                )
                target = config_home / "agent-of-empires/config.toml"
                assert target.exists() != dry, (ambient, dry)
            seeded_config = tomllib.loads(target.read_text())
            assert seeded_config["theme"]["name"] == "dracula", ambient
            assert seeded_config["session"]["default_tool"] == "codex", ambient
            assert not (home / ".config/agent-of-empires").exists(), ambient
            assert not old.exists(), ambient
            print(f"aoe: managed XDG with {ambient} ambient export selects future consumer path")

        # Use the same null filtering and POSIX expansion as the future HM session.
        for fixture in metadata["aoeExports"]:
            case = "null" if fixture["value"] is None else "expanded"
            case_root = root / "aoe-export" / case
            home = Path(fixture["homeDirectory"].replace(metadata["fixtureHome"], str(case_root)))
            home.mkdir(parents=True)
            inherited = home / "ambient config"
            environment = {"HOME": str(home), "XDG_CONFIG_HOME": str(inherited),
                           "PATH": "${lib.makeBinPath [ pkgs.coreutils ]}", "NO_COLOR": "1"}
            script = ("source " + shlex.quote(metadata["runHelper"]) + "\n"
                      + fixture["script"].replace(metadata["fixtureHome"], str(case_root)))
            subprocess.run(
                ["${lib.getExe pkgs.bash}", "--noprofile", "--norc", "-euc", script],
                env=environment, cwd=case_root, check=True, capture_output=True, text=True, timeout=10,
            )
            expected = inherited if case == "null" else home / "expanded config"
            assert tomllib.loads((expected / "agent-of-empires/config.toml").read_text())["session"]["default_tool"] == "codex"
            assert not (home / ".config/agent-of-empires").exists(), case
            if case == "expanded":
                assert not inherited.exists(), case
            print(f"aoe: {case} session export matches Home Manager shell semantics")

        # Relocate only the safe prefix; retain Nix's quoting of literal paths.
        for fixture in metadata["caveman"]:
            home = Path(fixture["homeDirectory"].replace(metadata["fixtureHome"], str(root)))
            profile = Path(fixture["profileDirectory"].replace(metadata["fixtureHome"], str(root)))
            redirect = root / "redirect" / home.name
            home.mkdir(parents=True)
            redirect.mkdir(parents=True)
            relative = Path(".local/share/caveman-blocks/bin/caveman-blocks")
            legacy = "${builtins.storeDir}/00000000000000000000000000000000-caveman-blocks-0.1.0/bin/caveman-blocks"
            hooks = [home / relative, redirect / relative]
            for hook in hooks:
                hook.parent.mkdir(parents=True)
                hook.symlink_to(legacy)
            original_inodes = [(hook.lstat().st_dev, hook.lstat().st_ino) for hook in hooks]
            binary = profile / "bin/caveman-blocks"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!${lib.getExe pkgs.bash}\nexit 0\n")
            binary.chmod(0o755)
            binary_inode = (binary.stat().st_dev, binary.stat().st_ino)
            script = (
                "source " + shlex.quote(metadata["runHelper"]) + "\n"
                + fixture["script"].replace(metadata["fixtureHome"], str(root))
                + '\n[[ "$CDPATH" == "$EXPECTED_CDPATH" ]]\n'
            )
            environment = {
                "HOME": str(home),
                "PATH": "${lib.makeBinPath [ pkgs.coreutils ]}",
                "NO_COLOR": "1",
                "VERBOSE": "1",
                "CDPATH": str(redirect) + ":.",
                "EXPECTED_CDPATH": str(redirect) + ":.",
            }
            def migrate(dry=False):
                pending = os.readlink(hooks[0]) == legacy
                result = subprocess.run(
                    ["${lib.getExe pkgs.bash}", "--noprofile", "--norc", "-euc", script],
                    env={**environment, **({"DRY_RUN": "1"} if dry else {})},
                    cwd=root, capture_output=True, text=True, timeout=10,
                )
                assert result.returncode == 0, (home.name, dry, result.stdout, result.stderr)
                if pending:
                    assert f"caveman: migrating existing Blocks hook to {binary}" in result.stdout
                assert not (hooks[0].parent / "caveman-shell-expanded").exists()
                assert (binary.stat().st_dev, binary.stat().st_ino) == binary_inode

            migrate(dry=True)
            assert [os.readlink(hook) for hook in hooks] == [legacy, legacy]
            assert [(hook.lstat().st_dev, hook.lstat().st_ino) for hook in hooks] == original_inodes
            migrate()
            assert os.readlink(hooks[0]) == str(binary)
            assert os.readlink(hooks[1]) == legacy
            assert (hooks[1].lstat().st_dev, hooks[1].lstat().st_ino) == original_inodes[1]
            migrated_inode = (hooks[0].lstat().st_dev, hooks[0].lstat().st_ino)
            migrate(dry=True)
            migrate()
            assert os.readlink(hooks[0]) == str(binary)
            assert (hooks[0].lstat().st_dev, hooks[0].lstat().st_ino) == migrated_inode
            assert os.readlink(hooks[1]) == legacy
            assert (hooks[1].lstat().st_dev, hooks[1].lstat().st_ino) == original_inodes[1]
            print(f"caveman: {home.name}: literal profile, CDPATH isolated; dry-run and repeat preserve outside hook")
    PY
    touch "$out"
  ''
