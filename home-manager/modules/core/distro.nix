{
  config,
  lib,
  pkgs,
  ...
}:

let
  constants = config.modules.core.constants;
  supportedDistros = builtins.attrValues constants.distros;
  distroIdsEnumType = lib.types.enum supportedDistros;

  detectDistro =
    if !pkgs.stdenv.isLinux then
      null
    else if !builtins.pathExists /etc/os-release then
      null
    else
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
      if distro != null && builtins.elem distro supportedDistros then distro else null;

  detectDarwin = if pkgs.stdenv.isDarwin then constants.systems.darwin.name else null;

  distroId = if detectDistro != null then detectDistro else detectDarwin;
in
{
  options.modules.core.distro = {
    id = lib.mkOption {
      type = lib.types.nullOr (
        lib.types.either distroIdsEnumType (lib.types.enum [ constants.systems.darwin.name ])
      );
      default = distroId;
      description = "The OS distribution ID";
      readOnly = true;
    };

    ids = lib.mkOption {
      type = lib.types.attrsOf distroIdsEnumType;
      default = constants.distros;
      description = "Supported GNU/Linux distribution IDs";
      readOnly = true;
    };
  };

  config = {
    warnings =
      lib.optional (pkgs.stdenv.isLinux && distroId == null && builtins.pathExists /etc/os-release)
        "distro: Detected unsupported Linux distribution. Supported: ${lib.concatStringsSep ", " supportedDistros}";
  };
}
