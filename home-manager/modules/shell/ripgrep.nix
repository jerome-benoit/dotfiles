{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.ripgrep;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.shell.ripgrep = {
    enable = lib.mkEnableOption "ripgrep configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.ripgrep = {
      enable = true;
      package =
        if pkgs.stdenv.isDarwin then pkgs.ripgrep else mkSystemPackage "ripgrep" { mainProgram = "rg"; };
    };
  };
}
