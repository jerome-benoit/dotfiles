{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.programs.ghostty;
  theme = config.modules.themes.tokyoNightStorm;
  systemGhostty = pkgs.runCommand "ghostty-system" { meta.mainProgram = "ghostty"; } "mkdir -p $out";
in
{
  options.modules.programs.ghostty = {
    enable = lib.mkEnableOption "ghostty configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.ghostty = {
      enable = true;
      package = systemGhostty;

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
        font-family = "JetBrainsMono Nerd Font";
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

        # Keybindings
        keybind = [
          # Tabs
          "ctrl+shift+t=new_tab"
          "ctrl+shift+w=close_surface"
          "ctrl+tab=next_tab"
          "ctrl+shift+tab=previous_tab"

          # Splits
          "ctrl+shift+enter=new_split:right"
          "ctrl+shift+alt+enter=new_split:down"
          "ctrl+shift+h=goto_split:left"
          "ctrl+shift+j=goto_split:bottom"
          "ctrl+shift+k=goto_split:top"
          "ctrl+shift+l=goto_split:right"

          # Resize splits
          "ctrl+shift+left=resize_split:left,10"
          "ctrl+shift+right=resize_split:right,10"
          "ctrl+shift+up=resize_split:up,10"
          "ctrl+shift+down=resize_split:down,10"

          # Other
          "ctrl+shift+c=copy_to_clipboard"
          "ctrl+shift+v=paste_from_clipboard"
          "ctrl+shift+equal=increase_font_size:1"
          "ctrl+shift+minus=decrease_font_size:1"
          "ctrl+shift+0=reset_font_size"
        ];
      }
      // lib.optionalAttrs pkgs.stdenv.isDarwin {
        theme = theme.name;
        macos-option-as-alt = true;
      };
    };
  };
}
