{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.tmux;
  systemTmux = pkgs.runCommand "tmux-system" { meta.mainProgram = "tmux"; } "mkdir -p $out";
in
{
  options.modules.programs.tmux = {
    enable = lib.mkEnableOption "tmux configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.tmux = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.tmux else systemTmux;
      mouse = true;
      baseIndex = 1;
      escapeTime = 0;
      historyLimit = 50000;
      terminal = "screen-256color";
      plugins = with pkgs.tmuxPlugins; [
        sensible
      ];
    };
  };
}
