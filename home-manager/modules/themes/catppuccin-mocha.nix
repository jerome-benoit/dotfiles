{
  lib,
  ...
}:

{
  config.modules.themes.registry.catppuccinMocha = {
    family = "catppuccin";
    name = "catppuccin-mocha";
    altName = "Catppuccin Mocha";
    fileName = "catppuccin_mocha";
    style = "mocha";

    colors = {
      # Base colors
      bg = "#1e1e2e";
      fg = "#cdd6f4";

      # Standard colors
      black = "#45475a";
      red = "#f38ba8";
      green = "#a6e3a1";
      yellow = "#f9e2af";
      blue = "#89b4fa";
      magenta = "#f5c2e7";
      cyan = "#94e2d5";
      white = "#a6adc8";

      # Bright colors
      brightBlack = "#585b70";
      brightRed = "#f37799";
      brightGreen = "#89d88b";
      brightYellow = "#ebd391";
      brightBlue = "#74a8fc";
      brightMagenta = "#f2aede";
      brightCyan = "#6bd7ca";
      brightWhite = "#bac2de";
    };
  };
}
