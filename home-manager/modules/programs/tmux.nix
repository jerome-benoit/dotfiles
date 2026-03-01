{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.tmux;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
  theme = config.modules.themes.current;

  tmuxThemePlugins = {
    tokyonight = {
      plugin = pkgs.tmuxPlugins.tokyo-night-tmux;
      extraConfig = ''
        set -g @tokyo-night-tmux_theme ${theme.style}
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
      extraPlugins = [ ];
      postConfig = "";
    };
    catppuccin = {
      plugin = pkgs.tmuxPlugins.catppuccin;
      extraConfig = ''
        set -g @catppuccin_flavor '${theme.style}'
        set -g @catppuccin_window_status_style "rounded"
        set -g @catppuccin_date_time_text "%H:%M"
      '';
      extraPlugins = [ pkgs.tmuxPlugins.battery ];
      postConfig = ''
        # Status line modules
        set -g status-right-length 100
        set -g status-left-length 100
        set -g status-left ""
        set -g status-right "#{E:@catppuccin_status_directory}"
        set -ag status-right "#{E:@catppuccin_status_date_time}"
        set -agF status-right "#{E:@catppuccin_status_battery}"
      '';
    };
  };
in
{
  options.modules.programs.tmux = {
    enable = lib.mkEnableOption "tmux configuration";
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = tmuxThemePlugins ? ${theme.family};
        message = "tmux: theme family '${theme.family}' not found. Available: ${builtins.concatStringsSep ", " (builtins.attrNames tmuxThemePlugins)}";
      }
    ];

    programs.tmux = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.tmux else mkSystemPackage "tmux" { };
      keyMode = "vi";
      terminal = "tmux-256color";
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
        set -s focus-events on

        # Session Options
        set -g renumber-windows on
        set -g allow-passthrough on

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

        # ============================================================================
        # THEME POST-CONFIG
        # ============================================================================
        ${tmuxThemePlugins.${theme.family}.postConfig}
      '';

      plugins = [
        pkgs.tmuxPlugins.sensible
        pkgs.tmuxPlugins.yank
        pkgs.tmuxPlugins.pain-control
        pkgs.tmuxPlugins.vim-tmux-navigator
        {
          plugin = tmuxThemePlugins.${theme.family}.plugin;
          extraConfig = tmuxThemePlugins.${theme.family}.extraConfig;
        }
        {
          plugin = pkgs.tmuxPlugins.resurrect;
          extraConfig = ''
            set -g @resurrect-strategy-nvim 'session'
            set -g @resurrect-capture-pane-contents 'on'
            set -g @resurrect-save-shell-history 'on'
            set -g @resurrect-processes 'ssh btop top htop less man'
          '';
        }
        {
          plugin = pkgs.tmuxPlugins.continuum;
          extraConfig = ''
            set -g @continuum-restore 'on'
            set -g @continuum-save-interval '15'
          '';
        }
      ]
      ++ tmuxThemePlugins.${theme.family}.extraPlugins;
    };
  };
}
