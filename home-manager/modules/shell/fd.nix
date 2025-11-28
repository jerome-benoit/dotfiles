{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.shell.fd;
  systemFd = pkgs.runCommand "fd-system" { meta.mainProgram = "fd"; } "mkdir -p $out";
in
{
  options.modules.shell.fd = {
    enable = lib.mkEnableOption "fd configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.fd = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.fd else systemFd;
    };
  };
}
