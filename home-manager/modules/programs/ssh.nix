{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.ssh;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.programs.ssh = {
    enable = lib.mkEnableOption "ssh configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.ssh = lib.mkMerge [
      {
        enable = true;
        enableDefaultConfig = false;
        package = mkSystemPackage "ssh" { };
        matchBlocks = {
          "*" = {
            addKeysToAgent = "yes";
            forwardAgent = true;
            forwardX11 = true;
          };
        };
      }
      (lib.mkIf pkgs.stdenv.isDarwin {
        matchBlocks = {
          "*" = {
            extraOptions = {
              UseKeychain = "yes";
            };
          };
        };
      })
    ];

    specialisation.work.configuration = {
      programs.ssh.matchBlocks."*.local" = {
        user = "fraggle";
      };
    };
  };
}
