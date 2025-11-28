{ pkgs, lib, ... }:

let
  systemEza = pkgs.runCommand "eza-system" { meta.mainProgram = "eza"; } "mkdir -p $out";
in
{
  programs.eza = {
    enable = true;
    package = if pkgs.stdenv.isDarwin then pkgs.eza else systemEza;
    enableZshIntegration = false;
    git = true;
    icons = "auto";
    extraOptions = [
      "--group-directories-first"
      "--header"
    ];
  };
}
