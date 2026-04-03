{
  lib,
  config,
  ...
}:

{
  imports = [
    ./tokyo-night.nix
    ./tokyo-night-storm.nix
    ./tokyo-night-light.nix
    ./catppuccin-mocha.nix
    ./catppuccin-macchiato.nix
    ./catppuccin-frappe.nix
    ./catppuccin-latte.nix
  ];

  options.modules.themes = {
    registry = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            family = lib.mkOption {
              type = lib.types.str;
              description = "Theme family (e.g. tokyonight, catppuccin)";
            };
            name = lib.mkOption {
              type = lib.types.str;
              description = "Display name of the theme variant";
            };
            altName = lib.mkOption {
              type = lib.types.str;
              description = "Alternative name used by some programs";
            };
            fileName = lib.mkOption {
              type = lib.types.str;
              description = "Theme file name without extension";
            };
            colors = lib.mkOption {
              type = lib.types.attrsOf lib.types.str;
              description = "Named color palette (bg, fg, accent, etc.)";
            };
            style = lib.mkOption {
              type = lib.types.str;
              description = "Light or dark style variant";
            };
          };
        }
      );
      default = { };
    };

    active = lib.mkOption {
      type = lib.types.str;
      default = "tokyoNightStorm";
    };

    current = lib.mkOption {
      type = lib.types.attrs;
      readOnly = true;
    };
  };

  config = {
    assertions = [
      {
        assertion = config.modules.themes.registry ? ${config.modules.themes.active};
        message = "themes: '${config.modules.themes.active}' not found in registry. Available: ${builtins.concatStringsSep ", " (builtins.attrNames config.modules.themes.registry)}";
      }
    ];

    modules.themes.current = config.modules.themes.registry.${config.modules.themes.active};
  };
}
