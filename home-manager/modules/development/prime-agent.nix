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
  pins =
    (import ./pins {
      inherit lib;
      inherit (pkgs) fetchurl fetchzip;
    }).primeAgent;

  platforms = [
    "aarch64-darwin"
    "aarch64-linux"
    "x86_64-linux"
  ];

  version = pins.version;
  src = pins.src;

  # Native/runtime deps external to the esbuild bundle, pinned with the Prime Agent release data.
  zeromqVersion = pins.npm.zeromq.version;

  zeromqSrc = pins.npm.zeromq.src;
  # zeromq's load-addon.js requires cmake-ts/build/loader at runtime.
  cmakeTsSrc = pins.npm.cmake-ts.src;
  photonSrc = pins.npm."@silvia-odwyer/photon-node".src;
  # cli-main dynamically imports undici, which is external to the esbuild bundle.
  undiciSrc = pins.npm.undici.src;

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

  # The manifest names and this pip-to-nixpkgs mapping must stay identical.
  kernelPython = py.withPackages (
    ps:
    let
      rlmPackages = import ./pins/rlm-packages.nix { inherit ps scipy tyro; };
    in
    assert builtins.attrNames rlmPackages == pins.rlmExtraPackages;
    [
      rlm
      ps.${pins.snapshotRequirement}
      ps.jupyter-client
    ]
    ++ builtins.attrValues rlmPackages
  );

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
  optionalPackages = config.modules.core.lib.mkOptionalPackages [
    {
      package = cfg.package;
      warning = "prime-agent: no supported build for system ${hp.system}";
    }
  ];
in
{
  options.modules.development.primeAgent = {
    enable = lib.mkEnableOption "Prime Agent (RLM coding/research agent)";

    package = config.modules.core.lib.mkOptionalPackageOption {
      default = primeAgentPackage;
      defaultText = lib.literalExpression "prime-agent assembled from the release tarball for the host platform";
      description = "prime-agent package (null on unsupported systems)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
