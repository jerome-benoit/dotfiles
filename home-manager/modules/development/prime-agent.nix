{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.prime-agent;
  stdenv = pkgs.stdenvNoCC;
  hp = stdenv.hostPlatform;

  # renovate: datasource=github-releases depName=PrimeIntellect-ai/prime-agent
  version = "0.7.1";

  src = pkgs.fetchzip {
    url = "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v${version}/prime-agent-${version}.tgz";
    hash = "sha256-o0zZuv+Xam0BNn112wkDP7SfDh24VfMMBJKSLBynIAI="; # @ci:src-hash-prime-agent
  };

  # The bundle keeps native deps external; only these artifacts are needed at runtime (not in the release tarball).
  zeromqSrc = pkgs.fetchzip {
    url = "https://registry.npmjs.org/zeromq/-/zeromq-6.5.0.tgz";
    hash = "sha256-znAyvpACYYJ64RUVEtDBBrYisMdkzxGDvSQbatd+dMM="; # @ci:src-hash-zeromq
  };
  # zeromq's load-addon.js does require("cmake-ts/build/loader"); cmake-ts is a runtime dep absent from its tarball.
  cmakeTsSrc = pkgs.fetchzip {
    url = "https://registry.npmjs.org/cmake-ts/-/cmake-ts-1.0.2.tgz";
    hash = "sha256-tR/YtX/WjwF3/w7sUSI3Sm4DvBmOMZbtwNJcdx+ozac="; # @ci:src-hash-cmake-ts
  };
  photonSrc = pkgs.fetchzip {
    url = "https://registry.npmjs.org/@silvia-odwyer/photon-node/-/photon-node-0.3.4.tgz";
    hash = "sha256-KuKwcs3bXqZpJiKLr45EMfJrQkhZ6NZtgaUSFuqGCb8="; # @ci:src-hash-photon
  };
  # cli-main dynamically imports "undici" (kept external from the esbuild bundle); it has no runtime deps.
  undiciSrc = pkgs.fetchzip {
    url = "https://registry.npmjs.org/undici/-/undici-7.29.0.tgz";
    hash = "sha256-xtWGZuAjA6c8p3EjgweXN6Au1sMLg9JZOKPXNFCMIjs="; # @ci:src-hash-undici
  };

  # python311 is eval-broken in current nixpkgs (sphinx via stack-data); 3.12 satisfies rlm's requires-python>=3.10.
  py = pkgs.python312;
  # tyro's own bash-completion tests flake building from source on aarch64-darwin; we only consume the library.
  tyro = py.pkgs.tyro.overridePythonAttrs (_: {
    doCheck = false;
  });
  # scipy's stats test suite has a flaky Hypothesis property test (test_support_moments_sample,
  # ~2e-9 tolerance drift) building from source on aarch64-darwin; we only consume the library.
  scipy = py.pkgs.scipy.overridePythonAttrs (_: {
    doCheck = false;
  });

  # Kernel-side runtime shim, built from the release's own bundled source so it matches the CLI's RUNTIME_READY_CHECK.
  rlm = py.pkgs.buildPythonPackage {
    pname = "prime-agent-runtime";
    version = "0.1.0";
    pyproject = true;
    src = "${src}/dist/prime-agent-runtime";
    build-system = [ py.pkgs.hatchling ];
    dependencies = [
      py.pkgs.ipykernel
      py.pkgs.nest-asyncio
      tyro
    ];
    doCheck = false;
  };

  # PRIME_AGENT_KERNEL_PYTHON is validated against ipykernel + rlm + every DEFAULT_RLM_EXTRA_PACKAGES;
  # a missing package makes the agent fall back to the uv/network venv path.
  kernelPython = py.withPackages (ps: [
    rlm
    tyro
    ps.dill
    ps.jupyter-client
    ps.requests
    ps.httpx
    ps.pyyaml
    ps.tomli
    ps.python-dotenv
    ps.pandas
    ps.numpy
    scipy
    ps.beautifulsoup4
    ps.lxml
    ps.pydantic
  ]);

  supported = builtins.elem hp.system [
    "aarch64-darwin"
    "x86_64-linux"
    "aarch64-linux"
  ];

  primeAgentPackage =
    if !supported then
      null
    else
      stdenv.mkDerivation {
        pname = "prime-agent";
        inherit version src;

        nativeBuildInputs = [
          pkgs.makeBinaryWrapper
        ]
        ++ lib.optionals hp.isElf [ pkgs.autoPatchelfHook ];

        buildInputs = lib.optionals hp.isElf [ pkgs.stdenv.cc.cc.lib ];

        dontConfigure = true;
        dontBuild = true;

        installPhase = ''
          runHook preInstall

          mkdir -p $out/lib/prime-agent
          cp -r dist docs skills $out/lib/prime-agent/
          # The CLI's getPackageDir() walks up from dist/bundle looking for the dir that
          # contains package.json (to read version + piConfig); ship it at the package root.
          cp package.json $out/lib/prime-agent/

          nm=$out/lib/prime-agent/node_modules
          mkdir -p "$nm/zeromq" "$nm/cmake-ts" "$nm/@silvia-odwyer/photon-node" "$nm/undici"
          cp -r ${zeromqSrc}/build ${zeromqSrc}/lib ${zeromqSrc}/package.json "$nm/zeromq/"
          cp -r ${cmakeTsSrc}/. "$nm/cmake-ts/"
          cp -r ${photonSrc}/. "$nm/@silvia-odwyer/photon-node/"
          cp -r ${undiciSrc}/. "$nm/undici/"

          makeBinaryWrapper ${lib.getExe pkgs.nodejs_22} $out/bin/prime-agent \
            --add-flags $out/lib/prime-agent/dist/bundle/cli.js \
            --prefix PATH : ${
              lib.makeBinPath [
                pkgs.nodejs_22
                kernelPython
                pkgs.git
                pkgs.fd
                pkgs.ripgrep
              ]
            } \
            --set PRIME_AGENT_KERNEL_PYTHON ${kernelPython}/bin/python3 \
            --set PRIME_AGENT_INSTALL_UV 0 \
            --set-default PI_OFFLINE 1

          runHook postInstall
        '';

        doInstallCheck = true;
        nativeInstallCheckInputs = [ pkgs.versionCheckHook ];
        versionCheckProgramArg = "--version";

        meta = {
          description = "Prime Agent: self-improving RLM coding and research agent";
          homepage = "https://github.com/PrimeIntellect-ai/prime-agent";
          license = lib.licenses.mit;
          mainProgram = "prime-agent";
          platforms = [
            "aarch64-darwin"
            "x86_64-linux"
            "aarch64-linux"
          ];
          sourceProvenance = with lib.sourceTypes; [
            binaryBytecode
            binaryNativeCode
          ];
        };
      };
in
{
  options.modules.development.prime-agent = {
    enable = lib.mkEnableOption "Prime Agent (RLM coding/research agent)";

    package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = primeAgentPackage;
      defaultText = lib.literalExpression "prime-agent assembled from the release tarball for the host platform";
      description = "prime-agent package (null on unsupported systems)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = lib.optional (cfg.package != null) cfg.package;
    warnings = lib.optional (
      cfg.package == null
    ) "prime-agent: no supported build for system ${hp.system}";
  };
}
