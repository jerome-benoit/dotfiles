{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.alacritty;
  systemAlacritty = pkgs.runCommand "alacritty-system" {
    meta.mainProgram = "alacritty";
  } "mkdir -p $out";
in
{
  options.modules.programs.alacritty = {
    enable = lib.mkEnableOption "alacritty configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.alacritty = {
      enable = true;
      package = if pkgs.stdenv.isDarwin then pkgs.alacritty else systemAlacritty;
      settings = {
        general = {
          import = [
            "${pkgs.alacritty-theme}/share/alacritty-theme/tokyo_night_storm.toml"
          ];
          live_config_reload = true;
        };

        env = {
          TERM = "xterm-256color";
        };

        window = {
          startup_mode = "Maximized";
          decorations = "full";
          dynamic_title = true;
          dynamic_padding = true;
          opacity = 0.95;
          blur = true;
        };

        font = {
          builtin_box_drawing = true;
          normal = {
            family = "JetBrainsMono Nerd Font";
            style = "Regular";
          };
          bold = {
            family = "JetBrainsMono Nerd Font";
            style = "Bold";
          };
          italic = {
            family = "JetBrainsMono Nerd Font";
            style = "Italic";
          };
          bold_italic = {
            family = "JetBrainsMono Nerd Font";
            style = "Bold Italic";
          };
          size = 14.0;
        }
        // lib.optionalAttrs pkgs.stdenv.isDarwin {
          use_thin_strokes = true;
        };

        cursor = {
          style = {
            shape = "Block";
            blinking = "On";
          };
          unfocused_hollow = true;
        };

        scrolling = {
          history = 50000;
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
          animation = "EaseOutExpo";
          duration = 100;
          color = "#ffffff";
        }
        // lib.optionalAttrs pkgs.stdenv.isLinux {
          command = {
            program = "notify-send";
            args = [
              "Alacritty"
              "Bell"
            ];
          };
        };

        hints = {
          enabled = [
            {
              regex = ''(ipfs:|ipns:|magnet:|mailto:|gemini://|gopher://|https://|http://|news:|file:|git://|ssh:|ftp://)[^\u0000-\u001f\u007f-\u009f<>"\\s{-}\\^⟨⟩`]+'';
              command = if pkgs.stdenv.isDarwin then "open" else "xdg-open";
              post_processing = true;
              mouse = {
                enabled = true;
                mods = if pkgs.stdenv.isDarwin then "Command" else "Control";
              };
              binding = {
                key = "U";
                mods = if pkgs.stdenv.isDarwin then "Command|Shift" else "Control|Shift";
              };
            }
          ];
        };

        keyboard = {
          bindings = [
            {
              key = "V";
              mods = "Control|Shift";
              action = "Paste";
            }
            {
              key = "C";
              mods = "Control|Shift";
              action = "Copy";
            }
            {
              key = "Insert";
              mods = "Shift";
              action = "PasteSelection";
            }
            {
              key = "Key0";
              mods = "Control";
              action = "ResetFontSize";
            }
            {
              key = "Equals";
              mods = "Control";
              action = "IncreaseFontSize";
            }
            {
              key = "Plus";
              mods = "Control";
              action = "IncreaseFontSize";
            }
            {
              key = "Minus";
              mods = "Control";
              action = "DecreaseFontSize";
            }
            {
              key = "N";
              mods = "Control|Shift";
              action = "CreateNewWindow";
            }
            {
              key = "Space";
              mods = "Control|Shift";
              action = "ToggleViMode";
            }
          ];
        };
      };
    };
  };
}
