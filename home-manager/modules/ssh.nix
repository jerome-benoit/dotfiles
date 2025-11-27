{ pkgs, lib, ... }:
let
  systemSsh = pkgs.runCommand "ssh-system" { } "mkdir -p $out";
in
{
  programs.ssh = lib.mkMerge [
    {
      enable = true;
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
}
