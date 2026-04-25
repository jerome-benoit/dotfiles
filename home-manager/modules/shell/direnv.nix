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
      # https://github.com/NixOS/nix/pull/15638
      package = (mkPlatformPackage "direnv" { }).overrideAttrs (old: {
        doCheck = (old.doCheck or true) && !isDarwin;
      });
      nix-direnv.enable = true;
      enableZshIntegration = false;
    };
  };
}
