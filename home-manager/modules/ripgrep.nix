{ pkgs, lib, ... }:

let
  systemRipgrep = pkgs.runCommand "ripgrep-system" { meta.mainProgram = "rg"; } "mkdir -p $out";
in
{
  programs.ripgrep = {
    enable = true;
    package = if pkgs.stdenv.isDarwin then pkgs.ripgrep else systemRipgrep;
  };
}
