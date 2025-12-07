{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.tmux;
  theme = config.modules.themes.tokyoNightStorm;
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
      keyMode = "vi";
      mouse = true;
      baseIndex = 1;
      escapeTime = 10;
      historyLimit = config.modules.core.constants.historySize;
      clock24 = true;
      disableConfirmationPrompt = true;

      extraConfig = ''
        # ============================================================================
        # OPTIONS
        # ============================================================================

        # Server Options
        set -s extended-keys on

        # Session Options
        set -g renumber-windows on

        # Window Options
        set -g set-titles on
        set -g set-clipboard on

        # Terminal Features
        set -as terminal-features ",*:RGB"

        # Terminal Overrides
        set -as terminal-overrides ',*:Smulx=\E[4::%p1%dm'
        set -as terminal-overrides ',*:Setulc=\E[58::2::%p1%{65536}%/%d::%p1%{256}%/%{255}%&%d::%p1%{255}%&%d%;m'

        # ============================================================================
        # KEY BINDINGS
        # ============================================================================
        # Pane Splits
        bind-key '"' split-window -v -c "#{pane_current_path}"
        bind-key % split-window -h -c "#{pane_current_path}"

        # Copy Mode - Selection
        bind-key -T copy-mode-vi v send-keys -X begin-selection
        bind-key -T copy-mode-vi C-v send-keys -X rectangle-toggle
        bind-key -T copy-mode-vi y send-keys -X copy-selection-and-cancel
        bind-key -T copy-mode-vi H send-keys -X start-of-line
        bind-key -T copy-mode-vi L send-keys -X end-of-line

        # Copy Mode - Navigation & Search
        bind-key -T copy-mode-vi C-u send-keys -X halfpage-up
        bind-key -T copy-mode-vi C-d send-keys -X halfpage-down
        bind-key -T copy-mode-vi g send-keys -X history-top
        bind-key -T copy-mode-vi G send-keys -X history-bottom
        bind-key -T copy-mode-vi / send-keys -X search-forward
        bind-key -T copy-mode-vi ? send-keys -X search-backward
        bind-key -T copy-mode-vi n send-keys -X search-again
        bind-key -T copy-mode-vi N send-keys -X search-reverse

        # Window Navigation
        bind -r C-h previous-window
        bind -r C-l next-window
      '';

      plugins = with pkgs.tmuxPlugins; [
        sensible
        yank
        pain-control
        vim-tmux-navigator
        {
          plugin = tokyo-night-tmux;
          extraConfig = ''
            set -g @tokyo-night-tmux_theme storm
            set -g @tokyo-night-tmux_window_id_style digital
            set -g @tokyo-night-tmux_pane_id_style hsquare
            set -g @tokyo-night-tmux_zoom_id_style dsquare
            set -g @tokyo-night-tmux_show_datetime 1
            set -g @tokyo-night-tmux_date_format DMY
            set -g @tokyo-night-tmux_time_format 24H
            set -g @tokyo-night-tmux_show_path 1
            set -g @tokyo-night-tmux_path_format relative
            set -g @tokyo-night-tmux_show_battery_widget 1
            set -g @tokyo-night-tmux_show_netspeed 1
          '';
        }
        {
          plugin = resurrect;
          extraConfig = ''
            set -g @resurrect-strategy-nvim 'session'
            set -g @resurrect-capture-pane-contents 'on'
            set -g @resurrect-save-shell-history 'on'
            set -g @resurrect-processes 'ssh btop sqlite3 "~gh" "~opencode"'
          '';
        }
        {
          plugin = continuum;
          extraConfig = ''
            set -g @continuum-restore 'on'
            set -g @continuum-save-interval '15'
          '';
        }
      ];
    };
  };
}
