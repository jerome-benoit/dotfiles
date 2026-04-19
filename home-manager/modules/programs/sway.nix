{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.sway;
  theme = config.modules.themes.current;
  constants = config.modules.core.constants;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
  fontFamily = constants.fontFamily;
  wallpaper = if isLightTheme then "/usr/share/backgrounds/default.jxl" else "/usr/share/backgrounds/default-dark.jxl";
  hex = color: lib.removePrefix "#" color;
  bg = theme.colors.bg;
  fg = theme.colors.fg;
  black = theme.colors.black;
  red = theme.colors.red;
  green = theme.colors.green;
  yellow = theme.colors.yellow;
  blue = theme.colors.blue;
  magenta = theme.colors.magenta;
  cyan = theme.colors.cyan;
  white = theme.colors.white;
  brightBlack = theme.colors.brightBlack or black;
  brightRed = theme.colors.brightRed or red;
  brightGreen = theme.colors.brightGreen or green;
  brightYellow = theme.colors.brightYellow or yellow;
  brightBlue = theme.colors.brightBlue or blue;
  brightMagenta = theme.colors.brightMagenta or magenta;
  brightCyan = theme.colors.brightCyan or cyan;
  brightWhite = theme.colors.brightWhite or white;
  isLightTheme = builtins.elem theme.style [
    "day"
    "latte"
  ];
  isLinuxDesktop =
    pkgs.stdenv.hostPlatform.isLinux && config.modules.core.profile.name == constants.profiles.desktop;
in
{
  options.modules.programs.sway = {
    enable = lib.mkEnableOption "Sway desktop configuration";
  };

  config = lib.mkIf (cfg.enable && isLinuxDesktop) {
    gtk = {
      enable = true;
      theme = {
        name = if isLightTheme then "Adwaita" else "Adwaita-dark";
        package = pkgs.gnome-themes-extra;
      };
      iconTheme = {
        name = "Adwaita";
        package = pkgs.adwaita-icon-theme;
      };
      cursorTheme = {
        name = "Adwaita";
        package = pkgs.adwaita-icon-theme;
      };
    };

    dconf.settings."org/gnome/desktop/interface" = {
      color-scheme = if isLightTheme then "prefer-light" else "prefer-dark";
    };

    xdg.configFile."sway/config.d/20-keyboard-and-lock.conf".text = ''
      # Generated from Home Manager.

      input "1452:657:Apple_Inc._Apple_Internal_Keyboard_/_Trackpad" {
          repeat_delay 300
          repeat_rate 40
      }

      bindsym $mod+Shift+Escape exec loginctl lock-session
    '';

    xdg.configFile."sway/config.d/40-theme.conf".text = ''
      # Generated from Home Manager theme registry.

      client.focused ${blue} ${bg} ${fg} ${cyan} ${blue}
      client.focused_inactive ${black} ${bg} ${white} ${black} ${black}
      client.unfocused ${black} ${bg} ${white} ${black} ${black}
      client.urgent ${red} ${bg} ${fg} ${red} ${red}

      default_border pixel 2
      default_floating_border pixel 2
      gaps inner 8
      gaps outer 4
      smart_gaps on
      smart_borders on

      titlebar_padding 8 4
      title_align center
    '';

    xdg.configFile."sway/config.d/50-background.conf".text = ''
      # Generated from Home Manager theme registry.

      output * bg ${wallpaper} fill
    '';

    programs.waybar = {
      enable = true;
      package = mkSystemPackage "waybar" { };
      settings = [
        {
          include = [ "/etc/xdg/waybar/config.jsonc" ];
        }
      ];
      style = ''
        * {
            min-height: 0;
        }

        window#waybar {
            background: ${bg};
            border-bottom: 1px solid ${black};
            color: ${fg};
        }

        window#waybar.hidden {
            opacity: 0.25;
        }

        button {
            border: none;
            border-radius: 8px;
            box-shadow: inset 0 -2px transparent;
            transition: background-color 120ms ease, color 120ms ease;
        }

        button:hover {
            background: ${black};
            box-shadow: inset 0 -2px ${blue};
        }

        #workspaces,
        #window {
            margin: 4px 6px;
        }

        #workspaces button {
            padding: 0 10px;
            color: ${fg};
            background: transparent;
        }

        #workspaces button:hover {
            color: ${fg};
        }

        #workspaces button.focused {
            background: ${black};
            color: ${blue};
            box-shadow: inset 0 -2px ${blue};
        }

        #workspaces button.urgent {
            background: ${red};
            color: ${bg};
        }

        #mode,
        #scratchpad,
        #clock,
        #battery,
        #cpu,
        #memory,
        #temperature,
        #backlight,
        #network,
        #language,
        #pulseaudio,
        #wireplumber,
        #tray,
        #idle_inhibitor,
        #power-profiles-daemon,
        #mpd,
        #custom-media {
            margin: 4px 3px;
            padding: 0 10px;
            border-radius: 8px;
            color: ${fg};
            background: ${bg};
        }

        #window {
            color: ${fg};
        }

        #clock {
            background: ${black};
            color: ${yellow};
        }

        #battery {
            background: ${black};
            color: ${fg};
        }

        #battery.charging,
        #battery.plugged {
            background: ${black};
            color: ${green};
        }

        @keyframes blink-critical {
            to {
                background: ${bg};
                color: ${red};
            }
        }

        #battery.critical:not(.charging) {
            background: ${red};
            color: ${bg};
            animation-name: blink-critical;
            animation-duration: 0.8s;
            animation-timing-function: steps(12);
            animation-iteration-count: infinite;
            animation-direction: alternate;
        }

        #cpu {
            color: ${cyan};
        }

        #memory {
            color: ${magenta};
        }

        #temperature {
            color: ${yellow};
        }

        #temperature.critical {
            color: ${red};
        }

        #backlight {
            color: ${yellow};
        }

        #network {
            color: ${blue};
        }

        #network.disconnected {
            color: ${red};
        }

        #pulseaudio,
        #wireplumber {
            color: ${cyan};
        }

        #pulseaudio.muted,
        #wireplumber.muted {
            color: ${white};
        }

        #tray > .passive {
            -gtk-icon-effect: dim;
        }

        #tray > .needs-attention {
            background: ${red};
        }

        #idle_inhibitor {
            color: ${white};
        }

        #idle_inhibitor.activated {
            color: ${yellow};
        }

        #power-profiles-daemon.performance {
            color: ${red};
        }

        #power-profiles-daemon.balanced {
            color: ${blue};
        }

        #power-profiles-daemon.power-saver {
            color: ${green};
        }
      '';
    };

    programs.rofi = {
      enable = true;
      package = mkSystemPackage "rofi" { };
      terminal = "foot";
      theme =
        let
          inherit (config.lib.formats.rasi) mkLiteral;
        in
        {
          "*" = {
            bg = mkLiteral bg;
            bg-alt = mkLiteral black;
            fg = mkLiteral fg;
            fg-dim = mkLiteral white;
            border = mkLiteral black;
            accent = mkLiteral blue;
            accent-alt = mkLiteral magenta;
            ok = mkLiteral green;
            warn = mkLiteral yellow;
            err = mkLiteral red;
            sel-bg = mkLiteral black;
            sel-fg = mkLiteral fg;
            urgent-bg = mkLiteral red;
            urgent-fg = mkLiteral bg;
            border-radius = mkLiteral "14px";
          };

          window = {
            location = mkLiteral "center";
            anchor = mkLiteral "center";
            width = mkLiteral "42em";
            border = 2;
            border-color = mkLiteral "@accent";
            border-radius = mkLiteral "@border-radius";
            background-color = mkLiteral "@bg";
            padding = mkLiteral "18px";
          };

          mainbox = {
            spacing = mkLiteral "12px";
            background-color = mkLiteral "transparent";
          };

          inputbar = {
            children = map mkLiteral [
              "prompt"
              "entry"
              "case-indicator"
            ];
            spacing = mkLiteral "10px";
            padding = mkLiteral "12px 14px";
            border = 0;
            border-radius = mkLiteral "12px";
            background-color = mkLiteral "@bg-alt";
            text-color = mkLiteral "@fg";
          };

          prompt.text-color = mkLiteral "@accent";

          entry = {
            placeholder = "Search";
            placeholder-color = mkLiteral "@fg-dim";
            text-color = mkLiteral "@fg";
          };

          message = {
            border-radius = mkLiteral "12px";
            background-color = mkLiteral "@bg-alt";
            padding = mkLiteral "10px 14px";
            text-color = mkLiteral "@fg";
          };

          textbox.text-color = mkLiteral "@fg-dim";
          overlay.text-color = mkLiteral "@fg-dim";
          "case-indicator".text-color = mkLiteral "@fg-dim";
          "num-rows".text-color = mkLiteral "@fg-dim";
          "num-filtered-rows".text-color = mkLiteral "@fg-dim";
          "textbox-current-entry".text-color = mkLiteral "@fg";

          "error-message" = {
            background-color = mkLiteral "@bg-alt";
            border-radius = mkLiteral "12px";
            border = 0;
            padding = mkLiteral "12px";
            text-color = mkLiteral "@fg";
          };

          listview = {
            lines = 10;
            columns = 1;
            fixed-height = false;
            cycle = true;
            dynamic = true;
            scrollbar = false;
            spacing = mkLiteral "8px";
            background-color = mkLiteral "transparent";
          };

          element = {
            padding = mkLiteral "12px 14px";
            border = 0;
            border-radius = mkLiteral "12px";
            background-color = mkLiteral "transparent";
            text-color = mkLiteral "@fg";
          };

          "element normal.normal" = {
            background-color = mkLiteral "transparent";
            text-color = mkLiteral "@fg";
          };

          "element alternate.normal" = {
            background-color = mkLiteral "transparent";
            text-color = mkLiteral "@fg";
          };

          "element normal.active".text-color = mkLiteral "@ok";
          "element alternate.active".text-color = mkLiteral "@ok";
          "element normal.urgent".text-color = mkLiteral "@err";
          "element alternate.urgent".text-color = mkLiteral "@err";

          "element selected.normal" = {
            background-color = mkLiteral "@sel-bg";
            text-color = mkLiteral "@sel-fg";
          };

          "element selected.active" = {
            background-color = mkLiteral "@accent";
            text-color = mkLiteral "@bg";
          };

          "element selected.urgent" = {
            background-color = mkLiteral "@urgent-bg";
            text-color = mkLiteral "@urgent-fg";
          };

          "element-icon" = {
            size = mkLiteral "1.1em";
            vertical-align = mkLiteral "0.5";
          };

          "element-text" = {
            text-color = mkLiteral "inherit";
            vertical-align = mkLiteral "0.5";
          };

          "mode-switcher" = {
            spacing = mkLiteral "8px";
            background-color = mkLiteral "transparent";
          };

          button = {
            padding = mkLiteral "10px 12px";
            border = 0;
            border-radius = mkLiteral "10px";
            background-color = mkLiteral "@bg-alt";
            text-color = mkLiteral "@fg-dim";
          };

          "button selected" = {
            background-color = mkLiteral "@accent-alt";
            text-color = mkLiteral "@bg";
          };
        };
      extraConfig = {
        modes = "drun,run,window,ssh";
        show-icons = true;
        icon-theme = "Adwaita";
        drun-display-format = "{name}";
      };
    };

    programs.swaylock = {
      enable = true;
      package = mkSystemPackage "swaylock" { };
      settings = {
        image = wallpaper;
        scaling = "fill";
        show-failed-attempts = true;
        indicator-idle-visible = true;
        indicator-radius = 110;
        indicator-thickness = 8;
        color = "${hex bg}cc";
        inside-color = "${hex black}cc";
        ring-color = "${hex blue}ff";
        line-color = "00000000";
        separator-color = "00000000";
        text-color = "${hex fg}ff";
        key-hl-color = "${hex magenta}ff";
        bs-hl-color = "${hex red}ff";
        inside-clear-color = "${hex black}cc";
        ring-clear-color = "${hex cyan}ff";
        text-clear-color = "${hex fg}ff";
        inside-caps-lock-color = "${hex black}cc";
        ring-caps-lock-color = "${hex yellow}ff";
        text-caps-lock-color = "${hex yellow}ff";
        inside-ver-color = "${hex black}cc";
        ring-ver-color = "${hex green}ff";
        text-ver-color = "${hex green}ff";
        inside-wrong-color = "${hex black}cc";
        ring-wrong-color = "${hex red}ff";
        text-wrong-color = "${hex red}ff";
        layout-bg-color = "${hex black}dd";
        layout-border-color = "${hex black}ff";
        layout-text-color = "${hex fg}ff";
      };
    };

    programs.foot = {
      enable = true;
      package = mkSystemPackage "foot" { };
      server.enable = true;
      settings = {
        main = {
          font = "${fontFamily}:size=12";
        };
        colors = {
          alpha = 0.95;
          foreground = hex fg;
          background = hex bg;
          regular0 = hex black;
          regular1 = hex red;
          regular2 = hex green;
          regular3 = hex yellow;
          regular4 = hex blue;
          regular5 = hex magenta;
          regular6 = hex cyan;
          regular7 = hex white;
          bright0 = hex brightBlack;
          bright1 = hex brightRed;
          bright2 = hex brightGreen;
          bright3 = hex brightYellow;
          bright4 = hex brightBlue;
          bright5 = hex brightMagenta;
          bright6 = hex brightCyan;
          bright7 = hex brightWhite;
          selection-foreground = hex fg;
          selection-background = hex brightBlack;
          cursor = "${hex fg} ${hex bg}";
        };
        cursor = {
          style = "block";
          blink = true;
        };
      };
    };
  };
}
