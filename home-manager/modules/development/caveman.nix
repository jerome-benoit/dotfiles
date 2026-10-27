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
    home = {
      packages = optionalPackages.packages;
      sessionVariables.CAVEMAN_MODE = lib.mkDefault "compress";
      activation.cavemanBlocksProfile = lib.mkIf (cfg.package != null) (
        let
          profileBinary = "${config.home.profileDirectory}/bin/caveman-blocks";
          replaceHook = pkgs.writeShellScript "caveman-blocks-profile-migration" ''
            set -eu
            export PATH=${lib.makeBinPath [ pkgs.coreutils ]}
            [[ -L caveman-blocks && "$(readlink -- caveman-blocks)" == "$2" ]] || exit 0
            temporary=$(mktemp -d .caveman-blocks-profile.XXXXXXXXXX)
            trap 'rm -f -- "$temporary/hook"; rmdir -- "$temporary"' EXIT
            ln -s -- "$1" "$temporary/hook"
            mv -T -- "$temporary/hook" caveman-blocks
          '';
        in
        lib.hm.dag.entryAfter [ "installPackages" ] ''
          (
            unset CDPATH
            # Reject missing, foreign-owned or symlinked parents without creating
            # anything. Walk relative to each checked directory, not through HOME.
            for directory in ${lib.escapeShellArg config.home.homeDirectory} .local share caveman-blocks bin; do
              [[ -d "$directory" && ! -L "$directory" && -O "$directory" ]] || exit 0
              cd -- "$directory"
            done
            [[ -L caveman-blocks ]] || exit 0
            [[ "$(${pkgs.coreutils}/bin/stat -c %u -- caveman-blocks)" == "$EUID" ]] || exit 0
            previousTarget=$(${pkgs.coreutils}/bin/readlink -- caveman-blocks)
            legacyPattern='^${builtins.storeDir}/[0-9abcdfghijklmnpqrsvwxyz]{32}-caveman-blocks-[0-9][^/]*/bin/caveman-blocks$'
            [[ "$previousTarget" =~ $legacyPattern ]] || exit 0
            # A collected legacy store path is still recognizable. Replace it only
            # when the selected profile already supplies an executable replacement.
            [[ -x ${lib.escapeShellArg profileBinary} ]] || exit 0
            verboseEcho ${lib.escapeShellArg "caveman: migrating existing Blocks hook to ${profileBinary}"}
            run ${replaceHook} ${lib.escapeShellArg profileBinary} "$previousTarget"
          )
        ''
      );
    };

    warnings = optionalPackages.warnings;

    # Existing Nix-installed hooks must follow profile switches too. Do not run
    # `hooks install`: that also rewrites agent configuration and creates hooks.

  };
}
