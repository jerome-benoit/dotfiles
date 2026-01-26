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
        }:
        pkgs.runCommand "${name}-system" { meta.mainProgram = mainProgram; } "mkdir -p $out";
      description = ''
        Creates a placeholder package that delegates to system-installed binary.
        Used when the program is managed by the system package manager (e.g., dnf, apt)
        rather than Nix, but Home Manager still needs a package reference for configuration.

        Usage:
          mkSystemPackage "toolname" { }                    # mainProgram = "toolname"
          mkSystemPackage "ripgrep" { mainProgram = "rg"; } # mainProgram = "rg"
      '';
      readOnly = true;
    };
  };
}
