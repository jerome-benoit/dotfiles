{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.primeAgent;
  stdenv = pkgs.stdenvNoCC;
  hp = stdenv.hostPlatform;

  platforms = [
    "aarch64-darwin"
    "aarch64-linux"
    "x86_64-linux"
  ];

  # renovate: datasource=github-releases depName=PrimeIntellect-ai/prime-agent
  version = "0.7.1";

  src = pkgs.fetchzip {
    url = "https://github.com/PrimeIntellect-ai/prime-agent/releases/download/v${version}/prime-agent-${version}.tgz";
    hash = "sha256-o0zZuv+Xam0BNn112wkDP7SfDh24VfMMBJKSLBynIAI="; # @ci:src-hash-prime-agent
  };

  # Native/runtime deps external to the esbuild bundle, absent from the tarball; pinned to prime-agent's package-lock.
  # Versions + hashes are resynced from the upstream lock (.packages["node_modules/<name>"].version) by fix-nix-hashes.yml on a
  # bump — the @ci:npm-version/@ci:npm-hash markers below are the rewrite anchors; keep one dep per marked line.
  zeromqVersion = "6.5.0"; # @ci:npm-version zeromq
  cmakeTsVersion = "1.0.2"; # @ci:npm-version cmake-ts
  photonVersion = "0.3.4"; # @ci:npm-version @silvia-odwyer/photon-node
  undiciVersion = "7.28.0"; # @ci:npm-version undici

  zeromqSrc = pkgs.fetchzip {
    url = "https://registry.npmjs.org/zeromq/-/zeromq-${zeromqVersion}.tgz";
    hash = "sha256-znAyvpACYYJ64RUVEtDBBrYisMdkzxGDvSQbatd+dMM="; # @ci:npm-hash zeromq
  };
  # zeromq's load-addon.js does require("cmake-ts/build/loader"); cmake-ts is a runtime dep absent from its tarball.
  cmakeTsSrc = pkgs.fetchzip {
    url = "https://registry.npmjs.org/cmake-ts/-/cmake-ts-${cmakeTsVersion}.tgz";
    hash = "sha256-tR/YtX/WjwF3/w7sUSI3Sm4DvBmOMZbtwNJcdx+ozac="; # @ci:npm-hash cmake-ts
  };
  photonSrc = pkgs.fetchzip {
    url = "https://registry.npmjs.org/@silvia-odwyer/photon-node/-/photon-node-${photonVersion}.tgz";
    hash = "sha256-KuKwcs3bXqZpJiKLr45EMfJrQkhZ6NZtgaUSFuqGCb8="; # @ci:npm-hash @silvia-odwyer/photon-node
  };
  # cli-main dynamically imports "undici" (kept external from the esbuild bundle); it has no runtime deps.
  undiciSrc = pkgs.fetchzip {
    url = "https://registry.npmjs.org/undici/-/undici-${undiciVersion}.tgz";
    hash = "sha256-j0xXiurS8I7UkOHltqn6o6ndDs4igkAAE0A3VPRxa9c="; # @ci:npm-hash undici
  };

  # zeromq ships prebuilt N-API addons for every platform; keep only the host os/arch and drop the musl
  # variants (autoPatchelfHook can't resolve musl's libc on a glibc stdenv). Patched writable here so the
  # consumer only copies a ready addon — isolates the ELF handling and keeps prime-agent a pure assembly.
  zeromqAddon = stdenv.mkDerivation {
    pname = "zeromq-node-addon";
    version = zeromqVersion;
    src = zeromqSrc;

    nativeBuildInputs = lib.optionals hp.isElf [ pkgs.autoPatchelfHook ];
    buildInputs = lib.optionals hp.isElf [ pkgs.stdenv.cc.cc.lib ];

    strictDeps = true;
    dontConfigure = true;
    dontBuild = true;

    installPhase = ''
      runHook preInstall
      mkdir -p $out
      cp -r build lib package.json $out/
      chmod -R u+w $out/build
      find $out/build -mindepth 1 -maxdepth 1 -type d ! -name '${hp.node.platform}' -exec rm -rf {} +
      find $out/build/${hp.node.platform} -mindepth 1 -maxdepth 1 -type d ! -name '${hp.node.arch}' -exec rm -rf {} +
      find $out/build -type d -name 'musl-*-Release' -prune -exec rm -rf {} +
      runHook postInstall
    '';
  };

  # python311 is eval-broken here: ipykernel -> ipython -> sphinx-9.1.0 (unsupported on 3.11); 3.12 satisfies rlm's requires-python>=3.10.
  py = pkgs.python312;
  # tyro's own bash-completion tests flake building from source on aarch64-darwin; we only consume the library.
  tyro = py.pkgs.tyro.overridePythonAttrs (_: {
    doCheck = false;
  });
  # scipy's stats suite has a flaky Hypothesis property test (~2e-9 drift) building from source on aarch64-darwin; we only consume the library.
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

  # PRIME_AGENT_KERNEL_PYTHON must cover ipykernel + rlm + every DEFAULT_RLM_EXTRA_PACKAGES; a missing one
  # silently drops the agent to the uv/network venv path. pip->nixpkgs names aren't 1:1, so the set is
  # hand-mirrored below (dill tracked separately) and fix-nix-hashes.yml fails a bump on upstream drift.
  # @ci:rlm-extra-packages beautifulsoup4 httpx lxml numpy pandas pydantic python-dotenv pyyaml requests scipy tomli tyro
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

  supported = builtins.elem hp.system platforms;

  primeAgentPackage =
    if !supported then
      null
    else
      stdenv.mkDerivation {
        pname = "prime-agent";
        inherit version src;

        nativeBuildInputs = [ pkgs.makeBinaryWrapper ];

        strictDeps = true;
        dontConfigure = true;
        dontBuild = true;

        installPhase = ''
          runHook preInstall

          mkdir -p $out/lib/prime-agent
          cp -r dist docs skills $out/lib/prime-agent/
          # The CLI's getPackageDir() walks up from dist/bundle for the dir that holds package.json
          # (to read version + piConfig); ship it at the package root.
          cp package.json $out/lib/prime-agent/

          nm=$out/lib/prime-agent/node_modules
          mkdir -p "$nm/cmake-ts" "$nm/@silvia-odwyer/photon-node" "$nm/undici"
          cp -r ${zeromqAddon} "$nm/zeromq"
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
        # Exercise the real runtime plumbing versionCheckHook misses: load the external native deps
        # (zeromq — also validates cmake-ts + the ELF patch — and undici) and the kernel import surface.
        preInstallCheck = ''
          ( cd $out/lib/prime-agent && ${lib.getExe pkgs.nodejs_22} -e 'require("zeromq"); require("undici")' )
          ${kernelPython}/bin/python3 -c 'import rlm, ipykernel'
        '';

        meta = {
          description = "Prime Agent: self-improving RLM coding and research agent";
          homepage = "https://github.com/PrimeIntellect-ai/prime-agent";
          license = lib.licenses.mit;
          mainProgram = "prime-agent";
          inherit platforms;
          sourceProvenance = with lib.sourceTypes; [
            binaryBytecode
            binaryNativeCode
          ];
        };
      };
in
{
  options.modules.development.primeAgent = {
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
