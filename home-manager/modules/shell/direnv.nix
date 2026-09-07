{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.direnv;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
in
{
  options.modules.shell.direnv = {
    enable = lib.mkEnableOption "direnv configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.direnv = {
      enable = true;
      # Nix can invalidate ad-hoc Mach-O signatures during Darwin check builds.
      package = (mkPlatformPackage "direnv" { }).overrideAttrs (previousAttrs: {
        doCheck = (previousAttrs.doCheck or true) && !isDarwin;
      });
      nix-direnv.enable = true;
      enableZshIntegration = false;
    };
  };
}
