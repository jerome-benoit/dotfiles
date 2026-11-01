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
  # `coli web` serves this Vite bundle from lib/colibri/web/dist. Build it in a
  # separate native derivation: the result is static and is therefore valid for
  # every target platform, including cross builds.
  colibriWeb = pkgs.buildPackages.buildNpmPackage {
    pname = "colibri-web";
    version = colibriVersion;
    src = "${src}/web";
    npmDeps = pkgs.buildPackages.importNpmLock { npmRoot = "${src}/web"; };
    npmConfigHook = pkgs.buildPackages.importNpmLock.npmConfigHook;
    npmBuildScript = "build";

    installPhase = ''
      runHook preInstall
      install -d "$out"
      cp -R dist/. "$out/"
      runHook postInstall
    '';
  };

  # Runtime for the `coli` launcher and the offline converter/oracle tools.
  pythonEnv = pkgs.python3.withPackages (
    ps: with ps; [
      torch
      safetensors
      huggingface-hub
      numpy
      pillow
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
      # Workaround: block-scaled cuBLASLt requires CUDA 12.8.
      # Remove when upstream automatically disables tensor cores on older toolkits.
      makeArgs =
        "ARCH=${archBaseline} CUDA=1 CUDA_HOME=${cudaHome} NVCC=${cudaNvcc}/bin/nvcc CUDA_ARCH=all-major"
        + lib.optionalString (cudaPackages.cudaOlder "12.8") " NO_TC=1"; # all-major: headless-safe
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

    nativeBuildInputs = [ pkgs.makeWrapper ] ++ build.extraNativeBuildInputs;
    nativeCheckInputs = [ pkgs.buildPackages.python3Minimal ];
    buildInputs = build.extraBuildInputs;

    # Build and stage every supported engine in $out; compilation belongs in
    # buildPhase, leaving installPhase to assemble the coli wrapper and GLM alias.
    buildPhase = ''
      runHook preBuild
      ${build.preMake}
      make -C c install ${build.makeArgs} DESTDIR=$out PREFIX= BINDIR=/bin LIBEXECDIR=/lib/colibri
      runHook postBuild
    '';

    # Workaround: test-c is only sandbox-validated on x86_64 Linux.
    # Remove when the remaining supported platforms pass their sandbox checks.
    doCheck = pkgs.stdenv.hostPlatform.isLinux && pkgs.stdenv.hostPlatform.isx86_64;
    checkPhase = ''
      runHook preCheck
      make -C c test-c ARCH=${archBaseline}
      runHook postCheck
    '';

    # Offline check: all unconditional engines, converter data, and dashboard
    # assets are staged; the wrapper runs (`coli --version` exits before model
    # loading); and the serve import surface resolves. Not versionCheckHook: our
    # unstable package suffix never matches coli's output.
    doInstallCheck = true;
    installCheckPhase = ''
      runHook preInstallCheck
      # `import openai_server` writes .pyc; keep the check from mutating $out.
      export PYTHONDONTWRITEBYTECODE=1
      for engine in colibri glm53 inkling kimi_k3 olmoe qwen36 qwen38 \
        deepseek_v41 mimo qwenimage laya gliner_decide; do
        test -x "$out/lib/colibri/$engine"
      done
      test -f $out/lib/colibri/tools/iq3xxs_grid.json
      test -f $out/lib/colibri/web/dist/index.html
      $out/bin/coli --version
      PYTHONPATH=$out/lib/colibri ${pythonEnv}/bin/python -c 'import openai_server'
      PYTHONPATH=$out/lib/colibri/tools ${pythonEnv}/bin/python - <<'PY'
      import io
      import numpy
      from PIL import Image
      from qwen38_image import preprocess
      image = io.BytesIO()
      Image.new("RGB", (32, 32)).save(image, format="PNG")
      patches, height, width = preprocess(image.getvalue())
      assert patches.dtype == numpy.float32 and numpy.isfinite(patches).all()
      assert patches.size > 0 and height > 0 and width > 0
      PY
      runHook postInstallCheck
    '';

    # Exercise the real Python preprocessor without building engines or loading models.
    passthru.integrationPython = pythonEnv;

    # Wrap the raw `coli` script through pythonEnv. COLI_ENGINE stays unset:
    # pinning it routes every model to GLM instead of dispatching per config.
    installPhase = ''
      runHook preInstall
      # Workaround: upstream omits the iq3_pack data grid from installation.
      # Remove when the installed tools directory includes iq3xxs_grid.json.
      [ -e "$out/lib/colibri/tools/iq3xxs_grid.json" ] || \
        install -m 644 c/tools/iq3xxs_grid.json "$out/lib/colibri/tools/"
      install -d "$out/lib/colibri/web/dist"
      cp -R ${colibriWeb}/. "$out/lib/colibri/web/dist/"
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
    enable = lib.mkEnableOption "colibri MoE inference engine (GLM-5.2, Inkling, Kimi K3, Qwen3.6, OLMoE, DeepSeek V4 Flash)";

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
