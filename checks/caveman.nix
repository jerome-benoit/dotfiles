{ pkgs, package }:
let
  # Pi supplies TypeBox when loading extensions; use the real module here too.
  typebox = pkgs.fetchzip {
    url = "https://registry.npmjs.org/typebox/-/typebox-1.3.18.tgz";
    hash = "sha256-U998vnfjsMa2RLRI+zYrIScZxTdy+Aj6IeaqF5JTUuw=";
  };
  filteredProfile = pkgs.buildEnv {
    name = "caveman-filtered-profile";
    paths = [ package ];
    pathsToLink = [
      "/bin"
      "/lib"
    ];
  };
  innerProfile = pkgs.buildEnv {
    name = "caveman-inner-profile";
    paths = [ package ];
  };
  nestedProfile = pkgs.buildEnv {
    name = "caveman-nested-profile";
    paths = [ innerProfile ];
    pathsToLink = [
      "/bin"
      "/lib"
    ];
  };
in
pkgs.runCommand "check-caveman-runtime"
  {
    nativeBuildInputs = [ pkgs.python3 ];
    __darwinAllowLocalNetworking = true;
  }
  ''
    CAVEMAN_TEST_SHELL=${pkgs.lib.getExe pkgs.bash} \
      ${pkgs.lib.getExe pkgs.nodejs_22} --test ${package.installerSource}/tests/installer/nix-registration-paths.test.mjs
    python3 ${./caveman.py} ${package} ${pkgs.lib.getExe pkgs.git} ${pkgs.lib.getExe pkgs.nodejs_22} ${package.runtime}/bin/caveman-blocks
    # Keep copies on the build filesystem while forcing the short-state fallback.
    profileTmp="$(mktemp -d "$TMPDIR/caveman-profiles-XXXXXXXX")"
    longTmp="$profileTmp/native-socket-regression-requires-a-temporary-parent-that-exceeds-the-portable-unix-domain-socket-path-limit"
    mkdir "$longTmp"
    TMPDIR="$longTmp" python3 ${./caveman-profiles.py} ${package} ${pkgs.lib.getExe pkgs.git} ${pkgs.lib.getExe pkgs.nodejs_22} ${typebox} ${filteredProfile} ${nestedProfile}
    rmdir "$longTmp" "$profileTmp"
    python3 ${./caveman-installer.py} ${package} ${pkgs.lib.getExe pkgs.nodejs_22} ${pkgs.lib.getExe pkgs.bash} ${package.installerSource.src}
    touch "$out"
  ''
