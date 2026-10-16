{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.primeAgent;
  hp = pkgs.stdenv.hostPlatform;
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

  # Python 3.12: the interpreter prime-agent-runtime's uv.lock resolves against.
  py = pkgs.python312;
  runtimeRoot = "${src}/prime-agent-runtime";
  runtimeProject = "${runtimeRoot}/pyproject.toml";
  runtimeLock = "${runtimeRoot}/uv.lock";

  # Preserve the MCP dependency versions from the runtime lock.
  mkLockedWheel =
    name: dependencies: pythonImportsCheck:
    py.pkgs.buildPythonPackage {
      pname = name;
      inherit (pins.python.${name}) version src;
      format = "wheel";
      inherit dependencies pythonImportsCheck;
      doCheck = false;
    };
  httpcore2 =
    mkLockedWheel "httpcore2"
      [
        py.pkgs.h11
        py.pkgs.truststore
      ]
      [ "httpcore2" ];
  httpx2 =
    mkLockedWheel "httpx2"
      [
        py.pkgs.anyio
        httpcore2
        py.pkgs.idna
        py.pkgs.truststore
        py.pkgs.typing-extensions
      ]
      [ "httpx2" ];
  mcpTypes =
    mkLockedWheel "mcp-types"
      [
        py.pkgs.pydantic
        py.pkgs.typing-extensions
      ]
      [ ];
  sseStarlette = py.pkgs.sse-starlette.overridePythonAttrs (previousAttrs: {
    # Workaround: nixpkgs omits sse-starlette's declared Starlette dependency.
    # Remove when the nixpkgs package propagates Starlette itself.
    dependencies = (previousAttrs.dependencies or [ ]) ++ [ py.pkgs.starlette ];
  });
  mcp2 =
    mkLockedWheel "mcp"
      [
        py.pkgs.anyio
        httpx2
        py.pkgs.jsonschema
        mcpTypes
        py.pkgs.opentelemetry-api
        py.pkgs.pydantic
        py.pkgs.pyjwt
        py.pkgs.cryptography
        py.pkgs.python-multipart
        sseStarlette
        py.pkgs.starlette
        py.pkgs.typing-extensions
        py.pkgs.typing-inspection
        py.pkgs.uvicorn
      ]
      [ "mcp" ];
  pythonRuntimePackages = {
    inherit httpcore2 httpx2;
    mcp = mcp2;
    mcp-types = mcpTypes;
  };

  # Workaround: tyro's completion tests flake on aarch64-darwin.
  # Remove when its source build checks are reliable there.
  tyro = py.pkgs.tyro.overridePythonAttrs (_: {
    doCheck = !pkgs.stdenv.hostPlatform.isDarwin;
  });
  scipy = py.pkgs.scipy;

  rlm = py.pkgs.buildPythonPackage {
    pname = "prime-agent-runtime";
    version = "0.1.0";
    pyproject = true;
    src = runtimeRoot;
    build-system = [ py.pkgs.hatchling ];
    dependencies = [
      mcp2
      tyro
    ];
    doCheck = false;
  };
  runtimePackage = rlm;
  kernelRequirements =
    let
      ps = py.pkgs;
      rlmPackages = import ./pins/rlm-packages.nix { inherit ps scipy tyro; };
    in
    assert builtins.attrNames rlmPackages == pins.rlmExtraPackages;
    rlmPackages
    // {
      inherit rlm;
      "${pins.snapshotRequirement}" = ps.${pins.snapshotRequirement};
    };
  bundledSkills =
    lib.mapAttrs
      (
        name: spec:
        py.pkgs.buildPythonPackage {
          pname = spec.pname or name;
          version = "0.1.0";
          pyproject = true;
          src = "${src}/skills/${name}";
          build-system = [ py.pkgs.hatchling ];
          dependencies = [ rlm ] ++ (spec.dependencies or [ ]);
          pythonImportsCheck = [ spec.importName ];
          doCheck = false;
        }
      )
      {
        agent-message.importName = "agent_message";
        agent-observe.importName = "agent_observe";
        attach-image = {
          pname = "prime-agent-skill-attach-image";
          importName = "attach_image";
          dependencies = [ py.pkgs.pillow ];
        };
        compact.importName = "compact";
        edit.importName = "edit";
        goal.importName = "goal";
        refine.importName = "refine";
        rlm-heartbeat.importName = "rlm_heartbeat";
        websearch = {
          pname = "prime-agent-skill-websearch";
          importName = "websearch";
          dependencies = [ py.pkgs.httpx ];
        };
      };
  kernelPython = py.withPackages (
    _ps: builtins.attrValues kernelRequirements ++ builtins.attrValues bundledSkills
  );

  supported = builtins.elem hp.system platforms;

  primeAgentPackage =
    if !supported then
      null
    else
      pkgs.rustPlatform.buildRustPackage {
        pname = "prime-agent";
        inherit version src;
        inherit (pins) cargoHash;
        cargoDepsName = "prime-agent";
        # Refuse self-update for this Nix-managed installation.
        # Remove when upstream offers a managed-install switch.
        # prime-agent-darwin-tests: platform-correct the AF_UNIX sun_path limit (104
        # on macOS/BSD vs 108 on Linux), gate the Linux-only /proc re-anchor test, skip
        # the ps ground-truth test without /bin/ps. Remove when upstream carries these.
        patches = [
          ../../../patches/prime-agent-nix-self-update.patch
          ../../../patches/prime-agent-darwin-tests.patch
        ];
        PRIME_AGENT_NIX_MANAGED = "1";
        # Upstream tests exercise installer-owned builds; installCheck and
        # runtime smoke checks exercise this build's immutable Nix ownership.
        preCheck = ''
          unset PRIME_AGENT_NIX_MANAGED
        '';
        cargoBuildFlags = [
          "-p"
          "pa-cli"
        ];
        cargoTestFlags = [
          "-p"
          "pa-cli"
          "-p"
          "pa-types"
          "--lib"
        ];
        # This wall-clock test flakes under load.
        checkFlags = [
          "--skip=piped_stdin::tests::a_live_producer_resets_the_window"
        ];
        passthru = {
          inherit
            bundledSkills
            pythonRuntimePackages
            kernelPython
            kernelRequirements
            runtimeLock
            runtimePackage
            runtimeProject
            ;
        };

        nativeBuildInputs = [ pkgs.makeBinaryWrapper ];
        strictDeps = true;
        # The read-only update installCheck serves HTTP on loopback.
        __darwinAllowLocalNetworking = true;

        postInstall = ''
          mkdir -p $out/share/prime-agent
          cp -r prime-agent-runtime docs skills $out/share/prime-agent/
          # The 0.10.0 release embeds synthetic fixtures. Pin production data
          # independently; catalog updates do not change the Rust source pin.
          cp ${pins.bundledCatalogs}/models/catalog.v1.json $out/share/prime-agent/models.bundled.json
          cp ${pins.bundledCatalogs}/plugins/catalog.v2.json $out/share/prime-agent/mcp-services.bundled.json
        '';
        postFixup = ''
          wrapProgram $out/bin/prime-agent \
            --set PI_PACKAGE_DIR $out/share/prime-agent \
            --prefix PATH : ${
              lib.makeBinPath [
                kernelPython
                pkgs.bash
                pkgs.git
                pkgs.fd
                pkgs.ripgrep
                pkgs.nodejs
              ]
            } \
            --set PRIME_AGENT_KERNEL_PYTHON ${kernelPython}/bin/python3 \
            --set-default PI_OFFLINE 1
        '';

        doInstallCheck = true;
        nativeInstallCheckInputs = [ pkgs.versionCheckHook ];
        versionCheckProgramArg = "--version";
        preInstallCheck = ''
          export HOME=$(mktemp -d)
          export DO_NOT_TRACK=1
          ${kernelPython}/bin/python3 scripts/release/bundle_catalog.py verify --out $out/share/prime-agent
          # Schema validation intentionally accepts upstream fixture catalogs.
          ${kernelPython}/bin/python3 - "$out/share/prime-agent" <<'PY'
          import json
          import pathlib
          import sys
          root = pathlib.Path(sys.argv[1])
          models = json.loads((root / "models.bundled.json").read_text())["models"]
          services = json.loads((root / "mcp-services.bundled.json").read_text())["entries"]
          assert all(not model["id"].startswith("fixture-") for model in models)
          assert all(service["service"] != "fixture" for service in services)
          PY
          $out/bin/prime-agent --prime-agent-bootstrap
          mkdir -p "$HOME/.prime/agent"
          printf '%s\n' '{"updateChannel":"stable"}' > "$HOME/.prime/agent/settings.json"
          cp "$HOME/.prime/agent/settings.json" "$TMPDIR/settings-before.json"
          # Exercise read-only checks through the wrapper with isolated environments.
          ${kernelPython}/bin/python3 ${./prime-agent-update-readonly.py} "$out/bin/prime-agent"
          for target in nightly rollback archive; do
            case "$target" in
              nightly) set -- update --nightly ;;
              rollback) set -- update --rollback ;;
              archive) set -- update --archive /nonexistent --source https://example.invalid ;;
            esac
            if $out/bin/prime-agent "$@"; then
              echo "Nix-managed self-update unexpectedly succeeded" >&2
              exit 1
            else
              test "$?" -eq 75
            fi
            cmp "$HOME/.prime/agent/settings.json" "$TMPDIR/settings-before.json"
            test ! -e "$HOME/.local"
          done
          $out/bin/prime-agent package update
          cmp "$HOME/.prime/agent/settings.json" "$TMPDIR/settings-before.json"
        '';

        meta = {
          description = "Prime Agent: self-improving RLM coding and research agent";
          homepage = "https://github.com/PrimeIntellect-ai/prime-agent";
          license = lib.licenses.mit;
          mainProgram = "prime-agent";
          inherit platforms;
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
      defaultText = lib.literalExpression "prime-agent built from the pinned Rust source release";
      description = "prime-agent package (null on unsupported systems)";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = optionalPackages.packages;
    warnings = optionalPackages.warnings;
  };
}
