{
  pkgs,
  nixpkgs,
  home-manager,
}:
let
  linuxPkgs = import nixpkgs {
    system = "x86_64-linux";
    config.allowUnfree = true;
  };
  lib = pkgs.lib;
  evaluate =
    {
      driver ? "615.71.09",
      status ? "ok",
      capabilities ? "8.9",
      configuredCapabilities ? [ ],
      modules ? [ "nvidia" ],
      render ? false,
      kfd ? false,
      targets ? "",
      nixos ? false,
    }:
    let
      fixturePkgs =
        if configuredCapabilities == [ ] then
          linuxPkgs
        else
          linuxPkgs.extend (
            _: previous: {
              config = previous.config // {
                cudaCapabilities = configuredCapabilities;
              };
            }
          );
      environment = {
        NIX_GPU_NVIDIA_DRIVER_VERSION = driver;
        NIX_GPU_CUDA_PROBE_STATUS = status;
        NIX_GPU_CUDA_CAPABILITIES = capabilities;
        NIX_GPU_ROCM_TARGETS = targets;
      };
      shadow = builtins // {
        getEnv = name: environment.${name} or "";
        pathExists =
          path:
          let
            p = toString path;
          in
          if p == "/etc/NIXOS" then
            nixos
          else if p == "/dev/dri" then
            render
          else if p == "/dev/kfd" then
            kfd
          else
            builtins.elem p (map (name: "/sys/module/${name}") modules);
        readDir = path: if toString path == "/dev/dri" then { renderD128 = "unknown"; } else { };
        fetchurl = _: throw "GPU policy must consume the native snapshot, not fetch host files";
      };
      result = lib.evalModules {
        specialArgs.pkgs = fixturePkgs;
        modules = [
          (builtins.scopedImport { builtins = shadow; } ../home-manager/modules/core/gpu.nix)
          {
            options.targets.genericLinux.gpu.nvidia = lib.mkOption {
              type = lib.types.attrs;
              default = { };
            };
            config.modules.core.gpu.enable = true;
          }
        ];
      };
    in
    result.config.modules.core.gpu;
  modern = evaluate { };
  legacy = evaluate {
    driver = "580.126.20";
    capabilities = "6.1,7.0,8.9";
  };
  configuredLegacy = evaluate {
    configuredCapabilities = [ "6.1" ];
  };
  rocm = evaluate {
    modules = [ "amdgpu" ];
    kfd = true;
    targets = "gfx90a,gfx9999";
  };
  consumerCudaArchitectures =
    gpu:
    let
      package = gpu.cudaPackages.pkgs.llama-cpp.override { cudaSupport = true; };
      flag = lib.findFirst (lib.hasPrefix "-DCMAKE_CUDA_ARCHITECTURES") "" package.cmakeFlags;
    in
    lib.splitString ";" (lib.last (lib.splitString "=" flag));
  hostConfiguration =
    nixos:
    let
      shadow = builtins // {
        pathExists =
          path:
          let
            p = toString path;
          in
          nixos && (p == "/etc/NIXOS" || p == "/sys/module/nvidia");
        getEnv =
          name:
          {
            NIX_GPU_NVIDIA_DRIVER_VERSION = "615.71.09";
            NIX_GPU_CUDA_PROBE_STATUS = "ok";
            NIX_GPU_CUDA_CAPABILITIES = "8.9";
          }
          .${name} or "";
        fetchurl = _: throw "NixOS must not fetch a non-NixOS NVIDIA driver";
      };
      actualHome = builtins.scopedImport { builtins = shadow; } ../home-manager/home.nix {
        inherit lib;
        pkgs = linuxPkgs;
        config = { };
        profile = "desktop";
        username = "gpu-check";
      };
    in
    (home-manager.lib.homeManagerConfiguration {
      pkgs = linuxPkgs;
      modules = [
        (builtins.scopedImport { builtins = shadow; } ../home-manager/modules/core/gpu.nix)
        {
          inherit (actualHome) home targets;
          modules.core.gpu.enable = true;
        }
      ];
    }).config;
  nixosConfig = hostConfiguration true;
  genericConfig = hostConfiguration false;
  check = label: condition: lib.assertMsg condition "GPU regression: ${label}";
