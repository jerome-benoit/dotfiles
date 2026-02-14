{
  lib,
  ...
}:

{
  config.modules.themes.tokyoNightStorm = {
    name = "tokyo-night-storm";
    altName = "TokyoNight Storm";
    fileName = "tokyo_night_storm";

    colors = {
      # Base colors
      bg = "#24283b";
      fg = "#a9b1d6";

      # Standard colors
      black = "#32344a";
      red = "#f7768e";
      green = "#9ece6a";
      yellow = "#e0af68";
      blue = "#7aa2f7";
      magenta = "#ad8ee6";
      cyan = "#449dab";
      white = "#9699a8";

      # Bright colors
      brightBlack = "#444b6a";
      brightRed = "#ff7a93";
      brightGreen = "#b9f27c";
      brightYellow = "#ff9e64";
      brightBlue = "#7da6ff";
      brightMagenta = "#bb9af7";
      brightCyan = "#0db9d7";
      brightWhite = "#acb0d0";
    };
  };
}
