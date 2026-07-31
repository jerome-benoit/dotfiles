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

  # Own derivation built from the flake input source.
  src = inputs.colibri;

  # Runtime for the `coli` launcher and the offline converter/oracle tools.
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

  # omp.h (dev output) + libomp.dylib (out) under one prefix for the Makefile's OMPDIR probe.
  colibriOmp = pkgs.symlinkJoin {
    name = "colibri-openmp";
    paths = [
      pkgs.llvmPackages.openmp
      pkgs.llvmPackages.openmp.dev
    ];
  };

  # Per-platform knobs: extra inputs, `make glm` args, an optional pre-make line, and doCheck.
  darwinBuild = {
    extraBuildInputs = [
      pkgs.llvmPackages.openmp
      pkgs.apple-sdk_15 # macOS 15 SDK: enables the Metal residency-set path
    ];
    extraNativeBuildInputs = [ ];
    preMake = "";
    makeArgs = "ARCH= METAL=1 OMPDIR=${colibriOmp}"; # ARCH= keeps the build portable (no -mcpu=native)
    doCheck = true;
  };

  cudaBuild =
    let
      cudaPackages = config.modules.core.gpu.cudaPackages;
      cudaNvcc = cudaPackages.cuda_nvcc.__spliced.buildHost or cudaPackages.cuda_nvcc;
      hostCxx = "${cudaPackages.backendStdenv.cc}/bin/g++";
      # cudart-only CUDA_HOME (-L/-rpath/lib64); keeps build-only nvcc out of the runtime closure.
      cudaHome = pkgs.symlinkJoin {
        name = "colibri-cuda-home";
        paths = [ cudaPackages.cuda_cudart ];
        postBuild = ''[ -e "$out/lib64" ] || ln -s lib "$out/lib64"'';
      };
    in
    {
      extraBuildInputs = [
        cudaPackages.cuda_cudart
        pkgs.stdenv.cc.cc.lib
      ];
      extraNativeBuildInputs = [ pkgs.autoAddDriverRunpath ]; # RUNPATH += /run/opengl-driver/lib for libcuda.so.1
      preMake = ''export NVCC_PREPEND_FLAGS="-ccbin ${hostCxx}"''; # host g++ without clobbering NVCCFLAGS
      makeArgs = "CUDA=1 CUDA_HOME=${cudaHome} NVCC=${cudaNvcc}/bin/nvcc CUDA_ARCH=all-major"; # all-major: headless-safe
      doCheck = false;
    };

  cpuBuild = {
    extraBuildInputs = [ ];
    extraNativeBuildInputs = [ ];
    preMake = "";
    makeArgs = "ARCH=${if pkgs.stdenv.hostPlatform.isx86_64 then "x86-64-v3" else "armv8-a"}"; # portable ISA baselines
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
    version = inputs.colibri.shortRev or "unstable";
    inherit src;

    nativeBuildInputs = [ pkgs.makeWrapper ] ++ build.extraNativeBuildInputs;
    buildInputs = [ pkgs.gmp ] ++ build.extraBuildInputs;
    nativeCheckInputs = [ pkgs.python3 ];

    buildPhase = ''
      runHook preBuild
      ${build.preMake}
      make -C c glm ${build.makeArgs}
      runHook postBuild
    '';

    # Self-contained layout `coli` resolves at runtime; install c/colibri as the engine `glm`.
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
      defaultText = lib.literalExpression "colibri built from the flake input (GPU-enabled)";
      description = "colibri package (Metal on darwin, CUDA on Linux when available, else CPU)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
  };
}
