{
  lib,
  buildGoModule,
  makeWrapper,
  git,
  python3,
  pins,
}:
buildGoModule {
  pname = "caveman-blocks";
  inherit (pins) version src vendorHash;
  subPackages = [ "cmd/caveman-blocks" ];
  env.CGO_ENABLED = "0";
  ldflags = [
    "-s"
    "-w"
    "-X main.version=${pins.version}"
  ];
  nativeBuildInputs = [ makeWrapper ];
  nativeCheckInputs = [
    git
    python3
  ];

  patches = [
    # Workaround: upstream copies os.Executable(), losing the Nix wrapper.
    # Remove when upstream preserves managed hook launchers and their refresh.
    ../../../../patches/caveman-blocks-nix-hooks.patch
    # Workaround: OpenCode 2 needs a compatible adapter and invocation-scoped hints.
    # Remove when upstream supports both APIs and location-relative workdirs.
    ../../../../patches/caveman-blocks-opencode2.patch
    # Workaround: the OpenCode profile ignores the effective config root.
    # Remove when upstream honors absolute OPENCODE_CONFIG_DIR and XDG fallback roots.
    ../../../../patches/caveman-blocks-config-root.patch
  ];

  postInstall = ''
    for name in LICENSE NOTICE; do
      install -Dm644 "$name" "$out/share/licenses/caveman-blocks/$name"
    done
    for dependency in github.com/pelletier/go-toml/v2 github.com/spf13/pflag; do
      install -Dm644 "vendor/$dependency/LICENSE" \
        "$out/share/licenses/caveman-blocks/$dependency/LICENSE"
    done
    # Workaround: upstream resolves git and python3 from PATH at run time.
    # Remove when the upstream binaries take those paths from their configuration.
    wrapProgram "$out/bin/caveman-blocks" \
      --prefix PATH : ${
        lib.makeBinPath [
          git
          python3
        ]
      } \
      --set CAVEMAN_NIX_MANAGED 1 \
      --set CAVEMAN_BLOCKS_NIX_WRAPPER "$out/bin/caveman-blocks" \
      --set-default DO_NOT_TRACK 1 \
      --set-default CAVEMAN_TELEMETRY 0
  '';

  meta = {
    description = "Caveman Blocks reusable scripts and coding-agent hooks";
    homepage = "https://github.com/caveman-ai/blocks";
    license = lib.licenses.asl20;
    mainProgram = "caveman-blocks";
    platforms = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-linux"
    ];
  };
}
