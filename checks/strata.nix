{ pkgs, src }:
pkgs.runCommand "check-strata-workspace"
  {
    nativeBuildInputs = [
      pkgs.git
      pkgs.nix
      pkgs.python3
    ];
  }
  ''
    export HOME=$TMPDIR/home
    mkdir -p "$HOME"
    python3 ${./strata.py} ${../home-manager/modules/development/strata-workspace.py} ${src}
    touch $out
  ''
