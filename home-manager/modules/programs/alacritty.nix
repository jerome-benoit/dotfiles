{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.alacritty;
  theme = config.modules.themes.current;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
  fontFamily = config.modules.core.constants.fontFamily;
  isDarwin = pkgs.stdenv.isDarwin;
  isLinux = pkgs.stdenv.isLinux;

  mod = if isDarwin then "Command" else "Control";
  modShift = if isDarwin then "Command|Shift" else "Control|Shift";
  urlOpener = if isDarwin then "open" else "xdg-open";

  bellCommand =
    if isDarwin then
      {
        program = "/opt/homebrew/bin/grrr";
        args = [
          "--title"
          "Alacritty"
          "--reactivate"
          "Bell"
        ];
      }
    else if isLinux then
      {
        program = "notify-send";
        args = [
          "Alacritty"
          "Bell"
        ];
      }
    else
      null;
in
{
  options.modules.programs.alacritty = {
    enable = lib.mkEnableOption "alacritty configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.alacritty = {
      enable = true;
      package = if isDarwin then pkgs.alacritty else mkSystemPackage "alacritty" { };
      settings = {
        general = {
          import = [
            "${pkgs.alacritty-theme}/share/alacritty-theme/${theme.fileName}.toml"
          ];
          live_config_reload = true;
        };

        env = {
          TERM = "xterm-256color";
        };

        window = {
          startup_mode = "Maximized";
          decorations = "Full";
          dynamic_title = true;
          dynamic_padding = true;
          opacity = 0.95;
          blur = true;
        };

        font = {
          builtin_box_drawing = true;
          normal = {
            family = fontFamily;
            style = "Regular";
          };
          bold = {
            family = fontFamily;
            style = "Bold";
          };
          italic = {
            family = fontFamily;
            style = "Italic";
          };
          bold_italic = {
            family = fontFamily;
            style = "Bold Italic";
          };
          size = 14.0;
        };

        cursor = {
          style = {
            shape = "Block";
            blinking = "On";
          };
          unfocused_hollow = true;
        };

        scrolling = {
          history = config.modules.core.constants.historySize;
          multiplier = 2;
        };

        selection = {
          save_to_clipboard = true;
        };

        mouse = {
          hide_when_typing = true;
          bindings = [
            {
              mouse = "Middle";
              action = "PasteSelection";
            }
          ];
        };

        bell = {
          animation = "EaseOutSine";
          duration = 125;
          color = theme.colors.brightBlack;
        }
        // lib.optionalAttrs (bellCommand != null) {
          command = bellCommand;
        };

        hints = {
          enabled = [
            {
              regex = "(ipfs:|ipns:|magnet:|mailto:|gemini://|gopher://|https://|http://|news:|file:|git://|ssh:|ftp://)[^\\u0000-\\u0020\\u007F-\\u009F<>\"{}|\\\\^⟨⟩`]+";
              hyperlinks = true;
              command = urlOpener;
              post_processing = true;
              mouse = {
                enabled = true;
                mods = mod;
              };
              binding = {
                key = "U";
                mods = modShift;
              };
            }
          ];
        };

        keyboard = {
          bindings = [
            {
              key = "V";
              mods = modShift;
              action = "Paste";
            }
            {
              key = "C";
              mods = modShift;
              action = "Copy";
            }
            {
              key = "Key0";
              mods = mod;
              action = "ResetFontSize";
            }
            {
              key = "Equals";
              mods = mod;
              action = "IncreaseFontSize";
            }
            {
              key = "Plus";
              mods = mod;
              action = "IncreaseFontSize";
            }
            {
              key = "Minus";
              mods = mod;
              action = "DecreaseFontSize";
            }
            {
              key = "N";
              mods = modShift;
              action = "CreateNewWindow";
            }
            {
              key = "Space";
              mods = modShift;
              action = "ToggleViMode";
            }
          ]
          ++ lib.optionals isLinux [
            {
              key = "Insert";
              mods = "Shift";
              action = "PasteSelection";
            }
          ];
        };
      };
    };
  };
}
