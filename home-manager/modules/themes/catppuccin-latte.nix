{
  lib,
  ...
}:

{
  config.modules.themes.registry.catppuccinLatte = {
    family = "catppuccin";
    name = "catppuccin-latte";
    altName = "Catppuccin Latte";
    fileName = "catppuccin_latte";
    style = "latte";

    colors = {
      # Base colors
      bg = "#eff1f5";
      fg = "#4c4f69";

      # Standard colors
      black = "#5c5f77";
      red = "#d20f39";
      green = "#40a02b";
      yellow = "#df8e1d";
      blue = "#1e66f5";
      magenta = "#ea76cb";
      cyan = "#179299";
      white = "#acb0be";

      # Bright colors
      brightBlack = "#6c6f85";
      brightRed = "#de293e";
      brightGreen = "#49af3d";
      brightYellow = "#eea02d";
      brightBlue = "#456eff";
      brightMagenta = "#fe85d8";
      brightCyan = "#2d9fa8";
      brightWhite = "#bcc0cc";
    };
  };
}
