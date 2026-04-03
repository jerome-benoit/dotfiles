{
  lib,
  config,
  ...
}:

let
  themeSubmoduleType = lib.types.submodule {
    options = {
      family = lib.mkOption {
        type = lib.types.str;
        description = "Theme family identifier (e.g. tokyonight, catppuccin)";
      };
      name = lib.mkOption {
        type = lib.types.str;
        description = "Theme slug in kebab-case (e.g. tokyo-night-storm)";
      };
      altName = lib.mkOption {
        type = lib.types.str;
        description = "Human-readable display name (e.g. TokyoNight Storm)";
      };
      fileName = lib.mkOption {
        type = lib.types.str;
        description = "Theme file name without extension (e.g. tokyo_night_storm)";
      };
      colors = lib.mkOption {
        type = lib.types.attrsOf lib.types.str;
        description = "Hex color palette keyed by role (e.g. bg, fg, blue)";
      };
      style = lib.mkOption {
        type = lib.types.str;
        description = "Variant within the family (e.g. storm, latte, mocha)";
      };
    };
  };

  mkTheme = key: data: _: {
    config.modules.themes.registry.${key} = data;
  };
in
{
  imports = [
    (mkTheme "tokyoNight" {
      family = "tokyonight";
      name = "tokyo-night";
      altName = "TokyoNight";
      fileName = "tokyo_night";
      style = "night";
      colors = {
        bg = "#1a1b26";
        fg = "#a9b1d6";
        black = "#363b54";
        red = "#f7768e";
        green = "#73daca";
        yellow = "#e0af68";
        blue = "#7aa2f7";
        magenta = "#bb9af7";
        cyan = "#7dcfff";
        white = "#787c99";
        brightBlack = "#363b54";
        brightRed = "#f7768e";
        brightGreen = "#73daca";
        brightYellow = "#e0af68";
        brightBlue = "#7aa2f7";
        brightMagenta = "#bb9af7";
        brightCyan = "#7dcfff";
        brightWhite = "#acb0d0";
      };
    })
    (mkTheme "tokyoNightStorm" {
      family = "tokyonight";
      name = "tokyo-night-storm";
      altName = "TokyoNight Storm";
      fileName = "tokyo_night_storm";
      style = "storm";
      colors = {
        bg = "#24283b";
        fg = "#a9b1d6";
        black = "#414868";
        red = "#f7768e";
        green = "#73daca";
        yellow = "#e0af68";
        blue = "#7aa2f7";
        magenta = "#bb9af7";
        cyan = "#7dcfff";
        white = "#8089b3";
        brightBlack = "#414868";
        brightRed = "#f7768e";
        brightGreen = "#73daca";
        brightYellow = "#e0af68";
        brightBlue = "#7aa2f7";
        brightMagenta = "#bb9af7";
        brightCyan = "#7dcfff";
        brightWhite = "#a9b1d6";
      };
    })
    (mkTheme "tokyoNightLight" {
      family = "tokyonight";
      name = "tokyo-night-light";
      altName = "TokyoNight Light";
      fileName = "tokyo_night_light";
      style = "day";
      colors = {
        bg = "#e6e7ed";
        fg = "#343b58";
        black = "#343b58";
        red = "#8c4351";
        green = "#33635c";
        yellow = "#8f5e15";
        blue = "#2959aa";
        magenta = "#7b43ba";
        cyan = "#006c86";
        white = "#707280";
        brightBlack = "#343b58";
        brightRed = "#8c4351";
        brightGreen = "#33635c";
        brightYellow = "#8f5e15";
        brightBlue = "#2959aa";
        brightMagenta = "#7b43ba";
        brightCyan = "#006c86";
        brightWhite = "#707280";
      };
    })
    (mkTheme "catppuccinMocha" {
      family = "catppuccin";
      name = "catppuccin-mocha";
      altName = "Catppuccin Mocha";
      fileName = "catppuccin_mocha";
      style = "mocha";
      colors = {
        bg = "#1e1e2e";
        fg = "#cdd6f4";
        black = "#45475a";
        red = "#f38ba8";
        green = "#a6e3a1";
        yellow = "#f9e2af";
        blue = "#89b4fa";
        magenta = "#f5c2e7";
        cyan = "#94e2d5";
        white = "#a6adc8";
        brightBlack = "#585b70";
        brightRed = "#f37799";
        brightGreen = "#89d88b";
        brightYellow = "#ebd391";
        brightBlue = "#74a8fc";
        brightMagenta = "#f2aede";
        brightCyan = "#6bd7ca";
        brightWhite = "#bac2de";
      };
    })
    (mkTheme "catppuccinMacchiato" {
      family = "catppuccin";
      name = "catppuccin-macchiato";
      altName = "Catppuccin Macchiato";
      fileName = "catppuccin_macchiato";
      style = "macchiato";
      colors = {
        bg = "#24273a";
        fg = "#cad3f5";
        black = "#494d64";
        red = "#ed8796";
        green = "#a6da95";
        yellow = "#eed49f";
        blue = "#8aadf4";
        magenta = "#f5bde6";
        cyan = "#8bd5ca";
        white = "#a5adcb";
        brightBlack = "#5b6078";
        brightRed = "#ec7486";
        brightGreen = "#8ccf7f";
        brightYellow = "#e1c682";
        brightBlue = "#78a1f6";
        brightMagenta = "#f2a9dd";
        brightCyan = "#63cbc0";
        brightWhite = "#b8c0e0";
      };
    })
    (mkTheme "catppuccinFrappe" {
      family = "catppuccin";
      name = "catppuccin-frappe";
      altName = "Catppuccin Frappe";
      fileName = "catppuccin_frappe";
      style = "frappe";
      colors = {
        bg = "#303446";
        fg = "#c6d0f5";
        black = "#51576d";
        red = "#e78284";
        green = "#a6d189";
        yellow = "#e5c890";
        blue = "#8caaee";
        magenta = "#f4b8e4";
        cyan = "#81c8be";
        white = "#a5adce";
        brightBlack = "#626880";
        brightRed = "#e67172";
        brightGreen = "#8ec772";
        brightYellow = "#d9ba73";
        brightBlue = "#7b9ef0";
        brightMagenta = "#f2a4db";
        brightCyan = "#5abfb5";
        brightWhite = "#b5bfe2";
      };
    })
    (mkTheme "catppuccinLatte" {
      family = "catppuccin";
      name = "catppuccin-latte";
      altName = "Catppuccin Latte";
      fileName = "catppuccin_latte";
      style = "latte";
      colors = {
        bg = "#eff1f5";
        fg = "#4c4f69";
        black = "#5c5f77";
        red = "#d20f39";
        green = "#40a02b";
        yellow = "#df8e1d";
        blue = "#1e66f5";
        magenta = "#ea76cb";
        cyan = "#179299";
        white = "#acb0be";
        brightBlack = "#6c6f85";
        brightRed = "#de293e";
        brightGreen = "#49af3d";
        brightYellow = "#eea02d";
        brightBlue = "#456eff";
        brightMagenta = "#fe85d8";
        brightCyan = "#2d9fa8";
        brightWhite = "#bcc0cc";
      };
    })
  ];

  options.modules.themes = {
    registry = lib.mkOption {
      type = lib.types.attrsOf themeSubmoduleType;
      default = { };
      description = "Registry of available themes";
    };

    active = lib.mkOption {
      type = lib.types.str;
      default = "tokyoNightStorm";
      description = "Registry key of the active theme";
    };

    current = lib.mkOption {
      type = themeSubmoduleType;
      readOnly = true;
      description = "Active theme resolved from the registry";
    };
  };

  config = {
    assertions = [
      {
        assertion = config.modules.themes.registry ? ${config.modules.themes.active};
        message = "themes: '${config.modules.themes.active}' not found in registry. Available: ${builtins.concatStringsSep ", " (builtins.attrNames config.modules.themes.registry)}";
      }
    ];

    modules.themes.current = config.modules.themes.registry.${config.modules.themes.active};
  };
}
