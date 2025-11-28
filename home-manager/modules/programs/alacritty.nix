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
          live_config_reload = true;
          import = [
            "${pkgs.alacritty-theme}/share/alacritty-theme/tokyo_night_storm.toml"
          ];
        };

        env = {
          TERM = "xterm-256color";
        };

        window = {
          padding = {
            x = 10;
            y = 10;
          };
          decorations = "full";
          opacity = 0.95;
          startup_mode = "Maximized";
          dynamic_title = true;
        };

        font = {
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
        };

        cursor = {
          style = {
            shape = "Block";
            blinking = "On";
          };
          unfocused_hollow = true;
        };

        scrolling = {
          history = 10000;
          multiplier = 3;
        };

        selection = {
          save_to_clipboard = true;
        };

        mouse = {
          hide_when_typing = true;
        };

        bell = {
          animation = "EaseOutExpo";
          duration = 0;
          color = "#ffffff";
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
          ];
        };
      };
    };
  };
}
