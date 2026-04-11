{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.core.gpu;
  isLinux = pkgs.stdenv.hostPlatform.isLinux;
in
{
  options.modules.core.gpu = {
    enable = lib.mkEnableOption "GPU support for non-NixOS Linux";

    nvidia = {
      enable = lib.mkEnableOption "NVIDIA proprietary driver support";

      version = lib.mkOption {
        type = lib.types.str;
        description = ''
          NVIDIA driver version matching the host kernel module.
          Detect with: cat /proc/driver/nvidia/version
        '';
        example = "550.163.01";
      };

      sha256 = lib.mkOption {
        type = lib.types.str;
        description = ''
          SRI hash of the NVIDIA driver installer.
          Compute with: nix store prefetch-file <url>
        '';
        example = "sha256-74FJ9bNFlUYBRen7+C08ku5Gc1uFYGeqlIh7l1yrmi4=";
      };
    };
  };

  config = lib.mkIf (cfg.enable && isLinux) {
    targets.genericLinux.gpu.nvidia = lib.mkIf cfg.nvidia.enable {
      enable = true;
      inherit (cfg.nvidia) version sha256;
    };
  };
}
