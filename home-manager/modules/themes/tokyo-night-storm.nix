{ lib, ... }:

{
  options.modules.themes.tokyoNightStorm = {
    # Meta
    name = lib.mkOption {
      type = lib.types.str;
      default = "tokyo-night-storm";
      description = "Theme name";
    };

    fileName = lib.mkOption {
      type = lib.types.str;
      default = "tokyo_night_storm";
      description = "Theme file name";
    };

    # Colors
    bg = lib.mkOption {
      type = lib.types.str;
      default = "#1a1b26";
      description = "Background";
    };

    fg = lib.mkOption {
      type = lib.types.str;
      default = "#c0caf5";
      description = "Foreground";
    };

    black = lib.mkOption {
      type = lib.types.str;
      default = "#32344a";
      description = "Normal black";
    };

    red = lib.mkOption {
      type = lib.types.str;
      default = "#f7768e";
      description = "Normal red";
    };

    green = lib.mkOption {
      type = lib.types.str;
      default = "#9ece6a";
      description = "Normal green";
    };

    yellow = lib.mkOption {
      type = lib.types.str;
      default = "#e0af68";
      description = "Normal yellow";
    };

    blue = lib.mkOption {
      type = lib.types.str;
      default = "#7aa2f7";
      description = "Normal blue";
    };

    magenta = lib.mkOption {
      type = lib.types.str;
      default = "#bb9af7";
      description = "Normal magenta";
    };

    cyan = lib.mkOption {
      type = lib.types.str;
      default = "#7dcfff";
      description = "Normal cyan";
    };

    white = lib.mkOption {
      type = lib.types.str;
      default = "#9699a8";
      description = "Normal white";
    };

    brightBlack = lib.mkOption {
      type = lib.types.str;
      default = "#444b6a";
      description = "Bright black";
    };

    brightBlue = lib.mkOption {
      type = lib.types.str;
      default = "#89B4FA";
      description = "Bright blue";
    };

    comment = lib.mkOption {
      type = lib.types.str;
      default = "#565f89";
      description = "Comment color";
    };

    orange = lib.mkOption {
      type = lib.types.str;
      default = "#ff9e64";
      description = "Orange accent";
    };
  };
}
