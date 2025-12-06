{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.zellij;
  theme = config.modules.themes.tokyoNight;
  systemZellij = pkgs.runCommand "zellij-system" {
    version = "0.43.0";
    meta.mainProgram = "zellij";
  } "mkdir -p $out";

in
{
  options.modules.programs.zellij = {
    enable = lib.mkEnableOption "zellij configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.zellij = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.zellij else systemZellij;
      enableZshIntegration = false;

      settings = {
        theme = theme.name;

        simplified_ui = true; # default: false

        session_serialization = true; # default: false
        pane_viewport_serialization = true; # default: false
        scrollback_lines_to_serialize = 100; # default: 10000
        serialization_interval = 60; # serialize every 60 seconds

        scroll_buffer_size = config.modules.core.constants.historySize;

        show_startup_tips = false; # default: true
      };

      extraConfig = ''
        keybinds {
          normal {
            // Pane navigation
            bind "Alt h" { MoveFocus "Left"; }
            bind "Alt j" { MoveFocus "Down"; }
            bind "Alt k" { MoveFocus "Up"; }
            bind "Alt l" { MoveFocus "Right"; }

            // Tab navigation
            bind "Alt [" { GoToPreviousTab; }
            bind "Alt ]" { GoToNextTab; }

            // Tab access
            bind "Alt 1" { GoToTab 1; }
            bind "Alt 2" { GoToTab 2; }
            bind "Alt 3" { GoToTab 3; }
            bind "Alt 4" { GoToTab 4; }
            bind "Alt 5" { GoToTab 5; }
            bind "Alt 6" { GoToTab 6; }
            bind "Alt 7" { GoToTab 7; }
            bind "Alt 8" { GoToTab 8; }
            bind "Alt 9" { GoToTab 9; }

            // Quick actions
            bind "Alt n" { NewPane; }
            bind "Alt t" { NewTab; }
            bind "Alt f" { ToggleFloatingPanes; }
            bind "Alt z" { ToggleFocusFullscreen; }
            bind "Alt w" { TogglePaneFrames; }

            // Plugin management
            bind "Ctrl o" "w" { LaunchOrFocusPlugin "session-manager"; }
            bind "Ctrl o" "p" { LaunchOrFocusPlugin "plugin-manager"; }
          }
        }
      '';

      layouts.default = {
        layout = {
          _children = [
            {
              default_tab_template = {
                _children = [
                  { children = { }; }

                  # Status bar
                  {
                    pane = {
                      _props = {
                        size = 1;
                        borderless = true;
                      };
                      _children = [
                        {
                          plugin = {
                            _props = {
                              location = "https://github.com/dj95/zjstatus/releases/latest/download/zjstatus.wasm";
                            };

                            format_left = "{mode} #[fg=${theme.brightBlue},bold]{session}";
                            format_center = "{tabs}";
                            format_right = "{datetime}";
                            format_space = "";

                            hide_frame_for_single_pane = "true";

                            mode_normal = "#[bg=${theme.blue},fg=${theme.bg},bold] NORMAL ";
                            mode_locked = "#[bg=${theme.red},fg=${theme.bg},bold] LOCKED ";
                            mode_pane = "#[bg=${theme.green},fg=${theme.bg},bold] PANE ";
                            mode_tab = "#[bg=${theme.cyan},fg=${theme.bg},bold] TAB ";
                            mode_resize = "#[bg=${theme.magenta},fg=${theme.bg},bold] RESIZE ";
                            mode_scroll = "#[bg=${theme.yellow},fg=${theme.bg},bold] SCROLL ";
                            mode_move = "#[bg=${theme.orange},fg=${theme.bg},bold] MOVE ";
                            mode_session = "#[bg=${theme.red},fg=${theme.bg},bold] SESSION ";
                            mode_tmux = "#[bg=${theme.fg},fg=${theme.bg},bold] TMUX ";

                            tab_normal = "#[fg=${theme.comment}] {index}:{name} ";
                            tab_active = "#[fg=${theme.blue},bold] {index}:{name} ";

                            datetime = "#[fg=${theme.fg}] {format}";
                            datetime_format = "%H:%M";
                            datetime_timezone = config.modules.core.constants.timezone;
                          };
                        }
                      ];
                    };
                  }
                ];
              };
            }
          ];
        };
      };
    };
  };
}
