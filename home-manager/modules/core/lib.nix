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
