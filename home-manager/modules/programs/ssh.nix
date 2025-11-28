{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.modules.programs.ssh;
  systemSsh = pkgs.runCommand "ssh-system" { } "mkdir -p $out";
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
        package = systemSsh;
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
          "*.local" = {
            user = "fraggle";
          };
        };
      })
    ];
  };
}
