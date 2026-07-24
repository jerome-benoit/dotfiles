{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.development.colibri;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;

  # colibri GLM-5.2 (744B MoE) inference engine. We build our OWN derivation from
  # the pinned flake input used purely as SOURCE — the upstream flake's own
  # packages.default is broken (its installPhase copies c/glm, but `make glm`
  # produces c/colibri), so consuming it would force a workaround. Deriving here
  # gives clean naming, GPU control (Metal on darwin, CUDA on Linux), and no
  # dependency on the upstream flake outputs.
  src = inputs.colibri;

  # Python runtime for the `coli` launcher and the offline converter/oracle tools.
  pythonEnv = pkgs.python3.withPackages (
    ps: with ps; [
      torch
      safetensors
      huggingface-hub
      numpy
      tokenizers
      datasets
    ]
  );

  # darwin OpenMP: omp.h lives in the `.dev` output, libomp.dylib in the default
  # output; the Makefile's OMPDIR probe needs both headers and lib under one prefix.
  colibriOmp = pkgs.symlinkJoin {
    name = "colibri-openmp";
    paths = [
      pkgs.llvmPackages.openmp
      pkgs.llvmPackages.openmp.dev
    ];
  };

  # Per-platform build knobs: extra inputs, the `make glm` arguments, an optional
  # pre-make shell snippet, and whether to run the upstream C test suite.
  darwinBuild = {
    extraBuildInputs = [
      pkgs.llvmPackages.openmp
      pkgs.apple-sdk_15 # backend_metal.mm needs the macOS 15 SDK (MTLResidencySet)
    ];
    preMake = "";
    # ARCH= drops -mcpu=native (portable). Only append GPU/OMP flags — CFLAGS/LDFLAGS
    # stay Makefile-controlled so METAL=1 keeps -DCOLI_METAL + -framework Metal.
    makeArgs = "ARCH= METAL=1 OMPDIR=${colibriOmp}";
    doCheck = true; # dependency-free C tests, validated on darwin
  };

  cudaBuild =
    let
      cudaPackages = config.modules.core.gpu.cudaPackages;
      cudaNvcc = cudaPackages.cuda_nvcc.__spliced.buildHost or cudaPackages.cuda_nvcc;
      hostCxx = "${cudaPackages.backendStdenv.cc}/bin/g++";
      # The Makefile hardcodes $(CUDA_HOME)/bin/nvcc and $(CUDA_HOME)/lib64; nixpkgs
      # cuda_cudart is a single `out` (include/ + lib/), so join with nvcc + alias lib64.
      cudaHome = pkgs.symlinkJoin {
        name = "colibri-cuda-home";
        paths = [
          cudaNvcc
          cudaPackages.cuda_cudart
        ];
        postBuild = ''[ -e "$out/lib64" ] || ln -s lib "$out/lib64"'';
      };
    in
    {
      extraBuildInputs = [
        cudaPackages.cuda_cudart
        pkgs.stdenv.cc.cc.lib
      ];
      # -ccbin via NVCC_PREPEND_FLAGS (env) so it does not clobber the Makefile's NVCCFLAGS.
      preMake = ''export NVCC_PREPEND_FLAGS="-ccbin ${hostCxx}"'';
      # CUDA_ARCH=all-major: headless-safe (no GPU probe) and version-adaptive.
      makeArgs = "CUDA=1 CUDA_HOME=${cudaHome} NVCC=${cudaHome}/bin/nvcc CUDA_ARCH=all-major";
      doCheck = false; # no NVIDIA GPU in the sandbox; CUDA path unvalidatable here
    };

  cpuBuild = {
    extraBuildInputs = [ ];
    preMake = "";
    # x86-64-v3 (portable AVX2) on x86_64; native elsewhere (nix strips -march/-mcpu=native)
    # — mirrors upstream's guard so a future aarch64-linux target does not get an invalid -march.
    makeArgs = "ARCH=${if pkgs.stdenv.hostPlatform.isx86_64 then "x86-64-v3" else "native"}";
    doCheck = false; # linux-only test_uring probes io_uring, unavailable in the sandbox
  };

  build =
    if isDarwin then
      darwinBuild
    else if config.modules.core.gpu.cudaEnable then
      cudaBuild
    else
      cpuBuild;

  colibriPackage = pkgs.stdenv.mkDerivation {
    pname = "colibri";
    version = "1.1.1";
    inherit src;

    nativeBuildInputs = [ pkgs.makeWrapper ];
    buildInputs = [ pkgs.gmp ] ++ build.extraBuildInputs;
    nativeCheckInputs = [ pkgs.python3 ];

    buildPhase = ''
      runHook preBuild
      ${build.preMake}
      make -C c glm ${build.makeArgs}
      runHook postBuild
    '';

    # Self-contained layout mirroring the tree `coli` resolves at runtime. The C
    # target `glm` produces the binary `c/colibri` (phony `glm: colibri`); install
    # it as the engine `glm` — no rename hack, unlike the upstream flake.
    installPhase = ''
      runHook preInstall
      mkdir -p $out/lib/colibri/tools $out/bin
      cp c/colibri $out/lib/colibri/glm
      cp c/coli    $out/lib/colibri/coli
      chmod +x $out/lib/colibri/coli
      cp c/openai_server.py c/resource_plan.py c/doctor.py c/version.py $out/lib/colibri/
      cp -r c/tools/* $out/lib/colibri/tools/
      ln -s ../lib/colibri/glm $out/bin/glm
      makeWrapper ${pythonEnv}/bin/python $out/bin/coli \
        --add-flags "$out/lib/colibri/coli" \
        --set-default COLI_ENGINE "$out/lib/colibri/glm" \
        --set PYTHONPATH "$out/lib/colibri:${pythonEnv}/${pkgs.python3.sitePackages}"
      runHook postInstall
    '';

    checkPhase = ''
      runHook preCheck
      make -C c test-c
      runHook postCheck
    '';
    doCheck = build.doCheck;

    meta = {
      description = "Run GLM-5.2 (744B MoE) on a consumer machine — pure C, experts streamed from disk";
      homepage = "https://github.com/JustVugg/colibri";
      license = lib.licenses.asl20;
      platforms = lib.platforms.linux ++ lib.platforms.darwin;
      mainProgram = "coli";
    };
  };
in
{
  options.modules.development.colibri = {
    enable = lib.mkEnableOption "colibri GLM-5.2 MoE inference engine";

    package = lib.mkOption {
      type = lib.types.package;
      default = colibriPackage;
      defaultText = lib.literalExpression "colibri built from the flake input source (GPU-enabled)";
      description = "colibri package (Metal on darwin, CUDA on Linux when available, else CPU)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
  };
}
