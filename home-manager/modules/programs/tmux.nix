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
      historyLimit = config.modules.core.constants.historySize;
      terminal = "screen-256color";
      keyMode = "vi";

      extraConfig = ''
        set -g set-clipboard on

        ${
          if pkgs.stdenv.isDarwin then
            ''
              bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy"
              bind-key -T copy-mode-vi Enter send-keys -X copy-pipe-and-cancel "pbcopy"
            ''
          else if pkgs.stdenv.isLinux then
            ''
              if-shell '[ -n "$WAYLAND_DISPLAY" ]' {
                bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "wl-copy"
                bind-key -T copy-mode-vi Enter send-keys -X copy-pipe-and-cancel "wl-copy"
              }

              if-shell '[ -n "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]' {
                bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "xclip -selection clipboard"
                bind-key -T copy-mode-vi Enter send-keys -X copy-pipe-and-cancel "xclip -selection clipboard"
              }
            ''
          else
            ""
        }
      '';

      plugins = with pkgs.tmuxPlugins; [
        sensible
      ];
    };
  };
}
