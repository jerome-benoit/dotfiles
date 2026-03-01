{
  lib,
  ...
}:

{
  config.modules.themes.registry.tokyoNightStorm = {
    family = "tokyonight";
    name = "tokyo-night-storm";
    altName = "TokyoNight Storm";
    fileName = "tokyo_night_storm";
    style = "storm";

    colors = {
      # Base colors
      bg = "#24283b";
      fg = "#a9b1d6";

      # Standard colors
      black = "#414868";
      red = "#f7768e";
      green = "#73daca";
      yellow = "#e0af68";
      blue = "#7aa2f7";
      magenta = "#bb9af7";
      cyan = "#7dcfff";
      white = "#8089b3";

      # Bright colors
      brightBlack = "#414868";
      brightRed = "#f7768e";
      brightGreen = "#73daca";
      brightYellow = "#e0af68";
      brightBlue = "#7aa2f7";
      brightMagenta = "#bb9af7";
      brightCyan = "#7dcfff";
      brightWhite = "#a9b1d6";
    };
  };
}
