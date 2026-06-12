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

  detectedNvidiaVersion =
    if isLinux && builtins.pathExists /proc/driver/nvidia/version then
      let
        raw = builtins.readFile /proc/driver/nvidia/version;
        match = builtins.match "NVRM version:[^\n]*[[:space:]]([0-9]+\\.[0-9]+(\\.[0-9]+)?)[^[:space:]\n]*[[:space:]].*" raw;
      in
      if match != null then builtins.head match else null
    else
      null;

  driverMajor =
    if detectedNvidiaVersion != null then
      lib.toInt (lib.head (lib.splitString "." detectedNvidiaVersion))
    else
      0;

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
    else if detectedNvidiaVersion != null then
      "nvidia"
    else if hasAmdgpu then
      "amd"
    else
      "none";

  effectiveVendor = if cfg.vendor == "auto" then inferredVendor else cfg.vendor;
  cudaEnable =
    cfg.enable
    && isLinux
    && effectiveVendor == "nvidia"
    && detectedNvidiaVersion != null
    && (lib.warnIf (driverMajor < 555)
      "modules.core.gpu: NVIDIA driver ${toString detectedNvidiaVersion} < 555 — CUDA disabled (cudaPackages_12_6 minimum)"
      (driverMajor >= 555)
    );
  rocmEnable = cfg.enable && isLinux && effectiveVendor == "amd" && hasAmdgpu;

  nvidiaArch = if pkgs.stdenv.hostPlatform.isx86_64 then "x86_64" else "aarch64";
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
        - Linux with /proc/driver/nvidia → "nvidia"
        - Linux with /sys/module/amdgpu → "amd"
        - Otherwise → "none"
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

    cudaLibraryPath = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = ''
        Runtime LD_LIBRARY_PATH addition for binaries that dlopen CUDA libs
        (e.g. ctranslate2 in faster-whisper). Empty when CUDA disabled.
      '';
    };
  };

  config = lib.mkIf cudaEnable {
    targets.genericLinux.gpu.nvidia = lib.mkIf (!isNixOS) {
      enable = true;
      version = detectedNvidiaVersion;
      sha256 = nvidiaDriverSri;
    };
    modules.core.gpu.cudaLibraryPath = lib.makeLibraryPath [
      cudaPkgs.cuda_cudart
      cudaPkgs.libcublas
      cudaPkgs.cudnn
    ];
  };
}
