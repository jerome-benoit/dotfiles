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
  };
}