in
assert lib.all (condition: condition) [
  (check "modern GPU uses CUDA 13.4" (
    modern.acceleration == "cuda" && modern.cudaPackages.cudaMajorMinorVersion == "13.4"
  ))
  (check "mixed legacy and modern GPUs retain CUDA" (
    legacy.acceleration == "cuda"
    && legacy.cudaPackages.cudaMajorMinorVersion == "12.9"
    && lib.all (capability: builtins.elem capability legacy.cudaPackages.flags.cudaCapabilities) [
      "6.1"
      "7.0"
      "8.9"
    ]
  ))
  (check "explicit legacy targets do not fail on a newer toolkit" (
    configuredLegacy.acceleration == "cuda"
    && configuredLegacy.cudaPackages.cudaMajorMinorVersion == "12.9"
    && builtins.elem "6.1" configuredLegacy.cudaPackages.flags.cudaCapabilities
    && builtins.elem "8.9" configuredLegacy.cudaPackages.flags.cudaCapabilities
  ))
  (check "nested CUDA consumers build every legacy target" (
    lib.all (architecture: builtins.elem architecture (consumerCudaArchitectures legacy)) [
      "61"
      "70"
      "89"
    ]
    && lib.all (architecture: builtins.elem architecture (consumerCudaArchitectures configuredLegacy)) [
      "61"
      "89"
    ]
  ))
  (check "CUDA 12.8 update boundary" (
    (evaluate { driver = "570.211.00"; }).cudaPackages.cudaMajorMinorVersion == "12.6"
    && (evaluate { driver = "570.211.01"; }).cudaPackages.cudaMajorMinorVersion == "12.8"
  ))
  (check "CUDA 13.2 update boundary" (
    (evaluate { driver = "595.71.04"; }).cudaPackages.cudaMajorMinorVersion == "13.1"
    && (evaluate { driver = "595.71.05"; }).cudaPackages.cudaMajorMinorVersion == "13.2"
  ))
  (check "old driver falls back to Vulkan" (
    (evaluate {
      driver = "560.35.04";
      render = true;
    }).acceleration == "vulkan"
  ))
  (check "unsupported hardware fails closed" (
    (evaluate { capabilities = "99.0"; }).acceleration == "default"
  ))
  (check "unsupported explicit target has a safe fallback scope" (
    let
      gpu = evaluate { configuredCapabilities = [ "99.0" ]; };
    in
    gpu.acceleration == "default" && !(builtins.elem "99.0" gpu.cudaPackages.flags.cudaCapabilities)
  ))
  (check "only complete successful capability snapshots enable CUDA" (
    lib.all (snapshot: (evaluate snapshot).acceleration == "default") [
      {
        status = "";
        capabilities = "";
      }
      { status = ""; }
      { status = "failed"; }
      { status = "unavailable"; }
      { status = "unknown"; }
      { capabilities = ""; }
      { capabilities = "8.9,bad"; }
      { capabilities = "8.9,"; }
    ]
  ))
  (check "unprobed NVIDIA can still use Vulkan" (
    (evaluate {
      status = "";
      render = true;
    }).acceleration == "vulkan"
  ))
  (check "AMD snapshot preserves supported hexadecimal targets" (
    rocm.acceleration == "rocm" && rocm.rocmTargets == [ "gfx90a" ]
  ))
  (check "AMD without KFD falls back to Vulkan" (
    (evaluate {
      modules = [ "amdgpu" ];
      targets = "gfx90a";
      render = true;
    }).acceleration == "vulkan"
  ))
  (check "Intel render node selects Vulkan" (
    (evaluate {
      modules = [ "xe" ];
      render = true;
    }).acceleration == "vulkan"
    && (evaluate { modules = [ "xe" ]; }).acceleration == "default"
  ))
  (check "NixOS does not provision non-NixOS drivers" (
    !nixosConfig.targets.genericLinux.gpu.enable
    && !(nixosConfig.home.activation ? checkExistingGpuDrivers)
    && !nixosConfig.targets.genericLinux.gpu.nvidia.enable
    && nixosConfig.modules.core.gpu.acceleration == "cuda"
  ))
  (check "Generic Linux retains driver provisioning" (
    genericConfig.targets.genericLinux.gpu.enable
    && genericConfig.home.activation ? checkExistingGpuDrivers
  ))
];
pkgs.runCommandLocal "check-gpu-integration"
  {
    nativeBuildInputs = [
      pkgs.bash
      pkgs.coreutils
      pkgs.shellcheck
    ];
  }
  ''
    shellcheck ${../scripts/gpu-env.sh}
    bash ${./gpu-probe.sh} ${../scripts/gpu-env.sh}
    echo GPU_POLICY_OK
    touch "$out"
  ''
