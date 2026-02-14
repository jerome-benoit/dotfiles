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

  options.modules.themes = lib.mkOption {
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
    description = "Available themes configuration";
  };
}
