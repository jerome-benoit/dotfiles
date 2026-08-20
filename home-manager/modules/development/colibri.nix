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

  # Per-platform knobs: extra inputs, `make` args, and an optional pre-make line.
  darwinBuild = {
    extraBuildInputs = [
      pkgs.llvmPackages.openmp
      pkgs.apple-sdk_15 # macOS 15 SDK: enables the Metal residency-set path
    ];
    extraNativeBuildInputs = [ ];
    preMake = "";
    makeArgs = "ARCH= METAL=1 OMPDIR=${colibriOmp}"; # ARCH= keeps the build portable (no -mcpu=native)
  };

  cudaBuild =
    let
      cudaPackages = config.modules.core.gpu.cudaPackages;
      cudaNvcc = cudaPackages.cuda_nvcc.__spliced.buildHost or cudaPackages.cuda_nvcc;
      hostCxx = "${cudaPackages.backendStdenv.cc}/bin/g++";
      cudaProfilerApi = cudaPackages.cuda_profiler_api;
      libcublas = cudaPackages.libcublas;
      # CUDA=1 resolves cudart, cuda_profiler_api.h, cuBLAS, and cuBLASLt through CUDA_HOME.
      cudaHome = pkgs.symlinkJoin {
        name = "colibri-cuda-home";
        paths = [
          cudaPackages.cuda_cudart
          cudaProfilerApi.include
          libcublas.include
          libcublas.lib
        ];
        postBuild = ''[ -e "$out/lib64" ] || ln -s lib "$out/lib64"'';
      };
    in
    {
      extraBuildInputs = [
        cudaPackages.cuda_cudart
        cudaProfilerApi
        libcublas
        pkgs.stdenv.cc.cc.lib
      ];
      extraNativeBuildInputs = [ pkgs.autoAddDriverRunpath ]; # RUNPATH += /run/opengl-driver/lib for libcuda.so.1
      preMake = ''export NVCC_PREPEND_FLAGS="-ccbin ${hostCxx}"''; # host g++ without clobbering NVCCFLAGS
      makeArgs = "CUDA=1 CUDA_HOME=${cudaHome} NVCC=${cudaNvcc}/bin/nvcc CUDA_ARCH=all-major"; # all-major: headless-safe
    };

  archBaseline = if pkgs.stdenv.hostPlatform.isx86_64 then "x86-64-v3" else "armv8-a";

  cpuBuild = {
    extraBuildInputs = [ pkgs.stdenv.cc.cc.lib ]; # libgomp.so.1 in the runtime closure
    extraNativeBuildInputs = [ ];
    preMake = "";
    makeArgs = "ARCH=${archBaseline}"; # portable ISA baseline
  };

  build =
    if isDarwin then
      darwinBuild
    else if config.modules.core.gpu.acceleration == "cuda" then
      cudaBuild
    else
      cpuBuild;

  colibriPackage = pkgs.stdenv.mkDerivation {
    pname = "colibri";
    version = config.modules.core.lib.mkUnstableVersionWithBase colibriVersion inputs.colibri;
    inherit src;
    postPatch = ''
      # 1.7.0 copies qwen36 during install without declaring it as a prerequisite.
      substituteInPlace c/Makefile \
        --replace-fail \
          'install: colibri$(EXE) inkling$(EXE) kimi_k3$(EXE) olmoe$(EXE)' \
          'install: colibri$(EXE) inkling$(EXE) kimi_k3$(EXE) olmoe$(EXE) qwen36$(EXE)'

      # Metal MoE requires qgs; Inkling uses fmt 1/2/5 here, where qgs is unused.
      substituteInPlace c/inkling.c \
        --replace-fail \
          'coli_metal_moe_block_begin(ns, D, I, 5, sgp, sup, sdp,' \
          'coli_metal_moe_block_begin(ns, D, I, 5, 0, sgp, sup, sdp,' \
        --replace-fail \
          'nb, D, I, q4 ? 2 : 1, mgp, mup, mdp, mgs, mus, mds,' \
          'nb, D, I, q4 ? 2 : 1, 0, mgp, mup, mdp, mgs, mus, mds,'
    '';

    nativeBuildInputs = [ pkgs.makeWrapper ] ++ build.extraNativeBuildInputs;
    buildInputs = build.extraBuildInputs;

    # Build and stage every supported engine in $out; compilation belongs in
    # buildPhase, leaving installPhase to assemble the coli wrapper and GLM alias.
    buildPhase = ''
      runHook preBuild
      ${build.preMake}
      make -C c install ${build.makeArgs} DESTDIR=$out PREFIX= BINDIR=/bin LIBEXECDIR=/lib/colibri
      runHook postBuild
    '';

    # No doCheck: upstream test-c isn't hermetic (test_ssd_probe timing-flakes,
    # Linux test_uring needs io_uring) — installCheckPhase validates packaging.
    doCheck = false;

    # Offline check: engines staged + the convert data asset present + the wrapper
    # runs (`coli --version` argparse-exits before any model load) + the serve import
    # surface (openai_server -> v4_dsml) resolves.
    # Not versionCheckHook: our -unstable- suffix never matches coli's output.
    doInstallCheck = true;
    installCheckPhase = ''
      runHook preInstallCheck
      # `import openai_server` writes .pyc; keep the check from mutating $out.
      export PYTHONDONTWRITEBYTECODE=1
      test -x $out/lib/colibri/colibri
      test -x $out/lib/colibri/olmoe
      test -f $out/lib/colibri/tools/iq3xxs_grid.json
      $out/bin/coli --version
      PYTHONPATH=$out/lib/colibri ${pythonEnv}/bin/python -c 'import openai_server'
      runHook postInstallCheck
    '';

    # Wrap the raw `coli` script through pythonEnv. COLI_ENGINE stays unset:
    # pinning it routes every model to GLM instead of dispatching per config.
    installPhase = ''
      runHook preInstall
      # make install omits v4_dsml.py (imported by openai_server) and iq3xxs_grid.json
      # (loaded by iq3_pack for `convert --xbits e8`); stage each if missing.
      [ -e "$out/lib/colibri/v4_dsml.py" ] || install -m 644 c/v4_dsml.py "$out/lib/colibri/"
      [ -e "$out/lib/colibri/tools/iq3xxs_grid.json" ] || install -m 644 c/tools/iq3xxs_grid.json "$out/lib/colibri/tools/"
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
      defaultText = lib.literalExpression "colibriPackage";
      description = "colibri package (Metal on Darwin, CUDA on Linux when available, otherwise CPU)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
  };
}
