{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.alacritty;
  theme = config.modules.themes.current;
  mkPlatformPackage = config.modules.core.lib.mkPlatformPackage;
  fontFamily = config.modules.core.constants.fontFamily;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  isLinux = pkgs.stdenv.hostPlatform.isLinux;

  mod = if isDarwin then "Command" else "Control";
  modShift = if isDarwin then "Command|Shift" else "Control|Shift";
  urlOpener = if isDarwin then "open" else "xdg-open";

  grrrBin =
    if builtins.pathExists /opt/homebrew/bin/grrr then
      "/opt/homebrew/bin/grrr"
    else if builtins.pathExists /usr/local/bin/grrr then
      "/usr/local/bin/grrr"
    else
      null;

  bellCommand =
    if isDarwin && grrrBin != null then
      {
        program = grrrBin;
        args = [
          "--title"
          "Alacritty"
          "--execute"
          "open -a Alacritty"
          "Bell"
        ];
      }
    else if isLinux then
      {
        program = "notify-send";
        args = [
          "-a"
          "Alacritty"
          "-i"
          "alacritty"
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
      package = mkPlatformPackage "alacritty" { };
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
