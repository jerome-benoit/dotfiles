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
        name: args:
        if pkgs.stdenv.hostPlatform.isDarwin then
          pkgs.${name} # args only apply to system stub on Linux
        else
          config.modules.core.lib.mkSystemPackage name args;
      description = ''
        Selects the real Nix package on Darwin or a system placeholder on Linux.

        Usage:
          mkPlatformPackage "eza" { }                                 # pkgs.eza on Darwin, system stub on Linux
          mkPlatformPackage "ripgrep" { mainProgram = "rg"; }         # pkgs.ripgrep on Darwin, system stub on Linux
      '';
      readOnly = true;
    };

    mkUnstableVersion = lib.mkOption {
      type = lib.types.functionTo lib.types.str;
      default =
        input:
        let
          date = input.lastModifiedDate or "19700101000000";
          fmtDate = "${builtins.substring 0 4 date}-${builtins.substring 4 2 date}-${builtins.substring 6 2 date}";
        in
        "0-unstable-${fmtDate}+${input.shortRev}";
      description = ''
        Generates a nixpkgs-convention version string for packages built from
        a flake input tracking a development branch.

        Format: 0-unstable-YYYY-MM-DD+shortRev

        Usage:
          version = mkUnstableVersion inputs.my-package;  # "0-unstable-2026-04-20+abc1234"
      '';
      readOnly = true;
    };
  };
}
