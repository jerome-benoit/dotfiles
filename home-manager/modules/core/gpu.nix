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

  hostFile =
    path:
    if builtins.pathExists path then
      lib.trim (lib.fileContents (builtins.fetchurl "file://${path}"))
    else
      "";

  nvidiaDetected = isLinux && builtins.pathExists /sys/module/nvidia;
  detectedNvidiaVersion =
    let
      sysfsVersion = if nvidiaDetected then hostFile "/sys/module/nvidia/version" else "";
    in
    if sysfsVersion != "" then sysfsVersion else cfg.nvidiaDriverVersion;
  nvidiaVersionKnown = detectedNvidiaVersion != null;

  # Exact toolkit driver versions from NVIDIA CUDA Release Notes, Table 3.
  cudaMatrix = [
    {
      minDriver = "610.43.02";
      packages = pkgs.cudaPackages_13_3;
    }
    {
      minDriver = "595.58.03";
      packages = pkgs.cudaPackages_13_2;
    }
    {
      minDriver = "590.48.01";
      packages = pkgs.cudaPackages_13_1;
    }
    {
      minDriver = "580.126.20";
      packages = pkgs.cudaPackages_13_0;
    }
    {
      minDriver = "575.57.08";
      packages = pkgs.cudaPackages_12_9;
    }
    {
      minDriver = "570.124.06";
      packages = pkgs.cudaPackages_12_8;
    }
    {
      minDriver = "560.35.05";
      packages = pkgs.cudaPackages_12_6;
    }
  ];
  selectedCuda =
    if nvidiaVersionKnown then
      lib.findFirst (entry: lib.versionAtLeast detectedNvidiaVersion entry.minDriver) null cudaMatrix
    else
      null;
  minSupportedDriver = (lib.last cudaMatrix).minDriver;
  cudaPkgs = if selectedCuda != null then selectedCuda.packages else pkgs.cudaPackages_12_6;
  cudaProbeStatus = builtins.getEnv "NIX_GPU_CUDA_PROBE_STATUS";
  detectedCudaCapabilities = lib.unique (
    lib.filter (capability: builtins.match "[0-9]+\\.[0-9]+" capability != null) (
      lib.splitString "," (builtins.getEnv "NIX_GPU_CUDA_CAPABILITIES")
    )
  );
  cudaProbeValid =
    cudaProbeStatus == "" || (cudaProbeStatus == "ok" && detectedCudaCapabilities != [ ]);
  cudaCapabilitiesBuilt =
    detectedCudaCapabilities == [ ]
    || lib.all (
      capability: builtins.elem capability cudaPkgs.flags.cudaCapabilities
    ) detectedCudaCapabilities;

  hasAmdgpu = isLinux && builtins.pathExists /sys/module/amdgpu;
  hasIntelGpu =
    isLinux && (builtins.pathExists /sys/module/i915 || builtins.pathExists /sys/module/xe);
  driDirectory = "/dev/dri";
  hasRenderNode =
    isLinux
    && builtins.pathExists driDirectory
    && lib.any (lib.hasPrefix "renderD") (builtins.attrNames (builtins.readDir driDirectory));

  kfdNodesDirectory = "/sys/class/kfd/kfd/topology/nodes";
  kfdNodeNames =
    if isLinux && builtins.pathExists kfdNodesDirectory then
      builtins.attrNames (builtins.readDir kfdNodesDirectory)
    else
      [ ];
  kfdGpuNodes = lib.filter (
    node:
    let
      gpuId = hostFile "${kfdNodesDirectory}/${node}/gpu_id";
    in
    gpuId != "" && gpuId != "0"
  ) kfdNodeNames;
  kfdProperty =
    node: name:
    let
      prefix = "${name} ";
      line = lib.findFirst (candidate: lib.hasPrefix prefix candidate) "" (
        lib.splitString "\n" (hostFile "${kfdNodesDirectory}/${node}/properties")
      );
    in
    lib.removePrefix prefix line;
  # KFD encodes GFX targets as major * 10000 + minor * 100 + stepping;
  # hexadecimal minor/stepping values preserve targets such as gfx90a.
  decodeGfxTarget =
    encoded:
    if encoded == "" || builtins.match "[0-9]+" encoded == null then
      null
    else
      let
        value = lib.toInt encoded;
        major = builtins.div value 10000;
        minor = lib.mod (builtins.div value 100) 100;
        stepping = lib.mod value 100;
      in
      "gfx${toString major}${lib.toLower (lib.toHexString minor)}${lib.toLower (lib.toHexString stepping)}";
  detectedGfxTargets = lib.unique (
    lib.filter (target: target != null) (
      map (node: decodeGfxTarget (kfdProperty node "gfx_target_version")) kfdGpuNodes
    )
  );
  supportedRocmTargets = lib.filter (
    target: builtins.elem target pkgs.rocmPackages.clr.gpuTargets
  ) detectedGfxTargets;

  inferredVendor =
    if isDarwin then
      "apple"
    else if nvidiaDetected then
      "nvidia"
    else if hasAmdgpu then
      "amd"
    else if hasIntelGpu then
      "intel"
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
    && (lib.warnIf (nvidiaVersionKnown && selectedCuda == null)
      "modules.core.gpu: NVIDIA driver ${toString detectedNvidiaVersion} < ${minSupportedDriver} — CUDA disabled"
      (selectedCuda != null)
    )
    && (lib.warnIf (!cudaProbeValid)
      "modules.core.gpu: NVIDIA compute capability probe ${cudaProbeStatus}; CUDA disabled"
      cudaProbeValid
    )
    && (lib.warnIf (!cudaCapabilitiesBuilt)
      "modules.core.gpu: detected CUDA capabilities ${builtins.toJSON detectedCudaCapabilities} are not built by the selected CUDA package set"
      cudaCapabilitiesBuilt
    );
  rocmEnable =
    cfg.enable
    && isLinux
    && effectiveVendor == "amd"
    && builtins.pathExists /dev/kfd
    && (lib.warnIf (supportedRocmTargets == [ ])
      "modules.core.gpu: no detected AMD GFX target is supported by the selected ROCm package set: ${builtins.toJSON detectedGfxTargets}"
      (supportedRocmTargets != [ ])
    );
  vulkanEnable =
    cfg.enable
    && isLinux
    && hasRenderNode
    && (
      effectiveVendor == "intel"
      || (effectiveVendor == "amd" && !rocmEnable)
      || (effectiveVendor == "nvidia" && !cudaEnable)
    );
  acceleration =
    if cudaEnable then
      "cuda"
    else if rocmEnable then
      "rocm"
    else if vulkanEnable then
      "vulkan"
    else
      "default";
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
        "intel"
        "apple"
        "none"
      ];
      default = "auto";
      description = ''
        GPU vendor selector. "auto" infers from the host:
        - Darwin → "apple" (native Metal/CoreML package defaults)
        - Linux with the NVIDIA kernel module → "nvidia"
        - Linux with the AMDGPU kernel module → "amd"
        - Linux with the i915 or xe kernel module → "intel"
        - Otherwise → "none"
      '';
    };

    nvidiaDriverVersion = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "595.80";
      description = ''
        Fallback NVIDIA driver version when /sys/module/nvidia/version is unavailable
        during impure evaluation. It must match the running driver. When sysfs is
        unavailable, null disables CUDA and the Generic Linux NVIDIA target.
      '';
    };

    acceleration = lib.mkOption {
      type = lib.types.enum [
        "cuda"
        "rocm"
        "vulkan"
        "default"
      ];
      readOnly = true;
      default = acceleration;
      description = "Package acceleration mode selected from the detected host capabilities.";
    };

    cudaCapabilities = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      readOnly = true;
      default = detectedCudaCapabilities;
      description = "CUDA compute capabilities reported by the impure host probe.";
    };

    rocmTargets = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      readOnly = true;
      default = supportedRocmTargets;
      description = "Detected AMD GFX targets supported by the selected ROCm package set.";
    };

    cudaPackages = lib.mkOption {
      type = lib.types.attrs;
      readOnly = true;
      visible = false;
      default = cudaPkgs;
      description = "CUDA package set selected for this host.";
    };
  };

  config =
    lib.mkIf
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
      };
}
