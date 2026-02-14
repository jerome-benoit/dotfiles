{
  lib,
  ...
}:

{
  config.modules.themes.tokyoNightLight = {
    name = "tokyo-night-light";
    altName = "TokyoNight Light";
    fileName = "tokyo_night_light";

    colors = {
      # Base colors
      bg = "#e6e7ed";
      fg = "#343b58";

      # Standard colors
      black = "#343b58";
      red = "#8c4351";
      green = "#33635c";
      yellow = "#8f5e15";
      blue = "#2959aa";
      magenta = "#7b43ba";
      cyan = "#006c86";
      white = "#707280";

      # Bright colors
      brightBlack = "#343b58";
      brightRed = "#8c4351";
      brightGreen = "#33635c";
      brightYellow = "#8f5e15";
      brightBlue = "#2959aa";
      brightMagenta = "#7b43ba";
      brightCyan = "#006c86";
      brightWhite = "#707280";
    };
  };
}
