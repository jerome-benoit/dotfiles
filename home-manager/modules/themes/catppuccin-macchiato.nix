{
  lib,
  ...
}:

{
  config.modules.themes.registry.catppuccinMacchiato = {
    family = "catppuccin";
    name = "catppuccin-macchiato";
    altName = "Catppuccin Macchiato";
    fileName = "catppuccin_macchiato";
    style = "macchiato";

    colors = {
      # Base colors
      bg = "#24273a";
      fg = "#cad3f5";

      # Standard colors
      black = "#494d64";
      red = "#ed8796";
      green = "#a6da95";
      yellow = "#eed49f";
      blue = "#8aadf4";
      magenta = "#f5bde6";
      cyan = "#8bd5ca";
      white = "#a5adcb";

      # Bright colors
      brightBlack = "#5b6078";
      brightRed = "#ec7486";
      brightGreen = "#8ccf7f";
      brightYellow = "#e1c682";
      brightBlue = "#78a1f6";
      brightMagenta = "#f2a9dd";
      brightCyan = "#63cbc0";
      brightWhite = "#b8c0e0";
    };
  };
}
