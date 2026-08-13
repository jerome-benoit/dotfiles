{
  config,
  lib,
  pkgs,
  ...
}:

{
  options.modules.core.lib = {
    mkSystemPackage = lib.mkOption {
      type = lib.types.functionTo (lib.types.functionTo lib.types.package);
      default =
        name:
        {
          mainProgram ? name,
          version ? "0.0.0",
        }:
        pkgs.runCommand "${name}-system" {
          inherit version;
          meta.mainProgram = mainProgram;
        } "mkdir -p $out";
      description = ''
        Creates a placeholder package that delegates to system-installed binary.
        Used when the program is managed by the system package manager (e.g., dnf, apt)
        rather than Nix, but Home Manager still needs a package reference for configuration.

        Usage:
          mkSystemPackage "toolname" { }                              # mainProgram = "toolname", version = "0.0.0"
          mkSystemPackage "ripgrep" { mainProgram = "rg"; }           # mainProgram = "rg"
          mkSystemPackage "zellij" { version = "0.43.0"; }            # with explicit version
      '';
      readOnly = true;
    };

    mkPlatformPackage = lib.mkOption {
      type = lib.types.functionTo (lib.types.functionTo lib.types.package);
      default =
        name:
        {
          mainProgram ? name,
          version ? "0.0.0",
          nixOn ? "darwin",
        }:
        let
          useNix =
            if nixOn == "darwin" then
              pkgs.stdenv.hostPlatform.isDarwin
            else if nixOn == "linux" then
              pkgs.stdenv.hostPlatform.isLinux
            else if nixOn == "all" then
              true
            else
              builtins.throw "mkPlatformPackage: invalid nixOn value '${nixOn}', expected: darwin, linux, all";
        in
        if useNix then
          pkgs.${name}
        else
          config.modules.core.lib.mkSystemPackage name { inherit mainProgram version; };
      description = ''
        Selects the real Nix package or a system placeholder based on platform.

        Usage:
          mkPlatformPackage "eza" { }                                 # pkgs.eza on Darwin, system stub on Linux (default)
          mkPlatformPackage "ripgrep" { mainProgram = "rg"; }         # pkgs.ripgrep on Darwin, system stub on Linux
          mkPlatformPackage "ghostty" { nixOn = "linux"; }            # pkgs.ghostty on Linux, system stub on Darwin
          mkPlatformPackage "bat" { nixOn = "all"; }                  # pkgs.bat everywhere
      '';
      readOnly = true;
    };

    mkUnstableVersionWithBase = lib.mkOption {
      type = lib.types.functionTo (lib.types.functionTo lib.types.str);
      default =
        base: input:
        let
          date = input.lastModifiedDate or "19700101000000";
          fmtDate = "${builtins.substring 0 4 date}-${builtins.substring 4 2 date}-${builtins.substring 6 2 date}";
        in
        "${base}-unstable-${fmtDate}+${input.shortRev}";
      description = ''
        Like mkUnstableVersion but with an explicit base version instead of "0",
        for inputs that expose a real upstream version.

        Format: <base>-unstable-YYYY-MM-DD+shortRev

        Usage:
          version = mkUnstableVersionWithBase "1.3.0" inputs.my-package;  # "1.3.0-unstable-2026-04-20+abc1234"
      '';
      readOnly = true;
    };

    mkUnstableVersion = lib.mkOption {
      type = lib.types.functionTo lib.types.str;
      default = input: config.modules.core.lib.mkUnstableVersionWithBase "0" input;
      description = ''
        Generates a nixpkgs-convention version string for packages built from
        a flake input tracking a development branch.

        Format: 0-unstable-YYYY-MM-DD+shortRev

        Usage:
          version = mkUnstableVersion inputs.my-package;  # "0-unstable-2026-04-20+abc1234"
      '';
      readOnly = true;
    };

    deltaConfigToCli = lib.mkOption {
      type = lib.types.functionTo lib.types.str;
      default =
        cfg:
        let
          boolFlag = name: value: lib.optional value "--${name}";
          strFlag = name: value: [ "--${name}='${value}'" ];
          intFlag = name: value: [ "--${name}=${toString value}" ];
          enumFlag = name: value: [ "--${name}=${value}" ];
        in
        lib.strings.concatStringsSep " " (
          lib.lists.flatten [
            "--paging=never"
            (boolFlag "navigate" cfg.navigate)
            (boolFlag "line-numbers" cfg.line-numbers)
            (boolFlag "side-by-side" cfg.side-by-side)
            (boolFlag "hyperlinks" cfg.hyperlinks)
            (strFlag "hyperlinks-file-link-format" cfg.hyperlinks-file-link-format)
            (boolFlag "dark" cfg.dark)
            (strFlag "syntax-theme" cfg.syntax-theme)
            (enumFlag "true-color" cfg.true-color)
            (intFlag "max-line-length" cfg.max-line-length)
            (strFlag "features" cfg.features)
            (strFlag "whitespace-error-style" cfg.whitespace-error-style)
            (strFlag "file-style" cfg.file-style)
            (strFlag "file-decoration-style" cfg.file-decoration-style)
            (strFlag "hunk-header-style" cfg.hunk-header-style)
            (strFlag "hunk-header-decoration-style" cfg.hunk-header-decoration-style)
          ]
        );
      description = ''
        Converts `modules.core.constants.deltaConfig` to a delta CLI flags string.

        Keep in sync with the deltaConfig submodule: every field added there
        should be reflected here, or the flag silently disappears from lazygit's pager.

        Usage:
          deltaFlags = lib.deltaConfigToCli config.modules.core.constants.deltaConfig;  # "--paging=never --navigate ..."
      '';
      readOnly = true;
    };

    mkOptionalPackageOption = lib.mkOption {
      type = lib.types.functionTo lib.types.attrs;
      default =
        {
          default,
          defaultText,
          description,
          example ? null,
        }:
        lib.mkOption {
          type = lib.types.nullOr lib.types.package;
          inherit default defaultText description;
        }
        // lib.optionalAttrs (example != null) { inherit example; };
      description = ''
        Creates an optional package option: null when the package is unavailable on the host system.
        Pair with mkOptionalPackages to install it only when non-null and warn otherwise.

        Usage:
          package = mkOptionalPackageOption {
            default = myPackage;   # null on unsupported systems
            defaultText = lib.literalExpression "inputs.foo.packages.''${system}.default";
            description = "Foo package";
            example = lib.literalExpression "inputs.foo.packages.''${system}.default"; # optional
          };
      '';
      readOnly = true;
    };

    mkOptionalPackages = lib.mkOption {
      type = lib.types.functionTo (lib.types.attrsOf lib.types.anything);
      default =
        entries:
        let
          entry =
            {
              package,
              enabled ? true,
              warning ? null,
              ...
            }:
            {
              inherit package enabled warning;
            };
        in
        {
          packages = lib.concatMap (e: lib.optional (e.enabled && e.package != null) e.package) (
            map entry entries
          );
          warnings = lib.concatMap (
            e: lib.optional (e.enabled && e.package == null && e.warning != null) e.warning
          ) (map entry entries);
        };
      description = ''
        Turns optional package entries into the { packages, warnings } lists feeding home.packages and warnings.
        Each entry is { package, enabled ? true, warning ? null } (warning only emitted for null packages).

        Usage:
          optionalPackages = mkOptionalPackages [
            { package = cfg.package; warning = "foo: package not available for system ''${system}"; }
            { package = cfg.desktopPackage; enabled = cfg.enableDesktop; warning = "foo: desktop not available"; }
          ];
          config = lib.mkIf cfg.enable {
            home.packages = optionalPackages.packages;
            warnings = optionalPackages.warnings;
          };
      '';
      readOnly = true;
    };
  };
}
