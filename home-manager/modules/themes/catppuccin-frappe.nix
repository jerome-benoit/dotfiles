{
  lib,
  ...
}:

{
  config.modules.themes.registry.catppuccinFrappe = {
    family = "catppuccin";
    name = "catppuccin-frappe";
    altName = "Catppuccin Frappe";
    fileName = "catppuccin_frappe";
    style = "frappe";

    colors = {
      # Base colors
      bg = "#303446";
      fg = "#c6d0f5";

      # Standard colors
      black = "#51576d";
      red = "#e78284";
      green = "#a6d189";
      yellow = "#e5c890";
      blue = "#8caaee";
      magenta = "#f4b8e4";
      cyan = "#81c8be";
      white = "#a5adce";

      # Bright colors
      brightBlack = "#626880";
      brightRed = "#e67172";
      brightGreen = "#8ec772";
      brightYellow = "#d9ba73";
      brightBlue = "#7b9ef0";
      brightMagenta = "#f2a4db";
      brightCyan = "#5abfb5";
      brightWhite = "#b5bfe2";
    };
  };
}
