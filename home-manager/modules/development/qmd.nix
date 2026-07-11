{
  config,
  lib,
  pkgs,
  inputs,
  self,
  ...
}:
let
  cfg = config.modules.development.qmd;
  system = pkgs.stdenv.hostPlatform.system;

  baseQmdPackage = inputs.qmd.packages.${system}.default or null;

  qmdPackage =
    if baseQmdPackage != null then
      baseQmdPackage.overrideAttrs (
        previousAttrs:
        let
          linuxLibPath = lib.optionalString pkgs.stdenv.hostPlatform.isLinux "${pkgs.stdenv.cc.libc.out}/lib:${pkgs.stdenv.cc.cc.lib}/lib:";
          envFlags = lib.concatStringsSep " " (
            [
              ''--set-default LLAMA_LOG_LEVEL "error"''
              ''--set-default GGML_LOG_LEVEL "error"''
              ''--set-default GGML_BACKEND_SILENT "1"''
            ]
            ++ lib.optional pkgs.stdenv.hostPlatform.isDarwin ''--set-default GGML_METAL_NO_RESIDENCY "1"''
          );
        in
        {
          patches = (previousAttrs.patches or [ ]) ++ [
            # tobi/qmd#574
            (self + "/patches/qmd/fix-nixos-llama-build.patch")
          ];
          # tobi/qmd#722 (skills) + #723 (env vars) + #574 (linux libs)
          installPhase =
            builtins.replaceStrings
              [
                "cp package.json $out/lib/qmd/"
                "--set LD_LIBRARY_PATH \""
              ]
              [
                "cp package.json $out/lib/qmd/\ncp -r skills $out/lib/qmd/"
                "${envFlags} --set LD_LIBRARY_PATH \"${linuxLibPath}"
              ]
              previousAttrs.installPhase;
        }
      )
    else
      null;
in
{
  options.modules.development.qmd = {
    enable = lib.mkEnableOption "qmd configuration";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = qmdPackage;
      defaultText = lib.literalExpression "inputs.qmd.packages.\${system}.default";
      description = "QMD CLI package";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;

    warnings = lib.optional (cfg.package == null) "qmd: package not available for system ${system}";
  };
}
