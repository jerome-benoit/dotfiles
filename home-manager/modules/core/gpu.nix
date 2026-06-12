{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.core.gpu;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  isLinux = pkgs.stdenv.hostPlatform.isLinux;
  isNixOS = builtins.pathExists /etc/NIXOS;

  nvidiaDetected = isLinux && builtins.pathExists /sys/module/nvidia;

  nvidiaVersionPattern = "[0-9]+\\.[0-9]+(\\.[0-9]+)?";

  nvidiaFirmwareRoots = [
    /usr/lib/firmware/nvidia
    /lib/firmware/nvidia
  ];

  nvidiaFirmwareVersions = lib.unique (
    lib.concatMap (
      root:
      if builtins.pathExists root then
        builtins.attrNames (
          lib.filterAttrs (
            name: type: type == "directory" && builtins.match nvidiaVersionPattern name != null
          ) (builtins.readDir root)
        )
      else
        [ ]
    ) nvidiaFirmwareRoots
  );

  detectedNvidiaVersion =
    if cfg.nvidiaDriverVersion != null then
      cfg.nvidiaDriverVersion
    else if builtins.length nvidiaFirmwareVersions == 1 then
      builtins.head nvidiaFirmwareVersions
    else
      null;

  driverMajor =
    if detectedNvidiaVersion != null then
      lib.toInt (lib.head (lib.splitString "." detectedNvidiaVersion))
    else
      0;

  nvidiaVersionKnown = detectedNvidiaVersion != null;
  cudaSupported = nvidiaVersionKnown && driverMajor >= 560;

  cudaPkgs =
    if driverMajor >= 580 then
      pkgs.cudaPackages_13_0
    else if driverMajor >= 570 then
      pkgs.cudaPackages_12_8
    else
      pkgs.cudaPackages_12_6;

  hasAmdgpu = isLinux && builtins.pathExists /sys/module/amdgpu;

  inferredVendor =
    if isDarwin then
      "apple"
    else if nvidiaDetected then
      "nvidia"
    else if hasAmdgpu then
      "amd"
    else
      "none";

  effectiveVendor = if cfg.vendor == "auto" then inferredVendor else cfg.vendor;
  nvidiaArch =
    if pkgs.stdenv.hostPlatform.isx86_64 then
      "x86_64"
    else if pkgs.stdenv.hostPlatform.isAarch64 then
      "aarch64"
    else
      null;
  cudaEnable =
    cfg.enable
    && isLinux
    && effectiveVendor == "nvidia"
    && nvidiaDetected
    && nvidiaArch != null
    && (lib.warnIf (
      !nvidiaVersionKnown
    ) "modules.core.gpu: NVIDIA driver version unknown; CUDA disabled" nvidiaVersionKnown)
    && (lib.warnIf (!cudaSupported)
      "modules.core.gpu: NVIDIA driver ${toString detectedNvidiaVersion} < 560 — CUDA disabled (cudaPackages_12_6 minimum)"
      cudaSupported
    );
  rocmEnable = cfg.enable && isLinux && effectiveVendor == "amd" && hasAmdgpu;
  nvidiaDriverSri =
    let
      url = "https://download.nvidia.com/XFree86/Linux-${nvidiaArch}/${detectedNvidiaVersion}/NVIDIA-Linux-${nvidiaArch}-${detectedNvidiaVersion}.run";
      hash = builtins.hashFile "sha256" (builtins.fetchurl url);
    in
    builtins.convertHash {
      inherit hash;
      toHashFormat = "sri";
      hashAlgo = "sha256";
    };
in
{
  options.modules.core.gpu = {
    enable = lib.mkEnableOption "GPU acceleration integration";

    vendor = lib.mkOption {
      type = lib.types.enum [
        "auto"
        "nvidia"
        "amd"
        "apple"
        "none"
      ];
      default = "auto";
      description = ''
        GPU vendor selector. "auto" infers from platform:
        - Darwin → "apple" (Metal/CoreML implicit)
        - Linux with /sys/module/nvidia → "nvidia"
        - Linux with /sys/module/amdgpu → "amd"
        - Otherwise → "none"
      '';
    };

    nvidiaDriverVersion = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "595.80";
      description = ''
        Explicit NVIDIA driver version for hosts where automatic firmware-directory
        detection cannot infer exactly one loaded driver version. Leave null to use
        automatic detection.
      '';
    };

    cudaEnable = lib.mkOption {
      type = lib.types.bool;
      readOnly = true;
      default = cudaEnable;
      description = "Whether CUDA acceleration is active for this host.";
    };

    rocmEnable = lib.mkOption {
      type = lib.types.bool;
      readOnly = true;
      default = rocmEnable;
      description = "Whether ROCm acceleration is active for this host.";
    };

    cudaPackages = lib.mkOption {
      type = lib.types.attrs;
      readOnly = true;
      visible = false;
      default = cudaPkgs;
      description = "CUDA package set selected for this host.";
    };

    cudaLibraryPath = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = ''
        Runtime LD_LIBRARY_PATH addition for binaries that dlopen CUDA libs
        (e.g. ctranslate2 in faster-whisper). Empty when CUDA disabled.
      '';
    };
  };

  config = lib.mkMerge [
    (lib.mkIf
      (
        cfg.enable
        && isLinux
        && effectiveVendor == "nvidia"
        && nvidiaDetected
        && nvidiaArch != null
        && !isNixOS
        && nvidiaVersionKnown
      )
      {
        targets.genericLinux.gpu.nvidia = {
          enable = true;
          version = detectedNvidiaVersion;
          sha256 = nvidiaDriverSri;
        };
      }
    )

    (lib.mkIf cudaEnable {
      modules.core.gpu.cudaLibraryPath = lib.makeLibraryPath [
        cudaPkgs.cuda_cudart
        cudaPkgs.libcublas
        cudaPkgs.cudnn
      ];
    })
  ];
}
