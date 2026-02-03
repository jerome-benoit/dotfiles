{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.ghostty;
  theme = config.modules.themes.tokyoNightStorm;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
  fontFamily = config.modules.core.constants.fontFamily;
  isDarwin = pkgs.stdenv.isDarwin;
in
{
  options.modules.programs.ghostty = {
    enable = lib.mkEnableOption "ghostty configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.ghostty = {
      enable = true;
      package = mkSystemPackage "ghostty" { };

      settings = {
        # Window
        window-decoration = true;
        window-padding-x = 10;
        window-padding-y = 10;
        window-padding-balance = true;
        window-save-state = "always";
        window-theme = "auto";
        window-inherit-working-directory = true;

        # Font
        font-family = fontFamily;
        font-size = 12;
        font-thicken = true;
        adjust-cell-height = "20%";

        # Cursor
        cursor-style = "block";
        cursor-style-blink = true;

        # Terminal
        term = "xterm-256color";

        # Shell
        shell-integration = "detect";
        shell-integration-features = "cursor,sudo,title";

        # Clipboard
        clipboard-read = "allow";
        clipboard-write = "allow";
        copy-on-select = true;

        # Mouse
        mouse-hide-while-typing = true;

        # Scrollback
        scrollback-limit = config.modules.core.constants.historySize;

        # Performance
        resize-overlay = "never";

        # Updates
        auto-update = "off";
      }
      // lib.optionalAttrs isDarwin {
        theme = theme.altName or theme.name;
        macos-option-as-alt = true;
      };
    };
  };
}
