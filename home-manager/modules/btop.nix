{ pkgs, lib, ... }:

let
  systemBtop = pkgs.runCommand "btop-system" { meta.mainProgram = "btop"; } "mkdir -p $out";
in
{
  programs.btop = {
    enable = true;
    package = if pkgs.stdenv.isDarwin then pkgs.btop else systemBtop;
  };
}
