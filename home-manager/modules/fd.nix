{ pkgs, lib, ... }:

let
  systemFd = pkgs.runCommand "fd-system" { meta.mainProgram = "fd"; } "mkdir -p $out";
in
{
  programs.fd = {
    enable = true;
    package = if pkgs.stdenv.isDarwin then pkgs.fd else systemFd;
  };
}
