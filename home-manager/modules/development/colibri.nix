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

  # Real upstream version from c/version.py, tracked by the input rev.
  colibriVersion =
    let
      match = builtins.match ''.*__version__ = "([^"]*)".*'' (builtins.readFile "${src}/c/version.py");
    in
    if match == null then "0" else builtins.head match;

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

  # Per-platform knobs: extra inputs, `make` args, an optional pre-make line, and doCheck.
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

  archBaseline = if pkgs.stdenv.hostPlatform.isx86_64 then "x86-64-v3" else "armv8-a";

  cpuBuild = {
    extraBuildInputs = [ pkgs.stdenv.cc.cc.lib ]; # libgomp.so.1 in the runtime closure
    extraNativeBuildInputs = [ ];
    preMake = "";
    makeArgs = "ARCH=${archBaseline}"; # portable ISA baseline
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
    version = config.modules.core.lib.mkUnstableVersionWithBase colibriVersion inputs.colibri;
    inherit src;

    nativeBuildInputs = [ pkgs.makeWrapper ] ++ build.extraNativeBuildInputs;
    buildInputs = build.extraBuildInputs;
    nativeCheckInputs = [ pkgs.python3 ];

    # Build+stage every engine into $out (GLM chosen variant, olmoe, deepseek_v4
    # on COLI_V4_SUPPORTED platforms); the compile belongs in buildPhase, leaving
    # installPhase to assemble the coli wrapper + glm alias.
    buildPhase = ''
      runHook preBuild
      ${build.preMake}
      make -C c install ${build.makeArgs} DESTDIR=$out PREFIX= BINDIR=/bin LIBEXECDIR=/lib/colibri
      runHook postBuild
    '';

    checkPhase = ''
      runHook preCheck
      make -C c test-c
      runHook postCheck
    '';
    doCheck = build.doCheck;

    # Offline check: assert the colibri + olmoe engine binaries are staged and the
    # wrapper runs (`coli --version` argparse-exits before any model load). Not
    # versionCheckHook: our -unstable- suffix never matches coli's `colibri <base>`.
    doInstallCheck = true;
    installCheckPhase = ''
      runHook preInstallCheck
      test -x $out/lib/colibri/colibri
      test -x $out/lib/colibri/olmoe
      $out/bin/coli --version
      runHook postInstallCheck
    '';

    # Wrap the raw `coli` script through pythonEnv. COLI_ENGINE stays unset:
    # pinning it routes every model to GLM instead of dispatching per config.
    installPhase = ''
      runHook preInstall
      mv $out/bin/coli $out/lib/colibri/coli
      ln -s ../lib/colibri/colibri $out/bin/glm
      makeWrapper ${pythonEnv}/bin/python $out/bin/coli \
        --add-flags "$out/lib/colibri/coli" \
        --set PYTHONPATH "$out/lib/colibri:${pythonEnv}/${pkgs.python3.sitePackages}"
      runHook postInstall
    '';

    meta = {
      description = "Run large MoE models in pure C, experts streamed from disk";
      homepage = "https://github.com/JustVugg/colibri";
      license = lib.licenses.asl20;
      platforms = lib.platforms.linux ++ lib.platforms.darwin;
      mainProgram = "coli";
    };
  };
in
{
  options.modules.development.colibri = {
    enable = lib.mkEnableOption "colibri MoE inference engine (GLM-5.2, OLMoE, DeepSeek V4 Flash)";

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
