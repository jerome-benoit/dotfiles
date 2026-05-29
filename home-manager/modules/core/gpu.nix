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

  detectedNvidiaVersion =
    if isLinux && builtins.pathExists /proc/driver/nvidia/version then
      let
        raw = builtins.readFile /proc/driver/nvidia/version;
        match = builtins.match "NVRM version:.*Module[[:space:]]+([0-9.]+)[^\n]*\n.*" raw;
      in
      if match != null then builtins.head match else null
    else
      null;

  inferredVendor =
    if isDarwin then
      "apple"
    else if detectedNvidiaVersion != null then
      "nvidia"
    else
      "none";

  effectiveVendor = if cfg.vendor == "auto" then inferredVendor else cfg.vendor;
  cudaEnable = cfg.enable && isLinux && effectiveVendor == "nvidia" && detectedNvidiaVersion != null;

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
        "apple"
        "none"
      ];
      default = "auto";
      description = ''
        GPU vendor selector. "auto" infers from platform:
        - Darwin → "apple" (Metal/CoreML implicit)
        - Linux with /proc/driver/nvidia → "nvidia"
        - Otherwise → "none"
      '';
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
    targets.genericLinux.gpu.nvidia = {
      enable = true;
      version = detectedNvidiaVersion;
      sha256 = nvidiaDriverSri;
    };
    modules.core.gpu.cudaLibraryPath = lib.makeLibraryPath [
      pkgs.cudaPackages.libcublas
      pkgs.cudaPackages.cudnn
    ];
  };
}
