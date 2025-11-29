{
  config,
  lib,
  pkgs,
  ...
}:

let
  supportedDistros = [
    "almalinux"
    "debian"
    "fedora"
    "ubuntu"
  ];

  distroIds = lib.genAttrs supportedDistros (id: id);

  distroIdsEnumType = lib.types.enum supportedDistros;

  distroId =
    if pkgs.stdenv.isLinux && builtins.pathExists /etc/os-release then
      let
        osRelease = builtins.readFile /etc/os-release;
        lines = lib.splitString "\n" osRelease;
        idLine = lib.findFirst (lib.hasPrefix "ID=") null lines;
        distro =
          if idLine != null then
            let
              rawId = lib.removePrefix "ID=" idLine;
            in
            lib.removeSuffix "\"" (lib.removePrefix "\"" rawId)
          else
            null;
      in
      if builtins.elem distro supportedDistros then distro else null
    else
      null;
in
{
  options.modules.core.distro = {
    id = lib.mkOption {
      type = lib.types.nullOr distroIdsEnumType;
      default = distroId;
      description = "The detected GNU/Linux distribution";
      readOnly = true;
    };

    ids = lib.mkOption {
      type = lib.types.attrsOf distroIdsEnumType;
      default = distroIds;
      description = "Supported distribution IDs";
      readOnly = true;
    };
  };
}
