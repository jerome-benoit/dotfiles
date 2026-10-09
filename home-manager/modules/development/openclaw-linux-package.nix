{
  lib,
  stdenv,
  fetchurl,
  dpkg,
  autoPatchelfHook,
  wrapGAppsHook3,
  gtk3,
  webkitgtk_4_1,
  libayatana-appindicator,
  xdotool,
  gst_all_1,
  bash,
  xdg-utils,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "openclaw-desktop";
  # renovate: datasource=github-releases depName=openclaw/openclaw versioning=loose
  version = "2026.9.9";

  src = fetchurl {
    url = "https://github.com/openclaw/openclaw/releases/download/v${finalAttrs.version}/OpenClaw-${finalAttrs.version}-amd64.deb";
    hash = "sha256-qNbLND82CpfpUWW7mIDtBTLIihLdMK9nccnrUGVOWeg=";
  };

  nativeBuildInputs = [
    dpkg
    autoPatchelfHook
    wrapGAppsHook3
  ];

  buildInputs = [
    gtk3
    webkitgtk_4_1
    libayatana-appindicator
    xdotool
    stdenv.cc.cc.lib
    gst_all_1.gst-plugins-base
    gst_all_1.gst-plugins-good
    gst_all_1.gst-plugins-bad
    gst_all_1.gst-libav
  ];

  # The tray and global shortcuts load these libraries dynamically.
  runtimeDependencies = map lib.getLib [
    libayatana-appindicator
    xdotool
  ];

  unpackPhase = ''
    runHook preUnpack
    dpkg-deb -x "$src" .
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p "$out"
    cp -r usr/bin usr/lib usr/share "$out/"
    substituteInPlace "$out/share/applications/OpenClaw.desktop" \
      --replace-fail 'Exec=openclaw-desktop' "Exec=$out/bin/openclaw-desktop"
    runHook postInstall
  '';

  preFixup = ''
    gappsWrapperArgs+=(--prefix PATH : ${
      lib.makeBinPath [
        bash
        xdg-utils
      ]
    })
  '';

  meta = {
    description = "Official OpenClaw Linux desktop companion";
    homepage = "https://github.com/openclaw/openclaw/tree/main/apps/linux";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "openclaw-desktop";
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
})
