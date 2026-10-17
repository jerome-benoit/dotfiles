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

  # Workaround: upstream copies os.Executable(), losing the Nix wrapper.
  # Remove when upstream preserves managed hook launchers and their refresh.
  patches = [ ../../../../patches/caveman-blocks-nix-hooks.patch ];

  postInstall = ''
    install -Dm644 LICENSE "$out/share/licenses/caveman-blocks/LICENSE"
    wrapProgram "$out/bin/caveman-blocks" \
      --prefix PATH : ${
        lib.makeBinPath [
          git
          python3
        ]
      } \
      --set CAVEMAN_BLOCKS_NIX_WRAPPER "$out/bin/caveman-blocks" \
      --set-default DO_NOT_TRACK 1 \
      --set-default CAVEMAN_TELEMETRY 0
  '';

  meta = {
    description = "Caveman Blocks with Nix-managed hook launchers";
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
