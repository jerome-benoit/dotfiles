{ pkgs, ... }:
let
  systemSsh = pkgs.runCommand "ssh-system" { } "mkdir -p $out";
in
{
  programs.ssh = {
    enable = true;
    package = systemSsh;
    matchBlocks = {
      "*" = {
        addKeysToAgent = "yes";
        forwardAgent = true;
        forwardX11 = true;
      };
    };
  };
}
