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
              description = "Theme family identifier (e.g. tokyonight, catppuccin)";
            };
            name = lib.mkOption {
              type = lib.types.str;
              description = "Theme slug in kebab-case (e.g. tokyo-night-storm)";
            };
            altName = lib.mkOption {
              type = lib.types.str;
              description = "Human-readable display name (e.g. TokyoNight Storm)";
            };
            fileName = lib.mkOption {
              type = lib.types.str;
              description = "Theme file name without extension (e.g. tokyo_night_storm)";
            };
            colors = lib.mkOption {
              type = lib.types.attrsOf lib.types.str;
              description = "Hex color palette keyed by role (e.g. bg, fg, blue)";
            };
            style = lib.mkOption {
              type = lib.types.str;
              description = "Variant within the family (e.g. storm, latte, mocha)";
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
