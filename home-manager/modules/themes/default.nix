{
  lib,
  ...
}:

{
  imports = [
    ./tokyo-night.nix
    ./tokyo-night-storm.nix
    ./tokyo-night-light.nix
  ];

  options.modules.themes = {
    registry = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            name = lib.mkOption {
              type = lib.types.str;
              description = "Theme name";
            };
            altName = lib.mkOption {
              type = lib.types.str;
              description = "Alternative theme name";
            };
            fileName = lib.mkOption {
              type = lib.types.str;
              description = "Theme file name";
            };
            colors = lib.mkOption {
              type = lib.types.attrsOf lib.types.str;
              description = "Theme color palette";
            };
          };
        }
      );
      default = { };
      description = "Available themes registry";
    };

    active = lib.mkOption {
      type = lib.types.str;
      default = "tokyoNightStorm";
      description = "Active theme key (must exist in registry)";
    };

    current = lib.mkOption {
      type = lib.types.attrs;
      readOnly = true;
      description = "Currently active theme (derived from registry[active])";
    };
  };

  config = {
    assertions = [
      {
        assertion = config.modules.themes.registry ? ${config.modules.themes.active};
        message = "modules.themes.active '${config.modules.themes.active}' not found in registry. Available: ${builtins.concatStringsSep ", " (builtins.attrNames config.modules.themes.registry)}";
      }
    ];

    modules.themes.current = config.modules.themes.registry.${config.modules.themes.active};
  };
}
