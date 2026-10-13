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
  probedNvidiaVersion = builtins.getEnv "NIX_GPU_NVIDIA_DRIVER_VERSION";
  detectedNvidiaVersion =
    if probedNvidiaVersion != "" then probedNvidiaVersion else cfg.nvidiaDriverVersion;
  nvidiaVersionKnown = detectedNvidiaVersion != null;

  # Exact toolkit driver versions from NVIDIA CUDA Release Notes, Table 3;
  # the 13.4 entry uses its R615 branch floor, listed in Table 2.
  cudaMatrix = [
    {
      minDriver = "615.71.09";
      name = "cudaPackages_13_4";
    }
    {
      minDriver = "610.43.02";
      name = "cudaPackages_13_3";
    }
    {
      minDriver = "595.71.05";
      name = "cudaPackages_13_2";
    }
    {
      minDriver = "590.48.01";
      name = "cudaPackages_13_1";
    }
    {
      minDriver = "580.126.20";
      name = "cudaPackages_13_0";
    }
    {
      minDriver = "575.57.08";
      name = "cudaPackages_12_9";
    }
    {
      minDriver = "570.211.01";
      name = "cudaPackages_12_8";
    }
    {
      minDriver = "560.35.05";
      name = "cudaPackages_12_6";
    }
  ];
  cudaProbeStatus = builtins.getEnv "NIX_GPU_CUDA_PROBE_STATUS";
  rawCudaCapabilities = builtins.getEnv "NIX_GPU_CUDA_CAPABILITIES";
  cudaCapabilityRows = lib.splitString "," rawCudaCapabilities;
  cudaProbeValid =
    cudaProbeStatus == "ok"
    && rawCudaCapabilities != ""
    && lib.all (capability: builtins.match "[0-9]+\\.[0-9]+" capability != null) cudaCapabilityRows;
  detectedCudaCapabilities = if cudaProbeValid then lib.unique cudaCapabilityRows else [ ];
  requiredCudaCapabilities = lib.unique (
    (pkgs.config.cudaCapabilities or [ ]) ++ detectedCudaCapabilities
  );
  cudaMetadataPkgs = pkgs.extend (
    _: previous: {
      config = previous.config // {
        cudaCapabilities = [ ];
      };
    }
  );
  driverCompatibleCuda =
    if nvidiaVersionKnown then
      lib.filter (entry: lib.versionAtLeast detectedNvidiaVersion entry.minDriver) cudaMatrix
    else
      [ ];
  selectedCuda =
    if cudaProbeValid then
      lib.findFirst (
        entry:
        lib.all (
          capability:
          builtins.elem capability cudaMetadataPkgs.${entry.name}.backendStdenv.supportedCudaCapabilities
        ) requiredCudaCapabilities
      ) null driverCompatibleCuda
    else
      null;
  minSupportedDriver = (lib.last cudaMatrix).minDriver;
  cudaPkgs =
    if selectedCuda == null then
      cudaMetadataPkgs.cudaPackages_12_6
    else
      let
        stock = pkgs.${selectedCuda.name};
        stockCoversHost = lib.all (
          capability: builtins.elem capability stock.flags.cudaCapabilities
        ) detectedCudaCapabilities;
      in
      if stockCoversHost then
        stock
      else
        (pkgs.extend (
          _: previous: {
            config = previous.config // {
              cudaCapabilities = requiredCudaCapabilities;
            };
          }
        )).${selectedCuda.name};

  hasAmdgpu = isLinux && builtins.pathExists /sys/module/amdgpu;
  hasIntelGpu =
    isLinux && (builtins.pathExists /sys/module/i915 || builtins.pathExists /sys/module/xe);
  driDirectory = "/dev/dri";
  hasRenderNode =
    isLinux
    && builtins.pathExists driDirectory
    && lib.any (lib.hasPrefix "renderD") (builtins.attrNames (builtins.readDir driDirectory));

  detectedGfxTargets = lib.unique (
    lib.filter (target: builtins.match "gfx[0-9a-f]+" target != null) (
      lib.splitString "," (builtins.getEnv "NIX_GPU_ROCM_TARGETS")
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
    && (lib.warnIf (driverCompatibleCuda == [ ])
      "modules.core.gpu: NVIDIA driver ${toString detectedNvidiaVersion} < ${minSupportedDriver} — CUDA disabled"
      (driverCompatibleCuda != [ ])
    )
    && (lib.warnIf (!cudaProbeValid) "modules.core.gpu: NVIDIA compute capability probe ${
      if cudaProbeStatus == "" then "missing" else cudaProbeStatus
    } is not valid; CUDA disabled" cudaProbeValid)
    && (lib.warnIf (selectedCuda == null)
      "modules.core.gpu: no driver-compatible CUDA toolkit supports capabilities ${builtins.toJSON requiredCudaCapabilities}"
      (selectedCuda != null)
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
        Fallback NVIDIA driver version when the native host probe cannot read it.
        It must match the running driver. Null disables the Generic Linux NVIDIA
        target when no version is probed. CUDA also requires a valid capability probe.
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
