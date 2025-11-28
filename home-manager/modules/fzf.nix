{ pkgs, lib, ... }:

let
  systemFzf = pkgs.runCommand "fzf-system" {
    version = "0.60.0";
    meta.mainProgram = "fzf";
  } "mkdir -p $out";
in
{
  programs.fzf = {
    enable = true;
    package = if pkgs.stdenv.isDarwin then pkgs.fzf else systemFzf;
    enableZshIntegration = false;
    defaultCommand = "fd --type f";
    fileWidgetCommand = "fd --type f";
  };
}
