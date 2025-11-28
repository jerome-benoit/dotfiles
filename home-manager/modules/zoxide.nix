{ pkgs, lib, ... }:

let
  systemZoxide = pkgs.runCommand "zoxide-system" { meta.mainProgram = "zoxide"; } "mkdir -p $out";
in
{
  programs.zoxide = {
    enable = true;
    package = if pkgs.stdenv.isDarwin then pkgs.zoxide else systemZoxide;
    enableZshIntegration = false;
  };
}
