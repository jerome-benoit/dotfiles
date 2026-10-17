{ pkgs, package }:
pkgs.runCommand "check-caveman-runtime"
  {
    nativeBuildInputs = [ pkgs.python3 ];
  }
  ''
    python3 ${./caveman.py} ${package}
    touch "$out"
  ''
