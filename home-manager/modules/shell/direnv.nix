{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.direnv;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.shell.direnv = {
    enable = lib.mkEnableOption "direnv configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.direnv = {
      enable = true;
      # See https://github.com/NixOS/nixpkgs/pull/502769
      package =
        if pkgs.stdenv.isDarwin then
          pkgs.direnv.overrideAttrs (old: {
            postPatch = (old.postPatch or "") + ''
              substituteInPlace GNUmakefile --replace-fail " -linkmode=external" ""
            '';
          })
        else
          mkSystemPackage "direnv" { };
      nix-direnv.enable = true;
      enableZshIntegration = false;
    };
  };
}
