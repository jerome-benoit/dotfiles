{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.development.caveman;
  supported = builtins.elem pkgs.stdenv.hostPlatform.system [
    "aarch64-darwin"
    "aarch64-linux"
    "x86_64-linux"
  ];
  cavemanPackage =
    if supported then
      pkgs.callPackage ./caveman/package.nix {
        src = inputs.caveman;
        registrationProfile = config.home.profileDirectory;
      }
    else
      null;
  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "caveman: no complete runtime available for system ${pkgs.stdenv.hostPlatform.system}";
    }
  ];
in
{
  options.modules.development.caveman = {
    enable = lib.mkEnableOption "Caveman CLI and complete local runtime";
    package = config.modules.core.lib.mkOptionalPackageOption {
      default = cavemanPackage;
      defaultText = lib.literalExpression ''
        pkgs.callPackage ./caveman/package.nix {
          src = inputs.caveman;
          registrationProfile = config.home.profileDirectory;
        }
      '';
      description = "Caveman CLI and companion executables (null on unsupported systems)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
