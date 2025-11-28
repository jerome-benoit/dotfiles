{ pkgs, lib, ... }:

let
  systemDirenv = pkgs.runCommand "direnv-system" { meta.mainProgram = "direnv"; } "mkdir -p $out";
in
{
  programs.direnv = {
    enable = true;
    package = if pkgs.stdenv.isDarwin then pkgs.direnv else systemDirenv;
    nix-direnv.enable = true;
    enableZshIntegration = false;
  };
}
