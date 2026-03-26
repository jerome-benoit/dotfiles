{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.modules.core.home-manager;
in
{
  options.modules.core.home-manager = {
    enable = lib.mkEnableOption "home-manager configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.home-manager.enable = true;

    nix.package = lib.mkDefault pkgs.nix;

    nix.settings = {
      experimental-features = [
        "nix-command"
        "flakes"
      ];
      warn-dirty = false;
    };

    nix.gc = {
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 30d";
    };
  };
}
