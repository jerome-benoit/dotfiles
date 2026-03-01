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
            family = lib.mkOption { type = lib.types.str; };
            name = lib.mkOption { type = lib.types.str; };
            altName = lib.mkOption { type = lib.types.str; };
            fileName = lib.mkOption { type = lib.types.str; };
            colors = lib.mkOption { type = lib.types.attrsOf lib.types.str; };
            style = lib.mkOption { type = lib.types.str; };
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
